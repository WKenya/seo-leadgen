from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.settings import get_settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_path:path}")
def get_artifact(artifact_path: str) -> FileResponse:
    settings = get_settings()
    base = Path(settings.artifacts_root).resolve()
    target = (base / artifact_path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target)
