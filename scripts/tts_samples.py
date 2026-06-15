"""Generate Sarvam TTS samples across speakers/paces so we can pick the
MOST HUMAN voice. Writes .wav files to ./tts_samples/ — listen and tell
me which one sounds best, then I set it live.

    python -m scripts.tts_samples
"""

from __future__ import annotations

import asyncio
import base64
import os

import httpx

from src.config import settings

_URL = "https://api.sarvam.ai/text-to-speech"
_OUT = os.path.join(os.getcwd(), "tts_samples")

# A natural conversational Telugu/Tenglish line (what the agent actually says).
_TEXT = (
    "హలో అండి! నేను జన్నారా క్లినిక్ నుంచి మాట్లాడుతున్నాను. మీ appointment "
    "confirm చేయడానికి call చేశాను అండి, ఒక్క నిమిషం మాట్లాడొచ్చా?"
)

# Candidate voices to compare. (model, speaker, pace, label)
_CANDIDATES = [
    ("bulbul:v2", "anushka", 1.0, "v2_anushka_warm"),
    ("bulbul:v2", "manisha", 1.0, "v2_manisha"),
    ("bulbul:v2", "vidya", 1.0, "v2_vidya_calm"),
    ("bulbul:v2", "arya", 1.0, "v2_arya_bright"),
    ("bulbul:v3-beta", "ritu", 1.0, "v3_ritu_current"),
    ("bulbul:v3-beta", "pooja", 1.0, "v3_pooja"),
    ("bulbul:v3-beta", "kavya", 1.0, "v3_kavya"),
    ("bulbul:v3-beta", "neha", 1.0, "v3_neha_creator"),
    ("bulbul:v3-beta", "shreya", 1.0, "v3_shreya"),
    ("bulbul:v3-beta", "simran", 1.0, "v3_simran"),
    ("bulbul:v3-beta", "priya", 1.0, "v3_priya"),
    ("bulbul:v3-beta", "ritu", 1.1, "v3_ritu_pace1.1"),
    # pace variants of the warmest v2 voice
    ("bulbul:v2", "anushka", 1.1, "v2_anushka_pace1.1"),
    ("bulbul:v2", "anushka", 0.9, "v2_anushka_pace0.9"),
]


async def _one(client, model, speaker, pace, label):
    body = {
        "inputs": [_TEXT],
        "target_language_code": "te-IN",
        "speaker": speaker,
        "pace": pace,
        "speech_sample_rate": 22050,  # high quality so you judge the VOICE
        "enable_preprocessing": True,
        "model": model,
    }
    # Bulbul v3 rejects pitch/loudness; only v2 accepts them.
    if model == "bulbul:v2":
        body["pitch"] = 0
        body["loudness"] = 1.0
    try:
        r = await client.post(
            _URL, json=body,
            headers={"api-subscription-key": settings.sarvam_api_key},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  ✗ {label}: HTTP {r.status_code} {r.text[:120]}")
            return
        audios = r.json().get("audios", [])
        if not audios:
            print(f"  ✗ {label}: no audio")
            return
        path = os.path.join(_OUT, f"{label}.wav")
        with open(path, "wb") as f:
            f.write(base64.b64decode(audios[0]))
        print(f"  ✓ {label}.wav")
    except Exception as e:
        print(f"  ✗ {label}: {type(e).__name__} {str(e)[:120]}")


async def main():
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY not set.")
        return
    os.makedirs(_OUT, exist_ok=True)
    print(f"Writing samples to: {_OUT}\nText: {_TEXT}\n")
    async with httpx.AsyncClient() as client:
        for model, speaker, pace, label in _CANDIDATES:
            await _one(client, model, speaker, pace, label)
    print(f"\nDone. Open the folder and listen:\n  {_OUT}")


if __name__ == "__main__":
    asyncio.run(main())
