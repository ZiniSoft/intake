from __future__ import annotations

import asyncio
import json
import socket
import time

from app.config import get_settings
from app.queue.celery_app import celery_app
from app.services.ai_processor import (
    AIProviderPermanentError,
    AIProviderTransientError,
    ai_provider_chain,
    available_routes,
    keep_delivery_route,
    build_intake_message,
    fit_route,
)
from app.modules.content_plan.service import content_plan_service
from app.modules.drafts.message import GROUP_NAMES, build_draft_message  # noqa: F401  (kept importable from here)
from app.modules.drafts.service import draft_service
from app.modules.meetings.service import MeetingError, meeting_service
from app.modules.reports import issue_match
from app.modules.reports.service import daily_report_service
from app.modules.watch.service import watch_service
from app.services.ai_processor import POST_DRAFT_PROMPT_VERSION, umodelverse_adapter
from app.services.intake_service import intake_store
from app.services.processing_repository import processing_repository


class TransientProcessingError(RuntimeError):
    pass


class PermanentProcessingError(RuntimeError):
    pass


def execute_normalization(run_id: str, intake_id: str, worker_id: str) -> str:
    if not processing_repository.mark_running(run_id, worker_id):
        return "SKIPPED"

    started_at = time.perf_counter()
    current_item = intake_store.get(intake_id)
    if current_item is None:
        raise PermanentProcessingError("INTAKE_NOT_FOUND")

    # Pictures first (FR-AI-14): what they say joins the text the model reads. A model outage leaves them unread,
    # the request is still normalized from its text, and "Đọc lại" on the request brings the transcript later.
    from app.services.attachment_reader import read_pending

    read_pending(intake_id)
    source = intake_store.normalization_source(intake_id)
    if source is None:
        raise PermanentProcessingError("INTAKE_NOT_FOUND")
    routes = available_routes(has_delivery=bool(source["has_delivery"]))
    message = build_intake_message(
        str(source["text"]), project_name=source["project_name"], project_kind=source["project_kind"],
        channel=source["channel"], routes=routes,
        brief=source.get("brief"), terms=source.get("terms"), open_issues=source.get("open_issues"),
        clarifications=source.get("clarifications"), existing_issue=source.get("existing_issue"),
    )
    try:
        provider_result = asyncio.run(ai_provider_chain.extract(message))
    except AIProviderTransientError as exc:
        raise TransientProcessingError(exc.code) from exc
    except AIProviderPermanentError as exc:
        raise PermanentProcessingError(exc.code) from exc

    if provider_result is None:
        extraction = intake_store.build_local_extraction(intake_id)
        if extraction is None:
            raise PermanentProcessingError("INTAKE_NOT_FOUND")
        model_provider = "LOCAL"
        model_name = "heuristic-v1"
        provider_metadata = {"fallback_used": False, "fallback_reason": "NO_PROVIDER_CONFIGURED"}
    else:
        extraction = provider_result.extraction
        # A project that is not linked to a delivery tracker cannot be routed there.
        fitted = keep_delivery_route(fit_route(extraction.proposed_route, routes), routes, source.get("existing_issue"))
        route_adjusted = fitted != extraction.proposed_route
        if route_adjusted:
            extraction = extraction.model_copy(update={"proposed_route": fitted})
        model_provider = provider_result.provider
        model_name = provider_result.model
        provider_metadata = {
            "fallback_used": provider_result.fallback_used,
            "fallback_reason": provider_result.fallback_reason,
            "input_origin": source["origin"],
            "route_adjusted": route_adjusted,
        }
    processing_repository.complete(
        run_id,
        intake_id,
        extraction,
        model_provider=model_provider,
        model_name=model_name,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        provider_metadata=provider_metadata,
    )
    return "SUCCEEDED"


