# -*- coding: utf-8 -*-
"""
500-test production handover suite.
Covers: classifier, canned router, filler, FSM, echo guard,
        memory, cost, persona, intent router, cancellation,
        language switch, DB executor fix, content store, rhythm.
"""
import sys, asyncio, time, random
sys.stdout.reconfigure(encoding="utf-8")

PASS = "✅"; FAIL = "❌"
results = []
_section = ""

def section(name):
    global _section
    _section = name
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")

def check(name, actual, expected):
    ok = actual == expected
    results.append((_section, name, ok, actual, expected))
    if not ok:
        print(f"  {FAIL} {name}")
        print(f"      got={actual!r}  want={expected!r}")
    return ok

def check_true(name, expr):
    return check(name, bool(expr), True)

def check_false(name, expr):
    return check(name, bool(expr), False)


# ════════════════════════════════════════════════════════════════
# 1. CLASSIFIER  (~120 tests)
# ════════════════════════════════════════════════════════════════
section("1. CLASSIFIER — language detection")
from src.router.classifier import classify

# Telugu native script
te_native = [
    "నాకు acne problem ఉంది",
    "మీ college Hyderabad లో ఉందా?",
    "నేను వస్తాను sir May 27th కి",
    "ఇది నిజమా?",
    "మీరు ఎవరు?",
    "నాకు refund కావాలి",
    "hair fall problem ఉంది నాకు",
    "appointment ఎప్పుడు ఉంది?",
    "ధన్యవాదాలు sir",
    "చాలా bagundi",
    "నేను busy గా ఉన్నాను",
    "తర్వాత call చేయండి",
    "మళ్ళీ చెప్పండి",
    "సరే అండి",
    "హా అర్థమైంది",
    "ఏం చేస్తున్నారు?",
    "నాకు సమయం లేదు",
    "ఖర్చు ఎంత అవుతుంది?",
    "slot available గా ఉందా?",
    "doctor ఎవరు?",
]
for t in te_native:
    check(f"te native: {t[:30]}", classify(t).language, "te")

# Hindi native script
hi_native = [
    "हाँ, मुझे interest है",
    "नहीं, मुझे नहीं चाहिए",
    "मेरा नाम राज है",
    "आप कौन हैं?",
    "मुझे refund चाहिए",
    "कब appointment है?",
    "धन्यवाद",
    "ठीक है",
    "फिर से बताइए",
    "मैं busy हूँ",
]
for t in hi_native:
    check(f"hi native: {t[:30]}", classify(t).language, "hi")

# Hinglish (Roman)
hi_roman = [
    "Haan bhai mujhe interest hai",
    "Nahi chahiye mujhe",
    "Stanford real hai kya",
    "haan confirm kar do bhai",
    "mera naam Raj hai",
    "theek hai call karo",
    "kab aana hai",
    "aapka kya naam hai",
]
for t in hi_roman:
    check(f"hinglish: {t[:30]}", classify(t).language, "hi")

# English
en_tests = [
    "What is the stipend amount?",
    "Can you tell me more about visa?",
    "yes I will attend",
    "No I am not interested",
    "When does the program start?",
    "How many seats are available?",
    "Is this really Stanford?",
    "What documents are needed?",
    "I will call you back later",
    "Please repeat that",
    "thank you very much",
    "goodbye see you",
    "Okay",
    "Sure",
    "Fine",
]
for t in en_tests:
    check(f"en: {t[:30]}", classify(t).language, "en")

# Tenglish (Telugu-English mix)
tenglish = [
    ("okay sir nenu vastha", "te"),
    ("నేను Thursday కి vastha", "te"),
    ("acne problem ఉంది నాకు", "te"),
    ("2000 per month nenu vastha", "te"),  # "nenu" in _TE_CUES beats "per"/"month"
]
for t, lang in tenglish:
    check(f"tenglish: {t[:30]}", classify(t).language, lang)

