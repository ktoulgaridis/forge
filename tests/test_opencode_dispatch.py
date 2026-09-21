#!/usr/bin/env python3
"""The emitted opencode `dispatch` tool — the orchestrator's primitive.

The emitted plugin carries BOTH host entrypoints (back/forward compatibility):
every test below runs against the 1.x path (`server()`) AND the 2.x path
(`setup()`), so a host-specific regression cannot hide behind "the other host
still works". The shared decision core (role allowlist, model policy, task_id
handles, ticketed/ad-hoc fork, worktree grant) must behave identically through
both; only the session-call shapes differ, via the per-host accessors.

Coverage, in order:

  - ticketed: a writer gets its own worktree in the RIGHT repo, on a branch named
    after the ticket, prompted there with the ticket as the whole envelope;
  - feedback loop: a follow-up by task_id resumes the same run — no new worktree,
    no new session (implement → review → fail → same implementer again);
  - ad-hoc (ticketless): read-only, in place, may background; the result is
    persisted to the on-disk delegation store and read back with dispatch_read /
    dispatch_list, surviving compaction and restart;
  - same-turn races: two dispatches for one (repo, ticket) collapse to ONE
    worktree and ONE writer (in-flight claim + persisted registry);
  - the model policy (one provider, a banned list) is enforced before anything
    is created; the tool is the role allowlist;
  - read-only roles cannot background a verdict, and the primary cannot use the
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

HOSTS = ["v1", "v2"]


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


def dispatch(out, ws, *seq, env=None, host="v1", **args):
    """One dispatch (kwargs) or a sequence of calls (dicts) in one plugin instance.

    A dict may name a different tool via `_tool` (e.g. {"_tool": "dispatch_read"}).
    """
    calls = list(seq) or [args]
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "dispatch.js"), str(ws),
                        json.dumps(calls), host], capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


# --- per-host accessors ---------------------------------------------------------------
# The policy is shared; only the session-call shapes differ between hosts.

def creates(r, host):
    """The session.create calls' inputs."""
    return [c["input"] for c in r["calls"] if c["op"] == "create"]


def create_dir(inp, host):
    """Where a run's session is created (the worktree for writers, the dir for readers)."""
    return inp["query"]["directory"] if host == "v1" else inp["location"]["directory"]


def prompt_of(r, i, host):
    """The i-th (0-based) prompt call, in call order."""
    prompts = [c for c in r["calls"] if c["op"] in ("prompt", "promptAsync")]
    return prompts[i]["input"]


def prompt_text(inp, host):
    return inp["body"]["parts"][0]["text"] if host == "v1" else inp["text"]


def prompt_session(inp, host):
    return inp["path"]["id"] if host == "v1" else inp["sessionID"]


def result_text(res, host):
    """What the caller reads from a tool result, per host: the native shape of each
    host's runtime. 1.x: the `output` string. 2.x: the `content` text — the native
    no-schema result (a 2.x result carrying `output` DIES: runtime.ts:46, forge#25)."""
    return res["output"] if host == "v1" else res["content"]


def result_title(res, host):
    """The result's display title: 1.x `title`; 2.x `metadata.title` (the stock 2.x
    TUI renders plugin-tool titles from the tool name/input, so the title rides
    metadata — the side-channel execute.after and the stored tool state carry)."""
    return res["title"] if host == "v1" else res["metadata"]["title"]


def sync_ops(r, host):
    """Ops a synchronous ticketed dispatch produces, per host."""
    if host == "v1":
        return ["create", "prompt"]
    return ["create", "prompt", "wait", "context"]


def adhoc_sync_ops(r, host):
    """Ops a synchronous ad-hoc dispatch produces, per host."""
    return sync_ops(r, host)


