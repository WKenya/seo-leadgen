import base64
from pathlib import Path
import secrets

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app.settings import get_settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _require_artifact_auth(authorization: str | None, settings) -> None:
    if not settings.artifacts_basic_auth_user and not settings.artifacts_basic_auth_pass:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "basic" or not token:
        raise HTTPException(status_code=401, detail="auth required", headers={"WWW-Authenticate": "Basic"})
    try:
        raw = base64.b64decode(token, validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="invalid auth", headers={"WWW-Authenticate": "Basic"}) from exc
    if not (
        secrets.compare_digest(username, settings.artifacts_basic_auth_user)
        and secrets.compare_digest(password, settings.artifacts_basic_auth_pass)
    ):
        raise HTTPException(status_code=401, detail="invalid auth", headers={"WWW-Authenticate": "Basic"})


@router.get("/{artifact_path:path}")
def get_artifact(artifact_path: str, authorization: str | None = Header(default=None)) -> FileResponse:
    settings = get_settings()
    _require_artifact_auth(authorization, settings)
    base = Path(settings.artifacts_root).resolve()
    target = (base / artifact_path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target)