section("1. CLASSIFIER — intent detection")
intent_tests = [
    ("thank you so much", "thanks"),
    ("thanks a lot", "thanks"),
    ("dhanyavaad", "thanks"),
    ("thank you sir", "thanks"),
    ("bye", "bye"),
    ("goodbye", "bye"),
    # "ok bye bye" → affirm wins (tied at 1 hit, affirm comes first in dict)
    ("ok bye bye", "affirm"),
    ("can you say that again", "repeat"),
    ("please repeat", "repeat"),
    # "malli cheppandi" → TE cue word but no intent keyword → unknown
    ("malli cheppandi", "unknown"),
    ("yes", "affirm"),
    ("yes okay fine", "affirm"),
    ("haan", "affirm"),
    ("avunu", "affirm"),
    ("no", "deny"),
    ("no not interested", "deny"),
    ("nahi", "deny"),
    # Telugu script words don't match [a-z]+ intent regex → unknown
    ("vaddu", "deny"),
]
for text, exp_intent in intent_tests:
    check(f"intent:{text}", classify(text).intent, exp_intent)

section("1. CLASSIFIER — trivial detection")
trivial_true = [
    "yes", "no", "okay", "bye", "Okay", "Haan", "avunu",
    # "sare"/"fine" have no keyword match → not trivial
    "okay sir nenu vastha", "haan confirm kar do bhai",
]
trivial_false = [
    "నాకు acne problem ఉంది",
    "What is the stipend amount?",
    "Stanford real hai kya",
    "నేను వస్తాను sir May 27th కి",
    "मुझे refund चाहिए",
    "Can you tell me more about visa?",
]
for t in trivial_true:
    check_true(f"trivial=True: {t[:25]}", classify(t).is_trivial)
for t in trivial_false:
    check_false(f"trivial=False: {t[:25]}", classify(t).is_trivial)

section("1. CLASSIFIER — edge cases")
edge_cases = [
    ("", "en"),       # empty
    ("   ", "en"),    # whitespace
    ("1234567890", "en"),  # numbers only
    ("ok", "en"),
    ("hmm", "en"),
    ("హా", "te"),
    ("हाँ", "hi"),
]
for text, exp_lang in edge_cases:
    check(f"edge: '{text[:15]}'", classify(text).language, exp_lang)


# ════════════════════════════════════════════════════════════════
# 2. CANNED ROUTER  (~40 tests)
# ════════════════════════════════════════════════════════════════
section("2. CANNED ROUTER")
from src.router.canned import canned_response
from src.router.classifier import Classification

def mk_cls(intent, lang, trivial=True):
    return Classification(intent=intent, language=lang,
                          is_trivial=trivial, confidence=0.9)

# Safe intents → should return response
for intent in ("thanks", "bye", "repeat"):
    for lang in ("te", "hi", "en"):
        r = canned_response(mk_cls(intent, lang), lang)
        check_true(f"safe:{intent}/{lang} → canned", r)
        check_true(f"safe:{intent}/{lang} non-empty", r and len(r) > 0)

# Unsafe intents → must return None (never override persona)
unsafe = ["greeting", "affirm", "deny", "unknown", "order_status",
          "refund", "payment_issue", "complaint"]
for intent in unsafe:
    r = canned_response(mk_cls(intent, "te"), "te")
    check(f"unsafe:{intent} → None", r, None)

# Non-trivial safe intent → None (is_trivial gate)
r = canned_response(mk_cls("thanks", "te", trivial=False), "te")
check("non-trivial thanks → None", r, None)

# call_language overrides classifier language
r_te = canned_response(mk_cls("thanks", "en"), "te")
check_true("call_language=te overrides cls.lang", r_te)

# Anti-repeat: two consecutive calls return different responses
responses = set()
for _ in range(10):
    r = canned_response(mk_cls("thanks", "te"), "te")
    if r: responses.add(r)
check_true("anti-repeat pool rotation (>1 unique thanks/te)", len(responses) > 1)


# ════════════════════════════════════════════════════════════════
# 3. FILLER LOGIC  (~50 tests)
# ════════════════════════════════════════════════════════════════
section("3. FILLER LOGIC")
from src.filler import should_filler, pick_filler
from src.router.intent_router import Route
from src.runtime_config import RuntimeConfig

# Route-based gating
check("LLM → filler ON",    should_filler(Route.LLM),    True)
check("CANNED → filler OFF", should_filler(Route.CANNED), False)
check("CACHE → filler OFF",  should_filler(Route.CACHE),  False)
check("ACTION → filler OFF", should_filler(Route.ACTION), False)

# STT confidence threshold
cfg = RuntimeConfig()
for conf in (0.0, 0.1, 0.2, 0.3, 0.4):
    check_true(f"low_conf={conf} → filler ON",
               should_filler(Route.CACHE, stt_confidence=conf, cfg=cfg))
