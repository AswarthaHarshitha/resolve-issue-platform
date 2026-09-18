"""Admin-issued RESOLVER/ADMIN invitations (DECISIONS.md D52). An admin
names an email and a role (never USER - that stays self-registration-only,
D23); the account does not exist until the invited person visits the
one-time activation link and sets their own password. The admin never
knows, chooses, or is shown that password at any point.

Security model for the token: a cryptographically random value
(secrets.token_urlsafe), returned to the inviting admin exactly once, at
creation. Only its SHA-256 digest is ever persisted - the database itself
cannot be used to recover or forge a valid token. Activation looks the
token up by re-hashing whatever was presented and comparing digests, so a
timing side-channel on "does this prefix look right" isn't meaningful the
way it would be for a shorter secret."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.roles import RoleName
from app.core.security import hash_password
from app.models.invite import Invite
from app.models.team import Team
from app.models.user import User
from app.repositories import role_repository, user_repository

INVITE_EXPIRY_DAYS = 7


class ValidationError(Exception):
    pass


class InvalidOrExpiredTokenError(Exception):
    pass


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_invite(
    db: Session, *, invited_by: User, email: str, role: str, team_id: Optional[UUID]
) -> tuple[Invite, str]:
    """Returns (invite, raw_token) - the caller (the API route) is
    responsible for building the activation_url from raw_token and
    returning it exactly once. Nothing about the raw token is retained
    after this call returns."""
    if user_repository.get_user_by_email(db, email) is not None:
        raise ValidationError(f"{email} is already a registered account")

    role_row = role_repository.get_role_by_name(db, role)
    if role_row is None:
        raise ValidationError(f"Unknown role: {role!r}")

    if role == RoleName.RESOLVER:
        if team_id is None:
            raise ValidationError("A RESOLVER invite must include a team_id (DECISIONS.md D18)")
        if db.get(Team, team_id) is None:
            raise ValidationError("team not found")
    elif team_id is not None:
        raise ValidationError("Only a RESOLVER invite may include a team_id")

    raw_token = secrets.token_urlsafe(32)
    invite = Invite(
        email=email,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRY_DAYS),
        role_id=role_row.id,
        team_id=team_id,
        invited_by_id=invited_by.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite, raw_token


def list_pending_invites(db: Session) -> List[Invite]:
    stmt = select(Invite).where(Invite.used_at.is_(None)).order_by(Invite.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def activate_invite(db: Session, *, raw_token: str, password: str, full_name: str) -> User:
    """Validates the token, creates the real User account with the role/
    team the invite specified, and consumes the invite - all inside one
    transaction, so a token can never be used twice even under a race (the
    invite row's own uniqueness on token_hash plus the used_at check inside
    this same commit make a second concurrent activation attempt fail
    cleanly rather than silently creating two accounts)."""
    token_hash = _hash_token(raw_token)
    invite = db.execute(select(Invite).where(Invite.token_hash == token_hash)).scalar_one_or_none()

    if invite is None or invite.used_at is not None or invite.expires_at < datetime.now(timezone.utc):
        raise InvalidOrExpiredTokenError()

    if user_repository.get_user_by_email(db, invite.email) is not None:
        # The email was registered some other way between the invite being
        # created and this activation attempt - the invite is stale, not
        # usable to silently take over or duplicate that account.
        raise InvalidOrExpiredTokenError()

    user = user_repository.create_user(
        db,
        email=invite.email,
        password_hash=hash_password(password),
        full_name=full_name,
        role_id=invite.role_id,
    )
    user.team_id = invite.team_id
    invite.used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user
