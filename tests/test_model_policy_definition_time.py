#!/usr/bin/env python3
"""Acceptance tests for definition-time cost-aware model policy (forge#28, step 6).

The glm-5.3 balance incident + the astra retention failure are the evidence:
a run with no explicit model inherits the host default, which can be a banned
model (haiku), an off-policy model, or one the host's retention mode rejects.
The policy must be load-bearing at DEFINITION time, not advisory:

  - the graph's nodes may pin a model per node (produce deep, validate at the
    org floor); a pinned model is validated against the org policy at EMIT time
    (off-provider or banned = does not emit);
  - the validating agent's frontmatter model is the node's pin when declared,
    else the org floor — never the host default;
  - dispatch's default (no explicit model arg) is the org floor, explicit —
    never the host default;
  - opencode.json's default model is validated against the banned list at emit
    time (a banned floor does not emit);
  - the policy is cost-aware: the org floor is the cheap sufficient model; a
    deeper pin is a deliberate per-node choice, validated at emit.

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
from test_graph_nodes import graph_cfg  # noqa: E402


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-modelpol-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


def frontmatter(txt):
    return yaml.safe_load(txt.split("---", 2)[1])


# --- per-node model pins, validated at emit -------------------------------------------

def test_a_node_may_pin_its_model():
    """The graph carries a per-node model pin: produce runs deep, validate at the
    org floor. The pin is process data, declared on the node."""
    cfg = graph_cfg()
    cfg["opencode"]["nodes"]["review"]["model"] = "amazon-bedrock/us.anthropic.claude-opus-4-8"
    out = emit_oc(cfg)
    # the validating agent's frontmatter carries the pin (the deepest validating pin
    # wins — a validating run never runs shallower than its deepest node)
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert "opus" in fm["model"], fm


def test_a_node_pin_off_provider_does_not_emit():
    cfg = graph_cfg()
    cfg["opencode"]["nodes"]["review"]["model"] = "gpt-5"  # no provider prefix = off-provider
    with pytest.raises(SystemExit):
        emit_oc(cfg)


def test_a_node_pin_on_the_banned_list_does_not_emit():
    cfg = graph_cfg()
    cfg["opencode"]["nodes"]["review"]["model"] = "us.anthropic.claude-haiku-4-5"
    with pytest.raises(SystemExit):
        emit_oc(cfg)


def test_a_node_pin_on_another_provider_does_not_emit():
    cfg = graph_cfg()
    cfg["opencode"]["nodes"]["review"]["model"] = "anthropic/claude-sonnet-4-5"
    with pytest.raises(SystemExit):
        emit_oc(cfg)


# --- the validating agent's model is never the host default -----------------------------

def test_the_validating_agent_model_is_the_org_floor_when_no_node_pins():
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm


# --- the org floor is validated at emit -------------------------------------------------

def test_a_banned_org_floor_does_not_emit():
    def m(c):
        c["opencode"]["model"]["model"] = "us.anthropic.claude-haiku-4-5"
    cfg = graph_cfg()
    cfg["opencode"]["model"]["model"] = "us.anthropic.claude-haiku-4-5"
    with pytest.raises(SystemExit):
        emit_oc(cfg)


# --- dispatch's default is the org floor, explicit --------------------------------------

def test_dispatch_defaults_to_the_org_floor_not_the_host_default():
    """forge#28 session finding: a dispatch child with no explicit model inherits the
    host default (which this host's retention mode rejects). Dispatch's default must
    be the org floor, explicit at session create — never absent."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "dispatch.js").read_text()
    # the default model ref is baked into the plugin and applied when args.model is unset
    assert "OC_DEFAULT_MODEL_REF" not in src  # the placeholder is resolved
    assert "us.anthropic.claude-sonnet-4-5-20250929-v1:0" in src, \
        "dispatch does not carry the org floor as its default model"
    import re
    assert re.search(r"DEFAULT_MODEL|defaultModel|FLOOR", src), \
        "dispatch has no named default-model constant"
