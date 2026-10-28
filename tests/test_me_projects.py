"""/auth/me carries the person's projects with their kind and the mode the web should take (FR-MKT-03): a
marketing-only owner or member sees the posts side; the CTO and anyone with a software project sees everything."""
import random
import string
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, Project, ProjectIntegration, User, UserProjectAccess, WorkforceMember, WorkforceProjectMembership

cto = TestClient(app, headers={"X-User-Subject": "cto"})


def _cleanup(project_code: str, member_id: str | None, user_ids: list[str]) -> None:
    with get_session() as session:
        for user_id in user_ids:
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            for row in session.scalars(select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)).all():
                session.delete(row)
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        if member_id:
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
                session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        project = session.scalar(select(Project).where(Project.code == project_code))
        if project is not None:
            for row in session.scalars(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id)).all():
                session.delete(row)
            session.delete(project)
        session.commit()


def test_me_lists_projects_with_kind_and_picks_the_mode() -> None:
    tag = uuid4().hex[:6]
    code = f"mkt-{tag}"
    key = "M" + "".join(random.choices(string.ascii_uppercase, k=4))
    made = cto.post("/api/v1/projects", json={"name": f"Marketing thử {tag}", "code": code, "intake_key": key, "kind": "NON_CODE"})
    assert made.status_code == 201, made.text
    project_id = made.json()["data"]["id"]
    member_id = None
    owner_member_id = None
    user_ids: list[str] = []
    try:
        me = cto.get("/api/v1/auth/me").json()["data"]
        assert me["mode"] == "FULL" and any(p["code"] == code and p["kind"] == "NON_CODE" for p in me["projects"])
        assert not any(p["code"] == "other" for p in me["projects"]), "the catch-all project is not a place to work"

        # A Project Owner with only the marketing project: posts mode. The owner is chosen on the project's team page,
        # which issues the login.
        owner_member = cto.post("/api/v1/planning/members", json={"display_name": f"Owner {tag}", "email_reference": f"po{tag}@example.test"}).json()["data"]
        owner_member_id = owner_member["id"]
        team = cto.put(f"/api/v1/projects/{code}/team", json={"owner_member_id": owner_member_id, "member_ids": []})
        assert team.status_code == 200, team.text
        issued = team.json()["data"]["issued"]
        assert issued and issued["subject"] == f"po{tag}"
        user_ids.append(next(row for row in cto.get("/api/v1/users").json()["data"] if row["subject"] == f"po{tag}")["id"])
        po = TestClient(app, headers={"X-User-Subject": f"po{tag}"})
        assert po.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": f"po-pass-{tag}-long"}).status_code == 200
        me = po.get("/api/v1/auth/me").json()["data"]
        assert me["mode"] == "MARKETING" and [p["code"] for p in me["projects"]] == [code]

        # A member of that project with a Developer login: posts mode too; add a software project and it is FULL.
        member = cto.post("/api/v1/planning/members", json={"display_name": "Người Viết", "email_reference": f"viet-{tag}@example.test",
                                                            "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424367", "role": "Developer"}]})
        assert member.status_code == 201, member.text
        member = member.json()["data"]
        member_id = member["id"]
        dev = cto.post("/api/v1/users", json={"subject": f"viet{tag}", "role": "DEVELOPER", "member_id": member_id})
        assert dev.status_code == 201, dev.text
        user_ids.append(dev.json()["data"]["account"]["id"])
        writer = TestClient(app, headers={"X-User-Subject": f"viet{tag}"})
        assert writer.post("/api/v1/auth/password", json={"current_password": dev.json()["data"]["temporary_password"], "new_password": f"viet-pass-{tag}-long"}).status_code == 200
        me = writer.get("/api/v1/auth/me").json()["data"]
        assert me["mode"] == "MARKETING" and [p["kind"] for p in me["projects"]] == ["NON_CODE"]
        with get_session() as session:
            orbit = session.scalar(select(Project).where(Project.code == "orbit"))
            session.add(WorkforceProjectMembership(id=str(uuid4()), member_id=member_id, project_id=orbit.id, gitlab_user_external_id="424366", role="Developer", active=True))
            session.commit()
        me = writer.get("/api/v1/auth/me").json()["data"]
        assert me["mode"] == "FULL" and sorted(p["kind"] for p in me["projects"]) == ["NON_CODE", "SOFTWARE"]
    finally:
        _cleanup(code, member_id, user_ids)
        _cleanup(code, owner_member_id, [])
