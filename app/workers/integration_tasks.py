from __future__ import annotations

import asyncio
import logging
import socket

from sqlalchemy import select

from app.db import get_session
from app.models import ProjectIntegration

from app.modules.integrations.adapters import (
    gitlab_project_members,
    gitlab_projects,
    GitLabAdapter,
    GitLabPermanentError,
    GitLabTransientError,
)
from app.modules.integrations import access_check, github
from app.modules.integrations.github import GitHubPermanentError, GitHubTransientError

logger = logging.getLogger(__name__)
from app.modules.integrations.service import SyncValidationError, integration_service
from app.modules.planning.service import PlanningValidationError, planning_service
from app.modules.planning import acceptance
from app.modules.planning import mapping as tracker_mapping
from app.modules.planning.gitlab_read_model import gitlab_read_model_service
from app.modules.projects.management import project_management_service
from app.queue.celery_app import celery_app


async def _sync_gitlab(context) -> tuple[dict[str, object], bool]:
    adapter = GitLabAdapter()
    existing = await adapter.find_issue(context.project_external_id, context.intake_public_id)
    if existing is not None:
        # The Issue of an earlier decision: same number, text brought up to date, reopened when it was closed.
        closed = str(existing.get("state") or "") == "closed"
        refreshed = await adapter.refresh_issue(context.project_external_id, str(existing["iid"]), context.approved, context.idempotency_key, reopen=closed)
        return {
            "id": str(existing["iid"]),
            "global_id": existing.get("id"),
            "web_url": refreshed.get("web_url") or existing.get("web_url"),
            "reopened": closed,
        }, True
    created = await adapter.create_issue(
        context.project_external_id,
        context.approved,
        context.idempotency_key,
    )
    return {
        "id": str(created["iid"]),
        "global_id": created.get("id"),
        "web_url": created.get("web_url"),
    }, False


async def _sync_github(context) -> tuple[dict[str, object], bool]:
    token_ref = str(context.project_config.get("credential_ref") or "")
    existing = await github.find_issue(token_ref, context.project_external_id, context.intake_public_id)
    closed = existing is not None and str(existing.get("state") or "") == "closed"
    if existing is not None:
        row = await github.refresh_issue(token_ref, context.project_external_id, str(existing["number"]), context.approved, reopen=closed)
    else:
        row = await github.create_issue(token_ref, context.project_external_id, context.approved)
    return {"id": str(row["number"]), "global_id": row.get("id"), "web_url": row.get("html_url"), "reopened": closed}, existing is not None


@celery_app.task(bind=True, name="intake.sync.external")
def sync_external(self, sync_job_id: str) -> str:
    worker_id = f"celery:{getattr(self.request, 'hostname', None) or socket.gethostname()}"
    context = None
    try:
        context = integration_service.claim_sync_job(sync_job_id, worker_id)
        if context is None:
            return "SKIPPED"
        if context.target_system == "GITLAB":
            result, found_existing = asyncio.run(_sync_gitlab(context))
        elif context.target_system == "GITHUB":
            result, found_existing = asyncio.run(_sync_github(context))
        else:
            raise SyncValidationError("ROUTE_NOT_SYNCABLE", "Unsupported external sync target")
        integration_service.complete(sync_job_id, result, found_existing)
        return "SUCCEEDED"
    except (GitLabPermanentError, GitHubPermanentError, SyncValidationError) as exc:
        code = exc.code if isinstance(exc, SyncValidationError) else str(exc)
        integration_service.fail(sync_job_id, code)
        raise
    except (GitLabTransientError, GitHubTransientError) as exc:
        code = str(exc)
        if context is not None and context.attempt >= context.max_attempts:
            integration_service.fail(sync_job_id, code)
            raise
        countdown = min(300, 5 * (2 ** self.request.retries))
        integration_service.mark_retry(sync_job_id, code, countdown)
        max_retries = context.max_attempts if context is not None else 5
        raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)
    except Exception as exc:
        code = "INTEGRATION_INTERNAL_ERROR"
        if context is not None and context.attempt >= context.max_attempts:
            integration_service.fail(sync_job_id, code)
            raise
        countdown = min(300, 5 * (2 ** self.request.retries))
        integration_service.mark_retry(sync_job_id, code, countdown)
        max_retries = context.max_attempts if context is not None else 5
        raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)


def _planning_state(issue: dict[str, object]) -> dict[str, object]:
    assignees = issue.get("assignees") if isinstance(issue.get("assignees"), list) else []
    milestone = issue.get("milestone") if isinstance(issue.get("milestone"), dict) else {}
    return {
        "assignee_ids": [str(item.get("id")) for item in assignees if isinstance(item, dict) and item.get("id")],
        "milestone_id": str(milestone.get("id")) if milestone.get("id") else None,
        "due_date": issue.get("due_date"),
    }