@celery_app.task(bind=True, name="intake.normalize")
def normalize_intake(self, run_id: str, intake_id: str) -> str:
    settings = get_settings()
    worker_id = f"celery:{getattr(self.request, 'hostname', None) or socket.gethostname()}"
    try:
        return execute_normalization(run_id, intake_id, worker_id)
    except TransientProcessingError as exc:
        if self.request.retries >= settings.ai_task_max_retries:
            processing_repository.fail(run_id, str(exc), retryable=False)
            raise
        countdown = min(300, 5 * (2 ** self.request.retries))
        processing_repository.requeue(run_id, str(exc), countdown)
        raise self.retry(exc=exc, countdown=countdown, max_retries=settings.ai_task_max_retries)
    except PermanentProcessingError as exc:
        processing_repository.fail(run_id, str(exc), retryable=False)
        raise
    except Exception as exc:
        if self.request.retries >= settings.ai_task_max_retries:
            processing_repository.fail(run_id, "INTERNAL_PROCESSING_ERROR", retryable=False)
            raise
        countdown = min(300, 5 * (2 ** self.request.retries))
        processing_repository.requeue(run_id, "INTERNAL_PROCESSING_ERROR", countdown)
        raise self.retry(exc=exc, countdown=countdown, max_retries=settings.ai_task_max_retries)


@celery_app.task(name="intake.attachments.read", bind=True, max_retries=3)
def read_attachment_task(self, attachment_id: str, intake_id: str) -> str:
    """An attachment added to a request that was already read: transcribe it, then let the AI read the request again."""
    from app.services.attachment_reader import read_attachment

    outcome = read_attachment(attachment_id)
    if outcome == "RETRY":
        raise self.retry(countdown=min(300, 15 * (2 ** self.request.retries)))
    if outcome == "DONE":
        try:
            processing_repository.enqueue_normalization(intake_id)
        except RuntimeError:
            # Synced already: the transcript is on the request for people to read, the AI result stands.
            pass
    return outcome


def execute_report_rescue(email_id: str) -> str:
    source = daily_report_service.ai_rescue_source(email_id)
    if source is None:
        return "SKIPPED"
    try:
        extraction = asyncio.run(umodelverse_adapter.extract_report(source))
    except AIProviderTransientError as exc:
        raise TransientProcessingError(exc.code) from exc
    except AIProviderPermanentError as exc:
        raise PermanentProcessingError(exc.code) from exc
    applied = daily_report_service.apply_ai_rescue(
        email_id, extraction, provider=umodelverse_adapter.describe("report")[0], model=umodelverse_adapter.describe("report")[1],
    )
    return "SUCCEEDED" if applied is not None else "SKIPPED"


def execute_issue_suggestions(email_id: str, item_ids: list[str]) -> str:
    """Ask AI where the items the rules could not place belong. Titles and Issue lists only; the email never leaves."""
    context = issue_match.ai_context(email_id, item_ids)
    if context is None:
        return "SKIPPED"
    try:
        answer = asyncio.run(umodelverse_adapter.match_report_issues(json.dumps(context, ensure_ascii=False)))
    except AIProviderTransientError as exc:
        raise TransientProcessingError(exc.code) from exc
    except AIProviderPermanentError as exc:
        raise PermanentProcessingError(exc.code) from exc
    applied = issue_match.apply_ai_matches(
        email_id, [row.model_dump() for row in answer.matches if row.issue], provider=umodelverse_adapter.describe("report")[0], model=umodelverse_adapter.describe("report")[1],
    )
    return "SUCCEEDED" if applied else "NOTHING"


@celery_app.task(name="intake.reports.issue-suggest", bind=True, max_retries=2)
def suggest_report_issues(self, email_id: str, item_ids: list[str]) -> dict[str, object]:
    if not umodelverse_adapter.is_configured("report"):
        return {"email_id": email_id, "outcome": "NOT_CONFIGURED"}
    try:
        return {"email_id": email_id, "outcome": execute_issue_suggestions(email_id, item_ids)}
    except TransientProcessingError as exc:
        if self.request.retries >= 2:
            return {"email_id": email_id, "outcome": "FAILED", "code": str(exc)}
        raise self.retry(exc=exc, countdown=60)
    except PermanentProcessingError as exc:
        return {"email_id": email_id, "outcome": "FAILED", "code": str(exc)}


def process_report_rescue(email_id: str) -> str:
    settings = get_settings()
    try:
        return execute_report_rescue(email_id)
    except TransientProcessingError as exc:
        exhausted = daily_report_service.record_ai_rescue_attempt(email_id, str(exc), settings.ai_task_max_retries)
        return "FAILED" if exhausted else "RETRY_LATER"
    except PermanentProcessingError as exc:
        daily_report_service.record_ai_rescue_failure(email_id, str(exc))
        return "FAILED"


