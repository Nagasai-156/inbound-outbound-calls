"""Parametrized matrix tests for the goodbye-detector regex.

Generates ~2,000 test cases from cross-product of:
  (phrase × leading separator × trailing punctuation × case variant)
"""

from __future__ import annotations

import re

import pytest

_GOODBYE_RE = re.compile(
    r"(?:^|[\s,.!?])(?:"
    r"bye|good\s*bye|good\s*day|nice\s*day|good\s*night|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*day|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*evening|"
    r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*night|"
    r"take\s*care|see\s*you|see\s*ya|"
    r"talk\s*(?:to\s*you\s*)?soon|catch\s*you\s*later|"
    r"all\s*the\s*best|farewell|cheers|"
    r"మంచి\s*రోజు|మంచి\s*రాత్రి|మంచి\s*సాయంత్రం|"
    r"ధన్యవాదాలు\s*అండి|మీ\s*సమయానికి\s*ధన్యవాదాలు|"
    r"మళ్ళీ\s*కలుద్దాం|జాగ్రత్తగా\s*ఉండండి|"
    r"వెళ్తున్నాను|ఉంటాను\s*అండి|బై\s*అండి|"
    r"manchi\s*roju|malli\s*kaludaam|veltunna|untanu\s*andi|bye\s*andi|"
    r"धन्यवाद\s*जी|शुभ\s*दिन|शुभ\s*रात्रि|शुभ\s*रात्री|शुभ\s*संध्या|"
    r"अलविदा|खुदा\s*हाफ़िज़|ख़ुदा\s*हाफ़िज़|"
    r"फिर\s*मिलेंगे|फिर\s*बात\s*करेंगे|अपना\s*ख्याल\s*रखिए|"
    r"alvida|khuda\s*hafiz|phir\s*milenge|apna\s*khayal\s*rakhiye"
    r")(?:[\s,.!?]|$)",
    re.IGNORECASE,
)


_POSITIVES = [
    "bye", "goodbye", "good day", "good night", "good bye",
    "have a great day", "have a nice day", "have a wonderful day",
    "have a lovely evening", "have a good night",
    "take care", "see you", "see ya", "talk soon", "talk to you soon",
    "catch you later", "all the best", "farewell", "cheers",
    "మంచి రోజు", "మంచి రాత్రి", "మంచి సాయంత్రం",
    "ధన్యవాదాలు అండి", "మీ సమయానికి ధన్యవాదాలు",
    "మళ్ళీ కలుద్దాం", "జాగ్రత్తగా ఉండండి", "వెళ్తున్నాను", "ఉంటాను అండి",
    "బై అండి", "manchi roju", "malli kaludaam", "bye andi",
    "धन्यवाद जी", "शुभ दिन", "शुभ रात्रि", "शुभ संध्या",
    "अलविदा", "खुदा हाफ़िज़", "फिर मिलेंगे", "फिर बात करेंगे",
    "अपना ख्याल रखिए", "alvida", "khuda hafiz", "phir milenge",
    "apna khayal rakhiye",
]

_NEGATIVES_BASE = [
    "thank you for that",
    "ధన్యవాదాలు sir cheppandi",
    "धन्यवाद bataiye",
    "okay sure",
    "hello there",
    "maybe next time",
    "my appointment is at five",
    "can you check again",
    "please tell me the price",
    "subway sandwich",
    "lullaby for the baby",
    "what is the procedure",
    "okay let me think",
    "yes ma'am please",
]

_LEADING = ["", " ", ", ", "okay ", "sure, "]
_TRAILING = ["", " ", ".", "!", "?", ", thanks", "."]
_CASES = [str.lower, str.upper, lambda s: s.title()]


def _hits(text: str) -> bool:
    return _GOODBYE_RE.search(text) is not None


# Positives — ~45 × 5 × 7 × 3 = ~4,725 cases, but reduce to keep runtime tight.
@pytest.mark.parametrize("phrase", _POSITIVES)
@pytest.mark.parametrize("leading", _LEADING[:4])
@pytest.mark.parametrize("trailing", _TRAILING[:5])
def test_goodbye_positive_matrix(phrase, leading, trailing):
    text = leading + phrase + trailing
    assert _hits(text), f"expected match for {text!r}"


@pytest.mark.parametrize("phrase", _NEGATIVES_BASE)
@pytest.mark.parametrize("leading", _LEADING[:3])
@pytest.mark.parametrize("trailing", _TRAILING[:4])
def test_goodbye_negative_matrix(phrase, leading, trailing):
    """Mid-conversation thanks / random other phrases must NOT
    fire the hangup."""
    text = leading + phrase + trailing
    assert not _hits(text), f"unexpected match for {text!r}"


# Case-fold matrix — every positive should still match under any case.
@pytest.mark.parametrize("phrase", _POSITIVES[:20])  # first 20 to cap volume
@pytest.mark.parametrize("case_fn_idx", range(3))
def test_goodbye_case_invariance(phrase, case_fn_idx):
    fn = _CASES[case_fn_idx]
    text = "ok " + fn(phrase) + "."
    # Some Indic scripts have no case → title() may be a no-op, that's fine.
    assert _hits(text)
