#!/usr/bin/env python3
"""The opencode worker agents and their launcher (ADR 0019 §4-5, opencode target).

  - each worker graph emits its OWN agent file (agent/<agent>.md) — the orchestrator
    (opencode.json default_agent) and a worker never share a definition;
  - the worker's cap is host-enforced (`steps` = max_total_steps) and it cannot fan out
    or ask the human (dispatch / subagent / task / question denied);
  - opencode ships the rubrics (rubric/) and the graph's node skills (skill/);
  - `dispatch` launches ONLY declared workers, each with its declared isolation
    (worktree | none — none runs in place: no worktree, no repo);
  - the <run-closed> postback carries the worker's RESULT line, not its first line;
  - a `variant` is never dropped silently: refused without a model (the launcher pins no
    floor), and refused on 1.x (whose prompt body cannot carry it);
  - AGENTS.md (loaded into EVERY session, workers included) no longer tells a worker it
    is the orchestrator.

Run:  uv run --with pytest --with pyyaml pytest tests/test_opencode_worker.py -q
"""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG  # noqa: E402
from test_opencode_dispatch import (  # noqa: E402
    HOSTS, dispatch, emit_oc, workspace, creates, create_dir, postbacks, postback_text,
    result_text,
)

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node required")


def split(md):
    _, fm, body = md.split("---", 2)
    return yaml.safe_load(fm), body


@pytest.fixture(scope="module")
def oc():
    return emit_oc()


def test_each_worker_graph_emits_its_own_agent_file(oc):
    assert (oc / "agent" / "builder.md").is_file(), "no opencode worker agent for `build`"
    conf = json.loads((oc / "opencode.json").read_text())
    assert conf["default_agent"] != "builder", "the orchestrator IS the worker"
    assert conf["permission"]["task"].get("builder") != "allow", \
        "a worker spawned through the native task tool lands in the orchestrator's location"


def test_the_worker_is_capped_and_cannot_fan_out_or_ask(oc):
    fm, _ = split((oc / "agent" / "builder.md").read_text())
    assert fm["steps"] == CFG["graphs"]["build"]["max_total_steps"], fm
    for cap in ("dispatch", "subagent", "task", "question"):
        assert fm["permission"].get(cap) == "deny", (cap, fm["permission"])
    assert fm.get("mode") == "primary" and fm.get("hidden") is True, fm
    assert "model" not in fm, "the opencode worker inherits the org floor (opencode.model)"


def test_the_worker_body_carries_the_walk_paths_and_result_line(oc):
    _, body = split((oc / "agent" / "builder.md").read_text())
    assert emit.RESULT_LINE in body
    for rel in ("rubric/review.md", "rubric/gate.md", "skill/build-understand/SKILL.md"):
        assert rel in body, f"the worker body does not point at {rel}"
    assert "CLAUDE_PLUGIN_ROOT" not in body, "a Claude Code path leaked into opencode"


def test_opencode_ships_the_rubrics_and_node_skills(oc):
    for rel in ("rubric/review.md", "rubric/gate.md", "skill/build-graph/SKILL.md",
                "skill/build-understand/SKILL.md", "skill/build-implement/SKILL.md",
                "skill/build-validate/SKILL.md", "skill/build-fix/SKILL.md"):
        assert (oc / rel).is_file(), f"opencode did not ship {rel}"


def test_dispatch_declares_exactly_the_worker_table(oc):
    src = (oc / "plugin" / "dispatch.js").read_text()
    m = re.search(r"^const WORKERS = (\{.*\})$", src, re.M)
    assert m, "dispatch.js carries no WORKERS table"
    assert json.loads(m.group(1)) == {"builder": {"isolation": "worktree"}}, m.group(1)


def test_emit_refuses_an_opencode_worker_without_the_host_cap(monkeypatch):
    real = emit.graph_bindings

    def no_cap(base, g, target):
        b = real(base, g, target)
        b["scalars"]["GRAPH_MAX_TOTAL_STEPS"] = "7"
        return b
    monkeypatch.setattr(emit, "graph_bindings", no_cap)
    with pytest.raises(SystemExit, match="steps"):
        emit_oc()


