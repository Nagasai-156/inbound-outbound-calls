"""end_call goodbye-guard regex tests.

The agent occasionally emits a goodbye line without firing the end_call
tool — calls then dangle forever. The code-level guard detects terminal
goodbye markers and fires _hangup as a fallback. These tests pin the
regex against a wide corpus of positives (must match → call ends) and
negatives (must NOT match → mid-conversation thanks etc.).
"""

from __future__ import annotations

import re

# Inline-copy of the regex from agent.py. If the agent code changes,
# update both. (Pure-function so worth duplicating to keep tests
# import-free of the heavy agent module.)
_GOODBYE_RE = re.compile(
    r"(?:^|[\s,.!?])(?:"
    # Group A: unambiguous closers (loose trailing boundary)
    r"(?:bye|good\s*bye|good\s*day|nice\s*day|good\s*night|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*day|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*evening|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*night|"
    r"farewell|"
    r"మంచి\s*రోజు|మంచి\s*రాత్రి|మంచి\s*సాయంత్రం|"
    r"ధన్యవాదాలు\s*అండి|మీ\s*సమయానికి\s*ధన్యవాదాలు|"
    r"మళ్ళీ\s*కలుద్దాం|జాగ్రత్తగా\s*ఉండండి|"
    r"వెళ్తున్నాను|ఉంటాను\s*అండి|బై\s*అండి|"
    r"manchi\s*roju|malli\s*kaludaam|veltunna|untanu\s*andi|bye\s*andi|"
    r"धन्यवाद\s*जी|शुभ\s*दिन|शुभ\s*रात्रि|शुभ\s*रात्री|शुभ\s*संध्या|"
    r"अलविदा|खुदा\s*हाफ़िज़|ख़ुदा\s*हाफ़िज़|"
    r"फिर\s*मिलेंगे|फिर\s*बात\s*करेंगे|अपना\s*ख्याल\s*रखिए|"
    r"alvida|khuda\s*hafiz|phir\s*milenge|apna\s*khayal\s*rakhiye)"
    r"(?:[\s,.!?]|$)"
    # Group B: ambiguous phrases — only at a sentence end
    r"|(?:take\s*care|see\s*you|see\s*ya|all\s*the\s*best|cheers|"
    r"talk\s*(?:to\s*you\s*)?soon|catch\s*you\s*later)"
    r"(?:\s*[.!?]|\s*$)"
    r")",
    re.IGNORECASE,
)


def _hits(text: str) -> bool:
    return _GOODBYE_RE.search(text) is not None


def test_english_goodbyes_match():
    for s in [
        "bye",
        "Goodbye!",
        "Have a great day.",
        "Have a nice evening",
        "Take care.",
        "See you, bye.",
        "See ya",
        "Talk soon",
        "Catch you later.",
        "All the best!",
        "farewell",
        "cheers",
        "Okay, good night.",
    ]:
        assert _hits(s), f"expected match for {s!r}"


def test_telugu_goodbyes_match():
    for s in [
        "మంచి రోజు అండి",
        "మంచి రాత్రి",
        "మంచి సాయంత్రం అండి",
        "ధన్యవాదాలు అండి, మంచి రోజు.",
        "మీ సమయానికి ధన్యవాదాలు అండి",
        "మళ్ళీ కలుద్దాం",
        "జాగ్రత్తగా ఉండండి అండి",
        "వెళ్తున్నాను",
        "ఉంటాను అండి",
        "బై అండి",
        "manchi roju andi",
        "malli kaludaam",
        "bye andi",
    ]:
        assert _hits(s), f"expected match for {s!r}"


def test_hindi_urdu_goodbyes_match():
    for s in [
        "धन्यवाद जी, शुभ दिन",
        "शुभ रात्रि",
        "अलविदा जी",
        "खुदा हाफ़िज़",
        "फिर मिलेंगे",
        "अपना ख्याल रखिए",
        "alvida ji",
        "khuda hafiz",
        "phir milenge",
    ]:
        assert _hits(s), f"expected match for {s!r}"


def test_mid_conversation_thanks_does_not_match():
    # "thank you" and bare-language thanks must NOT fire the hangup —
    # callers say these mid-conversation all the time.
    for s in [
        "thank you for the info",
        "ధన్యవాదాలు, చెప్పండి",
        "धन्यवाद, बताइए",
        "okay",
        "hello there",
        "sare andi, cheppandi",
        "మీ appointment confirm chestam",
        "sure, that works",
    ]:
        assert not _hits(s), f"unexpected match for {s!r}"


def test_trailing_punctuation_does_not_break_match():
    # The regex requires word-boundary handling — make sure "bye." and
    # "bye!" still match the same way as bare "bye".
    for s in ["Okay, bye.", "Okay, bye!", "okay bye?", " bye  "]:
        assert _hits(s), f"expected match for {s!r}"


def test_word_boundary_avoids_false_match_inside_other_words():
    # "Maybe" contains "bye" but must NOT match.
    for s in ["maybe later", "Maybe not", "embedybe"]:
        assert not _hits(s), f"unexpected match for {s!r}"


def test_mid_sentence_ambiguous_phrases_do_not_hang_up():
    # The #1 fix: ambiguous closers used mid-sentence (followed by a
    # continuing word) must NOT fire the fallback hangup. These are
    # normal reassurances/confirmations, not call closers.
    for s in [
        "I'll take care of that for you",
        "don't worry, we'll take care of it",
        "see you tomorrow at the clinic",
        "see you can book it online too",
        "all the best for your exam, and let me know",
        "cheers to that, now about your booking",
        "let's talk soon about the pricing details",
        "I'll catch you later in the day to confirm",
    ]:
        assert not _hits(s), f"unexpected mid-sentence match for {s!r}"


def test_ambiguous_phrases_still_match_as_closers():
    # ...but the SAME phrases as actual closers (sentence end) still end
    # the call, so we don't regress the documented goodbye behaviour.
    for s in [
        "Take care.",
        "See ya",
        "All the best!",
        "cheers",
        "Talk soon",
        "Catch you later.",
        "okay, take care",
    ]:
        assert _hits(s), f"expected closer match for {s!r}"