@celery_app.task(name="intake.reports.ai-rescue-scan")
def scan_daily_reports_for_rescue(remaining: int | None = None, skip: list[str] | None = None) -> dict[str, object]:
    # One email per task keeps each task well inside the broker visibility timeout; the task re-enqueues
    # itself until the scan budget is spent. PostgreSQL holds the pending set, so a lost message only delays work.
    if not umodelverse_adapter.is_configured("report"):
        return {"outcome": "NOT_CONFIGURED"}
    budget = get_settings().report_ai_batch_size if remaining is None else remaining
    skipped = list(skip or [])
    if budget <= 0:
        return {"outcome": "BUDGET_SPENT"}
    email_id = next(
        (candidate for candidate in daily_report_service.pending_ai_rescues(limit=budget + len(skipped))
         if candidate not in skipped),
        None,
    )
    if email_id is None:
        return {"outcome": "IDLE"}
    outcome = process_report_rescue(email_id)
    if budget > 1:
        scan_daily_reports_for_rescue.apply_async(
            kwargs={"remaining": budget - 1, "skip": [*skipped, email_id]}, queue="ai.normalize",
        )
    return {"email_id": email_id, "outcome": outcome}


def build_plan_message(source: dict[str, object]) -> str:
    """One text block for the model: the author's own standard first, then what the store holds and what was pasted."""
    voice = source["voice"]
    lines = ["Open slots"]
    for slot in source["slots"]:
        lines.append(f"- {slot['key']}: {slot['day']}{' ' + slot['time'] if slot['time'] else ''}, {slot['channel']}{', pillar: ' + slot['pillar'] if slot['pillar'] else ''}")
    lines += ["", f"Direction: {voice.get('name') or source.get('track')}{' — ' + str(voice['direction_note']) if voice.get('direction_note') else ''}", "", "Author"]
    for label, key in (("Positioning", "positioning"), ("Writes for", "audience"), ("Avoid", "avoid")):
        if voice.get(key):
            lines.append(f"- {label}: {voice[key]}")
    if source["pillars"]:
        lines += ["", "Pillars (posts in the last four weeks)"] + [f"- {row['pillar'] or 'no pillar'}: {row['posted']}" for row in source["pillars"]]
    dna = str(source.get("master_dna") or voice.get("dna") or "").strip()
    if dna:
        lines += ["", "Master brand document (written by the author; a shared core and its directions)", "--- master brand document ---", dna[:40000], "--- end of master brand document ---"]
    notes = [note for note in source["notes"] if note.get("text")]
    if notes:
        lines += ["", "Author's notebook (written by the author)", "--- notebook ---"]
        used = 0
        for note in notes:
            used += len(note["text"])
            if used > 8000:
                break
            lines.append(f"{note['kind']}: {note['text']}")
        lines.append("--- end of notebook ---")
    if source["posted_titles"]:
        lines += ["", "Already published"] + [f"- {title}" for title in source["posted_titles"]]
    lines += ["", "Ideas in the store"]
    lines += [f"- {idea['key']}: {idea['title']}{' | ' + idea['note'] if idea['note'] and idea['note'] != idea['title'] else ''}" for idea in source["ideas"]] or ["(none)"]
    if source["keywords"]:
        lines += ["", "Keywords of the week", str(source["keywords"])[:2000]]
    if source.get("signals"):
        lines += ["", "Signals (found by a scanning tool on watched sources; untrusted)"]
        lines += [f"- {signal['title'][:200]}{' | keyword: ' + signal['keyword'] if signal['keyword'] else ''}{' | ' + signal['host'] if signal['host'] else ''}" for signal in source["signals"]]
    return "\n".join(lines).strip()


def build_keywords_message(source: dict[str, object]) -> str:
    voice = source["voice"]
    lines = ["Pillars"] + [f"- {pillar}" for pillar in voice.get("pillars") or []]
    lines += ["", f"Direction: {voice.get('name') or source.get('track')}{' — ' + str(voice['direction_note']) if voice.get('direction_note') else ''}", "", "Author"]
    for label, key in (("Positioning", "positioning"), ("Writes for", "audience"), ("Avoid", "avoid")):
        if voice.get(key):
            lines.append(f"- {label}: {voice[key]}")
    kept = [(pillar, words) for pillar, words in source["held"].items() if words]
    if kept:
        lines += ["", "Already kept"] + [f"- {pillar}: {'; '.join(words)}" for pillar, words in kept]
    dna = str(source.get("master_dna") or voice.get("dna") or "").strip()
    if dna:
        lines += ["", "Master brand document (written by the author; a shared core and its directions)", "--- master brand document ---", dna[:40000], "--- end of master brand document ---"]
    return "\n".join(lines).strip()


