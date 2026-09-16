"""Attack-review Q9 (are database errors exposed?) and Q15 (what happens if
the database is unavailable during authentication?). Simulates a database
failure by overriding get_db to raise, since actually taking the test
database down mid-suite isn't practical - this still proves what a client
actually receives when the DB layer fails, not just that it "should" be
safe."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


def test_database_unavailable_during_login_returns_generic_error_without_leaking_details():
    """A real deployment (uvicorn) never re-raises an unhandled exception to
    the client - Starlette catches it and returns a generic 500. The shared
    `client` fixture's TestClient defaults to re-raising server exceptions
    (a debugging convenience), which would hide that behavior here, so this
    test builds its own TestClient with raise_server_exceptions=False to
    observe what an actual client receives."""

    def broken_get_db():
        raise OperationalError(
            "connection to server failed",
            params=None,
            orig=Exception("password authentication failed for user X"),
        )
        yield  # pragma: no cover - unreachable; keeps this a generator for FastAPI's Depends

    app.dependency_overrides[get_db] = broken_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as broken_client:
            response = broken_client.post(
                "/api/v1/auth/login", json={"email": "whoever@example.com", "password": "Whatever1"}
            )
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 500
    body_text = response.text.lower()
    assert "password authentication failed" not in body_text
    assert "traceback" not in body_text
    assert "operationalerror" not in body_text
