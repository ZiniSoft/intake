"""The words of a channel version against its channel's rule (FR-MKT-11) and the short link that measures every
channel with one ruler (FR-MKT-12)."""
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, PostClick, PostLink, WorkChannel, WorkComment, WorkItem, WorkLink
from app.modules.work.channels import count_chars, rule_of

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
visitor = TestClient(app, follow_redirects=False)


def _cleanup(work_ids: list[str]) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for version in session.scalars(select(WorkChannel).where(WorkChannel.work_id == work_id)).all():
                for link in session.scalars(select(PostLink).where(PostLink.work_channel_id == version.id)).all():
                    session.execute(delete(PostClick).where(PostClick.link_id == link.id))
                    session.delete(link)
                session.delete(version)
            for model in (WorkComment, WorkLink):
                session.execute(delete(model).where(model.work_id == work_id))
            session.execute(delete(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id))
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        session.commit()


def _move(work_id: str, status: str, note: str | None = None):
    current = cto.get(f"/api/v1/work/{work_id}").json()["data"]
    return cto.post(f"/api/v1/work/{work_id}/move", json={"status": status, "expected_version": current["version"], "note": note})


def test_a_version_longer_than_its_channel_allows_does_not_go_for_review() -> None:
    x = rule_of("X")
    assert count_chars("abc https://x.example/zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", x) == 4 + 23, "a link on X counts as 23 characters"
    assert count_chars("abc https://x.example/z", rule_of("EMAIL")) == 4, "a link in an email does not count"
    ids: list[str] = []
    try:
        post = cto.post("/api/v1/work", json={"project": "orbit", "title": "Bài thử bộ đếm", "campaign": "Thử link", "channels": [{"channel": "X", "language": "en"}, {"channel": "LINKEDIN", "language": "en"}]}).json()["data"]
        ids.append(post["id"])
        versions = {row["channel"]: row["id"] for row in post["channels"]}
        long_x = cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['X']}", json={"text": "x" * 300})
        assert long_x.status_code == 200 and next(row for row in long_x.json()["data"]["channels"] if row["channel"] == "X")["text"] == "x" * 300
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['LINKEDIN']}", json={"text": "l" * 3001}).status_code == 200
        assert _move(post["id"], "IN_PROGRESS").status_code == 200
        refused = _move(post["id"], "ACCEPTANCE")
        assert refused.status_code == 422 and "CHANNEL_TEXT_TOO_LONG" in refused.text and "LinkedIn" in refused.text, "3001 on LinkedIn is over its 3000"
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['LINKEDIN']}", json={"text": "l" * 100}).status_code == 200
        assert _move(post["id"], "ACCEPTANCE").status_code == 200, "300 on a paid X account is a long post, not a fault"
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['X']}", json={"text": "y" * 25001}).status_code == 200
        assert _move(post["id"], "IN_PROGRESS", "cắt bớt bản X").status_code == 200
        assert "CHANNEL_TEXT_TOO_LONG" in _move(post["id"], "ACCEPTANCE").text, "over the long limit too"
        cleared = cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['X']}", json={"clear_text": True})
        assert next(row for row in cleared.json()["data"]["channels"] if row["channel"] == "X")["text"] is None
    finally:
        _cleanup(ids)


def test_a_short_link_redirects_with_utm_tags_and_counts_human_clicks() -> None:
    ids: list[str] = []
    try:
        post = cto.post("/api/v1/work", json={"project": "orbit", "title": "Bài thử link ngắn", "campaign": "Ra mắt 5.0", "channels": [{"channel": "FACEBOOK_PAGE"}]}).json()["data"]
        ids.append(post["id"])
        version = post["channels"][0]["id"]
        path = f"/api/v1/work/{post['id']}/channels/{version}/link"
        assert cto.post(path, json={"target_url": "ftp://x"}).status_code == 422
        issued = cto.post(path, json={"target_url": "https://example.test/ra-mat?ref=1&utm_source=old"})
        assert issued.status_code == 200, issued.text
        link = issued.json()["data"]
        assert len(link["code"]) == 8 and link["url"].endswith(f"/p/{link['code']}") and link["clicks"] == 0
        assert link["target_url"] == "https://example.test/ra-mat?ref=1&utm_source=facebook_page&utm_medium=social&utm_campaign=ra-mat-5-0", "the old utm tag is replaced, the rest kept, the campaign in plain letters"
        assert cto.post(path, json={"target_url": "https://example.test/ra-mat"}).json()["data"]["code"] == link["code"], "one code per version"
        assert owner.post(path, json={"target_url": "https://example.test/ra-mat"}).status_code in (403, 404), "another project's owner sees nothing here"

        hit = visitor.get(f"/p/{link['code']}", headers={"Referer": "https://m.facebook.com/", "User-Agent": "Mozilla/5.0 (iPhone)"})
        assert hit.status_code == 302 and hit.headers["location"].startswith("https://example.test/ra-mat?") and "utm_campaign=ra-mat-5-0" in hit.headers["location"]
        assert visitor.get(f"/api/v1/p/{link['code']}", headers={"User-Agent": "facebookexternalhit/1.1"}).status_code == 302, "a crawler is sent on too, but not counted"
        assert visitor.get("/p/khong-co").status_code == 404 and visitor.get("/p/zzzzzzzz").status_code == 404
        detail = cto.get(f"/api/v1/work/{post['id']}").json()["data"]
        assert detail["channels"][0]["short_link"]["clicks"] == 1 and detail["channels"][0]["short_link"]["code"] == link["code"]
        with get_session() as session:
            seen = {(row.referrer_host, row.is_bot) for row in session.scalars(select(PostClick)).all()}
            assert ("m.facebook.com", False) in seen and (None, True) in seen, "a person from Facebook, and a crawler marked as one"
    finally:
        _cleanup(ids)
