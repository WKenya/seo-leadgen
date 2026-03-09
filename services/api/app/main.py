from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from app.routes.audits import router as audits_router
from app.routes.admin import router as admin_router
from app.routes.artifacts import router as artifacts_router
from app.routes.drafts import router as drafts_router
from app.routes.health import router as health_router
from app.routes.leads import router as leads_router
from app.routes.metrics import router as metrics_router
from app.routes.suppression import router as suppression_router
from app.routes.webhooks import router as webhooks_router
from app.settings import get_settings

_request_logger = logging.getLogger("seo_lead.api")


def _request_id(request: Request) -> str:
    raw = (request.headers.get("x-request-id") or "").strip()
    return raw or str(uuid4())


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        started = time.perf_counter()
        req_id = _request_id(request)
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        if "x-request-id" not in response.headers:
            response.headers["x-request-id"] = req_id
        _request_logger.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
        )
        return response

    app.include_router(health_router)
    app.include_router(leads_router)
    app.include_router(metrics_router)
    app.include_router(drafts_router)
    app.include_router(audits_router)
    app.include_router(suppression_router)
    app.include_router(webhooks_router)
    app.include_router(admin_router)
    app.include_router(artifacts_router)
    return app


app = create_app()
