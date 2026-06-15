"""Test Cartesia WebSocket streaming for ultra-low latency TTS.

Measures TTFB (time-to-first-byte) — target <150ms.
If this works, we'll wire it into src/pipeline/tts.py for live calls.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import wave
from pathlib import Path

_OUTPUT_DIR = Path("tts_samples/cartesia_ws")

# Test phrase
_TEXT = "హలో! జన్నారా క్లినిక్ నుంచి మాట్లాడుతున్నాను."

# Voice IDs to test
_VOICES = [
    ("79a125e8-cd45-4c13-8a67-188112f4dd22", "British_Lady"),
    ("a0e99841-438c-4a64-b679-ae501e7d6091", "Barbershop_Man"),
]


async def test_websocket(api_key: str, voice_id: str, voice_label: str):
    """Test WebSocket streaming with proper auth."""
    import websockets
    
    ws_url = f"wss://api.cartesia.ai/tts/websocket?api_key={api_key}&cartesia_version=2024-06-10"
    
    # Request message
    msg = {
        "context_id": f"test_{int(time.time())}",  # Required unique ID
        "model_id": "sonic-3.5",
        "voice": {"mode": "id", "id": voice_id},
        "transcript": _TEXT,
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
        "language": "te",
    }
    
    t0 = time.monotonic()
    ttfb = None
    chunks = []
    
    try:
        async with websockets.connect(ws_url) as ws:
            # Send request
            await ws.send(json.dumps(msg))
            
            # Receive audio chunks
            chunk_count = 0
            async for raw_msg in ws:
                chunk_count += 1
                
                # Debug first few messages
                if chunk_count <= 3:
                    print(f"  [Debug] Message {chunk_count}: {str(raw_msg)[:200]}")
                
                try:
                    data = json.loads(raw_msg)
                    
                    # Check for audio field (might be "data" or "audio" or "chunk")
                    audio_b64 = data.get("data") or data.get("audio") or data.get("chunk")
                    
                    if audio_b64 and ttfb is None:
                        ttfb = (time.monotonic() - t0) * 1000
                    
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        chunks.append(audio_bytes)
                    
                    # Check done
                    if data.get("done") or data.get("status") == "done":
                        break
                
                except json.JSONDecodeError:
                    # Might be binary
                    if ttfb is None:
                        ttfb = (time.monotonic() - t0) * 1000
                    chunks.append(raw_msg)
        
        total = (time.monotonic() - t0) * 1000
        
        if chunks and ttfb:
            # Save WAV
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            filepath = _OUTPUT_DIR / f"{voice_label}_ws.wav"
            
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(24000)
                wf.writeframes(b''.join(chunks))
            
            size_kb = filepath.stat().st_size / 1024
            
            print(f"✅ {voice_label}")
            print(f"   TTFB: {ttfb:.0f}ms  Total: {total:.0f}ms  Size: {size_kb:.1f}KB")
            print(f"   Saved: {filepath}")
            
            return ttfb
        else:
            print(f"❌ {voice_label} — No audio (chunks={len(chunks)}, ttfb={ttfb})")
            return None
    
    except Exception as e:
        print(f"❌ {voice_label} — {type(e).__name__}: {str(e)[:150]}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    api_key = os.environ.get("CARTESIA_API_KEY")
    if not api_key:
        try:
            from src.config import settings
            api_key = settings.cartesia_api_key
        except:
            pass
    
    if not api_key:
        print("ERROR: CARTESIA_API_KEY not set")
        return
    
    print("="*60)
    print("Cartesia WebSocket Latency Test")
    print("="*60)
    print(f"Text: {_TEXT}")
    print()
    
    results = []
    for voice_id, voice_label in _VOICES:
        ttfb = await test_websocket(api_key, voice_id, voice_label)
        if ttfb:
            results.append((voice_label, ttfb))
        await asyncio.sleep(0.3)
    
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    if results:
        avg_ttfb = sum(t for _, t in results) / len(results)
        print(f"Average TTFB: {avg_ttfb:.0f}ms")
        print(f"Target: <150ms (Cartesia claims ~90ms)")
        print(f"\nComparison:")
        print(f"  Sarvam Bulbul HTTP: ~460ms")
        print(f"  Cartesia WebSocket: ~{avg_ttfb:.0f}ms")
        print(f"  Latency reduction: {460 - avg_ttfb:.0f}ms ({(1 - avg_ttfb/460)*100:.0f}% faster)")
    else:
        print("No successful tests")
    
    print("\nIf TTFB < 200ms → Wire into src/pipeline/tts.py for live calls")


if __name__ == "__main__":
    asyncio.run(main())
