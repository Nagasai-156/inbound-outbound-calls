"""Dynamic content store: defaults fallback + runtime override.

The hot path must never call the LLM; it reads pools from the store.
Offline these come from built-in defaults; with Redis populated by
scripts/gen_content.py they're overlaid. Both paths verified here
network-free.
"""

from src.content import (
    DEFAULT_CANNED,
    DEFAULT_FILLERS,
    ContentStore,
    content_store,
)
from src.router.canned import canned_response
from src.router.classifier import classify
from src.filler import pick_filler


def _flat(lang: str) -> list[str]:
    return [t for pool in DEFAULT_FILLERS[lang].values() for t in pool]


def test_defaults_cover_all_langs():
    for lang in ("te", "hi", "en"):
        assert DEFAULT_FILLERS[lang]["ack"]
        assert DEFAULT_FILLERS[lang]["checking"]
    for intent, pools in DEFAULT_CANNED.items():
        for lang in ("te", "hi", "en"):
            assert pools[lang], f"{intent}/{lang} empty"


def test_store_falls_back_to_defaults_without_redis():
    s = ContentStore()
    assert s.fillers("hi") == _flat("hi")
    assert s.fillers("hi", "ack") == DEFAULT_FILLERS["hi"]["ack"]
    assert s.fillers("hi", "checking") == DEFAULT_FILLERS["hi"]["checking"]
    assert s.canned("greeting", "te") == DEFAULT_CANNED["greeting"]["te"]
    assert s.canned("nonexistent", "en") is None
    # mixed/unknown language degrades to English
    assert s.fillers("xx") == _flat("en")
    # code-mixed varieties fall back to their corresponding base languages
    assert s.fillers("te-mix") == _flat("te")
    assert s.fillers("hi-mix") == _flat("hi")


def test_runtime_override_is_used():
    s = ContentStore()
    s._fillers["en"] = {"ack": ["Custom one...", "Custom two..."]}
    assert set(s.fillers("en")) == {"Custom one...", "Custom two..."}
    # an unknown kind degrades to the ack pool, never empty
    assert s.fillers("en", "checking") == ["Custom one...", "Custom two..."]


def test_filler_and_canned_use_the_store():
    # filler always non-empty + drawn from the store's pool
    assert pick_filler("en") in content_store.fillers("en")
    assert pick_filler("te-mix") in content_store.fillers("te")
    assert pick_filler("hi-mix") in content_store.fillers("hi")
    # canned fires only for SAFE intents (thanks/bye/repeat) and uses
    # the store; greetings now go to the persona LLM (stay on-script).
    assert canned_response(classify("hello")) is None
    pool = content_store.canned("thanks", "en")
    assert pool, "thanks/en pool must exist"
    assert canned_response(classify("thank you"), "en") in pool
    assert canned_response(classify("thank you"), "te-mix") in DEFAULT_CANNED["thanks"]["te"]
