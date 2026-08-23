from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import Session, select

from config import get_settings
from core.logger.logger import LOG
from core.responses import ConflictError
from core.security import create_access_token, hash_password, verify_password
from modules.auth.auth_schemas import LoginRequest, SignupRequest, TokenResponse, UserRead
from modules.auth.user_model import User


class AuthService:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def get_by_email(self, email: str) -> User | None:
        return self.session.exec(select(User).where(User.email == email.lower())).first()

    def signup(self, data: SignupRequest) -> TokenResponse:
        if not self.settings.allow_signup:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Signup is disabled")
        if self.get_by_email(data.email):
            raise ConflictError("An account with this email already exists")
        user = User(email=data.email.lower(), hashed_password=hash_password(data.password), full_name=data.full_name)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        LOG.info("user.signup", extra={"event": "user.signup", "user_id": str(user.id)})
        return self._token_for(user)

    def login(self, data: LoginRequest) -> TokenResponse:
        user = self.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.hashed_password) or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
        return self._token_for(user)

    def ensure_demo_user(self) -> None:
        """Create the demo login (used by reviewers) if it does not exist."""
        if self.get_by_email(self.settings.demo_user_email):
            return
        user = User(
            email=self.settings.demo_user_email.lower(),
            hashed_password=hash_password(self.settings.demo_user_password),
            full_name="Demo Reviewer",
        )
        self.session.add(user)
        self.session.commit()
        LOG.info("user.demo_created", extra={"event": "user.demo_created", "email": user.email})

    def _token_for(self, user: User) -> TokenResponse:
        token = create_access_token(str(user.id))
        return TokenResponse(
            access_token=token,
            expires_in=self.settings.access_token_expire_minutes * 60,
            user=UserRead.model_validate(user),
        )
