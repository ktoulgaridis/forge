#!/usr/bin/env python3
"""Definition-time walls for the triage verb (ADR 0019 §1, §3, §8; TEC-4095).

  - the `triage` verb launches a READ-ONLY WORKER: a writer, or a main-thread walk, bound
    to it does not emit (the triage graph drafts and never writes);
  - a read_only graph's `allow` may not grant a write/exec tool by name — on Claude Code
    a named tool is granted verbatim (Edit, Write, NotebookEdit, Bash), and on opencode
    `edit` in allow would lift the edit deny. Either would make "read_only" a label.

Run:  uv run --with pytest --with pyyaml pytest tests/test_triage_guards.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import cfg_with  # noqa: E402


def triage_graph(**over):
    g = {"agent": "triager", "verb": "triage", "launch": "worker", "isolation": "none",
         "tools": "read_only", "max_total_steps": 150, "allow": ["mcp__o11y__query"],
         "entry": "intake",
         "nodes": {"intake": {"skill": "build-understand", "next": "diagnose"},
                   "diagnose": {"rubric": "review", "max_visits": 3,
                                "next": ["intake", "report"]},
                   "report": {"skill": "build-validate", "terminal": "drafts_returned"}}}
    g.update(over)
    return g


def bindings(**over):
    return emit.build_bindings(cfg_with(lambda c: c["graphs"].__setitem__(
        "triage", triage_graph(**over))))


def test_a_read_only_triage_worker_validates():
    t = next(g for g in bindings()["graphs"] if g["name"] == "triage")
    assert t["tools"] == "read_only" and t["launch"] == "worker", t


def test_a_triage_verb_bound_to_a_writer_refuses():
    with pytest.raises(SystemExit, match=r"triage.*read_only"):
        bindings(tools="write")


def test_a_triage_verb_bound_to_a_main_thread_graph_refuses():
    g = triage_graph(launch="main_thread")
    g.pop("agent")
    with pytest.raises(SystemExit, match=r"triage.*worker"):
        emit.build_bindings(cfg_with(lambda c: c["graphs"].__setitem__("triage", g)))


@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit", "MultiEdit", "Bash",
                                  "edit", "write", "patch", "bash"])
def test_a_read_only_allow_that_grants_a_write_tool_refuses(tool):
    with pytest.raises(SystemExit, match=r"read_only.*allow.*write/exec"):
        bindings(allow=["mcp__o11y__query", tool])


def test_a_read_only_allow_of_reads_and_shell_patterns_validates():
    bindings(allow=["Grep", "Glob", "mcp__o11y__query", "git log *"])


def test_a_write_graph_may_still_name_write_tools():
    emit.build_bindings(cfg_with(lambda c: c["graphs"]["build"].__setitem__(
        "allow", ["Edit", "Bash"])))
