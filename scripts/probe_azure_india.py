"""Probe Azure OpenAI India (Central India region) for latency.

Same gpt-4o model, but hosted in Mumbai → should be much faster than
US OpenAI (3257ms avg → target ~500-800ms).

Tests Telugu + tool calling to ensure quality unchanged.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Same test scenarios
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
        "user": "మా clinic ఎక్కడ ఉందండి? consultation fee ఎంత?",
        "tools": False,
    },
]

_SYS = """You are a warm Telugu call-center agent for Jannara Clinic.
Reply in Tenglish: Telugu script (తెలుగు లిపి) for connectors/pronouns,
English words for business terms (appointment, confirm, consultation).
NEVER pure English or Roman Telugu. One short sentence only."""

_TOOL = {
    "type": "function",
    "function": {
        "name": "check_appointment_slots",
        "description": "Return free/booked slots for a date",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date YYYY-MM-DD"}
            },
            "required": ["date"],
        },
    },
}


def _probe(endpoint: str, api_key: str, deployment: str, scenario: dict):
    """Single probe: measure TTFT."""
    from openai import OpenAI
    
    client = OpenAI(
        base_url=endpoint,
        api_key=api_key,
    )
    
    messages = [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": scenario["user"]},
    ]
    
    tools = [_TOOL] if scenario["tools"] else None
    
    t0 = time.monotonic()
    ttft = None
    chunks = []
    tool_used = None
    
    try:
        stream = client.chat.completions.create(
            model=deployment,
            messages=messages,
            tools=tools,
            temperature=0.3,
            max_tokens=200,
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
            if delta.tool_calls:
                tool_used = delta.tool_calls[0].function.name
        
        total = (time.monotonic() - t0) * 1000
        text = "".join(chunks)
        
        print(f"\n[{scenario['label']}]")
        print(f"  TTFT={ttft:.0f}ms  total={total:.0f}ms  tool={tool_used}")
        print(f"  text={text[:180]!r}")
        
        return ttft, total, text
    
    except Exception as e:
        print(f"\n[{scenario['label']}] ERROR: {type(e).__name__}: {str(e)[:300]}")
        import traceback
        traceback.print_exc()
        return None, None, None


def main():
    # Load from .env
    env_file = Path(__file__).parent.parent / ".env"
    endpoint = None
    api_key = None
    deployment = None
    
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("AZURE_OPENAI_ENDPOINT="):
                endpoint = line.split("=", 1)[1].strip()
            elif line.startswith("AZURE_OPENAI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
            elif line.startswith("AZURE_OPENAI_DEPLOYMENT="):
                deployment = line.split("=", 1)[1].strip()
    
    if not all([endpoint, api_key, deployment]):
        print("ERROR: Azure OpenAI config not found in .env")
        print("Need: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT")
        return
    
    print("="*60)
    print(f"Azure OpenAI India Probe — {deployment}")
    print("="*60)
    print(f"Endpoint: {endpoint}")
    print()
    
    results = []
    
    for scenario in _SCENARIOS:
        ttft, total, text = _probe(endpoint, api_key, deployment, scenario)
        if ttft:
            results.append((scenario["label"], ttft, total, text))
        time.sleep(0.3)
    
    # Summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    
    if results:
        ttfts = [t for _, t, _, _ in results]
        avg_ttft = sum(ttfts) / len(ttfts)
        
        print(f"\nAzure OpenAI India (Central India):")
        print(f"  Average TTFT: {avg_ttft:.0f}ms")
        print(f"  Range: {min(ttfts):.0f}-{max(ttfts):.0f}ms")
        
        print(f"\nComparison:")
        print(f"  OpenAI US: 3257ms avg (11917ms spikes!)")
        print(f"  Azure India: {avg_ttft:.0f}ms avg")
        print(f"  Latency reduction: {3257 - avg_ttft:.0f}ms ({(1 - avg_ttft/3257)*100:.0f}% faster)")
        
        print(f"\n{'='*60}")
        print("QUALITY CHECK:")
        print("="*60)
        for label, _, _, text in results:
            print(f"  {label}: {text[:80]}")
        
        print(f"\n{'='*60}")
        if avg_ttft < 1000:
            print("✅ SUCCESS! Azure India < 1s → USE THIS!")
            print("\nNext: Wire into src/pipeline/llm.py")
            print("  1. Detect 'azure/' prefix in model name")
            print("  2. Use Azure endpoint + deployment")
            print("  3. Set DEFAULT_LLM_MODEL=azure/gpt-4o")
        else:
            print("⚠️ Still slow. Check:")
            print("  1. Region = Central India (Mumbai)?")
            print("  2. Network latency from your location?")
    else:
        print("No successful tests")


if __name__ == "__main__":
    main()