@celery_app.task(bind=True, name="intake.sync.planning-gitlab")
def sync_planning_gitlab(self, planning_sync_job_id: str) -> str:
    worker_id = f"celery:{getattr(self.request, 'hostname', None) or socket.gethostname()}"
    context = None
    try:
        context = planning_service.claim_sync_job(planning_sync_job_id, worker_id)
        if context is None:
            return "SKIPPED"
        adapter = GitLabAdapter()
        before_issue = asyncio.run(
            adapter.get_issue_by_iid(context.project_external_id, context.gitlab_issue_external_id)
        )
        updated_issue = asyncio.run(
            adapter.update_issue_planning(
                context.project_external_id,
                context.gitlab_issue_external_id,
                context.update_payload,
                context.idempotency_key,
            )
        )
        planning_service.complete_sync(
            planning_sync_job_id,
            _planning_state(before_issue),
            _planning_state(updated_issue),
        )
        return "SUCCEEDED"
    except (GitLabPermanentError, PlanningValidationError) as exc:
        code = exc.code if isinstance(exc, PlanningValidationError) else str(exc)
        planning_service.fail_sync(planning_sync_job_id, code)
        raise
    except GitLabTransientError as exc:
        code = str(exc)
        if context is not None and context.attempt >= context.max_attempts:
            planning_service.fail_sync(planning_sync_job_id, code)
            raise
        countdown = min(300, 5 * (2 ** self.request.retries))
        planning_service.mark_sync_retry(planning_sync_job_id, code, countdown)
        max_retries = context.max_attempts if context is not None else 5
        raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)


@celery_app.task(bind=True, name="intake.integrations.accept-issue", max_retries=3)
def accept_issue_on_tracker(self, verification_id: str) -> dict[str, object]:
    """Write the CTO's acceptance on the tracker: a note, then the Issue closed (FR-PLAN-31)."""
    target = acceptance.sync_target(verification_id)
    if target is None:
        return {"verification_id": verification_id, "outcome": "SKIPPED"}
    try:
        if target["system"] == "GITLAB":
            asyncio.run(GitLabAdapter().accept_issue(str(target["target"]), str(target["issue"]), str(target["note"]), close=bool(target["close"])))
        else:
            asyncio.run(github.accept_issue(str(target["token_ref"]), str(target["target"]), str(target["issue"]), str(target["note"]), close=bool(target["close"])))
    except (GitLabTransientError, GitHubTransientError) as exc:
        if self.request.retries >= 3:
            acceptance.record_sync(verification_id, "FAILED", str(exc))
            return {"verification_id": verification_id, "outcome": "FAILED", "code": str(exc)}
        acceptance.record_sync(verification_id, "RETRY", str(exc))
        raise self.retry(exc=exc, countdown=120)
    except (GitLabPermanentError, GitHubPermanentError) as exc:
        acceptance.record_sync(verification_id, "FAILED", str(exc))
        return {"verification_id": verification_id, "outcome": "FAILED", "code": str(exc)}
    acceptance.record_sync(verification_id, "DONE")
    return {"verification_id": verification_id, "outcome": "DONE"}


def _match_team(project_id: str, users) -> dict[str, object]:
    """Fill missing tracker-user mappings by email or name (FR-PLAN-32). A failure here never stops the refresh."""
    try:
        return tracker_mapping.auto_map(project_id, [dict(row) for row in users()])
    except (GitLabPermanentError, GitLabTransientError, GitHubPermanentError, GitHubTransientError) as exc:
        logger.warning("tracker users of project %s not read: %s", project_id, exc)
        return {"filled": 0, "names": [], "unmapped": 0, "error": str(exc)}


def _refresh_evidence(project_id: str, lookup) -> dict[str, int]:
    """The code traces of recently closed Issues (FR-PLAN-22). One Issue failing does not stop the others."""
    done, failed = 0, 0
    for issue_id in gitlab_read_model_service.evidence_targets(project_id):
        try:
            gitlab_read_model_service.store_evidence(project_id, issue_id, lookup(issue_id))
            done += 1
        except (GitLabPermanentError, GitLabTransientError, GitHubPermanentError, GitHubTransientError) as exc:
            logger.warning("evidence of issue %s in project %s not read: %s", issue_id, project_id, exc)
            failed += 1
    return {"read": done, "failed": failed}


