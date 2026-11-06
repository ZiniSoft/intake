from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
import hmac
import json

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from starlette.requests import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles

from app.api.routes.changelog import router as changelog_router
from app.api.routes.health import router as health_router
from app.api.routes.intakes import router as intakes_router
from app.api.routes.operations import router as operations_router
from app.api.routes.projects import router as projects_router
from app.api.routes.auth import router as auth_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.acceptance import router as acceptance_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.planning import router as planning_router
from app.api.routes.reports import router as reports_router
from app.api.routes.users import router as users_router
from app.api.routes.meetings import router as meetings_router
from app.api.routes.agent_commands import router as agent_commands_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.work import router as work_router
from app.api.routes.hints import router as hints_router
from app.api.routes.channels import router as channels_router
from app.api.routes.notify import router as notify_router
from app.api.routes.personal import router as personal_router
from app.api.routes.private_space import drafts_router, router as private_space_router
from app.api.routes.content_plan import router as content_plan_router
from app.api.routes.publish import router as publish_router
from app.api.routes.ai_settings import router as ai_settings_router
from app.api.routes.setup import router as setup_router
from app.api.routes.showcase import router as showcase_router
from app.api.routes.github_tokens import router as github_tokens_router
from app.api.routes.connectors import router as connectors_router
from app.api.routes.links import router as links_router
from app.api.routes.topics import router as topics_router
from app.api.routes.watch import flow_router as watch_flow_router, router as watch_router
from app.api.errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler
from app.config import get_settings
from app.db import init_db
from app.modules.identity.service import identity_service
from app.modules.projects.service import project_catalog_service

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    identity_service.ensure_database_users()
    project_catalog_service.ensure_database_projects()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Private Feedback Intake for validated human approval workflows.",
    lifespan=lifespan,
)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            for status_code, response in operation.get("responses", {}).items():
                if not str(status_code).startswith("2"):
                    continue
                media = response.get("content", {}).get("application/json")
                if not media or "schema" not in media:
                    continue
                data_schema = media["schema"]
                media["schema"] = {
                    "type": "object",
                    "required": ["success", "data", "request_id"],
                    "properties": {
                        "success": {"type": "boolean", "const": True},
                        "data": data_schema,
                        "request_id": {"type": "string"},
                    },
                }
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    public_auth_requests = {
        "/api/v1/auth/login", "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm",
        "/api/v1/setup/bootstrap",
    }
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path not in public_auth_requests:
        session_cookie = request.cookies.get(settings.auth_cookie_name)
        bearer_header = request.headers.get("Authorization", "")
        dev_subject_header = settings.allow_subject_header_auth and request.headers.get("X-User-Subject")
        if session_cookie and not bearer_header.startswith("Bearer ") and not dev_subject_header:
            csrf_cookie = request.cookies.get(settings.csrf_cookie_name, "")
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    return await call_next(request)


@app.middleware("http")
async def api_response_contract_middleware(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if request.url.path.startswith("/api/v1/mcp-server"):
        # JSON-RPC answers keep their own shape: an MCP client reads them, not the web app. The body is sent whole,
        # with its length, so a strict HTTP client sees one well-framed response.
        body = b"".join([chunk async for chunk in response.body_iterator])
        return Response(content=body, status_code=response.status_code, media_type=content_type or None,
                        headers={"X-Request-ID": str(getattr(request.state, "request_id", "unknown"))})
    if (
        not request.url.path.startswith("/api/v1")
        or not 200 <= response.status_code < 300
        or not content_type.startswith("application/json")
        or response.status_code == 204
    ):
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=content_type,
        )

    wrapped = JSONResponse(
        status_code=response.status_code,
        content={
            "success": True,
            "data": payload,
            "request_id": str(getattr(request.state, "request_id", "unknown")),
        },
    )
    excluded = {b"content-length", b"content-type"}
    for key, value in response.raw_headers:
        if key.lower() not in excluded:
            wrapped.raw_headers.append((key, value))
    return wrapped

app.include_router(health_router, prefix="/api/v1")
app.include_router(changelog_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(mcp_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(acceptance_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(intakes_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(planning_router, prefix="/api/v1")
app.include_router(meetings_router, prefix="/api/v1")
app.include_router(notify_router, prefix="/api/v1")
app.include_router(agent_commands_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(work_router, prefix="/api/v1")
app.include_router(hints_router, prefix="/api/v1")
app.include_router(channels_router, prefix="/api/v1")
app.include_router(personal_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(private_space_router, prefix="/api/v1")
app.include_router(drafts_router, prefix="/api/v1")
app.include_router(content_plan_router, prefix="/api/v1")
app.include_router(publish_router, prefix="/api/v1")
app.include_router(setup_router, prefix="/api/v1")
app.include_router(showcase_router, prefix="/api/v1")
app.include_router(github_tokens_router, prefix="/api/v1")
app.include_router(ai_settings_router, prefix="/api/v1")
app.include_router(watch_router, prefix="/api/v1")
app.include_router(watch_flow_router, prefix="/api/v1")
app.include_router(topics_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
# The short domain points its `/p/` at the API root; behind nginx the same route also answers under /api/v1.
app.include_router(links_router)
app.include_router(links_router, prefix="/api/v1")
app.mount("/mfa/assets", StaticFiles(directory=Path(__file__).resolve().parent / "web"), name="mfa-assets")


@app.get("/mfa", include_in_schema=False)
async def mfa_console() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent / "web" / "mfa.html")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": settings.app_name, "project": settings.project_name}
