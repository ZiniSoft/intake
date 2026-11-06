"""The showcase catalog is edited by hand, so its shape is checked here (keys are stable ids, never reused)."""
import json
from pathlib import Path
from urllib.parse import urlparse

CATALOG = Path(__file__).resolve().parents[1] / "app" / "resources" / "showcase.json"
REQUIRED = {"key", "kind", "group", "name", "summary", "repo_url", "languages", "license", "default_enabled", "sample_requests"}


def test_showcase_catalog_is_well_formed():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert data["version"] >= 1
    keys = [item["key"] for item in data["items"]]
    assert len(keys) == len(set(keys))
    for item in data["items"]:
        assert REQUIRED <= set(item), item["key"]
        assert item["group"] in data["groups"]
        assert item["kind"] in {"demo", "real"}
        if item["kind"] == "real":
            assert item["project_code"] and 0 < len(item["intake_key"]) <= 8
        assert urlparse(item["repo_url"]).scheme == "https"
        assert isinstance(item["languages"], list) and isinstance(item["default_enabled"], bool)
        for request in item["sample_requests"]:
            assert request.get("title") and request.get("body")