# --- the writer gets a worktree in the right repo -------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_implementer_runs_in_its_own_worktree_in_the_named_repo(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="web", ticket="TST-7", host=host)
    assert [c["op"] for c in r["calls"]] == sync_ops(r, host), r
    wt = create_dir(creates(r, host)[0], host)
    assert Path(wt).is_dir() and wt.startswith(str(ws)), wt
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "TST-7"
    # the worktree belongs to `web`, not `api`
    assert wt in git("worktree", "list", cwd=ws / "web")
    assert wt not in git("worktree", "list", cwd=ws / "api")
    ci = creates(r, host)[0]
    if host == "v1":
        assert prompt_of(r, 0, host)["body"]["agent"] == "produce"
    else:
        assert ci["agent"] == "produce"
        assert "model" not in ci  # unset → the agent file's model
        assert ci["metadata"]["run"] is True  # 2.x has no parentID; the run is marked
    assert "TST-7" in prompt_text(prompt_of(r, 0, host), host)
    # the orchestrator gets result lines + the task_id to resume, not the transcript
    assert "ses_1" in result_text(r["result"], host) and "PR https://x/pr/1" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_repo_is_required_when_the_workspace_is_ambiguous(host):
    out, ws = emit_oc(), workspace(("api", "web"))
    r = dispatch(out, ws, node="produce", ticket="TST-8", host=host)
    assert r["calls"] == [], r
    assert "repo" in result_text(r["result"], host).lower()


@pytest.mark.parametrize("host", HOSTS)
def test_single_repo_workspace_needs_no_repo_argument(host):
    out, ws = emit_oc(), workspace(("api",))
    r = dispatch(out, ws, node="produce", ticket="TST-9", host=host)
    assert [c["op"] for c in r["calls"]] == sync_ops(r, host), r
    assert "TST-9" in git("worktree", "list", cwd=ws / "api")


# --- feedback loop: same run, follow-up command ----------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_task_id_resumes_the_same_session_without_a_new_worktree(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"node": "produce", "repo": "api", "ticket": "TST-1"},
                 {"node": "produce", "ticket": "TST-1", "task_id": "ses_1",
                  "command": "address the review deficiencies"}, host=host)
    if host == "v1":
        assert [c["op"] for c in r["calls"]] == ["create", "prompt", "prompt"], r
    else:
        assert [c["op"] for c in r["calls"]] == \
            ["create", "prompt", "wait", "context", "prompt", "wait", "context"], r
    follow = prompt_of(r, 1, host)
    assert prompt_session(follow, host) == "ses_1"
    assert "address the review deficiencies" in prompt_text(follow, host)
    # the follow-up lands in the run's session (routed at create on 2.x; per call on 1.x)
    wt = create_dir(creates(r, host)[0], host)
    if host == "v1":
        assert prompt_of(r, 0, host)["query"]["directory"] == wt
        assert follow["query"]["directory"] == wt
    else:
        assert prompt_session(prompt_of(r, 0, host), host) == "ses_1"
        assert prompt_session(follow, host) == "ses_1"
    trees = [l for l in git("worktree", "list", cwd=ws / "api").splitlines() if "api--TST-1" in l]
    assert len(trees) == 1, trees


@pytest.mark.parametrize("host", HOSTS)
def test_prompt_is_routed_to_the_worktree_not_the_orchestrator_dir(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="web", ticket="TST-11", host=host)
    wt = create_dir(creates(r, host)[0], host)
    assert wt != str(ws)
    if host == "v1":
        assert r["calls"][1]["input"]["query"]["directory"] == wt


