from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, issues, rbac_demo
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

# Restricted to configured origins (never "*") - see DECISIONS.md D28.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(issues.router, prefix="/api/v1")
app.include_router(rbac_demo.router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "environment": settings.environment}
