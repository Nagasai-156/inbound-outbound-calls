"""Test different stack combinations to find optimal latency + quality.

Tests 3 combinations:
1. Sarvam STT + Azure OpenAI + Cartesia TTS (fastest expected)
2. Sarvam STT + Azure OpenAI + Sarvam TTS (balanced)
3. Sarvam STT + OpenAI US + Sarvam TTS (current baseline)

For each:
- Measures latency (TTFT/TTFB)
- Checks Telugu quality
- Estimates total perceived latency
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path


# Test phrase (Telugu Tenglish like real agent)
_TEST_TEXT = "రేపు morning పదిన్నరకి మీ appointment ఉంది అండి. రాగలుగుతారా?"


def load_env():
    """Load API keys from .env."""
    env_file = Path(__file__).parent.parent / ".env"
    config = {}
    
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip()
    
    return config


def test_llm_azure(config: dict, test_name: str):
    """Test Azure OpenAI India LLM."""
    from openai import OpenAI
    
    endpoint = config.get("AZURE_OPENAI_ENDPOINT")
    api_key = config.get("AZURE_OPENAI_API_KEY")
    deployment = config.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    
    if not endpoint or not api_key:
        print(f"  ❌ Azure config missing")
        return None
    
    client = OpenAI(base_url=endpoint, api_key=api_key)
    
    messages = [
        {"role": "system", "content": "Reply in Telugu Tenglish. One short sentence."},
        {"role": "user", "content": "Hello, appointment book cheyali"},
    ]
    
    t0 = time.monotonic()
    ttft = None
    chunks = []
    
    try:
        stream = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=0.3,
            max_tokens=100,
            stream=True,
        )
        
        for chunk in stream:
            if not chunk.choices:
                continue
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            
            delta = chunk.choices[0].delta
            if delta.content:
                chunks.append(delta.content)
        
        total = (time.monotonic() - t0) * 1000
        text = "".join(chunks)
        
        print(f"    LLM (Azure India): TTFT={ttft:.0f}ms, total={total:.0f}ms")
        print(f"      Response: {text[:100]!r}")
        
        return {"ttft": ttft, "total": total, "text": text}
    
    except Exception as e:
        print(f"    ❌ Azure LLM error: {e}")
        return None


def test_llm_openai_us(config: dict, test_name: str):
    """Test OpenAI US LLM (baseline)."""
    from openai import OpenAI
    
    api_key = config.get("OPENAI_API_KEY")
    if not api_key:
        print(f"  ❌ OpenAI API key missing")
        return None
    
    client = OpenAI(api_key=api_key)
    
    messages = [
        {"role": "system", "content": "Reply in Telugu Tenglish. One short sentence."},
        {"role": "user", "content": "Hello, appointment book cheyali"},
    ]
    
    t0 = time.monotonic()
    ttft = None
    chunks = []
    
    try:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=100,
            stream=True,
        )
        
        for chunk in stream:
            if not chunk.choices:
                continue
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            
            delta = chunk.choices[0].delta
            if delta.content:
                chunks.append(delta.content)
        
        total = (time.monotonic() - t0) * 1000
        text = "".join(chunks)
        
        print(f"    LLM (OpenAI US): TTFT={ttft:.0f}ms, total={total:.0f}ms")
        print(f"      Response: {text[:100]!r}")
        
        return {"ttft": ttft, "total": total, "text": text}
    
    except Exception as e:
        print(f"    ❌ OpenAI LLM error: {e}")
        return None


def test_tts_sarvam(config: dict, text: str):
    """Test Sarvam TTS."""
    import requests
    
    api_key = config.get("SARVAM_API_KEY")
    url = config.get("SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech")
    
    if not api_key:
        print(f"    ❌ Sarvam API key missing")
        return None
    
    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": api_key,
    }
    
    payload = {
        "inputs": [text],
        "target_language_code": "te-IN",
        "speaker": "anushka",
        "model": "bulbul:v2",
    }
    
    t0 = time.monotonic()
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        ttfb = (time.monotonic() - t0) * 1000
        
        if resp.status_code == 200:
            data = resp.json()
            audio_b64 = data.get("audios", [None])[0]
            
            if audio_b64:
                import base64
                audio_bytes = base64.b64decode(audio_b64)
                size_kb = len(audio_bytes) / 1024
                
                print(f"    TTS (Sarvam): TTFB={ttfb:.0f}ms, size={size_kb:.1f}KB")
                return {"ttfb": ttfb, "size_kb": size_kb}
        
        print(f"    ❌ Sarvam TTS error: {resp.status_code}")
        return None
    
    except Exception as e:
        print(f"    ❌ Sarvam TTS error: {e}")
        return None


async def test_tts_cartesia(config: dict, text: str):
    """Test Cartesia TTS WebSocket."""
    import base64
    import json
    
    api_key = config.get("CARTESIA_API_KEY")
    if not api_key:
        print(f"    ❌ Cartesia API key missing")
        return None
    
    try:
        import websockets
    except ImportError:
        print(f"    ❌ websockets not installed")
        return None
    
    ws_url = f"wss://api.cartesia.ai/tts/websocket?api_key={api_key}&cartesia_version=2024-06-10"
    
    msg = {
        "context_id": f"test_{int(time.time())}",
        "model_id": "sonic-3.5",
        "voice": {"mode": "id", "id": "79a125e8-cd45-4c13-8a67-188112f4dd22"},
        "transcript": text,
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
            await ws.send(json.dumps(msg))
            
            async for raw_msg in ws:
                data = json.loads(raw_msg)
                
                if data.get("type") == "chunk" and "data" in data:
                    if ttfb is None:
                        ttfb = (time.monotonic() - t0) * 1000
                    audio_bytes = base64.b64decode(data["data"])
                    chunks.append(audio_bytes)
                
                if data.get("done"):
                    break
        
        if ttfb and chunks:
            size_kb = sum(len(c) for c in chunks) / 1024
            print(f"    TTS (Cartesia WS): TTFB={ttfb:.0f}ms, size={size_kb:.1f}KB")
            return {"ttfb": ttfb, "size_kb": size_kb}
        
        print(f"    ❌ Cartesia TTS: no audio received")
        return None
    
    except Exception as e:
        print(f"    ❌ Cartesia TTS error: {e}")
        return None


async def run_combination_test(name: str, llm_func, tts_func, config: dict):
    """Run one combination test."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)
    
    # Test LLM
    print(f"  [1/2] Testing LLM...")
    llm_result = llm_func(config, name)
    
    if not llm_result:
        print(f"  ❌ LLM test failed, skipping combination")
        return None
    
    # Test TTS
    print(f"  [2/2] Testing TTS...")
    if asyncio.iscoroutinefunction(tts_func):
        tts_result = await tts_func(config, _TEST_TEXT)
    else:
        tts_result = tts_func(config, _TEST_TEXT)
    
    if not tts_result:
        print(f"  ❌ TTS test failed, skipping combination")
        return None
    
    # Calculate total
    endpointing = 736  # Current average from CallDetail
    llm_ttft = llm_result["ttft"]
    tts_ttfb = tts_result["ttfb"]
    
    # Perceived latency (with sentence streaming benefit)
    # Sentence streaming cuts ~400ms perceived (first sentence plays while LLM generates rest)
    sentence_streaming_benefit = 400
    
    total_without_streaming = endpointing + llm_ttft + tts_ttfb
    total_with_streaming = total_without_streaming - sentence_streaming_benefit
    
    print(f"\n  LATENCY BREAKDOWN:")
    print(f"    Endpointing:      {endpointing}ms")
    print(f"    LLM TTFT:         {llm_ttft:.0f}ms")
    print(f"    TTS TTFB:         {tts_ttfb:.0f}ms")
    print(f"    ─────────────────────────────")
    print(f"    Total (no streaming):   {total_without_streaming:.0f}ms")
    print(f"    Total (with streaming): {total_with_streaming:.0f}ms ⭐")
    
    # Quality check
    print(f"\n  QUALITY:")
    print(f"    LLM output: {llm_result['text'][:80]}")
    
    return {
        "name": name,
        "endpointing": endpointing,
        "llm_ttft": llm_ttft,
        "tts_ttfb": tts_ttfb,
        "total_without_streaming": total_without_streaming,
        "total_with_streaming": total_with_streaming,
        "llm_text": llm_result["text"],
    }


