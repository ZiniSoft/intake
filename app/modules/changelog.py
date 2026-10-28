"""What changed, for the people using the app (FR-UI-14).

The source is CHANGELOG.md at the repository root, written by hand in Vietnamese with every commit. This reads it
into entries: a date heading, an entry heading with the commit hashes in backticks and an optional {cto} mark, a
"Tham chiếu:" line with the FR and ADR codes, and the bullets the user sees.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
HASH = re.compile(r"`([0-9a-f]{7,40})`")
DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
CTO_MARK = "{cto}"


def parse_changelog(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current_date: str | None = None
    entry: dict[str, object] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        date_match = DATE.match(line)
        if date_match:
            current_date = date_match.group(1)
            entry = None
            continue
        if line.startswith("### ") and current_date:
            title = line[4:].strip()
            commits = HASH.findall(title)
            title = HASH.sub("", title)
            cto_only = CTO_MARK in title
            title = " ".join(title.replace(CTO_MARK, "").split())
            entry = {"date": current_date, "title": title, "commits": commits, "refs": [], "bullets": [], "cto_only": cto_only}
            entries.append(entry)
            continue
        if entry is None:
            continue
        if line.lower().startswith("tham chiếu:"):
            entry["refs"] = [part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()]
        elif line.startswith("- "):
            entry["bullets"].append(line[2:].strip())
    return entries


@lru_cache(maxsize=1)
def _load(mtime: float) -> list[dict[str, object]]:
    return parse_changelog(CHANGELOG_PATH.read_text(encoding="utf-8"))


def entries_behind(entries: list[dict[str, object]], running_sha: str | None) -> int | None:
    """How many entries are newer than the build that runs: the entries above the first one carrying its hash.

    None when the running build is unknown (a dev build) or its hash is in no entry (a build older than the log, or
    a branch build): then nothing can be said."""
    sha = (running_sha or "").strip().lower()
    if not sha or sha == "dev":
        return None
    for position, row in enumerate(entries):
        if any(str(commit).startswith(sha) or sha.startswith(str(commit)) for commit in row["commits"]):
            return position
    return None


def changelog(include_cto: bool) -> dict[str, object]:
    settings = get_settings()
    try:
        entries = _load(CHANGELOG_PATH.stat().st_mtime)
    except FileNotFoundError:
        entries = []
    visible = [row for row in entries if include_cto or not row["cto_only"]]
    return {
        "build": {"sha": settings.git_sha or "dev", "built_at": settings.build_time or None},
        "latest": visible[0]["date"] if visible else None,
        "entries": visible,
        # Only the CTO deploys, so only the CTO is told how far the running build is behind (FR-UI-15).
        "behind": entries_behind(entries, settings.git_sha) if include_cto else None,
    }
