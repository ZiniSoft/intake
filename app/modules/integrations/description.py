"""The body of a work item made from an approved request: the summary, then what a developer needs to start (ADR-0032).

Every part is optional. Parts the request did not give are left out rather than filled with boilerplate.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select

from app.models import GitLabIssueSnapshot


# How many new questions an analysis may raise once the team has already answered a first round.
FOLLOW_UP_LIMIT = 2


# Words that carry no subject: a question is "about" what is left after these are removed.
_FILLER = frozenset("""
là gì nào của và cho có không được cần những các trên ở này đã chưa để thì hay hoặc với khi nếu như bao nhiêu ai đâu sao
một cái việc cụ thể đang sẽ phải nên rồi lại ra vào từ đến tới theo về bằng mà bị do vì ạ nhé the a an of to is are what which
""".split())


def _subject_words(text: object) -> set[str]:
    cleaned = unicodedata.normalize("NFC", str(text or "")).lower()
    return {word for word in re.findall(r"[0-9a-zà-ỹđ]+", cleaned) if len(word) > 1 and word not in _FILLER}


def repeats_settled(question: str, settled: list[dict]) -> bool:
    """Whether a question asks again, in other words, about something the team already settled.

    The model is told not to do this and still does. A question is treated as a repeat when at least half of its
    subject words already appear in one settled question together with its answer. This can drop a real follow-up
    on the same subject; after one round with the sender that is the better mistake to make.
    """
    asked = _subject_words(question)
    if not asked:
        # Nothing to compare on ("Từ khi nào?"): keep the question rather than guess.
        return False
    for row in settled:
        known = _subject_words(f"{row.get('question') or ''} {row.get('answer') or ''}")
        if known and len(asked & known) / len(asked) >= 0.5:
            return True
    return False


def _lines(value: object) -> list[str]:
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _related(details: dict) -> list[dict]:
    return [row for row in (details.get("related") or []) if isinstance(row, dict) and row.get("id")]


def clarified(details: object) -> list[dict]:
    """Questions the team has settled: answered, or marked as not needed."""
    if not isinstance(details, dict):
        return []
    rows = [row for row in (details.get("clarifications") or []) if isinstance(row, dict) and str(row.get("question") or "").strip()]
    return [row for row in rows if str(row.get("answer") or "").strip() or row.get("skipped") is True]


def unanswered(details: object) -> list[str]:
    """Questions AI raised that nobody has answered or dismissed yet."""
    if not isinstance(details, dict):
        return []
    settled = {str(row["question"]).strip() for row in clarified(details)}
    return [question for question in _lines(details.get("open_questions")) if question not in settled]


def has_details(details: object) -> bool:
    if not isinstance(details, dict):
        return False
    return bool(clarified(details)) or bool(
        (details.get("where") or "").strip() or (details.get("expected") or "").strip() or _related(details)
        or any(_lines(details.get(key)) for key in ("steps", "subtasks", "acceptance", "open_questions"))
    )


def details_markdown(details: object, *, link_related: bool = True) -> str:
    """Markdown for GitLab and GitHub. Sub-tasks and acceptance criteria are checklists the team ticks off."""
    if not has_details(details):
        return ""
    assert isinstance(details, dict)
    parts: list[str] = []
    if (details.get("where") or "").strip():
        parts.append(f"**Ở đâu:** {details['where'].strip()}")
    steps = _lines(details.get("steps"))
    if steps:
        parts.append("**Các bước**\n\n" + "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)))
    if (details.get("expected") or "").strip():
        parts.append(f"**Kết quả mong đợi:** {details['expected'].strip()}")
    subtasks = _lines(details.get("subtasks"))
    if subtasks:
        parts.append("## Việc con\n\n" + "\n".join(f"- [ ] {item}" for item in subtasks))
    acceptance = _lines(details.get("acceptance"))
    if acceptance:
        parts.append("## Tiêu chí nghiệm thu\n\n" + "\n".join(f"- [ ] {item}" for item in acceptance))
    answered = [row for row in clarified(details) if str(row.get("answer") or "").strip()]
    if answered:
        parts.append("## Đã làm rõ\n\n" + "\n".join(f"- **{str(row['question']).strip()}** {str(row['answer']).strip()}" for row in answered))
    questions = unanswered(details)
    if questions:
        parts.append("## Cần làm rõ\n\n" + "\n".join(f"- {item}" for item in questions))
    related = _related(details)
    if related and link_related:
        parts.append("**Có thể liên quan:** " + ", ".join(f"#{row['id']}" for row in related))
    return "\n\n".join(parts)


def proposed_details(session, project_id: object, extraction, previous: object = None) -> dict[str, object] | None:
    """What AI proposed beyond the summary, ready to store on the Intake; None when there is nothing.

    Related issues are kept only when they really are current issues of this project, whatever the model returned.
    What the team already answered is theirs, not the model's: it is carried over from `previous` unchanged.
    """
    details = extraction.details()
    kept = clarified(previous)
    if kept:
        details["clarifications"] = kept
        # A question that was settled is not asked again, even if the model repeats it. And after one round with the
        # sender, the model gets at most two more: questions have to converge, not grow with every analysis.
        settled = {str(row["question"]).strip() for row in kept}
        details["open_questions"] = [
            question for question in details["open_questions"]
            if question not in settled and not repeats_settled(question, kept)
        ][:FOLLOW_UP_LIMIT]
    related: list[dict[str, object]] = []
    if extraction.related_issues:
        rows = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True),
            GitLabIssueSnapshot.issue_external_id.in_(extraction.related_issues),
        ).order_by(GitLabIssueSnapshot.issue_external_id)).all()
        related = [{"id": row.issue_external_id, "title": row.title, "url": row.web_url} for row in rows]
    details["related"] = related
    return details if has_details(details) else None
