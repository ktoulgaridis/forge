#!/usr/bin/env python3
"""The opencode shell guard: ONE simple command per call for an allowlisted shell.

opencode checks shell permission per command NODE of the parsed command. A statement
with no command node (`> f` alone, or `git log -1; > f`) asks no permission at all
(core/src/tool/plugin/shell.ts: `if (parsed.commands.length > 0) permission.assert(…)`),
so an agent whose shell is a permission allowlist could still create or truncate a file.
Permission config cannot close that; the emitted plugin/shell-guard.js does:

  - it guards every emitted agent whose shell permission is an allowlist (`"*": deny`,
    then allows) — derived at emit time from the catalog, checked on the artifact;
  - for those agents it rejects any shell call that is not ONE simple command, by the
    same rule the Claude Code gate (hooks/scripts/code-read-gate.py `words`) enforces —
    the parity test below runs both over one case table;
  - it identifies the caller as plugin/verify.js does (2.x: the hook event names the
    agent; 1.x: `chat.params`), and a shell call from a session of unknown agent is
    blocked;
  - every other agent (the builder, an agent whose shell is fully disabled) and every
    other tool passes through untouched.

Run:  uv run --with pytest --with pyyaml pytest tests/test_oc_shell_guard.py -q
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_triage_graph import emit_to, load, split, triage  # noqa: E402
from test_graph_nodes import emit_oc, graph_cfg  # noqa: E402

HARNESS = ROOT / "tests" / "shell_guard_harness.mjs"
HOSTS = ["v1", "v2"]
SHELL = {"v1": "bash", "v2": "shell"}
GUARD = "plugin/shell-guard.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node required")

# ONE case table for both hosts' rule: (command, is it one simple command?).
CASES = [
    # one simple command — quotes only group a word; inside single quotes anything goes
    ("rg foo", True),
    ("git log -1", True),
    ("git -C api log -1", True),
    ("git log --since=2026-09-01T00:00Z --until=2026-09-02T00:00Z -- api/src/x.go", True),
    ("git show 1a2b3c4:api/src/handler.go", True),
    ("git blame -L 10,20 api/src/handler.go", True),
    ("rg -n 'a|b; c > d' api/src", True),
    ("rg 'a$b' 'c`d' 'e\\f'", True),
    ("find api -name '*.go'", True),
    ('cat "api/go.mod"', True),
    ("gh pr view 12 --json title,body", True),
    ("ls\tapi", True),
    ("git log HEAD~3 HEAD^ @{u}", False),  # braces are operators even without a space
    # no command node: a bare redirect, alone or chained after a read
    ("> f", False),
    (">f", False),
    ("git log -1; > f", False),
    ("git log -1;>f", False),
    # redirects and here-strings
    ("rg x > f", False),
    ("rg x >> f", False),
    ("rg x 2>f", False),
    ("rg x >| f", False),
    ("cat < f", False),
    ("cat <<< x", False),
    # substitution, expansion, escape — also inside double quotes
    ("git log $(x)", False),
    ('rg "$(x)"', False),
    ("rg `x`", False),
    ("rg $HOME", False),
    ('rg "a\\b"', False),
    ("rg foo\\ bar", False),
    # chains, pipes, background, grouping, comments, globs
    ("git log -1\n> f", False),
    ("git log -1\nrm x", False),
    ("git log -1\r> f", False),
    ("rg x\x00", False),
    ("rg foo | sh", False),
    ("rg foo|sh", False),
    ("git log && rm x", False),
    ("git log || rm x", False),
    ("git log & rm x", False),
    ("(rg foo)", False),
    ("{ rg foo; }", False),
    ("rg foo #x", False),
    ("ls *", False),
    ("ls ?", False),
    ("ls [ab]", False),
    # nothing, or an unterminated quote
    ("", False),
    ("   ", False),
    ("cat 'unterminated", False),
    ('cat "unterminated', False),
]
SIMPLE = [c for c, ok in CASES if ok]
NOT_SIMPLE = [c for c, ok in CASES if not ok]
# The acceptance commands, named on their own so a table edit cannot drop them.
MUST_BLOCK = ["> f", "git log -1; > f", "rg x > f", "cat < f", "git log $(x)",
              "git log -1\n> f"]
MUST_PASS = ["git -C api log -1", "rg foo"]


def with_code():
    return load(lambda c: triage(c).__setitem__("code", "read"))


@pytest.fixture(scope="module")
def code_oc():
    """The triager declares `code: read` (an allowlisted shell) + the supplementary
    reviewer is enabled (its shell is the tracker + git read allowlist)."""
    return emit_to("opencode", with_code())


@pytest.fixture(scope="module")
def plain_oc():
    """No `code:` — the triager's shell is wholly disabled; the reviewer is enabled."""
    return emit_to("opencode", load())


