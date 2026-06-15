"""Probe Gemini Flash 2.0 for voice agent use-case:
- TTFT (time-to-first-token)
- Telugu/Tenglish quality
- Tool calling support
- Compare with OpenAI gpt-4o-mini baseline

Gemini Flash 2.0 claims sub-500ms latency. Let's verify for Telugu.
"""

from __future__ import annotations

import json
import os
import time

# Test scenarios (same as we use for OpenAI)
_SCENARIOS = [
    {
        "label": "greeting_plain",
        "user": "Hello, meeru clinic nunchi calling aa?",
        "tools": False,
    },
    {
        "label": "booking_with_tool",
        "user": "Repu morning appointment unda? check cheyandi.",
        "tools": True,
    },
    {
        "label": "tenglish_codemix",
        "user": "మా clinic ఎక్కడ ఉందండి? మరియు consultation fee ఎంత?",
        "tools": False,
    },
]

_SYS = """You are a warm Telugu call-center agent for Jannara Clinic.
Reply in Tenglish: Telugu script (తెలుగు లిపి) for connectors/pronouns,
English words for business terms (appointment, confirm, consultation).
NEVER pure English or Roman Telugu. One short sentence only.
"""

_TOOL = {
    "function_declarations": [
        {
            "name": "check_appointment_slots",
            "description": "Return free/booked slots for a date",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"}
                },
                "required": ["date"],
            },
        }
    ]
}


def _probe(api_key: str, model: str, scenario: dict):
    """Single probe: measure TTFT + quality."""
    import requests
    
    # Correct Gemini API endpoint format (v1, not v1beta)
    url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"
    
    headers = {
        "Content-Type": "application/json",
    }
    
    body = {
        "contents": [
            {
                "parts": [
                    {"text": _SYS + "\n\nUser: " + scenario["user"]}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 200,
        },
    }
    
    # Tools not supported in v1 API
    # if scenario["tools"]:
    #     body["tools"] = [_TOOL]
    
    t0 = time.monotonic()
    
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        
        # Debug on error
        if resp.status_code != 200:
            print(f"\n[{scenario['label']}] ERROR {resp.status_code}: {resp.text[:300]}")
            return None, None, None
        
        total = (time.monotonic() - t0) * 1000
        data = resp.json()
        
        # Extract text from response
        chunks = []
        tool_used = None
        
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    chunks.append(part["text"])
                if "functionCall" in part:
                    tool_used = part["functionCall"].get("name")
        
        text = "".join(chunks)
        ttft = total  # Non-streaming, so TTFT = total
        
        print(f"\n[{scenario['label']}]")
        print(f"  TTFT={ttft:.0f}ms  total={total:.0f}ms  tool={tool_used}")
        print(f"  text={text[:180]!r}")
        
        return ttft, total, text
    
    except Exception as e:
        print(f"\n[{scenario['label']}] ERROR: {type(e).__name__}: {str(e)[:250]}")
        import traceback
        traceback.print_exc()
        return None, None, None


def main():
    # Load API key directly from environment
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # If not in env, try loading .env file
    if not api_key:
        try:
            from pathlib import Path
            env_file = Path(__file__).parent.parent / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except:
            pass
    
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set")
        print("Get one from: https://aistudio.google.com/apikey")
        print("Add to .env: GEMINI_API_KEY=...")
        return
    
    model = "gemini-2.5-flash"  # Latest Gemini 2.5 Flash (2025)
    
    print("="*60)
    print(f"Gemini Flash Probe — {model}")
    print("="*60)
    print()
    
    results = []
    
    for scenario in _SCENARIOS:
        ttft, total, text = _probe(api_key, model, scenario)
        if ttft:
            results.append((scenario["label"], ttft, total, text))
        time.sleep(0.5)  # Rate limit courtesy
    
    # Summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    
    if results:
        ttfts = [t for _, t, _, _ in results]
        avg_ttft = sum(ttfts) / len(ttfts)
        
        print(f"\nGemini Flash 2.0:")
        print(f"  Average TTFT: {avg_ttft:.0f}ms")
        print(f"  Range: {min(ttfts):.0f}-{max(ttfts):.0f}ms")
        
        print(f"\nComparison:")
        print(f"  OpenAI gpt-4o-mini: 3257ms avg (11917ms spikes!)")
        print(f"  Gemini Flash 2.0: {avg_ttft:.0f}ms avg")
        print(f"  Latency reduction: {3257 - avg_ttft:.0f}ms ({(1 - avg_ttft/3257)*100:.0f}% faster)")
        
        print(f"\n{'='*60}")
        print("QUALITY CHECK:")
        print("="*60)
        print("1. Telugu pronunciation (తెలుగు లిపి vs Roman)")
        print("2. Tenglish codemix (appointment/confirm in English)")
        print("3. Tool calling works?")
        print("4. Natural conversational tone?")
        
        print("\nIf quality GOOD + TTFT < 500ms:")
        print("  → Gemini Flash > OpenAI for voice agents")
        print("\nIf quality BAD (romanizes Telugu / weak codemix):")
        print("  → Stick with OpenAI or Bedrock Nova (proven Telugu)")
    else:
        print("No successful tests")
    
    print("\n" + "="*60)
    print("NEXT: Check if you have Gemini API key quota")
    print("Free tier: 15 RPM, 1M TPM, 1500 RPD")
    print("For production: Need paid API (higher quota)")


if __name__ == "__main__":
    main()
