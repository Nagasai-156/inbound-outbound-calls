"""Check available Cerebras models."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def check_models():
    """List available models."""
    try:
        from openai import AsyncOpenAI
        from src.config import settings
        
        cerebras_key = settings.cerebras_api_key
        if not cerebras_key:
            print("❌ CEREBRAS_API_KEY not found in .env")
            return
        
        print(f"✅ API Key found: {cerebras_key[:20]}...")
        print("\nChecking Cerebras API...\n")
        
        client = AsyncOpenAI(
            api_key=cerebras_key,
            base_url="https://api.cerebras.ai/v1"
        )
        
        # Try to list models
        try:
            models = await client.models.list()
            print("Available models:")
            print("="*60)
            for model in models.data:
                print(f"- {model.id}")
            print("="*60)
        except Exception as e:
            print(f"Could not list models: {e}")
            print("\nTrying common model names...")
            
            # Try common names
            test_models = [
                "llama3.1-8b",
                "llama-3.1-8b",
                "meta-llama/Llama-3.1-8B",
                "llama3.1-70b", 
                "llama-3.1-70b",
                "llama-3.3-70b",
                "cerebras/llama3.1-8b",
            ]
            
            print("\nTesting model availability:")
            for model_name in test_models:
                try:
                    response = await client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": "test"}],
                        max_tokens=5
                    )
                    print(f"✅ {model_name} - WORKS!")
                    break
                except Exception as e:
                    error_msg = str(e)
                    if "model_not_found" in error_msg or "404" in error_msg:
                        print(f"❌ {model_name} - Not found")
                    else:
                        print(f"⚠️  {model_name} - Error: {error_msg[:50]}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_models())
