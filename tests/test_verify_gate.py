#!/usr/bin/env python3
"""The build graph's deterministic VERIFY gate.

A builder reviews its own work in one context, so it can repeat its own mistakes and claim
success on a patch whose tests fail or were edited. The verify gate takes that call away
from the builder: a script's exit code decides whether the builder may open its PR.

  - The graph declares it: a `check: verify` node (a node whose exit is decided by a
    script, not by the walker) with its pass edge (`terminal`) and its fail edge (`next`).
    Every rubric node declares its FAIL edge, so the gate rubric's `clear -> fix` loop is
    an edge emit can see. The execute worker's graph must carry the verify node.

Run:  uv run --with pytest --with pyyaml pytest tests/test_verify_gate.py -q
"""
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def refuses(mutate, match):
    with pytest.raises(SystemExit, match=match):
        emit.build_bindings(cfg_with(mutate))


def nodes(c, graph="build"):
    return c["graphs"][graph]["nodes"]


def build_graph(b):
    return next(g for g in b["graphs"] if g["name"] == "build")


# --- the graph declares the gate --------------------------------------------------------

def test_the_build_graph_declares_verify_as_a_check_node():
    g = build_graph(emit.build_bindings(CFG))
    assert g["nodes"]["verify"] == {"check": "verify", "next": "fix",
                                    "terminal": "pr_open"}, g["nodes"]["verify"]
    assert emit._targets(g["nodes"]["clear"]) == ["verify", "fix"], g["nodes"]["clear"]


def test_an_unknown_check_refuses():
    refuses(lambda c: nodes(c)["verify"].__setitem__("check", "lint"),
            r"nodes\.verify: check 'lint' is not a check")


def test_a_check_node_without_its_fail_edge_refuses():
    refuses(lambda c: nodes(c)["verify"].pop("next"), r"nodes\.verify.*fail edge")


def test_a_check_node_without_its_pass_terminal_refuses():
    refuses(lambda c: nodes(c)["verify"].pop("terminal"), r"nodes\.verify.*terminal")


def test_a_node_carrying_a_check_and_a_rubric_refuses():
    refuses(lambda c: nodes(c)["verify"].__setitem__("rubric", "gate"),
            r"exactly one of skill\|rubric\|check")


def test_a_terminal_rubric_node_with_no_fail_edge_refuses():
    """The defect this closes: the gate rubric loops `clear` back to `fix`, but the graph
    declared `clear` terminal, so emit could not see (or cap) that edge."""
    def m(c):
        nodes(c)["clear"] = {"rubric": "gate", "terminal": "pr_open"}
        nodes(c).pop("verify")
    refuses(m, r"nodes\.clear.*rubric.*FAIL edge")


def test_the_clear_to_fix_loop_is_capped_by_review():
    """clear -> fix and verify -> fix are declared, so the loop check sees them: drop the
    review cap and the loop through them refuses."""
    def m(c):
        nodes(c)["review"].pop("max_visits")
    refuses(m, r"loop .*clear.*max_visits")


def test_the_execute_worker_must_carry_the_verify_gate():
    def m(c):
        nodes(c).pop("verify")
        nodes(c)["clear"]["next"] = ["fix"]
        nodes(c)["clear"]["terminal"] = "pr_open"
    refuses(m, r"graphs\.build.*check: verify")


def test_verify_is_only_for_a_writing_worker():
    def m(c):
        c["graphs"]["build"]["tools"] = "read_only"
    refuses(m, r"nodes\.verify.*writing worker")


def test_the_index_names_the_check_node_and_its_file():
    b = emit.build_bindings(CFG)
    lines = {i["line"].split("**")[1]: i for i in
             emit.node_lines(build_graph(b), "claude-code", b["verbs"])}
    v = lines["verify"]
    assert "check `verify`" in v["line"], v["line"]
    assert v["path"] == "nodes/check-verify.md", v["path"]
    assert "terminal `pr_open`" in v["line"] and "`fix`" in v["line"], v["line"]


# --- the gate itself, against throwaway git repos -------------------------------------------
# A real, trivial project: shell functions in src/, shell tests in tests/, one test command
# that runs every tests/test_*.sh. The repo is a clone of a bare origin, so the default
# branch is origin/HEAD; the builder works on `feat`.