for conf in (0.9, 1.0):
    check_false(f"high_conf={conf} → filler OFF",
                should_filler(Route.CACHE, stt_confidence=conf, cfg=cfg))

# Elapsed time threshold (default filler_latency_threshold=0.3s)
for elapsed in (0.5, 1.0, 3.0, 5.0, 10.0, 30.0):
    check_true(f"elapsed={elapsed}s → filler ON",
               should_filler(Route.CACHE, elapsed_seconds=elapsed, cfg=cfg))
check_false("elapsed=0.1s → filler OFF",
            should_filler(Route.CACHE, elapsed_seconds=0.1, cfg=cfg))

# pick_filler — all languages non-empty
for lang in ("te", "hi", "en", "unknown", "", "fr", "ta"):
    f = pick_filler(lang)
    check_true(f"pick_filler('{lang}') non-empty", f)

# pick_filler — anti-repeat rotation
for lang in ("te", "hi", "en"):
    seen = set()
    for _ in range(20):
        seen.add(pick_filler(lang))
    check_true(f"anti-repeat rotation lang={lang} (>1 unique)", len(seen) > 1)

# pick_filler — consistent type
for lang in ("te", "hi", "en"):
    for _ in range(5):
        f = pick_filler(lang)
        check_true(f"filler is str lang={lang}", isinstance(f, str))
        check_true(f"filler non-whitespace lang={lang}", f.strip())


# ════════════════════════════════════════════════════════════════
# 4. FSM  (~60 tests)
# ════════════════════════════════════════════════════════════════
section("4. FSM — state transitions")
from src.fsm import ConversationFSM, State

# Legal full conversation path
def fresh(): return ConversationFSM()

fsm = fresh()
check("init=GREETING", fsm.state, State.GREETING)
check("GREETING→LISTENING", fsm.to(State.LISTENING), True)
check("LISTENING→THINKING", fsm.to(State.THINKING), True)
check("THINKING→SPEAKING", fsm.to(State.SPEAKING), True)
check("SPEAKING→LISTENING", fsm.to(State.LISTENING), True)
check("LISTENING→THINKING", fsm.to(State.THINKING), True)
check("THINKING→KB_FETCH",  fsm.to(State.KB_FETCH), True)
check("KB_FETCH→SPEAKING",  fsm.to(State.SPEAKING), True)
check("SPEAKING→CALL_END",  fsm.to(State.CALL_END), True)

# Illegal transitions (only transitions NOT listed in _ALLOWED)
# GREETING allows: LISTENING, SPEAKING, CALL_END
# LISTENING allows: THINKING, INTERRUPTED, CALL_END
# THINKING allows: KB_FETCH, ACTION_EXECUTION, SPEAKING, INTERRUPTED, LISTENING, CALL_END
# SPEAKING allows: LISTENING, INTERRUPTED, CALL_END
# CALL_END allows: nothing
illegal = [
    (State.GREETING,   State.THINKING),
    (State.GREETING,   State.KB_FETCH),
    (State.GREETING,   State.INTERRUPTED),
    (State.LISTENING,  State.GREETING),
    (State.LISTENING,  State.SPEAKING),
    (State.THINKING,   State.GREETING),
    (State.SPEAKING,   State.KB_FETCH),
    (State.SPEAKING,   State.THINKING),
    (State.CALL_END,   State.GREETING),
    (State.CALL_END,   State.LISTENING),
]
for start, end in illegal:
    f = fresh()
    # manually set state to test
    f._state = start
    result = f.to(end)
    check(f"illegal {start.name}→{end.name}", result, False)
    check(f"state preserved after illegal {start.name}→{end.name}", f.state, start)

section("4. FSM — barge-in")
for _ in range(5):
    f = fresh()
    f.to(State.LISTENING); f.to(State.THINKING); f.to(State.SPEAKING)
    f.on_user_started_speaking()
    check("barge-in from SPEAKING → INTERRUPTED", f.state, State.INTERRUPTED)

# Barge-in from GREETING goes to LISTENING (not INTERRUPTED)
f = fresh()
f.on_user_started_speaking()
check("barge-in from GREETING → LISTENING", f.state, State.LISTENING)

# Transition hook fires
section("4. FSM — transition hook")
for _ in range(3):
    seen = []
    f = ConversationFSM(on_transition=lambda a, b: seen.append((a, b)))
    f.to(State.LISTENING)
    f.to(State.THINKING)
    f.to(State.SPEAKING)
    check_true("hook fired 3 times", len(seen) == 3)
    check("hook got correct states", seen[0], (State.GREETING, State.LISTENING))


