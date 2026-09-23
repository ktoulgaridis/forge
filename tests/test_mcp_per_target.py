#!/usr/bin/env python3
"""Per-target MCP server names for a read_only worker (TEC-4099).

The two hosts name the SAME MCP server differently:
  - Claude Code names a plugin-provided server `plugin_<plugin.json name>_<.mcp.json key>`
    (observed live: `mcp__plugin_proscia-o11y_proscia-o11y__*`);
  - opencode names a server by its key in the user's config `mcp` block (2.x
    `mcp.servers.<key>`, 1.x `mcp.<key>`: core/src/config/normalize.ts:260-283 @ v2.0.12)
    and a tool `<sanitized server>_<sanitized tool>` (core/src/tool/mcp.ts:16-17).

So `mcp_servers` maps a graph-local HANDLE to one name per target, `allow` / `deny` /
node goal+guidance name tools by handle (`mcp__<handle>__<tool>`), and each target emits
its OWN names — in the permission keys and in every file it renders. A server with no name
for a target that emits refuses (a read_only worker would otherwise deny every declared
read: safe, but the worker cannot work).

Run:  uv run --with pytest --with pyyaml pytest tests/test_mcp_per_target.py -q
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_triage_graph import load, split, oc_decision, oc_rule  # noqa: E402

CC_O11Y, OC_O11Y = "plugin_acme-o11y_acme-o11y", "acme-o11y"
CC_ZD, OC_ZD = "plugin_acme-zd_acme-zd", "acme.zd"      # `.` is sanitized to `_` on opencode
SERVERS = {"o11y": {"claude-code": CC_O11Y, "opencode": OC_O11Y},
           "zd": {"claude-code": CC_ZD, "opencode": OC_ZD}}
READS = ["mcp__o11y__query_clickhouse", "mcp__o11y__search_logs", "mcp__zd__get_ticket"]
WRITES = ["mcp__o11y__create_dashboard", "mcp__o11y__update_annotation"]
GUIDANCE = "one probe at a time via mcp__o11y__query_clickhouse; never set_environment"


def per_target(c):
    t = c["graphs"]["triage"]
    t["mcp_servers"] = {h: dict(n) for h, n in SERVERS.items()}
    t["allow"] = ["Grep", "Glob", *READS]
    t["deny"] = list(WRITES)
    t["nodes"]["investigate"]["guidance"] = GUIDANCE


def cfg(mutate=None):
    def m(c):
        per_target(c)
        if mutate:
            mutate(c)
    return load(m)


def emit_to(target, c=None):
    out = Path(tempfile.mkdtemp(prefix=f"emit-mcp-{target}-")) / "out"
    emit.TARGETS[target](c or cfg(), out)
    return out


@pytest.fixture(scope="module")
def cc():
    return emit_to("claude-code")


@pytest.fixture(scope="module")
def oc():
    return emit_to("opencode")


def oc_key(server, tool):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", server) + "_" + tool


def tool_of(name):
    return name.split("__", 2)[2]


# --- the permission keys use each host's own names --------------------------------------

def test_oc_triager_allows_its_opencode_named_reads(oc):
    perm = split((oc / "agent" / "triager.md").read_text())[0]["permission"]
    for name in READS:
        server = OC_O11Y if "__o11y__" in name else OC_ZD
        key = oc_key(server, tool_of(name))
        assert oc_decision(perm, key) == "allow", (key, perm)


def test_oc_triager_denies_set_environment_and_writes_under_opencode_names(oc):
    perm = split((oc / "agent" / "triager.md").read_text())[0]["permission"]
    for key in [oc_key(OC_O11Y, "set_environment"), oc_key(OC_ZD, "set_environment"),
                *(oc_key(OC_O11Y, tool_of(w)) for w in WRITES)]:
        assert oc_rule(perm, key) == (key, "*", "deny"), (key, oc_rule(perm, key))
    assert oc_decision(perm, oc_key(OC_O11Y, "a_tool_added_next_release")) == "deny", perm


def test_oc_triager_permission_names_no_claude_code_server(oc):
    perm = split((oc / "agent" / "triager.md").read_text())[0]["permission"]
    for key in perm:
        assert CC_O11Y not in key and CC_ZD not in key, key
        assert not key.startswith("mcp__"), key


def test_cc_triager_grants_and_disallows_under_claude_code_names(cc):
    fm, _ = split((cc / "agents" / "triager.md").read_text())
    tools = {x.strip() for x in fm["tools"].split(",")}
    denied = {x.strip() for x in fm["disallowedTools"].split(",")}
    assert {f"mcp__{CC_O11Y}__query_clickhouse", f"mcp__{CC_O11Y}__search_logs",
            f"mcp__{CC_ZD}__get_ticket"} <= tools, tools
    assert {f"mcp__{CC_O11Y}__set_environment", f"mcp__{CC_ZD}__set_environment",
            f"mcp__{CC_O11Y}__create_dashboard", f"mcp__{CC_O11Y}__update_annotation"} <= denied
    assert not [t for t in tools | denied if t.startswith(("mcp__o11y__", "mcp__zd__"))], \
        "an unresolved handle reached the Claude Code agent"


def test_the_triage_verb_checks_each_hosts_server_names(cc, oc):
    cc_body = (cc / "skills" / "triage" / "SKILL.md").read_text()
    oc_body = (oc / "skill" / "triage" / "SKILL.md").read_text()
    assert f"`{CC_O11Y}`" in cc_body and f"`{CC_ZD}`" in cc_body, "CC /triage names"
    assert f"`{OC_O11Y}`" in oc_body and f"`{OC_ZD}`" in oc_body, "opencode /triage names"
    assert CC_O11Y not in oc_body and CC_ZD not in oc_body, "a CC name on opencode"


# --- every emitted file names only its own host's servers -------------------------------

def emitted_text(out):
    return {p.relative_to(out): p.read_text() for p in out.rglob("*.md")}


def test_the_node_guidance_names_each_hosts_tool(cc, oc):
    cc_idx = (cc / "skills" / "triage-graph" / "SKILL.md").read_text()
    assert f"mcp__{CC_O11Y}__query_clickhouse" in cc_idx, cc_idx
    for f in (oc / "skill" / "triage-graph" / "SKILL.md", oc / "agent" / "triager.md"):
        body = f.read_text()
        assert f"{OC_O11Y}_query_clickhouse" in body, f


def test_no_opencode_file_names_a_claude_code_server_or_tool(oc):
    for rel, text in emitted_text(oc).items():
        for bad in (CC_O11Y, CC_ZD, "mcp__o11y__", "mcp__zd__", f"mcp__{OC_O11Y}__"):
            assert bad not in text, f"{rel} names {bad!r} on opencode"


def test_no_claude_code_file_names_an_opencode_tool(cc):
    rx = re.compile(r"(?<![\w-])(acme-o11y|acme_zd)_\w")
    for rel, text in emitted_text(cc).items():
        assert not rx.search(text), f"{rel} names an opencode tool key on Claude Code"
        assert "mcp__o11y__" not in text and "mcp__zd__" not in text, rel


# --- refusals: an ambiguous or incomplete per-target name does not emit -----------------

def refuses(target, mutate, match):
    with pytest.raises(SystemExit, match=match):
        emit_to(target, cfg(mutate))


def test_a_server_without_an_opencode_name_refuses_on_opencode_only():
    drop = lambda c: c["graphs"]["triage"]["mcp_servers"]["zd"].pop("opencode")  # noqa: E731
    refuses("opencode", drop, r"mcp_servers\.zd.*no `opencode` name")
    emit_to("claude-code", cfg(drop))   # the target it names still emits


def test_a_server_without_a_claude_code_name_refuses_on_claude_code():
    drop = lambda c: c["graphs"]["triage"]["mcp_servers"]["o11y"].pop("claude-code")  # noqa: E731
    refuses("claude-code", drop, r"mcp_servers\.o11y.*no `claude-code` name")


def test_the_single_list_form_refuses_with_a_migration():
    refuses("claude-code", lambda c: c["graphs"]["triage"].__setitem__(
        "mcp_servers", ["o11y", "zd"]), r"mcp_servers.*mapping.*claude-code.*opencode")


def test_a_single_string_name_refuses_as_ambiguous():
    refuses("claude-code", lambda c: c["graphs"]["triage"]["mcp_servers"].__setitem__(
        "o11y", CC_O11Y), r"mcp_servers\.o11y.*ambiguous")


def test_an_unknown_target_key_refuses():
    refuses("claude-code", lambda c: c["graphs"]["triage"]["mcp_servers"]["o11y"].__setitem__(
        "cursor", "x"), r"mcp_servers\.o11y.*unknown")


def test_a_name_with_a_double_underscore_refuses():
    refuses("claude-code", lambda c: c["graphs"]["triage"]["mcp_servers"]["o11y"].__setitem__(
        "opencode", "a__b"), r"__")


def test_a_deny_on_an_undeclared_handle_refuses():
    refuses("claude-code", lambda c: c["graphs"]["triage"]["deny"].append(
        "mcp__other__delete"), r"undeclared.*mcp_servers")


def test_guidance_naming_an_undeclared_handle_refuses():
    refuses("claude-code", lambda c: c["graphs"]["triage"]["nodes"]["investigate"].__setitem__(
        "guidance", "use mcp__plugin_acme-o11y_acme-o11y__query"), r"undeclared.*mcp_servers")