def test_emit_refuses_a_dispatch_table_that_drifts_from_the_catalog(monkeypatch):
    real = emit.build_bindings_opencode

    def drift(cfg):
        b = real(cfg)
        b["scalars"]["OC_WORKERS_JSON"] = json.dumps({"builder": {"isolation": "none"}})
        return b
    monkeypatch.setattr(emit, "build_bindings_opencode", drift)
    with pytest.raises(SystemExit, match="WORKERS"):
        emit_oc()


def test_a_read_only_worker_derives_a_hard_deny_set():
    g = {"tools": "read_only", "allow": ["git log *", "mcp__o11y__query", "Read"]}
    perm = emit.oc_worker_permission(g)
    assert perm["deny"] >= {"dispatch", "subagent", "task", "question", "edit",
                            "webfetch", "websearch"}, perm
    assert perm["bash"] == ["git log *"], perm
    w = emit.oc_worker_permission({"tools": "write", "allow": []})
    assert w["deny"] == {"dispatch", "subagent", "task", "question"} and w["bash"] is None, w


def test_agents_md_does_not_tell_a_worker_it_is_the_orchestrator(oc):
    txt = (oc / "AGENTS.md").read_text()
    assert "You are the **orchestrator**" not in txt
    assert "dispatched worker" in txt and "never dispatch" in txt, txt
    assert "skill/rubric/effort" not in txt


# --- the launcher -----------------------------------------------------------------------

@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_dispatch_refuses_an_undeclared_agent_and_creates_nothing(host):
    out, ws = emit_oc(), workspace()
    for agent in ("build", "general", "plan", "nonesuch"):
        r = dispatch(out, ws, agent=agent, repo="api", ticket="TST-60", host=host)
        assert creates(r, host) == [], (agent, r)
        assert "builder" in result_text(r["result"], host), r
    assert not (ws / ".worktrees").exists() or not any((ws / ".worktrees").iterdir())


def _with_in_place_worker(out):
    """Declare an in-place worker in the emitted launcher (its body template is later
    work; the launcher's isolation table is what is under test here)."""
    f = out / "plugin" / "dispatch.js"
    src = f.read_text()
    src = re.sub(r"^const WORKERS = .*$",
                 'const WORKERS = {"builder": {"isolation": "worktree"}, '
                 '"triager": {"isolation": "none"}}', src, flags=re.M)
    f.write_text(src)
    return out


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_an_isolation_none_worker_runs_in_place_with_no_worktree(host):
    out, ws = _with_in_place_worker(emit_oc()), workspace()
    r = dispatch(out, ws, agent="triager", ticket="TST-61", host=host)
    assert len(creates(r, host)) == 1, r
    assert create_dir(creates(r, host)[0], host) == str(ws), creates(r, host)
    wt = ws / ".worktrees"
    assert not wt.exists() or not [p for p in wt.iterdir() if p.is_dir()], list(wt.iterdir())


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_the_postback_carries_the_result_line(host):
    out, ws = emit_oc(), workspace()
    line = ("RESULT: PASS | task=TST-62 | pr=https://x/pr/9 | branch=TST-62@abc1234 | "
            "tests=pytest -q -> 10/0 | note=ok")
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-62", host=host,
                 env={"HARNESS_TEXT": f"Opened the PR.\nAll green.\n{line}"})
    pb = postbacks(r, host)
    assert pb, r
    assert f"<result>{line}</result>" in postback_text(pb[-1], host), postback_text(pb[-1], host)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_a_variant_without_a_model_is_refused_not_dropped(host):
    """The launcher pins no floor of its own (ADR 0017: the floor lives in the user's
    opencode config), so a variant with no model has nothing to ride on."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-63", variant="high",
                 host=host)
    assert creates(r, host) == [], r
    assert "variant" in result_text(r["result"], host), r


@needs_node
def test_a_variant_is_refused_on_1x_where_it_would_be_dropped():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-64", variant="high",
                 host="v1")
    assert creates(r, "v1") == [], r
    assert "variant" in result_text(r["result"], "v1"), r
