from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "intake",
    broker=settings.celery_broker_url,
    include=["app.workers.ai_tasks", "app.workers.integration_tasks", "app.workers.planning_tasks", "app.workers.repo_tasks"],
)
celery_app.conf.update(
    task_default_queue="intake.default",
    task_routes={
        "intake.normalize": {"queue": "ai.normalize"},
        "intake.attachments.read": {"queue": "ai.normalize"},
        "intake.context.read": {"queue": "repo.read"},
        "intake.context.refresh-all": {"queue": "repo.read"},
        "intake.sync.external": {"queue": "integration.sync"},
        "intake.sync.planning-gitlab": {"queue": "integration.sync"},
        "intake.planning.refresh-gitlab": {"queue": "integration.sync"},
        "intake.integration.probe": {"queue": "integration.sync"},
        "intake.integrations.accept-issue": {"queue": "integration.sync"},
        "intake.reports.daily-snapshot": {"queue": "planning.schedule"},
        "intake.watch.health-check": {"queue": "planning.schedule"},
        "intake.reports.ai-rescue-scan": {"queue": "ai.normalize"},
        "intake.meetings.note-scan": {"queue": "ai.normalize"},
        "intake.meetings.rewrite": {"queue": "ai.normalize"},
        "intake.drafts.write": {"queue": "ai.normalize"},
        "intake.plan.propose": {"queue": "ai.normalize"},
        "intake.watch.keywords": {"queue": "ai.normalize"},
        "intake.watch.topics": {"queue": "ai.normalize"},
        "intake.watch.topics-tick": {"queue": "planning.schedule"},
        "intake.planning.preflight": {"queue": "planning.schedule"},
        "intake.planning.create-daily": {"queue": "planning.schedule"},
        "intake.personal.nightly": {"queue": "planning.schedule"},
    },
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": settings.pipeline_run_lease_seconds + 60},
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    beat_schedule={
        "meeting-note-scan": {
            "task": "intake.meetings.note-scan",
            "schedule": crontab(minute="*"),
        },
        "daily-report-ai-rescue-scan": {
            "task": "intake.reports.ai-rescue-scan",
            "schedule": crontab(minute="10,40"),
        },
        # Twice a day, twelve hours apart: is the scanner outside delivering?
        "watch-health-check-12h": {
            "task": "intake.watch.health-check",
            "schedule": crontab(hour="7,19", minute=30),
        },
        # Every half hour: which marketing projects are due an AI build of their hot topics (FR-MKT-10).
        "watch-topics-tick": {
            "task": "intake.watch.topics-tick",
            "schedule": crontab(minute="0,30"),
        },
        "daily-report-snapshot-2330": {
            "task": "intake.reports.daily-snapshot",
            "schedule": crontab(hour=23, minute=30),
        },
        "daily-planning-preflight-0645": {
            "task": "intake.planning.refresh-gitlab",
            "schedule": crontab(hour=6, minute=45),
        },
        # The context pack of every software project, read from its repository (ADR-0063).
        "project-context-0650": {
            "task": "intake.context.refresh-all",
            "schedule": crontab(hour=6, minute=50),
        },
        "daily-planning-create-0700": {
            "task": "intake.planning.create-daily",
            "schedule": crontab(hour=7, minute=0),
        },
        # The board as it stood at the end of the day, for the week page (FR-PLAN-30).
        "board-snapshot-2355": {
            "task": "intake.planning.board-snapshot",
            "schedule": crontab(hour=23, minute=55),
        },
        # A person's own unfinished tasks roll to the next working day; the drop quadrant archives itself (FR-PER-05).
        "personal-nightly-2358": {
            "task": "intake.personal.nightly",
            "schedule": crontab(hour=23, minute=58),
        },
    },
)