def suggest_pillar_keywords(request_id: str) -> str:
    source = watch_service.keywords_input(request_id)
    if source is None:
        return "SKIPPED"
    try:
        result = asyncio.run(umodelverse_adapter.suggest_pillar_keywords(build_keywords_message(source)))
    except (AIProviderTransientError, AIProviderPermanentError) as exc:
        watch_service.save_suggestion(request_id, None, exc.code)
        return "FAILED"
    watch_service.save_suggestion(request_id, [item.model_dump() for item in result.pillars])
    return "SUCCEEDED"


@celery_app.task(name="intake.watch.keywords")
def suggest_pillar_keywords_task(request_id: str) -> str:
    return suggest_pillar_keywords(request_id)


def propose_week_plan(request_id: str) -> str:
    source = content_plan_service.proposal_input(request_id)
    if source is None:
        return "SKIPPED"
    try:
        result = asyncio.run(umodelverse_adapter.propose_week_plan(build_plan_message(source)))
    except (AIProviderTransientError, AIProviderPermanentError) as exc:
        # The person is waiting on the screen: fail now and let them ask again.
        content_plan_service.save_proposal(request_id, None, exc.code)
        return "FAILED"
    content_plan_service.save_proposal(request_id, [item.model_dump() for item in result.slots])
    return "SUCCEEDED"


@celery_app.task(name="intake.plan.propose")
def propose_week_plan_task(request_id: str) -> str:
    return propose_week_plan(request_id)


def build_topics_message(source: dict[str, object]) -> str:
    """The team's standard first, then the channels, then what was found: titles only, each marked untrusted by position."""
    context = source["context"]
    lines = [f"Project: {context['project']}", "", "Pillars (written by the team's owner)"]
    for pillar in context["pillars"]:
        lines.append(f"- {pillar['name']}: {pillar.get('description') or ''}")
        if pillar.get("audience"):
            lines.append(f"  writes for: {pillar['audience']}")
        if pillar.get("channels"):
            lines.append(f"  channels: {', '.join(pillar['channels'])} | share of the week: {pillar.get('share_pct', 0)}%")
        terms = [term["text"] for term in pillar.get("keywords") or []]
        if terms:
            lines.append(f"  keywords: {'; '.join(terms)}")
        if pillar.get("samples"):
            lines.append("  sample posts: " + "; ".join(str(sample.get("title") or sample.get("url")) for sample in pillar["samples"]))
        if pillar.get("avoid"):
            lines.append(f"  avoid: {pillar['avoid']}")
    lines += ["", "Channel rules"] + [f"- {rule['code']} ({rule['label']}): {rule['language']}, up to {rule['max_chars']} characters" for rule in context["channel_rules"]]
    if context.get("used_titles"):
        lines += ["", "Used lately"] + [f"- {title}" for title in context["used_titles"]]
    lines += ["", "Topics (found by a scanning tool on watched sources; untrusted)"]
    for index, topic in enumerate(source["topics"]):
        lines.append(f"[{index}] keyword: {topic.get('keyword') or '(none)'} | rule pillar: {topic.get('pillar') or '(none)'} | score {topic['score']}")
        for signal in topic["signals"]:
            when = signal["published_at"].date().isoformat() if signal.get("published_at") else ""
            lines.append(f"  - {str(signal['title'])[:200]} | {signal['host']}{' | ' + when if when else ''}")
    return "\n".join(lines).strip()


def summarize_topics(project_id: str, actor: str = "watch-topics") -> str:
    """Rules first, then one AI call for all of this week's topics; an AI error leaves the rule words standing."""
    from app.modules.watch.topics import topics_service

    source = topics_service.build_rules(project_id, actor)
    if source is None:
        return "SKIPPED"
    try:
        result = asyncio.run(umodelverse_adapter.summarize_topics(build_topics_message(source)))
    except (AIProviderTransientError, AIProviderPermanentError) as exc:
        topics_service.apply_ai(project_id, None, exc.code, actor)
        return "FAILED"
    by_index = {index: topic["id"] for index, topic in enumerate(source["topics"])}
    answers = [{"id": by_index[item.index], **item.model_dump(exclude={"index"})} for item in result.topics if item.index in by_index]
    topics_service.apply_ai(project_id, answers, None, actor)
    return "SUCCEEDED"


