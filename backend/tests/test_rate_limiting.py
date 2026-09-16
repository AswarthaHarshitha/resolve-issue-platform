"""Attack-review Q12: can an attacker repeatedly attempt login without any
protection? Exercises the real in-memory limiter (app/core/rate_limit.py),
not a mock - the _reset_auth_rate_limiter autouse fixture in conftest.py
guarantees a clean counter at the start of this test regardless of what ran
before it."""

from app.core.rate_limit import auth_rate_limiter


def test_repeated_login_attempts_are_rate_limited(client):
    for _ in range(auth_rate_limiter.max_attempts):
        response = client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WhateverItTakes1"}
        )
        assert response.status_code == 401

    limited_response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WhateverItTakes1"}
    )

    assert limited_response.status_code == 429


def test_repeated_registration_attempts_are_rate_limited(client):
    for i in range(auth_rate_limiter.max_attempts):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": f"ratelimit{i}@example.com", "password": "Sup3rSecret1", "full_name": "X"},
        )
        assert response.status_code == 201

    limited_response = client.post(
        "/api/v1/auth/register",
        json={"email": "onemore@example.com", "password": "Sup3rSecret1", "full_name": "X"},
    )

    assert limited_response.status_code == 429
