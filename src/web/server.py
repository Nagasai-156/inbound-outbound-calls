"""Python control API (LiveKit + telephony brain).

The dashboard UI now lives in the Next.js app (`dashboard/`) backed by
Supabase + Prisma. This service is intentionally thin: it only does the
things that need the LiveKit/Sarvam/OpenAI Python SDKs, and the Next.js
server proxies to it (server-to-server, so no CORS needed):

  POST /api/token            -> LiveKit join token (+ dispatch agent)
  POST /api/outbound         -> place an outbound call via Vobiz trunk
  POST /api/content/generate -> regenerate dynamic content pools (LLM->Redis)
  GET  /healthz

Calls/transcripts/config are read by the dashboard directly from
Supabase (durable) — not from here.

Run:
    uvicorn src.web.server:app --port 8000
"""

from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from livekit import api
from pydantic import BaseModel

from src.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("control-api")

app = FastAPI(title="AI Voice Calls — Control API")

# Endpoints reachable WITHOUT the shared secret (health probes only).
_AUTH_EXEMPT = {"/healthz", "/", "/docs", "/openapi.json", "/redoc"}
_warned_no_key = False


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    """Gate every endpoint on the shared `X-API-Key` secret.

    This service can place outbound calls, run bulk campaigns and mint
    LiveKit tokens — it MUST NOT be open. The Next.js dashboard sends the
    same secret on every proxy call.

    Backward-compat: if `CONTROL_API_KEY` is not configured, we log a
    loud one-time warning but still serve (so existing local/dev deploys
    keep working). In production, SET the key — then it's enforced with a
    timing-safe comparison.
    """
    global _warned_no_key
    expected = settings.control_api_key
    path = request.url.path
    if not expected:
        if not _warned_no_key:
            _warned_no_key = True
            logger.warning(
                "CONTROL_API_KEY is NOT set — the control API (outbound "
                "dialer / campaigns / LiveKit tokens) is UNAUTHENTICATED. "
                "Set CONTROL_API_KEY in the root .env and dashboard/.env "
                "for production."
            )
        return await call_next(request)
    if path in _AUTH_EXEMPT:
        return await call_next(request)
    provided = request.headers.get("x-api-key", "")
    if not (provided and hmac.compare_digest(provided, expected)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "livekit": settings.livekit_configured}


# ─── LiveKit token (browser test client joins w/ the agent) ──────────
class TokenReq(BaseModel):
    identity: str = "web-tester"
    room: str | None = None


@app.post("/api/token")
async def create_token(req: TokenReq):
    if not settings.livekit_configured:
        raise HTTPException(500, "LiveKit not configured in .env")
    room = req.room or f"web-{req.identity}"
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(req.identity)
        .with_name(req.identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=settings.agent_name)]
            )
        )
        .to_jwt()
    )
    return {"url": settings.livekit_url, "token": token, "room": room}


# ─── Outbound dialer ─────────────────────────────────────────────────
class OutboundReq(BaseModel):
    phone_number: str
    caller_id: str = ""
    name: str = ""
    language: str = ""
    script: str = ""            # per-call goal/script (test call)
    voice_model: str = ""
    voice_speaker: str = ""
    # Per-call use-case + content overrides (mirror campaign runner).
    # Without these the single-call test path was stuck on whatever
    # global use-case Settings had — couldn't pick custom/survey/etc.
    # for a one-off test, and couldn't override business/style/KB.
    use_case: str = ""
    business_description: str = ""
    style_examples: str = ""
    kb_vector_store_id: str = ""


@app.post("/api/outbound")
async def outbound(req: OutboundReq):
    from src.telephony.outbound import OutboundCallError, place_call

    try:
        room = await place_call(
            req.phone_number,
            name=req.name,
            language=req.language,
            script=req.script,
            voice_model=req.voice_model,
            voice_speaker=req.voice_speaker,
            use_case=req.use_case,
            business_description=req.business_description,
            style_examples=req.style_examples,
            kb_vector_store_id=req.kb_vector_store_id,
            caller_id=req.caller_id,
        )
        return {"status": "dialing", "room": room}
    except SystemExit as e:
        raise HTTPException(400, str(e))
    except OutboundCallError as e:
        # SIP/trunk rejected the dial (invalid number, no answer, trunk
        # down, etc.). Already cleaned up the orphan room. 400 so the
        # dashboard surfaces the human reason instead of "dial failed".
        raise HTTPException(400, e.reason)
    except Exception as e:
        raise HTTPException(500, f"dial failed: {e}")


# ─── Config reload (called by the dashboard right after a save) ──────
@app.post("/api/config/reload")
async def config_reload():
    """Bust the runtime-config Redis cache so the very next call —
    inbound or outbound — uses the just-saved Voice & Agent settings."""
    from src.runtime_config import invalidate_runtime_config

    await invalidate_runtime_config()
    return {"status": "reloaded"}


