from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import get_session
from app.models import EmailMessage, Project, User
from app.modules.planning import acceptance
from app.modules.planning.service import planning_service
from app.modules.planning.snapshot import snapshot_board
from app.modules.reports.service import daily_report_service
from app.queue.celery_app import celery_app
from app.schemas import PlanningRunCreate


LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


@celery_app.task(name="intake.watch.health-check")
def check_watch_health() -> dict[str, object]:
    """Every twelve hours: has the scanning flow outside delivered anything to the tracks still short of signals?"""
    from app.api.machine_auth import MIN_SECRET
    from app.config import get_settings
    from app.modules.watch.service import watch_service

    settings = get_settings()
    routes_open = all(len((value or "").strip()) >= MIN_SECRET for value in (settings.watch_api_key, settings.watch_webhook_secret))
    results = watch_service.check(routes_open)
    return {"checked": len(results), "warnings": sum(row["status"] == "WARNING" for row in results)}


@celery_app.task(name="intake.watch.topics-tick")
def watch_topics_tick() -> dict[str, object]:
    """Every half hour: the marketing projects whose schedule names a time that just passed get their topics built (FR-MKT-10)."""
    from app.modules.watch.topics import topics_service

    due = topics_service.due_projects()
    for project_id in due:
        celery_app.send_task("intake.watch.topics", args=[project_id, "scheduler"], queue="ai.normalize")
    return {"due": len(due)}


@celery_app.task(name="intake.reports.daily-snapshot")
def create_daily_report_snapshot() -> dict[str, object]:
    report_date = datetime.now(LOCAL_TZ).date()
    return daily_report_service.create_snapshot(report_date)


@celery_app.task(name="intake.planning.preflight")
def planning_preflight() -> dict[str, object]:
    plan_date = datetime.now(LOCAL_TZ).date()
    window_start = plan_date - timedelta(days=7)
    with get_session() as session:
        reports = session.scalars(select(EmailMessage).where(
            EmailMessage.report_date >= window_start,
            EmailMessage.report_date < plan_date,
            EmailMessage.is_current.is_(True),
        )).all()
        return {
            "plan_date": plan_date.isoformat(),
            "current_reports_in_lookback": len(reports),
            "malformed_reports": sum(report.status == "MALFORMED" for report in reports),
            "late_reports": sum(report.is_late for report in reports),
        }


@celery_app.task(name="intake.personal.nightly")
def personal_nightly_task() -> dict[str, int]:
    """Unfinished personal tasks roll to the next working day; the drop quadrant archives what it held a week (FR-PER-05)."""
    from app.modules.planning.personal import nightly
    return nightly()


@celery_app.task(name="intake.planning.board-snapshot")
def snapshot_board_task(day: str | None = None) -> dict[str, object]:
    """Keep the evening's board, one row per project, for the week page (FR-PLAN-30)."""
    return snapshot_board(date.fromisoformat(day) if day else None)


@celery_app.task(name="intake.planning.create-daily")
def create_daily_planning_run(plan_date: str | None = None) -> dict[str, object]:
    """One plan per software project for the day (FR-PLAN-24). A plan the Project Owner made the evening before is
    kept: it only receives the candidates that came in overnight and is marked for review."""
    with get_session() as session:
        cto = session.scalar(select(User).where(User.role == "CTO", User.is_active.is_(True)).order_by(User.created_at))
        if cto is None:
            raise RuntimeError("ACTIVE_CTO_REQUIRED")
        actor_id = str(cto.id)
        project_ids = [str(value) for value in session.scalars(select(Project.id).where(
            Project.status == "ACTIVE", Project.kind == "SOFTWARE",
        ).order_by(Project.code)).all()]
    day = date.fromisoformat(plan_date) if plan_date else datetime.now(LOCAL_TZ).date()
    runs = []
    for project_id in project_ids:
        run = planning_service.create_run(PlanningRunCreate(plan_date=day, project_ids=[project_id], timezone="Asia/Ho_Chi_Minh"), actor_id)
        runs.append({"planning_run_id": str(run["id"]), "project_id": project_id, "status": str(run["status"])})
    # Everything reported done or closed lately becomes an acceptance; five of them make today's sample (FR-PLAN-31).
    collected = acceptance.collect()
    sampled = acceptance.sample(day)
    return {"plan_date": day.isoformat(), "runs": runs, "acceptance": {**collected, "sampled": sampled}}
