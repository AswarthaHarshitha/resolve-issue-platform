"""Shared helper for tests that need a real, validly-signed JWT for a given
user - avoids repeating the same jose.jwt.encode boilerplate in every test
file that exercises a protected endpoint."""

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import get_settings

settings = get_settings()


def token_for(user, exp_delta: timedelta = timedelta(minutes=60)) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iat": int(now.timestamp()), "exp": now + exp_delta}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def auth_headers(user) -> dict:
    return {"Authorization": f"Bearer {token_for(user)}"}
