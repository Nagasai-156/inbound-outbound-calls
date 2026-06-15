"""Control API authentication middleware tests.

The control API places outbound calls, runs bulk campaigns and mints
LiveKit tokens — it must reject unauthenticated requests when a shared
secret is configured. /healthz stays open for probes. When no key is
configured it serves (backward-compat) but that path is covered too.
"""

from __future__ import annotations

import importlib

import pytest

try:
    from fastapi.testclient import TestClient

    _HAVE = True
except Exception:  # pragma: no cover
    _HAVE = False

pytestmark = pytest.mark.skipif(not _HAVE, reason="fastapi testclient missing")


def _client_with_key(monkeypatch, key: str):
    """Rebuild settings + server module with CONTROL_API_KEY set."""
    monkeypatch.setenv("CONTROL_API_KEY", key)
    import src.config as cfg

    cfg.get_settings.cache_clear()
    cfg.settings = cfg.get_settings()
    import src.web.server as server

    importlib.reload(server)
    # reload re-binds module-level `settings`; ensure it sees our value
    server.settings = cfg.settings
    return TestClient(server.app), server


def test_healthz_open_without_key(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "")
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_healthz_open_even_with_key(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "s3cret")
    r = client.get("/healthz")
    assert r.status_code == 200


def test_rejects_missing_key(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "s3cret")
    r = client.post("/api/outbound", json={"phone_number": "+910000000000"})
    assert r.status_code == 401


def test_rejects_wrong_key(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "s3cret")
    r = client.post(
        "/api/outbound",
        json={"phone_number": "+910000000000"},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401


def test_accepts_correct_key_passes_auth(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "s3cret")
    # Correct key clears the auth gate; the handler itself may still 4xx/5xx
    # (LiveKit not configured in tests) — the point is it's NOT 401.
    r = client.post(
        "/api/config/reload",
        headers={"X-API-Key": "s3cret"},
    )
    assert r.status_code != 401


def test_no_key_configured_allows(monkeypatch):
    client, _ = _client_with_key(monkeypatch, "")
    # Backward-compat: unauthenticated path still served (warned in logs).
    r = client.post("/api/config/reload")
    assert r.status_code != 401
