"""Acceptance as its own queue (FR-PLAN-31, ADR-0055): a report saying done with an Issue becomes an acceptance, the
CTO's sample of the day, the Project Owner's word beside the CTO's, rework on "not done", and the tracker write."""
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import EmailMessage, ExternalLink, GitLabIssueSnapshot, IntakeItem, IssueEvidenceLink, IssueVerification, PlanningCandidate, PlanningRun, PlanningWarning, Project, ReportItem, SyncJob, User, WorkforceMember
from app.modules.planning import acceptance
from tests.test_intake_reopen import _approved, _mark_synced

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
SENDER = "acceptance-test@example.test"
ISSUES = {"9701": "Xuất báo cáo tuần ra PDF", "9702": "Sửa lỗi gửi email trễ"}


def _project_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(Project).where(Project.code == "orbit")).id)


def _member() -> str:
    with get_session() as session:
        existing = session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == SENDER))
        if existing is not None:
            return str(existing.id)
    created = cto.post("/api/v1/planning/members", json={
        "display_name": "Acceptance Test", "email_reference": SENDER,
        "project_mappings": [{"project_id": _project_id(), "gitlab_user_external_id": "78", "role": "Developer"}],
    })
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _issues() -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        for issue, title in ISSUES.items():
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=_project_id(), issue_external_id=issue, title=title, state="opened", labels=["priority:p1" if issue == "9701" else "priority:p3"],
                assignee_external_ids=["78"], milestone_external_id=None, milestone_title=None, due_date=None, web_url=None,
                payload_hash=hashlib.sha256(f"acceptance:{issue}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
            ))
        session.commit()


def _report(uid: str, day: str, items: str) -> dict:
    body = f"BÁO CÁO NGÀY\nNgày: {day} | Nhân sự: Acceptance Test | Tổng thời gian: 6 giờ\n\n=== ORBIT | Orbit ===\n{items}\n"
    response = cto.post("/api/v1/reports/daily/ingest", json={
        "mailbox": "report@example.test", "uid_validity": "20261013", "uid": uid, "message_id": f"<acceptance-{uid}@example.test>",
        "sender_address": SENDER, "sender_name": "Acceptance Test", "subject": f"DAILY REPORT | {day} | Acceptance Test | ORBIT",
        "body": body, "received_at": f"{day}T10:30:00Z",
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _cleanup() -> None:
    with get_session() as session:
        for row in session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id.in_(list(ISSUES)), IssueVerification.project_id == _project_id())).all():
            session.delete(row)
        for row in session.scalars(select(PlanningCandidate).where(PlanningCandidate.gitlab_issue_external_id.in_(list(ISSUES)))).all():
            session.delete(row)
        for row in session.scalars(select(EmailMessage).where(EmailMessage.sender_address == SENDER)).all():
            for item in session.scalars(select(ReportItem).where(ReportItem.email_message_id == row.id)).all():
                session.delete(item)
            session.delete(row)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id.in_(list(ISSUES)), GitLabIssueSnapshot.project_id == _project_id())).all():
            session.delete(row)
        session.commit()


def test_reported_done_with_an_issue_becomes_an_acceptance_and_the_cto_gets_a_sample() -> None:
    _member()
    _issues()
    today = date.today().isoformat()
    try:
        report = _report("acc-1", today, "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có\n\n[DONE] Sửa lỗi gửi email trễ | Thời gian: 2 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9702 | Plane: Không có | Intake: Không có")
        assert report["unlinked_items"] == 0
        with get_session() as session:
            rows = session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id.in_(list(ISSUES)), IssueVerification.project_id == _project_id())).all()
            assert {row.issue_external_id for row in rows} == set(ISSUES)
            assert all(row.source == "REPORT" and row.decision == "PENDING" and row.reported_on == date.fromisoformat(today) for row in rows)
        again = acceptance.collect()
        assert isinstance(again["from_reports"], int)
        with get_session() as session:
            assert len(session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id.in_(list(ISSUES)), IssueVerification.project_id == _project_id())).all()) == 2
        shown = cto.get("/api/v1/acceptance")
        assert shown.status_code == 200, shown.text
        data = shown.json()["data"]
        mine = [row for row in data["today"] + data["more"] if row["issue_external_id"] in ISSUES]
        assert len(mine) == 2 and all(row["reporter_name"] == "Acceptance Test" and row["reported_hours"] in (4.0, 2.0) for row in mine)
        picked = [row for row in data["today"] if row["issue_external_id"] in ISSUES]
        # P1 before P3 in the sample order wherever both are in today's five.
        if len(picked) == 2:
            assert [row["issue_external_id"] for row in picked] == ["9701", "9702"]
        assert cto.post("/api/v1/acceptance/sample?extra=5").status_code == 200
    finally:
        _cleanup()


