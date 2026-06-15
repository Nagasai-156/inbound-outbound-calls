#!/usr/bin/env python3
"""
Test and compare Groq models for Telugu voice AI
Compares: Llama 8B, Qwen 32B, Llama 70B
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from typing import Dict, List, Any
from dotenv import load_dotenv
from groq import Groq

# Load environment
load_dotenv()

# Test scenarios for Telugu/Tenglish
TEST_SCENARIOS = [
    {
        "name": "Greeting (Simple Telugu)",
        "system": "You are a helpful Telugu voice assistant. Respond naturally in Telugu or Tenglish.",
        "user": "Namaste, mee peru enti?",
        "expected": "Natural Telugu response with code-switching",
        "complexity": "simple"
    },
    {
        "name": "Appointment Booking (Tenglish)",
        "system": "You are a helpful appointment booking assistant. Speak Telugu and English mixed naturally.",
        "user": "Naku repu 3 PM ki doctor appointment book cheyali. Available aa?",
        "expected": "Professional Tenglish with appointment details",
        "complexity": "medium"
    },
    {
        "name": "Complaint Handling (Complex)",
        "system": "You are a customer support agent. Handle complaints professionally in Tenglish.",
        "user": "Naa internet connection chala slow ga work chestundi. Last 3 days nundi same problem. Ela resolve chestaru?",
        "expected": "Empathetic response, troubleshooting steps in Tenglish",
        "complexity": "complex"
    },
    {
        "name": "Payment Query (Business)",
        "system": "You are a billing support assistant. Explain payment details clearly in Tenglish.",
        "user": "Naa bill eppudu generate avtundi? EMI option available aa?",
        "expected": "Clear billing info with EMI details in Tenglish",
        "complexity": "medium"
    },
    {
        "name": "Technical Support (Advanced)",
        "system": "You are a technical support expert. Help debug issues using Tenglish.",
        "user": "Mobile lo apps install avtunnayi kani open avvadam ledu. Settings lo storage chusa, sufficient space undi. Troubleshooting steps cheppandi.",
        "expected": "Step-by-step technical guidance in Tenglish",
        "complexity": "complex"
    }
]

# Available Groq models
GROQ_MODELS = {
    "llama-8b": {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B Instant",
        "size": "8B",
        "rpm": 30,
        "rpd": 14400
    },
    "qwen-32b": {
        "id": "qwen/qwen3-32b",
        "name": "Qwen3 32B",
        "size": "32B",
        "rpm": 60,
        "rpd": 1000
    },
    "llama-70b": {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B Versatile",
        "size": "70B",
        "rpm": 30,
        "rpd": 1000
    }
}


def test_model(client: Groq, model_id: str, scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Test a single model with a scenario"""
    
    print(f"  Testing: {scenario['name']}...", end=" ", flush=True)
    
    start_time = time.time()
    
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": scenario["system"]},
                {"role": "user", "content": scenario["user"]}
            ],
            max_tokens=150,
            temperature=0.7
        )
        
        latency = (time.time() - start_time) * 1000  # ms
        
        assistant_response = response.choices[0].message.content
        
        # Calculate tokens
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        
        print(f"✅ {latency:.0f}ms")
        
        return {
            "success": True,
            "latency_ms": latency,
            "response": assistant_response,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        }
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "latency_ms": (time.time() - start_time) * 1000
        }


def evaluate_response(response: str, scenario: Dict[str, Any]) -> Dict[str, float]:
    """Manual evaluation prompts (to be filled by human reviewer)"""
    
    # For automated testing, we return placeholders
    # In real usage, this would be manual review or LLM-as-judge
    
    return {
        "telugu_fluency": 0.0,  # 1-5 scale
        "code_switching": 0.0,  # 1-5 scale  
        "instruction_following": 0.0,  # 1-5 scale
        "naturalness": 0.0,  # 1-5 scale
        "overall": 0.0  # 1-5 scale
    }


