from dataclasses import dataclass


@dataclass
class ApprovalDecision:
    action: str
    reason: str | None = None
    approved_priority: str | None = None
    approved_route: str | None = None


class ApprovalService:
    def __init__(self) -> None:
        self.decisions: list[ApprovalDecision] = []

    def record(self, action: str, reason: str | None = None, approved_priority: str | None = None, approved_route: str | None = None) -> ApprovalDecision:
        decision = ApprovalDecision(
            action=action,
            reason=reason,
            approved_priority=approved_priority,
            approved_route=approved_route,
        )
        self.decisions.append(decision)
        return decision


approval_service = ApprovalService()