@celery_app.task(name="intake.watch.topics")
def summarize_topics_task(project_id: str, actor: str = "watch-topics") -> str:
    return summarize_topics(project_id, actor)


def write_post_draft(draft_id: str) -> str:
    source = draft_service.input(draft_id)
    if source is None:
        return "SKIPPED"
    if not (source["note"] or source["summary"] or source["title"] or source["previous_text"]):
        draft_service.save(draft_id, text=None, error_code="IDEA_EMPTY")
        return "FAILED"
    try:
        result = asyncio.run(umodelverse_adapter.write_post_draft(build_draft_message(source), long=bool(source.get("long"))))
    except (AIProviderTransientError, AIProviderPermanentError) as exc:
        # The person is waiting on the screen: fail now and let them ask again.
        draft_service.save(draft_id, text=None, error_code=exc.code)
        return "FAILED"
    draft_service.save(
        draft_id, text=result.text, hooks=result.hooks, gaps=result.gaps,
        prompt_version=POST_DRAFT_PROMPT_VERSION, model=umodelverse_adapter.describe("content")[1],
    )
    return "SUCCEEDED"


@celery_app.task(name="intake.drafts.write")
def write_post_draft_task(draft_id: str) -> str:
    return write_post_draft(draft_id)


def rewrite_spoken_request(meeting_id: str) -> str:
    source = meeting_service.rewrite_input(meeting_id)
    if source is None:
        meeting_service.save_rewrite(meeting_id, None, "NO_TRANSCRIPT")
        return "FAILED"
    header = f"Project: {source['project']}\n\n" if source["project"] else ""
    try:
        result = asyncio.run(umodelverse_adapter.rewrite_request(f"{header}Transcript:\n{source['transcript']}"))
    except (AIProviderTransientError, AIProviderPermanentError) as exc:
        # The person is waiting on the screen: fail now and let them ask again, rather than retry behind their back.
        meeting_service.save_rewrite(meeting_id, None, exc.code)
        return "FAILED"
    meeting_service.save_rewrite(meeting_id, result.text)
    return "SUCCEEDED"


@celery_app.task(name="intake.meetings.rewrite")
def rewrite_spoken_request_task(meeting_id: str) -> str:
    return rewrite_spoken_request(meeting_id)


def generate_meeting_note(meeting_id: str) -> str:
    source = meeting_service.note_input(meeting_id)
    if source is None:
        meeting_service.note_failed(meeting_id, "NO_TRANSCRIPT", final=True)
        return "FAILED"
    header = "Projects: " + ", ".join(source["projects"])
    if source["selected_project"]:
        header += f"\nProject chosen for this meeting: {source['selected_project']}"
    try:
        note = asyncio.run(umodelverse_adapter.extract_meeting_note(f"{header}\n\nTranscript:\n{source['transcript']}"))
    except AIProviderTransientError as exc:
        return "FAILED" if meeting_service.note_failed(meeting_id, exc.code, final=False) else "RETRY_LATER"
    except AIProviderPermanentError as exc:
        meeting_service.note_failed(meeting_id, exc.code, final=True)
        return "FAILED"
    meeting_service.save_note(meeting_id, note, model="/".join(umodelverse_adapter.describe("meeting")))
    return "SUCCEEDED"


@celery_app.task(name="intake.meetings.note-scan")
def scan_meetings_for_notes() -> dict[str, object]:
    # One meeting per run; PostgreSQL holds the pending set, so a lost message only delays the note.
    if not umodelverse_adapter.is_configured("meeting"):
        return {"outcome": "NOT_CONFIGURED"}
    try:
        meeting_id = meeting_service.claim_note()
    except MeetingError:
        return {"outcome": "IDLE"}
    if meeting_id is None:
        return {"outcome": "IDLE"}
    return {"meeting_id": meeting_id, "outcome": generate_meeting_note(meeting_id)}
