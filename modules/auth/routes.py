from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, status
from fastapi.responses import JSONResponse

from core.database import SessionDep
from core.responses import envelope
from core.security import get_current_user
from modules.auth.auth_schemas import LoginRequest, SignupRequest, UserRead
from modules.auth.auth_service import AuthService
from modules.auth.user_model import User

auth_router = APIRouter(prefix="/auth", tags=["Auth"])


@auth_router.post("/signup", status_code=status.HTTP_201_CREATED, summary="Create a dashboard account")
def signup(payload: Annotated[SignupRequest, Body()], session: SessionDep) -> JSONResponse:
    return envelope(AuthService(session).signup(payload), status.HTTP_201_CREATED)


@auth_router.post("/login", summary="Exchange email + password for a JWT")
def login(payload: Annotated[LoginRequest, Body()], session: SessionDep) -> JSONResponse:
    return envelope(AuthService(session).login(payload))


@auth_router.get("/me", summary="Current user")
def me(user: Annotated[User, Depends(get_current_user)]) -> JSONResponse:
    return envelope(UserRead.model_validate(user))
