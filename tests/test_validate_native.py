#!/usr/bin/env python3
"""Acceptance tests for the Path B engine split (forge#28, step 2).

The maintainer ruled Path B on #28: the node kind decides the engine.

  - **Validate nodes (review/gate/ad-hoc) → the native subagent tool.** One
    contract-carrying validating agent file (`agent/validate.md`): mode
    `subagent`, the read-only deny set in its own frontmatter (the native tool
    derives the child session's permissions from the spawned agent's own block —
    deterministic, no rule-stomping machinery of ours), the org's model floor
    pinned in frontmatter (definition-time — the astra retention failure is the
    evidence: a run with no explicit model inherits the host default, which this
    host's retention mode rejects). The org config's `task` permission rule
    allowlists exactly the spawnable set (`build` + `validate`) — anything else
    is denied, so a typo'd subagent_type can never fall back to the
    full-permission primary agent.
  - **Produce nodes → dispatch, shrunk to the writer grant.** The native path
    cannot relocate a child (the subagent tool never passes a directory), so the
    per-(repo, ticket) worktree stays dispatch's. Dispatch no longer carries
    ticketed validate runs at all — a ticketed `validate` dispatch is refused
    and routed to the native tool. Ad-hoc read-only delegations stay on
    dispatch (the delegation store is ours).

Each test below holds one piece of that split to a checkable claim.

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
from test_graph_nodes import graph_cfg  # noqa: E402


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-pathb-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


def frontmatter(txt):
    return yaml.safe_load(txt.split("---", 2)[1])


# --- the contract-carrying validating agent file -------------------------------------

def test_the_validating_agent_file_is_emitted():
    out = emit_oc(graph_cfg())
    assert (out / "agent" / "validate.md").is_file(), \
        "agent/validate.md — the ONE validating agent file — was not emitted"


def test_the_validating_agent_is_a_subagent_at_the_org_floor():
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    assert fm.get("mode") == "subagent", fm
    # definition-time model pin: the org floor, explicit — never the host default
    assert fm.get("model") == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm
    # the shallowest validating cap in the graph (review 40, gate 25 → 25)
    assert fm.get("steps") == 25, fm


def test_the_validating_agent_carries_the_graphs_read_only_contract():
    """The deny set derives from the union of the graph's read surfaces — the same
    set dispatch applied at session create in step 1, now the agent's own
    frontmatter (the native tool derives the child session's permissions from it).
    bash is an allowlist of the tracker's + git's read commands, never a blanket
    deny — a validating node that cannot read its ticket wanders instead of
    judging."""
    out = emit_oc(graph_cfg())
    fm = frontmatter((out / "agent" / "validate.md").read_text())
    perm = fm["permission"]
    for cap in ("edit", "dispatch", "webfetch", "websearch"):
        assert perm.get(cap) == "deny", f"validate does not deny {cap}: {perm}"
    bash = perm["bash"]
    assert isinstance(bash, dict) and bash.get("*") == "deny", f"bash is not an allowlist: {bash}"
    keys = list(bash)
    allowed = [p for p, a in bash.items() if a == "allow"]
    assert allowed, "validate allows no read-only commands — it cannot read the ticket"
    # opencode matches the WHOLE command text and the LAST matching rule wins: an
    # allowed read followed by `> file` or `--output file` would write, so the
    # trailing denies must come after the allows.
    for tail in ("*>*", "*--output*"):
        assert bash.get(tail) == "deny", f"validate lacks the {tail!r} deny: {bash}"
        assert keys.index(tail) > max(keys.index(p) for p in allowed), \
            f"{tail!r} deny must follow the allows (last match wins)"
    assert not any(p.startswith("gh api") for p in allowed), \
        "validate allows `gh api` — -X POST/PUT/DELETE is a full write path"


def test_the_validating_agent_body_carries_the_node_contract():
    """The body instructs the general agent standing on a validating node: fresh
    context, read-only by construction, verdict-shaped output, the tracker reads
    it may use. The contract rides the agent file — there is no persona cast."""
    out = emit_oc(graph_cfg())
    body = (out / "agent" / "validate.md").read_text().split("---", 2)[2]
    for needle in ("read-only", "fresh context", "verdict", "deficienc"):
        assert needle in body.lower(), f"validate.md body does not carry {needle!r}"


# --- the subagent allowlist (the org config's task permission rule) -------------------

def test_opencode_json_allowlists_exactly_the_spawnable_set():
    """`task` becomes an ALLOWLIST: the primary agent (build) and the validating
    agent (validate) are spawnable; everything else is denied. Without this a
    typo'd subagent_type resolves to no agent and the native tool's error is the
    only guard — and a hand-added agent file would be silently spawnable."""
    out = emit_oc(graph_cfg())
    conf = json.loads((out / "opencode.json").read_text())
    task = conf["permission"]["task"]
    assert isinstance(task, dict), f"task must be an allowlist object, got {task!r}"
    assert task.get("*") == "deny", task
    assert task.get("build") == "allow", task
    assert task.get("validate") == "allow", task
    # exactly those two — no more
    assert sorted(k for k, v in task.items() if v == "allow") == ["build", "validate"], task


def test_the_allowlist_tracks_the_configured_primary_agent():
    def m(c):
        c["opencode"]["primary_agent"] = "main"
    out = emit_oc(graph_cfg())
    # the mutation must apply to the CFG the graph builder derived from
    cfg = cfg_with(lambda c: c["opencode"].__setitem__("primary_agent", "main"))
    cfg["opencode"]["nodes"] = graph_cfg()["opencode"]["nodes"]
    out = emit_oc(cfg)
    conf = json.loads((out / "opencode.json").read_text())
    task = conf["permission"]["task"]
    assert task.get("main") == "allow" and "build" not in task, task


# --- dispatch shrinks to the writer grant ---------------------------------------------

def test_dispatch_refuses_a_ticketed_validate_run_and_routes_to_the_native_tool():
    """Path B: validate runs go through the native subagent tool (parentID at
    create — native tree visibility the public API cannot give dispatch
    children). Dispatch keeps ONLY what is genuinely ours: the writer worktree
    grant (produce) and the ad-hoc delegation store."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "dispatch.js").read_text()
    assert '"validate"' in src, "dispatch lost the validate node kind"
    # the refusal must name the native path so the orchestrator can self-correct
    assert "subagent" in src.lower(), \
        "the ticketed-validate refusal does not route to the native subagent tool"


def test_dispatch_applies_no_session_permissions_at_all():
    """ADR 0017: dispatch is a thin, agent-agnostic launcher — the read-only boundary for
    validating nodes lives entirely in the validating agent's own frontmatter (the native
    subagent tool derives from it). Dispatch no longer creates any read-only session, so it
    carries NO permission-deny machinery (the retired ADHOC_DENY / READ_ONLY_TOOLS) and no
    node-kind branching (`ticketed`/`produce`/`validate`)."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "dispatch.js").read_text()
    for gone in ("ADHOC_DENY", "READ_ONLY_TOOLS", "NODE_KINDS", 'kind: "ticketed"', 'kind === "ticketed"'):
        assert gone not in src, f"dispatch still carries the retired {gone!r}"
    # the validating boundary is the agent file's, not dispatch's
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    assert fm["permission"].get("edit") == "deny", fm["permission"]


# --- the skills route validate to the native tool --------------------------------------

def test_execute_routes_validate_nodes_to_the_native_subagent_tool():
    out = emit_oc(graph_cfg())
    ex = (out / "skill" / "execute" / "SKILL.md").read_text()
    oc_section = ex.split("### 5.")[1] if "### 5." in ex else ex
    assert "subagent_type" in oc_section, \
        "execute's opencode fan-out section does not name the native tool's subagent_type"
    assert '"validate"' in oc_section, \
        "execute's opencode fan-out section does not name the validating agent"
    assert 'node: "validate"' not in oc_section, \
        "execute still routes ticketed validate runs through dispatch"
    # ADR 0017: dispatch launches a WRITER by naming its graph-agent (`agent:`), not a node
    assert "dispatch({ agent:" in oc_section, \
        "execute no longer launches writer workers via dispatch({ agent: ... })"
    assert 'node: "produce"' not in oc_section, \
        "execute still uses the retired node-kind dispatch shape"


def test_refine_routes_the_agent_ready_gate_to_the_native_subagent_tool():
    out = emit_oc(graph_cfg())
    rf = (out / "skill" / "refine" / "SKILL.md").read_text()
    assert "subagent_type" in rf, \
        "refine's agent-ready gate does not name the native tool's subagent_type"


# --- fail-closed: the graph-lint survives the split ------------------------------------

def test_a_validating_node_with_no_read_surface_still_does_not_emit():
    cfg = graph_cfg(review={"read_surface": []})
    with pytest.raises(SystemExit):
        emit_oc(cfg)


def test_the_emitted_validate_agent_resolves_no_placeholders():
    out = emit_oc(graph_cfg())
    txt = (out / "agent" / "validate.md").read_text()
    assert "{{" not in txt, "unresolved placeholder in agent/validate.md"