# ─── Voice preview (Sarvam TTS sample) ───────────────────────────────
_LANG = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}


class PreviewReq(BaseModel):
    text: str = "Hello, this is a voice sample."
    language: str = "en"
    speaker: str = "anushka"
    model: str = "bulbul:v2"


@app.post("/api/tts/preview")
async def tts_preview(req: PreviewReq):
    """Synthesize a short sample so the dashboard can preview a voice."""
    if not settings.sarvam_api_key:
        raise HTTPException(400, "SARVAM_API_KEY not set")
    import base64

    import httpx

    from src.pipeline.tts import _safe_model, _safe_speaker

    model = _safe_model(req.model)
    payload = {
        "text": req.text[:300],
        "target_language_code": _LANG.get(req.language, "en-IN"),
        "speaker": _safe_speaker(model, req.speaker),
        "model": model,
        "speech_sample_rate": 22050,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as cx:
            r = await cx.post(
                settings.sarvam_tts_url
                or "https://api.sarvam.ai/text-to-speech",
                headers={"api-subscription-key": settings.sarvam_api_key},
                json=payload,
            )
        if r.status_code >= 400:
            raise HTTPException(502, f"sarvam: {r.status_code} {r.text[:200]}")
        audios = r.json().get("audios") or []
        if not audios:
            raise HTTPException(502, "sarvam returned no audio")
        return Response(
            content=base64.b64decode(audios[0]), media_type="audio/wav"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"preview failed: {e}")


# ─── Campaign runner (bulk outbound, bounded concurrency) ────────────
# Max simultaneous live calls per campaign run. A campaign of 2-min
# calls without this would pile up unbounded -> provider rate limits +
# cost spikes (see plan P0-7).
_CAMPAIGN_MAX_CONCURRENT = 8
_CAMPAIGN_MAX_ATTEMPTS = 3
# Guard against duplicate concurrent runs of the same campaign (double
# click on Run, or Run + Re-run firing together). asyncio is single-
# threaded so the check+add below is race-free within this process.
_running_campaigns: set[str] = set()


async def _run_campaign(cid: str) -> None:
    if cid in _running_campaigns:
        logger.info(
            "campaign %s already running — ignoring duplicate start", cid
        )
        return
    _running_campaigns.add(cid)
    try:
        await _run_campaign_inner(cid)
    finally:
        _running_campaigns.discard(cid)


async def _run_campaign_inner(cid: str) -> None:
    from src import db
    from src.telephony.outbound import place_call

    camp = await db.get_campaign(cid)
    if not camp:
        return
    await db.set_campaign_status(cid, "running")
    contacts = await db.pending_contacts(cid)
    # Open a durable run record so THIS run's results survive a later
    # re-run (CampaignContact only keeps the latest live state).
    run_id = await db.create_campaign_run(cid, len(contacts))
    sem = asyncio.Semaphore(_CAMPAIGN_MAX_CONCURRENT)

    async def _safe(coro):
        """Run a db op that must never raise (zombie-contact guard)."""
        try:
            await coro
        except Exception:
            logger.debug("campaign db op failed", exc_info=True)

    async def _dial(ct: dict) -> None:
        # Stop retrying a contact that has already failed too many times.
        ph, nm = ct["phone"], ct.get("name", "")
        if int(ct.get("attempts", 0) or 0) >= _CAMPAIGN_MAX_ATTEMPTS:
            await _safe(db.update_contact(
                ct["id"], status="failed",
                error="max attempts reached"))
            await _safe(db.record_run_contact(
                run_id, ph, name=nm, status="failed",
                error="max attempts reached"))
            return
        async with sem:
            await _safe(db.update_contact(
                ct["id"], status="dialing", bump_attempts=True))
            await _safe(db.record_run_contact(
                run_id, ph, name=nm, status="dialing"))
            try:
                room = await place_call(
                    ph,
                    name=nm,
                    language=camp.get("language", ""),
                    script=camp.get("script", ""),
                    voice_model=camp.get("voiceModel", ""),
                    voice_speaker=camp.get("voiceSpeaker", ""),
                    use_case=camp.get("useCaseType", ""),
                    business_description=camp.get("businessDescription", ""),
                    style_examples=camp.get("styleExamples", ""),
                    kb_vector_store_id=camp.get("kbVectorStoreId", ""),
                    caller_id=camp.get("callerId", ""),
                )
                await _safe(db.update_contact(
                    ct["id"], status="done", room=room))
                await _safe(db.record_run_contact(
                    run_id, ph, name=nm, status="done", room=room))
            except Exception as e:
                await _safe(db.update_contact(
                    ct["id"], status="failed", error=str(e)[:300]))
                await _safe(db.record_run_contact(
                    run_id, ph, name=nm, status="failed",
                    error=str(e)[:300]))
            await _safe(db.refresh_campaign_counts(cid))

    # Launch with a small stagger; the semaphore caps true concurrency.
    tasks = []
    for ct in contacts:
        tasks.append(asyncio.ensure_future(_dial(ct)))
        await asyncio.sleep(1)  # gentle ramp, not a hard 3s serial wait
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await _safe(db.finalize_campaign_run(run_id))
    await _safe(db.set_campaign_status(cid, "done"))
    await _safe(db.refresh_campaign_counts(cid))


@app.post("/api/campaigns/{cid}/run")
async def run_campaign(cid: str):
    asyncio.ensure_future(_run_campaign(cid))
    return {"status": "started", "campaign": cid}


@app.post("/api/campaigns/{cid}/rerun")
async def rerun_campaign(cid: str, failed: int = 0):
    """Re-arm a finished campaign and dial it again.

    failed=1 -> retry only the contacts that did NOT complete.
    failed=0 -> re-run the entire contact list.
    """
    from src import db

    rearmed = await db.reset_campaign(cid, only_failed=bool(failed))
    if rearmed == 0:
        raise HTTPException(
            400,
            "nothing to re-run (no matching contacts)"
            if failed
            else "campaign has no contacts",
        )
    asyncio.ensure_future(_run_campaign(cid))
    return {"status": "restarted", "campaign": cid, "rearmed": rearmed}


# ─── Knowledge base ingest (file -> OpenAI vector store) ─────────────
def _extract_text(data: bytes, ext: str) -> str:
    """Best-effort text extraction for the supported file types."""
    if ext in (".txt", ".md", ".json", ".html"):
        text = data.decode("utf-8", errors="ignore")
        if ext == ".html":
            import re

            text = re.sub(r"<[^>]+>", " ", text)
        return text
    if ext == ".pdf":
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".docx":
        import io

        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    return ""


@app.post("/api/kb/upload")
async def kb_upload(file: UploadFile = File(...), kb_id: str = ""):
    import uuid as _uuid

    from fastapi import Form as _Form
    from src import db
    from src.kb_store import ingest_document

    doc_id = _uuid.uuid4().hex
    data = await file.read()
    fname = file.filename or "document"
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""
    allowed = {".pdf", ".txt", ".md", ".docx", ".json", ".html"}
    if ext not in allowed:
        raise HTTPException(
            400,
            f"Unsupported file type {ext or '?'} "
            f"(allowed: {sorted(allowed)})",
        )
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 25 MB)")
    if not settings.openai_api_key:
        raise HTTPException(400, "OPENAI_API_KEY not set (embeddings)")
    if not settings.supabase_db_url:
        raise HTTPException(400, "Supabase not configured (pgvector)")

    await db.insert_kb_document(doc_id, fname, len(data), kb_id=kb_id)
    try:
        text = _extract_text(data, ext)
        if not text.strip():
            raise ValueError("no extractable text in file")
        n = await ingest_document(doc_id, fname, text, kb_id=kb_id)
        await db.update_kb_document(
            doc_id, status="indexed", vector_store_id="pgvector"
        )
        return {"status": "indexed", "chunks": n}
    except Exception as e:
        await db.update_kb_document(doc_id, status="failed", error=str(e))
        raise HTTPException(500, f"ingest failed: {e}")


