#!/usr/bin/env python3
"""The emitted opencode `dispatch` tool — the orchestrator's one primitive.

These tests run the RENDERED plugin under node against a real temp git workspace
(one main dir, several repos) and a fake opencode client, and check behaviour:

  - a writer role gets its own worktree in the RIGHT repo, on a branch named after the
    ticket, and is prompted there with the ticket as the whole envelope;
  - a follow-up command by task_id resumes the same session: no new worktree, no new
    session (that is the feedback loop — implement → review → fail → same troop again);
  - a model the org bans is refused before anything is created; an allowed one is
    forwarded per call (the orchestrator picks the model per task);
  - an unknown role is refused (the tool IS the role allowlist);
  - read-only roles cannot dispatch (derived deny), and the primary cannot use the
    built-in `task` — dispatch is the only door.

Run:  uv run --with pytest --with pyyaml pytest tests/test_opencode_dispatch.py -q
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402

HARNESS = ROOT / "tests" / "dispatch_harness.mjs"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node required")


def emit_oc(cfg=None):
    out = Path(tempfile.mkdtemp(prefix="emit-dispatch-")) / "out"
    emit.TARGETS["opencode"](cfg or CFG, out)
    return out


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def workspace(repos=("api", "web")):
    """One main dir, N sibling repos (each a real git repo with one commit)."""
    ws = Path(tempfile.mkdtemp(prefix="ws-"))
    for r in repos:
        d = ws / r
        d.mkdir()
        git("init", "-q", "-b", "main", cwd=d)
        git("config", "user.email", "t@t", cwd=d)
        git("config", "user.name", "t", cwd=d)
        (d / "README").write_text(r)
        git("add", ".", cwd=d)
        git("commit", "-q", "-m", "init", cwd=d)
    return ws


def dispatch(out, ws, **args):
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "dispatch.js"), str(ws),
                        json.dumps(args)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


# --- the writer gets a worktree in the right repo -------------------------------------

def test_implementer_runs_in_its_own_worktree_in_the_named_repo():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="implementer", repo="web", ticket="TST-7")
    ops = [c["op"] for c in r["calls"]]
    assert ops == ["create", "prompt"], r
    wt = r["calls"][0]["input"]["query"]["directory"]
    assert Path(wt).is_dir() and wt.startswith(str(ws)), wt
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "TST-7"
    # the worktree belongs to `web`, not `api`
    assert wt in git("worktree", "list", cwd=ws / "web")
    assert wt not in git("worktree", "list", cwd=ws / "api")
    body = r["calls"][1]["input"]["body"]
    assert body["agent"] == "implementer"
    assert "TST-7" in body["parts"][0]["text"]
    assert "model" not in body  # unset → the agent file's model
    # the orchestrator gets result lines + the task_id to resume, not the transcript
    assert "ses_1" in r["result"]["output"] and "PR https://x/pr/1" in r["result"]["output"]


def test_repo_is_required_when_the_workspace_is_ambiguous():
    out, ws = emit_oc(), workspace(("api", "web"))
    r = dispatch(out, ws, role="implementer", ticket="TST-8")
    assert r["calls"] == [], r
    assert "repo" in r["result"]["output"].lower()


def test_single_repo_workspace_needs_no_repo_argument():
    out, ws = emit_oc(), workspace(("api",))
    r = dispatch(out, ws, role="implementer", ticket="TST-9")
    assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r
    assert "TST-9" in git("worktree", "list", cwd=ws / "api")


# --- feedback loop: same troop, follow-up command ----------------------------------

def test_task_id_resumes_the_same_session_without_a_new_worktree():
    out, ws = emit_oc(), workspace()
    first = dispatch(out, ws, role="implementer", repo="api", ticket="TST-1")
    before = git("worktree", "list", cwd=ws / "api")
    r = dispatch(out, ws, role="implementer", ticket="TST-1", task_id="ses_1",
                 command="address the review deficiencies")
    assert [c["op"] for c in r["calls"]] == ["prompt"], r
    assert r["calls"][0]["input"]["path"]["id"] == "ses_1"
    assert "address the review deficiencies" in r["calls"][0]["input"]["body"]["parts"][0]["text"]
    assert git("worktree", "list", cwd=ws / "api") == before
    assert first["calls"][0]["op"] == "create"


# --- the orchestrator picks the model per task, inside the org's policy ------------

def test_allowed_model_is_forwarded_per_call():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="reviewer", ticket="TST-2",
                 model="amazon-bedrock/us.openai.gpt-5-2025-08-07")
    body = r["calls"][-1]["input"]["body"]
    assert body["model"] == {"providerID": "amazon-bedrock",
                             "modelID": "us.openai.gpt-5-2025-08-07"}, body


def test_banned_model_is_refused_before_anything_is_created():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="implementer", repo="api", ticket="TST-3",
                 model="amazon-bedrock/us.anthropic.claude-haiku-4-5")
    assert r["calls"] == [], r
    assert "haiku" in r["result"]["output"]
    assert "TST-3" not in git("worktree", "list", cwd=ws / "api")


def test_model_outside_the_org_provider_is_refused():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="reviewer", ticket="TST-4", model="anthropic/claude-sonnet-4-5")
    assert r["calls"] == [], r
    assert "amazon-bedrock" in r["result"]["output"]


# --- the tool is the role allowlist ---------------------------------------------------

def test_unknown_role_is_refused():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="general", repo="api", ticket="TST-5")
    assert r["calls"] == [], r
    assert "general" in r["result"]["output"]


def test_read_only_roles_run_in_the_main_dir_and_get_no_worktree():
    out, ws = emit_oc(), workspace()
    for role in ("reviewer", "gate"):
        r = dispatch(out, ws, role=role, ticket="TST-6")
        assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r
        assert r["calls"][0]["input"]["query"]["directory"] == str(ws)
    assert "TST-6" not in git("worktree", "list", cwd=ws / "api")


def test_background_dispatch_returns_immediately_with_the_task_id():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="implementer", repo="api", ticket="TST-10", background=True)
    assert [c["op"] for c in r["calls"]] == ["create", "promptAsync"], r
    assert "ses_1" in r["result"]["output"]


# --- dispatch is the only door ---------------------------------------------------------

def test_read_only_agents_deny_dispatch_and_primary_denies_builtin_task():
    out = emit_oc()
    for name in ("reviewer", "gate"):
        text = (out / "agent" / f"{name}.md").read_text()
        assert "dispatch: deny" in text, name
    assert "dispatch: deny" not in (out / "agent" / "implementer.md").read_text()
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["permission"]["task"] == "deny", conf["permission"]


def test_emit_fails_closed_if_a_read_only_role_is_allowed_to_dispatch():
    cfg = cfg_with(lambda c: c["opencode"]["subagents"]["reviewer"]["toolFilter"]["allow"]
                   .append("dispatch"))
    with pytest.raises(SystemExit, match="dispatch"):
        emit_oc(cfg)
