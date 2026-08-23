from fastapi import APIRouter

from modules.calls.routes import calls_router, patient_calls_router

API_ROUTER = APIRouter(prefix="/api/v1")
API_ROUTER.include_router(calls_router)
API_ROUTER.include_router(patient_calls_router)