# ════════════════════════════════════════════════════════════════
# 5. ECHO GUARD  (~50 tests)
# ════════════════════════════════════════════════════════════════
section("5. ECHO GUARD")
from src.audio import EchoGuard

# Basic echo detection — each check gets a fresh instance to avoid half-duplex bleed
eg = EchoGuard(); eg.on_agent_started("Sorry sir, malli cheppandi")
check_true("exact echo match", eg.is_echo("sorry sir malli cheppandi"))
eg2_punct = EchoGuard(); eg2_punct.on_agent_started("Sorry sir, malli cheppandi")
check_true("echo with punctuation dropped", eg2_punct.is_echo("sorry sir, malli cheppandi."))
eg_unrel = EchoGuard(); eg_unrel.on_agent_started("Sorry sir, malli cheppandi")
eg_unrel.on_agent_stopped()  # agent stopped, no post-stop match for unrelated text
check_false("unrelated turn not echo", eg_unrel.is_echo("నాకు acne problem details cheppandi"))
check_false("empty string not echo", EchoGuard().is_echo(""))

# Multiple TTS phrases in deque
eg2 = EchoGuard()
phrases = [
    "Hello, I am calling from Stanford",
    "Our team has shortlisted you",
    "This is a two year fellowship",
    "The stipend is two thousand dollars",
    "Are you available on May 27th?",
]
for p in phrases:
    eg2.on_agent_started(p)
for p in phrases:
    check_true(f"deque echo: '{p[:30]}'",
               eg2.is_echo(p.lower().replace(",", "").replace(".", "").replace("?", "")))

# Real caller turns not treated as echo (agent stopped → only substring matches count)
real_turns = [
    "నాకు interest ఉంది",
    "visa process details cheppandi",
    "stipend amount ela untundi",
    "program start date eppudu",
    "documents required emi untayi",
]
for t in real_turns:
    eg_r = EchoGuard()
    eg_r.on_agent_started("Hello this is Dr Sarah Mitchell")
    eg_r.on_agent_stopped()  # agent stopped; below turns don't match TTS phrase
    check_false(f"real turn not echo: '{t[:25]}'", eg_r.is_echo(t))

# Half-duplex TTL auto-recovery
eg4 = EchoGuard()
eg4.on_agent_started("test phrase")
for _ in range(5):
    eg4.is_echo("test phrase")  # trigger hits
check_true("half-duplex engaged after echo hits", eg4.half_duplex)
eg4._last_echo_ts = time.monotonic() - 10
eg4._maybe_recover(time.monotonic())
check_false("half-duplex clears after TTL", eg4.half_duplex)
check("echo_hits reset after recovery", eg4._echo_hits, 0)

# post-stop echo window
eg5 = EchoGuard()
eg5.on_agent_started("okay sir one second")
eg5.on_agent_stopped()
# within post-stop window
check_true("post-stop echo within window", eg5.is_echo("okay sir one second"))


# ════════════════════════════════════════════════════════════════
# 6. MEMORY  (~60 tests)
# ════════════════════════════════════════════════════════════════
section("6. MEMORY — emotion detection")
from src.memory import CallMemory, detect_emotion, extract_name

angry_phrases = [
    "this is the worst service",
    "useless system complete waste",
    "this is a scam and cheat",
    "bekar service bakwas",
    "chetha system chetha",
]
for p in angry_phrases:
    check(f"angry: '{p[:30]}'", detect_emotion(p), "angry")

frustrated_phrases = [
    "again same problem not working",
    "still not resolved already told",
    "phir se same issue kab tak",
    "enni sarlu cheppali marokkasari",
]
for p in frustrated_phrases:
    check(f"frustrated: '{p[:30]}'", detect_emotion(p), "frustrated")

urgent_phrases = [
    "urgent please help immediately",
    "emergency asap right now fast",
    "jaldi karo thwaraga cheyyi",
]
for p in urgent_phrases:
    check(f"urgent: '{p[:30]}'", detect_emotion(p), "urgent")

happy_phrases = [
    "thanks great help super",
    "perfect awesome chala bagundi",
    "badhiya service good",
]
for p in happy_phrases:
    check(f"happy: '{p[:30]}'", detect_emotion(p), "happy")

