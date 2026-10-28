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
import shutil
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

TARGET = Path("/backups")
WORK = Path("/tmp/restore-work")
CIPHER = ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-pass", "env:BACKUP_PASSPHRASE"]
COUNTED = ("projects", "users", "intake_items", "email_messages", "meetings", "planning_runs")


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
        unpacked = subprocess.run(["tar", "-xf", "-", "-C", str(WORK)], stdin=opened.stdout, capture_output=True)
        if opened.wait() != 0 or unpacked.returncode != 0:
            stop("the file could not be opened. The passphrase is wrong, or this is not an Intake backup")
    manifest = json.loads((WORK / "manifest.json").read_text(encoding="utf-8"))
    if sha256(WORK / manifest["database"]["file"]) != manifest["database"]["sha256"]:
        stop("the database dump inside the backup is damaged")
    damaged = [entry["key"] for entry in manifest["objects"] if sha256(WORK / "objects" / entry["file"]) != entry["sha256"]]
    if damaged:
        stop(f"{len(damaged)} stored file(s) inside the backup are damaged")
    print(f"2/5 Backup of {manifest['created_at'][:16]} opened: {manifest['database']['tables']} tables, {len(manifest['objects'])} stored files")

    restored = subprocess.run(
        ["pg_restore", "--no-owner", "--clean", "--if-exists", "--exit-on-error", "--dbname", os.environ["PGDATABASE"], str(WORK / manifest["database"]["file"])],
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
    for entry in manifest["objects"]:
        client.upload_file(str(WORK / "objects" / entry["file"]), bucket, entry["key"])
    print(f"4/5 Stored files restored: {len(manifest['objects'])}")

    # Read a few back, so a silent storage failure does not pass as a restore.
    for entry in manifest["objects"][:5]:
        if client.head_object(Bucket=bucket, Key=entry["key"])["ContentLength"] != entry["size"]:
            stop(f"a stored file came back with the wrong size after upload: {entry['key']}")
    migrations = psql("SELECT count(*) FROM schema_migrations")
    print(f"5/5 Verified. {migrations} migrations recorded. Start the application: docker compose up -d")
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
