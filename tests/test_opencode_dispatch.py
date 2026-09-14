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
import os
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


def dispatch(out, ws, *seq, env=None, **args):
    """One dispatch (kwargs) or a sequence of dispatches (dicts) in one plugin instance."""
    calls = list(seq) or [args]
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "dispatch.js"), str(ws),
                        json.dumps(calls)], capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
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
    r = dispatch(out, ws,
                 {"role": "implementer", "repo": "api", "ticket": "TST-1"},
                 {"role": "implementer", "ticket": "TST-1", "task_id": "ses_1",
                  "command": "address the review deficiencies"})
    assert [c["op"] for c in r["calls"]] == ["create", "prompt", "prompt"], r
    follow = r["calls"][2]["input"]
    assert follow["path"]["id"] == "ses_1"
    assert "address the review deficiencies" in follow["body"]["parts"][0]["text"]
    # the follow-up is routed to the troop's worktree, same as the first prompt
    wt = r["calls"][0]["input"]["query"]["directory"]
    assert r["calls"][1]["input"]["query"]["directory"] == wt
    assert follow["query"]["directory"] == wt
    trees = [l for l in git("worktree", "list", cwd=ws / "api").splitlines() if "api--TST-1" in l]
    assert len(trees) == 1, trees


def test_prompt_is_routed_to_the_worktree_not_the_orchestrator_dir():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="implementer", repo="web", ticket="TST-11")
    wt = r["calls"][0]["input"]["query"]["directory"]
    assert wt != str(ws) and r["calls"][1]["input"]["query"]["directory"] == wt


def test_unknown_or_foreign_task_id_is_refused():
    out, ws = emit_oc(), workspace()
    for tid in ("ses_parent", "ses_someone_elses"):
        r = dispatch(out, ws, role="implementer", ticket="TST-1", task_id=tid)
        assert r["calls"] == [], r
        assert "task_id" in r["result"]["output"]


def test_task_id_cannot_be_reused_under_a_different_role():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"role": "reviewer", "ticket": "TST-12"},
                 {"role": "implementer", "ticket": "TST-12", "task_id": "ses_1"})
    assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r
    assert "reviewer" in r["result"]["output"] and "implementer" in r["result"]["output"]


def test_second_dispatch_for_the_same_ticket_without_task_id_is_refused():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"role": "implementer", "repo": "api", "ticket": "TST-13"},
                 {"role": "implementer", "repo": "api", "ticket": "TST-13"})
    assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r
    assert "task_id" in r["result"]["output"]


def test_session_create_failure_rolls_the_worktree_back():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="implementer", repo="api", ticket="TST-16",
                 env={"HARNESS_FAIL": "create"})
    assert "failed" in r["result"]["title"], r
    assert "TST-16" not in git("worktree", "list", cwd=ws / "api")
    # and the ticket is dispatchable again
    r = dispatch(out, ws, role="implementer", repo="api", ticket="TST-16")
    assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r


def test_troops_survive_a_restart_of_the_plugin():
    """A new plugin instance (opencode restarted) must still continue a troop by task_id
    and must not strand a ticket whose worktree exists."""
    out, ws = emit_oc(), workspace()
    first = dispatch(out, ws, role="implementer", repo="api", ticket="TST-17")
    wt = first["calls"][0]["input"]["query"]["directory"]
    # new process = new instance: resume works and lands in the same worktree
    r = dispatch(out, ws, role="implementer", ticket="TST-17", task_id="ses_1")
    assert [c["op"] for c in r["calls"]] == ["prompt"], r
    assert r["calls"][0]["input"]["query"]["directory"] == wt
    # a fresh dispatch names the holder instead of refusing blindly
    r = dispatch(out, ws, role="implementer", repo="api", ticket="TST-17")
    assert r["calls"] == [] and "ses_1" in r["result"]["output"], r


def test_background_is_refused_for_read_only_roles():
    """A backgrounded reader cannot write its verdict anywhere (no edit, no tracker
    writes), so the verdict would be unreachable. Only writers may run in background."""
    out, ws = emit_oc(), workspace()
    for role in ("reviewer", "gate"):
        r = dispatch(out, ws, role=role, ticket="TST-18", background=True)
        assert r["calls"] == [] and "background" in r["result"]["output"], (role, r)


