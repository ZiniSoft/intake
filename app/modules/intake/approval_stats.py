"""How approvals were given, week by week: in the approval queue, or straight from Daily Planning."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import get_session
from app.models import ApprovalAction

LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")


def approval_sources(weeks: int = 4, today: date | None = None) -> list[dict[str, object]]:
    """Approvals per week (Monday first, Vietnam time), newest week first."""
    today = today or datetime.now(LOCAL).date()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=weeks - 1)
    since = datetime.combine(first_monday, time.min, tzinfo=LOCAL).astimezone(timezone.utc)
    counts = {first_monday + timedelta(weeks=index): {"QUEUE": 0, "PLANNING": 0} for index in range(weeks)}
    with get_session() as session:
        rows = session.execute(
            select(ApprovalAction.created_at, ApprovalAction.source)
            .where(ApprovalAction.action == "APPROVE", ApprovalAction.created_at >= since)
        ).all()
    for created_at, source in rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        day = created_at.astimezone(LOCAL).date()
        week = day - timedelta(days=day.weekday())
        if week in counts:
            counts[week]["PLANNING" if source == "PLANNING" else "QUEUE"] += 1
    return [
        {"week_start": week, "from_queue": counts[week]["QUEUE"], "from_planning": counts[week]["PLANNING"]}
        for week in sorted(counts, reverse=True)
    ]