def test_the_owner_confirms_the_cto_accepts_and_not_done_goes_back_to_the_plan() -> None:
    _member()
    _issues()
    today = date.today().isoformat()
    try:
        _report("acc-2", today, "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có\n\n[DONE] Sửa lỗi gửi email trễ | Thời gian: 2 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9702 | Plane: Không có | Intake: Không có")
        with get_session() as session:
            by_issue = {row.issue_external_id: str(row.id) for row in session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id.in_(list(ISSUES)), IssueVerification.project_id == _project_id())).all()}
        # The Project Owner's word is recorded beside the CTO's, and does not decide for the CTO.
        theirs = owner.post(f"/api/v1/acceptance/{by_issue['9701']}/accept", json={"evidence_missing_reason": "xem PDF tại chỗ"})
        assert theirs.status_code in (200, 404), theirs.text
        if theirs.status_code == 200:
            assert theirs.json()["data"]["po_decision"] == "ACCEPTED" and theirs.json()["data"]["decision"] == "PENDING"
        # The CTO accepts: the decision stands and the tracker write is recorded (queued or not, with no broker here).
        accepted = cto.post(f"/api/v1/acceptance/{by_issue['9701']}/accept", json={"evidence_missing_reason": "xem PDF tại chỗ"})
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()["data"]
        assert body["decision"] == "ACCEPTED" and body["level_name"] == "ACCEPTED" and body["sync_status"] in ("PENDING", "QUEUE_FAILED")
        assert cto.post(f"/api/v1/acceptance/{by_issue['9701']}/accept", json={}).status_code == 409
        assert cto.post(f"/api/v1/acceptance/{by_issue['9702']}/reject", json={}).status_code == 422
        # Not done: rework lands in the project's open plan when there is one.
        run = cto.post("/api/v1/planning/runs", json={"plan_date": date(2031, 4, 7).isoformat(), "project_ids": [_project_id()], "timezone": "Asia/Ho_Chi_Minh"})
        assert run.status_code in (200, 201), run.text
        run_id = run.json()["data"]["id"]
        try:
            rejected = cto.post(f"/api/v1/acceptance/{by_issue['9702']}/reject", json={"reason": "email vẫn trễ khi hàng đợi đầy"})
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["data"]["decision"] == "REJECTED"
            with get_session() as session:
                rework = session.scalars(select(PlanningCandidate).where(PlanningCandidate.gitlab_issue_external_id == "9702", PlanningCandidate.source_type == "VERIFICATION")).all()
                assert rework and any(str(row.planning_run_id) == run_id for row in rework)
                assert session.get(PlanningRun, run_id).status == "REVIEW_REQUIRED"
            decided = cto.get("/api/v1/acceptance").json()["data"]["decided"]
            assert {row["issue_external_id"] for row in decided} >= set(ISSUES)
        finally:
            with get_session() as session:
                for model in (PlanningCandidate, PlanningWarning):
                    for row in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                        session.delete(row)
                run_row = session.get(PlanningRun, run_id)
                if run_row is not None:
                    session.delete(run_row)
                session.commit()
    finally:
        _cleanup()


