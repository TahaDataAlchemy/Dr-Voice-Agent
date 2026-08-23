from fastapi import APIRouter

from modules.voice.routes import voice_router

API_ROUTER = APIRouter(prefix="/api/v1")
API_ROUTER.include_router(voice_router)