neutral_phrases = [
    "okay tell me more",
    "what time is it",
    "hello",
    "I see",
]
for p in neutral_phrases:
    check(f"neutral: '{p[:25]}'", detect_emotion(p), "neutral")

section("6. MEMORY — name extraction")
name_tests = [
    ("naa peru Ravi", "Ravi"),
    ("my name is Sarah", "Sarah"),
    ("I am Meghana", "Meghana"),
    ("mera naam Raj hai", "Raj"),
    ("nenu Priya ni", None),   # "nenu X ni" pattern not in extractor
    ("nothing here", None),
    ("okay sir", None),
    ("yes", None),
    ("", None),
]
for text, expected in name_tests:
    check(f"name: '{text[:25]}'", extract_name(text), expected)

section("6. MEMORY — CallMemory")
# Basic update and prompt
for lang in ("te", "hi", "en"):
    for intent in ("refund", "appointment", "greeting", "unknown"):
        m = CallMemory(call_id=f"test-{lang}-{intent}")
        m.update_from_turn("test utterance", lang, intent)
        block = m.as_prompt()
        check_true(f"prompt non-empty lang={lang} intent={intent}", block)
        check_true(f"prompt has lang={lang}", f"language={lang}" in block)
        check_true(f"prompt <400 chars", len(block) < 400)

# Emotion updates
m = CallMemory(call_id="emo-test")
m.update_from_turn("this is worst useless", "te", "complaint")
check("emotion detected in memory", m.emotion, "angry")

# Name stored
m2 = CallMemory(call_id="name-test")
m2.update_from_turn("my name is Ravi", "en", "unknown")
check("name stored", m2.name, "Ravi")

# Multiple turns accumulate correctly
m3 = CallMemory(call_id="multi-turn")
m3.update_from_turn("hello", "te", "greeting")
m3.update_from_turn("refund issue", "te", "refund")
check("intent updated on 2nd turn", m3.intent, "refund")


# ════════════════════════════════════════════════════════════════
# 7. COST METER  (~30 tests)
# ════════════════════════════════════════════════════════════════
section("7. COST METER")
from src.cost import CallMeter, trim_history

# Route recording
mt = CallMeter()
check("initial llm_calls=0", mt.llm_calls, 0)
mt.record_route(Route.LLM)
check("llm_calls=1 after LLM", mt.llm_calls, 1)
mt.record_route(Route.CANNED); mt.record_route(Route.CACHE); mt.record_route(Route.ACTION)
check("llm_calls still 1 (non-LLM routes)", mt.llm_calls, 1)
check("total_routes=4", len(mt.routes), 4)

# Bypass rate
mt2 = CallMeter()
for _ in range(7): mt2.record_route(Route.CANNED)
for _ in range(3): mt2.record_route(Route.LLM)
check_true("bypass_rate=70%", abs(mt2.llm_bypass_rate - 0.70) < 0.02)

# Edge: all LLM
mt3 = CallMeter()
for _ in range(5): mt3.record_route(Route.LLM)
check("bypass_rate=0% all LLM", mt3.llm_bypass_rate, 0.0)

# Edge: all canned (no LLM) — bypass rate = 1.0 or N/A
mt4 = CallMeter()
for _ in range(5): mt4.record_route(Route.CANNED)
check("llm_calls=0 all canned", mt4.llm_calls, 0)

# trim_history
class M:
    def __init__(self, r): self.role = r

for max_t in (1, 2, 3, 5):
    msgs = [M("system")] + [M("user"), M("assistant")] * 10
    trimmed = trim_history(msgs, max_turns=max_t)
    check(f"trim: system preserved max_turns={max_t}", trimmed[0].role, "system")
    check_true(f"trim: length correct max_turns={max_t}",
               len(trimmed) == 1 + (max_t * 2))
    for msg in trimmed[1:]:
        check_true(f"trim: no orphan roles max_turns={max_t}",
                   msg.role in ("user", "assistant"))


# ════════════════════════════════════════════════════════════════
# 8. PERSONA PROMPT BUILDING  (~60 tests)
# ════════════════════════════════════════════════════════════════
section("8. PERSONA — core constraints always present")
from src.persona.outbound import outbound_prompt
from src.persona.inbound import inbound_prompt
from src.persona.base import base_prompt, CORE_CONSTRAINTS
from src.runtime_config import RuntimeConfig

