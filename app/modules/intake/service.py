from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas import IntakeCreate, IntakeDecision, IntakeOut


class IntakeModuleService:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def create(self, payload: IntakeCreate) -> IntakeOut:
        now = datetime.now(timezone.utc)
        public_id = f"FB-{now:%Y}-{len(self._items) + 1:06d}"
        intake_id = f"intake-{len(self._items) + 1:06d}"
        item = {
            "id": intake_id,
            "public_id": public_id,
            "project_id": payload.project_id,
            "channel": payload.channel,
            "item_type": "UNCLEAR",
            "status": "NEW",
            "normalized_title": payload.raw_text[:80].strip() if payload.raw_text else None,
            "normalized_summary": payload.raw_text.strip() if payload.raw_text else None,
            "approved_priority": None,
            "approved_route": None,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "raw_text": payload.raw_text,
            "sender_reference": payload.sender_reference,
        }
        self._items[intake_id] = item
        return IntakeOut(**{k: v for k, v in item.items() if k in IntakeOut.model_fields})

    def list(self) -> list[IntakeOut]:
        return [
            IntakeOut(**{k: v for k, v in item.items() if k in IntakeOut.model_fields})
            for item in self._items.values()
        ]

    def get(self, intake_id: str) -> IntakeOut | None:
        item = self._items.get(intake_id)
        if item is None:
            return None
        return IntakeOut(**{k: v for k, v in item.items() if k in IntakeOut.model_fields})

    def approve(self, intake_id: str, decision: IntakeDecision) -> IntakeOut:
        item = self._items[intake_id]
        item["version"] = item["version"] + 1
        item["status"] = "APPROVED"
        item["approved_route"] = decision.approved_route
        item["approved_priority"] = decision.approved_priority
        item["normalized_title"] = item["normalized_title"] or "Approved intake"
        item["updated_at"] = datetime.now(timezone.utc)
        return IntakeOut(**{k: v for k, v in item.items() if k in IntakeOut.model_fields})


intake_module_service = IntakeModuleService()
