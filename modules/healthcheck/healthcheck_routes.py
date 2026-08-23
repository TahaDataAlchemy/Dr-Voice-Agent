from fastapi import APIRouter
from modules.healthcheck.routes import health_router

# Router for the health check
API_ROUTER = APIRouter(prefix="/api/v1", tags=["Health Check"])

# Include all routers from the health check
API_ROUTER.include_router(health_router)