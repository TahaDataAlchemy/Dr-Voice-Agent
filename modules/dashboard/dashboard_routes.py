from fastapi import APIRouter

from modules.dashboard.routes import dashboard_router

API_ROUTER = APIRouter(prefix="/api/v1")
API_ROUTER.include_router(dashboard_router)