@pytest.mark.parametrize("host", HOSTS)
def test_unknown_or_foreign_task_id_is_refused(host):
    out, ws = emit_oc(), workspace()
    for tid in ("ses_parent", "ses_someone_elses"):
        r = dispatch(out, ws, node="produce", ticket="TST-1", task_id=tid, host=host)
        assert r["calls"] == [], r
        assert "task_id" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_task_id_cannot_be_reused_under_a_different_node(host):
    """A task_id is a handle, not a free session: only the node that issued it may
    resume it. Path B: a ticketed validate run no longer exists on dispatch (it is
    refused, routed to the native subagent tool), so the cross-node reuse attempt is
    a validate node trying to resume a PRODUCE run — the refusal must name both."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"node": "produce", "repo": "api", "ticket": "TST-12"},
                 {"node": "validate", "ticket": "TST-12", "task_id": "ses_1"}, host=host)
    assert "validate" in result_text(r["result"], host) and "produce" in result_text(r["result"], host), r


@pytest.mark.parametrize("host", HOSTS)
def test_second_dispatch_for_the_same_ticket_without_task_id_is_refused(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"node": "produce", "repo": "api", "ticket": "TST-13"},
                 {"node": "produce", "repo": "api", "ticket": "TST-13"}, host=host)
    assert [c["op"] for c in r["calls"]] == sync_ops(r, host), r
    assert "task_id" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_session_create_failure_rolls_the_worktree_back(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-16",
                 env={"HARNESS_FAIL": "create"}, host=host)
    assert "failed" in result_title(r["result"], host), r
    assert "TST-16" not in git("worktree", "list", cwd=ws / "api")
    # and the ticket is dispatchable again
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-16", host=host)
    assert [c["op"] for c in r["calls"]] == sync_ops(r, host), r


@pytest.mark.parametrize("host", HOSTS)
def test_runs_survive_a_restart_of_the_plugin(host):
    """A new plugin instance (opencode restarted) must still continue a run by task_id
    and must not strand a ticket whose worktree exists."""
    out, ws = emit_oc(), workspace()
    first = dispatch(out, ws, node="produce", repo="api", ticket="TST-17", host=host)
    wt = create_dir(creates(first, host)[0], host)
    # new process = new instance: resume works and lands in the same session/worktree
    r = dispatch(out, ws, node="produce", ticket="TST-17", task_id="ses_1", host=host)
    if host == "v1":
        assert [c["op"] for c in r["calls"]] == ["prompt"], r
        assert r["calls"][0]["input"]["query"]["directory"] == wt
    else:
        assert [c["op"] for c in r["calls"]] == ["prompt", "wait", "context"], r
        assert prompt_session(r["calls"][0]["input"], host) == "ses_1"
    # a fresh dispatch names the holder instead of refusing blindly
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-17", host=host)
    assert r["calls"] == [] and "ses_1" in result_text(r["result"], host), r


@pytest.mark.parametrize("host", HOSTS)
def test_background_is_refused_for_read_only_nodes(host):
    """A backgrounded reader cannot write its verdict anywhere (no edit, no tracker
    writes), so the verdict would be unreachable. Only writers may run in background."""
    out, ws = emit_oc(), workspace()
    for node in ("validate",):
        r = dispatch(out, ws, node=node, ticket="TST-18", background=True, host=host)
        assert r["calls"] == [] and "background" in result_text(r["result"], host), (node, r)


# --- same-turn width: parallel dispatches ---------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_parallel_dispatches_in_one_turn_get_separate_worktrees(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"node": "produce", "repo": "api", "ticket": "TST-19"},
        {"node": "produce", "repo": "api", "ticket": "TST-20"},
        {"node": "produce", "repo": "web", "ticket": "TST-21"},
    ]}, host=host)
    if host == "v1":
        assert sorted(c["op"] for c in r["calls"]) == ["create"] * 3 + ["prompt"] * 3, r
    else:
        assert sorted(c["op"] for c in r["calls"]) == \
            ["context"] * 3 + ["create"] * 3 + ["prompt"] * 3 + ["wait"] * 3, r
    dirs = {create_dir(c, host) for c in creates(r, host)}
    assert len(dirs) == 3 and all(Path(x).is_dir() for x in dirs), dirs
    assert "TST-19" in git("worktree", "list", cwd=ws / "api") and "TST-21" in git("worktree", "list", cwd=ws / "web")
    # every run is remembered (no lost update between concurrent saves): each resumes
    for tid in ("ses_1", "ses_2", "ses_3"):
        r2 = dispatch(out, ws, node="produce", ticket="x", task_id=tid, host=host)
        resumed = ["prompt"] if host == "v1" else ["prompt", "wait", "context"]
        assert [c["op"] for c in r2["calls"]] == resumed, (tid, r2)


@pytest.mark.parametrize("host", HOSTS)
def test_two_same_turn_dispatches_for_one_ticket_land_one_writer_in_one_worktree(host):
    """The stale-snapshot race: both dispatches in one turn snapshot an EMPTY registry
    (a run is only recorded AFTER session.create), so holderOf sees no holder for
    either. Without an in-flight reservation the first caller creates the tree and yields
    at its first await; the second then finds the tree on disk, takes the reuse path, and
    both become writers in ONE working tree. The module-level claim serializes them: one
    writer, one worktree; the sibling is refused and told to continue by task_id."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"node": "produce", "repo": "api", "ticket": "TST-22"},
        {"node": "produce", "repo": "api", "ticket": "TST-22"},
    ]}, host=host)
    # (a) exactly one of the two actually created a session in the worktree
    creates_calls = [c for c in r["calls"] if c["op"] == "create"]
    assert len(creates_calls) == 1, r
    # (b) the other result is a refuse that names the create-in-flight / continue path
    refuses = [x for x in r["results"]
               if "already creating" in result_text(x, host) and "task_id" in result_text(x, host)]
    assert len(refuses) == 1, r
    # and exactly one winner reports a live task_id
    winners = [x for x in r["results"] if "task_id=ses_1" in result_text(x, host)]
    assert len(winners) == 1, r
    # (c) only ONE worktree directory exists under .worktrees for that (repo, ticket)
    trees = [p for p in (ws / ".worktrees").iterdir() if p.name.startswith("api--TST-22")]
    assert len(trees) == 1, trees
    assert "TST-22" in git("worktree", "list", cwd=ws / "api")


