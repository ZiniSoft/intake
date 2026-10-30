from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import User, UserPlanningProjectOrder


cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
DAY = "2031-11-03"


def _clear_preferences() -> None:
    with get_session() as session:
        user_ids = list(session.scalars(select(User.id).where(User.auth_subject.in_(("cto", "project-owner")))).all())
        session.execute(delete(UserPlanningProjectOrder).where(UserPlanningProjectOrder.user_id.in_(user_ids)))
        session.commit()


def test_planning_project_order_is_saved_per_account_and_scoped_to_visible_projects() -> None:
    _clear_preferences()
    try:
        cto_day = cto.get(f"/api/v1/planning/day-plans/{DAY}")
        assert cto_day.status_code == 200, cto_day.text
        cto_data = cto_day.json()["data"]
        cto_ids = [row["id"] for row in cto_data["projects"]]
        assert cto_data["project_order"] == {"mode": "PRIORITY", "project_ids": []}
        assert len(cto_ids) >= 2

        custom_ids = list(reversed(cto_ids))
        saved = cto.put("/api/v1/planning/project-order", json={"mode": "CUSTOM", "project_ids": custom_ids})
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"] == {"mode": "CUSTOM", "project_ids": custom_ids}
        assert cto.get(f"/api/v1/planning/day-plans/{DAY}").json()["data"]["project_order"] == saved.json()["data"]

        owner_data = owner.get(f"/api/v1/planning/day-plans/{DAY}").json()["data"]
        owner_ids = [row["id"] for row in owner_data["projects"]]
        assert owner_data["project_order"] == {"mode": "PRIORITY", "project_ids": []}, "preferences are per account"
        outside = next(project_id for project_id in cto_ids if project_id not in owner_ids)
        denied = owner.put("/api/v1/planning/project-order", json={"mode": "CUSTOM", "project_ids": [outside]})
        assert denied.status_code == 422 and denied.json()["error"] == "PROJECT_ORDER_PROJECT_NOT_VISIBLE"

        duplicate = cto.put("/api/v1/planning/project-order", json={"mode": "CUSTOM", "project_ids": [cto_ids[0], cto_ids[0]]})
        assert duplicate.status_code == 422 and duplicate.json()["error"] == "PROJECT_ORDER_DUPLICATE"
        reset = cto.put("/api/v1/planning/project-order", json={"mode": "PRIORITY", "project_ids": custom_ids})
        assert reset.json()["data"] == {"mode": "PRIORITY", "project_ids": []}
    finally:
        _clear_preferences()
