"""Probe Cartesia TTS for Telugu voice quality + latency vs Sarvam.

Tests:
  1. Telugu multilingual voices (emotion, streaming latency)
  2. First-byte latency (TTFT) — Cartesia claims ~90ms
  3. Voice naturalness vs Sarvam Bulbul anushka (current)
  4. Emotion control (warmth, excitement for sales calls)

Setup:
  1. Add CARTESIA_API_KEY to .env
  2. pip install websockets (for streaming)
  3. python -m scripts.probe_cartesia

Outputs audio samples to tts_samples/cartesia/ for A/B comparison.
Read-only probe. Changes no config.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

# Test phrases — same as Sarvam probe for fair comparison
_PHRASES = [
    ("greeting", "హలో! జన్నారా క్లినిక్ నుంచి మాట్లాడుతున్నాను. మీ appointment confirm చేయడానికి call చేశాను."),
    ("question", "రేపు morning పదిన్నరకి మీ appointment ఉంది. రాగలుగుతారా?"),
    ("services", "మా clinic లో medical aesthetics, dermatology, మరియు wellness services అందిస్తున్నాం."),
    ("filler", "హా అండి, చెప్పండి."),
]

# Cartesia voices to test (multilingual + Telugu support)
# https://docs.cartesia.ai/get-started/available-models
_VOICES = [
    ("79a125e8-cd45-4c13-8a67-188112f4dd22", "British Lady", "female"),
    ("a0e99841-438c-4a64-b679-ae501e7d6091", "Barbershop Man", "male"),
    ("248be419-c632-4f23-adf1-5324ed7dbf1d", "Classy British Man", "male"),
    # Add Telugu-optimized voices if found in their library
]

_OUTPUT_DIR = Path("tts_samples/cartesia")


async def _probe_streaming(api_key: str, voice_id: str, voice_label: str, text: str, label: str):
    """Streaming probe: WebSocket for first-byte latency."""
    try:
        import websockets
    except ImportError:
        print("websockets not installed. Run: pip install websockets")
        return
    
    ws_url = "wss://api.cartesia.ai/tts/websocket"
    
    # Cartesia WebSocket message format
    msg = {
        "model_id": "sonic-english",  # Sonic = fastest (90ms TTFB)
        "voice": {
            "mode": "id",
            "id": voice_id,
        },
        "transcript": text,
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
        "language": "te",  # Telugu language code
    }
    
    t0 = time.monotonic()
    ttfb = None
    chunks = []
    
    try:
        async with websockets.connect(
            ws_url,
            extra_headers={"Cartesia-Version": "2024-06-10"},
        ) as ws:
            # Auth
            await ws.send(json.dumps({"api_key": api_key}))
            
            # Send TTS request
            await ws.send(json.dumps(msg))
            
            # Receive audio chunks
            async for raw_msg in ws:
                msg_data = json.loads(raw_msg)
                
                if "audio" in msg_data:
                    if ttfb is None:
                        ttfb = (time.monotonic() - t0) * 1000
                    # Base64 audio data
                    import base64
                    audio_bytes = base64.b64decode(msg_data["audio"])
                    chunks.append(audio_bytes)
                
                if msg_data.get("done"):
                    break
        
        total = (time.monotonic() - t0) * 1000
        
        # Save audio file
        if chunks:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"{label}_{voice_label.lower().replace(' ', '_')}.wav"
            filepath = _OUTPUT_DIR / filename
            
            # Write WAV file (PCM s16le, 24kHz)
            import wave
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(24000)
                wf.writeframes(b''.join(chunks))
            
            file_size_kb = filepath.stat().st_size / 1024
            
            print(f"[{voice_label} | {label}]")
            print(f"  TTFB={ttfb:.0f}ms  total={total:.0f}ms  size={file_size_kb:.1f}KB")
            print(f"  saved: {filepath}")
        else:
            print(f"[{voice_label} | {label}] ERROR: No audio received")
    
    except Exception as e:
        print(f"[{voice_label} | {label}] ERROR: {type(e).__name__}: {str(e)[:200]}")


async def _probe_http(api_key: str, voice_id: str, voice_label: str, text: str, label: str):
    """HTTP streaming probe (fallback if WebSocket fails)."""
    import requests
    
    url = "https://api.cartesia.ai/tts/bytes"
    
    payload = {
        "model_id": "sonic-3.5",  # Latest Sonic model (multilingual, 40+ langs)
        "voice": {"mode": "id", "id": voice_id},
        "transcript": text,
        "output_format": {
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
        "language": "te",  # Telugu
    }
    
    headers = {
        "Cartesia-Version": "2024-06-10",
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    
    t0 = time.monotonic()
    ttfb = None
    
    try:
        resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=10)
        
        # Debug 400 errors
        if resp.status_code == 400:
            print(f"[{voice_label} | {label} HTTP] ERROR 400: {resp.text[:300]}")
            return
        
        resp.raise_for_status()
        
        chunks = []
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                if ttfb is None:
                    ttfb = (time.monotonic() - t0) * 1000
                chunks.append(chunk)
        
        total = (time.monotonic() - t0) * 1000
        
        if chunks:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"{label}_{voice_label.lower().replace(' ', '_')}_http.wav"
            filepath = _OUTPUT_DIR / filename
            filepath.write_bytes(b''.join(chunks))
            
            file_size_kb = filepath.stat().st_size / 1024
            
            print(f"[{voice_label} | {label} HTTP]")
            print(f"  TTFB={ttfb:.0f}ms  total={total:.0f}ms  size={file_size_kb:.1f}KB")
            print(f"  saved: {filepath}")
    
    except Exception as e:
        print(f"[{voice_label} | {label} HTTP] ERROR: {type(e).__name__}: {str(e)[:200]}")


async def main():
    api_key = os.environ.get("CARTESIA_API_KEY")
    if not api_key:
        try:
            from src.config import settings
            api_key = settings.cartesia_api_key
        except Exception:
            pass
    
    if not api_key:
        print("ERROR: CARTESIA_API_KEY not set in .env")
        print("Get one from: https://play.cartesia.ai/")
        print("Add to .env: CARTESIA_API_KEY=sk_car_...")
        return
    
    print("=" * 60)
    print("Cartesia TTS Probe — Telugu Voice Quality + Latency")
    print("=" * 60)
    print(f"Output directory: {_OUTPUT_DIR.absolute()}")
    print()
    
    # Test each voice with multiple phrases
    # Use HTTP for now (WebSocket auth has version issue)
    for voice_id, voice_label, gender in _VOICES:
        print(f"\n{'='*60}")
        print(f"Testing: {voice_label} ({gender})")
        print('='*60)
        
        for phrase_label, text in _PHRASES[:2]:  # Test first 2 phrases per voice
            await _probe_http(api_key, voice_id, voice_label, text, phrase_label)
            await asyncio.sleep(0.3)  # Rate limit courtesy
    
    print("\n" + "="*60)
    print("COMPARISON CHECKLIST:")
    print("="*60)
    print("1. Listen to tts_samples/cartesia/*.wav files")
    print("2. Compare with tts_samples/*.wav (Sarvam Bulbul)")
    print("3. Check:")
    print("   - Telugu pronunciation quality (తెలుగు clarity)")
    print("   - English words (appointment, clinic, confirm)")
    print("   - Naturalness vs robotic feel")
    print("   - TTFB latency (target: <200ms HTTP, <100ms WebSocket)")
    print("4. If better → wire into src/pipeline/tts.py")
    print("\nSarvam current: anushka ~460ms TTFB")
    print("Cartesia HTTP target: ~150-200ms TTFB (still 2-3x faster)")


if __name__ == "__main__":
    asyncio.run(main())
