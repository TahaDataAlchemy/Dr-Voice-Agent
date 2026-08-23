from fastapi import APIRouter

from modules.auth.routes import auth_router

API_ROUTER = APIRouter(prefix="/api/v1")
API_ROUTER.include_router(auth_router)