TEST_CMD = 'for t in tests/test_*.sh; do sh "$t" || exit 1; done'
ADD = 'add() { echo $(($1 + $2)); }\n'
MUL = 'mul() { echo $(($1 * $2)); }\n'
TEST_ADD = '. ./src/calc.sh\n[ "$(add 2 2)" = 4 ]\n'
TEST_MUL = '. ./src/calc.sh\n[ "$(mul 2 3)" = 6 ]\n'
PLUGIN = "testco-harness"
BUILDER = f"{PLUGIN}:builder"


def sh(cwd, *args):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout


def write(repo, files):
    for path, text in files.items():
        f = repo / path
        if text is None:
            f.unlink()
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)


def commit(repo, files, msg="change"):
    write(repo, files)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    sh(tmp_path, "git", "init", "-q", "-b", "main", str(work))
    sh(work, "git", "config", "user.email", "t@example.invalid")
    sh(work, "git", "config", "user.name", "t")
    commit(work, {"src/calc.sh": ADD, "tests/test_add.sh": TEST_ADD, "README.md": "calc\n"},
           "base")
    sh(work, "git", "remote", "add", "origin", str(origin))
    sh(work, "git", "push", "-q", "-u", "origin", "main")
    sh(work, "git", "remote", "set-head", "origin", "main")
    sh(work, "git", "checkout", "-q", "-b", "feat")
    return work


def declare(repo, command=TEST_CMD, tests=()):
    gitdir = Path(sh(repo, "git", "rev-parse", "--absolute-git-dir").strip())
    lines = [f"command: {command}"] + [f"test: {t}" for t in tests]
    (gitdir / "verify-test").write_text("\n".join(lines) + "\n")


def pr(verdict="pass"):
    return f"gh pr create --title 'add mul' --body 'Adds mul.\n\nverify={verdict}'"


def snapshot(repo):
    """Everything the gate must leave as it found it."""
    files = {str(p.relative_to(repo)): p.read_bytes() for p in sorted(repo.rglob("*"))
             if p.is_file() and ".git" not in p.relative_to(repo).parts}
    return {"head": sh(repo, "git", "rev-parse", "HEAD"),
            "status": sh(repo, "git", "status", "--porcelain=v1", "-uall"),
            "worktrees": sh(repo, "git", "worktree", "list", "--porcelain"),
            "stash": sh(repo, "git", "stash", "list"), "files": files}


@pytest.fixture(scope="module")
def cc():
    out = Path(tempfile.mkdtemp(prefix="emit-verify-cc-")) / "out"
    emit.TARGETS["claude-code"](CFG, out)
    return out


