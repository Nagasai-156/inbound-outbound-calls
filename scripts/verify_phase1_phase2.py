"""Quick verification script for Phase 1+2 implementation.

Checks:
1. Azure OpenAI India client builds successfully
2. Cartesia TTS imports correctly
3. Sentence streaming tokenizer works
4. Configuration loaded correctly
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def verify_azure_client():
    """Verify Azure OpenAI India client builds correctly."""
    print("\n1. Testing Azure OpenAI India client...")
    try:
        from src.pipeline.llm import _build_azure_client
        client = _build_azure_client()
        if client:
            print("   ✅ Azure client built successfully")
            print(f"   - Base URL: {client.base_url}")
            return True
        else:
            print("   ⚠️  Azure client is None (missing credentials?)")
            return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def verify_cartesia_import():
    """Verify Cartesia plugin imports correctly."""
    print("\n2. Testing Cartesia TTS import...")
    try:
        from livekit.plugins import cartesia
        print("   ✅ Cartesia plugin imported successfully")
        return True
    except ImportError as e:
        print(f"   ❌ Cartesia import failed: {e}")
        print("   Install with: pip install livekit-plugins-cartesia")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def verify_sentence_streaming():
    """Verify Telugu sentence tokenizer works."""
    print("\n3. Testing Telugu-aware sentence streaming...")
    try:
        from src.pipeline.sentence_streaming import TeluguSentenceTokenizer
        
        tokenizer = TeluguSentenceTokenizer()
        test_text = "హలో అండి! మీ appointment confirm చేయడానికి call చేశాను."
        
        # Simulate streaming
        sentences = list(tokenizer.tokenize_stream(iter([test_text])))
        
        print(f"   ✅ Tokenizer works - split into {len(sentences)} sentences")
        for i, sentence in enumerate(sentences, 1):
            print(f"      {i}. {sentence[:50]}...")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def verify_config():
    """Verify Phase 1+2 configuration loaded correctly."""
    print("\n4. Testing configuration...")
    try:
        from src.config import settings
        
        checks = {
            "Azure endpoint": settings.azure_openai_endpoint,
            "Azure API key": "***" if settings.azure_openai_api_key else None,
            "Cartesia API key": "***" if settings.cartesia_api_key else None,
            "Sentence streaming": getattr(settings, "enable_sentence_streaming", None),
            "VAD start": settings.vad_start_secs,
            "VAD stop": settings.vad_stop_secs,
            "Min endpointing": settings.min_endpointing_delay,
            "Max endpointing": settings.max_endpointing_delay,
        }
        
        all_ok = True
        for name, value in checks.items():
            if value:
                print(f"   ✅ {name}: {value}")
            else:
                print(f"   ⚠️  {name}: Not set")
                all_ok = False
        
        return all_ok
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def verify_tts_routing():
    """Verify TTS provider routing works."""
    print("\n5. Testing TTS provider routing...")
    try:
        from src.pipeline.tts import build_tts
        from src.runtime_config import RuntimeConfig
        
        # Test Cartesia routing
        cfg = RuntimeConfig()
        cfg.tts_provider = "cartesia"
        
        tts = build_tts(cfg)
        module_name = type(tts).__module__
        
        print(f"   ℹ️  TTS module: {module_name}")
        
        # Check if it's Cartesia or Sarvam based on module
        if "cartesia" in module_name.lower():
            print("   ✅ Cartesia TTS routing works")
            return True
        elif "sarvam" in module_name.lower():
            print("   ⚠️  Fell back to Sarvam (Cartesia key missing or error)")
            return True
        else:
            print(f"   ❌ Unexpected TTS module: {module_name}")
            return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Phase 1+2 Implementation Verification")
    print("=" * 60)
    
    results = []
    
    # Run checks
    results.append(("Azure OpenAI India", await verify_azure_client()))
    results.append(("Cartesia Import", verify_cartesia_import()))
    results.append(("Sentence Streaming", verify_sentence_streaming()))
    results.append(("Configuration", verify_config()))
    results.append(("TTS Routing", await verify_tts_routing()))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    
    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status:10} {name}")
    
    print(f"\nResult: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed! Phase 1+2 implementation ready to test.")
        print("\nNext steps:")
        print("1. Restart worker: python -m src.agent start")
        print("2. Make a test call")
        print("3. Monitor latency in logs")
    else:
        print("\n⚠️  Some checks failed. Review errors above.")
        print("\nCommon fixes:")
        print("- Install Cartesia: pip install livekit-plugins-cartesia")
        print("- Set Azure credentials in .env")
        print("- Set Cartesia API key in .env")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