def test_owner_acceptance_completes_the_linked_intake_lifecycle() -> None:
    """INT-26W44-002: owner-confirmed work must not leave its Intake waiting for acceptance."""
    request = _approved("GITLAB")
    _mark_synced(request["id"], "GITLAB", "9701")
    _member()
    _issues()
    today = date.today().isoformat()
    try:
        _report(
            "acc-owner-lifecycle",
            today,
            "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\n"
            "Tham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có",
        )
        with get_session() as session:
            verification = session.scalar(select(IssueVerification).where(
                IssueVerification.issue_external_id == "9701",
                IssueVerification.project_id == _project_id(),
            ))
            assert verification is not None
            actor_id = str(session.scalar(select(User.id).where(User.auth_subject == "cto")))

        confirmed = acceptance.decide(
            str(verification.id), decision="ACCEPTED", reason=None, actor_id=actor_id, role="PROJECT_OWNER",
            allowed_project_ids=frozenset({_project_id()}), evidence_missing_reason="Project Owner đã kiểm trực tiếp",
        )
        assert confirmed["po_decision"] == "ACCEPTED"
        assert confirmed["decision"] == "PENDING", "CTO sampling remains a separate decision"

        detail = cto.get(f"/api/v1/intakes/{request['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["lifecycle_stage"] == "ACCEPTED"
        accepted_page = cto.get("/api/v1/intakes", params={"stage": "ACCEPTED", "search": request["public_id"]})
        assert accepted_page.status_code == 200, accepted_page.text
        assert [row["id"] for row in accepted_page.json()["data"]["items"]] == [request["id"]]
    finally:
        with get_session() as session:
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            session.commit()
        _cleanup()


def test_sync_target_says_what_to_write_and_record_sync_closes_the_snapshot() -> None:
    _member()
    _issues()
    today = date.today().isoformat()
    try:
        _report("acc-3", today, "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có")
        with get_session() as session:
            row = session.scalar(select(IssueVerification).where(IssueVerification.issue_external_id == "9701", IssueVerification.project_id == _project_id()))
            row.decision, row.decided_at, row.sync_status = "ACCEPTED", datetime.now(timezone.utc), "PENDING"
            session.commit()
            verification_id = str(row.id)
        target = acceptance.sync_target(verification_id)
        if target is not None:
            assert target["issue"] == "9701" and target["close"] is True and "nghiệm thu" in target["note"] and target["system"] in ("GITLAB", "GITHUB")
        acceptance.record_sync(verification_id, "DONE")
        with get_session() as session:
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == "9701", GitLabIssueSnapshot.project_id == _project_id(), GitLabIssueSnapshot.is_current.is_(True)))
            assert snapshot.state == "closed" and snapshot.closed_at is not None
            assert session.get(IssueVerification, verification_id).sync_status == "DONE"
    finally:
        _cleanup()


def test_the_owner_sees_which_acceptances_the_cto_marked_hard() -> None:
    _member()
    _issues()
    today = date.today().isoformat()
    approved = _approved("GITLAB")
    _mark_synced(approved["id"], "GITLAB", "9701")
    try:
        _report("acc-hard", today, "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có")
        def flag(client: TestClient) -> bool | None:
            data = client.get("/api/v1/acceptance").json()["data"]
            rows = [row for key in ("today", "more") for row in data[key] if row["issue_external_id"] == "9701"]
            return rows[0]["needs_cto_acceptance"] if rows else None
        cto.post("/api/v1/acceptance/sample?extra=5")
        assert flag(cto) is False
        with get_session() as session:
            session.get(IntakeItem, approved["id"]).needs_cto_acceptance = True
            session.commit()
        assert flag(cto) is True
        assert flag(owner) in (True, None)
    finally:
        with get_session() as session:
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == approved["id"])).all():
                job = session.get(SyncJob, link.sync_job_id)
                session.delete(link)
                session.flush()
                if job is not None:
                    session.delete(job)
            session.commit()
        _cleanup()


# --- Project Owner closes low-risk work (FR-PLAN-41, ADR-0082) ---------------------------------------------------

PO_EMAIL = "acceptance-po@example.test"
DONE_LINE = "[DONE] Sửa lỗi gửi email trễ | Thời gian: 2 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9702 | Plane: Không có | Intake: Không có"
P1_LINE = "[DONE] Xuất báo cáo tuần ra PDF | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9701 | Plane: Không có | Intake: Không có"


