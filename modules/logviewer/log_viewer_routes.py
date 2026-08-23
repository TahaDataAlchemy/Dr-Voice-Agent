from fastapi import APIRouter
from modules.logviewer.routes import log_router

# Router for the log viewer
API_ROUTER = APIRouter(prefix="/api/v1", tags=["Log Viewer"])

# Include all routers from the log viewer
API_ROUTER.include_router(log_router)