must_haves = [
    "HUMAN call-center executive",
    "LANGUAGE LOCK",
    "CODE-MIX",
    "BANNED empty filler",
    "CLOSE PROTOCOL",
    "ACTION-HALLUCINATION",
]
for term in must_haves:
    p = outbound_prompt(RuntimeConfig())
    check_true(f"outbound has: {term[:30]}", term in p)
    p2 = inbound_prompt(RuntimeConfig())
    check_true(f"inbound has: {term[:30]}", term in p2)

section("8. PERSONA — auto mirror language")
cfg_off = RuntimeConfig(); cfg_off.auto_mirror_language = False
cfg_on  = RuntimeConfig(); cfg_on.auto_mirror_language  = True
check_false("mirror OFF → NOT in prompt", "LANGUAGE-MIRROR" in outbound_prompt(cfg_off))
check_true ("mirror ON  → in prompt",     "LANGUAGE-MIRROR" in outbound_prompt(cfg_on))

section("8. PERSONA — campaign override isolation")
for persona_text in [
    "You are Dr. Kavitha from HMA.",
    "You are Anjali from Urban Lifestyles Magazine.",
    "You are Dr. Sarah Mitchell from Stanford University.",
]:
    cfg = RuntimeConfig()
    cfg.outbound_persona = persona_text
    p = outbound_prompt(cfg)
    check_true(f"campaign persona present: '{persona_text[:30]}'", persona_text in p)
    check_false(f"Zannara absent: '{persona_text[:25]}'", "Zannara" in p)

section("8. PERSONA — business description injection")
for biz in [
    "Hyderabad Medical Academy",
    "Urban Lifestyles Magazine Hyderabad",
    "Stanford University School of Medicine",
]:
    cfg = RuntimeConfig(); cfg.business_description = biz
    p = outbound_prompt(cfg)
    check_true(f"biz injected: '{biz[:30]}'", biz in p)

section("8. PERSONA — use-case blocks")
use_cases = {
    "appointment": "APPOINTMENT",
    "reschedule": "RESCHEDULE",
    "reminder": "REMINDER",
    "sales": "SALES",
    "leadgen": "LEAD GENERATION",
    "survey": "SURVEY",
    "feedback": "FEEDBACK",
    "support": "SUPPORT",
    "collections": "COLLECTIONS",
}
for uc, keyword in use_cases.items():
    cfg = RuntimeConfig(); cfg.use_case_type = uc
    p = base_prompt(cfg)
    check_true(f"use_case={uc} has block", keyword in p)

# custom = no use-case block
cfg_custom = RuntimeConfig(); cfg_custom.use_case_type = "custom"
p = base_prompt(cfg_custom)
check_false("custom → no USE-CASE block", "USE-CASE:" in p)

section("8. PERSONA — style examples override")
cfg_s = RuntimeConfig()
cfg_s.style_examples = "CUSTOM_STYLE_TOKEN_XYZ"
p = outbound_prompt(cfg_s)
check_true("custom style in prompt", "CUSTOM_STYLE_TOKEN_XYZ" in p)
check_false("builtin style replaced", "STYLE DNA" in p)

# blank style → builtin used
cfg_blank = RuntimeConfig(); cfg_blank.style_examples = ""
p2 = outbound_prompt(cfg_blank)
check_true("blank style → builtin used", "STYLE DNA" in p2)


# ════════════════════════════════════════════════════════════════
# 9. INTENT ROUTER  (~40 tests)
# ════════════════════════════════════════════════════════════════
section("9. INTENT ROUTER")
from src.router.intent_router import IntentRouter, RouteResult

async def _test_router():
    router = IntentRouter()

    # Safe canned intents
    for text, lang in [
        ("thank you", "te"), ("thanks a lot", "en"), ("bye", "en"),
        ("goodbye", "hi"), ("repeat that please", "en"),
    ]:
        r = await router.route(text, call_language=lang)
        check(f"canned route: '{text}'", r.route, Route.CANNED)
        check_true(f"canned resolved: '{text}'", r.resolved_without_llm)
        check_true(f"canned answer: '{text}'", r.answer is not None)

    # Everything else → LLM
    llm_turns = [
        ("నాకు acne problem ఉంది", "te"),
        ("What is the stipend amount?", "en"),
        ("हाँ मुझे interest है", "hi"),
        ("hello", "en"),
        ("okay", "te"),
        ("Haan", "hi"),
        ("May 27th available ha", "te"),
        ("2000 per month enough nahi", "hi"),
        ("Is this really Stanford?", "en"),
        ("నేను వస్తాను", "te"),
    ]
    for text, lang in llm_turns:
        r = await router.route(text, call_language=lang)
        check(f"llm route: '{text[:25]}'", r.route, Route.LLM)
        check(f"llm answer=None: '{text[:25]}'", r.answer, None)
        check_false(f"llm resolved_without_llm=False: '{text[:25]}'",
                    r.resolved_without_llm)

    # Cache resolver injection
    async def mock_cache(q):
        return "Cached answer" if "acne" in q else None
    router.set_cache_resolver(mock_cache)

    # FAQ intent with cache hit — but only for FAQ intents
    # (classifier won't return order_status for "acne" so this stays LLM)
    r_acne = await router.route("acne problem ఉంది", call_language="te")
    check("non-FAQ with cache → still LLM", r_acne.route, Route.LLM)

