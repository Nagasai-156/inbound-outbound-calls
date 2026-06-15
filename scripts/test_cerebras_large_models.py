#!/usr/bin/env python3
"""
Test Cerebras Large Models for Telugu/Tenglish Fluency
=======================================================
Tests frontier-class models (Llama 405B, Qwen 2.5 235B) for:
- Telugu/Tenglish code-switching quality
- Natural conversation flow
- Business context understanding
- Latency with large parameter counts

Run: python scripts/test_cerebras_large_models.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("cerebras_test")


@dataclass
class ModelTest:
    """Single model test result"""
    model_name: str
    prompt: str
    response: str
    latency_ms: float
    quality_score: int  # 1-5 scale
    fluency_notes: str


# Test prompts covering different business scenarios
TEST_PROMPTS = [
    {
        "scenario": "Appointment Booking",
        "prompt": "నమస్కారం sir, నేను doctor appointment book చేసుకోవాలి. Next week ఏదైనా slots available unnaya?",
        "expected": "Should respond naturally in Tenglish, check availability, ask for preferred day/time"
    },
    {
        "scenario": "Product Inquiry",
        "prompt": "Eeyana product price enti? Delivery eppudu avtundi Hyderabad ki?",
        "expected": "Should handle mixed Telugu-English naturally, provide pricing info, delivery timeline"
    },
    {
        "scenario": "Payment Issue",
        "prompt": "Nenu payment chesanu kani order confirm avvaledu. Endi problem? UPI transaction success aindi.",
        "expected": "Should empathize, troubleshoot payment issue, offer resolution"
    },
    {
        "scenario": "Order Status",
        "prompt": "My order #12345 inka deliver avvaledu. Status enti bro? Already 3 days ayyayi.",
        "expected": "Should check order status, provide update, show concern for delay"
    },
    {
        "scenario": "Reschedule Request",
        "prompt": "Naa tomorrow appointment cancel cheyali. Next week same time ki shift cheyagalara?",
        "expected": "Should confirm cancellation, check new slot availability, reschedule smoothly"
    },
]


CEREBRAS_MODELS = [
    {
        "id": "zai-glm-4.7",
        "name": "GLM-4 (4.7B)",
        "description": "Smaller efficient model",
        "params": "4.7B"
    },
    {
        "id": "gpt-oss-120b",
        "name": "GPT-OSS 120B (Large)",
        "description": "Large open-source model, best quality",
        "params": "120B"
    },
]


class CerebrasLargeModelTester:
    """Test Cerebras large models for Telugu fluency"""
    
    def __init__(self):
        self.api_key = os.getenv("CEREBRAS_API_KEY")
        if not self.api_key:
            raise ValueError("CEREBRAS_API_KEY not found in environment")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.cerebras.ai/v1"
        )
        
        self.results: List[ModelTest] = []
    
    async def test_model(
        self,
        model_id: str,
        model_name: str,
        prompt_data: dict
    ) -> ModelTest:
        """Test a single model with a prompt"""
        
        system_prompt = """You are a friendly customer service AI agent for an Indian business. 
