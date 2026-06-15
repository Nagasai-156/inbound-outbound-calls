"""Probe AWS Bedrock (US us-east-1 / India ap-south-1) for voice:
TTFT, tool-calling, Tenglish quality. Tests Claude 3.5 Haiku + Nova Lite/Micro.
Uses Bedrock API keys (bearer tokens) for fast auth — no IAM setup needed.

Setup:
  1. AWS console -> Bedrock -> API keys -> Generate long-term key (30d)
  2. Enable model access: Claude 3.5 Haiku, Nova Lite, Nova Micro
  3. Add to .env:
       AWS_BEARER_TOKEN_BEDROCK=ABSK...
       AWS_REGION=us-east-1  (or ap-south-1 for India latency)
  4. pip install requests   (if not present)
  5. python -m scripts.probe_bedrock

For production India latency: switch region to ap-south-1 + use apac.* profiles.
Read-only probe. Changes no config.
"""

from __future__ import annotations

import json
import os
import time

# Bedrock model inference profiles.
# YOUR REGION = us-east-1 → use us.* profiles
# For India latency → switch to apac.* + AWS_REGION=ap-south-1
_MODELS = [
    ("us.anthropic.claude-3-5-haiku-20241022-v1:0", "Claude 3.5 Haiku"),
    ("us.amazon.nova-lite-v1:0", "Amazon Nova Lite"),
    ("us.amazon.nova-micro-v1:0", "Amazon Nova Micro"),
    # Mistral models — testing per user request
    ("us.mistral.mistral-large-2407-v1:0", "Mistral Large 2"),
    ("us.mistral.mistral-small-2402-v1:0", "Mistral Small"),
]

_REGION = os.environ.get("AWS_REGION", "us-east-1")

_TOOL = {
    "toolSpec": {
        "name": "check_appointment_slots",
        "description": "Return free/booked slots for a date.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            }
        },
    }
}

_SYS = (
    "You are a warm Telugu call-center agent. Reply in Tenglish: Telugu in "
    "NATIVE Telugu script (తెలుగు లిపి) for connectors, English words for "
    "business terms (appointment, confirm). NEVER Roman Telugu. When the "
    "caller asks to book/check availability for a day, call "
    "check_appointment_slots. One short sentence."
)


def _probe_non_stream(bearer_token, region, model_id, label, text, with_tool):
    """Non-streaming probe to test quality + get parseable response."""
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
    
    body = {
        "messages": [{"role": "user", "content": [{"text": text}]}],
        "system": [{"text": _SYS}],
        "inferenceConfig": {"maxTokens": 200, "temperature": 0.3},
    }
    if with_tool:
        body["toolConfig"] = {"tools": [_TOOL]}
    
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    
    t0 = time.monotonic()
    
    try:
        import requests
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        
        if resp.status_code == 403:
            print(f"\n[{label} | {label2(with_tool)}] ERROR 403: Model access denied")
            print(f"  → Enable model in Bedrock console ({region})")
            return
        
        resp.raise_for_status()
        total = (time.monotonic() - t0) * 1000
        
        result = resp.json()
        out_text = ""
        tool_used = None
        
        # Parse Converse API response
        if "output" in result and "message" in result["output"]:
            for content_block in result["output"]["message"].get("content", []):
                if "text" in content_block:
                    out_text += content_block["text"]
                if "toolUse" in content_block:
                    tool_used = content_block["toolUse"].get("name")
        
        # Usage stats
        usage = result.get("usage", {})
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        
        print(f"\n[{label} | {label2(with_tool)}]")
        print(f"  TTFT=N/A (non-stream)  total={total:.0f}ms  tool={tool_used}")
        print(f"  tokens={in_tok}+{out_tok}  text={out_text[:180]!r}")
        
    except Exception as e:
        print(f"\n[{label} | {label2(with_tool)}] ERROR: {type(e).__name__}: {str(e)[:300]}")


def _probe(bearer_token, region, model_id, label, text, with_tool):
    """Streaming probe for TTFT measurement."""
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse-stream"
    
    body = {
        "messages": [{"role": "user", "content": [{"text": text}]}],
        "system": [{"text": _SYS}],
        "inferenceConfig": {"maxTokens": 200, "temperature": 0.3},
    }
    if with_tool:
        body["toolConfig"] = {"tools": [_TOOL]}
    
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.amazon.eventstream",
    }
    
    t0 = time.monotonic()
    ttft = None
    chunk_count = 0
    
    try:
        import requests
        resp = requests.post(url, headers=headers, json=body, stream=True, timeout=15)
        
        if resp.status_code == 403:
            print(f"\n[{label} | {label2(with_tool)} STREAM] ERROR 403: Model not enabled")
            return
        
        resp.raise_for_status()
        
        for chunk in resp.iter_content(chunk_size=1024):
            if chunk:
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                chunk_count += 1
        
        total = (time.monotonic() - t0) * 1000
        print(f"  [STREAM] TTFT={ttft:.0f}ms total={total:.0f}ms chunks={chunk_count}")
            
    except Exception as e:
        print(f"  [STREAM] ERROR: {type(e).__name__}")


def label2(with_tool):
    return "tool" if with_tool else "plain"


def main():
    try:
        import requests
    except ImportError:
        print("requests library not installed. Run: pip install requests")
        return
    
    # Load bearer token from .env
    bearer_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    region = os.environ.get("AWS_REGION", "us-east-1")
    
    if not bearer_token:
        try:
            from src.config import settings
            bearer_token = settings.aws_bearer_token_bedrock
            region = settings.aws_region
        except Exception:
            pass
    
    if not bearer_token:
        print("ERROR: AWS_BEARER_TOKEN_BEDROCK not set in .env")
        print("Generate one in AWS Console → Bedrock → API keys")
        print("Add to .env: AWS_BEARER_TOKEN_BEDROCK=ABSK...")
        return
    
    print(f"=== Bedrock probe · region={region} ===")
    print(f"Using API key: {bearer_token[:25]}...")
    print()
    
    for model_id, label in _MODELS:
        # Non-streaming for quality check (parseable JSON)
        _probe_non_stream(bearer_token, region, model_id, label,
                         "Hello, meeru clinic nunchi calling aa?", with_tool=False)
        _probe_non_stream(bearer_token, region, model_id, label,
                         "Repu morning appointment unda? check cheyandi.", with_tool=True)
        # Streaming for TTFT
        _probe(bearer_token, region, model_id, label,
               "Test TTFT", with_tool=False)
    
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("1. Compare TTFT with gpt-4o-mini (~900ms-11s spikes)")
    print("2. Check Telugu quality (Tenglish script, no Roman)")
    print("3. Verify tool-calling works (check_appointment_slots)")
    print("4. For India latency: switch AWS_REGION=ap-south-1 + apac.* models")
    print("5. If good → wire into src/pipeline/llm.py as bedrock/* prefix")


if __name__ == "__main__":
    main()