@app.delete("/api/kb/{doc_id}")
async def kb_delete(doc_id: str):
    from src.kb_store import delete_document

    try:
        await delete_document(doc_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(500, f"delete failed: {e}")


class KbTextReq(BaseModel):
    title: str = "Pasted note"
    text: str
    kb_id: str = ""


@app.post("/api/kb/text")
async def kb_text(req: KbTextReq):
    """Ingest pasted plain text directly (no file) into pgvector."""
    import uuid as _uuid

    from src import db
    from src.kb_store import ingest_document

    text = (req.text or "").strip()
    if len(text) < 5:
        raise HTTPException(400, "Text is empty / too short")
    if not settings.openai_api_key:
        raise HTTPException(400, "OPENAI_API_KEY not set (embeddings)")
    if not settings.supabase_db_url:
        raise HTTPException(400, "Supabase not configured (pgvector)")

    fname = (req.title.strip() or "Pasted note")[:120]
    doc_id = _uuid.uuid4().hex
    await db.insert_kb_document(doc_id, fname, len(text.encode()), kb_id=req.kb_id)
    try:
        n = await ingest_document(doc_id, fname, text, kb_id=req.kb_id)
        await db.update_kb_document(
            doc_id, status="indexed", vector_store_id="pgvector"
        )
        return {"status": "indexed", "chunks": n}
    except Exception as e:
        await db.update_kb_document(doc_id, status="failed", error=str(e))
        raise HTTPException(500, f"ingest failed: {e}")


# ─── Regenerate dynamic content (LLM -> Redis, offline) ──────────────
class ContentReq(BaseModel):
    business: str = ""
    n: int = 12


@app.post("/api/content/generate")
async def gen_content(req: ContentReq):
    from scripts.gen_content import _run

    asyncio.ensure_future(_run(req.business, req.n))
    return {"status": "started"}
