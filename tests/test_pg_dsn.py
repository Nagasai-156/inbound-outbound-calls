"""PgBouncer/Supabase DSN sanitization tests for src/pg.py.

A DSN bug at startup blocks ALL persistence — every call goes "live"
but transcripts/calls don't land in Supabase. Tests ensure asyncpg-
compatible kwargs come out for the common Supabase URL shapes."""

from __future__ import annotations

import ssl

from src.pg import asyncpg_args


def test_simple_dsn_no_params_passes_through():
    url = "postgresql://user:pw@host:5432/db"
    clean, kwargs = asyncpg_args(url)
    assert "?" not in clean
    assert kwargs == {}


def test_pgbouncer_true_sets_statement_cache_size_zero():
    """PgBouncer transaction-pooling can't keep prepared statements."""
    url = "postgresql://u:p@h:5432/db?pgbouncer=true"
    _, kwargs = asyncpg_args(url)
    assert kwargs.get("statement_cache_size") == 0


def test_pgbouncer_false_does_not_set_cache_size():
    url = "postgresql://u:p@h/db?pgbouncer=false"
    _, kwargs = asyncpg_args(url)
    assert "statement_cache_size" not in kwargs


def test_sslmode_require_sets_ssl_context():
    url = "postgresql://u:p@h/db?sslmode=require"
    _, kwargs = asyncpg_args(url)
    assert "ssl" in kwargs
    # require → context with verify disabled (Supabase pooler chain).
    ctx = kwargs["ssl"]
    assert ctx.verify_mode == ssl.CERT_NONE


def test_sslmode_verify_full_keeps_verification():
    url = "postgresql://u:p@h/db?sslmode=verify-full"
    _, kwargs = asyncpg_args(url)
    assert "ssl" in kwargs


def test_sslmode_disable_does_not_add_ssl_kwarg():
    url = "postgresql://u:p@h/db?sslmode=disable"
    _, kwargs = asyncpg_args(url)
    assert "ssl" not in kwargs


def test_stripped_params_removed_from_clean_url():
    """asyncpg can't handle these params in the URL — must be stripped."""
    url = "postgresql://u:p@h:5432/db?pgbouncer=true&sslmode=require&channel_binding=disable"
    clean, _ = asyncpg_args(url)
    assert "pgbouncer" not in clean
    assert "sslmode" not in clean
    assert "channel_binding" not in clean


def test_unknown_params_preserved_in_clean_url():
    """Custom application params should pass through untouched."""
    url = "postgresql://u:p@h/db?application_name=worker&pgbouncer=true"
    clean, _ = asyncpg_args(url)
    assert "application_name=worker" in clean
    assert "pgbouncer" not in clean


def test_empty_url_returns_empty():
    clean, kwargs = asyncpg_args("")
    assert clean == ""
    assert kwargs == {}


def test_none_url_returns_none():
    clean, kwargs = asyncpg_args(None)
    assert clean is None
    assert kwargs == {}


def test_supabase_full_pooler_url():
    """Realistic Supabase pooler URL shape — verify the full chain."""
    url = (
        "postgresql://postgres.abc:secret@aws-1-ap-southeast-1.pooler.supabase.com:5432"
        "/postgres?pgbouncer=true&sslmode=require"
    )
    clean, kwargs = asyncpg_args(url)
    # Both params stripped, both kwargs set.
    assert "pgbouncer" not in clean
    assert "sslmode" not in clean
    assert kwargs.get("statement_cache_size") == 0
    assert "ssl" in kwargs


def test_multiple_values_for_same_param_preserved_for_passthrough():
    url = "postgresql://u:p@h/db?application_name=a&application_name=b"
    clean, _ = asyncpg_args(url)
    # Both should be in the cleaned query.
    assert "application_name=a" in clean
    assert "application_name=b" in clean


def test_clean_dsn_still_parseable_by_asyncpg_format():
    """Just verify the result is a valid-looking URL string."""
    url = "postgresql://u:p@h:5432/db?pgbouncer=true"
    clean, _ = asyncpg_args(url)
    assert clean.startswith("postgresql://")
    assert "@h:5432/db" in clean