@pytest.mark.parametrize("host", HOSTS)
def test_sdk_error_is_reported_not_swallowed(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-14",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    assert "failed" in result_title(r["result"], host) and "no such session" in result_text(r["result"], host), r


# --- the orchestrator picks the model per task, inside the org policy ------------

@pytest.mark.parametrize("host", HOSTS)
def test_allowed_model_is_forwarded_per_call(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-2",
                 model="amazon-bedrock/us.openai.gpt-5-2025-08-07", host=host)
    if host == "v1":
        body = r["calls"][-1]["input"]["body"]
        assert body["model"] == {"providerID": "amazon-bedrock",
                                 "modelID": "us.openai.gpt-5-2025-08-07"}, body
    else:
        ci = creates(r, host)[0]
        assert ci["model"] == {"providerID": "amazon-bedrock",
                               "id": "us.openai.gpt-5-2025-08-07"}, ci


@pytest.mark.parametrize("host", HOSTS)
def test_banned_model_is_refused_before_anything_is_created(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-3",
                 model="amazon-bedrock/us.anthropic.claude-haiku-4-5", host=host)
    assert r["calls"] == [], r
    assert "haiku" in result_text(r["result"], host)
    assert "TST-3" not in git("worktree", "list", cwd=ws / "api")


@pytest.mark.parametrize("host", HOSTS)
def test_model_outside_the_org_provider_is_refused(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="validate", task="scope the review",
                 model="anthropic/claude-sonnet-4-5", host=host)
    assert r["calls"] == [], r
    assert "amazon-bedrock" in result_text(r["result"], host)


# --- ad-hoc: ticketless, read-only, persisted --------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_adhoc_background_delegation_persists_and_read_returns_it(host):
    """(a) A ticketless ad-hoc task runs read-only in place, persists a titled result to
    the on-disk store keyed by task_id, and dispatch_read blocks until terminal and hands
    back that result — the whole point being that it survives past the turn (and a restart
    or compaction) that launched it."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"node": "validate", "task": "research the auth flow", "background": True},
                 {"_tool": "dispatch_read", "task_id": "ses_1", "timeout_ms": 8000}, host=host)
    ops = [c["op"] for c in r["calls"]]
    assert "create" in ops and "prompt" in ops, r          # a session was created + prompted
    assert not (ws / ".worktrees").exists(), "ad-hoc gets no worktree"
    # the record is persisted to the delegation store, keyed by task_id, and reaches a
    # terminal state on its own (background finalize), not by the reader blocking forever
    rec = json.loads((ws / ".delegations" / "ses_1.json").read_text())
    assert rec["status"] == "complete" and rec["node"] == "validate" and rec["title"], rec
    # dispatch_read returns the persisted result (not a "still running" fallback)
    assert "PR https://x/pr/1" in result_text(r["result"], host) and "ses_1" in result_text(r["result"], host), r
    # dispatch_list sees it too, reading only the on-disk store
    r2 = dispatch(out, ws, {"_tool": "dispatch_list"}, host=host)
    assert "ses_1" in result_text(r2["result"], host) and "complete" in result_text(r2["result"], host), r2


@pytest.mark.parametrize("host", HOSTS)
def test_adhoc_runs_read_only_and_cannot_write(host):
    """(b) An ad-hoc run is read-only: no worktree is created and the write surface is
    denied — enforced, not documented — whatever role it runs as, even a writer role like
    the implementer. The two hosts enforce the same set through their own shapes: 1.x
    gates tools on the prompt body; 2.x denies actions in the session's create
    permissions."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", task="draft the migration plan", host=host)
    assert [c["op"] for c in r["calls"]] == adhoc_sync_ops(r, host), r
    ci = creates(r, host)[0]
    assert create_dir(ci, host) == str(ws)   # main dir, not a worktree
    assert not (ws / ".worktrees").exists()
    if host == "v1":
        tools = r["calls"][1]["input"]["body"]["tools"]
        for cap in ("write", "edit", "patch", "bash", "task", "dispatch"):
            assert tools[cap] is False, (cap, tools)
    else:
        deny = {(p["action"], p["effect"]) for p in ci["permissions"]}
        for action in ("edit", "shell", "subagent", "dispatch"):
            assert (action, "deny") in deny, (action, ci["permissions"])


