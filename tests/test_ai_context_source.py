"""FR-CTX-05: which project context the AI reads when it normalizes a request. An approved context pack supplies its
sections 1 and 2 and the free brief field is ignored; without an approved pack the brief field is the source. The
brief endpoint says which one is in use so the settings page can tell the manager where to edit."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Project, ProjectContextSnapshot
from app.services.intake_service import intake_store
from tests.test_intake_context import _retire
from tests.test_project_context import SAMPLE

cto = TestClient(app, headers={"X-User-Subject": "cto"})
BRIEF = "Brief tự do (thử): màn Bán hàng, Kho, Báo cáo."


def _clear_pack(project_code: str) -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        for row in session.scalars(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project.id)).all():
            session.delete(row)
        session.commit()


def test_an_approved_pack_replaces_the_brief_and_the_page_says_so() -> None:
    _clear_pack("orbit")
    assert cto.put("/api/v1/projects/orbit/brief", json={"brief": BRIEF}).status_code == 200
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Bot trả lời sai giờ mở cửa (thử)."}).json()["data"]
    try:
        # No pack: the free brief is what the AI reads, and the page says so.
        shown = cto.get("/api/v1/projects/orbit/brief").json()["data"]
        assert shown["ai_source"] == "BRIEF" and shown["brief"] == BRIEF and shown["pack_approved_at"] is None and shown["pack_sections"] == []
        source = intake_store.normalization_source(intake["id"])
        assert source["brief"] == BRIEF and source["brief_source"] == "BRIEF"

        # A pack that is read or pasted but not approved changes nothing: the CTO has not signed it.
        assert cto.put("/api/v1/projects/orbit/context", json={"content": SAMPLE.read_text(encoding="utf-8")}).status_code == 200
        assert intake_store.normalization_source(intake["id"])["brief_source"] == "BRIEF"
        assert cto.get("/api/v1/projects/orbit/brief").json()["data"]["ai_source"] == "BRIEF"

        # Approved: sections 1 and 2 go instead of the brief; sections 3 to 8 never leave; the field is kept but ignored.
        assert cto.post("/api/v1/projects/orbit/context/approve").status_code == 200
        source = intake_store.normalization_source(intake["id"])
        assert source["brief_source"] == "PACK", source
        assert "Nova Labs" in source["brief"] and BRIEF not in source["brief"]
        assert "Môi trường và truy cập" not in source["brief"] and "Chạy, test, triển khai" not in source["brief"], "sections 3 to 8 never leave"
        assert len(source["brief"]) <= 4000
        shown = cto.get("/api/v1/projects/orbit/brief").json()["data"]
        assert shown["ai_source"] == "PACK" and shown["pack_approved_at"] and len(shown["pack_sections"]) == 2
        assert shown["brief"] == BRIEF, "the field keeps its text as the fallback"

        # Saving the field while the pack is in use still answers with the real source.
        saved = cto.put("/api/v1/projects/orbit/brief", json={"brief": BRIEF + " Sửa thêm."}).json()["data"]
        assert saved["ai_source"] == "PACK" and saved["brief"].endswith("Sửa thêm.")

        # A newer pack version that the CTO has not approved yet falls back to the field.
        newer = SAMPLE.read_text(encoding="utf-8").replace("## 1. ", "## 1. ", 1) + "\n- Dòng mới chưa duyệt (thử).\n"
        assert cto.put("/api/v1/projects/orbit/context", json={"content": newer}).status_code == 200
        assert cto.get("/api/v1/projects/orbit/brief").json()["data"]["ai_source"] == "BRIEF"
        assert intake_store.normalization_source(intake["id"])["brief_source"] == "BRIEF"
    finally:
        cto.put("/api/v1/projects/orbit/brief", json={"brief": ""})
        _clear_pack("orbit")
        _retire(intake["id"])
