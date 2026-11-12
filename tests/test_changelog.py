"""The "what's new" list read from CHANGELOG.md, and the build that is running (FR-UI-14)."""
from fastapi.testclient import TestClient

from app.main import app
from app.modules.changelog import CHANGELOG_EN_PATH, CHANGELOG_PATH, parse_changelog

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})

SAMPLE = """# Nhật ký thay đổi

Lời dẫn không phải mục.

## 2026-10-12

### Nút "Có gì mới" trên thanh trên cùng
Tham chiếu: FR-UI-14
- Bấm biểu tượng tia sáng cạnh chuông.

### Không gian riêng thành bàn làm việc nội dung {cto} `cf14535` `3101b00`
Tham chiếu: FR-CNT-16, ADR-0043
- Trụ nội dung, kế hoạch tuần.
- Giọng bốn lớp.

## 2026-10-10

### Dự án xếp A-Z `6fb8dd9`
- Ô chọn dự án theo tên.
"""


def test_the_file_is_read_into_dated_entries_with_commits_refs_and_bullets() -> None:
    entries = parse_changelog(SAMPLE)
    assert [row["date"] for row in entries] == ["2026-10-12", "2026-10-12", "2026-10-10"]
    first, private, last = entries
    assert first["title"] == 'Nút "Có gì mới" trên thanh trên cùng' and first["commits"] == [] and first["refs"] == ["FR-UI-14"] and first["cto_only"] is False
    assert private["title"] == "Không gian riêng thành bàn làm việc nội dung" and private["commits"] == ["cf14535", "3101b00"]
    assert private["cto_only"] is True and private["refs"] == ["FR-CNT-16", "ADR-0043"] and len(private["bullets"]) == 2
    assert last["commits"] == ["6fb8dd9"] and last["refs"] == [] and last["bullets"] == ["Ô chọn dự án theo tên."]


def test_english_reference_lines_are_parsed() -> None:
    entries = parse_changelog("""## 2026-11-11
### English entry `abcdef0`
References: FR-UI-14, ADR-0078
- English bullet.
""")
    assert entries[0]["refs"] == ["FR-UI-14", "ADR-0078"]
    assert entries[0]["bullets"] == ["English bullet."]


def test_the_real_changelog_parses_and_the_cto_sees_private_entries_the_owner_does_not() -> None:
    assert CHANGELOG_PATH.exists()
    entries = parse_changelog(CHANGELOG_PATH.read_text(encoding="utf-8"))
    assert len(entries) >= 3 and all(row["date"] and row["title"] for row in entries)
    assert entries == sorted(entries, key=lambda row: row["date"], reverse=True), "newest first, as the file is written"

    shown = cto.get("/api/v1/changelog")
    assert shown.status_code == 200, shown.text
    data = shown.json()["data"]
    assert data["build"]["sha"] and data["latest"] == entries[0]["date"]
    assert any(row["cto_only"] for row in data["entries"])
    theirs = owner.get("/api/v1/changelog").json()["data"]
    assert theirs["entries"] and not any(row["cto_only"] for row in theirs["entries"])
    assert TestClient(app).get("/api/v1/changelog").status_code in (401, 403)


def test_the_changelog_api_returns_english_entries_when_requested() -> None:
    assert CHANGELOG_EN_PATH.exists()
    english = parse_changelog(CHANGELOG_EN_PATH.read_text(encoding="utf-8"))
    assert len(english) >= 10

    shown = cto.get("/api/v1/changelog?lang=en")
    assert shown.status_code == 200, shown.text
    data = shown.json()["data"]
    assert data["latest"] == english[0]["date"]
    assert data["entries"][0]["title"] == english[0]["title"]
    assert not any(character in data["entries"][0]["title"] for character in "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯàáâãèéêìíòóôõùúăđĩũơư")

    assert cto.get("/api/v1/changelog?lang=fr").status_code == 422