@pytest.mark.parametrize("host", HOSTS)
def test_adhoc_needs_a_ticket_or_a_task_and_a_ticketless_writer_is_refused(host):
    """(c) Fail closed with neither a ticket nor a task. A writer that wants to background
    still REQUIRES a ticket — a ticketless writer/background is refused, nothing created,
    because there is no envelope and no tracker key to record a result under."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", host=host)
    assert r["calls"] == [], r
    assert "ticket" in result_text(r["result"], host) and "task" in result_text(r["result"], host), r
    r = dispatch(out, ws, node="produce", background=True, host=host)
    assert r["calls"] == [], r
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_adhoc_task_alongside_ticketed_writers_keeps_the_one_worktree_guarantee(host):
    """(d) Ad-hoc mode does not weaken the same-turn one-worktree-per-(repo,ticket) race
    guard: two ticketed writers for one (repo, ticket) still collapse to a single worktree,
    one winner and one refuse-with-task_id, while an ad-hoc task in the same turn takes no
    worktree at all — it lands in the delegation store instead."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"node": "produce", "repo": "api", "ticket": "TST-30"},
        {"node": "produce", "repo": "api", "ticket": "TST-30"},
        {"node": "validate", "task": "scan for similar prior art"},
    ]}, host=host)
    trees = [p for p in (ws / ".worktrees").iterdir() if p.name.startswith("api--TST-30")]
    assert len(trees) == 1, trees                                   # one worktree, not two
    assert "TST-30" in git("worktree", "list", cwd=ws / "api")
    refuses = [x for x in r["results"] if "already creating" in result_text(x, host) and "task_id" in result_text(x, host)]
    assert len(refuses) == 1, r                                     # the sibling was refused
    # the ad-hoc reviewer produced a delegation record, and NO worktree
    assert list((ws / ".delegations").glob("*.json")), "ad-hoc run left no store record"


