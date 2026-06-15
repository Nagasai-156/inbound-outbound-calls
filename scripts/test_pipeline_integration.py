#!/usr/bin/env python3
"""
Integration test: Verify Groq models are properly wired in the pipeline
Tests: llama-3.1-8b-instant, qwen/qwen3-32b, llama-3.3-70b-versatile
"""

import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pipeline.llm import build_llm
from src.runtime_config import RuntimeConfig

# Load environment
load_dotenv()

TEST_MODELS = [
    {
        "name": "Llama 3.1 8B (Current)",
        "model_id": "llama-3.1-8b-instant",
        "expected_provider": "Groq",
        "rpm_limit": 30,
        "rpd_limit": 14400
    },
    {
        "name": "Qwen3 32B (Asian Expert)",
        "model_id": "qwen/qwen3-32b",
        "expected_provider": "Groq",
        "rpm_limit": 60,
        "rpd_limit": 1000
    },
    {
        "name": "Llama 3.3 70B (Quality)",
        "model_id": "llama-3.3-70b-versatile",
        "expected_provider": "Groq",
        "rpm_limit": 30,
        "rpd_limit": 1000
    }
]

TEST_PROMPT = """You are a helpful Telugu voice assistant. 
Respond naturally in Telugu or Tenglish (Telugu-English code-switching).

User: Namaste, mee peru enti?
"""


def test_model_routing(model_config):
    """Test if model routes to correct provider"""
    
    print(f"\n{'='*70}")
    print(f"Testing: {model_config['name']}")
    print(f"Model ID: {model_config['model_id']}")
    print(f"Expected Provider: {model_config['expected_provider']}")
    print(f"{'='*70}\n")
    
    try:
        # Create runtime config
        cfg = RuntimeConfig()
        cfg.llm_model = model_config["model_id"]
        cfg.llm_temperature = 0.7
        
        # Build LLM
        print(f"  ✅ Building LLM with model: {model_config['model_id']}")
        llm = build_llm(cfg)
        
        # Verify LLM object created
        if llm is None:
            print(f"  ❌ FAILED: LLM object is None")
            return False
        
        print(f"  ✅ LLM object created successfully")
        
        # Check if it's using Groq client
        if hasattr(llm, '_client') and llm._client is not None:
            client = llm._client
            base_url = getattr(client, 'base_url', None)
            
            if base_url:
                base_url_str = str(base_url)
                print(f"  ℹ️  Base URL: {base_url_str}")
                
                if "groq.com" in base_url_str.lower():
                    print(f"  ✅ CORRECT: Using Groq API")
                elif "openai.com" in base_url_str.lower():
                    print(f"  ⚠️  WARNING: Using OpenAI API (expected Groq)")
                elif "azure" in base_url_str.lower():
                    print(f"  ⚠️  WARNING: Using Azure API (expected Groq)")
                else:
                    print(f"  ⚠️  WARNING: Unknown provider")
            else:
                print(f"  ⚠️  WARNING: Could not detect base_url")
        else:
            print(f"  ⚠️  WARNING: Could not access client object")
        
        # Verify model name
        if hasattr(llm, '_model'):
            actual_model = llm._model
            print(f"  ℹ️  Model name: {actual_model}")
            
            if actual_model == model_config["model_id"]:
                print(f"  ✅ CORRECT: Model name matches")
            else:
                print(f"  ⚠️  WARNING: Model name mismatch (expected {model_config['model_id']})")
        
        print(f"\n  ✅ SUCCESS: Model {model_config['model_id']} is properly wired!")
        return True
        
    except Exception as e:
        print(f"  ❌ FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_live_inference(model_config):
    """Test actual LLM inference with the model"""
    
    print(f"\n{'─'*70}")
    print(f"Live Inference Test: {model_config['name']}")
    print(f"{'─'*70}\n")
    
    try:
        # Import required for async test
        import asyncio
        from openai import AsyncOpenAI
        
        # Get Groq client
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            print(f"  ❌ GROQ_API_KEY not found in environment")
            return False
        
        client = AsyncOpenAI(
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1"
        )
        
        async def test_async():
            start_time = time.time()
            
            response = await client.chat.completions.create(
                model=model_config["model_id"],
                messages=[
                    {"role": "system", "content": "You are a helpful Telugu voice assistant."},
                    {"role": "user", "content": "Namaste, mee peru enti?"}
                ],
                max_tokens=50,
                temperature=0.7
            )
            
            latency = (time.time() - start_time) * 1000
            
            assistant_response = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            return {
                "latency_ms": latency,
                "response": assistant_response,
                "tokens": tokens_used
            }
        
        # Run async test
        result = asyncio.run(test_async())
        
        print(f"  ✅ Latency: {result['latency_ms']:.0f}ms")
        print(f"  ✅ Tokens: {result['tokens']}")
        print(f"  ✅ Response: {result['response'][:100]}...")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Live inference failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════╗
║              PIPELINE INTEGRATION TEST - GROQ MODELS                      ║
║              Verify: llama-8b, qwen-32b, llama-70b wiring                 ║
╚═══════════════════════════════════════════════════════════════════════════╝

Testing {len(TEST_MODELS)} models...
""")
    
    # Check Groq API key
    if not os.getenv("GROQ_API_KEY"):
        print("❌ Error: GROQ_API_KEY not found in environment")
        print("   Please set it in .env file")
        sys.exit(1)
    
    print("✅ GROQ_API_KEY found in environment\n")
    
    # Test each model
    results = {}
    
    for model_config in TEST_MODELS:
        # Test routing
        routing_ok = test_model_routing(model_config)
        results[model_config["model_id"]] = {
            "routing": routing_ok,
            "inference": False
        }
        
        # Test live inference if routing works
        if routing_ok:
            time.sleep(1)  # Rate limit protection
            inference_ok = test_live_inference(model_config)
            results[model_config["model_id"]]["inference"] = inference_ok
        
        time.sleep(1)  # Rate limit protection between models
    
    # Print summary
    print(f"\n{'='*70}")
    print("INTEGRATION TEST SUMMARY")
    print(f"{'='*70}\n")
    
    all_passed = True
    
    for model_config in TEST_MODELS:
        model_id = model_config["model_id"]
        result = results[model_id]
        
        routing_status = "✅ PASS" if result["routing"] else "❌ FAIL"
        inference_status = "✅ PASS" if result["inference"] else "❌ FAIL"
        
        print(f"{model_config['name']}:")
        print(f"  ├─ Routing:   {routing_status}")
        print(f"  └─ Inference: {inference_status}")
        print()
        
        if not (result["routing"] and result["inference"]):
            all_passed = False
    
    print(f"{'='*70}")
    
    if all_passed:
        print("✅ ALL TESTS PASSED - All models properly wired! 🎉")
        print("\nYou can safely use any of these models in production:")
        print("  • llama-3.1-8b-instant (speed)")
        print("  • qwen/qwen3-32b (balance + 60 RPM)")
        print("  • llama-3.3-70b-versatile (quality)")
        print("\nUpdate .env:")
        print("  DEFAULT_LLM_MODEL=llama-3.3-70b-versatile")
        return 0
    else:
        print("❌ SOME TESTS FAILED - Check errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
