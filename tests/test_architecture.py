from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, headers={"X-User-Subject": "cto"})


def test_project_catalog() -> None:
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert {project["code"] for project in payload} == {"ember", "other", "orbit"}
    ember = next(project for project in payload if project["code"] == "ember")
    assert ember["gitlab_project_id"] == "2026/ember-platform"
    orbit = next(project for project in payload if project["code"] == "orbit")
    assert orbit["gitlab_project_id"] == "2026/orbit-platform"


def test_operations_status() -> None:
    response = client.get("/api/v1/operations/status")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_api_routes_declare_requirement_ids() -> None:
    schema = client.get("/openapi.json").json()
    missing: list[str] = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in operations.items():
            if method.lower() in {"get", "post", "put", "patch", "delete"} and not operation.get(
                "x-requirement-ids"
            ):
                missing.append(f"{method.upper()} {path}")
    assert missing == []
    list_schema = schema["paths"]["/api/v1/intakes"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert set(list_schema["required"]) == {"success", "data", "request_id"}
    assert list_schema["properties"]["data"]
