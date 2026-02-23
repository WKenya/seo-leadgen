from fastapi import APIRouter

from app.queue import celery_client

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run-discovery")
def run_discovery(
    city: str = "Cleveland, OH",
    category: str = "HVAC",
    radius_meters: int = 15000,
) -> dict[str, str]:
    task = celery_client.send_task(
        "discover_leads",
        kwargs={"city": city, "category": category, "radius_meters": radius_meters},
    )
    return {"status": "queued", "task_id": task.id}


@router.post("/run-audit/{lead_id}")
def run_audit(lead_id: str) -> dict[str, str]:
    task = celery_client.send_task("audit_lead", kwargs={"lead_id": lead_id})
    return {"lead_id": lead_id, "status": "queued", "task_id": task.id}


@router.post("/mark-optout/{lead_id}")
def mark_optout(lead_id: str) -> dict[str, str]:
    return {"lead_id": lead_id, "status": "todo"}