You speak naturally in Telugu-English code-mixed style (Tenglish) which is common in Hyderabad and Telangana.
You understand Telugu, Hindi, and English, and respond in the same language/mix the customer uses.
Be warm, helpful, and conversational. Keep responses concise (2-3 sentences max)."""
        
        try:
            start = time.perf_counter()
            
            response = await self.client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_data["prompt"]}
                ],
                temperature=0.7,
                max_tokens=200,
            )
            
            latency_ms = (time.perf_counter() - start) * 1000
            response_text = response.choices[0].message.content
            
            # Basic quality check (would be manual in production)
            quality_score = self._assess_quality(
                prompt_data["prompt"],
                response_text,
                prompt_data["expected"]
            )
            
            return ModelTest(
                model_name=model_name,
                prompt=prompt_data["prompt"],
                response=response_text,
                latency_ms=round(latency_ms, 1),
                quality_score=quality_score,
                fluency_notes=self._get_fluency_notes(response_text)
            )
            
        except Exception as e:
            logger.error(f"Error testing {model_name}: {e}")
            return ModelTest(
                model_name=model_name,
                prompt=prompt_data["prompt"],
                response=f"ERROR: {str(e)}",
                latency_ms=0,
                quality_score=0,
                fluency_notes="Test failed"
            )
    
    def _assess_quality(self, prompt: str, response: str, expected: str) -> int:
        """Basic automated quality assessment (1-5 scale)"""
        
        score = 3  # Start with neutral
        
        # Check if response is in Tenglish (has both Telugu and English)
        has_telugu = any(ord(c) >= 0x0C00 and ord(c) <= 0x0C7F for c in response)
        has_english = any(c.isascii() and c.isalpha() for c in response)
        
        if has_telugu and has_english:
            score += 1  # Good code-mixing
        elif not has_telugu:
            score -= 1  # Missing Telugu context
        
        # Check response length (should be concise)
        if len(response.split()) > 50:
            score -= 1  # Too verbose
        elif len(response.split()) < 10:
            score -= 1  # Too brief
        
        # Check if response addresses the query
        key_terms = ["appointment", "delivery", "payment", "order", "reschedule"]
        if any(term in prompt.lower() for term in key_terms):
            if any(term in response.lower() for term in key_terms):
                score += 1  # Contextually relevant
        
        return max(1, min(5, score))  # Clamp to 1-5
    
    def _get_fluency_notes(self, response: str) -> str:
        """Generate fluency assessment notes"""
        
        has_telugu = any(ord(c) >= 0x0C00 and ord(c) <= 0x0C7F for c in response)
        has_english = any(c.isascii() and c.isalpha() for c in response)
        word_count = len(response.split())
        
        notes = []
        
        if has_telugu and has_english:
            notes.append("✓ Natural code-mixing")
        elif has_telugu:
            notes.append("⚠ Telugu-only (should mix English)")
        elif has_english:
            notes.append("⚠ English-only (missing Telugu)")
        
        if word_count < 15:
            notes.append("⚠ Too brief")
        elif word_count > 60:
            notes.append("⚠ Too verbose")
        else:
            notes.append("✓ Good length")
        
        return ", ".join(notes) if notes else "N/A"
    
    async def run_comprehensive_test(self):
        """Run full test suite across all models and prompts"""
        
        logger.info("="*80)
        logger.info("CEREBRAS LARGE MODEL TESTING - Telugu/Tenglish Fluency")
        logger.info("="*80)
        logger.info("\nTesting Models:")
        for model in CEREBRAS_MODELS:
            logger.info(f"  • {model['name']} ({model['params']}) - {model['description']}")
        logger.info(f"\nTest Scenarios: {len(TEST_PROMPTS)}")
        logger.info("="*80 + "\n")
        
        for model in CEREBRAS_MODELS:
            logger.info(f"\n{'='*80}")
            logger.info(f"Testing: {model['name']} ({model['params']})")
            logger.info(f"{'='*80}\n")
            
            model_results = []
            
            for i, prompt_data in enumerate(TEST_PROMPTS, 1):
                logger.info(f"Test {i}/{len(TEST_PROMPTS)}: {prompt_data['scenario']}")
                logger.info(f"Prompt: {prompt_data['prompt']}")
                
                result = await self.test_model(
                    model['id'],
                    model['name'],
                    prompt_data
                )
                
                model_results.append(result)
                
                logger.info(f"Response: {result.response}")
                logger.info(f"Latency: {result.latency_ms}ms")
                logger.info(f"Quality: {'⭐' * result.quality_score} ({result.quality_score}/5)")
                logger.info(f"Notes: {result.fluency_notes}")
                logger.info("")
                
                # Brief delay between requests
                await asyncio.sleep(1)
            
            self.results.extend(model_results)
            self._print_model_summary(model['name'], model_results)
        
        self._print_final_comparison()
        self._save_results()
    
    def _print_model_summary(self, model_name: str, results: List[ModelTest]):
        """Print summary for a single model"""
        
        avg_latency = sum(r.latency_ms for r in results) / len(results)
        avg_quality = sum(r.quality_score for r in results) / len(results)
        
        logger.info(f"\n{'─'*80}")
        logger.info(f"Summary: {model_name}")
        logger.info(f"{'─'*80}")
        logger.info(f"Average Latency: {avg_latency:.1f}ms")
        logger.info(f"Average Quality: {avg_quality:.1f}/5.0 {'⭐' * round(avg_quality)}")
        logger.info(f"Tests Completed: {len(results)}/{len(TEST_PROMPTS)}")
        logger.info("")
    
    def _print_final_comparison(self):
        """Print comparative analysis across all models"""
        
        logger.info("\n" + "="*80)
        logger.info("COMPARATIVE ANALYSIS")
        logger.info("="*80 + "\n")
        
        # Group results by model
        model_summaries = {}
        for model in CEREBRAS_MODELS:
            model_results = [r for r in self.results if r.model_name == model['name']]
            if model_results:
                model_summaries[model['name']] = {
                    'avg_latency': sum(r.latency_ms for r in model_results) / len(model_results),
                    'avg_quality': sum(r.quality_score for r in model_results) / len(model_results),
                    'params': model['params']
                }
        
        # Print comparison table
        logger.info("| Model | Params | Avg Latency | Avg Quality | Recommendation |")
        logger.info("|-------|--------|-------------|-------------|----------------|")
        
        for model_name, summary in model_summaries.items():
            quality_stars = '⭐' * round(summary['avg_quality'])
            
            # Recommendation logic
            if summary['avg_quality'] >= 4.5 and summary['avg_latency'] < 1000:
                rec = "🏆 Best overall"
            elif summary['avg_quality'] >= 4.0:
                rec = "✅ Recommended"
            elif summary['avg_latency'] < 500:
                rec = "⚡ Fastest"
            else:
                rec = "⚠️ Consider alternatives"
            
            logger.info(f"| {model_name} | {summary['params']} | "
                       f"{summary['avg_latency']:.1f}ms | "
                       f"{summary['avg_quality']:.1f}/5 {quality_stars} | {rec} |")
        
        logger.info("\n" + "="*80)
        
        # Recommendations
        logger.info("\n📊 RECOMMENDATIONS:\n")
        
        best_quality = max(model_summaries.items(), key=lambda x: x[1]['avg_quality'])
        fastest = min(model_summaries.items(), key=lambda x: x[1]['avg_latency'])
        
        logger.info(f"🏆 Best Quality: {best_quality[0]} ({best_quality[1]['avg_quality']:.1f}/5)")
        logger.info(f"⚡ Fastest: {fastest[0]} ({fastest[1]['avg_latency']:.1f}ms)")
        
        logger.info("\n💡 Use Case Recommendations:")
        logger.info("  • Production (Quality Priority): Use highest quality model")
        logger.info("  • Production (Speed Priority): Use fastest model with quality ≥4.0")
        logger.info("  • Testing/Demo: Use fastest model")
        
        # Pricing consideration
        logger.info("\n💰 Cost Consideration:")
        logger.info("  • Larger models (405B, 235B) may cost more per token")
        logger.info("  • Check Cerebras pricing before production deployment")
        logger.info("  • Balance quality vs cost based on business value")
    
    def _save_results(self):
        """Save results to JSON file"""
        
        output_dir = Path("benchmarks")
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = output_dir / f"cerebras_large_models_test_{timestamp}.json"
        
        data = {
            "test_info": {
                "timestamp": datetime.now().isoformat(),
                "models_tested": [m['name'] for m in CEREBRAS_MODELS],
                "scenarios": [p['scenario'] for p in TEST_PROMPTS],
            },
            "results": [asdict(r) for r in self.results],
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n✅ Results saved to: {filename}")


async def main():
    """Main test runner"""
    
    try:
        tester = CerebrasLargeModelTester()
        await tester.run_comprehensive_test()
        
        logger.info("\n" + "="*80)
        logger.info("✅ TESTING COMPLETE!")
        logger.info("="*80)
        logger.info("\nNext Steps:")
        logger.info("1. Review test results above")
        logger.info("2. Check benchmarks/cerebras_large_models_test_*.json for details")
        logger.info("3. Update .env with best model: DEFAULT_LLM_MODEL=cerebras/<model>")
        logger.info("4. Re-run p50 benchmark with new model")
        logger.info("5. Compare quality vs latency tradeoff")
        
    except ValueError as e:
        logger.error(f"\n❌ Configuration Error: {e}")
        logger.info("\nAdd to .env:")
        logger.info("CEREBRAS_API_KEY=your_key_here")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n\n⚠️ Test interrupted by user")
    except Exception as e:
        logger.error(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
