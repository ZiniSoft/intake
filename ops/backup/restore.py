"""Restore one backup file into this installation: the database and every stored file.

    docker compose run --rm backup python3 /opt/restore.py intake-YYYYMMDD-HHMMSS.tar.enc

The file is looked for in BACKUP_DIR (/backups in the container) and opened with BACKUP_PASSPHRASE.
Everything in the target database is replaced. A database that already holds Intakes is refused unless
--overwrite is given, so a restore cannot wipe a running system by accident.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

TARGET = Path("/backups")
WORK = Path("/tmp/restore-work")
CIPHER = ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-pass", "env:BACKUP_PASSPHRASE"]
COUNTED = ("projects", "users", "intake_items", "email_messages", "meetings", "planning_runs")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RestoreValidationError(ValueError):
    """The decrypted archive or its manifest violates the restore format."""


def stop(message: str) -> None:
    print(f"Restore stopped: {message}")
    shutil.rmtree(WORK, ignore_errors=True)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_name(value: object, label: str, *, allow_tar_prefix: bool = False) -> PurePosixPath:
    """Return one portable relative path and reject ambiguous path syntax."""
    if not isinstance(value, str) or not value:
        raise RestoreValidationError(f"{label} must be a non-empty string")
    if "\\" in value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise RestoreValidationError(f"{label} contains forbidden characters")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise RestoreValidationError(f"{label} must be relative")
    if value.startswith("./") and not allow_tar_prefix:
        raise RestoreValidationError(f"{label} is not normalized")
    while allow_tar_prefix and value.startswith("./"):
        value = value[2:]
    parts = value.split("/")
    if not value or any(part in {"", ".", ".."} for part in parts):
        raise RestoreValidationError(f"{label} is not a normalized relative path")
    return PurePosixPath(*parts)


def contained_path(root: Path, relative: PurePosixPath, label: str) -> Path:
    root = root.resolve()
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise RestoreValidationError(f"{label} escapes the restore directory") from exc
    return candidate


def extract_archive(stream: BinaryIO, root: Path) -> None:
    """Extract regular files from a tar stream without following archive links."""
    root = root.resolve()
    seen: set[PurePosixPath] = set()
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in archive:
            if member.name in {".", "./"} and member.isdir():
                continue
            relative = relative_name(member.name, "archive member", allow_tar_prefix=True)
            target = contained_path(root, relative, "archive member")
            if relative in seen:
                raise RestoreValidationError(f"duplicate archive member: {relative}")
            seen.add(relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise RestoreValidationError(f"archive member is not a regular file: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise RestoreValidationError(f"archive member would overwrite another path: {relative}")
            source = archive.extractfile(member)
            if source is None:
                raise RestoreValidationError(f"archive member cannot be read: {relative}")
            with source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)


def regular_file(root: Path, value: object, label: str) -> Path:
    """Resolve a manifest path under root and require a real, regular file."""
    relative = relative_name(value, label)
    current = root.resolve()
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RestoreValidationError(f"{label} must not contain links")
    candidate = contained_path(root, relative, label)
    try:
        file_stat = candidate.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise RestoreValidationError(f"{label} does not exist") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise RestoreValidationError(f"{label} must be one regular, non-linked file")
    return candidate


def object_key(value: object) -> str:
    """Keep restored objects inside the configured bucket's normalized namespace."""
    return relative_name(value, "object key").as_posix()


def checked_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RestoreValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_manifest(manifest: object, root: Path) -> tuple[dict[str, object], Path, list[tuple[dict[str, object], Path, str]]]:
    if not isinstance(manifest, dict):
        raise RestoreValidationError("manifest must be a JSON object")
    database = manifest.get("database")
    objects = manifest.get("objects")
    if not isinstance(database, dict) or not isinstance(objects, list):
        raise RestoreValidationError("manifest database and objects sections are invalid")
    database_path = regular_file(root, database.get("file"), "database file")
    checked_sha256(database.get("sha256"), "database checksum")
    checked_objects: list[tuple[dict[str, object], Path, str]] = []
    keys: set[str] = set()
    for index, entry in enumerate(objects):
        if not isinstance(entry, dict):
            raise RestoreValidationError(f"object {index} must be a JSON object")
        path = regular_file(root / "objects", entry.get("file"), f"object {index} file")
        key = object_key(entry.get("key"))
        if key in keys:
            raise RestoreValidationError(f"duplicate object key: {key}")
        keys.add(key)
        checked_sha256(entry.get("sha256"), f"object {index} checksum")
        size = entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RestoreValidationError(f"object {index} size must be a non-negative integer")
        checked_objects.append((entry, path, key))
    return database, database_path, checked_objects


