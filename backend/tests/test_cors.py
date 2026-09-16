"""Attack-review Q11: is CORS unrestricted? Verifies the configured origin
allow-list (app/main.py + app/core/config.py) actually restricts responses,
rather than just asserting the config value looks right."""

from app.core.config import get_settings

settings = get_settings()


def test_cors_configuration_is_not_wildcarded():
    assert "*" not in settings.cors_origins_list
    assert settings.cors_origins_list  # non-empty, at least the dev frontend origin


def test_allowed_origin_receives_cors_header(client):
    allowed_origin = settings.cors_origins_list[0]

    response = client.get("/health", headers={"Origin": allowed_origin})

    assert response.headers.get("access-control-allow-origin") == allowed_origin


def test_disallowed_origin_does_not_receive_cors_header(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert response.headers.get("access-control-allow-origin") is None
