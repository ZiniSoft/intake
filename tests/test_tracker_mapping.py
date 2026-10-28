"""Who is who on the tracker (FR-PLAN-32, ADR-0056): matching by email and name, filling unique matches, a Project
Owner or the CTO naming the user for their project, and the Issue's assignee offered as a mapping."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Project, WorkforceMember, WorkforceProjectMembership
from app.modules.planning import mapping

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
USERS = [
    {"id": "501", "name": "Trần Văn Đoàn", "username": "doan.tran", "email": None},
    {"id": "502", "name": "Doan Tran", "username": "doantran2", "email": None},
    {"id": "503", "name": "Lê Minh Tường", "username": "tuong.le", "email": "tuong@example.test"},
    {"id": "504", "name": "Nguyen Quoc Anh", "username": "qanh", "email": None},
]


class _Member:
    def __init__(self, name: str, email: str | None):
        self.id = str(uuid4())
        self.display_name = name
        self.email_reference = email


def test_matching_goes_by_email_then_name_then_username_and_refuses_ambiguity() -> None:
    tuong = _Member("Tường Lê", "tuong@example.test")
    anh = _Member("Nguyễn Quốc Anh", None)
    doan = _Member("Đoàn Trần", None)
    qanh = _Member("Quốc Anh", "qanh@example.test")
    out = mapping.suggest(USERS, [tuong, anh, doan, qanh])
    assert out[tuong.id] == "503"          # email wins even though the names differ in order
    assert out[anh.id] == "504"            # name without diacritics, any word order
    assert out[doan.id] == "502"           # "Đoàn Trần" and "Doan Tran" share the same bag of words; the three-word name does not
    assert out[qanh.id] == "504"           # username equals the email's local part
    # Two tracker users with the same name mean no suggestion.
    twin_users = USERS + [{"id": "505", "name": "Nguyễn Quốc Anh", "username": "anh2", "email": None}]
    assert _Member("Nguyễn Quốc Anh", None).id not in mapping.suggest(twin_users, [_Member("Nguyễn Quốc Anh", None)])


def _project_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(Project).where(Project.code == "orbit")).id)


def test_auto_map_fills_only_the_unmapped_and_the_owner_or_cto_can_set_one_by_hand() -> None:
    email = f"map-test-{uuid4().hex[:6]}@example.test"
    created = cto.post("/api/v1/planning/members", json={
        "display_name": "Map Test Person", "email_reference": email,
        "project_mappings": [{"project_id": _project_id(), "gitlab_user_external_id": "9999", "role": "Developer"}],
    })
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]
    try:
        # Creating a member demands a tracker user; clearing it is the state a new project starts in.
        cleared = cto.put(f"/api/v1/planning/projects/orbit/members/{member_id}/tracker-user", json={"gitlab_user_external_id": None})
        assert cleared.status_code == 200, cleared.text
        users = [{"id": "9601", "name": "Map Test Person", "username": "map.test", "email": None}, {"id": "9602", "name": "Someone Else", "username": "else", "email": None}]
        shown = mapping.view(_project_id(), users, issue=None)
        assert any(row["member_id"] == member_id and row["suggested_user_id"] == "9601" for row in shown["unmapped"])
        assert next(user for user in shown["users"] if user["id"] == "9601")["suggested_member_id"] == member_id
        filled = mapping.auto_map(_project_id(), users)
        assert "Map Test Person" in filled["names"]
        with get_session() as session:
            row = session.scalar(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.project_id == _project_id()))
            assert row.gitlab_user_external_id == "9601"
        # Auto never overwrites: a second run with a different match leaves the mapping alone.
        again = mapping.auto_map(_project_id(), [{"id": "9777", "name": "Map Test Person", "username": "x", "email": None}])
        assert again["filled"] == 0
        # A person can change it by hand; the CTO reaches every project, a Project Owner only theirs.
        put = cto.put(f"/api/v1/planning/projects/orbit/members/{member_id}/tracker-user", json={"gitlab_user_external_id": "9602"})
        assert put.status_code == 200, put.text
        with get_session() as session:
            row = session.scalar(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.project_id == _project_id()))
            assert row.gitlab_user_external_id == "9602"
        theirs = owner.put(f"/api/v1/planning/projects/orbit/members/{member_id}/tracker-user", json={"gitlab_user_external_id": "9601"})
        assert theirs.status_code in (200, 404), theirs.text
        assert cto.put(f"/api/v1/planning/projects/no-such-project/members/{member_id}/tracker-user", json={"gitlab_user_external_id": "1"}).status_code == 404
    finally:
        with get_session() as session:
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
                session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
            session.commit()


def test_the_user_list_comes_through_a_probe_of_the_integration_worker() -> None:
    # The API holds no tracker token; the lookup is a probe the worker answers. Without a broker here it fails at once,
    # and the planning dialog reads that state instead of a dead end.
    started = cto.post("/api/v1/planning/projects/orbit/tracker-users/lookup")
    assert started.status_code in (202, 422), started.text
    if started.status_code == 202:
        probe = started.json()["data"]
        assert probe["system"] in ("GITLAB", "GITHUB") and probe["status"] in ("PENDING", "FAILED")
        shown = cto.get(f"/api/v1/planning/projects/orbit/tracker-users?probe={probe['probe_id']}")
        assert shown.status_code == 200, shown.text
        data = shown.json()["data"]
        assert data["status"] in ("PENDING", "FAILED") and data["users"] == []
        assert cto.post(f"/api/v1/planning/projects/orbit/tracker-users/auto-map?probe={probe['probe_id']}").status_code == 409
        # A probe id of another project, or a made-up one, shows nothing.
        other = cto.get("/api/v1/planning/projects/orbit/tracker-users?probe=no-such-probe").json()["data"]
        assert other["status"] == "FAILED" and other["error_code"] == "PROBE_NOT_FOUND"
    assert owner.post("/api/v1/planning/projects/no-such-project/tracker-users/lookup").status_code == 404

