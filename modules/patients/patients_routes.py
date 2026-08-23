from fastapi import APIRouter

from modules.patients.routes import patients_router

# The assessment specifies `/patients` at the root - that is the documented router.
ROOT_ROUTER = APIRouter()
ROOT_ROUTER.include_router(patients_router)

# FastCrate convention keeps everything under /api/v1 - expose the same routes there as a hidden alias.
API_ROUTER = APIRouter(prefix="/api/v1", include_in_schema=False)
API_ROUTER.include_router(patients_router)