# --- the tool is the role allowlist ---------------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_unknown_node_is_refused_including_prototype_keys(host):
    out, ws = emit_oc(), workspace()
    for node in ("general", "constructor", "__proto__", "toString"):
        r = dispatch(out, ws, node=node, repo="api", ticket="TST-5", host=host)
        assert r["calls"] == [], (node, r)
        assert "node" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_repo_cannot_escape_the_workspace(host):
    out, ws = emit_oc(), workspace()
    outside = Path(tempfile.mkdtemp(prefix="outside-")) / "repo"
    outside.mkdir(); git("init", "-q", cwd=outside)
    rel = os.path.relpath(outside, ws)
    for repo in (rel, str(outside), "api/../../x"):
        r = dispatch(out, ws, node="produce", repo=repo, ticket="TST-15", host=host)
        assert r["calls"] == [], (repo, r)
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_a_ticketed_validate_dispatch_is_refused_and_routed_to_the_native_tool(host):
    """Path B: a ticketed validate run does not exist on dispatch — validating nodes
    run through the native subagent tool (parentID at create; the read-only boundary
    derives from the validating agent's own frontmatter). The refusal must say so, and
    nothing may be created — no session, no worktree."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="validate", ticket="TST-6", host=host)
    assert r["calls"] == [], r
    txt = result_text(r["result"], host)
    assert "subagent" in txt and "validate" in txt, txt
    assert "TST-6" not in git("worktree", "list", cwd=ws / "api")
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_adhoc_validate_runs_in_the_main_dir_and_gets_no_worktree(host):
    """The read-only run that DOES still ride dispatch: the ad-hoc delegation. It runs
    in place (the main dir), never in a worktree."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="validate", task="scan for similar prior art", host=host)
    assert [c["op"] for c in r["calls"]] == adhoc_sync_ops(r, host), r
    assert create_dir(creates(r, host)[0], host) == str(ws)
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_background_dispatch_returns_immediately_with_the_task_id(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-10",
                 background=True, host=host)
    if host == "v1":
        assert [c["op"] for c in r["calls"]] == ["create", "promptAsync"], r
    else:
        # 2.x background = admit the prompt and return; no wait, no context read
        assert [c["op"] for c in r["calls"]] == ["create", "prompt"], r
    assert "ses_1" in result_text(r["result"], host)


# --- the artifact itself: both entrypoints, one file -----------------------------

def test_the_emitted_plugin_carries_both_entrypoints():
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    for needle in ("async setup(", "async server(", "id: "):
        assert needle in src, f"dispatch.js lost {needle!r}"
    # the 1.x SDK must be a DYNAMIC import only — a static one fails the whole module on 2.x
    assert 'from "@opencode-ai/plugin"' not in src, "static 1.x SDK import would break 2.x"
    assert 'import("@opencode-ai/plugin")' in src
    # the full tool family is registered through BOTH entrypoints
    for needle in ('name: "dispatch"', 'name: "dispatch_read"', 'name: "dispatch_list"',
                   "dispatch_read: tool(", "dispatch_list: tool("):
        assert needle in src, f"dispatch.js lost tool {needle!r}"
    rem = (out / "plugin" / "reminders.js").read_text()
    for needle in ("async setup(", "async server(", 'hook("compaction"'):
        assert needle in rem, f"reminders.js lost {needle!r}"