def gate_cc(out, repo, command, agent_type=BUILDER, cwd=None):
    payload = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(cwd or repo)}
    if agent_type is not None:
        payload.update({"agent_type": agent_type, "agent_id": "agent-1"})
    return subprocess.run(["sh", str(out / "hooks" / "scripts" / "verify-gate.sh")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          timeout=120)


def feature_with_tests(repo):
    commit(repo, {"src/calc.sh": ADD + MUL, "tests/test_mul.sh": TEST_MUL}, "add mul")


def test_cc_hooks_json_runs_the_verify_gate_on_bash(cc):
    hooks = json.loads((cc / "hooks" / "hooks.json").read_text())["hooks"]
    entry = next(e for e in hooks["PreToolUse"] if any(
        "verify-gate.sh" in h["command"] for h in e["hooks"]))
    assert entry["matcher"] == "Bash", entry
    # a hook the host times out does not block: the host limit must exceed the gate's own
    assert entry["hooks"][0]["timeout"] > 2 * 1500, entry


def test_cc_pass_lets_the_pr_create_run(cc, repo):
    feature_with_tests(repo)
    declare(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 0, r.stderr


def test_cc_tests_that_still_pass_with_the_source_reverted_fail(cc, repo):
    """The new test exercises only what the default branch already had: it passes with
    the change reverted, so it proves nothing about the change."""
    commit(repo, {"src/calc.sh": ADD + MUL,
                  "tests/test_add_more.sh": '. ./src/calc.sh\n[ "$(add 1 1)" = 2 ]\n'})
    declare(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "verify=fail" in r.stderr and "still pass" in r.stderr, r.stderr
    assert "src/calc.sh" in r.stderr, "the refusal names what it reverted"


def test_cc_a_command_that_fails_at_head_fails(cc, repo):
    commit(repo, {"src/calc.sh": MUL, "tests/test_mul.sh": TEST_MUL})  # add() is gone
    declare(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "fails at HEAD" in r.stderr, r.stderr


def test_cc_a_protected_test_edit_is_flagged_and_must_reach_the_pr_body(cc, repo):
    feature_with_tests(repo)
    commit(repo, {"tests/test_add.sh": TEST_ADD + '[ "$(add 0 0)" = 0 ]\n'}, "edit old test")
    declare(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2, r.stderr
    assert "verify=protected-edited" in r.stderr and "tests/test_add.sh" in r.stderr, r.stderr
    r = gate_cc(cc, repo, pr("protected-edited"))
    assert r.returncode == 0, r.stderr


def test_cc_a_deleted_protected_test_is_flagged(cc, repo):
    feature_with_tests(repo)
    commit(repo, {"tests/test_add.sh": None}, "drop old test")
    declare(repo)
    assert gate_cc(cc, repo, pr("protected-edited")).returncode == 0
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "verify=protected-edited" in r.stderr, r.stderr


def test_cc_no_test_change_is_no_tests_and_does_not_block(cc, repo):
    commit(repo, {"README.md": "calc, documented\n"})
    declare(repo)
    assert gate_cc(cc, repo, pr("no-tests")).returncode == 0
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "verify=no-tests" in r.stderr, r.stderr


def test_cc_a_declared_test_path_counts_as_a_test(cc, repo):
    """A declaration may ADD test paths: a checks/ dir becomes a test path, so editing
    one that the default branch has is a protected edit."""
    commit(repo, {"checks/check_add.sh": TEST_ADD}, "a check outside tests/")
    sh(repo, "git", "push", "-q", "origin", "feat:main")
    sh(repo, "git", "fetch", "-q", "origin")
    feature_with_tests(repo)
    commit(repo, {"checks/check_add.sh": TEST_ADD + "true\n"})
    declare(repo, tests=["checks/"])
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "checks/check_add.sh" in r.stderr, r.stderr


def test_cc_no_declaration_blocks(cc, repo):
    feature_with_tests(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "no test command is declared" in r.stderr, r.stderr


def test_cc_no_verdict_in_the_pr_body_blocks_before_any_run(cc, repo):
    feature_with_tests(repo)
    declare(repo, command="touch /dev/null/never; exit 1")
    r = gate_cc(cc, repo, "gh pr create --title t --body 'no verdict here'")
    assert r.returncode == 2 and "verify=<pass|no-tests|protected-edited>" in r.stderr, r.stderr


def test_cc_the_verdict_may_ride_a_body_file(cc, repo, tmp_path):
    feature_with_tests(repo)
    declare(repo)
    body = tmp_path / "body.md"
    body.write_text("Adds mul.\n\nverify=pass\n")
    assert gate_cc(cc, repo, f"gh pr create --title t --body-file {body}").returncode == 0


def test_cc_the_worktree_is_taken_from_a_leading_cd(cc, repo, tmp_path):
    feature_with_tests(repo)
    declare(repo)
    r = gate_cc(cc, repo, f"cd {repo} && " + pr("pass"), cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    r = gate_cc(cc, repo, pr("pass"), cwd=tmp_path)  # not a repo: fail closed
    assert r.returncode == 2, r.stderr


@pytest.mark.parametrize("scenario", ["pass", "fail"])
def test_cc_the_builders_tree_is_left_unchanged(cc, repo, scenario):
    feature_with_tests(repo)
    if scenario == "fail":
        commit(repo, {"tests/test_mul.sh": None,
                      "tests/test_add_more.sh": '. ./src/calc.sh\n[ "$(add 1 1)" = 2 ]\n'})
    declare(repo)
    write(repo, {"notes.txt": "uncommitted\n", "README.md": "dirty edit\n"})
    before = snapshot(repo)
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == (0 if scenario == "pass" else 2), r.stderr
    assert snapshot(repo) == before


def test_cc_a_signal_removes_the_temporary_worktree(cc, repo):
    feature_with_tests(repo)
    declare(repo, command="sleep 60")
    before = snapshot(repo)
    payload = {"tool_name": "Bash", "tool_input": {"command": pr("pass")},
               "agent_type": BUILDER, "cwd": str(repo)}
    p = subprocess.Popen(["sh", str(cc / "hooks" / "scripts" / "verify-gate.sh")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    p.stdin.write(json.dumps(payload))
    p.stdin.close()
    deadline = time.time() + 30
    while sh(repo, "git", "worktree", "list").count("\n") < 2:
        assert time.time() < deadline, "the gate never started its run"
        time.sleep(0.1)
    p.send_signal(signal.SIGTERM)
    rc = p.wait(timeout=30)
    assert rc == 2, (rc, p.stderr.read())
    assert "interrupted" in p.stderr.read()
    assert snapshot(repo) == before


@pytest.mark.parametrize("agent_type", ["testco-harness:triager", "Explore", None,
                                        "other:builder-x"])
def test_cc_every_other_agent_is_ignored(cc, repo, agent_type):
    feature_with_tests(repo)  # no declaration: a gated PR create would block
    r = gate_cc(cc, repo, pr("pass"), agent_type=agent_type)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == "", (agent_type, r)


@pytest.mark.parametrize("command", ["git status", "gh pr view 1", "gh pr list",
                                     "echo 'gh pr' create"])
def test_cc_the_builders_other_commands_pass_through(cc, repo, command):
    r = gate_cc(cc, repo, command)
    assert r.returncode == 0 and r.stderr == "", (command, r.stderr)


@pytest.mark.parametrize("command", ["gh pr new --title t", "cd . && gh pr create",
                                     "/usr/local/bin/gh pr create -t t"])
def test_cc_every_pr_create_spelling_is_gated(cc, repo, command):
    feature_with_tests(repo)
    r = gate_cc(cc, repo, command)
    assert r.returncode == 2, (command, r.stderr)


# --- opencode: a plugin guard on the shell tool -------------------------------------------

HARNESS = ROOT / "tests" / "verify_harness.mjs"
HOSTS = ["v1", "v2"]
SHELL = {"v1": "bash", "v2": "shell"}
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node required")


@pytest.fixture(scope="module")
def oc():
    out = Path(tempfile.mkdtemp(prefix="emit-verify-oc-")) / "out"
    emit.TARGETS["opencode"](CFG, out)
    return out


def guard(out, directory, command, host, agent="builder", tool=None, **extra):
    scenario = {"agent": agent, "tool": tool or SHELL[host], "command": command, **extra}
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "verify.js"), str(directory),
                        json.dumps(scenario), host], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])["threw"]


def test_oc_emits_the_guard_beside_its_script(oc):
    assert (oc / "plugin" / "verify-gate.py").is_file()
    src = (oc / "plugin" / "verify.js").read_text()
    assert "const AGENTS = [\"builder\"]" in src, "the guard names only the declared builder"


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_pass_lets_the_pr_create_run(oc, repo, host):
    feature_with_tests(repo)
    declare(repo)
    assert guard(oc, repo, pr("pass"), host) is None


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_tests_that_still_pass_with_the_source_reverted_throw(oc, repo, host):
    commit(repo, {"src/calc.sh": ADD + MUL,
                  "tests/test_add_more.sh": '. ./src/calc.sh\n[ "$(add 1 1)" = 2 ]\n'})
    declare(repo)
    before = snapshot(repo)
    threw = guard(oc, repo, pr("pass"), host)
    assert threw and "verify=fail" in threw and "still pass" in threw, threw
    assert snapshot(repo) == before, "the builder's tree changed"


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_a_protected_test_edit_is_flagged(oc, repo, host):
    feature_with_tests(repo)
    commit(repo, {"tests/test_add.sh": TEST_ADD + "true\n"})
    declare(repo)
    threw = guard(oc, repo, pr("pass"), host)
    assert threw and "verify=protected-edited" in threw, threw
    assert guard(oc, repo, pr("protected-edited"), host) is None


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_no_test_change_is_no_tests(oc, repo, host):
    commit(repo, {"README.md": "calc, documented\n"})
    declare(repo)
    assert guard(oc, repo, pr("no-tests"), host) is None


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_the_shell_workdir_names_the_worktree(oc, repo, host, tmp_path):
    feature_with_tests(repo)
    declare(repo)
    assert guard(oc, tmp_path, pr("pass"), host, workdir=str(repo)) is None


@needs_node
@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("agent", ["build", "triager", "validate"])
def test_oc_every_other_agent_is_ignored(oc, repo, host, agent):
    feature_with_tests(repo)  # no declaration: a gated PR create would throw
    assert guard(oc, repo, pr("pass"), host, agent=agent) is None


@needs_node
@pytest.mark.parametrize("host", HOSTS)
def test_oc_other_tools_and_commands_pass_through(oc, repo, host):
    feature_with_tests(repo)
    assert guard(oc, repo, pr("pass"), host, tool="read") is None
    assert guard(oc, repo, "git status", host) is None


@needs_node
def test_oc_v1_a_session_of_unknown_agent_fails_closed_on_pr_create(oc, repo):
    feature_with_tests(repo)
    threw = guard(oc, repo, pr("pass"), "v1", known=False)
    assert threw and "fail closed" in threw, threw
    assert guard(oc, repo, "git status", "v1", known=False) is None


def test_emit_refuses_a_verify_node_whose_guard_names_no_agent(monkeypatch, tmp_path):
    """The artifact check: a verify node whose gate does not name its worker does not
    emit (a template edit that drops the agent fails the emit, not a later test)."""
    for target in ("claude-code", "opencode"):
        monkeypatch.setattr(emit, "verify_gate_agents", lambda graphs, plugin: [])
        monkeypatch.setattr(emit, "verify_gate_oc_agents", lambda graphs: [])
        with pytest.raises(SystemExit, match=r"verify gate"):
            emit.TARGETS[target](CFG, tmp_path / target)


# --- the contract the builder walks by --------------------------------------------------

def test_the_result_line_carries_the_verify_verdict():
    assert "| verify=<pass|fail|no-tests|protected-edited> |" in emit.RESULT_LINE, \
        emit.RESULT_LINE


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_the_prose_walks_the_gate(target, cc, oc):
    out = {"claude-code": cc, "opencode": oc}[target]
    nd, rb, ag = {"claude-code": ("nodes", "rubrics", "agents"),
                  "opencode": ("node", "rubric", "agent")}[target]
    validate = (out / nd / "build-validate.md").read_text()
    for needle in ("verify-test", "--absolute-git-dir", "command: ", "test: "):
        assert needle in validate, f"validate does not say how to declare ({needle!r})"
    gate = (out / rb / "gate.md").read_text()
    assert "`verify`" in gate and "`fix`" in gate, "the gate rubric does not route PASS to verify"
    check = (out / nd / "check-verify.md").read_text()
    assert "verify=protected-edited" in check and "`fix`" in check, check
    body = (out / ag / "builder.md").read_text()
    assert "verify" in body.split("---", 2)[1], "the builder's description omits verify"
    assert "protected-edited" in body, "the builder body does not explain the verdicts"
    fix = (out / nd / "build-fix.md").read_text()
    assert "verify" in fix, "fix does not say a verify refusal enters it"
    skills = {"claude-code": "skills", "opencode": "skill"}[target]
    execute = (out / skills / "execute" / "SKILL.md").read_text()
    assert "verify=protected-edited" in execute, "execute does not surface protected edits"


def test_cc_a_declared_command_that_names_the_worktree_is_refused(cc, repo):
    """The command runs in a fresh checkout; one that cds into the builder's tree would
    run the reverted leg against the builder's HEAD (and could write to it)."""
    feature_with_tests(repo)
    top = sh(repo, "git", "rev-parse", "--show-toplevel").strip()
    declare(repo, command=f"cd {top} && {TEST_CMD}")
    r = gate_cc(cc, repo, pr("pass"))
    assert r.returncode == 2 and "names your worktree" in r.stderr, r.stderr
