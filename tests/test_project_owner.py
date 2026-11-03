"""Project Owners work only in the projects they own (ADR-0022, ADR-0023).

A project has exactly one Project Owner, chosen from the staff list on the project itself, and any
number of members. Only the owner logs in. The important property is isolation: whatever the owner
of one project asks for, nothing that belongs to another project comes back or changes.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, IntakeItem, User, WorkforceMember
from app.modules.meetings.service import meeting_service


cto = TestClient(app, headers={"X-User-Subject": "cto"})
OWN_PASSWORD = "a-long-own-password-1"


def _as(subject: str) -> TestClient:
    return TestClient(app, headers={"X-User-Subject": subject})


def _staff(name: str, email: str | None) -> dict:
    created = cto.post("/api/v1/planning/members", json={"display_name": name, "email_reference": email})
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _team(project: str) -> dict:
    return cto.get(f"/api/v1/projects/{project}/team").json()["data"]


def _set_team(project: str, owner: str | None, members: list[str] | None = None, keep: bool = True):
    """Choose the owner (and members). By default people already on the project stay on it."""
    current = [row["member_id"] for row in _team(project)["members"]] if keep else []
    return cto.put(f"/api/v1/projects/{project}/team", json={"owner_member_id": owner, "member_ids": list(dict.fromkeys(current + (members or [])))})


def _owner(subject: str, projects: list[str]) -> tuple[dict, str, TestClient]:
    """A staff member made Project Owner of `projects`, logged in with their own password."""
    member = _staff(f"Owner {subject}", f"{subject}@example.test")
    issued = None
    for project in projects:
        response = _set_team(project, member["id"])
        assert response.status_code == 200, response.text
        issued = issued or response.json()["data"]["issued"]
    assert issued is not None and issued["subject"] == subject
    client = _as(subject)
    # A temporary password must be replaced before anything else works.
    blocked = client.get("/api/v1/intakes")
    assert blocked.status_code == 403 and "PASSWORD_CHANGE_REQUIRED" in blocked.text
    changed = client.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": OWN_PASSWORD})
    assert changed.status_code == 200, changed.text
    return member, issued["temporary_password"], client


def _account(subject: str) -> dict:
    return next(row for row in cto.get("/api/v1/users").json()["data"] if row["subject"] == subject)


def _pending_intake(project: str, text: str) -> dict:
    intake = cto.post("/api/v1/intakes", json={"project_id": project, "channel": "MANUAL", "raw_text": text}).json()["data"]
    with get_session() as session:
        item = session.get(IntakeItem, intake["id"])
        item.status, item.item_type = "PENDING_APPROVAL", "TASK"
        item.normalized_title, item.normalized_summary = text[:60], text
        session.commit()
    return cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]


def test_a_project_has_one_owner_from_the_staff_list_and_many_members() -> None:
    first = _staff("Team Nhân sự 1", "team.one@example.test")
    second = _staff("Team Nhân sự 2", "team.two@example.test")
    third = _staff("Team Nhân sự 3", None)
    fourth = _staff("Team Nhân sự 4", "team.four@example.test")

    # Project 1: owner is person 1, members are persons 2 and 4.
    saved = cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": first["id"], "member_ids": [second["id"], fourth["id"]]})
    assert saved.status_code == 200, saved.text
    team = saved.json()["data"]
    assert team["owner_member_id"] == first["id"]
    assert [(row["display_name"], row["is_owner"]) for row in team["members"]] == [("Team Nhân sự 1", True), ("Team Nhân sự 2", False), ("Team Nhân sự 4", False)]
    # Only the owner gets a login; its temporary password is shown once.
    assert team["issued"]["subject"] == "team.one" and len(team["issued"]["temporary_password"]) >= 12
    assert [row["account_subject"] for row in team["members"]] == ["team.one", None, None]
    assert _team("orbit")["issued"] is None
    assert cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": first["id"], "member_ids": [second["id"], fourth["id"]]}).json()["data"]["issued"] is None
    listed = {row["code"]: row for row in cto.get("/api/v1/projects").json()["data"]}
    assert listed["orbit"]["owner_name"] == "Team Nhân sự 1" and listed["orbit"]["owner_member_id"] == first["id"]
    account = _account("team.one")
    assert account["member_id"] == first["id"] and [p["code"] for p in account["projects"]] == ["orbit"] and account["is_active"] is True

    # Project 2: owner is person 2 (a member of project 1), members are persons 3 and 4.
    second_team = cto.put("/api/v1/projects/ember/team", json={"owner_member_id": second["id"], "member_ids": [third["id"], fourth["id"]]}).json()["data"]
    assert second_team["issued"]["subject"] == "team.two"
    assert [(row["display_name"], row["is_owner"]) for row in second_team["members"]] == [("Team Nhân sự 2", True), ("Team Nhân sự 3", False), ("Team Nhân sự 4", False)]
    owner_two = _as("team.two")
    owner_two.post("/api/v1/auth/password", json={"current_password": second_team["issued"]["temporary_password"], "new_password": OWN_PASSWORD})
    # Being a member of project 1 gives person 2 no access there; owning project 2 does.
    assert [p["code"] for p in owner_two.get("/api/v1/projects").json()["data"]] == ["ember"]

    # Replacing the owner: the old owner loses the project at once and, owning nothing else, is locked.
    replaced = cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": fourth["id"], "member_ids": [first["id"], second["id"]]}).json()["data"]
    assert replaced["owner_member_id"] == fourth["id"] and replaced["issued"]["subject"] == "team.four"
    assert sum(row["is_owner"] for row in replaced["members"]) == 1
    old = _account("team.one")
    assert old["projects"] == [] and old["is_active"] is False
    assert _as("team.one").get("/api/v1/auth/me").status_code == 401

    # One person may own several projects; they are locked only when the last one is taken away.
    both = cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": second["id"], "member_ids": [first["id"], fourth["id"]]}).json()["data"]
    assert both["issued"] is None and sorted(p["code"] for p in _account("team.two")["projects"]) == ["ember", "orbit"]
    assert _account("team.four")["is_active"] is False
    cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": None, "member_ids": [first["id"], second["id"], fourth["id"]]})
    assert _account("team.two")["is_active"] is True and [p["code"] for p in _account("team.two")["projects"]] == ["ember"]
    assert cto.get("/api/v1/projects").json()["data"] and {row["code"]: row for row in cto.get("/api/v1/projects").json()["data"]}["orbit"]["owner_name"] is None

    # Choosing a locked former owner again unlocks the account with a fresh temporary password.
    again = cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": first["id"], "member_ids": [second["id"], fourth["id"]]}).json()["data"]
    assert again["issued"]["subject"] == "team.one" and _account("team.one")["is_active"] is True and _account("team.one")["must_change_password"] is True

    # Rules that keep the model consistent.
    no_email = cto.put("/api/v1/projects/ember/team", json={"owner_member_id": third["id"], "member_ids": []})
    assert no_email.status_code == 422 and "OWNER_EMAIL_REQUIRED" in no_email.text
    assert _team("ember")["owner_member_id"] == second["id"]
    unknown = cto.put("/api/v1/projects/ember/team", json={"owner_member_id": None, "member_ids": ["00000000-0000-4000-8000-00000000dead"]})
    assert unknown.status_code == 422 and "MEMBER_NOT_ACTIVE" in unknown.text
    assert cto.get("/api/v1/projects/nope/team").status_code == 404
    # The owner stays a member: their own record cannot drop the project or be deactivated.
    body = {"display_name": "Team Nhân sự 1", "email_reference": "team.one@example.test", "status": "ACTIVE", "project_mappings": []}
    assert "MEMBER_OWNS_PROJECT" in cto.put(f"/api/v1/planning/members/{first['id']}", json=body).text
    assert "MEMBER_OWNS_PROJECT" in cto.put(f"/api/v1/planning/members/{first['id']}", json={**body, "status": "INACTIVE", "project_mappings": [{"project_id": "orbit"}]}).text
    # Project grants are no longer handed out on the account itself.
    assert "PROJECTS_ASSIGNED_ON_PROJECT" in cto.patch(f"/api/v1/users/{old['id']}", json={"project_ids": ["ember"]}).text
    assert "PROJECTS_ASSIGNED_ON_PROJECT" in cto.post("/api/v1/users", json={"subject": "x.direct", "email": "x.direct@example.test", "display_name": "X", "project_ids": ["ember"]}).text
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "project.team_changed")) is not None
    # The owner can now read the team, find active staff, and add one person without receiving the CTO's replace-team power.
    owner_team = owner_two.get("/api/v1/projects/ember/team")
    assert owner_team.status_code == 200 and owner_team.json()["data"]["owner_member_id"] == second["id"]
    candidates = owner_two.get("/api/v1/projects/ember/team/candidates")
    assert candidates.status_code == 200 and first["id"] in {row["member_id"] for row in candidates.json()["data"]}
    added = owner_two.post("/api/v1/projects/ember/team/members", json={"member_id": first["id"]})
    assert added.status_code == 200 and added.json()["data"]["added"] is True
    assert first["id"] in {row["member_id"] for row in added.json()["data"]["team"]["members"]}
    repeated = owner_two.post("/api/v1/projects/ember/team/members", json={"member_id": first["id"]})
    assert repeated.status_code == 200 and repeated.json()["data"]["added"] is False
    assert len([row for row in repeated.json()["data"]["team"]["members"] if row["member_id"] == first["id"]]) == 1
    profile = next(row for row in cto.get("/api/v1/planning/members?include_inactive=true").json()["data"] if row["id"] == first["id"])
    edit_body = {
        "display_name": "Team Nhân sự 1 đã sửa", "email_reference": "team.one.updated@example.test",
        "default_weekday_hours": profile["default_weekday_hours"], "status": profile["status"],
        "project_mappings": [mapping for mapping in profile["project_mappings"] if mapping["active"]],
    }
    assert owner_two.put(f"/api/v1/planning/members/{first['id']}", json=edit_body).status_code == 403
    edited = cto.put(f"/api/v1/planning/members/{first['id']}", json=edit_body)
    assert edited.status_code == 200 and edited.json()["data"]["display_name"] == "Team Nhân sự 1 đã sửa"
    assert next(row for row in _team("ember")["members"] if row["member_id"] == first["id"])["email"] == "team.one.updated@example.test"
    # The owner may take someone off their own project, but not themselves while they are the owner (ADR-0072).
    assert "MEMBER_OWNS_PROJECT" in owner_two.delete(f"/api/v1/projects/ember/team/members/{second['id']}").text
    assert "MEMBER_OWNS_PROJECT" in cto.delete(f"/api/v1/projects/ember/team/members/{second['id']}").text
    assert owner_two.delete(f"/api/v1/projects/orbit/team/members/{first['id']}").status_code == 404
    removed = owner_two.delete(f"/api/v1/projects/ember/team/members/{first['id']}")
    assert removed.status_code == 200 and removed.json()["data"]["removed"] is True
    assert first["id"] not in {row["member_id"] for row in removed.json()["data"]["team"]["members"]}
    assert cto.delete(f"/api/v1/projects/ember/team/members/{first['id']}").json()["data"]["removed"] is False
    with get_session() as session:
        assert session.get(WorkforceMember, first["id"]) is not None
    assert _account("team.one")["is_active"] is True
    assert first["id"] in {row["member_id"] for row in _team("orbit")["members"]}
    assert owner_two.get("/api/v1/projects/orbit/team").status_code == 404
    assert owner_two.post("/api/v1/projects/orbit/team/members", json={"member_id": third["id"]}).status_code == 404
    assert owner_two.put("/api/v1/projects/ember/team", json={"owner_member_id": None, "member_ids": []}).status_code == 403
    with get_session() as session:
        owner_user = session.scalar(select(User).where(User.auth_subject == "team.two"))
        events = session.scalars(select(AuditEvent).where(
            AuditEvent.event_type == "project.member_added", AuditEvent.actor_id == owner_user.id,
        )).all()
        assert len(events) == 1 and events[0].details["member_id"] == first["id"]
        # The owner took the person off, so the audit names the owner (ADR-0072).
        removed_events = session.scalars(select(AuditEvent).where(
            AuditEvent.event_type == "project.member_removed", AuditEvent.entity_id == second_team["project_id"],
            AuditEvent.actor_id == owner_user.id,
        )).all()
        assert len(removed_events) == 1 and removed_events[0].details["member_id"] == first["id"]
    cto.put("/api/v1/projects/ember/team", json={"owner_member_id": None, "member_ids": []})
    cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": None, "member_ids": []})


def test_cto_manages_accounts_and_temporary_passwords() -> None:
    member, temporary, client = _owner("owner.accounts", ["orbit"])
    account = _account("owner.accounts")
    assert account["role"] == "PROJECT_OWNER" and [p["code"] for p in account["projects"]] == ["orbit"] and account["member_id"] == member["id"]
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["role"] == "PROJECT_OWNER" and len(me["project_ids"]) == 1 and me["must_change_password"] is False
    assert cto.get("/api/v1/auth/me").json()["data"]["project_ids"] is None
    assert "password" not in str(account).lower().replace("must_change_password", "")

    # Only the CTO manages accounts, and the CTO account itself is protected.
    for call in (client.get("/api/v1/users"), client.post("/api/v1/users", json={"subject": "x.y.z", "email": "x@example.test", "display_name": "X"}),
                 client.patch(f"/api/v1/users/{account['id']}", json={"is_active": True}), client.post(f"/api/v1/users/{account['id']}/reset-password")):
        assert call.status_code == 403
    with get_session() as session:
        cto_id = str(session.scalar(select(User.id).where(User.auth_subject == "cto")))
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "user.created", AuditEvent.entity_id == account["id"])) is not None
    assert "CTO_ACCOUNT_PROTECTED" in cto.patch(f"/api/v1/users/{cto_id}", json={"is_active": False}).text
    assert "CTO_ACCOUNT_PROTECTED" in cto.post(f"/api/v1/users/{cto_id}/reset-password").text

    assert "PASSWORD_TOO_SHORT" in client.post("/api/v1/auth/password", json={"current_password": OWN_PASSWORD, "new_password": "short"}).text
    assert "PASSWORD_INCORRECT" in client.post("/api/v1/auth/password", json={"current_password": temporary, "new_password": "another-long-password-2"}).text

    reset = cto.post(f"/api/v1/users/{account['id']}/reset-password").json()["data"]
    assert reset["temporary_password"] != temporary and reset["account"]["must_change_password"] is True
    assert client.get("/api/v1/intakes").status_code == 403

    # Locking takes effect on the next request, without waiting for the session to expire.
    assert cto.patch(f"/api/v1/users/{account['id']}", json={"is_active": False}).json()["data"]["is_active"] is False
    assert client.get("/api/v1/auth/me").status_code == 401


def test_project_owner_sees_and_decides_only_inside_owned_projects() -> None:
    _, _, owner = _owner("owner.orbit", ["orbit"])
    mine = _pending_intake("orbit", "Việc của Orbit cho owner xử lý")
    theirs = _pending_intake("ember", "Việc của Ember, owner Orbit không được thấy")

    assert [p["code"] for p in owner.get("/api/v1/projects").json()["data"]] == ["orbit"]
    page = owner.get("/api/v1/intakes?limit=100").json()["data"]
    ids = {row["id"] for row in page["items"]}
    assert mine["id"] in ids and theirs["id"] not in ids
    everything = cto.get("/api/v1/intakes?limit=100").json()["data"]
    assert page["summary"]["total_items"] < everything["summary"]["total_items"]
    assert page["summary"]["pending_approval"] < everything["summary"]["pending_approval"]
    # Asking for another project by name returns nothing rather than that project's items.
    assert owner.get("/api/v1/intakes?project_id=ember").json()["data"]["items"] == []
    assert owner.get(f"/api/v1/intakes?search={theirs['public_id']}").json()["data"]["items"] == []
    queue = {row["id"] for row in owner.get("/api/v1/approvals?limit=100").json()["data"]["items"]}
    assert mine["id"] in queue and theirs["id"] not in queue

    # Every route that takes an Intake of another project answers "not found".
    other = theirs["id"]
    decision = {"approved_route": "WORK", "approved_priority": "P2", "expected_version": theirs["version"]}
    action = {"expected_version": theirs["version"], "reason": "x"}
    review = {"normalized_title": "Đã sửa", "normalized_summary": "Đã sửa", "expected_version": theirs["version"]}
    blocked = [
        owner.get(f"/api/v1/intakes/{other}"), owner.get(f"/api/v1/intakes/{other}/raw"), owner.get(f"/api/v1/intakes/{other}/runs"),
        owner.get(f"/api/v1/intakes/{other}/pipeline"), owner.get(f"/api/v1/intakes/{other}/sync-status"),
        owner.get(f"/api/v1/intakes/{other}/attachments/missing/file"),
        owner.patch(f"/api/v1/intakes/{other}/review", json=review), owner.post(f"/api/v1/intakes/{other}/process"),
        owner.post(f"/api/v1/intakes/{other}/approve", json=decision), owner.post(f"/api/v1/intakes/{other}/reject", json=action),
        owner.post(f"/api/v1/intakes/{other}/defer", json=action), owner.post(f"/api/v1/intakes/{other}/needs-information", json=action),
        owner.post(f"/api/v1/intakes/{other}/attachments", files={"file": ("a.txt", b"x", "text/plain")}),
        owner.post("/api/v1/intakes", json={"project_id": "ember", "channel": "MANUAL", "raw_text": "chèn vào dự án khác"}),
    ]
    assert [call.status_code for call in blocked] == [404] * len(blocked)
    untouched = cto.get(f"/api/v1/intakes/{other}").json()["data"]
    assert untouched["status"] == "PENDING_APPROVAL" and untouched["version"] == theirs["version"] and untouched["normalized_title"] == theirs["normalized_title"]

    # Inside the owned project the owner reads the original text, creates, and approves.
    raw = owner.get(f"/api/v1/intakes/{mine['id']}/raw")
    assert raw.status_code == 200 and raw.json()["data"]["raw_text"] == "Việc của Orbit cho owner xử lý"
    created = owner.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Owner tự nhập một yêu cầu"})
    assert created.status_code == 201, created.text
    approved = owner.post(f"/api/v1/intakes/{mine['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P1", "expected_version": mine["version"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "APPROVED" and approved.json()["data"]["approved_priority"] == "P1"

    # The snapshot of another project's approval cannot be queued for sync by this owner.
    cto.post(f"/api/v1/intakes/{other}/approve", json=decision)
    snapshot = cto.get(f"/api/v1/intakes/{other}/sync-status").json()["data"]["snapshot_id"]
    assert snapshot and owner.post(f"/api/v1/approval-snapshots/{snapshot}/sync").status_code == 404

    # Everything outside the opened areas stays CTO-only.
    closed = [
        owner.get("/api/v1/operations/status"), owner.get("/api/v1/reports/mailbox"), owner.post("/api/v1/reports/mailbox/scan"),
        owner.post("/api/v1/projects", json={"name": "X", "code": "owner-made", "intake_key": "OWN", "kind": "IDEA"}),
        owner.patch("/api/v1/projects/orbit", json={"name": "Đổi tên"}), owner.post("/api/v1/projects/integration-probes", json={"system": "PLANE", "action": "LIST"}),
        owner.put("/api/v1/projects/orbit/team", json={"owner_member_id": None, "member_ids": []}),
    ]
    assert [call.status_code for call in closed] == [403] * len(closed)


def test_project_owner_meetings_and_glossary_are_scoped(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "meeting_capture_enabled", True)
    _, _, owner = _owner("owner.meet", ["orbit"])
    own = owner.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"})
    assert own.status_code == 201, own.text
    other = cto.post("/api/v1/meetings", json={"project_id": "ember", "source": "MIC"}).json()["data"]

    listed = {row["id"] for row in owner.get("/api/v1/meetings").json()["data"]}
    assert own.json()["data"]["id"] in listed and other["id"] not in listed
    assert owner.post("/api/v1/meetings", json={"project_id": "ember", "source": "MIC"}).status_code == 404
    base = f"/api/v1/meetings/{other['id']}"
    blocked = [
        owner.get(base), owner.get(f"{base}/audio"), owner.post(f"{base}/finish"),
        owner.post(f"{base}/audio?sequence=0", files={"file": ("a.webm", b"x", "audio/webm")}),
        owner.patch(f"{base}/project", json={"project_id": "orbit"}), owner.patch(f"{base}/speakers", json={"names": {"Thành viên 1": "A"}}),
        owner.patch(f"{base}/note", json={"summary": "x"}), owner.post(f"{base}/note/regenerate"),
        owner.delete(f"{base}/note/items/00000000-0000-4000-8000-000000000001"),
        owner.post(f"{base}/note/items/00000000-0000-4000-8000-000000000001/intake"),
    ]
    assert [call.status_code for call in blocked] == [404] * len(blocked)
    # Moving an own meeting into a project that is not owned is refused as well.
    assert owner.patch(f"/api/v1/meetings/{own.json()['data']['id']}/project", json={"project_id": "ember"}).status_code == 404
    assert meeting_service.project_of(other["id"])[1] is not None

    # Glossary: own project's terms can be managed; shared terms and other projects cannot.
    term = owner.post("/api/v1/meetings/glossary", json={"term": "OwnerTerm", "project_id": "orbit"})
    assert term.status_code in (200, 201), term.text
    assert owner.post("/api/v1/meetings/glossary", json={"term": "Shared", "project_id": None}).status_code == 403
    assert owner.post("/api/v1/meetings/glossary", json={"term": "Theirs", "project_id": "ember"}).status_code == 404
    assert owner.get("/api/v1/meetings/glossary?project_id=ember").status_code == 404
    assert owner.get("/api/v1/meetings/glossary?project_id=orbit").status_code == 200
    shared = cto.post("/api/v1/meetings/glossary", json={"term": "SharedByCto", "project_id": None}).json()["data"]
    foreign = cto.post("/api/v1/meetings/glossary", json={"term": "EmberTerm", "project_id": "ember"}).json()["data"]
    assert owner.delete(f"/api/v1/meetings/glossary/{shared['id']}").status_code == 403
    assert owner.delete(f"/api/v1/meetings/glossary/{foreign['id']}").status_code == 404
    assert owner.delete(f"/api/v1/meetings/glossary/{term.json()['data']['id']}").status_code == 200


def test_taking_a_project_away_takes_effect_immediately() -> None:
    member, _, owner = _owner("owner.revoke", ["orbit", "ember"])
    intake = _pending_intake("ember", "Việc Ember trước khi đổi owner")
    assert owner.get(f"/api/v1/intakes/{intake['id']}").status_code == 200
    assert _set_team("ember", None).status_code == 200
    assert [p["code"] for p in _account("owner.revoke")["projects"]] == ["orbit"]
    assert owner.get(f"/api/v1/intakes/{intake['id']}").status_code == 404
    assert [p["code"] for p in owner.get("/api/v1/projects").json()["data"]] == ["orbit"]
    # Losing the last project locks the account.
    assert _set_team("orbit", None).status_code == 200
    assert _account("owner.revoke")["is_active"] is False and owner.get("/api/v1/intakes").status_code == 401
    # They are still a member of both projects for planning, just without a login.
    assert member["id"] in {row["member_id"] for row in _team("ember")["members"]}


def test_capacity_lists_only_the_scope_team_and_counts_hours_planned_elsewhere() -> None:
    from app.models import GitLabIssueSnapshot, WorkforceProjectMembership

    owner = _staff("Cap Owner", "cap.owner@example.test")
    shared = _staff("Cap Shared", "cap.shared@example.test")
    outsider = _staff("Cap Outsider", "cap.outsider@example.test")
    assert cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": owner["id"], "member_ids": [shared["id"]]}).status_code == 200
    assert cto.put("/api/v1/projects/ember/team", json={"owner_member_id": None, "member_ids": [shared["id"]]}).status_code == 200
    day = "2026-12-22"

    def names(path: str) -> list[str]:
        return [row["display_name"] for row in cto.get(path).json()["data"]]

    orbit = cto.get(f"/api/v1/planning/capacities/{day}?project_id=orbit").json()["data"]
    # Only the project's own people, owner first; nobody from outside the project.
    assert [(row["display_name"], row["is_owner"]) for row in orbit] == [("Cap Owner", True), ("Cap Shared", False)]
    assert names(f"/api/v1/planning/capacities/{day}?project_id=ember") == ["Cap Shared"]
    everyone = names(f"/api/v1/planning/capacities/{day}")
    assert "Cap Owner" in everyone and "Cap Shared" in everyone and "Cap Outsider" not in everyone
    assert outsider["id"] not in {row["member_id"] for row in cto.get(f"/api/v1/planning/capacities/{day}").json()["data"]}
    assert cto.get(f"/api/v1/planning/capacities/{day}?project_id=nope").status_code in (404, 422)

    # One Issue occupies one half-day in Ember; Orbit's view still has the other half-day available.
    with get_session() as session:
        from app.models import Project
        ember = session.scalar(select(Project).where(Project.code == "ember"))
        orbit = session.scalar(select(Project).where(Project.code == "orbit"))
        for project in (ember, orbit):
            membership = session.scalar(select(WorkforceProjectMembership).where(
                WorkforceProjectMembership.member_id == shared["id"], WorkforceProjectMembership.project_id == project.id,
            ))
            membership.gitlab_user_external_id = "4242"
        from datetime import datetime, timezone
        from uuid import uuid4
        now = datetime.now(timezone.utc)
        for project, issue in ((ember, "9101"), (orbit, "9102")):
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project.id, issue_external_id=issue, title=f"Capacity issue {issue}", state="opened",
                labels=["priority:p2"], assignee_external_ids=["4242"], milestone_external_id="1", milestone_title="M1",
                due_date=None, web_url=None, payload_hash=f"cap-{issue}", is_current=True, fetched_at=now, last_seen_at=now,
            ))
        session.commit()
    ember_run = cto.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["ember"]}).json()["data"]
    assert sum(a["planned_hours"] for a in ember_run["assignments"] if a["member_id"] == shared["id"]) == 4
    after = {row["display_name"]: row for row in cto.get(f"/api/v1/planning/capacities/{day}?project_id=orbit").json()["data"]}
    assert after["Cap Shared"]["planned_elsewhere_hours"] == 4 and after["Cap Shared"]["remaining_hours"] == 4 and after["Cap Shared"]["available_hours"] == 8
    assert after["Cap Owner"]["planned_elsewhere_hours"] == 0 and after["Cap Owner"]["remaining_hours"] == 8
    # Inside Ember's own view those hours are not "elsewhere".
    own = cto.get(f"/api/v1/planning/capacities/{day}?project_id=ember").json()["data"][0]
    assert own["planned_elsewhere_hours"] == 0 and own["remaining_hours"] == 8

    # The remaining half-day can hold one different Issue in Orbit.
    orbit_run = cto.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    shared_orbit = [a for a in orbit_run["assignments"] if a["member_id"] == shared["id"]]
    assert len(shared_orbit) == 1 and shared_orbit[0]["planned_hours"] == 4
    cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": None, "member_ids": []})
    cto.put("/api/v1/projects/ember/team", json={"owner_member_id": None, "member_ids": []})


def test_project_owner_reviews_reports_plans_work_and_sets_hours_only_for_own_team() -> None:
    """ADR-0026: the owner does the daily work for their team; the CTO still approves requests and closes the plan."""
    import hashlib
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.models import GitLabIssueSnapshot, Project
    from app.modules.reports.service import daily_report_service

    owner_member, _, owner = _owner("owner.daily", ["orbit"])
    mate = _staff("Daily Mate", "daily.mate@example.test")
    stranger = _staff("Daily Stranger", "daily.stranger@example.test")
    assert cto.put("/api/v1/projects/orbit/team", json={"owner_member_id": owner_member["id"], "member_ids": [mate["id"]]}).status_code == 200
    assert _set_team("ember", None, [stranger["id"]]).status_code == 200
    day = "2026-12-28"

    # Staff: the owner's own team, with no trace of other projects.
    team = owner.get("/api/v1/planning/members").json()["data"]
    assert {row["id"] for row in team} == {owner_member["id"], mate["id"]}
    orbit_id = next(row["id"] for row in cto.get("/api/v1/projects").json()["data"] if row["code"] == "orbit")
    assert {mapping["project_id"] for row in team for mapping in row["project_mappings"]} == {orbit_id}

    # Hours: the owner's team only, and always for a named project of theirs.
    assert owner.get(f"/api/v1/planning/capacities/{day}").status_code == 404
    assert owner.get(f"/api/v1/planning/capacities/{day}?project_id=ember").status_code == 404
    listed = owner.get(f"/api/v1/planning/capacities/{day}?project_id=orbit")
    assert listed.status_code == 200 and mate["id"] in {row["member_id"] for row in listed.json()["data"]}
    hours = {"expected_version": 0, "override_hours": 4, "fixed_hours": 0, "reason": "Nghỉ nửa ngày"}
    assert owner.put(f"/api/v1/planning/capacities/{day}/{mate['id']}", json=hours).json()["data"]["available_hours"] == 4
    assert owner.put(f"/api/v1/planning/capacities/{day}/{stranger['id']}", json=hours).status_code == 404

    # Plans: one over the owner's project. A plan over everything, or over another project, is not theirs.
    everything = cto.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": []}).json()["data"]
    assert owner.get(f"/api/v1/planning/runs/{everything['id']}").status_code == 404
    assert owner.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": []}).status_code == 404
    assert owner.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["ember"]}).status_code == 404
    opened = owner.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]})
    assert opened.status_code == 201, opened.text
    run = opened.json()["data"]
    assert run["project_ids"] == [orbit_id]
    base = f"/api/v1/planning/runs/{run['id']}"

    # Arranging work is the owner's, including work that needs a new Issue; closing the plan is not.
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project.id, issue_external_id="8801", title="Việc của đội owner.daily", state="opened",
            labels=["priority:p2"], assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=None, payload_hash=hashlib.sha256(b"owner.daily:8801").hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()
    assert "8801" in {row.get("issue_external_id") for row in owner.get(f"{base}/work-items?search=8801").json()["data"]}
    existing = owner.post(f"{base}/work", json={"expected_run_version": run["version"], "project_id": "orbit", "source": "ISSUE", "issue_external_id": "8801"})
    assert existing.status_code == 201, existing.text
    fresh = owner.post(f"{base}/work", json={
        "expected_run_version": 1, "project_id": "orbit", "source": "NEW", "title": "Việc mới chưa duyệt", "content": "Nội dung", "reason": "Gấp trong ngày",
    })
    # An owner approves requests in their own project, so they may also add work that has no Issue yet.
    assert fresh.status_code != 403 and "CTO_APPROVAL_REQUIRED" not in fresh.text, fresh.text
    waiting = owner.get(base).json()["data"]["candidates"]
    assert waiting, "the Issue added without a person waits for assignment"
    created = owner.post(f"{base}/candidates/{waiting[0]['id']}/assign", json={
        "expected_run_version": 1, "member_id": mate["id"], "slot": "MORNING", "planned_hours": 2, "issue_mode": "CREATE", "reason": "Tạo Issue mới",
    })
    assert created.status_code != 403 and "CTO_APPROVAL_REQUIRED" not in created.text, created.text
    assert owner.post(f"{base}/candidates/{waiting[0]['id']}/dismiss").status_code == 200
    assert owner.post(f"{base}/candidates/{waiting[0]['id']}/restore").status_code == 200
    closing = [
        owner.post(f"{base}/accept-proposals", json={"expected_version": 1}),
        owner.post(f"{base}/approve", json={"expected_version": 1, "acknowledged_warning_ids": []}),
        owner.get(f"{base}/sync-jobs"),
    ]
    # Since ADR-0051 the owner closes the plan of their own project: nothing here is a permission refusal any more.
    assert all(call.status_code != 403 for call in closing), [call.status_code for call in closing]
    assert closing[2].status_code == 200

    # Reports: those sent by the owner's team, and nobody else's.
    def report(uid: str, sender: str) -> str:
        return str(daily_report_service.ingest(
            mailbox="report@example.test", uid_validity="20261228", uid=uid, message_id=f"<owner-daily-{uid}@example.test>",
            sender_address=sender, sender_name=sender, subject="Báo cáo ngày 27/12", body="Hôm nay làm việc với khách.",
            received_at=datetime(2026, 12, 27, 11, 0, tzinfo=timezone.utc),
        )["id"])

    mine, theirs = report("9001", "daily.mate@example.test"), report("9002", "daily.stranger@example.test")
    seen = {row["id"] for row in owner.get("/api/v1/reports/daily").json()["data"]}
    assert mine in seen and theirs not in seen
    assert owner.get(f"/api/v1/reports/daily/{mine}").status_code == 200
    assert owner.get(f"/api/v1/reports/daily/{mine}/raw").status_code == 200
    reviewed = owner.post(f"/api/v1/reports/daily/{mine}/review", json={"decision": "CONFIRMED"})
    assert reviewed.status_code == 200 and reviewed.json()["data"]["review_decision"] == "CONFIRMED"
    for call in (
        owner.get(f"/api/v1/reports/daily/{theirs}"), owner.get(f"/api/v1/reports/daily/{theirs}/raw"),
        owner.post(f"/api/v1/reports/daily/{theirs}/review", json={"decision": "REJECTED"}),
    ):
        assert call.status_code == 404
    assert cto.get(f"/api/v1/reports/daily/{theirs}").json()["data"]["review_decision"] is None
    # Reading the original text is recorded under the owner's name.
    with get_session() as session:
        reader = session.scalar(select(User).where(User.auth_subject == "owner.daily"))
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "report.raw.read", AuditEvent.entity_id == mine, AuditEvent.actor_id == reader.id,
        )) is not None



def test_day_status_reads_a_plan_without_opening_one() -> None:
    """FR-UI-12: the home page asks where today's plan stands; asking never creates a plan."""
    _, _, owner = _owner("owner.today", ["orbit"])
    day = "2027-03-17"
    empty = owner.get(f"/api/v1/planning/days/{day}?project_id=orbit")
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] == {"plan_date": day, "run_id": None, "status": None, "assigned": 0, "waiting": 0}
    assert owner.get(f"/api/v1/planning/days/{day}?project_id=orbit").json()["data"]["run_id"] is None

    opened = owner.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"], "timezone": "Asia/Ho_Chi_Minh"})
    assert opened.status_code in (200, 201), opened.text
    run = opened.json()["data"]
    seen = owner.get(f"/api/v1/planning/days/{day}?project_id=orbit").json()["data"]
    assert seen["run_id"] == run["id"] and seen["status"] == run["status"]
    assert seen["assigned"] == len(run["assignments"])
    assert seen["waiting"] == len([row for row in run["candidates"] if row["status"] in ("PENDING_TRIAGE", "READY")])

    # Another project's plan, and the all-projects plan, are not the owner's to read.
    assert owner.get(f"/api/v1/planning/days/{day}?project_id=ember").status_code == 404
    assert owner.get(f"/api/v1/planning/days/{day}").status_code == 404
    assert cto.get(f"/api/v1/planning/days/{day}").json()["data"]["run_id"] is None
