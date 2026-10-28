"""Evidence behind "done" (FR-PLAN-36, ADR-0065).

Beside the traces the read model finds on its own (commits and merge requests that name the Issue), people attach
their own: the worker when reporting done, the agent through log_work, the acceptor before confirming. A link is one
of three kinds: COMMIT, MR (code work) or LINK (a document, a video, a picture, anything that is not code). The rule
that says whether an Issue has enough is fixed here and the same on every screen; nothing here calls out.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import GitLabIssueSnapshot, IssueEvidenceLink, User, WorkforceMember
from app.modules.planning.gitlab_read_model import DONE_EVIDENCE_MR

KINDS = ("COMMIT", "MR", "LINK")
SOURCES = ("WORKER", "ACCEPTOR", "AGENT", "WORK_LOG", "REPORT")
MAX_LINKS = 10
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
COMMIT_PATH = re.compile(r"/(-/)?commits?/[0-9a-f]{7,40}", re.IGNORECASE)
MR_PATH = re.compile(r"/(-/)?(merge_requests|pull)/\d+", re.IGNORECASE)


class EvidenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def kind_of_url(url: str) -> str:
    """What a pasted address is, from its shape: a commit page, a merge request, or anything else."""
    if COMMIT_PATH.search(url):
        return "COMMIT"
    if MR_PATH.search(url):
        return "MR"
    return "LINK"


def repo_base(issue_web_url: str | None) -> str | None:
    """The repository's web address, from the Issue's: GitLab `.../-/issues/7` or GitHub `.../issues/7`."""
    if not issue_web_url:
        return None
    match = re.match(r"^(https?://[^\s]+?)/(-/)?issues/\d+", issue_web_url.strip())
    return match.group(1).rstrip("/") if match else None


def commit_url(issue_web_url: str | None, sha: str) -> str | None:
    base = repo_base(issue_web_url)
    if not base or not re.fullmatch(r"[0-9a-f]{7,40}", sha, re.IGNORECASE):
        return None
    return f"{base}/-/commit/{sha}" if "/-/" in (issue_web_url or "") else f"{base}/commit/{sha}"


def urls_in(text: str | None) -> list[str]:
    return [match.group(0).rstrip(".,;") for match in URL.finditer(text or "")]


def clean_links(links: list[dict] | None, *, issue_web_url: str | None = None) -> list[dict]:
    """Validate what a person or an agent hands in; code links must point at the project's own repository when the
    repository is known."""
    out: list[dict] = []
    base = repo_base(issue_web_url)
    for raw in (links or [])[:MAX_LINKS]:
        if not isinstance(raw, dict):
            continue
        url = " ".join(str(raw.get("url") or "").split())
        ref = " ".join(str(raw.get("ref") or "").split())[:200]
        note = " ".join(str(raw.get("note") or "").split())[:300]
        kind = str(raw.get("kind") or "").upper()
        if url and not url.lower().startswith(("http://", "https://")):
            raise EvidenceError("EVIDENCE_URL_INVALID", "Link phải bắt đầu bằng http:// hoặc https://")
        if len(url) > 1000:
            raise EvidenceError("EVIDENCE_URL_INVALID", "Link quá dài")
        if kind not in KINDS:
            kind = kind_of_url(url) if url else ("COMMIT" if ref else "LINK")
        if not url and not ref:
            continue
        if kind in ("COMMIT", "MR") and url and base and not url.lower().startswith(base.lower() + "/"):
            raise EvidenceError("EVIDENCE_WRONG_REPO", f"Link {kind} phải trỏ về repo của dự án ({base})")
        out.append({"kind": kind, "url": url or None, "ref": ref or None, "note": note or None})
    return out


def add_links(session, project_id: str, issue_id: str, links: list[dict], *, source: str, actor_id: str | None = None,
              member_id: str | None = None, issue_web_url: str | None = None) -> int:
    """Keep each new link once per Issue; the same address or commit twice is one line."""
    if source not in SOURCES:
        raise EvidenceError("EVIDENCE_SOURCE_UNKNOWN", "source")
    cleaned = clean_links(links, issue_web_url=issue_web_url)
    if not cleaned:
        return 0
    existing = session.scalars(select(IssueEvidenceLink).where(IssueEvidenceLink.project_id == project_id, IssueEvidenceLink.issue_external_id == issue_id)).all()
    seen = {(row.url or "").lower() for row in existing if row.url} | {(row.ref or "").lower() for row in existing if row.ref and not row.url}
    now = datetime.now(timezone.utc)
    added = 0
    for link in cleaned:
        key = (link["url"] or link["ref"] or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        session.add(IssueEvidenceLink(
            id=str(uuid4()), project_id=project_id, issue_external_id=issue_id, kind=link["kind"], url=link["url"], ref=link["ref"], note=link["note"],
            source=source, added_by=actor_id, member_id=member_id, created_at=now,
        ))
        added += 1
    return added


def links_for(session, project_id: str, issue_id: str) -> list[dict]:
    rows = session.scalars(select(IssueEvidenceLink).where(
        IssueEvidenceLink.project_id == project_id, IssueEvidenceLink.issue_external_id == issue_id,
    ).order_by(IssueEvidenceLink.created_at)).all()
    out = []
    for row in rows:
        who = None
        if row.member_id:
            member = session.get(WorkforceMember, row.member_id)
            who = member.display_name if member else None
        if not who and row.added_by:
            user = session.get(User, row.added_by)
            who = (user.display_name or user.auth_subject) if user else None
        out.append({"id": str(row.id), "kind": row.kind, "url": row.url, "ref": row.ref, "note": row.note, "source": row.source, "added_by_name": who, "created_at": row.created_at})
    return out


def assess(rule: str, auto: dict | None, links: list[dict]) -> dict[str, object]:
    """Is there enough behind "done"? Code work (traces or a commit/MR link) is judged by the project's rule; other
    work needs one link; nothing at all is MISSING. The words say why, for the card."""
    auto = auto or {}
    commits, mrs, merged, pipeline = int(auto.get("commits") or 0), int(auto.get("merge_requests") or 0), int(auto.get("merged") or 0), auto.get("pipeline")
    code_links = [link for link in links if link.get("kind") in ("COMMIT", "MR")]
    doc_links = [link for link in links if link.get("kind") == "LINK"]
    is_code = commits > 0 or mrs > 0 or bool(code_links)
    if is_code:
        if rule == DONE_EVIDENCE_MR:
            mr_links = [link for link in code_links if link.get("kind") == "MR"]
            if (merged > 0 and pipeline != "failed") or mr_links:
                return {"work": "CODE", "status": "OK", "why": "MR đã merge" if merged > 0 else "có link MR"}
            if pipeline == "failed":
                return {"work": "CODE", "status": "WEAK", "why": "pipeline đỏ; quy tắc dự án cần MR đã merge và pipeline không hỏng"}
            return {"work": "CODE", "status": "WEAK", "why": "có commit nhưng quy tắc dự án cần MR đã merge; dán link MR nếu đã merge"}
        return {"work": "CODE", "status": "OK", "why": "có commit hoặc MR nhắc Issue" if (commits or mrs) else "có link commit hoặc MR"}
    if doc_links:
        return {"work": "OTHER", "status": "OK", "why": f"{len(doc_links)} link minh họa"}
    return {"work": "UNKNOWN", "status": "MISSING", "why": "chưa có commit, MR hay link nào"}


def links_from_text(text: str | None, issue_web_url: str | None) -> list[dict]:
    """Addresses a person wrote in a report line, typed by their shape."""
    return [{"kind": kind_of_url(url), "url": url} for url in urls_in(text)]


def snapshot_url(session, project_id: str, issue_id: str) -> str | None:
    row = session.scalar(select(GitLabIssueSnapshot).where(
        GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue_id, GitLabIssueSnapshot.is_current.is_(True),
    ))
    return row.web_url if row is not None else None
