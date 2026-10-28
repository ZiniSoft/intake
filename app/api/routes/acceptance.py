from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto, require_member
from app.modules.planning import acceptance
from app.modules.planning.evidence import EvidenceError
from app.schemas import AcceptanceDecisionRequest, AcceptanceItemOut, AcceptanceQueueOut, EvidenceLinksRequest

router = APIRouter(prefix="/acceptance", tags=["acceptance"])

REASONS = {
    "REASON_REQUIRED": (status.HTTP_422_UNPROCESSABLE_ENTITY, "Nói rõ chưa xong ở chỗ nào"),
    "VERIFICATION_DECIDED": (status.HTTP_409_CONFLICT, "Việc này đã được quyết rồi"),
    "EVIDENCE_REASON_REQUIRED": (status.HTTP_422_UNPROCESSABLE_ENTITY, "Chưa có bằng chứng: dán link hoặc commit, hoặc ghi lý do vẫn xác nhận"),
}


@router.get("", response_model=AcceptanceQueueOut, openapi_extra={"x-requirement-ids": ["FR-PLAN-31", "FR-PLAN-22", "FR-ID-08"]})
async def get_acceptance_queue(project_id: str | None = Query(default=None), context: AuthContext = Depends(require_member)) -> AcceptanceQueueOut:
    """What waits to be accepted: the CTO's sample of the day apart from the rest; a Project Owner sees their projects."""
    return AcceptanceQueueOut.model_validate(acceptance.queue(context.project_ids, is_cto=context.role == "CTO", project_id=project_id))


@router.post("/{verification_id}/evidence", response_model=AcceptanceItemOut, openapi_extra={"x-requirement-ids": ["FR-PLAN-36", "FR-ID-08"]})
async def add_acceptance_evidence(verification_id: str, payload: EvidenceLinksRequest, context: AuthContext = Depends(require_member)) -> AcceptanceItemOut:
    """The acceptor pastes what stands behind the work: a commit or merge request for code, a link for anything else."""
    try:
        result = acceptance.add_evidence(verification_id, [link.model_dump() for link in payload.links], actor_id=context.user_id, allowed_project_ids=context.project_ids)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found") from exc
    except EvidenceError as exc:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc)) from exc
    return AcceptanceItemOut.model_validate(result)


@router.post("/{verification_id}/{decision}", response_model=AcceptanceItemOut, openapi_extra={"x-requirement-ids": ["FR-PLAN-31", "FR-PLAN-22", "FR-PLAN-36", "FR-ID-08"]})
async def decide_acceptance(
    verification_id: str, decision: Literal["accept", "reject"], payload: AcceptanceDecisionRequest, context: AuthContext = Depends(require_member),
) -> AcceptanceItemOut:
    """Done, or not done with a reason. The CTO's "done" closes the Issue on the tracker; the Project Owner's is recorded beside it."""
    try:
        result = acceptance.decide(
            verification_id, decision="ACCEPTED" if decision == "accept" else "REJECTED", reason=payload.reason,
            actor_id=context.user_id, role=context.role, allowed_project_ids=context.project_ids, evidence_missing_reason=payload.evidence_missing_reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found") from exc
    except acceptance.AcceptanceError as exc:
        code, message = REASONS.get(str(exc), (status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)))
        raise api_exception(code, str(exc), message) from exc
    return AcceptanceItemOut.model_validate(result)


@router.post("/sample", openapi_extra={"x-requirement-ids": ["FR-PLAN-31"]})
async def sample_more(extra: int = Query(default=5, ge=1, le=20), _: AuthContext = Depends(require_cto)) -> dict[str, object]:
    """The CTO wants to look at more than today's five."""
    return {"added": acceptance.sample(extra=extra)}


@router.post("/collect", openapi_extra={"x-requirement-ids": ["FR-PLAN-31"]})
async def collect_now(_: AuthContext = Depends(require_cto)) -> dict[str, object]:
    """Turn every recent "done" into an acceptance now instead of waiting for the next report or the 07:00 job."""
    return acceptance.collect()
