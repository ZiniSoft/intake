English | [Tiếng Việt](backup-restore.vi.md)

# Backup and restore 1.3

## 1. Objectives

- RPO: at most 24 hours.
- RTO: at most 4 hours.
- Backups are stored on a different machine from the workstation/SSD running Intake.

## 2. Backup scope

- PostgreSQL logical dump including schema and data.
- SeaweedFS master/filer metadata, volume data and the required S3 config.
- Configuration files without secrets, or secrets backed up through a separate encrypted channel.
- Manifest including the application version, image digest, migration version and backup checksum.
- The manifest must record the documentation baseline, the list of versions in `schema_migrations` and the count of the 33 current tables, to detect a restore with a mismatched schema.

Redis does not need to be backed up as a business data source; outbox/job state lives in PostgreSQL.

## 3. Pilot schedule

- PostgreSQL: daily.
- SeaweedFS: daily, or incremental depending on the chosen backup tool.
- Minimum retention: 7 daily + 4 weekly during the pilot.
- A failed backup job must raise an alert; a file that exists but whose checksum has not been verified does not count as a successful backup.

## 4. Restore drill

1. Create an isolated restore environment.
2. Restore PostgreSQL and SeaweedFS from the same recovery point.
3. Start the app with a compatible image/migration.
4. Check the counts of project/intake/source/attachment and the checksums of random objects.
5. Run the smoke flow: login, list, detail and downloading an allowed attachment.
6. Run the Planning read smoke: workforce, capacity, one run without external writes and the GitLab read-model count.
7. Measure the time of the latest backup and the total restore time.
8. Save redacted evidence in the gate report.

The drill fails if a DB-object link is lost, RPO/RTO is exceeded, or a step not written in the runbook is needed.

## 5. Encryption and access

Backups containing Restricted data must be encrypted at rest; only the CTO can decrypt them during the pilot. The recovery key is not stored on the same machine or in the same folder as the backups.

### Trust boundary of the restore file

- The `backup` container builds an archive from the running PostgreSQL and bucket and writes it to `BACKUP_DIR`. The CTO syncs this folder to Google Drive, picks the file and runs the restore command; no API or application user can start a restore.
- The synced folder, the cloud account, the host and anyone with Docker access can replace or choose the archive. The `.sha256` file next to the archive only detects copy errors; it does not authenticate the creator and is not a signature. Therefore the restore treats the tar and `manifest.json` as untrusted data even when decryption succeeds.
- `BACKUP_PASSPHRASE` lives in `.env`, is passed by Docker Compose into the `backup` container, and must have a separate recovery copy outside the backup folder. The host administrator, anyone who can read `.env` or control Docker/containers can obtain the key. These permissions are already equivalent to sensitive operations permissions and must be limited to the CTO.
- The `backup` image currently runs the restore command as root inside the container. The container has PostgreSQL credentials sufficient to replace the database, S3 credentials sufficient to write the configured bucket, a read/write `/backups` mount and the two internal networks `backend` and `storage`; it has no Internet route. Root inside the container is not automatically root on the host, but it can modify files in the bind mount according to the mount permissions.
- The allowed object namespace is the target environment's `S3_BUCKET` bucket with normalized relative keys. Absolute keys, `.` or `..` components, Windows separators, control characters and duplicate keys are rejected before upload.

The restore decrypts into a tar stream and writes each member itself. Only directories and regular files inside `/tmp/restore-work` are accepted; symlinks, hard links, devices, FIFOs, absolute paths, path traversal, duplicate names and ambiguous separators are all rejected. Every path specified by the manifest is resolved again under the corresponding directory, must not contain links and must be a regular file with exactly one hard link before `pg_restore` or the upload reads the file.

## 6. Pilot tooling (ADR-0025)

Configuration in `.env`:

| Variable | Meaning |
|---|---|
| `BACKUP_DIR` | Folder on the machine running Intake that receives backup files. Point it at a folder synced to Google Drive. |
| `BACKUP_PASSPHRASE` | At least 16 characters. Leave it empty to disable backups. |
| `BACKUP_TIME` | Daily run time, Vietnam time, default `01:30`. |
| `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY` | Number of copies kept, default 7 and 4. |

After editing `.env`: `docker compose up -d backup`. Run one backup right away: `docker compose run --rm -e BACKUP_RUN_ONCE=1 backup`.

Keep these somewhere other than the backup folder (for example a password manager): the passphrase and a copy of `.env`. Without the passphrase the file cannot be opened; without `SECRET_KEY` in `.env` the encrypted original content in the database cannot be read.

### Restore

One command, run on a machine that has the source code, `.env` (with the same `SECRET_KEY` and `BACKUP_PASSPHRASE` as the old machine) and Docker:

1. Start empty infrastructure: `docker compose up -d postgres seaweed-master seaweed-volume seaweed-filer seaweed-s3`.
2. Copy the `intake-....tar.enc` file and the `.sha256` file into the `BACKUP_DIR` folder.
3. `docker compose run --rm backup python3 /opt/restore.py intake-YYYYMMDD-HHMMSS.tar.enc`
4. `docker compose up -d`, then check according to section 4 (login, list, detail, download an attachment, play back a meeting recording).

The command in step 3 checks the checksum, decrypts, matches each component against the manifest, replaces the whole database with the copy in the file, reloads every stored file (creating the bucket if it does not exist) and prints the row counts of the main tables. It refuses to run when the target database already contains Intake, unless `--overwrite` is added.

On 2026-10-06 this command was run with a real backup into a temporary database and bucket on the pilot stack: 42 tables, 17 files, row counts matching the live data; the cases of a wrong passphrase, a missing file and a database that already has data were all correctly rejected. Not done yet: starting the application on the restored copy on a different machine.
