#!/usr/bin/env python3
"""The builder — the build graph's worker agent (ADR 0019 §4-5, both targets).

Each claim below is a load-bearing piece of the worker's contract:

  - it is its OWN identity: never the orchestrator's skill. The Claude Code builder
    preloads only its graph-index skill + its entry node's skill — never a verb skill
    (the execute verb's body says "you are the orchestrator");
  - its total cap is host-enforced: `maxTurns` equals the graph's max_total_steps;
  - its tool list is what the host actually exposes to a plugin subagent (dogfood
    2026-09-23: only Read, Edit, Write, Bash reached the worker) and never carries a
    fan-out tool (Agent, Skill);
  - it does NOT force `isolation` in its own frontmatter: from a multi-repo workspace
    root the WorktreeCreate hook cannot resolve the repo (the Agent tool always names the
    worktree `agent-worktree`), so the orchestrator decides isolation per dispatch;
  - it reads every other node file and rubric by `${CLAUDE_PLUGIN_ROOT}` path;
  - it ends EVERY run (pass, fail, blocked, capped) with the one shared RESULT line.

Run:  uv run --with pytest --with pyyaml pytest tests/test_builder_agent.py -q
"""
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def emit_cc(cfg=None):
    out = Path(tempfile.mkdtemp(prefix="emit-builder-cc-")) / "out"
    emit.TARGETS["claude-code"](cfg or CFG, out)
    return out


def split(md):
    _, fm, body = md.split("---", 2)
    return yaml.safe_load(fm), body


@pytest.fixture(scope="module")
def cc():
    return emit_cc()


def builder(out):
    return split((out / "agents" / "builder.md").read_text())


def test_builder_preloads_only_its_graph_index_and_entry_node(cc):
    fm, _ = builder(cc)
    assert fm["skills"] == ["build-graph", "build-understand"], fm.get("skills")


def test_builder_never_preloads_a_verb_skill(cc):
    fm, _ = builder(cc)
    verbs = set(emit.resolve_verbs(CFG).values())
    assert not set(fm["skills"]) & verbs, f"the builder preloads a verb skill: {fm['skills']}"


def test_builder_total_cap_is_the_host_maxturns(cc):
    fm, _ = builder(cc)
    assert fm.get("maxTurns") == CFG["graphs"]["build"]["max_total_steps"], fm


def test_builder_tools_are_what_the_host_exposes_and_cannot_fan_out(cc):
    fm, _ = builder(cc)
    tools = [t.strip() for t in fm["tools"].split(",")]
    assert tools == ["Read", "Edit", "Write", "Bash"], tools
    assert not {"Agent", "Skill", "Workflow", "Task"} & set(tools), tools


def test_builder_does_not_force_isolation_in_its_frontmatter(cc):
    fm, _ = builder(cc)
    assert "isolation" not in fm, \
        "frontmatter isolation fires the WorktreeCreate hook, which cannot resolve a repo " \
        "from a multi-repo workspace root (worktree_name is always 'agent-worktree')"


def test_builder_reads_rubrics_and_nodes_by_plugin_root_path(cc):
    idx = (cc / "skills" / "build-graph" / "SKILL.md").read_text()
    for rel in ("rubrics/review.md", "rubrics/gate.md", "skills/build-implement/SKILL.md",
                "skills/build-validate/SKILL.md", "skills/build-fix/SKILL.md"):
        assert f"${{CLAUDE_PLUGIN_ROOT}}/{rel}" in idx, f"index does not point at {rel}"
        assert (cc / rel).is_file(), f"{rel} is referenced but not emitted"


def test_graph_index_carries_the_node_walk_and_caps(cc):
    fm, body = split((cc / "skills" / "build-graph" / "SKILL.md").read_text())
    assert fm["name"] == "build-graph" and fm.get("user-invocable") is False, fm
    assert "disable-model-invocation" not in fm, "a preloaded skill must stay loadable"
    for node in ("understand", "build", "validate", "review", "fix", "clear"):
        assert f"**{node}**" in body, f"index lacks node {node}"
    assert "at most 4 visits" in body, "the review loop cap is not in the index"


def test_node_skills_are_worker_scoped_not_orchestrator_prose(cc):
    for s in ("build-understand", "build-implement", "build-validate", "build-fix"):
        fm, body = split((cc / "skills" / s / "SKILL.md").read_text())
        assert fm["name"] == s, fm
        assert "orchestrator" not in body.lower(), f"{s} carries orchestrator prose"


def test_builder_ends_every_path_with_the_shared_result_line(cc):
    _, body = builder(cc)
    assert emit.RESULT_LINE in body, "the builder does not carry the shared RESULT line"
    for status in ("PASS", "FAIL", "BLOCKED", "CAPPED"):
        assert f"**{status}**" in body, f"the builder does not define {status}"
    assert "every path" in body.lower(), "the RESULT line is not required on every path"


def test_builder_body_has_no_dead_depth_steering(cc):
    _, body = builder(cc)
    assert "Raise or lower your reasoning" not in body
    assert "skill / rubric / effort" not in body


def test_emit_refuses_a_builder_that_preloads_a_verb_skill(monkeypatch):
    """Call-site guard: the post-render contract check, not just the template."""
    real = emit.worker_preloads
    monkeypatch.setattr(emit, "worker_preloads",
                        lambda g, verbs: real(g, verbs) + [verbs["execute"]])
    with pytest.raises(SystemExit, match="preload"):
        emit_cc()


def test_emit_refuses_a_builder_without_the_host_cap(monkeypatch):
    real = emit.graph_bindings

    def no_cap(base, g, target):
        b = real(base, g, target)
        b["scalars"]["GRAPH_MAX_TOTAL_STEPS"] = "0"
        return b
    monkeypatch.setattr(emit, "graph_bindings", no_cap)
    with pytest.raises(SystemExit, match="maxTurns"):
        emit_cc()
