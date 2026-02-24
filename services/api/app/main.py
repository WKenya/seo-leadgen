from fastapi import FastAPI

from app.routes.audits import router as audits_router
from app.routes.admin import router as admin_router
from app.routes.artifacts import router as artifacts_router
from app.routes.health import router as health_router
from app.routes.leads import router as leads_router
from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    app.include_router(leads_router)
    app.include_router(audits_router)
    app.include_router(admin_router)
    app.include_router(artifacts_router)
    return app


app = create_app()
