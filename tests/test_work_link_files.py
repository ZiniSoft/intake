"""A file from the computer goes where a link goes on a work item (FR-WRK-10, Issue #43): pictures and PDFs, checked at the door,
downloaded with authorization, removed with their link. Links by address keep working."""
import base64

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, WorkItem, WorkLink
from app.services.object_storage import get_object_storage

cto = TestClient(app, headers={"X-User-Subject": "cto"})

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _cleanup(work_id: str) -> None:
    with get_session() as session:
        session.execute(delete(WorkLink).where(WorkLink.work_id == work_id))
        session.execute(delete(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id))
        row = session.get(WorkItem, work_id)
        if row is not None:
            session.delete(row)
        session.commit()


def _upload(work_id: str, name: str, content: bytes, mime: str, note: str | None = None):
    return cto.post(f"/api/v1/work/{work_id}/links/file", files={"file": (name, content, mime)}, data={"note": note} if note else {})


def test_a_picture_and_a_pdf_become_links_that_download_and_the_address_links_still_work() -> None:
    made = cto.post("/api/v1/work", json={"project": "orbit", "title": "Thử tệp vào link", "priority": "P2"})
    assert made.status_code == 201, made.text
    work_id = made.json()["data"]["id"]
    try:
        # The address link is untouched.
        assert cto.post(f"/api/v1/work/{work_id}/links", json={"url": "https://drive.example.test/folder-43"}).status_code == 201

        shot = _upload(work_id, "man-hinh.png", PNG, "image/png", "Ảnh màn hình thử")
        assert shot.status_code == 201, shot.text
        doc = _upload(work_id, "mo-ta.pdf", PDF, "application/pdf")
        assert doc.status_code == 201, doc.text
        links = doc.json()["data"]["links"]
        assert len(links) == 3 and doc.json()["data"]["link_count"] == 3
        files = [link for link in links if link["file_name"]]
        assert {link["file_name"] for link in files} == {"man-hinh.png", "mo-ta.pdf"}
        picture = next(link for link in files if link["file_name"] == "man-hinh.png")
        assert picture["mime_type"] == "image/png" and picture["size_bytes"] == len(PNG) and picture["note"] == "Ảnh màn hình thử"
        assert picture["url"] == f"/api/v1/work/{work_id}/links/{picture['id']}/file"
        assert [link for link in links if not link["file_name"]][0]["url"] == "https://drive.example.test/folder-43"

        # Download: authorized, never shown inline.
        got = cto.get(picture["url"])
        assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
        assert got.headers["content-disposition"].startswith("attachment") and got.headers["x-content-type-options"] == "nosniff"
        assert TestClient(app).get(picture["url"]).status_code in (401, 403)

        # Removing the link removes the stored bytes.
        with get_session() as session:
            key = session.get(WorkLink, picture["id"]).object_key
        assert get_object_storage().get(key) == PNG
        assert cto.delete(f"/api/v1/work/{work_id}/links/{picture['id']}").status_code == 204
        try:
            get_object_storage().get(key)
            raise AssertionError("the file should be gone with its link")
        except FileNotFoundError:
            pass
        assert cto.get(picture["url"]).status_code == 404
    finally:
        with get_session() as session:
            keys = [row.object_key for row in session.scalars(select(WorkLink).where(WorkLink.work_id == work_id)).all() if row.object_key]
        for key in keys:
            get_object_storage().delete(key)
        _cleanup(work_id)


def test_a_file_that_is_not_a_picture_or_pdf_or_too_big_or_lying_is_refused() -> None:
    made = cto.post("/api/v1/work", json={"project": "orbit", "title": "Thử tệp sai", "priority": "P2"})
    work_id = made.json()["data"]["id"]
    try:
        assert _upload(work_id, "a.exe", b"MZ\x90\x00", "application/x-msdownload").status_code == 422
        assert _upload(work_id, "fake.png", PDF, "image/png").status_code == 422, "content must match the declared type"
        big = _upload(work_id, "big.pdf", PDF + b"0" * (5 * 1024 * 1024), "application/pdf")
        assert big.status_code == 422, big.text
        assert cto.get(f"/api/v1/work/{work_id}").json()["data"]["link_count"] == 0
    finally:
        _cleanup(work_id)
