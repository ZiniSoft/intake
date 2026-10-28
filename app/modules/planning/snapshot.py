"""Keep each evening's board (FR-PLAN-30).

The board counts what is true at the moment it is read. To compare weeks, the counts of each project are written
once a day at 23:55; running it again for the same day replaces the row.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import BoardDailySnapshot
from app.modules.planning.overview import LOCAL_TZ, day_overview


def snapshot_board(day: date | None = None) -> dict[str, object]:
    """Write one row per software project for `day` (today in Vietnam time by default)."""
    target = day or datetime.now(LOCAL_TZ).date()
    board = day_overview(target, None)
    written = 0
    with get_session() as session:
        for row in board["projects"]:
            existing = session.scalar(select(BoardDailySnapshot).where(
                BoardDailySnapshot.snapshot_date == target, BoardDailySnapshot.project_id == row["id"],
            ))
            values = {
                "readiness_state": row["readiness"]["state"],
                "reports_expected": row["reports"]["expected"], "reports_received": row["reports"]["received"], "reports_late": row["reports"]["late"],
                "approvals_pending": row["approvals"]["pending"], "approvals_cto": row["approvals"]["cto"], "approvals_overdue": row["approvals"]["overdue"],
                "waiting": row["plan"]["waiting"], "waiting_overdue": row["overdue"]["waiting"],
                "unsynced": row["unsynced"], "stuck": row["stuck"],
                "work_log_pending": row["acceptance"]["work_log_pending"], "work_log_overdue": row["overdue"]["work_log"],
                "p0_open": row["gitlab"]["open_p0"], "p0_open_overdue": row["overdue"]["p0_open"],
                "plan_status": row["plan"]["status"], "assigned_hours": row["plan"]["assigned_hours"], "available_hours": row["plan"]["available_hours"],
            }
            if existing is None:
                session.add(BoardDailySnapshot(id=str(uuid4()), snapshot_date=target, project_id=row["id"], **values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            written += 1
        session.commit()
    return {"snapshot_date": target.isoformat(), "projects": written}
