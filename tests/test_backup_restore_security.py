"""Untrusted backup archives cannot escape the restore work area."""
from __future__ import annotations

import importlib.util
import io
import os
import tarfile
from pathlib import Path

import pytest


RESTORE_PATH = Path(__file__).parents[1] / "ops" / "backup" / "restore.py"
SPEC = importlib.util.spec_from_file_location("intake_backup_restore", RESTORE_PATH)
assert SPEC is not None and SPEC.loader is not None
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


def _tar(*members: tuple[str, bytes | None, bytes | None]) -> io.BytesIO:
    """Build members as (name, content, link_type); None content means a directory."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content, link_type in members:
            info = tarfile.TarInfo(name)
            if link_type is not None:
                info.type = link_type
                info.linkname = "../outside"
            elif content is None:
                info.type = tarfile.DIRTYPE
            else:
                info.size = len(content)
            archive.addfile(info, io.BytesIO(content) if content is not None and link_type is None else None)
    stream.seek(0)
    return stream


def test_extract_archive_accepts_only_normal_backup_files(tmp_path: Path) -> None:
    stream = _tar(
        ("./", None, None),
        ("./objects", None, None),
        ("./database.dump", b"database", None),
        ("./manifest.json", b"{}", None),
        ("./objects/00000000", b"object", None),
    )

    restore.extract_archive(stream, tmp_path)

    assert (tmp_path / "database.dump").read_bytes() == b"database"
    assert (tmp_path / "objects" / "00000000").read_bytes() == b"object"


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "objects/../../outside",
        "/absolute",
        "C:/windows-absolute",
        "objects\\windows-separator",
        "objects//empty-segment",
    ],
)
def test_extract_archive_rejects_escaping_and_ambiguous_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(restore.RestoreValidationError):
        restore.extract_archive(_tar((name, b"bad", None)), tmp_path)

    assert not (tmp_path.parent / "outside").exists()


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_extract_archive_rejects_symbolic_and_hard_links(tmp_path: Path, link_type: bytes) -> None:
    stream = _tar(("objects/link", None, link_type))

    with pytest.raises(restore.RestoreValidationError, match="not a regular file"):
        restore.extract_archive(stream, tmp_path)


def test_extract_archive_rejects_link_chains_before_following_them(tmp_path: Path) -> None:
    stream = _tar(
        ("objects/first", None, tarfile.SYMTYPE),
        ("objects/second", None, tarfile.SYMTYPE),
        ("objects/file", b"bad", None),
    )

    with pytest.raises(restore.RestoreValidationError, match="not a regular file"):
        restore.extract_archive(stream, tmp_path)


def test_extract_archive_rejects_duplicate_members(tmp_path: Path) -> None:
    stream = _tar(("database.dump", b"first", None), ("database.dump", b"second", None))

    with pytest.raises(restore.RestoreValidationError, match="duplicate archive member"):
        restore.extract_archive(stream, tmp_path)


@pytest.mark.parametrize(
    "key",
    ["../outside", "/absolute", "C:/windows-absolute", "a\\b", "a/../b", "./prefixed", "a//b", "bad\nkey"],
)
def test_object_keys_must_stay_in_the_normalized_bucket_namespace(key: str) -> None:
    with pytest.raises(restore.RestoreValidationError):
        restore.object_key(key)


def test_manifest_paths_must_be_contained_regular_files(tmp_path: Path) -> None:
    (tmp_path / "objects").mkdir()
    database = tmp_path / "database.dump"
    database.write_bytes(b"database")
    object_file = tmp_path / "objects" / "00000000"
    object_file.write_bytes(b"object")
    manifest = {
        "database": {"file": "database.dump", "sha256": "a" * 64, "tables": 1},
        "objects": [{"file": "00000000", "key": "attachments/example", "size": 6, "sha256": "b" * 64}],
    }

    checked_database, database_path, objects = restore.validate_manifest(manifest, tmp_path)

    assert checked_database is manifest["database"]
    assert database_path == database
    assert objects == [(manifest["objects"][0], object_file, "attachments/example")]


@pytest.mark.parametrize("file_name", ["../outside", "/absolute", "C:/windows-absolute", "a\\b"])
def test_manifest_database_path_cannot_escape(tmp_path: Path, file_name: str) -> None:
    manifest = {"database": {"file": file_name, "sha256": "a" * 64}, "objects": []}

    with pytest.raises(restore.RestoreValidationError):
        restore.validate_manifest(manifest, tmp_path)


def test_manifest_rejects_files_with_multiple_hard_links(tmp_path: Path) -> None:
    database = tmp_path / "database.dump"
    database.write_bytes(b"database")
    os.link(database, tmp_path / "database-copy.dump")
    manifest = {"database": {"file": "database.dump", "sha256": "a" * 64}, "objects": []}

    with pytest.raises(restore.RestoreValidationError, match="non-linked file"):
        restore.validate_manifest(manifest, tmp_path)


def test_manifest_rejects_symlinked_object_files(tmp_path: Path) -> None:
    (tmp_path / "objects").mkdir()
    (tmp_path / "database.dump").write_bytes(b"database")
    outside = tmp_path / "outside"
    outside.write_bytes(b"object")
    try:
        (tmp_path / "objects" / "00000000").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    manifest = {
        "database": {"file": "database.dump", "sha256": "a" * 64},
        "objects": [{"file": "00000000", "key": "attachments/example", "size": 6, "sha256": "b" * 64}],
    }

    with pytest.raises(restore.RestoreValidationError, match="must not contain links"):
        restore.validate_manifest(manifest, tmp_path)


def test_manifest_rejects_duplicate_object_keys(tmp_path: Path) -> None:
    (tmp_path / "objects").mkdir()
    (tmp_path / "database.dump").write_bytes(b"database")
    (tmp_path / "objects" / "00000000").write_bytes(b"first")
    (tmp_path / "objects" / "00000001").write_bytes(b"second")
    manifest = {
        "database": {"file": "database.dump", "sha256": "a" * 64},
        "objects": [
            {"file": "00000000", "key": "attachments/example", "size": 5, "sha256": "b" * 64},
            {"file": "00000001", "key": "attachments/example", "size": 6, "sha256": "c" * 64},
        ],
    }

    with pytest.raises(restore.RestoreValidationError, match="duplicate object key"):
        restore.validate_manifest(manifest, tmp_path)
