"""Azure OpenAI India latency benchmark - multiple runs for accurate TTFT."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def benchmark_azure_latency(num_runs=5):
    """Run multiple Azure API calls to get accurate TTFT statistics."""
    print("="*60)
    print("Azure OpenAI India Latency Benchmark")
    print("="*60)
    
    try:
        from src.pipeline.llm import _build_azure_client
        
        client = _build_azure_client()
        
        if not client:
            print("❌ Azure client not available (check credentials)")
            return
        
        print(f"\n✅ Azure client built: {client.base_url}")
        print(f"\nRunning {num_runs} test calls to measure TTFT...\n")
        
        ttfts = []
        
        test_prompts = [
            "చెప్పండి అండి, appointment ఎప్పుడు పెట్టుకోవాలి?",
            "Hello, I need to schedule an appointment.",
            "मुझे appointment लेना है",
            "What time slots are available tomorrow?",
            "రేపు morning slots available ఉన్నాయా?",
        ]
        
        for i in range(num_runs):
            prompt = test_prompts[i % len(test_prompts)]
            
            try:
                start = time.time()
                
                response = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=50,
                    temperature=0.4,
                    stream=False
                )
                
                ttft = (time.time() - start) * 1000
                ttfts.append(ttft)
                
                reply = response.choices[0].message.content[:80] if response.choices else ""
                
                print(f"Run {i+1}/{num_runs}: TTFT = {ttft:6.0f}ms | Reply: {reply}...")
            
            except Exception as e:
                print(f"Run {i+1}/{num_runs}: ❌ Error: {e}")
        
        # Statistics
        if ttfts:
            avg_ttft = sum(ttfts) / len(ttfts)
            min_ttft = min(ttfts)
            max_ttft = max(ttfts)
            
            print("\n" + "="*60)
            print("RESULTS")
            print("="*60)
            print(f"Average TTFT: {avg_ttft:.0f}ms")
            print(f"Min TTFT:     {min_ttft:.0f}ms")
            print(f"Max TTFT:     {max_ttft:.0f}ms")
            print(f"Std Dev:      {(sum((x - avg_ttft)**2 for x in ttfts) / len(ttfts))**0.5:.0f}ms")
            
            print("\n" + "="*60)
            print("COMPARISON")
            print("="*60)
            print(f"Baseline (OpenAI US):  3257ms")
            print(f"Azure India (actual):  {avg_ttft:.0f}ms")
            print(f"Improvement:           {(1 - avg_ttft/3257)*100:.0f}% faster")
            
            if avg_ttft < 1500:
                print("\n✅ Azure India is SIGNIFICANTLY faster than US!")
            elif avg_ttft < 2500:
                print("\n✅ Azure India is faster, but not as much as expected")
                print("   (Network conditions or region routing may vary)")
            else:
                print("\n⚠️  Azure India TTFT higher than expected")
                print("   Possible causes:")
                print("   - Network congestion")
                print("   - Cold start (first call penalty)")
                print("   - Region routing issue")
        
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(benchmark_azure_latency(5))
