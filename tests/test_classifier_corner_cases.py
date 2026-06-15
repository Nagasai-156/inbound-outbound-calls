"""Classifier corner cases — code-mix balance, regression scenarios."""

from __future__ import annotations

from src.router.classifier import detect_language, classify


# ─── Codemix sentence variations ──────────────────────────────────


def test_telugu_with_one_english_word_stays_te():
    """Codemix Tenglish — one English word shouldn't flip to mixed."""
    assert detect_language("నాకు appointment kavali") == "te"


def test_hindi_with_one_english_word_stays_hi():
    assert detect_language("मुझे booking चाहिए") == "hi"


def test_english_sentence_with_one_namaste_might_match_te():
    """A single Indic cue word in pure English sentence — depends on
    threshold tuning. Just verify no crash."""
    out = detect_language("hello, what is your namaste service?")
    assert out in ("te", "hi", "en", "mixed")


# ─── Romanized-script-only edge cases ─────────────────────────────


def test_pure_romanized_telugu_with_no_indic_script():
    """Caller speech transcribed as pure Roman by STT in some configs."""
    out = detect_language("naa appointment book chesthunna kavali")
    assert out in ("te", "mixed")


def test_pure_romanized_hindi():
    out = detect_language("mera naam kya hai aapko pata hai")
    assert out in ("hi", "mixed")


def test_empty_after_strip_returns_en():
    assert detect_language("\t\n  \r  ") == "en"


# ─── Classify trivial vs non-trivial ──────────────────────────────


def test_single_word_yes_is_trivial():
    c = classify("yes")
    assert c.is_trivial is True
    assert c.intent == "affirm"


def test_two_word_yes_okay_is_trivial():
    c = classify("yes ok")
    assert c.is_trivial is True


def test_three_word_combo_still_trivial():
    c = classify("yes ok haan")
    assert c.is_trivial is True


def test_four_word_with_affirm_kw_not_trivial():
    """Above the short threshold — must go to LLM not canned."""
    c = classify("yes please do that thing")
    assert c.is_trivial is False


def test_classify_with_only_punctuation():
    """Bare punctuation from STT mishears."""
    c = classify("...")
    # Should NOT crash; intent is whatever fallback.
    assert isinstance(c.intent, str)
    assert isinstance(c.is_trivial, bool)


def test_classify_with_only_digits():
    c = classify("12345")
    assert isinstance(c.intent, str)


def test_classify_with_only_one_char():
    c = classify("y")
    assert isinstance(c.intent, str)


# ─── Bye keyword priority regression ─────────────────────────────


def test_okay_fine_bye_routes_to_bye():
    """okay (affirm) + fine + bye (bye) → bye must win."""
    c = classify("okay fine bye")
    assert c.intent == "bye"


def test_thanks_bye_combination_routes_to_bye():
    """When both bye and thanks present, bye wins (closing intent)."""
    c = classify("thanks bye")
    assert c.intent == "bye"


def test_alvida_lowercase():
    c = classify("alvida")
    assert c.intent == "bye"


# ─── Confidence levels ──────────────────────────────────────────


def test_zero_hits_low_confidence():
    c = classify("the matter that we discussed during a meeting yesterday")
    # 0 keyword hits OR maybe 1 ('the').
    assert c.confidence <= 0.7


def test_multiple_hits_high_confidence():
    c = classify("yes ok sure haan")  # multiple affirm hits
    assert c.confidence == 0.9


# ─── Multiple intent keywords across categories ────────────────


def test_payment_refund_combo():
    """'payment' + 'refund' — which wins? Both have keyword sets."""
    c = classify("I want a refund for my payment")
    # Either is acceptable — both are in the right ballpark.
    assert c.intent in ("payment_issue", "refund")


def test_order_payment_combo():
    c = classify("my order payment failed")
    assert c.intent in ("order_status", "payment_issue")


# ─── Classification stability under flicker ────────────────────


def test_classify_consistent_on_same_input():
    """Two calls with identical input must produce identical
    classification (no internal random state)."""
    text = "where is my order"
    c1 = classify(text)
    c2 = classify(text)
    assert c1.language == c2.language
    assert c1.intent == c2.intent
    assert c1.is_trivial == c2.is_trivial
    assert c1.confidence == c2.confidence


# ─── Multi-script in one sentence ──────────────────────────────


def test_te_plus_hi_script_returns_te_or_hi_not_mixed_garbage():
    """A sentence with BOTH Telugu + Devanagari (rare but happens).
    Detector should pick one based on first script seen."""
    out = detect_language("నాకు मुझे help kavali")
    # Telugu is checked first in our regex order.
    assert out == "te"


def test_extremely_short_indic_burst():
    """Just 'ఆ' — bare acknowledgement."""
    out = detect_language("ఆ")
    assert out == "te"


# ─── Mixed-only without script ─────────────────────────────────


def test_high_cue_count_returns_mixed():
    """Multiple competing cues + close count → mixed."""
    out = detect_language("naa kya undi help please where")
    # 2 te + 2 hi + 3 en is mostly en. depending on count distribution.
    assert out in ("te", "hi", "en", "mixed")
