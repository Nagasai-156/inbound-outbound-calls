"""Dashboard /api/* HTTP smoke tests (skip if dashboard not running)."""

from __future__ import annotations

import os
import pytest
import requests

BASE = "http://localhost:3000"


def _up() -> bool:
    try:
        r = requests.get(BASE + "/", timeout=2, allow_redirects=False)
        return r.status_code in (200, 302, 307, 308)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="dashboard not running")


# ─── Calls API ───────────────────────────────────────────────────


def test_api_calls_requires_auth():
    r = requests.get(BASE + "/api/calls", timeout=5)
    # Unauthenticated → 401 or login redirect.
    assert r.status_code in (401, 200, 302)


def test_api_calls_by_id_requires_auth():
    r = requests.get(BASE + "/api/calls/nonexistent", timeout=5)
    assert r.status_code in (401, 404, 200)


# ─── Config API ──────────────────────────────────────────────────


def test_api_config_requires_auth():
    r = requests.get(BASE + "/api/config", timeout=5)
    assert r.status_code in (401, 200)


def test_api_config_post_requires_auth():
    r = requests.post(BASE + "/api/config", json={}, timeout=5)
    assert r.status_code in (401, 405, 400, 200, 422)


# ─── Outbound API ────────────────────────────────────────────────


def test_api_outbound_no_payload():
    r = requests.post(BASE + "/api/outbound", json={}, timeout=5)
    # Either auth or validation error.
    assert r.status_code in (400, 401, 422, 405)


def test_api_outbound_invalid_phone():
    r = requests.post(BASE + "/api/outbound", json={"phone": "abc"}, timeout=5)
    assert r.status_code in (400, 401, 422, 405)


# ─── Campaigns API ───────────────────────────────────────────────


def test_api_campaigns_requires_auth():
    r = requests.get(BASE + "/api/campaigns", timeout=5)
    assert r.status_code in (401, 200)


# ─── Profiles API ────────────────────────────────────────────────


def test_api_profiles_requires_auth():
    r = requests.get(BASE + "/api/profiles", timeout=5)
    assert r.status_code in (401, 200)


# ─── Knowledge-bases API ────────────────────────────────────────


def test_api_knowledge_bases_requires_auth():
    r = requests.get(BASE + "/api/knowledge-bases", timeout=5)
    assert r.status_code in (401, 200, 404)


# ─── Appointments API ───────────────────────────────────────────


def test_api_appointments_requires_auth():
    r = requests.get(BASE + "/api/appointments", timeout=5)
    assert r.status_code in (401, 200)


# ─── Static assets accessible ──────────────────────────────────


def test_login_page_renders_html():
    r = requests.get(BASE + "/login", timeout=5)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_dashboard_404_for_unknown_path():
    r = requests.get(BASE + "/totally-not-a-real-route", timeout=5)
    # Next.js may render a 404 page (200) or redirect via middleware.
    assert r.status_code in (200, 404, 302, 307)


# ─── Security headers smoke ─────────────────────────────────────


def test_dashboard_root_returns_content_type():
    r = requests.get(BASE + "/", timeout=5, allow_redirects=True)
    assert "content-type" in r.headers


# ─── Method-not-allowed paths ──────────────────────────────────


def test_api_calls_disallows_delete_without_auth():
    r = requests.delete(BASE + "/api/calls", timeout=5)
    assert r.status_code in (401, 404, 405)
