import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.modules.integrations import adapters as adapter_module
from app.modules.integrations.adapters import GitLabAdapter, payload_hash


def test_external_adapters_require_approval_snapshot() -> None:
    approved = {
        "approved": True,
        "title": "Fix issue",
        "description": "Details",
        "intake_public_id": "FB-2026-TEST01",
        "approved_priority": "P1",
    }
    assert GitLabAdapter().build_issue_payload(approved)["title"] == "[FB-2026-TEST01] Fix issue"
    assert len(payload_hash(approved)) == 64

    with pytest.raises(ValueError):
        GitLabAdapter().build_issue_payload({"approved": False})


def _gitlab_adapter() -> GitLabAdapter:
    adapter = GitLabAdapter()
    adapter.settings = SimpleNamespace(
        gitlab_base_url="https://gitlab.test",
        gitlab_token="secret",
    )
    return adapter


def test_gitlab_payload_contains_sanitized_traceability_and_acceptance_criteria() -> None:
    payload = _gitlab_adapter().build_issue_payload(
        {
            "approved": True,
            "title": "Fix checkout",
            "description": "Approved summary only",
            "intake_public_id": "FB-2026-GL01",
            "approved_priority": "P1",
            "item_type": "BUG",
        }
    )
    assert payload["title"] == "[FB-2026-GL01] Fix checkout"
    assert "Approved summary only" in payload["description"]
    assert "## Acceptance criteria" in payload["description"]
    assert "Priority: `P1`" in payload["description"]
    assert "<!-- intake:FB-2026-GL01 -->" in payload["description"]
    assert payload["labels"] == "source:intake,priority:p1,type:bug"


@pytest.mark.parametrize(
    ("item_type", "expected_label"),
    [
        ("FEATURE", "type:feature"),
        ("SCOPE_CHANGE", "type:feature"),
        ("TASK", "type:task"),
        ("FEEDBACK", "type:task"),
        ("TECH_DEBT", "type:tech-debt"),
    ],
)
def test_gitlab_labels_are_selected_from_the_fixed_allowlist(item_type: str, expected_label: str) -> None:
    payload = _gitlab_adapter().build_issue_payload(
        {
            "approved": True,
            "title": "Allowlisted labels",
            "description": "Approved summary",
            "intake_public_id": "FB-2026-LABEL",
            "approved_priority": "P2",
            "item_type": item_type,
        }
    )
    assert payload["labels"] == f"source:intake,priority:p2,{expected_label}"


def test_gitlab_labels_fail_closed_for_unknown_values() -> None:
    base = {
        "approved": True,
        "title": "Invalid labels",
        "description": "Approved summary",
        "intake_public_id": "FB-2026-LABEL",
        "approved_priority": "P2",
        "item_type": "BUG",
    }
    with pytest.raises(ValueError, match="Unsupported GitLab priority"):
        _gitlab_adapter().build_issue_payload({**base, "approved_priority": "URGENT"})
    with pytest.raises(ValueError, match="Unsupported GitLab item type"):
        _gitlab_adapter().build_issue_payload({**base, "item_type": "CUSTOM_AI_LABEL"})


def test_gitlab_lookup_and_create_use_stable_marker(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    def client_factory(**kwargs):
        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 91,
                            "iid": 7,
                            "description": "<!-- intake:FB-2026-GL01 -->",
                            "web_url": "https://gitlab.test/2026/orbit-platform/-/issues/7",
                        }
                    ],
                )
            body = __import__("json").loads(request.content)
            assert "<!-- intake:FB-2026-GL02 -->" in body["description"]
            assert body["labels"] == "source:intake,priority:p2,type:task"
            return httpx.Response(
                201,
                json={
                    "id": 92,
                    "iid": 8,
                    "web_url": "https://gitlab.test/2026/orbit-platform/-/issues/8",
                },
            )

        return real_client(
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", client_factory)
    adapter = _gitlab_adapter()
    found = asyncio.run(adapter.find_issue("2026/orbit-platform", "FB-2026-GL01"))
    assert found is not None and found["iid"] == 7
    created = asyncio.run(
        adapter.create_issue(
            "2026/orbit-platform",
            {
                "approved": True,
                "title": "Synthetic GitLab",
                "description": "Approved only",
                "intake_public_id": "FB-2026-GL02",
                "approved_priority": "P2",
            },
            "gitlab:snapshot-2",
        )
    )
    assert created["iid"] == 8
    assert all("2026%2Forbit-platform" in request.url.raw_path.decode() for request in requests)


def test_gitlab_planning_update_uses_allowlisted_fields(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requests: list[httpx.Request] = []

    def client_factory(**kwargs):
        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={"iid": 125, "assignees": [], "milestone": None, "due_date": None},
                )
            payload = __import__("json").loads(request.content)
            assert payload == {"assignee_ids": [42], "milestone_id": 9, "due_date": "2026-10-02"}
            assert request.headers["Idempotency-Key"] == "planning:snapshot:125"
            return httpx.Response(
                200,
                json={
                    "iid": 125,
                    "assignees": [{"id": 42}],
                    "milestone": {"id": 9},
                    "due_date": "2026-10-02",
                },
            )

        return real_client(
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout"],
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", client_factory)
    adapter = _gitlab_adapter()
    before = asyncio.run(adapter.get_issue_by_iid("2026/orbit-platform", "125"))
    assert before["iid"] == 125
    updated = asyncio.run(
        adapter.update_issue_planning(
            "2026/orbit-platform",
            "125",
            {
                "assignee_external_id": "42",
                "milestone_external_id": "9",
                "due_date": "2026-10-02",
            },
            "planning:snapshot:125",
        )
    )
    assert updated["assignees"][0]["id"] == 42
    assert [request.method for request in requests] == ["GET", "PUT"]


def test_gitlab_planning_update_sends_only_the_fields_the_plan_has() -> None:
    # A plan without a milestone or a due date updates the assignee alone: nothing on GitLab is erased (ADR-0013).
    assert GitLabAdapter.build_planning_update_payload({"assignee_external_id": "42"}) == {"assignee_ids": [42]}
    assert GitLabAdapter.build_planning_update_payload({"assignee_external_id": "42", "milestone_external_id": "9", "due_date": ""}) == {"assignee_ids": [42], "milestone_id": 9}
    assert GitLabAdapter.build_planning_update_payload({"assignee_external_id": "42", "due_date": "2026-10-02"}) == {"assignee_ids": [42], "due_date": "2026-10-02"}


def test_gitlab_planning_update_rejects_non_numeric_mapping() -> None:
    with pytest.raises(ValueError, match="must be numeric"):
        GitLabAdapter.build_planning_update_payload(
            {
                "assignee_external_id": "user-name",
                "milestone_external_id": "9",
                "due_date": "2026-10-02",
            }
        )