def psql(sql: str) -> str:
    return subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-At", "-c", sql], capture_output=True, text=True, check=True).stdout.strip()


def rows(table: str) -> int:
    try:
        return int(psql(f"SELECT count(*) FROM {table}"))
    except subprocess.CalledProcessError:
        return 0  # the table does not exist yet: an empty installation


def main() -> None:
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    overwrite = "--overwrite" in sys.argv
    if len(names) != 1:
        stop("name exactly one backup file, for example intake-20261006-104017.tar.enc")
    source = TARGET / Path(names[0]).name
    if not source.is_file():
        stop(f"{source.name} is not in the backup folder (BACKUP_DIR)")
    if not os.environ.get("BACKUP_PASSPHRASE"):
        stop("BACKUP_PASSPHRASE is not set; it must be the passphrase the backup was made with")

    checksum = Path(f"{source}.sha256")
    if checksum.is_file():
        if checksum.read_text(encoding="utf-8").split()[0] != sha256(source):
            stop("the file does not match its .sha256; it was damaged or not copied completely")
        print("1/5 File is complete (checksum matches)")
    else:
        print("1/5 No .sha256 next to the file; its completeness is checked through the manifest instead")

    existing = rows("intake_items")
    if existing > 0 and not overwrite:
        stop(f"this database already holds {existing} Intakes. Add --overwrite to replace everything in it")

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    with source.open("rb") as handle:
        opened = subprocess.Popen(CIPHER, stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            if opened.stdout is None:
                raise RestoreValidationError("the decryptor did not provide an archive stream")
            extract_archive(opened.stdout, WORK)
        except (OSError, tarfile.TarError, RestoreValidationError) as exc:
            opened.kill()
            opened.wait()
            stop(f"the archive is unsafe or invalid: {exc}")
        finally:
            if opened.stdout is not None:
                opened.stdout.close()
        if opened.wait() != 0:
            stop("the file could not be opened. The passphrase is wrong, or this is not an Intake backup")
    try:
        manifest_path = regular_file(WORK, "manifest.json", "manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        database, database_path, objects = validate_manifest(manifest, WORK)
    except (OSError, UnicodeError, json.JSONDecodeError, RestoreValidationError) as exc:
        stop(f"the manifest is unsafe or invalid: {exc}")
    if sha256(database_path) != database["sha256"]:
        stop("the database dump inside the backup is damaged")
    damaged = [key for entry, path, key in objects if sha256(path) != entry["sha256"]]
    if damaged:
        stop(f"{len(damaged)} stored file(s) inside the backup are damaged")
    created_at = manifest.get("created_at")
    tables = database.get("tables")
    if not isinstance(created_at, str) or not isinstance(tables, int) or isinstance(tables, bool) or tables < 0:
        stop("the manifest is unsafe or invalid: backup metadata has invalid types")
    print(f"2/5 Backup of {created_at[:16]} opened: {tables} tables, {len(objects)} stored files")

    restored = subprocess.run(
        ["pg_restore", "--no-owner", "--clean", "--if-exists", "--exit-on-error", "--dbname", os.environ["PGDATABASE"], str(database_path)],
        capture_output=True, text=True,
    )
    if restored.returncode != 0:
        stop(f"the database was not restored: {restored.stderr.strip().splitlines()[-1] if restored.stderr.strip() else 'pg_restore failed'}")
    print("3/5 Database restored: " + ", ".join(f"{table} {rows(table)}" for table in COUNTED))

    client = boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"], aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"], region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    bucket = os.environ["S3_BUCKET"]
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
    for entry, path, key in objects:
        client.upload_file(str(path), bucket, key)
    print(f"4/5 Stored files restored: {len(objects)}")

    # Read a few back, so a silent storage failure does not pass as a restore.
    for entry, _path, key in objects[:5]:
        if client.head_object(Bucket=bucket, Key=key)["ContentLength"] != entry["size"]:
            stop(f"a stored file came back with the wrong size after upload: {key}")
    migrations = psql("SELECT count(*) FROM schema_migrations")
    print(f"5/5 Verified. {migrations} migrations recorded. Start the application: docker compose up -d")
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
