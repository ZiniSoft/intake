"""The short agent commands as public text (FR-MCP-07): an install line fetches them into a machine or a repo. The
files hold instructions for an agent, never data or secrets, so no login is asked."""
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.modules.mcp.prompts import INSTALL_PS1, INSTALL_SH, command_file, public_base

router = APIRouter(prefix="/agent-commands", tags=["agent-commands"])
REQUIREMENTS = {"x-requirement-ids": ["FR-MCP-07"]}


def _base(request: Request) -> str:
    return public_base() or str(request.base_url).rstrip("/")


@router.get("/install.sh", response_class=PlainTextResponse, openapi_extra=REQUIREMENTS)
async def install_sh(request: Request) -> str:
    return INSTALL_SH.format(url=f"{_base(request)}/api/v1/agent-commands")


@router.get("/install.ps1", response_class=PlainTextResponse, openapi_extra=REQUIREMENTS)
async def install_ps1(request: Request) -> str:
    return INSTALL_PS1.format(url=f"{_base(request)}/api/v1/agent-commands")


@router.get("/files/{name}.md", response_class=PlainTextResponse, openapi_extra=REQUIREMENTS)
async def command_markdown(name: str) -> str:
    if name == "context-template":
        # The project context pack template (ADR-0063), public like the command files.
        from pathlib import Path

        template = Path(__file__).resolve().parents[3] / "docs" / "stable" / "agent-context-template.md"
        if not template.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such command")
        return template.read_text(encoding="utf-8")
    made = command_file(name)
    if made is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such command")
    return made[1]
