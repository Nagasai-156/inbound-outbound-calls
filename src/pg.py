"""asyncpg DSN normalisation for Supabase/PgBouncer.

Supabase connection strings carry libpq-style query params
(`?pgbouncer=true&sslmode=require`) that asyncpg does NOT understand —
passing them raw makes asyncpg.connect raise. This strips those params
and returns the kwargs asyncpg actually needs:

  * `sslmode=require`  -> ssl=True
  * `pgbouncer=true`   -> statement_cache_size=0 (no prepared statements
    in transaction pooling mode)
"""

from __future__ import annotations

import ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Query keys asyncpg can't take as DSN params.
_STRIP = {"pgbouncer", "sslmode", "channel_binding", "connection_limit"}


def asyncpg_args(url: str) -> tuple[str, dict]:
    """Return (clean_dsn, connect_kwargs) for asyncpg.connect/create_pool."""
    if not url:
        return url, {}
    parts = urlparse(url)
    q = parse_qs(parts.query)
    kwargs: dict = {}

    sslmode = q.get("sslmode", [""])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        ctx = ssl.create_default_context()
        if sslmode == "require":
            # libpq 'require' = encrypt, do NOT verify the CA/hostname.
            # Supabase's pooler chain isn't in the local trust store, so
            # verifying here would wrongly fail every connection.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl"] = ctx
    if q.get("pgbouncer", [""])[0] == "true":
        # PgBouncer transaction pooling can't keep prepared statements.
        kwargs["statement_cache_size"] = 0

    kept = {k: v for k, v in q.items() if k not in _STRIP}
    clean = urlunparse(parts._replace(query=urlencode(kept, doseq=True)))
    return clean, kwargs