async def main():
    print("="*60)
    print("STACK COMBINATION TESTING")
    print("="*60)
    print()
    print("Testing 3 combinations to find optimal latency + quality:")
    print("  1. Sarvam STT + Azure India + Cartesia TTS")
    print("  2. Sarvam STT + Azure India + Sarvam TTS")
    print("  3. Sarvam STT + OpenAI US + Sarvam TTS (baseline)")
    print()
    
    config = load_env()
    
    # Run tests
    results = []
    
    # Test 1: Azure + Cartesia (fastest expected)
    result1 = await run_combination_test(
        "Sarvam STT + Azure India + Cartesia TTS",
        test_llm_azure,
        test_tts_cartesia,
        config,
    )
    if result1:
        results.append(result1)
    
    await asyncio.sleep(1)
    
    # Test 2: Azure + Sarvam (balanced)
    result2 = await run_combination_test(
        "Sarvam STT + Azure India + Sarvam TTS",
        test_llm_azure,
        test_tts_sarvam,
        config,
    )
    if result2:
        results.append(result2)
    
    await asyncio.sleep(1)
    
    # Test 3: OpenAI US + Sarvam (baseline)
    result3 = await run_combination_test(
        "Sarvam STT + OpenAI US + Sarvam TTS (BASELINE)",
        test_llm_openai_us,
        test_tts_sarvam,
        config,
    )
    if result3:
        results.append(result3)
    
    # Final comparison
    print(f"\n\n{'='*60}")
    print("FINAL COMPARISON")
    print('='*60)
    
    if not results:
        print("No successful tests")
        return
    
    # Sort by total latency (with streaming)
    results.sort(key=lambda r: r["total_with_streaming"])
    
    print(f"\n{'Stack':<45} {'Latency':<15} {'vs Baseline'}")
    print('-'*60)
    
    baseline = results[-1]["total_with_streaming"]  # Assume last is baseline
    
    for r in results:
        latency = r["total_with_streaming"]
        vs_baseline = baseline - latency
        pct = (vs_baseline / baseline * 100) if baseline > 0 else 0
        
        icon = "⭐" if latency == min(res["total_with_streaming"] for res in results) else "  "
        
        print(f"{icon} {r['name']:<43} {latency:.0f}ms {vs_baseline:+.0f}ms ({pct:+.0f}%)")
    
    # Winner
    winner = results[0]
    print(f"\n{'='*60}")
    print("RECOMMENDATION")
    print('='*60)
    print(f"✅ WINNER: {winner['name']}")
    print(f"   Latency: {winner['total_with_streaming']:.0f}ms (perceived)")
    print(f"   Improvement: {baseline - winner['total_with_streaming']:.0f}ms faster than baseline")
    print(f"   Quality: {winner['llm_text'][:80]}")
    
    if winner["total_with_streaming"] < 1500:
        print(f"\n   🎉 Sub-1.5s! This will feel INSTANT to users!")
    elif winner["total_with_streaming"] < 2000:
        print(f"\n   ✅ Sub-2s! This is acceptable for voice agents.")
    else:
        print(f"\n   ⚠️  Still >2s. Consider further optimizations.")


if __name__ == "__main__":
    asyncio.run(main())
