from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import enforce_auth_rate_limit
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.invite import InviteActivateRequest, InviteActivateResponse
from app.schemas.user import UserPublic
from app.services import auth_service, invite_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    try:
        return auth_service.register_user(
            db, email=payload.email, password=payload.password, full_name=payload.full_name
        )
    except auth_service.EmailAlreadyRegisteredError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = auth_service.authenticate_user(
            db, email=payload.email, password=payload.password, login_context=payload.login_context
        )
    except auth_service.InvalidCredentialsError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    except auth_service.AccountDisabledError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account has been disabled")

    token = auth_service.issue_access_token(user)
    return TokenResponse(access_token=token, user=user)


@router.post(
    "/activate",
    response_model=InviteActivateResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
def activate_invite(payload: InviteActivateRequest, db: Session = Depends(get_db)) -> InviteActivateResponse:
    """Public, unauthenticated - the one-time token itself is the proof of
    authorization here, exactly like a password-reset link (DECISIONS.md
    D52). A RESOLVER/ADMIN account is created with the role/team the
    inviting admin specified - never anything the activation request body
    could influence."""
    try:
        user = invite_service.activate_invite(
            db, raw_token=payload.token, password=payload.password, full_name=payload.full_name
        )
    except invite_service.InvalidOrExpiredTokenError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invitation link is invalid or has expired")

    token = auth_service.issue_access_token(user)
    return InviteActivateResponse(access_token=token, user=user)


@router.get("/me", response_model=UserPublic)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: User = Depends(get_current_user)) -> None:
    """Stateless JWTs mean there is nothing to invalidate server-side - this
    endpoint exists for API/frontend symmetry and to confirm the caller held
    a valid token, but the token itself remains valid until it naturally
    expires. The frontend discarding it IS the actual logout. See
    DECISIONS.md D22 for the full tradeoff."""
    return None