def run(out, scenarios, host):
    p = subprocess.run(["node", str(HARNESS), str(out / GUARD), str(out),
                        json.dumps(scenarios), host], capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["threw"]


def calls(out, commands, host, agent="triager", tool=None, **extra):
    """What the guard did with each command from `agent`: None = let it run."""
    return run(out, [{"agent": agent, "tool": tool or SHELL[host], "command": c, **extra}
                     for c in commands], host)


# --- which agents are guarded: derived at emit time, checked on the artifact -------------

def guarded(out):
    src = (out / GUARD).read_text()
    return json.loads(next(ln for ln in src.splitlines()
                           if ln.startswith("const AGENTS = "))[len("const AGENTS = "):])


def test_every_allowlisted_shell_is_guarded(code_oc):
    assert guarded(code_oc) == ["triager", "validate"]


def test_a_disabled_shell_is_not_guarded(plain_oc):
    assert guarded(plain_oc) == ["validate"]


def test_no_guard_ships_without_an_allowlisted_shell():
    out = emit_oc(graph_cfg(enabled=False))
    assert not (out / GUARD).exists()


def test_the_guarded_set_matches_the_emitted_permissions(code_oc):
    """Each guarded agent's emitted shell is an allowlist; the builder's is not."""
    for agent in guarded(code_oc):
        bash = split((code_oc / "agent" / f"{agent}.md").read_text())[0]["permission"]["bash"]
        assert list(bash.items())[0] == ("*", "deny") and "allow" in bash.values(), bash
    builder = split((code_oc / "agent" / "builder.md").read_text())[0]["permission"]
    assert "bash" not in builder, builder


def test_emit_refuses_a_guard_that_misses_an_allowlisted_shell(monkeypatch, tmp_path):
    """The artifact check: a guard rendered without an allowlisted agent does not emit."""
    real = emit.build_bindings_opencode

    def drop(cfg):
        b = real(cfg)
        b["scalars"]["SHELL_GUARD_OC_AGENTS_JSON"] = '["validate"]'
        return b
    monkeypatch.setattr(emit, "build_bindings_opencode", drop)
    with pytest.raises(SystemExit, match=r"shell guard"):
        emit.TARGETS["opencode"](with_code(), tmp_path / "oc")


# --- the acceptance: a guarded agent runs only one simple command per call ---------------

@needs_node
@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("agent", ["triager", "validate"])
def test_a_guarded_agent_cannot_run_anything_but_one_simple_command(code_oc, host, agent):
    threw = calls(code_oc, MUST_BLOCK, host, agent)
    for command, why in zip(MUST_BLOCK, threw):
        assert why and "shell-guard" in why, (command, why)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_a_guarded_agent_runs_a_simple_read(code_oc, host):
    assert calls(code_oc, MUST_PASS, host) == [None] * len(MUST_PASS)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("command", [None, 7, ["rg", "foo"]])
def test_a_guarded_agent_without_a_command_string_is_blocked(code_oc, host, command):
    [why] = calls(code_oc, [command], host)
    assert why and "fail closed" in why, why


@needs_node
@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("agent", ["builder", "build", "explore"])
def test_an_unguarded_agent_is_untouched(code_oc, host, agent):
    assert calls(code_oc, NOT_SIMPLE, host, agent) == [None] * len(NOT_SIMPLE)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_an_agent_whose_shell_is_disabled_is_untouched(plain_oc, host):
    """Without `code:` the triager's shell is removed by permission, not by the guard."""
    assert calls(plain_oc, MUST_BLOCK, host) == [None] * len(MUST_BLOCK)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_other_tools_pass_through(code_oc, host):
    assert calls(code_oc, MUST_BLOCK, host, tool="read") == [None] * len(MUST_BLOCK)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_a_session_of_unknown_agent_is_blocked(code_oc, host):
    threw = calls(code_oc, MUST_PASS + MUST_BLOCK, host, known=False)
    for command, why in zip(MUST_PASS + MUST_BLOCK, threw):
        assert why and "fail closed" in why, (command, why)
    # ... on the shell only
    assert calls(code_oc, MUST_BLOCK, host, tool="read", known=False) == [None] * len(MUST_BLOCK)


# --- parity: the Claude Code gate and the opencode guard, one case table -----------------

@pytest.fixture(scope="module")
def cc_rule():
    """The rendered Claude Code gate's own rule (hooks/scripts/code-read-gate.py)."""
    out = emit_to("claude-code", with_code())
    path = out / "hooks" / "scripts" / "code-read-gate.py"
    spec = importlib.util.spec_from_file_location("code_read_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def simple(command):
        try:
            return bool(mod.words(command))
        except mod.Refused:
            return False
    return simple


def test_the_table_carries_the_acceptance_commands():
    assert set(MUST_BLOCK) <= set(NOT_SIMPLE) and set(MUST_PASS) <= set(SIMPLE)


def test_the_cc_gate_decides_the_table(cc_rule):
    assert {c: cc_rule(c) for c, _ in CASES} == dict(CASES)


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_the_oc_guard_decides_the_table_as_the_cc_gate_does(code_oc, cc_rule, host):
    commands = [c for c, _ in CASES]
    got = {c: why is None for c, why in zip(commands, calls(code_oc, commands, host))}
    assert got == {c: cc_rule(c) for c in commands}


# --- the emitted README says what ships --------------------------------------------------

def test_the_readme_documents_the_guard_it_ships(code_oc):
    readme = (code_oc / "README.md").read_text()
    assert "## `plugin/shell-guard.js`" in readme, "the README does not document the guard"
    layout = readme.split("## Layout", 1)[1].split("```", 2)[1]
    assert "shell-guard.js" in layout, layout
    assert "`plugin/shell-guard.js`" in readme.split("## Host compatibility", 1)[1]


def test_the_readme_does_not_document_a_guard_it_does_not_ship():
    readme = (emit_oc(graph_cfg(enabled=False)) / "README.md").read_text()
    assert "shell-guard" not in readme, "the README documents a guard that is not emitted"
