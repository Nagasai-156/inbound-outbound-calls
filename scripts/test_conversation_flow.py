#!/usr/bin/env python3
"""
Multi-turn conversation test for Groq models
Tests realistic 5-turn conversations with each model
"""

import os
import sys
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq

# Load environment
load_dotenv()

# Test models
MODELS = {
    "llama-8b": {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B (Current)",
        "rpm": 30,
        "rpd": 14400
    },
    "qwen-32b": {
        "id": "qwen/qwen3-32b",
        "name": "Qwen3 32B (Asian Expert)",
        "rpm": 60,
        "rpd": 1000
    },
    "llama-70b": {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B (Quality)",
        "rpm": 30,
        "rpd": 1000
    }
}

# Conversation scenarios (5 turns each)
CONVERSATIONS = [
    {
        "name": "Appointment Booking",
        "system": "You are a helpful appointment booking assistant. Speak Telugu and English mixed naturally (Tenglish). Be professional and helpful.",
        "turns": [
            "Namaste, naku doctor appointment book cheyali",
            "Repu morning 10 AM available aa?",
            "Ok perfect. Dr. Sharma unda available?",
            "General checkup kosam. Maa intlo address update cheyali",
            "Great! Confirmation SMS pampandi please"
        ]
    },
    {
        "name": "Internet Complaint",
        "system": "You are a customer support agent. Handle complaints professionally and empathetically in Tenglish.",
        "turns": [
            "Hello, naa internet connection problem undi",
            "Last 2 days nundi chala slow ga work chestundi. Streaming kuda avvadam ledu",
            "Router restart chesanu, but same problem",
            "Speed test chesthe 2 Mbps ostundi, but plan 50 Mbps",
            "Ok, technician eppudu vastaru? Urgent ga chudandi"
        ]
    },
    {
        "name": "Bill Payment Query",
        "system": "You are a billing support assistant. Explain payment details clearly in Tenglish.",
        "turns": [
            "Naa bill amount entha undi ee month?",
            "Ah ok. EMI option available aa?",
            "6 months EMI chesthe monthly entha avutundi?",
            "Interest rate entha?",
            "Ok proceed cheyyandi EMI option tho"
        ]
    },
    {
        "name": "Product Purchase",
        "system": "You are a sales assistant. Help customers make purchase decisions in Tenglish.",
        "turns": [
            "iPhone 15 pro stock lo unda?",
            "256GB variant price entha?",
            "Delivery entha sepu padutundi Hyderabad ki?",
            "Exchange offer unda? iPhone 12 undi naaku",
            "Good! Order confirm cheyandi, cash on delivery"
        ]
    },
    {
        "name": "Technical Support",
        "system": "You are a technical support expert. Help debug issues clearly using Tenglish.",
        "turns": [
            "Mobile charge avvadam ledu, cable connection chesthe charging symbol kanapadatledu",
            "Cable marchukoni try chesanu, different socket kuda try chesanu",
            "Phone reboot kuda chesanu, still charging avvadam ledu",
            "Battery health 85% undi last check lo",
            "Service center address cheppandi please"
        ]
    }
]


def run_conversation(client, model_id, conversation):
    """Run a complete conversation with multiple turns"""
    
    messages = [
        {"role": "system", "content": conversation["system"]}
    ]
    
    results = []
    total_latency = 0
    
    for turn_idx, user_message in enumerate(conversation["turns"], 1):
        # Add user message
        messages.append({"role": "user", "content": user_message})
        
        # Get response
        start_time = time.time()
        
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=150,
                temperature=0.7
            )
            
            latency = (time.time() - start_time) * 1000
            total_latency += latency
            
            assistant_message = response.choices[0].message.content
            
            # Add assistant response to conversation
            messages.append({"role": "assistant", "content": assistant_message})
            
            results.append({
                "turn": turn_idx,
                "user": user_message,
                "assistant": assistant_message,
                "latency_ms": latency,
                "tokens": response.usage.total_tokens,
                "success": True
            })
            
        except Exception as e:
            results.append({
                "turn": turn_idx,
                "user": user_message,
                "assistant": None,
                "latency_ms": (time.time() - start_time) * 1000,
                "error": str(e),
                "success": False
            })
            break  # Stop conversation on error
        
        # Rate limit protection
        time.sleep(0.3)
    
    return {
        "results": results,
        "total_latency": total_latency,
        "avg_latency": total_latency / len(results) if results else 0,
        "success_rate": sum(1 for r in results if r["success"]) / len(results) if results else 0
    }


