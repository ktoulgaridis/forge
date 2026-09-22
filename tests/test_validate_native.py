#!/usr/bin/env python3
"""The OPTIONAL supplementary reviewer (ADR 0018 §5), on the opencode target.

Under ADR 0018 the build graph is ONE `build` graph-agent that traverses build →
validate → review (self-check) → fix → clear in a single context. The review node is a
self-check of that one agent, NOT a separately-spawned validator. The ONE surviving
fresh-context validator is the *optional* supplementary reviewer: dispatched on a
COMPLETED PR for a high-risk diff, never inside the build loop.

On opencode that reviewer is realized as `agent/validate.md` — a `subagent`-mode agent,
read-only by its own frontmatter (the native subagent tool derives the child session's
permissions from it), pinned to a definition-time model — and the org config's `task`
rule allowlists exactly the spawnable set (`build` + `validate`). It is emitted ONLY when
`graph.supplementary_reviewer.enabled` is true.

Run:  uv run --with pytest --with pyyaml pytest tests/test_validate_native.py -q
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


# --- the supplementary reviewer agent file (when enabled) ---------------------------

def test_the_supplementary_reviewer_file_is_emitted_when_enabled():
    out = emit_oc(graph_cfg())
    assert (out / "agent" / "validate.md").is_file(), \
        "agent/validate.md — the optional supplementary reviewer — was not emitted"


def test_it_is_a_subagent_pinned_at_its_configured_model_and_cap():
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm.get("mode") == "subagent", fm
    # definition-time model pin — the supplementary_reviewer.model in the graph block
    assert fm.get("model") == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm
    assert fm.get("steps") == 40, fm


def test_it_carries_the_read_only_contract():
    """The deny set derives from the reviewer's read_surface; bash is an allowlist of the
    tracker's + git's read commands, never a blanket deny — a reviewer that cannot read
    the ticket wanders instead of judging."""
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    perm = fm["permission"]
    for cap in ("edit", "task", "dispatch", "webfetch", "websearch"):
        assert perm.get(cap) == "deny", f"validate does not deny {cap}: {perm}"
    bash = perm["bash"]
    assert isinstance(bash, dict) and bash.get("*") == "deny", f"bash is not an allowlist: {bash}"
    keys = list(bash)
    allowed = [p for p, a in bash.items() if a == "allow"]
    assert allowed, "validate allows no read-only commands — it cannot read the ticket"
    for tail in ("*>*", "*--output*"):
        assert bash.get(tail) == "deny", f"validate lacks the {tail!r} deny: {bash}"
        assert keys.index(tail) > max(keys.index(p) for p in allowed), \
            f"{tail!r} deny must follow the allows (last match wins)"
    assert not any(p.startswith("gh api") for p in allowed), \
        "validate allows `gh api` — -X POST/PUT/DELETE is a full write path"


def test_it_denies_dispatch_so_it_cannot_launder_a_write():
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm["permission"].get("dispatch") == "deny", fm["permission"]


def test_its_body_carries_the_fresh_context_read_only_completed_pr_contract():
    out = emit_oc(graph_cfg())
    body = (out / "agent" / "validate.md").read_text().split("---", 2)[2].lower()
    for needle in ("read-only", "fresh context", "verdict", "deficienc", "completed"):
        assert needle in body, f"validate.md body does not carry {needle!r}"
    assert "self-check" in body, "validate.md body does not distinguish itself from the build agent's self-check"


def test_it_resolves_no_placeholders():
    out = emit_oc(graph_cfg())
    assert "{{" not in (out / "agent" / "validate.md").read_text()


# --- the task allowlist (the org config's task permission rule) ---------------------

def test_opencode_json_allowlists_exactly_the_spawnable_set_when_enabled():
    out = emit_oc(graph_cfg())
    task = json.loads((out / "opencode.json").read_text())["permission"]["task"]
    assert task.get("*") == "deny", task
    assert task.get("build") == "allow" and task.get("validate") == "allow", task
    assert sorted(k for k, v in task.items() if v == "allow") == ["build", "validate"], task


def test_the_allowlist_tracks_the_configured_primary_agent():
    cfg = cfg_with(lambda c: c["opencode"].__setitem__("primary_agent", "main"))
    task = json.loads((emit_oc(cfg) / "opencode.json").read_text())["permission"]["task"]
    assert task.get("main") == "allow" and "build" not in task, task
    assert task.get("validate") == "allow", task


# --- disabled: no fresh-context validator at all ------------------------------------

def test_disabled_reviewer_emits_no_agent_and_no_allow():
    out = emit_oc(graph_cfg(enabled=False))
    assert not (out / "agent" / "validate.md").exists(), \
        "a disabled supplementary reviewer still emitted agent/validate.md"
    task = json.loads((out / "opencode.json").read_text())["permission"]["task"]
    assert task["*"] == "deny" and task.get("build") == "allow", task
    assert task.get("validate") != "allow", task


# --- the skills route to the reviewer correctly -------------------------------------

def test_execute_dispatches_the_build_graph_agent_and_supplementary_review_is_completed_pr_only():
    out = emit_oc(graph_cfg())
    ex = (out / "skill" / "execute" / "SKILL.md").read_text()
    oc_section = ex.split("### 5.")[1] if "### 5." in ex else ex
    # ADR 0018: dispatch launches ONE build graph-agent per task (not a node/role)
    assert "dispatch({ agent:" in oc_section, \
        "execute no longer launches the build graph-agent via dispatch({ agent: ... })"
    assert 'node: "produce"' not in oc_section and 'node: "validate"' not in oc_section, \
        "execute still uses the retired node-kind dispatch shape"
    # the in-loop review is a self-check, not a dispatched validate node
    assert "self-check" in oc_section, "execute does not frame in-loop review as a self-check node"
    # the supplementary reviewer (subagent_type: validate) is the COMPLETED-PR exception
    assert "subagent_type" in oc_section and '"validate"' in oc_section, \
        "execute does not name the optional supplementary reviewer (subagent_type: validate)"


def test_refine_agent_ready_gate_is_an_orchestrator_check_not_a_dispatched_validator():
    out = emit_oc(graph_cfg())
    rf = (out / "skill" / "refine" / "SKILL.md").read_text()
    assert "agent-ready" in rf, "refine lost its agent-ready gate"
    assert "subagent_type" not in rf, \
        "refine still dispatches a validate subagent — the agent-ready gate is an orchestrator check (ADR 0018)"


# --- fail-closed graph-lint survives -----------------------------------------------

def test_a_reviewer_with_a_write_capability_still_does_not_emit():
    with pytest.raises(SystemExit):
        emit_oc(graph_cfg(read_surface=["read", "edit"]))
