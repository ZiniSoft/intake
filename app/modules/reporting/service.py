class ReportingService:
    def build_digest(self, intake_count: int = 0, approved_count: int = 0) -> dict[str, object]:
        return {
            "intake_count": intake_count,
            "approved_count": approved_count,
            "status": "draft",
            "summary": "Awaiting final CTO approval",
        }


reporting_service = ReportingService()