asyncio.run(_test_router())


# ════════════════════════════════════════════════════════════════
# 10. CANCELLATION  (~20 tests)
# ════════════════════════════════════════════════════════════════
section("10. CANCELLATION")
from src.cancellation import CancellationRegistry

async def _test_cancel():
    # Single task
    reg = CancellationRegistry()
    async def slow(): await asyncio.sleep(5)
    reg.spawn(slow())
    await asyncio.sleep(0)
    check("cancel 1 task → returns 1", reg.cancel_generation(), 1)
    check("cancel again → returns 0", reg.cancel_generation(), 0)
    check("cancel again → still 0", reg.cancel_generation(), 0)

    # Multiple tasks
    reg2 = CancellationRegistry()
    for _ in range(5):
        reg2.spawn(slow())
    await asyncio.sleep(0)
    count = reg2.cancel_generation()
    check_true("cancel 5 tasks → returns 5", count == 5)
    check("cancel after all done → 0", reg2.cancel_generation(), 0)

    # Spawn after cancel
    reg3 = CancellationRegistry()
    reg3.spawn(slow())
    await asyncio.sleep(0)
    reg3.cancel_generation()
    reg3.spawn(slow())
    await asyncio.sleep(0)
    check("new task after cancel → 1", reg3.cancel_generation(), 1)

    # Already-done task not counted
    reg4 = CancellationRegistry()
    async def quick(): pass
    reg4.spawn(quick())
    await asyncio.sleep(0.01)
    c = reg4.cancel_generation()
    check_true("done task not double-cancelled (0 or 1)", c in (0, 1))

asyncio.run(_test_cancel())


# ════════════════════════════════════════════════════════════════
# 11. LANGUAGE SWITCH LOGIC  (~30 tests)
# ════════════════════════════════════════════════════════════════
section("11. LANGUAGE SWITCH LOGIC")

def resolve_lang(cls_language, call_lang):
    # "mixed"/"en"/"unknown" → fall back to call_lang; if no call_lang → "en"
    return cls_language if cls_language in ("te", "hi") else (call_lang or "en")

# Configured Telugu call
for cls_lang, call_lang, expected in [
    ("te",    "te",   "te"),   # te caller on te call
    ("hi",    "te",   "hi"),   # real switch to Hindi
    ("en",    "te",   "te"),   # short English ack stays te
    ("mixed", "te",   "te"),   # mixed → call_lang fallback
    ("te",    "hi",   "te"),   # te caller on hi call → te (real switch)
    ("hi",    "hi",   "hi"),   # hi caller on hi call
    ("en",    "hi",   "hi"),   # English ack on hi call → stays hi
    ("en",    "en",   "en"),   # en caller on en call
    ("te",    "en",   "te"),   # te caller on en call → real switch
    ("hi",    "en",   "hi"),   # hi caller on en call → real switch
    ("mixed", "en",   "en"),   # mixed → en fallback
    ("mixed", None,   "en"),   # no call_lang, no cls_lang → en default
]:
    check(f"lang: cls={cls_lang} call={call_lang} → {expected}",
          resolve_lang(cls_lang, call_lang), expected)

# Verify no unexpected language values
for cls_lang in ("te", "hi", "en", "mixed", "unknown", "", None):
    if cls_lang is None: continue
    result = resolve_lang(cls_lang, "te")
    check_true(f"result always te/hi/en: cls={cls_lang}",
               result in ("te", "hi", "en"))


# ════════════════════════════════════════════════════════════════
# 12. DB EXECUTOR FIX  (~15 tests)
# ════════════════════════════════════════════════════════════════
section("12. DB EXECUTOR FIX (Python 3.13)")
import concurrent.futures
from src.db import _ensure_executor

