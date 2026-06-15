"""Test Cerebras models for speed and Telugu quality."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_cerebras_model(model_name: str):
    """Test a specific Cerebras model."""
    print(f"\n{'='*60}")
    print(f"Testing: {model_name}")
    print(f"{'='*60}")
    
    try:
        from openai import AsyncOpenAI
        from src.config import settings
        
        cerebras_key = settings.cerebras_api_key
        if not cerebras_key:
            print("❌ CEREBRAS_API_KEY not found in .env")
            return None
        
        client = AsyncOpenAI(
            api_key=cerebras_key,
            base_url="https://api.cerebras.ai/v1"
        )
        
        # Telugu test prompt
        test_prompts = [
            "చెప్పండి అండి, రేపు morning appointment available ఉందా?",
            "Hello, I need to book an appointment for tomorrow.",
            "मुझे कल appointment चाहिए।"
        ]
        
        results = []
        
        for i, prompt in enumerate(test_prompts, 1):
            print(f"\nTest {i}/3: ", end="")
            
            try:
                start = time.time()
                
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant for a clinic."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=100,
                    temperature=0.4,
                )
                
                ttft = (time.time() - start) * 1000
                reply = response.choices[0].message.content if response.choices else ""
                
                print(f"✅ TTFT: {ttft:.0f}ms")
                print(f"   Reply: {reply[:100]}...")
                
                results.append({
                    "prompt": prompt[:50],
                    "ttft": ttft,
                    "reply": reply[:100]
                })
            
            except Exception as e:
                print(f"❌ Error: {e}")
                return None
        
        # Calculate average
        if results:
            avg_ttft = sum(r["ttft"] for r in results) / len(results)
            print(f"\n{'='*60}")
            print(f"SUMMARY: {model_name}")
            print(f"{'='*60}")
            print(f"Average TTFT: {avg_ttft:.0f}ms")
            print(f"Tests passed: {len(results)}/3")
            
            return {
                "model": model_name,
                "avg_ttft": avg_ttft,
                "results": results
            }
        
        return None
    
    except Exception as e:
        print(f"❌ Setup error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Test all Cerebras models."""
    print("="*60)
    print("CEREBRAS MODELS TEST")
    print("="*60)
    
    models_to_test = [
        "llama3.1-8b",           # Fastest
        "llama-3.3-70b",         # Best balance (if available)
        "llama3.1-70b",          # Alternative
    ]
    
    results = {}
    
    for model in models_to_test:
        result = await test_cerebras_model(model)
        if result:
            results[model] = result
        await asyncio.sleep(2)  # Rate limit courtesy
    
    # Final comparison
    print("\n" + "="*60)
    print("FINAL COMPARISON")
    print("="*60)
    
    if results:
        print(f"\n{'Model':<25} {'Avg TTFT':<15} {'Status'}")
        print("-"*60)
        
        for model, data in sorted(results.items(), key=lambda x: x[1]["avg_ttft"]):
            ttft = data["avg_ttft"]
            status = "✅ FAST" if ttft < 500 else "⚠️  SLOW"
            print(f"{model:<25} {ttft:>6.0f}ms        {status}")
        
        # Recommendation
        fastest = min(results.items(), key=lambda x: x[1]["avg_ttft"])
        print(f"\n{'='*60}")
        print(f"RECOMMENDED: {fastest[0]}")
        print(f"Expected TTFT: {fastest[1]['avg_ttft']:.0f}ms")
        print(f"{'='*60}")
        
        print(f"\nTo use this model, update .env:")
        print(f"DEFAULT_LLM_MODEL={fastest[0]}")
    else:
        print("\n❌ No models worked. Check:")
        print("1. CEREBRAS_API_KEY in .env")
        print("2. Internet connection")
        print("3. Cerebras API status")


if __name__ == "__main__":
    asyncio.run(main())
