#!/usr/bin/env python3
"""Definition-time, cost-aware model policy on the opencode target (ADR 0018).

The glm-5.3 balance incident + the astra retention failure are the evidence: a run with
no explicit model inherits the host default, which can be banned (haiku), off-policy, or
retention-rejected. The policy must be load-bearing at DEFINITION time, not advisory:

  - the org floor (opencode.model) is validated at emit — a banned/off-provider floor
    does not emit;
  - the OPTIONAL supplementary reviewer pins its model in the graph block; that pin is
    validated on-provider + off-banned at emit, and becomes the emitted agent's
    frontmatter model (never the host default);
  - dispatch pins NO hardcoded default — an unset model is omitted so the graph-agent's
    own default (the org floor, which lives in opencode.json) governs.

Run:  uv run --with pytest --with pyyaml pytest tests/test_model_policy_definition_time.py -q
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402
from test_graph_nodes import graph_cfg, emit_oc  # noqa: E402


def frontmatter(txt):
    return yaml.safe_load(txt.split("---", 2)[1])


# --- the supplementary reviewer's model pin, validated at emit ----------------------

def test_the_reviewer_pins_its_configured_model_at_definition_time():
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm


def test_a_reviewer_model_can_be_a_deeper_pin():
    out = emit_oc(graph_cfg(model="amazon-bedrock/us.anthropic.claude-opus-4-8"))
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert "opus" in fm["model"], fm


def test_a_reviewer_model_off_provider_does_not_emit():
    with pytest.raises(SystemExit, match="off-provider"):
        emit_oc(graph_cfg(model="gpt-5"))  # no provider prefix = off-provider


def test_a_reviewer_model_on_the_banned_list_does_not_emit():
    with pytest.raises(SystemExit, match="banned"):
        emit_oc(graph_cfg(model="amazon-bedrock/us.anthropic.claude-haiku-4-5"))


def test_a_reviewer_model_on_another_provider_does_not_emit():
    with pytest.raises(SystemExit, match="off-provider"):
        emit_oc(graph_cfg(model="anthropic/claude-sonnet-4-5"))


# --- when the reviewer is disabled, its (dropped) frontmatter defaults to the floor --

def test_a_disabled_reviewer_needs_no_model_pin_and_still_emits():
    out = emit_oc(graph_cfg(enabled=False))
    # no reviewer file at all — nothing to pin
    assert not (out / "agent" / "validate.md").exists()
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", conf


# --- the org floor is validated at emit ---------------------------------------------

def test_a_banned_org_floor_does_not_emit():
    cfg = cfg_with(lambda c: c["opencode"]["model"].__setitem__(
        "model", "us.anthropic.claude-haiku-4-5"))
    with pytest.raises(SystemExit):
        emit_oc(cfg)


# --- dispatch's default is the org floor, explicit — never a baked constant ----------

def test_dispatch_pins_no_hardcoded_default_and_the_floor_lives_in_config():
    """ADR 0017 model-floor decision: the launcher keeps the provider+banned GUARD but
    pins NO hardcoded default model. An unset model is OMITTED, so the worker inherits
    the graph-agent's own default — the org floor, which lives in opencode.json's
    `model`, NOT in a dispatch constant (a baked floor would silently drift)."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "dispatch.js").read_text()
    assert "OC_DEFAULT_MODEL_REF" not in src
    assert "DEFAULT_MODEL" not in src, "dispatch still bakes a hardcoded default-model constant"
    assert "us.anthropic.claude-sonnet-4-5-20250929-v1:0" not in src, \
        "dispatch hardcodes the org floor instead of omitting an unset model"
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", conf