def _po_member() -> str:
    with get_session() as session:
        existing = session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == PO_EMAIL))
        if existing is not None:
            return str(existing.id)
    created = cto.post("/api/v1/planning/members", json={
        "display_name": "Acceptance PO", "email_reference": PO_EMAIL,
        "project_mappings": [{"project_id": _project_id(), "gitlab_user_external_id": "7901", "role": "Project Owner"}],
    })
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


class _PoFinal:
    """orbit lets its Owner close low-risk work, and the "project-owner" user is that Owner; all restored on exit."""

    def __init__(self, policy: str = "PO_FINAL_LOW_RISK") -> None:
        self.policy = policy

    def __enter__(self) -> str:
        member_id = _po_member()
        assert owner.get("/api/v1/auth/me").status_code == 200
        with get_session() as session:
            project = session.get(Project, _project_id())
            user = session.scalar(select(User).where(User.auth_subject == "project-owner"))
            self.saved = (dict(project.project_settings or {}), project.owner_member_id, user.member_id)
            self.user_id = str(user.id)
            project.project_settings = {**(project.project_settings or {}), "acceptance_policy": self.policy}
            project.owner_member_id = member_id
            user.member_id = member_id
            session.commit()
        return self.user_id

    def __exit__(self, *exc) -> None:
        with get_session() as session:
            project = session.get(Project, _project_id())
            project.project_settings, project.owner_member_id = self.saved[0], self.saved[1]
            session.get(User, self.user_id).member_id = self.saved[2]
            for row in session.scalars(select(IssueEvidenceLink).where(IssueEvidenceLink.project_id == _project_id(), IssueEvidenceLink.issue_external_id.in_(list(ISSUES)))).all():
                session.delete(row)
            session.commit()


def _row(issue: str) -> str:
    with get_session() as session:
        return str(session.scalar(select(IssueVerification).where(
            IssueVerification.issue_external_id == issue, IssueVerification.project_id == _project_id(), IssueVerification.decision == "PENDING",
        )).id)


def _with_evidence(verification_id: str) -> None:
    added = acceptance.add_evidence(verification_id, [{"url": "https://docs.example.test/bien-ban-thu"}], actor_id=_cto_id(), allowed_project_ids=None)
    assert added["evidence_status"] == "OK" if "evidence_status" in added else True


def _cto_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(User.id).where(User.auth_subject == "cto")))


def _po_accepts(verification_id: str, user_id: str, **extra) -> dict:
    return acceptance.decide(verification_id, decision="ACCEPTED", reason=None, actor_id=user_id, role="PROJECT_OWNER",
                             allowed_project_ids=frozenset({_project_id()}), **extra)


def _reset_po(verification_id: str, **fields) -> None:
    with get_session() as session:
        row = session.get(IssueVerification, verification_id)
        row.po_decision = row.po_decided_by = row.po_decided_at = None
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def _labels(issue: str, labels: list[str]) -> None:
    with get_session() as session:
        session.scalar(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.issue_external_id == issue, GitLabIssueSnapshot.project_id == _project_id(), GitLabIssueSnapshot.is_current.is_(True),
        )).labels = labels
        session.commit()


def test_owner_accepting_low_risk_work_closes_it_and_p1_is_not_hard() -> None:
    _member()
    _issues()
    try:
        _report("po-final-1", date.today().isoformat(), P1_LINE + "\n\n" + DONE_LINE)
        with _PoFinal() as user_id:
            for issue in ("9702", "9701"):
                verification_id = _row(issue)
                _with_evidence(verification_id)
                listed = owner.get("/api/v1/acceptance")
                assert listed.status_code == 200, listed.text
                shown = [row for row in listed.json()["data"]["today"] + listed.json()["data"]["more"] if row["id"] == verification_id]
                if shown:
                    assert shown[0]["po_final_blockers"] == [] and shown[0]["acceptance_policy"] == "PO_FINAL_LOW_RISK"
                result = _po_accepts(verification_id, user_id)
                assert result["po_decision"] == "ACCEPTED" and result["decision"] == "ACCEPTED", (issue, result["po_final_blockers"])
                assert result["final_by"] == "PO" and result["sync_status"] in ("PENDING", "QUEUE_FAILED")
                target = acceptance.sync_target(verification_id)
                if target is not None:
                    assert target["close"] is True and "Project Owner đã nghiệm thu" in target["note"]
    finally:
        _cleanup()


