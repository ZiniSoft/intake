"""Help inside the app (FR-UI-17): a page introduction read once stays read on every device, each hint open is
counted, and the CTO sees the week's counts."""
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import HintOpen, UserHintDismissal

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _cleanup() -> None:
    with get_session() as session:
        session.execute(delete(UserHintDismissal).where(UserHintDismissal.key.like("test.%")))
        session.execute(delete(HintOpen).where(HintOpen.key.like("test.%")))
        session.commit()


def test_an_introduction_read_once_stays_read_and_hint_opens_are_counted() -> None:
    _cleanup()
    try:
        assert "test.work" not in owner.get("/api/v1/hints").json()["data"]["dismissed"]
        assert owner.post("/api/v1/hints/test.work/dismiss").json()["data"]["dismissed"] == ["test.work"]
        assert owner.post("/api/v1/hints/test.work/dismiss").status_code == 200, "reading it twice is fine"
        assert "test.work" in owner.get("/api/v1/hints").json()["data"]["dismissed"]
        assert "test.work" not in cto.get("/api/v1/hints").json()["data"]["dismissed"], "per person"
        assert owner.post("/api/v1/hints/bad key!/dismiss").status_code == 422

        for _ in range(3):
            assert owner.post("/api/v1/hints/test.work.links/opened").status_code == 204
        assert cto.post("/api/v1/hints/test.work.links/opened").status_code == 204
        assert owner.get("/api/v1/hints/stats").status_code == 403
        stats = cto.get("/api/v1/hints/stats", params={"days": 7}).json()["data"]
        row = next(item for item in stats["opened"] if item["key"] == "test.work.links")
        assert row["opens"] == 4 and row["people"] == 2
        assert any(item["key"] == "test.work" and item["people"] == 1 for item in stats["dismissed"])

        assert owner.delete("/api/v1/hints/test.work/dismiss").status_code == 204
        assert "test.work" not in owner.get("/api/v1/hints").json()["data"]["dismissed"]
    finally:
        _cleanup()
