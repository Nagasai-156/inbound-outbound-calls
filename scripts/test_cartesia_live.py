"""Test Cartesia TTS integration in isolation before wiring into agent.

Simulates the agent pipeline: text → Cartesia WebSocket → audio playback.
If this works, we can wire it into src/agent.py via TTS_MODEL env variable.
"""

from __future__ import annotations

import asyncio
import os

# Test phrases (Telugu Tenglish like real agent output)
_PHRASES = [
    "హలో! జన్నారా క్లినిక్ నుంచి మాట్లాడుతున్నాను.",
    "రేపు morning పదిన్నరకి మీ appointment ఉంది అండి. రాగలుగుతారా?",
    "సరే అండి, మీ appointment confirm అయింది.",
]


async def main():
    # Import Cartesia TTS
    try:
        from src.pipeline.tts_cartesia import build_cartesia_tts
    except ImportError as e:
        print(f"ERROR importing Cartesia TTS: {e}")
        print("Make sure tts_cartesia.py is in src/pipeline/")
        return
    
    # Load API key
    try:
        from src.config import settings
        if not settings.cartesia_api_key:
            print("ERROR: CARTESIA_API_KEY not set in .env")
            return
        print(f"✅ API key loaded: {settings.cartesia_api_key[:20]}...")
    except Exception as e:
        print(f"ERROR loading config: {e}")
        return
    
    print("="*60)
    print("Cartesia TTS Live Test")
    print("="*60)
    print()
    
    # Test each voice
    voices = ["british_lady", "barbershop_man"]
    
    for voice in voices:
        print(f"\n{'='*60}")
        print(f"Testing voice: {voice}")
        print('='*60)
        
        # Build TTS
        try:
            tts = build_cartesia_tts(voice=voice, language="te")
            print(f"✅ TTS instance created")
        except Exception as e:
            print(f"❌ Failed to create TTS: {e}")
            continue
        
        # Test synthesis
        for i, text in enumerate(_PHRASES[:2]):  # Test first 2 phrases
            print(f"\n[{i+1}] Synthesizing: {text[:50]}...")
            
            try:
                # Get stream
                stream = tts.synthesize(text)
                
                frame_count = 0
                total_samples = 0
                
                # Collect frames
                async for event in stream:
                    if hasattr(event, 'frame'):
                        frame_count += 1
                        total_samples += event.frame.samples_per_channel
                
                duration_sec = total_samples / 24000  # 24kHz sample rate
                
                print(f"   ✅ Synthesized: {frame_count} frames, {duration_sec:.1f}s audio")
            
            except Exception as e:
                print(f"   ❌ Synthesis failed: {e}")
                import traceback
                traceback.print_exc()
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)
    print()
    print("If all tests passed:")
    print("1. Cartesia WebSocket TTS is working")
    print("2. Ready to wire into live agent")
    print()
    print("Next step: Update agent to use Cartesia")
    print("  1. Add TTS_PROVIDER=cartesia to .env")
    print("  2. Modify src/pipeline/tts.py to route to Cartesia")
    print("  3. Test on live call")


if __name__ == "__main__":
    asyncio.run(main())
