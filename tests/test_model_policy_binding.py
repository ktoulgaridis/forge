#!/usr/bin/env python3
"""Tests for the model_policy config binding in emit.build_bindings.

Run:  uv run --with pyyaml python tests/test_model_policy_binding.py

model_policy is an OPTIONAL, org-configurable block (the org's model floor).
emit must:
  - expose MODEL_POLICY_DEFAULT / MODEL_POLICY_BANNED / MODEL_POLICY_RULE scalars,
  - read them from cfg["model_policy"] when present,
  - supply sane NEUTRAL defaults when the block is absent (never required).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import emit  # noqa: E402

BASE = {
    "org": {"name": "Testco", "slug": "testco"},
    "plugin": {
        "name": "testco-harness", "version": "0.1.0", "description": "d",
        "author": {"name": "Testco Platform Engineering", "url": "https://github.com/testco"},
        "homepage": "https://github.com/testco/testco-harness", "license": "UNLICENSED",
    },
    "org_wiki": {
        "name": "testco-wiki", "remote": "git@github.com:testco/testco-wiki.git",
        "local_path_env": "TESTCO_WIKI", "default_local_path": "~/work/testco-wiki",
        "prime_reads": ["operating-model.md"],
    },
    "tracker": {"type": "jira", "config": {}},
    "agents": [
        {"name": "implementer", "model": "sonnet"},
        {"name": "reviewer", "model": "sonnet"},
        {"name": "gate", "model": "sonnet"},
    ],
}


def cfg_with(**over):
    import copy
    c = copy.deepcopy(BASE)
    c.update(over)
    return c


def test_present_block_is_read():
    c = cfg_with(model_policy={
        "banned": ["haiku"], "default": "opus",
        "rule": "Never Haiku. Always set model explicitly.",
    })
    s = emit.build_bindings(c)["scalars"]
    assert s["MODEL_POLICY_DEFAULT"] == "opus", s["MODEL_POLICY_DEFAULT"]
    assert s["MODEL_POLICY_BANNED"] == "haiku", s["MODEL_POLICY_BANNED"]
    assert s["MODEL_POLICY_RULE"] == "Never Haiku. Always set model explicitly.", s["MODEL_POLICY_RULE"]


def test_banned_list_renders_comma_joined():
    c = cfg_with(model_policy={"banned": ["haiku", "foo"], "default": "opus", "rule": "r"})
    s = emit.build_bindings(c)["scalars"]
    assert s["MODEL_POLICY_BANNED"] == "haiku, foo", s["MODEL_POLICY_BANNED"]


def test_absent_block_supplies_defaults():
    c = cfg_with()  # no model_policy
    s = emit.build_bindings(c)["scalars"]
    # defaults must exist (block is optional) and be neutral non-empty strings
    assert s["MODEL_POLICY_DEFAULT"], "MODEL_POLICY_DEFAULT default missing"
    assert s["MODEL_POLICY_BANNED"] != "" or s["MODEL_POLICY_BANNED"] == "", "key must exist"
    assert "MODEL_POLICY_BANNED" in s
    assert s["MODEL_POLICY_RULE"], "MODEL_POLICY_RULE default missing"


def test_scalars_are_strings():
    c = cfg_with(model_policy={"banned": ["haiku"], "default": "opus", "rule": "r"})
    s = emit.build_bindings(c)["scalars"]
    for k in ("MODEL_POLICY_DEFAULT", "MODEL_POLICY_BANNED", "MODEL_POLICY_RULE"):
        assert isinstance(s[k], str), f"{k} must be str, got {type(s[k])}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