def compare_models(models_to_test: List[str], calls_per_model: int = 5) -> Dict[str, Any]:
    """Compare multiple Groq models"""
    
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    results = {}
    
    for model_key in models_to_test:
        if model_key not in GROQ_MODELS:
            print(f"❌ Unknown model: {model_key}")
            continue
        
        model_info = GROQ_MODELS[model_key]
        model_id = model_info["id"]
        
        print(f"\n{'='*70}")
        print(f"Testing: {model_info['name']} ({model_info['size']})")
        print(f"Model ID: {model_id}")
        print(f"Limits: {model_info['rpm']} RPM, {model_info['rpd']} RPD")
        print(f"{'='*70}\n")
        
        model_results = {
            "model_info": model_info,
            "scenarios": {}
        }
        
        # Test each scenario
        for scenario in TEST_SCENARIOS[:calls_per_model]:
            scenario_name = scenario["name"]
            
            result = test_model(client, model_id, scenario)
            
            model_results["scenarios"][scenario_name] = {
                "scenario": scenario,
                "result": result
            }
            
            # Rate limit protection
            time.sleep(0.5)
        
        results[model_key] = model_results
    
    return results


def calculate_statistics(results: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate statistics across models"""
    
    stats = {}
    
    for model_key, model_data in results.items():
        latencies = []
        successes = 0
        total = 0
        total_tokens = 0
        
        for scenario_name, scenario_data in model_data["scenarios"].items():
            result = scenario_data["result"]
            total += 1
            
            if result["success"]:
                successes += 1
                latencies.append(result["latency_ms"])
                total_tokens += result.get("total_tokens", 0)
        
        if latencies:
            latencies.sort()
            n = len(latencies)
            
            stats[model_key] = {
                "success_rate": successes / total,
                "total_tests": total,
                "avg_latency_ms": sum(latencies) / len(latencies),
                "p50_latency_ms": latencies[n // 2] if n > 0 else 0,
                "p90_latency_ms": latencies[int(n * 0.9)] if n > 0 else 0,
                "p95_latency_ms": latencies[int(n * 0.95)] if n > 0 else 0,
                "min_latency_ms": min(latencies),
                "max_latency_ms": max(latencies),
                "avg_tokens": total_tokens / successes if successes > 0 else 0
            }
        else:
            stats[model_key] = {
                "success_rate": 0,
                "total_tests": total,
                "avg_latency_ms": 0,
                "p50_latency_ms": 0
            }
    
    return stats


def print_comparison_table(stats: Dict[str, Any], results: Dict[str, Any]):
    """Print comparison table"""
    
    print(f"\n{'='*90}")
    print("GROQ MODELS COMPARISON - LATENCY & PERFORMANCE")
    print(f"{'='*90}\n")
    
    # Header
    print(f"{'Model':<25} {'Size':<8} {'RPM':<6} {'RPD':<8} {'Avg':<10} {'p50':<10} {'p90':<10} {'Success':<8}")
    print(f"{'-'*90}")
    
    # Rows
    for model_key, stat in stats.items():
        model_info = results[model_key]["model_info"]
        
        print(f"{model_info['name']:<25} "
              f"{model_info['size']:<8} "
              f"{model_info['rpm']:<6} "
              f"{model_info['rpd']:<8} "
              f"{stat['avg_latency_ms']:>8.0f}ms "
              f"{stat['p50_latency_ms']:>8.0f}ms "
              f"{stat['p90_latency_ms']:>8.0f}ms "
              f"{stat['success_rate']*100:>6.0f}%")
    
    print()


def print_detailed_responses(results: Dict[str, Any]):
    """Print detailed responses for manual review"""
    
    print(f"\n{'='*90}")
    print("DETAILED RESPONSES FOR MANUAL QUALITY REVIEW")
    print(f"{'='*90}\n")
    
    for scenario_idx, scenario in enumerate(TEST_SCENARIOS[:5]):
        print(f"\n{'─'*90}")
        print(f"Scenario {scenario_idx + 1}: {scenario['name']}")
        print(f"User: {scenario['user']}")
        print(f"{'─'*90}\n")
        
        for model_key, model_data in results.items():
            model_name = model_data["model_info"]["name"]
            
            if scenario["name"] in model_data["scenarios"]:
                result = model_data["scenarios"][scenario["name"]]["result"]
                
                print(f"{model_name} ({result.get('latency_ms', 0):.0f}ms):")
                
                if result["success"]:
                    print(f"{result['response']}")
                else:
                    print(f"❌ Error: {result.get('error', 'Unknown')}")
                
                print()


def save_results(results: Dict[str, Any], stats: Dict[str, Any], output_dir: str = "benchmarks"):
    """Save results to JSON"""
    
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/groq_models_comparison_{timestamp}.json"
    
    output = {
        "timestamp": datetime.now().isoformat(),
        "test_scenarios": TEST_SCENARIOS,
        "results": results,
        "statistics": stats
    }
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Results saved to: {filename}")
    return filename


def main():
    parser = argparse.ArgumentParser(description="Compare Groq models for Telugu voice AI")
    parser.add_argument(
        "--models",
        type=str,
        default="llama-8b,qwen-32b,llama-70b",
        help="Comma-separated list of models to test (llama-8b, qwen-32b, llama-70b)"
    )
    parser.add_argument(
        "--calls",
        type=int,
        default=5,
        help="Number of test scenarios per model (default: 5)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmarks",
        help="Output directory for results (default: benchmarks)"
    )
    
    args = parser.parse_args()
    
    # Parse models
    models_to_test = [m.strip() for m in args.models.split(",")]
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════╗
║                     GROQ MODELS COMPARISON TEST                           ║
║                     Telugu/Tenglish Voice AI                              ║
╚═══════════════════════════════════════════════════════════════════════════╝

Models to test: {', '.join(models_to_test)}
Scenarios per model: {args.calls}
Output directory: {args.output_dir}

Starting tests...
""")
    
    # Check API key
    if not os.getenv("GROQ_API_KEY"):
        print("❌ Error: GROQ_API_KEY not found in environment")
        sys.exit(1)
    
    # Run comparison
    start_time = time.time()
    results = compare_models(models_to_test, args.calls)
    total_time = time.time() - start_time
    
    # Calculate statistics
    stats = calculate_statistics(results)
    
    # Print results
    print_comparison_table(stats, results)
    print_detailed_responses(results)
    
    # Save results
    output_file = save_results(results, stats, args.output_dir)
    
    # Summary
    print(f"\n{'='*90}")
    print("SUMMARY & RECOMMENDATIONS")
    print(f"{'='*90}\n")
    
    # Find best models
    best_speed = min(stats.items(), key=lambda x: x[1]["p50_latency_ms"])
    
    print(f"⚡ Fastest Model: {GROQ_MODELS[best_speed[0]]['name']}")
    print(f"   p50 Latency: {best_speed[1]['p50_latency_ms']:.0f}ms")
    print(f"   Avg Latency: {best_speed[1]['avg_latency_ms']:.0f}ms")
    print()
    
    print("📊 Model Comparison:")
    for model_key in models_to_test:
        if model_key in stats:
            model_info = GROQ_MODELS[model_key]
            stat = stats[model_key]
            
            print(f"\n{model_info['name']}:")
            print(f"  ├─ Size: {model_info['size']}")
            print(f"  ├─ Limits: {model_info['rpm']} RPM, {model_info['rpd']} RPD")
            print(f"  ├─ p50 Latency: {stat['p50_latency_ms']:.0f}ms")
            print(f"  ├─ Avg Latency: {stat['avg_latency_ms']:.0f}ms")
            print(f"  ├─ Success Rate: {stat['success_rate']*100:.0f}%")
            print(f"  └─ Avg Tokens: {stat['avg_tokens']:.0f}")
    
    print(f"\n⏱️  Total test time: {total_time:.1f}s")
    print(f"📁 Full results: {output_file}")
    
    print(f"\n{'='*90}")
    print("MANUAL QUALITY REVIEW REQUIRED")
    print(f"{'='*90}\n")
    print("Please review the detailed responses above and rate each model:")
    print("  1. Telugu fluency (1-5)")
    print("  2. Code-switching ability (1-5)")
    print("  3. Instruction following (1-5)")
    print("  4. Naturalness (1-5)")
    print("  5. Overall quality (1-5)")
    print()
    print("Responses are printed above for each scenario.")
    print()


if __name__ == "__main__":
    main()
