"""A Project Owner sees only their project's part of a daily report (FR-ID-08): items of other projects are hidden
and counted, a report with nothing of theirs is not listed, and confirming a mixed email is the CTO's."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import EmailMessage, ReportItem

cto = TestClient(app, headers={"X-User-Subject": "cto"})
OWN_PASSWORD = "Owner-pass-2026!"


def _as(subject: str) -> TestClient:
    return TestClient(app, headers={"X-User-Subject": subject})


def _team(project: str) -> dict:
    return cto.get(f"/api/v1/projects/{project}/team").json()["data"]


def _set_team(project: str, owner: str | None, members: list[str] | None = None):
    current = [row["member_id"] for row in _team(project)["members"]]
    return cto.put(f"/api/v1/projects/{project}/team", json={"owner_member_id": owner, "member_ids": list(dict.fromkeys(current + (members or [])))})


def _owner(subject: str, project: str) -> tuple[dict, TestClient]:
    created = cto.post("/api/v1/planning/members", json={"display_name": f"Owner {subject}", "email_reference": f"{subject}@example.test"})
    assert created.status_code == 201, created.text
    member = created.json()["data"]
    response = _set_team(project, member["id"])
    assert response.status_code == 200, response.text
    issued = response.json()["data"]["issued"]
    client = _as(subject)
    changed = client.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": OWN_PASSWORD})
    assert changed.status_code == 200, changed.text
    return member, client


def _report(uid: str, sender: str, name: str, day: str, sections: str) -> dict:
    body = f"BÁO CÁO NGÀY\nNgày: {day} | Nhân sự: {name} | Tổng thời gian: 6 giờ\n\n{sections}\n"
    response = cto.post("/api/v1/reports/daily/ingest", json={
        "mailbox": "report@example.test", "uid_validity": "20261013", "uid": uid, "message_id": f"<scope-{uid}@example.test>",
        "sender_address": sender, "sender_name": name, "subject": f"DAILY REPORT | {day} | {name} | ORBIT", "body": body, "received_at": f"{day}T10:30:00Z",
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_the_owner_sees_their_part_of_a_shared_report_and_cannot_confirm_the_whole() -> None:
    tag = uuid4().hex[:6]
    subject = f"po-scope-{tag}"
    owner, po = _owner(subject, "orbit")
    # A developer on both Orbit (the owner's) and Ember.
    dev = cto.post("/api/v1/planning/members", json={"display_name": f"Dev Scope {tag}", "email_reference": f"dev-scope-{tag}@example.test"})
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["data"]["id"]
    assert _set_team("orbit", owner["id"], [dev_id]).status_code == 200
    ember_owner = _team("ember")["owner_member_id"]
    assert _set_team("ember", ember_owner, [dev_id]).status_code == 200
    sender = f"dev-scope-{tag}@example.test"
    try:
        mixed = _report(f"scope-{tag}-1", sender, f"Dev Scope {tag}", "2026-10-13",
                        "=== ORBIT | Orbit ===\n[DONE] Việc của Orbit | Thời gian: 3 giờ | Tiến độ: 100%\n\n=== EMBER | Ember ===\n[DONE] Việc của Ember | Thời gian: 3 giờ | Tiến độ: 100%")
        only_other = _report(f"scope-{tag}-2", sender, f"Dev Scope {tag}", "2026-10-12",
                             "=== EMBER | Ember ===\n[IN_PROGRESS] Việc chỉ của Ember | Thời gian: 6 giờ | Tiến độ: 40%")
        listed = {row["id"]: row for row in po.get("/api/v1/reports/daily").json()["data"]}
        assert mixed["id"] in listed and only_other["id"] not in listed
        assert listed[mixed["id"]]["item_count"] == 1 and listed[mixed["id"]]["hidden_items"] == 1 and listed[mixed["id"]]["can_review"] is False
        detail = po.get(f"/api/v1/reports/daily/{mixed['id']}").json()["data"]
        assert [item["title"] for item in detail["items"]] == ["Việc của Orbit"]
        assert po.get(f"/api/v1/reports/daily/{mixed['id']}/raw").status_code == 403
        assert po.post(f"/api/v1/reports/daily/{mixed['id']}/review", json={"decision": "CONFIRMED"}).status_code == 403
        ember_item = next(item for item in cto.get(f"/api/v1/reports/daily/{mixed['id']}").json()["data"]["items"] if item["title"] == "Việc của Ember")
        assert po.post(f"/api/v1/reports/daily/{mixed['id']}/items/{ember_item['id']}/issue", json={"no_issue_reason": "MEETING"}).status_code == 404
        assert po.patch(f"/api/v1/reports/daily/{mixed['id']}/items/{ember_item['id']}", json={"title": "x"}).status_code == 404
        own_item = detail["items"][0]
        moved = po.patch(f"/api/v1/reports/daily/{mixed['id']}/items/{own_item['id']}", json={"project_code": "ember"})
        assert moved.status_code == 403
        # The CTO sees the whole email and may confirm it.
        full = cto.get(f"/api/v1/reports/daily/{mixed['id']}").json()["data"]
        assert len(full["items"]) == 2 and full["hidden_items"] == 0 and full["can_review"] is True
    finally:
        with get_session() as session:
            for row in session.scalars(select(EmailMessage).where(EmailMessage.sender_address == sender)).all():
                for item in session.scalars(select(ReportItem).where(ReportItem.email_message_id == row.id)).all():
                    session.delete(item)
                session.delete(row)
            session.commit()
        _set_team("orbit", None)
        _set_team("ember", ember_owner)


def test_work_in_the_catch_all_project_stays_with_the_cto_until_a_report_code_routes_it() -> None:
    """FR-ID-08 since 2026-10-15: a Project Owner does not see work grouped under "Dự án khác"; a report code on
    the project makes the next report land in the project, where its owner sees it (FR-EML-12)."""
    tag = uuid4().hex[:6]
    subject = f"po-other-{tag}"
    owner, po = _owner(subject, "orbit")
    dev = cto.post("/api/v1/planning/members", json={"display_name": f"Dev Other {tag}", "email_reference": f"dev-other-{tag}@example.test"})
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["data"]["id"]
    assert _set_team("orbit", owner["id"], [dev_id]).status_code == 200
    sender = f"dev-other-{tag}@example.test"
    alias = f"AISE{tag.upper()}"
    try:
        stray = _report(f"other-{tag}-1", sender, f"Dev Other {tag}", "2026-10-13",
                        f"=== {alias} | Chatbot ===\n[DONE] Việc của chatbot | Thời gian: 3 giờ | Tiến độ: 100%")
        listed = {row["id"]: row for row in po.get("/api/v1/reports/daily").json()["data"]}
        assert stray["id"] not in listed, "nothing of theirs in it"
        assert po.get(f"/api/v1/reports/daily/{stray['id']}").status_code in (200, 404)
        if po.get(f"/api/v1/reports/daily/{stray['id']}").status_code == 200:
            assert po.get(f"/api/v1/reports/daily/{stray['id']}").json()["data"]["items"] == []
        # The CTO sees it under the catch-all project and gives Orbit the code.
        full = cto.get(f"/api/v1/reports/daily/{stray['id']}").json()["data"]
        assert [item["reported_project_code"] for item in full["items"]] == [alias]
        assert po.put("/api/v1/projects/ember/report-codes", json={"codes": [alias]}).status_code == 404, "not their project"
        saved = cto.put("/api/v1/projects/orbit/report-codes", json={"codes": [alias.lower(), alias]})
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["codes"] == [alias]
        assert cto.get("/api/v1/projects/orbit/report-codes").json()["data"]["codes"] == [alias]
        clash = cto.put("/api/v1/projects/ember/report-codes", json={"codes": [alias]})
        assert clash.status_code == 409 and "REPORT_CODE_TAKEN" in clash.text
        bad = cto.put("/api/v1/projects/ember/report-codes", json={"codes": ["AISE (thử)"]})
        assert bad.status_code == 422 and "REPORT_CODE_INVALID" in bad.text
        routed = _report(f"other-{tag}-2", sender, f"Dev Other {tag}", "2026-10-14",
                         f"=== {alias} | Chatbot ===\n[IN_PROGRESS] Việc của chatbot ngày sau | Thời gian: 2 giờ | Tiến độ: 50%")
        listed = {row["id"]: row for row in po.get("/api/v1/reports/daily").json()["data"]}
        assert routed["id"] in listed and listed[routed["id"]]["item_count"] == 1
        assert [item["title"] for item in po.get(f"/api/v1/reports/daily/{routed['id']}").json()["data"]["items"]] == ["Việc của chatbot ngày sau"]
    finally:
        cto.put("/api/v1/projects/orbit/report-codes", json={"codes": []})
        with get_session() as session:
            for row in session.scalars(select(EmailMessage).where(EmailMessage.sender_address == sender)).all():
                for item in session.scalars(select(ReportItem).where(ReportItem.email_message_id == row.id)).all():
                    session.delete(item)
                session.delete(row)
            session.commit()