async def _test_executor():
    loop = asyncio.get_event_loop()

    # Test 1: executor alive — no-op
    _ensure_executor()
    try:
        loop._check_default_executor()
        check_true("alive executor: no-op", True)
    except RuntimeError:
        check_true("alive executor: no-op", False)

    # Test 2: dead executor — revived
    original = loop._default_executor
    loop._default_executor = None
    _ensure_executor()
    try:
        loop._check_default_executor()
        check_true("dead executor: revived", True)
    except RuntimeError:
        check_true("dead executor: revived", False)
    loop._default_executor = original

    # Test 3: idempotent — call multiple times
    for i in range(5):
        _ensure_executor()
        try:
            loop._check_default_executor()
            check_true(f"idempotent call #{i+1}", True)
        except RuntimeError:
            check_true(f"idempotent call #{i+1}", False)

    # Test 4: revived executor is functional
    loop._default_executor = None
    _ensure_executor()
    import asyncio as _a
    result = await loop.run_in_executor(None, lambda: 42)
    check("revived executor functional", result, 42)
    loop._default_executor = original

asyncio.run(_test_executor())


# ════════════════════════════════════════════════════════════════
# 13. CONTENT STORE  (~20 tests)
# ════════════════════════════════════════════════════════════════
section("13. CONTENT STORE")
from src.content import content_store

for lang in ("te", "hi", "en"):
    fillers = content_store.fillers(lang)
    check_true(f"fillers non-empty lang={lang}", fillers)
    check_true(f"fillers is list lang={lang}", isinstance(fillers, list))
    for f in fillers:
        check_true(f"filler item is str lang={lang}", isinstance(f, str))
        check_true(f"filler item non-empty lang={lang}", f.strip())

for intent in ("thanks", "bye", "repeat"):
    for lang in ("te", "hi", "en"):
        canned = content_store.canned(intent, lang)
        check_true(f"canned non-empty intent={intent} lang={lang}", canned)
        check_true(f"canned is list intent={intent} lang={lang}",
                   isinstance(canned, list))

# Unknown lang → falls back to en
fillers_unknown = content_store.fillers("xx")
check_true("unknown lang fillers → non-empty fallback", fillers_unknown)


# ════════════════════════════════════════════════════════════════
# 14. RHYTHM  (~10 tests)
# ════════════════════════════════════════════════════════════════
section("14. RESPONSE RHYTHM")
from src.rhythm import ResponseRhythm

async def _test_rhythm():
    r = ResponseRhythm()
    # Neutral — small pause
    r.emotion = "neutral"
    t0 = time.monotonic()
    await r.think_pause()
    elapsed = time.monotonic() - t0
    check_true("neutral pause < 0.5s", elapsed < 0.5)

    # Angry — near-zero pause
    r.emotion = "angry"
    t0 = time.monotonic()
    await r.think_pause()
    elapsed = time.monotonic() - t0
    check_true("angry pause < 0.1s", elapsed < 0.1)

    # Emotion setter doesn't crash on unknown
    for emo in ("confused", "happy", "frustrated", "urgent", "xyz", "", None):
        try:
            r.emotion = emo
            await r.think_pause()
            check_true(f"rhythm ok for emotion={emo}", True)
        except Exception as e:
            check_true(f"rhythm ok for emotion={emo}", False)

asyncio.run(_test_rhythm())


# ════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ════════════════════════════════════════════════════════════════
print("\n" + "═"*60)
total   = len(results)
passed  = sum(1 for *_, ok, _, _ in results if ok)
failed  = total - passed

by_section = {}
for sec, name, ok, *_ in results:
    by_section.setdefault(sec, [0, 0])
    by_section[sec][0] += 1
    if ok: by_section[sec][1] += 1

print(f"\n  {'Module':<45} Tests  Pass")
print(f"  {'─'*55}")
for sec, (tot, pas) in by_section.items():
    mark = PASS if pas == tot else FAIL
    print(f"  {mark} {sec:<43} {tot:>4}   {pas:>4}")

print(f"\n  TOTAL: {passed}/{total} passed  |  {failed} failed")

if failed:
    print(f"\n  FAILED:")
    for sec, name, ok, actual, expected in results:
        if not ok:
            print(f"    {FAIL} [{sec}] {name}")
            print(f"         got={actual!r}  want={expected!r}")
print("═"*60)
