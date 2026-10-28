"""Daily encrypted backup of the Intake database and stored files into one folder.

Each backup is a single file, intake-YYYYMMDD-HHMMSS.tar.enc, holding a PostgreSQL dump, every stored
object and a manifest. It is encrypted with BACKUP_PASSPHRASE, so the folder can be synced to a cloud
drive. Nothing is ever written unencrypted to that folder. Restore steps: docs/stable/operations/backup-restore.md
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("intake.backup")

TARGET = Path("/backups")
WORK = Path("/tmp/backup-work")
READY_FILE = Path("/tmp/backup-ready")
LOCAL = ZoneInfo(os.environ.get("BACKUP_TIMEZONE", "Asia/Ho_Chi_Minh"))
RUN_AT = os.environ.get("BACKUP_TIME", "01:30")
KEEP_DAILY = int(os.environ.get("BACKUP_KEEP_DAILY", "7"))
KEEP_WEEKLY = int(os.environ.get("BACKUP_KEEP_WEEKLY", "4"))
MIN_PASSPHRASE = 16
CIPHER = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-pass", "env:BACKUP_PASSPHRASE"]
RETRY_AFTER = timedelta(hours=1)


class BackupError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def psql(sql: str, **values: str) -> str:
    args = ["psql", "-v", "ON_ERROR_STOP=1", "-At"]
    for name, value in values.items():
        args += ["-v", f"{name}={value}"]
    return subprocess.run(args, input=sql, capture_output=True, text=True, check=True).stdout.strip()


def record(started: datetime, status: str, file_name: str | None, size: int, tables: int, objects: int, error: str | None) -> None:
    try:
        psql(
            "INSERT INTO backup_runs (id, status, file_name, size_bytes, table_count, object_count, error_code, started_at, completed_at) "
            "VALUES (gen_random_uuid(), :'status', NULLIF(:'file', ''), :'size', :'tables', :'objects', NULLIF(:'error', ''), :'started', now());"
            "DELETE FROM backup_runs WHERE started_at < now() - interval '90 days';",
            status=status, file=file_name or "", size=str(size), tables=str(tables), objects=str(objects),
            error=error or "", started=started.isoformat(),
        )
    except Exception as exc:  # The backup file itself matters more than its log line.
        logger.error("Backup result could not be recorded: %s", type(exc).__name__)


def dump_database(folder: Path) -> tuple[int, list[str]]:
    subprocess.run(["pg_dump", "--format=custom", "--file", str(folder / "database.dump")], check=True, capture_output=True)
    tables = int(psql("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))
    migrations = psql("SELECT version FROM schema_migrations ORDER BY version").splitlines()
    return tables, migrations


def copy_objects(folder: Path) -> list[dict[str, object]]:
    client = boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"], aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"], region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    bucket = os.environ["S3_BUCKET"]
    listed: list[dict[str, object]] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for entry in page.get("Contents", []):
            # Stored under a numbered name: object keys are free text and must not shape local paths.
            local = folder / "objects" / f"{len(listed):08d}"
            local.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, entry["Key"], str(local))
            listed.append({"key": entry["Key"], "file": local.name, "size": local.stat().st_size, "sha256": sha256(local)})
    return listed


def run_once() -> None:
    started = datetime.now(LOCAL)
    tables, objects = 0, []
    try:
        if len(os.environ.get("BACKUP_PASSPHRASE", "")) < MIN_PASSPHRASE:
            raise BackupError("PASSPHRASE_MISSING")
        if not TARGET.is_dir():
            raise BackupError("TARGET_FOLDER_MISSING")
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir(parents=True)
        tables, migrations = dump_database(WORK)
        objects = copy_objects(WORK)
        manifest = {
            "created_at": started.isoformat(), "format": 1,
            "database": {"file": "database.dump", "sha256": sha256(WORK / "database.dump"), "tables": tables, "migrations": migrations},
            "bucket": os.environ["S3_BUCKET"], "objects": objects,
        }
        (WORK / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

        name = f"intake-{started:%Y%m%d-%H%M%S}.tar.enc"
        partial = TARGET / f"{name}.partial"
        with partial.open("wb") as out:
            tar = subprocess.Popen(["tar", "-cf", "-", "-C", str(WORK), "."], stdout=subprocess.PIPE)
            enc = subprocess.run([*CIPHER, "-salt"], stdin=tar.stdout, stdout=out)
            if tar.wait() != 0 or enc.returncode != 0:
                raise BackupError("ARCHIVE_FAILED")
        # A backup counts only after it has been decrypted and listed again.
        with partial.open("rb") as source:
            dec = subprocess.Popen([*CIPHER, "-d"], stdin=source, stdout=subprocess.PIPE)
            listing = subprocess.run(["tar", "-tf", "-"], stdin=dec.stdout, capture_output=True, text=True)
            if dec.wait() != 0 or listing.returncode != 0:
                raise BackupError("VERIFY_FAILED")
        names = {line.strip("./") for line in listing.stdout.splitlines()}
        if "database.dump" not in names or "manifest.json" not in names or sum(1 for n in names if n.startswith("objects/") and n != "objects/") != len(objects):
            raise BackupError("VERIFY_INCOMPLETE")
        final = TARGET / name
        partial.rename(final)
        (TARGET / f"{name}.sha256").write_text(f"{sha256(final)}  {name}\n", encoding="utf-8")
        prune()
        record(started, "DONE", name, final.stat().st_size, tables, len(objects), None)
        READY_FILE.touch()
        logger.info("Backup %s written: %s bytes, %s tables, %s objects", name, final.stat().st_size, tables, len(objects))
    except Exception as exc:
        code = exc.code if isinstance(exc, BackupError) else type(exc).__name__
        for leftover in TARGET.glob("*.partial") if TARGET.is_dir() else []:
            leftover.unlink(missing_ok=True)
        READY_FILE.unlink(missing_ok=True)
        record(started, "FAILED", None, 0, tables, len(objects), code)
        logger.error("Backup failed: %s", code)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


def backups() -> list[Path]:
    return sorted(TARGET.glob("intake-*.tar.enc"), reverse=True)


def taken_at(path: Path) -> datetime:
    return datetime.strptime(path.name[len("intake-"):len("intake-") + 15], "%Y%m%d-%H%M%S").replace(tzinfo=LOCAL)


def prune() -> None:
    """Keep the newest KEEP_DAILY backups and the newest backup of each of the last KEEP_WEEKLY weeks."""
    files = backups()
    keep = set(files[:KEEP_DAILY])
    weeks: dict[tuple[int, int], Path] = {}
    for path in files:
        weeks.setdefault(tuple(taken_at(path).isocalendar()[:2]), path)
    keep.update(list(weeks.values())[:KEEP_WEEKLY])
    for path in files:
        if path not in keep:
            path.unlink(missing_ok=True)
            Path(f"{path}.sha256").unlink(missing_ok=True)
            logger.info("Old backup removed: %s", path.name)


def due(now: datetime, last_try: datetime | None) -> bool:
    if last_try is not None and now - last_try < RETRY_AFTER:
        return False
    files = backups() if TARGET.is_dir() else []
    newest = taken_at(files[0]) if files else None
    if newest is None or now - newest > timedelta(hours=24):
        return True
    hour, minute = (int(part) for part in RUN_AT.split(":"))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= scheduled and newest < scheduled


def main() -> None:
    if os.environ.get("BACKUP_RUN_ONCE") == "1":
        run_once()
        raise SystemExit(0 if READY_FILE.exists() else 1)
    last_try: datetime | None = None
    while True:
        now = datetime.now(LOCAL)
        if due(now, last_try):
            last_try = now
            run_once()
        time.sleep(60)


if __name__ == "__main__":
    main()
