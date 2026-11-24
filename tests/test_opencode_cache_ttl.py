#!/usr/bin/env python3
"""opencode.cache_ttl (optional) asks the provider for a longer prompt-cache lifetime.

opencode >= 2.3 reads `providers.<id>.settings.cache.ttl` and sends it on each cache
marker. Unset, the emitted opencode.json carries no `providers` key, so the provider's
default lifetime applies.

Run:  uv run --with pytest --with pyyaml pytest tests/test_opencode_cache_ttl.py -q
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
from test_opencode_emit import cfg_with, emit_target  # noqa: E402


def conf(mutate=None):
    return json.loads((emit_target("opencode", cfg_with(mutate)) / "opencode.json").read_text())


def test_cache_ttl_lands_on_the_configured_provider():
    c = conf(lambda c: c["opencode"].__setitem__("cache_ttl", "1h"))
    assert c["providers"] == {"amazon-bedrock": {"settings": {"cache": {"ttl": "1h"}}}}


def test_unset_emits_no_providers_key():
    assert "providers" not in conf()


def test_cache_ttl_must_be_a_duration():
    try:
        conf(lambda c: c["opencode"].__setitem__("cache_ttl", "an hour"))
    except SystemExit:
        return
    raise AssertionError("a non-duration cache_ttl was accepted")