def print_conversation(model_name, conversation_name, conv_result):
    """Print a single conversation in readable format"""
    
    print(f"\n{'='*80}")
    print(f"{model_name} - {conversation_name}")
    print(f"{'='*80}\n")
    
    for turn_data in conv_result["results"]:
        turn = turn_data["turn"]
        
        # User message
        print(f"Turn {turn} | USER:")
        print(f"  {turn_data['user']}")
        print()
        
        # Assistant response
        if turn_data["success"]:
            print(f"Turn {turn} | ASSISTANT ({turn_data['latency_ms']:.0f}ms):")
            
            # Format response (wrap long lines)
            response = turn_data["assistant"]
            if len(response) > 100:
                # Print first 100 chars per line
                for i in range(0, len(response), 100):
                    print(f"  {response[i:i+100]}")
            else:
                print(f"  {response}")
        else:
            print(f"Turn {turn} | ERROR:")
            print(f"  {turn_data.get('error', 'Unknown error')}")
        
        print()
    
    # Summary
    print(f"{'─'*80}")
    print(f"Avg Latency: {conv_result['avg_latency']:.0f}ms | "
          f"Total: {conv_result['total_latency']:.0f}ms | "
          f"Success Rate: {conv_result['success_rate']*100:.0f}%")
    print()


def main():
    print(f"""
╔═══════════════════════════════════════════════════════════════════════════╗
║            MULTI-TURN CONVERSATION TEST - GROQ MODELS                     ║
║            5 Realistic Scenarios × 5 Turns Each × 3 Models               ║
╚═══════════════════════════════════════════════════════════════════════════╝

Testing {len(MODELS)} models with {len(CONVERSATIONS)} conversation scenarios...
Each conversation has 5 turns (10 messages total with assistant responses)

""")
    
    # Check API key
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        print("❌ Error: GROQ_API_KEY not found in environment")
        sys.exit(1)
    
    client = Groq(api_key=groq_key)
    
    # Store all results
    all_results = {}
    
    # Test each model
    for model_key, model_info in MODELS.items():
        model_id = model_info["id"]
        model_name = model_info["name"]
        
        print(f"\n{'#'*80}")
        print(f"# TESTING: {model_name}")
        print(f"# Model ID: {model_id}")
        print(f"# Limits: {model_info['rpm']} RPM, {model_info['rpd']} RPD")
        print(f"{'#'*80}\n")
        
        model_results = {}
        
        # Test each conversation
        for conv_idx, conversation in enumerate(CONVERSATIONS, 1):
            conv_name = conversation["name"]
            
            print(f"[{conv_idx}/{len(CONVERSATIONS)}] Testing: {conv_name}...", flush=True)
            
            conv_result = run_conversation(client, model_id, conversation)
            model_results[conv_name] = conv_result
            
            print(f"    ✅ Completed | Avg: {conv_result['avg_latency']:.0f}ms | "
                  f"Success: {conv_result['success_rate']*100:.0f}%")
            
            # Rate limit protection between conversations
            time.sleep(1)
        
        all_results[model_key] = {
            "model_info": model_info,
            "conversations": model_results
        }
        
        # Longer pause between models
        time.sleep(2)
    
    # Print all conversations
    print(f"\n\n{'='*80}")
    print("DETAILED CONVERSATION TRANSCRIPTS")
    print(f"{'='*80}\n")
    
    for model_key, model_data in all_results.items():
        model_name = model_data["model_info"]["name"]
        
        for conv_name, conv_result in model_data["conversations"].items():
            print_conversation(model_name, conv_name, conv_result)
    
    # Print summary statistics
    print(f"\n{'='*80}")
    print("SUMMARY STATISTICS")
    print(f"{'='*80}\n")
    
    print(f"{'Model':<30} {'Avg Latency':<15} {'Success Rate':<15}")
    print(f"{'-'*60}")
    
    for model_key, model_data in all_results.items():
        model_name = model_data["model_info"]["name"]
        
        # Calculate overall stats
        all_latencies = []
        all_successes = []
        
        for conv_result in model_data["conversations"].values():
            for turn_data in conv_result["results"]:
                if turn_data["success"]:
                    all_latencies.append(turn_data["latency_ms"])
                    all_successes.append(1)
                else:
                    all_successes.append(0)
        
        avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else 0
        success_rate = sum(all_successes) / len(all_successes) if all_successes else 0
        
        print(f"{model_name:<30} {avg_latency:>8.0f}ms       {success_rate*100:>6.0f}%")
    
    print()
    
    # Save results to JSON
    output_dir = "benchmarks"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{output_dir}/conversation_test_{timestamp}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "models": MODELS,
            "conversations": CONVERSATIONS,
            "results": all_results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {output_file}")
    print()
    
    # Quality review instructions
    print(f"{'='*80}")
    print("NEXT STEPS: MANUAL QUALITY REVIEW")
    print(f"{'='*80}\n")
    print("Review the conversation transcripts above and rate each model:")
    print()
    print("For each conversation, evaluate:")
    print("  1. Telugu/Tenglish fluency (1-5)")
    print("  2. Code-switching naturalness (1-5)")
    print("  3. Context understanding (1-5)")
    print("  4. Response appropriateness (1-5)")
    print("  5. Overall conversation quality (1-5)")
    print()
    print("Look for:")
    print("  ✅ Natural Tenglish mixing")
    print("  ✅ Maintains context across turns")
    print("  ✅ Professional and helpful tone")
    print("  ✅ No <think> tags or reasoning exposure")
    print("  ✅ Appropriate response length")
    print()
    print("After review, choose the best model for production!")
    print()


if __name__ == "__main__":
    main()
