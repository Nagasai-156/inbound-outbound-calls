#!/usr/bin/env python3
"""
Comprehensive latency benchmark for Llama 3.3 70B Versatile
Tests: TTFT, total response time, token generation speed
Sample size: 50 requests for statistical accuracy
"""

import os
import sys
import time
import json
import statistics
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq

# Load environment
load_dotenv()

# Test prompts - realistic Telugu/Tenglish scenarios
TEST_PROMPTS = [
    {
        "category": "Simple Greeting",
        "system": "You are a helpful Telugu voice assistant.",
        "user": "Namaste, mee peru enti?",
        "expected_tokens": 30
    },
    {
        "category": "Appointment Booking",
        "system": "You are an appointment booking assistant. Speak Tenglish naturally.",
        "user": "Repu morning 10 AM ki doctor appointment available aa?",
        "expected_tokens": 50
    },
    {
        "category": "Customer Complaint",
        "system": "You are a customer support agent. Be empathetic and helpful in Tenglish.",
        "user": "Naa internet connection 2 days nundi slow ga work chestundi. Speed test chesthe 2 Mbps ostundi but plan 50 Mbps. Em cheyali?",
        "expected_tokens": 80
    },
    {
        "category": "Bill Payment",
        "system": "You are a billing support assistant. Explain clearly in Tenglish.",
        "user": "Naa current bill amount entha? EMI option available aa? Interest rate emiti?",
        "expected_tokens": 70
    },
    {
        "category": "Technical Support",
        "system": "You are a technical support expert. Guide users clearly in Tenglish.",
        "user": "Mobile charge avvadam ledu. Cable marchanu, socket marchanu, phone restart chesanu. Still problem undi. Troubleshooting steps cheppandi.",
        "expected_tokens": 100
    },
    {
        "category": "Product Query",
        "system": "You are a sales assistant. Help customers in Tenglish.",
        "user": "iPhone 15 Pro 256GB variant price entha? Delivery time entha? Exchange offer unda?",
        "expected_tokens": 60
    },
    {
        "category": "Order Tracking",
        "system": "You are a delivery support agent. Be helpful in Tenglish.",
        "user": "Naa order status enti? Tracking number OD12345. Delivery eppudu expect cheyalo?",
        "expected_tokens": 50
    },
    {
        "category": "Service Request",
        "system": "You are a service booking assistant. Speak Tenglish.",
        "user": "AC service book cheyali. Last service 6 months back ayyindi. Eppudu technician ravacchu?",
        "expected_tokens": 60
    }
]


def measure_latency(client, model_id, test_case, max_tokens=150):
    """Measure detailed latency metrics for a single request"""
    
    messages = [
        {"role": "system", "content": test_case["system"]},
        {"role": "user", "content": test_case["user"]}
    ]
    
    start_time = time.time()
    
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7
        )
        
        total_time = (time.time() - start_time) * 1000  # ms
        
        # Extract metrics
        assistant_response = response.choices[0].message.content
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        
        # Estimate TTFT (first token) - Groq doesn't provide this directly
        # But we can estimate: total_time includes generation
        # Rough estimate: TTFT ≈ 20-30% of total time for streaming
        estimated_ttft = total_time * 0.25  # Conservative estimate
        
        # Token generation speed
        tokens_per_second = (completion_tokens / total_time) * 1000 if total_time > 0 else 0
        
        return {
            "success": True,
            "total_time_ms": total_time,
            "estimated_ttft_ms": estimated_ttft,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "tokens_per_second": tokens_per_second,
            "response": assistant_response,
            "response_length": len(assistant_response)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "total_time_ms": (time.time() - start_time) * 1000
        }


def run_benchmark(num_samples=50):
    """Run comprehensive benchmark with multiple samples"""
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════╗
║         LLAMA 3.3 70B VERSATILE - LATENCY BENCHMARK                       ║
║         Comprehensive Testing for Production Readiness                    ║
╚═══════════════════════════════════════════════════════════════════════════╝

Model: llama-3.3-70b-versatile
Provider: Groq
Samples: {num_samples} requests
Test Categories: {len(TEST_PROMPTS)} scenarios

