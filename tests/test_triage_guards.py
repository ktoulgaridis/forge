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
         "mcp_servers": {"o11y": {"claude-code": "plugin_o11y_o11y", "opencode": "o11y"}},
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


# --- the MCP wall: exact, org-configured denies ------------------------------------------
# forge knows no MCP server's tool names: which tools a worker may never call (a write
# tool, an environment-switching tool) is the org's `deny`, per handle. Emit adds none.

SERVERS = {"o11y": {"claude-code": "plugin_o11y_o11y", "opencode": "o11y"},
           "zd": {"claude-code": "plugin_zd_zd", "opencode": "zd"}}
ENV_DENY = ["mcp__o11y__set_environment", "mcp__zd__set_environment"]


def triage_of(b):
    return next(g for g in b["graphs"] if g["name"] == "triage")


def test_with_no_configured_deny_emit_invents_no_tool_deny():
    for target in ("claude-code", "opencode"):
        t = triage_of(emit.build_bindings(cfg_with(lambda c: c["graphs"].__setitem__(
            "triage", triage_graph(mcp_servers=SERVERS))), target))
        assert t["deny"] == [], (target, t["deny"])
        assert emit.cc_worker_tools(t)[1] == ["Edit", "Write", "NotebookEdit"], target
        assert not [r for r in emit.oc_worker_permission(t)["mcp"]
                    if "set_environment" in r[0]], target


def test_a_configured_deny_resolves_per_host_and_is_emitted_last():
    cfg = cfg_with(lambda c: c["graphs"].__setitem__(
        "triage", triage_graph(mcp_servers=SERVERS, deny=list(ENV_DENY))))
    cc = triage_of(emit.build_bindings(cfg, "claude-code"))
    want = ["mcp__plugin_o11y_o11y__set_environment", "mcp__plugin_zd_zd__set_environment"]
    assert cc["deny"] == want, cc["deny"]
    assert emit.cc_worker_tools(cc)[1][-2:] == want
    oc = triage_of(emit.build_bindings(cfg, "opencode"))
    assert emit.oc_worker_permission(oc)["mcp"][-2:] == [
        ("o11y_set_environment", "deny"), ("zd_set_environment", "deny")]


def test_a_tool_both_allowed_and_denied_refuses():
    with pytest.raises(SystemExit, match=r"both allow.*deny"):
        bindings(allow=["mcp__o11y__query", "mcp__o11y__set_environment"],
                 deny=["mcp__o11y__set_environment"])


def test_deny_takes_only_mcp_tool_names():
    with pytest.raises(SystemExit, match=r"deny.*MCP tool"):
        bindings(deny=["Edit"])


def test_a_read_only_mcp_allow_on_an_undeclared_server_refuses():
    with pytest.raises(SystemExit, match=r"undeclared.*mcp_servers"):
        bindings(allow=["mcp__other__query"])


def test_an_mcp_allow_on_an_undeclared_server_refuses_on_a_write_graph_too():
    """No handle, no per-host name: a writer's MCP names must resolve as well."""
    with pytest.raises(SystemExit, match=r"undeclared.*mcp_servers"):
        emit.build_bindings(cfg_with(lambda c: c["graphs"]["build"].__setitem__(
            "allow", ["mcp__other__query"])))


def test_the_opencode_permission_denies_by_default_then_allows_then_denies():
    """TEC-4097: the catch-all (every MCP tool of ANY server, plus 2.x's ungated
    `opencode_*` session tools) comes first, then each declared server's default deny, then
    the exact read allowlist; the exact deny list comes last."""
    g = {"tools": "read_only", "mcp_servers": ["o11y"], "allow": ["mcp__o11y__query"],
         "deny": ["mcp__o11y__set_environment"]}
    assert emit.oc_worker_permission(g)["mcp"] == [
        ("*_*", {"?": "deny"}), ("opencode_*", "deny"),
        ("o11y_*", "deny"), ("o11y_query", "allow"), ("o11y_set_environment", "deny")]


def test_a_read_only_worker_with_no_mcp_servers_still_denies_every_mcp_tool():
    rules = emit.oc_worker_permission({"tools": "read_only", "allow": []})["mcp"]
    assert rules == [("*_*", {"?": "deny"}), ("opencode_*", "deny")], rules


def test_a_write_worker_gets_no_mcp_catch_all():
    rules = emit.oc_worker_permission({"tools": "write", "allow": [],
                                       "deny": ["mcp__o11y__set_environment"]})["mcp"]
    assert rules == [("o11y_set_environment", "deny")], rules
