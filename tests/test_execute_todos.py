#!/usr/bin/env python3
"""Native todos as the orchestrator's wave walk (ADR 0018).

The orchestrator renders the wave as native todowrite items — one per `build`
graph-agent run (per task) — session-local progress the engineer can watch; the
tracker stays the durable envelope — todos never replace it. The optional
supplementary reviewer (a single fresh-context run) keeps the native todowrite deny
(it has no walk of its own).

Each test below holds one piece to a checkable claim:

  - the execute skill instructs the orchestrator to render the wave as native todos
    (todowrite) and to keep it current as runs close;
  - the same skill states the boundary: todos are session-local progress; the
    tracker stays the bus (durable state never lives in the todo list);
  - the supplementary reviewer's frontmatter keeps todowrite denied;
  - the primary agent is NOT denied todowrite (the orchestrator's walk is the point).

Run:  uv run --with pytest --with pyyaml pytest tests/test_execute_todos.py -q
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
from test_graph_nodes import graph_cfg  # noqa: E402
import emit  # noqa: E402


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-todos-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


def test_execute_renders_the_node_walk_as_native_todos():
    out = emit_oc(graph_cfg())
    ex = (out / "skill" / "execute" / "SKILL.md").read_text()
    assert "todowrite" in ex, "execute never names the native todowrite tool"
    # the walk is the decomposition's nodes — each task's produce/validate runs
    assert re_search_todo_walk(ex), \
        "execute does not render the node walk as todos (one item per node run)"


def re_search_todo_walk(text):
    import re
    return re.search(r"todo", text, re.I) and re.search(r"node|task|run", text, re.I)


def test_execute_states_todos_are_progress_the_tracker_is_the_bus():
    out = emit_oc(graph_cfg())
    ex = (out / "skill" / "execute" / "SKILL.md").read_text()
    # the boundary must be explicit: todos never replace the tracker
    import re
    sec = ex[re.search(r"todo", ex, re.I).start():]
    assert re.search(r"tracker", sec, re.I), \
        "the todo guidance does not state that the tracker stays the durable bus"
    assert re.search(r"session-local|session.local|ephemeral|never replace", sec, re.I), \
        "the todo guidance does not state todos are session-local progress only"


def test_the_supplementary_reviewer_keeps_todowrite_denied():
    """The supplementary reviewer is a single fresh-context run with no walk to track —
    it carries no todowrite allow, so the native tool's own default-deny applies."""
    out = emit_oc(graph_cfg())
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    perm = fm["permission"]
    assert perm.get("todowrite") != "allow", \
        f"the supplementary reviewer must not write todos: {perm}"


def test_the_primary_agent_is_not_denied_todowrite():
    """The orchestrator's node walk IS the todo list — the primary agent must keep
    todowrite available (no deny in opencode.json)."""
    out = emit_oc(graph_cfg())
    conf = json.loads((out / "opencode.json").read_text())
    perm = conf.get("permission", {})
    assert perm.get("todowrite") != "deny", \
        f"the primary agent is denied todowrite — the node walk has nowhere to live: {perm}"
