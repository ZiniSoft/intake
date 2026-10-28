from dataclasses import dataclass, field


@dataclass
class AuditEvent:
    event_type: str
    actor: str
    details: str | None = None


class AuditService:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event_type: str, actor: str, details: str | None = None) -> AuditEvent:
        event = AuditEvent(event_type=event_type, actor=actor, details=details)
        self.events.append(event)
        return event


audit_service = AuditService()
