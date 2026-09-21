#!/usr/bin/env python3
"""Acceptance tests for the graph-not-agents emit (forge#28, ADR 0001 + Path B).

The cast dies; the graph is the contract. Each test holds one piece of the
rework to a checkable claim:

  - node contracts are graph data: `opencode.nodes` declares the validating
    nodes (review/gate) with kind, fresh-context, read surface, cap, model;
  - fail-closed graph-lint at emit: a validating node with no read-only
    contract does not emit; a review node without fresh-context does not
    emit; a node with no declared cap does not emit;
  - the cast is gone from the artifact: no agent/ role files, no per-role
    permission derivation, no filename-as-contract machinery;
  - dispatch re-keys: the role table becomes node kinds (produce/validate);
    validate runs carry the node contract at session create; produce runs
    keep the worktree grant;
  - the native path: opencode.json raises subagent_depth so a workflow agent
    (depth 1) can spawn its review-node subagent (depth 2).

Run:  uv run --with pytest --with pyyaml pytest tests/test_graph_nodes.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-graph-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


# --- the graph as data ------------------------------------------------------------

GRAPH = {
    "nodes": {
        "review": {
            "kind": "validate",
            "fresh_context": True,
            "read_surface": ["read", "grep", "glob"],
            "max_steps": 40,
        },
        "gate": {
            "kind": "validate",
            "fresh_context": True,
            "read_surface": ["read", "grep", "glob"],
            "max_steps": 25,
        },
    },
}


def graph_cfg(**node_overrides):
    """CFG with the graph declared; per-node overrides for the mutation battery."""
    nodes = {k: dict(v) for k, v in GRAPH["nodes"].items()}
    for name, patch in node_overrides.items():
        nodes[name].update(patch)
    return cfg_with(lambda c: c.setdefault("opencode", {}).__setitem__("nodes", nodes))


# --- fail-closed graph-lint --------------------------------------------------------

def test_a_validating_node_with_no_read_surface_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(review={"read_surface": []}))


def test_a_validating_node_with_a_write_capability_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(review={"read_surface": ["read", "edit"]}))


def test_a_review_node_without_fresh_context_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(review={"fresh_context": False}))


def test_a_node_with_no_declared_cap_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(gate={"max_steps": None}))


def test_a_node_with_an_unknown_kind_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(review={"kind": "persona"}))


def test_a_happy_graph_emits():
    emit_oc(graph_cfg())


# --- the cast is gone --------------------------------------------------------------

def test_no_agent_role_files_are_emitted(cfg=None):
    out = emit_oc(cfg or graph_cfg())
    agents = sorted(p.name for p in (out / "agent").glob("*.md")) if (out / "agent").is_dir() else []
    assert not any(n in agents for n in ("implementer.md", "reviewer.md", "gate.md", "clearance.md")), agents


def test_the_subagents_block_is_no_longer_required():
    # The cast config (opencode.subagents) is dead — a config without it must emit.
    cfg = graph_cfg()
    cfg.get("opencode", {}).pop("subagents", None)
    emit_oc(cfg)


# --- dispatch re-keys to node kinds -------------------------------------------------

def test_dispatch_knows_node_kinds_not_roles():
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "dispatch.js").read_text()
    assert '"produce"' in src and '"validate"' in src
    assert '"implementer"' not in src.replace("implementer.md", "")


def test_opencode_json_raises_subagent_depth():
    import json
    out = emit_oc(graph_cfg())
    cfg = json.loads((out / "opencode.json").read_text())
    assert cfg.get("subagent_depth", 1) >= 2, cfg