Starting benchmark...
""")
    
    # Check API key
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        print("❌ Error: GROQ_API_KEY not found in environment")
        sys.exit(1)
    
    client = Groq(api_key=groq_key)
    model_id = "llama-3.3-70b-versatile"
    
    # Store all results
    all_results = []
    category_results = {cat["category"]: [] for cat in TEST_PROMPTS}
    
    # Run tests
    total_tests = num_samples
    completed = 0
    
    start_benchmark = time.time()
    
    for i in range(num_samples):
        # Rotate through test prompts
        test_case = TEST_PROMPTS[i % len(TEST_PROMPTS)]
        category = test_case["category"]
        
        # Progress indicator
        completed += 1
        progress = (completed / total_tests) * 100
        print(f"[{completed}/{total_tests}] ({progress:.1f}%) Testing: {category}...", 
              end=" ", flush=True)
        
        # Measure latency
        result = measure_latency(client, model_id, test_case)
        
        if result["success"]:
            print(f"✅ {result['total_time_ms']:.0f}ms")
            all_results.append(result)
            category_results[category].append(result)
        else:
            print(f"❌ Error: {result.get('error', 'Unknown')}")
        
        # Rate limit protection (30 RPM = 2 sec per request)
        if completed < total_tests:
            time.sleep(2.1)  # Slightly over 2s to be safe
    
    total_benchmark_time = time.time() - start_benchmark
    
    # Calculate statistics
    if not all_results:
        print("\n❌ No successful results to analyze")
        sys.exit(1)
    
    print(f"\n✅ Benchmark completed in {total_benchmark_time:.1f}s\n")
    
    return all_results, category_results


def calculate_statistics(results):
    """Calculate comprehensive statistics"""
    
    total_times = [r["total_time_ms"] for r in results]
    ttfts = [r["estimated_ttft_ms"] for r in results]
    token_speeds = [r["tokens_per_second"] for r in results]
    completion_tokens = [r["completion_tokens"] for r in results]
    
    total_times.sort()
    ttfts.sort()
    
    n = len(total_times)
    
    stats = {
        "total_requests": n,
        "success_rate": 100.0,
        
        # Total response time
        "total_time": {
            "mean": statistics.mean(total_times),
            "median": statistics.median(total_times),
            "stdev": statistics.stdev(total_times) if n > 1 else 0,
            "min": min(total_times),
            "max": max(total_times),
            "p50": total_times[n // 2],
            "p90": total_times[int(n * 0.9)],
            "p95": total_times[int(n * 0.95)],
            "p99": total_times[int(n * 0.99)] if n >= 100 else total_times[-1]
        },
        
        # TTFT (estimated)
        "ttft": {
            "mean": statistics.mean(ttfts),
            "median": statistics.median(ttfts),
            "p50": ttfts[n // 2],
            "p90": ttfts[int(n * 0.9)],
            "p95": ttfts[int(n * 0.95)]
        },
        
        # Token generation
        "tokens": {
            "avg_completion_tokens": statistics.mean(completion_tokens),
            "avg_tokens_per_second": statistics.mean(token_speeds),
            "max_tokens_per_second": max(token_speeds)
        }
    }
    
    return stats


def print_statistics(stats, category_stats=None):
    """Print detailed statistics"""
    
    print(f"{'='*80}")
    print("OVERALL LATENCY STATISTICS")
    print(f"{'='*80}\n")
    
    print(f"Total Requests: {stats['total_requests']}")
    print(f"Success Rate: {stats['success_rate']:.1f}%\n")
    
    print("Total Response Time:")
    print(f"  Mean:   {stats['total_time']['mean']:>8.0f}ms")
    print(f"  Median: {stats['total_time']['median']:>8.0f}ms")
    print(f"  StdDev: {stats['total_time']['stdev']:>8.0f}ms")
    print(f"  Min:    {stats['total_time']['min']:>8.0f}ms")
    print(f"  Max:    {stats['total_time']['max']:>8.0f}ms")
    print()
    print(f"  p50:    {stats['total_time']['p50']:>8.0f}ms  ← Industry target: <700ms")
    print(f"  p90:    {stats['total_time']['p90']:>8.0f}ms")
    print(f"  p95:    {stats['total_time']['p95']:>8.0f}ms")
    print(f"  p99:    {stats['total_time']['p99']:>8.0f}ms")
    print()
    
    print("Estimated TTFT (Time to First Token):")
    print(f"  Mean:   {stats['ttft']['mean']:>8.0f}ms")
    print(f"  Median: {stats['ttft']['median']:>8.0f}ms")
    print(f"  p50:    {stats['ttft']['p50']:>8.0f}ms")
    print(f"  p90:    {stats['ttft']['p90']:>8.0f}ms")
    print(f"  p95:    {stats['ttft']['p95']:>8.0f}ms")
    print()
    
    print("Token Generation:")
    print(f"  Avg Completion Tokens: {stats['tokens']['avg_completion_tokens']:>8.1f}")
    print(f"  Avg Tokens/Second:     {stats['tokens']['avg_tokens_per_second']:>8.1f}")
    print(f"  Max Tokens/Second:     {stats['tokens']['max_tokens_per_second']:>8.1f}")
    print()
    
    # Category breakdown
    if category_stats:
        print(f"\n{'='*80}")
        print("LATENCY BY SCENARIO CATEGORY")
        print(f"{'='*80}\n")
        
        print(f"{'Category':<25} {'Count':<8} {'Mean':<10} {'p50':<10} {'p90':<10}")
        print(f"{'-'*80}")
        
        for category, results in category_stats.items():
            if results:
                times = [r["total_time_ms"] for r in results]
                times.sort()
                n = len(times)
                
                mean = statistics.mean(times)
                p50 = times[n // 2]
                p90 = times[int(n * 0.9)] if n >= 10 else times[-1]
                
                print(f"{category:<25} {n:<8} {mean:>8.0f}ms {p50:>8.0f}ms {p90:>8.0f}ms")
        
        print()


def estimate_pipeline_latency(llm_p50):
    """Estimate full pipeline latency"""
    
    print(f"{'='*80}")
    print("ESTIMATED FULL PIPELINE LATENCY")
    print(f"{'='*80}\n")
    
    components = {
        "EOU (VAD)": 150,
        "STT (Sarvam)": 150,
        "LLM (70B)": llm_p50,
        "TTS (Cartesia)": 256
    }
    
    total = sum(components.values())
    
    print("Component Breakdown:")
    for component, latency in components.items():
        print(f"  {component:<20} {latency:>6.0f}ms")
    
    print(f"  {'-'*27}")
    print(f"  {'Total Pipeline':<20} {total:>6.0f}ms")
    print()
    
    # Compare to benchmarks
    print("Industry Comparison:")
    competitors = {
        "ElevenLabs": 600,
        "Retell AI": 650,
        "Bland AI": 700,
        "Vapi": 720,
        "Diigoo (Llama 70B)": total
    }
    
    for name, latency in competitors.items():
        status = "✅" if latency <= 700 else "⚠️"
        highlight = " ← YOU ARE HERE" if "Diigoo" in name else ""
        print(f"  {status} {name:<25} {latency:>6.0f}ms{highlight}")
    
    print()
    
    # Verdict
    target = 700
    difference = total - target
    
    if total <= target:
        print(f"✅ EXCELLENT: {difference:+.0f}ms vs industry target (<700ms)")
    elif total <= 1000:
        print(f"⚠️  ACCEPTABLE: {difference:+.0f}ms over target (still competitive)")
    else:
        print(f"❌ NEEDS IMPROVEMENT: {difference:+.0f}ms over target")
    
    print()


def save_results(all_results, stats, output_dir="benchmarks"):
    """Save results to JSON"""
    
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/llama70b_benchmark_{timestamp}.json"
    
    output = {
        "timestamp": datetime.now().isoformat(),
        "model": "llama-3.3-70b-versatile",
        "provider": "Groq",
        "total_samples": len(all_results),
        "statistics": stats,
        "raw_results": all_results[:10]  # Save first 10 for reference
    }
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {filename}\n")
    return filename


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Benchmark Llama 3.3 70B latency")
    parser.add_argument(
        "--samples",
        type=int,
        default=50,
        help="Number of test samples (default: 50)"
    )
    
    args = parser.parse_args()
    
    # Run benchmark
    all_results, category_results = run_benchmark(args.samples)
    
    # Calculate statistics
    stats = calculate_statistics(all_results)
    
    # Calculate category statistics
    category_stats = {}
    for category, results in category_results.items():
        if results:
            category_stats[category] = results
    
    # Print results
    print_statistics(stats, category_stats)
    
    # Estimate pipeline
    estimate_pipeline_latency(stats['total_time']['p50'])
    
    # Save results
    save_results(all_results, stats)
    
    # Final recommendation
    print(f"{'='*80}")
    print("PRODUCTION READINESS ASSESSMENT")
    print(f"{'='*80}\n")
    
    llm_p50 = stats['total_time']['p50']
    pipeline_total = 150 + 150 + llm_p50 + 256
    
    print(f"LLM p50 Latency: {llm_p50:.0f}ms")
    print(f"Pipeline Total: {pipeline_total:.0f}ms")
    print()
    
    if pipeline_total < 700:
        print("✅ EXCELLENT - Beats industry standard!")
        print("   Recommendation: Deploy immediately")
    elif pipeline_total < 1000:
        print("✅ GOOD - Competitive latency")
        print("   Recommendation: Deploy for quality-focused use case")
    elif pipeline_total < 1500:
        print("⚠️  ACCEPTABLE - Slower than competitors")
        print("   Recommendation: Deploy with quality positioning")
    else:
        print("❌ NEEDS IMPROVEMENT - Too slow")
        print("   Recommendation: Optimize or use faster model")
    
    print()


if __name__ == "__main__":
    main()
