from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_agents import router as agents_router
from app.api.routes_client_profiles import router as client_profiles_router
from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_lawyer_profiles import router as lawyer_profiles_router
from app.api.routes_legal_opinions import router as legal_opinions_router
from app.api.routes_n8n import router as n8n_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Source-aware Ukrainian legal AI assistant for lawyer review workflows.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(agents_router)
    app.include_router(client_profiles_router)
    app.include_router(lawyer_profiles_router)
    app.include_router(legal_opinions_router)
    app.include_router(documents_router)
    app.include_router(n8n_router)
    return app


app = create_app()

