"""The repo-reader worker (ADR-0063): reads `docs/agent/CONTEXT.md` from each software project's main repository
with a read-only token and keeps a scored snapshot. It has no write token and no AI key."""
from __future__ import annotations

import asyncio
import logging

from app.modules.integrations.repo_reader import RepoReadError, read_context_file
from app.modules.projects.context import CONTEXT_PATH, project_context_service
from app.queue.celery_app import celery_app

logger = logging.getLogger(__name__)


def read_project_context(project_id: str) -> dict[str, object]:
    """One project: find its main repository, read the pack, store it; a failed read keeps the last good pack."""
    repo = project_context_service.main_repo(project_id)
    if repo is None:
        return {"project_id": project_id, "error": "NO_MAIN_REPO"}
    try:
        content, sha = asyncio.run(read_context_file(repo, CONTEXT_PATH))
    except RepoReadError as error:
        project_context_service.record_error(project_id, error.code)
        return {"project_id": project_id, "error": error.code, "transient": error.transient}
    stored = project_context_service.store(project_id, source="REPO", content=content, sha=sha)
    return {"project_id": project_id, "score": stored["score"], "band": stored["band"], "sha": sha}


@celery_app.task(bind=True, name="intake.context.read", max_retries=3)
def read_context_task(self, project_id: str) -> dict[str, object]:
    result = read_project_context(project_id)
    if result.get("transient"):
        raise self.retry(countdown=min(600, 30 * (2 ** self.request.retries)))
    return result


@celery_app.task(name="intake.context.refresh-all")
def refresh_all_contexts() -> dict[str, object]:
    """Every active software project, one after the other; one broken repository does not stop the rest."""
    results = []
    for project_id in project_context_service.software_project_ids():
        try:
            results.append(read_project_context(project_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("context read failed for %s", project_id)
            results.append({"project_id": project_id, "error": str(exc)[:200]})
    return {"projects": len(results), "results": results}