@celery_app.task(bind=True, name="intake.planning.refresh-gitlab")
def refresh_gitlab_read_model(self) -> dict[str, object]:
    try:
        with get_session() as session:
            mappings = session.scalars(select(ProjectIntegration).where(
                ProjectIntegration.system == "GITLAB",
                ProjectIntegration.enabled.is_(True),
                ProjectIntegration.project_external_id.is_not(None),
            ).order_by(ProjectIntegration.project_id)).all()
            targets = [(str(mapping.project_id), str(mapping.project_external_id)) for mapping in mappings]
            github_targets = [
                (str(mapping.project_id), str(mapping.project_external_id), str(mapping.credential_ref or ""))
                for mapping in session.scalars(select(ProjectIntegration).where(
                    ProjectIntegration.system == "GITHUB", ProjectIntegration.enabled.is_(True),
                    ProjectIntegration.project_external_id.is_not(None),
                ).order_by(ProjectIntegration.project_id)).all()
            ]
        adapter = GitLabAdapter()
        results = []
        for project_id, project_path in targets:
            issues = asyncio.run(adapter.list_all_issues(project_path))
            result = gitlab_read_model_service.replace_project_snapshot(project_id, issues)
            result["evidence"] = _refresh_evidence(project_id, lambda iid: asyncio.run(adapter.issue_evidence(project_path, iid)))
            result["mapping"] = _match_team(project_id, lambda: asyncio.run(gitlab_project_members(project_path)))
            results.append(result)
        for project_id, repository, token_ref in github_targets:
            # One customer's revoked token must not stop the other projects from refreshing.
            try:
                issues = asyncio.run(github.list_all_issues(token_ref, repository))
            except (GitHubPermanentError, GitHubTransientError) as exc:
                results.append({"project_id": project_id, "error": str(exc)})
                continue
            result = gitlab_read_model_service.replace_project_snapshot(project_id, issues)
            result["evidence"] = _refresh_evidence(project_id, lambda iid, repo=repository, ref=token_ref: asyncio.run(github.issue_evidence(ref, repo, iid)))
            result["mapping"] = _match_team(project_id, lambda repo=repository, ref=token_ref: asyncio.run(github.assignees(ref, repo)))
            results.append(result)
        return {"projects": len(results), "results": results}
    except GitLabPermanentError:
        raise
    except GitLabTransientError as exc:
        countdown = min(300, 15 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown, max_retries=5)
    except Exception as exc:
        countdown = min(300, 15 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown, max_retries=5)


@celery_app.task(name="intake.integration.probe")
def run_integration_probe(probe_id: str) -> str:
    """List or check GitLab/GitHub projects for the project wizard. Only names, IDs and URLs are stored."""
    request = project_management_service.probe_request(probe_id)
    if request is None:
        return "SKIPPED"
    try:
        if request["system"] == "GITHUB":
            if request["action"] == "TOKENS":
                project_management_service.complete_probe(probe_id, result=[{"id": name, "name": name} for name in github.token_names()])
                return "DONE"
            token_ref, _, target = str(request["reference"] or "").partition("|")
            if request["action"] == "ACCESS":
                project_management_service.complete_probe(probe_id, result=asyncio.run(access_check.github_access(token_ref, target)))
                return "DONE"
            if request["action"] == "MEMBERS":
                rows = asyncio.run(github.assignees(token_ref, target))
            elif request["action"] == "CHECK":
                rows = asyncio.run(github.repositories(token_ref, repository=target))
            else:
                rows = asyncio.run(github.repositories(token_ref, search=target or None))
        elif request["action"] == "ACCESS":
            project_management_service.complete_probe(probe_id, result=asyncio.run(access_check.gitlab_access(request["reference"] or None)))
            return "DONE"
        elif request["action"] == "MEMBERS":
            rows = asyncio.run(gitlab_project_members(str(request["reference"])))
        elif request["system"] == "GITLAB":
            rows = asyncio.run(gitlab_projects(
                search=request["reference"] if request["action"] == "LIST" else None,
                path=request["reference"] if request["action"] == "CHECK" else None,
            ))
        else:
            raise ValueError("Unsupported integration system")
    except (GitLabPermanentError, GitLabTransientError, GitHubPermanentError, GitHubTransientError) as exc:
        project_management_service.complete_probe(probe_id, error_code=str(exc)[:64])
        return "FAILED"
    except Exception:
        project_management_service.complete_probe(probe_id, error_code="INTEGRATION_INTERNAL_ERROR")
        return "FAILED"
    if request["action"] == "CHECK":
        if not rows:
            project_management_service.complete_probe(probe_id, error_code=f"{request['system']}_MAPPING_NOT_FOUND")
            return "FAILED"
        project_management_service.complete_probe(probe_id, result=rows[0])
    else:
        project_management_service.complete_probe(probe_id, result=rows)
    return "DONE"