def test_the_v2_path_marshals_every_tool_result_to_the_native_shape():
    """forge#25, emit level: a 2.x tool result carrying `output` while the tool
    definition declares no output schema DIES (2.0.8 core/src/tool/runtime.ts:46)
    — every dispatch result was destroyed on 2.x. The 2.x path must marshal the
    shared `{title, output}` results to the native no-schema shape: text under
    `content`, the title under `metadata.title` (probed live on 2.0.8: the
    `{content, metadata}` shape survives and the caller receives the content
    verbatim; a declared JSON-Schema `output` adds no validation — encodeOutput
    only checks JSON-ness — and still drops the title). All THREE tools marshal,
    at ONE boundary: the registration sites, not the handler bodies."""
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    wrapped = src.count("execute: native(")
    assert wrapped == 3, f"expected all three 2.x tools marshaled, found {wrapped}"
    assert "metadata: { title: r.title }" in src, "2.x marshal must carry the title in metadata"
    # the 1.x path is untouched: server() still returns the 1.x-native {title, output}
    assert 'output: `task_id=${sessionID}\\n${lastTextOf(res) || "(no result lines)"}`' in src


# --- the result survives the 2.x runtime (forge#25) -----------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_every_result_is_the_native_shape_and_none_dies_on_the_2x_runtime(host):
    """forge#25, behaviour: no dispatch-family result may carry `output` on the 2.x
    host (the runtime's die condition) and the text + title must survive in the
    native shape; 1.x keeps {title, output} byte-for-byte. Covers the success, the
    refuse and the failure paths — the reasons are the orchestrator's steering."""
    out, ws = emit_oc(), workspace()
    # success: a ticketed dispatch returns result lines + the task_id
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-25", host=host)
    res = r["result"]
    assert "died" not in res, res
    assert "ses_1" in result_text(res, host), res
    assert result_title(res, host) == "produce TST-25", res
    # refuse: the reason survives
    r = dispatch(out, ws, node="produce", host=host)
    res = r["result"]
    assert "died" not in res and "ticket" in result_text(res, host), res
    assert result_title(res, host) == "dispatch refused", res
    # failure: the error survives
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-26",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    res = r["result"]
    assert "died" not in res and "failed" in result_title(res, host), res
    assert "no such session" in result_text(res, host), res
    # the read/list tools marshal through the same boundary
    r = dispatch(out, ws,
                 {"node": "validate", "task": "probe the shape", "background": True},
                 {"_tool": "dispatch_read", "task_id": "ses_1", "timeout_ms": 8000}, host=host)
    res = r["result"]
    assert "died" not in res and "ses_1" in result_text(res, host), res


# --- dispatch is the only door ---------------------------------------------------------

def test_validate_runs_deny_dispatch_and_the_spawnable_set_is_allowlisted():
    """The node-level successor of the cast's per-role deny assertions (ADR 0001,
    Path B): the validating deny set lives in the validating agent's own frontmatter
    (the native tool derives the child session's permissions from it), the validating
    agent denies `dispatch` (no laundering a write through a child run), and the org
    config's `task` rule allowlists exactly the spawnable set under a '*': deny."""
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    assert '"dispatch"' in src and '"validate"' in src
    conf = json.loads((out / "opencode.json").read_text())
    task = conf["permission"]["task"]
    assert isinstance(task, dict) and task.get("*") == "deny", task
    assert task.get("build") == "allow" and task.get("validate") == "allow", task
    # the validating agent's own frontmatter denies dispatch — no write laundering
    import yaml
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    assert fm["permission"].get("dispatch") == "deny", fm["permission"]


def test_emit_fails_closed_if_a_validate_node_is_allowed_to_dispatch():
    cfg = cfg_with(lambda c: c["opencode"]["nodes"]["review"]["read_surface"]
                   .append("dispatch"))
    with pytest.raises(SystemExit, match="dispatch"):
        emit_oc(cfg)
