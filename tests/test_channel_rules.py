"""Channel rules (FR-MKT-02): seeded once, read by everyone with a login, edited by the CTO only."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, ChannelRule

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def test_rules_are_seeded_read_by_all_and_edited_by_the_cto() -> None:
    rules = owner.get("/api/v1/channel-rules")
    assert rules.status_code == 200, rules.text
    codes = [row["code"] for row in rules.json()["data"]]
    assert codes[:4] == ["FACEBOOK_PAGE", "FACEBOOK_PERSONAL", "THREADS", "X"] and len(codes) == 12
    x = next(row for row in rules.json()["data"] if row["code"] == "X")
    assert x["language"] == "en" and x["max_chars"] == 280 and x["long_max_chars"] == 25000 and x["link_chars"] == 23
    original = {k: x[k] for k in ("max_chars", "best_hours")}
    try:
        assert owner.put("/api/v1/channel-rules/X", json={"max_chars": 4000}).status_code == 403
        assert cto.put("/api/v1/channel-rules/MYSPACE", json={"max_chars": 10}).status_code == 404
        assert cto.put("/api/v1/channel-rules/X", json={"best_hours": ["9h"]}).status_code == 422
        assert cto.put("/api/v1/channel-rules/X", json={"max_chars": 0}).status_code == 422
        changed = cto.put("/api/v1/channel-rules/x", json={"max_chars": 4000, "best_hours": ["08:30", "18:00"]})
        assert changed.status_code == 200 and changed.json()["data"]["max_chars"] == 4000 and changed.json()["data"]["best_hours"] == ["08:30", "18:00"]
        with get_session() as session:
            assert session.get(ChannelRule, "X").max_chars == 4000
            assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "channel_rule.updated").order_by(AuditEvent.created_at.desc())).details["code"] == "X"
        assert cto.put("/api/v1/channel-rules/X", json={"max_chars": 4000}).status_code == 200, "no change is fine"
    finally:
        cto.put("/api/v1/channel-rules/X", json=original)
