from fastapi import APIRouter, Query

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def list_leads(status: str | None = Query(default=None)) -> dict[str, object]:
    return {"items": [], "status_filter": status}


@router.get("/{lead_id}")
def get_lead(lead_id: str) -> dict[str, object]:
    return {"id": lead_id, "status": "placeholder"}

