#!/usr/bin/env python3
"""Acceptance tests for the graph catalog (ADR 0019; ADR 0018 single-locus build graph).

The org's plugin declares a CATALOG of named graphs (`graphs:`). The build graph is one
persistent `builder` graph-agent that traverses its nodes — not a cast of agents. The
catalog is SHARED and target-neutral: both targets bind the same graphs. Each test below
holds one piece of that decision to a checkable claim:

  - the catalog validates and both targets emit the build graph's worker, `builder`;
  - a worker graph's total cap (max_total_steps) is REQUIRED — omit it and emit refuses;
  - the supplementary reviewer is the ONLY fresh-context validator: enabled → an
    agent/validate.md + a `validate` task allow + subagent_depth 2; disabled → none;
  - fail-closed model policy: a banned / off-provider model (org floor or the
    supplementary reviewer's pin) refuses to emit;
  - fail-closed read-only: the supplementary reviewer's read surface may not carry a
    write/delegate capability.

Run:  uv run --with pytest --with pyyaml pytest tests/test_graph_nodes.py -q
"""
import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with, ORG_FLOOR  # noqa: E402


def frontmatter(txt):
    return yaml.safe_load(txt.split("---", 2)[1])


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-graph-oc-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


def emit_cc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-graph-cc-")) / "out"
    emit.TARGETS["claude-code"](cfg, out)
    return out


def graph_cfg(**supp_overrides):
    """CFG (which already carries the ADR-0019 catalog). `supp_overrides` patch the
    top-level supplementary_reviewer block for the mutation battery; pass `_graph` to
    patch graphs.build itself, `_nodes` to patch a node."""
    graph_patch = supp_overrides.pop("_graph", None)
    node_patch = supp_overrides.pop("_nodes", None)

    def mut(c):
        if supp_overrides:
            c["supplementary_reviewer"].update(supp_overrides)
        if graph_patch:
            c["graphs"]["build"].update(graph_patch)
        if node_patch:
            for name, patch in node_patch.items():
                c["graphs"]["build"]["nodes"][name].update(patch)
    return cfg_with(mut)


def build_graph(bindings):
    return next(g for g in bindings["graphs"] if g["name"] == "build")


# --- the graph is shared, target-neutral, and validates -----------------------------

def test_the_catalog_is_a_shared_top_level_block_both_builders_read():
    """The catalog is bound by the SHARED build_bindings (used by BOTH targets), not a
    per-target block. Delete it and even the claude-code target refuses."""
    for builder in (emit.build_bindings, emit.build_bindings_opencode):
        b = builder(CFG)
        g = build_graph(b)
        assert g["agent"] == "builder" and g["entry"] == "understand", g
        assert g["max_total_steps"] == 400, g
        assert b["scalars"]["BUILD_AGENT"] == "builder", b["scalars"]["BUILD_AGENT"]
    c = cfg_with(lambda c: c.pop("graphs"))
    with pytest.raises(SystemExit):
        emit.build_bindings(c)


def test_a_happy_catalog_emits_both_targets():
    emit_oc(graph_cfg())
    emit_cc(graph_cfg())


def test_claude_code_emits_the_builder_agent_and_opencode_keeps_its_orchestrator():
    cc = emit_cc(graph_cfg())
    assert (cc / "agents" / "builder.md").is_file(), "claude-code emitted no builder agent"
    assert not (cc / "agents" / "build.md").exists(), "the retired `build` agent name survived"
    oc = emit_oc(graph_cfg())
    conf = json.loads((oc / "opencode.json").read_text())
    # the orchestrator is the host's primary, never the worker (ADR 0019 §4)
    assert conf["default_agent"] == "build", conf.get("default_agent")
    assert conf["permission"]["task"].get("build") == "allow", conf["permission"]["task"]


def test_the_review_node_is_a_rubric_node_of_the_one_agent():
    lines = "\n".join(i["line"] for i in emit.node_lines(build_graph(emit.build_bindings(CFG)),
                                                           "claude-code"))
    assert "**review**" in lines and "rubric `review`" in lines, lines


# --- a worker graph's total cap is REQUIRED (silence is fail-open) -----------------

def test_omitting_max_total_steps_refuses_on_both_targets():
    for target_emit in (emit_cc, emit_oc):
        with pytest.raises(SystemExit, match="max_total_steps"):
            target_emit(graph_cfg(_graph={"max_total_steps": None}))


