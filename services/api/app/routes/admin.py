from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run-discovery")
def run_discovery() -> dict[str, str]:
    return {"status": "queued-placeholder"}


@router.post("/run-audit/{lead_id}")
def run_audit(lead_id: str) -> dict[str, str]:
    return {"lead_id": lead_id, "status": "queued-placeholder"}


@router.post("/mark-optout/{lead_id}")
def mark_optout(lead_id: str) -> dict[str, str]:
    return {"lead_id": lead_id, "status": "optout-placeholder"}

