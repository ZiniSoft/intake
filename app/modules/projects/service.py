from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.db import get_session
from app.models import Project, ProjectIntegration, WorkforceMember


OTHER_ID = "10000000-0000-4000-8000-000000000003"
# Catch-all for Daily Report work outside any real project; it has no delivery mapping.
OTHER_PROJECT_CODE = "other"


@dataclass(frozen=True)
class ProjectView:
    id: str
    code: str
    intake_key: str
    name: str
    status: str
    gitlab_project_id: str | None = None
    gitlab_project_url: str | None = None
    kind: str = "SOFTWARE"
    gitlab_enabled: bool = False
    github_repository: str | None = None
    github_project_url: str | None = None
    github_enabled: bool = False
    github_token_ref: str | None = None
    telegram_chat_title: str | None = None
    telegram_linked: bool = False
    delivery_system: str | None = None
    # What counts as the trace of code behind a closed Issue: COMMIT (default) or MR (FR-PLAN-22).
    done_evidence: str = "COMMIT"
    # Who closes an acceptance: CTO_ALWAYS (default) or PO_FINAL_LOW_RISK (FR-PLAN-41).
    acceptance_policy: str = "CTO_ALWAYS"
    agent_ready: bool = False
    owner_member_id: str | None = None
    owner_name: str | None = None
    # The tracker the project left for GitHub, kept for its old Issue links (FR-PRJ-13).
    previous_delivery: dict | None = None


class ProjectCatalogService:
    def ensure_database_projects(self) -> None:
        """Seed only the catch-all project. Real projects are created by the CTO (first-run setup or Settings)."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
            if project is None:
                session.add(
                    Project(
                        id=OTHER_ID,
                        code=OTHER_PROJECT_CODE,
                        intake_key="OTH",
                        name="Dự án khác",
                        kind="IDEA",
                        status="ACTIVE",
                        project_settings={},
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                project.intake_key = "OTH"
            session.commit()

    def list_projects(self) -> list[ProjectView]:
        with get_session() as session:
            # A-Z by the name people read, not by code.
            projects = sorted(session.scalars(select(Project)).all(), key=lambda row: (row.name or row.code or "").casefold())
            self._owner_names = {str(row.id): row.display_name for row in session.scalars(select(WorkforceMember)).all()}
            mappings = session.scalars(select(ProjectIntegration)).all()
            by_project = {
                (str(mapping.project_id), mapping.system): mapping for mapping in mappings
            }
            return [
                self._view(
                    project,
                    by_project.get((str(project.id), "GITLAB")),
                    by_project.get((str(project.id), "GITHUB")),
                )
                for project in projects
            ]

    def get_project(self, project_id_or_code: str) -> ProjectView | None:
        with get_session() as session:
            query = select(Project).where(Project.code == project_id_or_code)
            try:
                UUID(project_id_or_code)
                query = select(Project).where(
                    (Project.id == project_id_or_code) | (Project.code == project_id_or_code)
                )
            except ValueError:
                pass
            project = session.scalar(query)
            if project is None:
                return None
            self._owner_names = {str(row.id): row.display_name for row in session.scalars(select(WorkforceMember)).all()}
            mappings = session.scalars(
                select(ProjectIntegration).where(ProjectIntegration.project_id == project.id)
            ).all()
            by_system = {mapping.system: mapping for mapping in mappings}
            return self._view(project, by_system.get("GITLAB"), by_system.get("GITHUB"))

    _owner_names: dict[str, str] = {}

    def _view(
        self,
        project: Project,
        gitlab_mapping: ProjectIntegration | None,
        github_mapping: ProjectIntegration | None = None,
    ) -> ProjectView:
        config = gitlab_mapping.config if gitlab_mapping and isinstance(gitlab_mapping.config, dict) else {}
        return ProjectView(
            id=str(project.id),
            code=project.code,
            intake_key=project.intake_key,
            name=project.name,
            status=project.status,
            gitlab_project_id=gitlab_mapping.project_external_id if gitlab_mapping else None,
            gitlab_project_url=config.get("project_url") if gitlab_mapping and gitlab_mapping.project_external_id else None,
            kind=project.kind,
            gitlab_enabled=bool(gitlab_mapping and gitlab_mapping.enabled and gitlab_mapping.project_external_id),
            owner_member_id=str(project.owner_member_id) if project.owner_member_id else None,
            owner_name=self._owner_names.get(str(project.owner_member_id)) if project.owner_member_id else None,
            github_repository=github_mapping.project_external_id if github_mapping else None,
            github_project_url=(github_mapping.config or {}).get("project_url") if github_mapping else None,
            github_enabled=bool(github_mapping and github_mapping.enabled and github_mapping.project_external_id),
            github_token_ref=github_mapping.credential_ref if github_mapping else None,
            telegram_chat_title=project.telegram_chat_title,
            telegram_linked=bool(project.telegram_chat_id),
            delivery_system=(
                "GITHUB" if github_mapping and github_mapping.project_external_id
                else "GITLAB" if gitlab_mapping and gitlab_mapping.project_external_id else None
            ),
            done_evidence=str((project.project_settings or {}).get("done_evidence") or "COMMIT"),
            acceptance_policy=str((project.project_settings or {}).get("acceptance_policy") or "CTO_ALWAYS"),
            agent_ready=bool((project.project_settings or {}).get("agent_ready")),
            previous_delivery=config.get("previous") if gitlab_mapping and isinstance(config.get("previous"), dict) else None,
        )


def _mapping_id(project_id: str, system: str) -> str:
    value = UUID(project_id)
    offset = 100 if system == "GITLAB" else 200
    return str(UUID(int=(value.int + offset) % (1 << 128)))


project_catalog_service = ProjectCatalogService()