def test_a_zero_or_negative_cap_refuses():
    with pytest.raises(SystemExit):
        emit_cc(graph_cfg(_graph={"max_total_steps": 0}))
    with pytest.raises(SystemExit, match="max_visits"):
        emit_cc(graph_cfg(_nodes={"review": {"max_visits": 0}}))


# --- the supplementary reviewer is the ONLY fresh-context validator ----------------

def test_supplementary_reviewer_enabled_emits_the_only_validator():
    out = emit_oc(graph_cfg())
    assert (out / "agent" / "validate.md").is_file(), "enabled reviewer emitted no validate.md"
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["permission"]["task"].get("validate") == "allow", conf["permission"]["task"]
    assert conf["subagent_depth"] >= 2, conf.get("subagent_depth")


def test_supplementary_reviewer_disabled_emits_no_validator():
    out = emit_oc(graph_cfg(enabled=False))
    assert not (out / "agent" / "validate.md").exists(), \
        "a disabled reviewer still emitted agent/validate.md"
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["permission"]["task"].get("validate") != "allow", conf["permission"]["task"]
    assert conf["permission"]["task"]["*"] == "deny", conf["permission"]["task"]
    assert conf["subagent_depth"] == 1, conf.get("subagent_depth")


def test_the_supplementary_reviewer_read_surface_must_be_read_only():
    with pytest.raises(SystemExit, match="write/delegate|read_surface"):
        emit_oc(graph_cfg(read_surface=["read", "edit"]))


def test_an_enabled_reviewer_without_fresh_context_does_not_emit():
    with pytest.raises(SystemExit, match="fresh_context"):
        emit_oc(graph_cfg(fresh_context=False))


# --- fail-closed model policy (definition time) ------------------------------------

def test_a_banned_org_floor_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(cfg_with(lambda c: c["opencode"]["model"].__setitem__(
            "model", "us.anthropic.claude-haiku-4-5")))


def test_a_banned_supplementary_reviewer_model_does_not_emit():
    with pytest.raises(SystemExit, match="banned"):
        emit_oc(graph_cfg(model="amazon-bedrock/us.anthropic.claude-haiku-4-5"))


def test_an_off_provider_supplementary_reviewer_model_does_not_emit():
    with pytest.raises(SystemExit, match="off-provider"):
        emit_oc(graph_cfg(model="anthropic/claude-sonnet-4-5"))


# --- model + effort are OPTIONAL and default to INHERIT (forge 0.8.1 / ADR 0017) ----

def _strip_all_model_and_effort(c):
    """Drop every model/effort pin: the builder's and the reviewer's."""
    for g in c["graphs"].values():
        g.pop("model", None)
        g.pop("effort", None)
    c["supplementary_reviewer"].pop("model", None)


def test_a_config_omitting_model_and_effort_everywhere_emits_and_inherits():
    """The whole point of 0.8.1: neither model nor effort is REQUIRED anywhere. A config
    that pins none of them emits on BOTH targets and the builder INHERITS — CC
    builder.md carries `model: inherit` and no effort line; the opencode reviewer inherits
    the orchestration model too."""
    cfg = cfg_with(_strip_all_model_and_effort)

    cc = emit_cc(cfg)
    fm = frontmatter((cc / "agents" / "builder.md").read_text())
    assert fm["model"] == "inherit", fm
    assert "effort" not in fm, f"an unset effort must drop the frontmatter line: {fm}"

    oc = emit_oc(cfg)
    conf = json.loads((oc / "opencode.json").read_text())
    assert conf["model"] == ORG_FLOOR, conf["model"]
    vfm = frontmatter((oc / "agent" / "validate.md").read_text())
    assert vfm["model"] == ORG_FLOOR, f"an unset reviewer model must inherit the floor: {vfm}"


def test_the_builder_pins_when_the_config_pins():
    """When the config DOES pin, the pin renders — model + the effort line both present."""
    cc = emit_cc(graph_cfg())  # CFG carries build model=sonnet, effort=high
    fm = frontmatter((cc / "agents" / "builder.md").read_text())
    assert fm["model"] == "sonnet" and fm["effort"] == "high", fm


def test_supplementary_reviewer_model_is_optional_and_inherits_orchestration():
    out = emit_oc(cfg_with(lambda c: c["supplementary_reviewer"].pop("model", None)))
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm["model"] == ORG_FLOOR, f"unset reviewer model must be the orchestration ref: {fm}"
