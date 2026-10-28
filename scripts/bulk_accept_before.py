"""One-off clean-up: accept every request still waiting for acceptance that was received up to a cut-off day.

Goes through the same path as the CTO's own acceptance (accept_intake_work + queue_acceptance), so the audit trail,
the evidence note and the tracker close are the same as a hand click.  Dry run by default: it only lists.

    python scripts/bulk_accept_before.py --through 2026-10-23              # list what would be accepted
    python scripts/bulk_accept_before.py --through 2026-10-23 --apply      # accept and queue the tracker close
    python scripts/bulk_accept_before.py --through 2026-10-23 --apply --no-tracker   # accept in Intake only

The cut-off is the end of that day in Vietnam time, compared with the request's received_at.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select

from app.db import get_session
from app.models import ExternalLink, IntakeItem, IssueVerification, SourceMessage, User
from app.modules.planning.acceptance import accept_intake_work, queue_acceptance
from app.modules.planning.overview import LOCAL_TZ

NOTE = "Dọn dữ liệu: CTO duyệt hàng loạt các yêu cầu cũ đang chờ nghiệm thu"


def pending(cutoff: datetime) -> list[tuple[str, str, str]]:
    """(intake id, public id, issue number) of requests received by the cut-off whose Issue awaits acceptance."""
    out: list[tuple[str, str, str]] = []
    with get_session() as session:
        received = select(SourceMessage.intake_id, func.min(SourceMessage.received_at).label("at")).group_by(SourceMessage.intake_id).subquery()
        rows = session.execute(
            select(IntakeItem.id, IntakeItem.public_id, ExternalLink.project_id, ExternalLink.external_id)
            .join(ExternalLink, ExternalLink.intake_id == IntakeItem.id)
            .join(received, received.c.intake_id == IntakeItem.id)
            .where(received.c.at <= cutoff, ExternalLink.target_system.in_(("GITLAB", "GITHUB")))
            .order_by(received.c.at)
        ).all()
        for intake_id, public_id, project_id, issue in rows:
            latest = session.scalar(select(IssueVerification).where(
                IssueVerification.project_id == project_id, IssueVerification.issue_external_id == issue,
            ).order_by(IssueVerification.created_at.desc()))
            if latest is not None and latest.decision == "PENDING" and (str(intake_id), public_id, issue) not in out:
                out.append((str(intake_id), public_id, issue))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--through", required=True, help="last day to include, YYYY-MM-DD (Vietnam time)")
    parser.add_argument("--apply", action="store_true", help="really accept; without it only list")
    parser.add_argument("--no-tracker", action="store_true", help="do not queue the Issue close on GitLab/GitHub")
    args = parser.parse_args()
    day = date.fromisoformat(args.through)
    cutoff = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc) - timedelta(microseconds=1)

    todo = pending(cutoff)
    print(f"{len(todo)} request(s) received through {day} waiting for acceptance")
    for _, public_id, issue in todo:
        print(f"  {public_id}  Issue #{issue}")
    if not args.apply or not todo:
        print("Dry run: nothing changed. Add --apply to accept.")
        return

    with get_session() as session:
        cto = session.scalar(select(User).where(User.role == "CTO", User.is_active.is_(True)).order_by(User.created_at))
        if cto is None:
            raise SystemExit("No active CTO user")
        actor = str(cto.id)
    done = queued = 0
    for intake_id, public_id, _ in todo:
        with get_session() as session:
            verification_id, should_queue = accept_intake_work(session, intake_id, actor_id=actor, note=NOTE, now=datetime.now(timezone.utc))
            session.commit()
        if verification_id is None:
            print(f"  skipped {public_id}: no delivery Issue")
            continue
        done += 1
        if should_queue and not args.no_tracker:
            queued += queue_acceptance(verification_id)
    print(f"Accepted {done}; tracker close queued for {queued}.")


if __name__ == "__main__":
    main()