def test_owner_word_still_waits_for_the_cto_when_the_work_is_risky() -> None:
    _member()
    _issues()
    try:
        _report("po-final-2", date.today().isoformat(), DONE_LINE)
        verification_id = _row("9702")
        # The default policy keeps the CTO on every acceptance.
        with _PoFinal("CTO_ALWAYS") as user_id:
            _with_evidence(verification_id)
            result = _po_accepts(verification_id, user_id)
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["POLICY"] and not result["final_by"]
        with _PoFinal() as user_id:
            # Nothing behind "done": the Owner may say why, but the word is not final.
            _reset_po(verification_id)
            result = _po_accepts(verification_id, user_id, evidence_missing_reason="đã xem trực tiếp")
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["EVIDENCE"]
            _with_evidence(verification_id)
            # P0 stays hard.
            _reset_po(verification_id)
            _labels("9702", ["priority:p0"])
            result = _po_accepts(verification_id, user_id)
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["P0"]
            _labels("9702", ["priority:p3"])
            # The Owner reported the work.
            _reset_po(verification_id, member_id=_po_member())
            result = _po_accepts(verification_id, user_id)
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["SELF"]
            # Someone said "not done" before.
            _reset_po(verification_id, member_id=_member())
            with get_session() as session:
                session.add(IssueVerification(
                    id=str(uuid4()), project_id=_project_id(), issue_external_id="9702", source="REPORT", decision="REJECTED",
                    reason="lần trước chưa đạt", decided_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
                ))
                session.commit()
            result = _po_accepts(verification_id, user_id)
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["REJECTED_BEFORE"]
            # The CTO still closes it.
            closed = cto.post(f"/api/v1/acceptance/{verification_id}/accept", json={})
            assert closed.status_code == 200, closed.text
            assert closed.json()["data"]["final_by"] == "CTO"
    finally:
        _cleanup()


def test_hard_work_stays_with_the_cto() -> None:
    request = _approved("GITLAB")
    _mark_synced(request["id"], "GITLAB", "9702")
    _member()
    _issues()
    try:
        with get_session() as session:
            session.get(IntakeItem, request["id"]).needs_cto_acceptance = True
            session.commit()
        _report("po-final-3", date.today().isoformat(), DONE_LINE)
        verification_id = _row("9702")
        with _PoFinal() as user_id:
            _with_evidence(verification_id)
            result = _po_accepts(verification_id, user_id)
            assert result["decision"] == "PENDING" and result["po_final_blockers"] == ["HARD"] and result["needs_cto_acceptance"] is True
    finally:
        with get_session() as session:
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            session.commit()
        _cleanup()


def test_only_the_cto_sets_who_closes_acceptance() -> None:
    with get_session() as session:
        saved = dict(session.get(Project, _project_id()).project_settings or {})
    try:
        assert owner.put("/api/v1/planning/projects/orbit/acceptance-policy", json={"acceptance_policy": "PO_FINAL_LOW_RISK"}).status_code == 403
        assert cto.put("/api/v1/planning/projects/orbit/acceptance-policy", json={"acceptance_policy": "ANYONE"}).status_code == 422
        changed = cto.put("/api/v1/planning/projects/orbit/acceptance-policy", json={"acceptance_policy": "PO_FINAL_LOW_RISK"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["data"]["acceptance_policy"] == "PO_FINAL_LOW_RISK"
        with get_session() as session:
            assert acceptance.acceptance_policy_of(session, _project_id()) == "PO_FINAL_LOW_RISK"
    finally:
        with get_session() as session:
            session.get(Project, _project_id()).project_settings = saved
            session.commit()