def test_parallel_dispatches_in_one_turn_get_separate_worktrees():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"role": "implementer", "repo": "api", "ticket": "TST-19"},
        {"role": "implementer", "repo": "api", "ticket": "TST-20"},
        {"role": "implementer", "repo": "web", "ticket": "TST-21"},
    ]})
    assert sorted(c["op"] for c in r["calls"]) == ["create"] * 3 + ["prompt"] * 3, r
    dirs = {c["input"]["query"]["directory"] for c in r["calls"] if c["op"] == "create"}
    assert len(dirs) == 3 and all(Path(x).is_dir() for x in dirs), dirs
    assert "TST-19" in git("worktree", "list", cwd=ws / "api") and "TST-21" in git("worktree", "list", cwd=ws / "web")
    # every troop is remembered (no lost update between concurrent saves): each resumes
    for tid in ("ses_1", "ses_2", "ses_3"):
        r2 = dispatch(out, ws, role="implementer", ticket="x", task_id=tid)
        assert [c["op"] for c in r2["calls"]] == ["prompt"], (tid, r2)


def test_two_same_turn_dispatches_for_one_ticket_land_one_writer_in_one_worktree():
    """The stale-snapshot race: both dispatches in one turn snapshot an EMPTY registry
    (a troop is only recorded AFTER session.create), so holderOf sees no holder for
    either. Without an in-flight reservation the first caller creates the tree and yields
    at its first await; the second then finds the tree on disk, takes the reuse path, and
    both become writers in ONE working tree. The module-level claim serializes them: one
    writer, one worktree; the sibling is refused and told to continue by task_id."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"role": "implementer", "repo": "api", "ticket": "TST-22"},
        {"role": "implementer", "repo": "api", "ticket": "TST-22"},
    ]})
    # (a) exactly one of the two actually created a session in the worktree
    creates = [c for c in r["calls"] if c["op"] == "create"]
    assert len(creates) == 1, r
    # (b) the other result is a refuse that names the create-in-flight / continue path
    refuses = [x for x in r["results"]
               if "already creating" in x["output"] and "task_id" in x["output"]]
    assert len(refuses) == 1, r
    # and exactly one winner reports a live task_id
    winners = [x for x in r["results"] if "task_id=ses_1" in x["output"]]
    assert len(winners) == 1, r
    # (c) only ONE worktree directory exists under .worktrees for that (repo, ticket)
    trees = [p for p in (ws / ".worktrees").iterdir() if p.name.startswith("api--TST-22")]
    assert len(trees) == 1, trees
    assert "TST-22" in git("worktree", "list", cwd=ws / "api")


def test_sdk_error_is_reported_not_swallowed():
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, role="reviewer", ticket="TST-14", env={"HARNESS_FAIL": "prompt"})
    assert "failed" in r["result"]["title"] and "no such session" in r["result"]["output"], r


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

def test_unknown_role_is_refused_including_prototype_keys():
    out, ws = emit_oc(), workspace()
    for role in ("general", "constructor", "__proto__", "toString"):
        r = dispatch(out, ws, role=role, repo="api", ticket="TST-5")
        assert r["calls"] == [], (role, r)
        assert "role" in r["result"]["output"]


def test_repo_cannot_escape_the_workspace():
    out, ws = emit_oc(), workspace()
    outside = Path(tempfile.mkdtemp(prefix="outside-")) / "repo"
    outside.mkdir(); git("init", "-q", cwd=outside)
    rel = os.path.relpath(outside, ws)
    for repo in (rel, str(outside), "api/../../x"):
        r = dispatch(out, ws, role="implementer", repo=repo, ticket="TST-15")
        assert r["calls"] == [], (repo, r)
    assert not (ws / ".worktrees").exists()


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
        assert "bash: deny" not in text, f"{name}: bash must be an allowlist, not a blanket deny"
    # the swarm is flat: a troop cannot spawn troops
    assert "dispatch: deny" in (out / "agent" / "implementer.md").read_text()
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["permission"]["task"] == "deny", conf["permission"]


def test_emit_fails_closed_if_a_read_only_role_is_allowed_to_dispatch():
    cfg = cfg_with(lambda c: c["opencode"]["subagents"]["reviewer"]["toolFilter"]["allow"]
                   .append("dispatch"))
    with pytest.raises(SystemExit, match="dispatch"):
        emit_oc(cfg)
