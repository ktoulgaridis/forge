#!/usr/bin/env python3
"""The emitted opencode `dispatch` tool — the orchestrator's thin launcher (ADR 0017).

The emitted plugin carries BOTH host entrypoints (back/forward compatibility):
every behavioural test below runs against the 1.x path (`server()`) AND the 2.x
path (`setup()`), so a host-specific regression cannot hide behind "the other
host still works". The shared decision core (model policy, task_id handles, the
per-(repo, ticket) worktree grant) must behave identically through both; only the
session-call shapes differ, via the per-host accessors.

The launcher is a THIN, NON-BLOCKING primitive:

  - it fans out ONE writer worker per call, as a ROOT session (no parentID) created
    at a git worktree of `repo` — one per (repo, ticket) — running the graph-agent
    you name (`agent`), and returns the task_id AT ONCE;
  - a DETACHED waiter then blocks to the worker's idle, reads its result, and posts a
    <run-closed> line back to the orchestrator with resume:false (2.x) / a noReply
    promptAsync (1.x) — so completion is poll-free and surfaces next turn;
  - `task_id` resumes the same worker (implement → review → fail → same worker again),
    with no new worktree and no new session; a resume re-prompts and posts its own close;
  - two same-turn dispatches for one (repo, ticket) collapse to ONE worktree and ONE
    writer (in-flight claim + persisted registry);
  - the model policy (one provider, a banned list) is enforced before anything is
    created; an unset model is OMITTED so the agent's own default (the org floor) applies.

Validating runs do NOT come through dispatch — they go through the native subagent
tool (`subagent_type: "validate"`); dispatch owns only the writer worktree grant.

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
ORG_FLOOR = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


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
    """One dispatch (kwargs) or a sequence of calls (dicts) in one plugin instance."""
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
    """Where a worker's session is created (its worktree)."""
    return inp["query"]["directory"] if host == "v1" else inp["location"]["directory"]


def is_postback(c, host):
    """The <run-closed> postback to the orchestrator: a resume:false prompt to the parent
    (2.x) / a noReply promptAsync to the parent (1.x). NOT a prompt to a worker."""
    if host == "v1":
        return c["op"] == "promptAsync" and c["input"]["path"]["id"] == "ses_parent"
    return c["op"] == "prompt" and c["input"].get("sessionID") == "ses_parent"


def run_calls(r, host):
    """The workers' own ops, with the closing postback(s) filtered out."""
    return [c for c in r["calls"] if not is_postback(c, host)]


def run_ops(r, host):
    """Multiset (sorted) of the workers' ops — the detached waiter means wait/context/
    postback interleave nondeterministically across dispatches, so we assert the SET of
    calls that happened, not a brittle order."""
    return sorted(c["op"] for c in run_calls(r, host))


def sync_ops(host):
    """The ops one worker launch produces (postback excluded): create + the worker prompt
    inline, then wait + result read on the detached waiter (2.x reads them itself; 1.x's
    single prompt call blocks to completion server-side)."""
    return sorted(["create", "prompt"]) if host == "v1" else sorted(["create", "prompt", "wait", "context"])


def worker_prompts(r, host):
    """The prompt inputs directed at a WORKER (not the parent postback), in call order."""
    return [c["input"] for c in run_calls(r, host) if c["op"] in ("prompt", "promptAsync")]


def prompt_text(inp, host):
    return inp["body"]["parts"][0]["text"] if host == "v1" else inp["text"]


def prompt_session(inp, host):
    return inp["path"]["id"] if host == "v1" else inp["sessionID"]


def postbacks(r, host):
    return [c for c in r["calls"] if is_postback(c, host)]


def postback_text(c, host):
    return c["input"]["body"]["parts"][0]["text"] if host == "v1" else c["input"]["text"]


def result_text(res, host):
    """What the caller reads from a tool result, per host: the native shape of each host's
    runtime. 1.x: the `output` string. 2.x: the `content` text — the native no-schema
    result (a 2.x result carrying `output` DIES: runtime.ts:46, forge#25)."""
    return res["output"] if host == "v1" else res["content"]


def result_title(res, host):
    """The result's display title: 1.x `title`; 2.x `metadata.title`."""
    return res["title"] if host == "v1" else res["metadata"]["title"]


# --- the writer gets a worktree in the right repo -------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_worker_runs_in_its_own_worktree_in_the_named_repo(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="web", ticket="TST-7", host=host)
    assert run_ops(r, host) == sync_ops(host), r
    wt = create_dir(creates(r, host)[0], host)
    assert Path(wt).is_dir() and wt.startswith(str(ws)), wt
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "TST-7"
    # the worktree belongs to `web`, not `api`
    assert wt in git("worktree", "list", cwd=ws / "web")
    assert wt not in git("worktree", "list", cwd=ws / "api")
    if host == "v1":
        assert worker_prompts(r, host)[0]["body"]["agent"] == "build"
    else:
        ci = creates(r, host)[0]
        assert ci["agent"] == "build"
        # unset model arg → OMITTED, so the agent's own default (the org floor) applies —
        # the launcher pins no hardcoded default of its own (ADR 0017 model floor).
        assert "model" not in ci, ci
        assert ci["metadata"]["run"] is True
        assert ci["metadata"]["ticket"] == "TST-7"
        assert "parent" not in ci["metadata"], ci  # workers are ROOTS — no parent link
    assert "TST-7" in prompt_text(worker_prompts(r, host)[0], host)
    # the orchestrator gets the task_id to resume NOW; the result surfaces via the postback
    assert "ses_1" in result_text(r["result"], host) and "launched" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_worker_is_a_root_session_with_no_parent(host):
    """ADR 0017: workers are ROOT sessions (no parentID), so the native session list is the
    fleet view. Neither host may link the worker to the orchestrator at create."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-50", host=host)
    ci = creates(r, host)[0]
    if host == "v1":
        assert "parentID" not in ci["body"], ci
    else:
        assert "parent" not in ci["metadata"], ci


@pytest.mark.parametrize("host", HOSTS)
def test_repo_is_required_when_the_workspace_is_ambiguous(host):
    out, ws = emit_oc(), workspace(("api", "web"))
    r = dispatch(out, ws, agent="build", ticket="TST-8", host=host)
    assert r["calls"] == [], r
    assert "repo" in result_text(r["result"], host).lower()


@pytest.mark.parametrize("host", HOSTS)
def test_single_repo_workspace_needs_no_repo_argument(host):
    out, ws = emit_oc(), workspace(("api",))
    r = dispatch(out, ws, agent="build", ticket="TST-9", host=host)
    assert run_ops(r, host) == sync_ops(host), r
    assert "TST-9" in git("worktree", "list", cwd=ws / "api")


# --- feedback loop: same worker, follow-up command --------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_task_id_resumes_the_same_session_without_a_new_worktree(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"agent": "build", "repo": "api", "ticket": "TST-1"},
                 {"agent": "build", "ticket": "TST-1", "task_id": "ses_1",
                  "command": "address the review deficiencies"}, host=host)
    # fresh (create + prompt [+ wait + context]) then resume (prompt [+ wait + context]) —
    # one create, two worker prompts; the detached tails interleave, so assert the multiset
    if host == "v1":
        assert run_ops(r, host) == sorted(["create", "prompt", "prompt"]), r
    else:
        assert run_ops(r, host) == sorted(["create", "prompt", "wait", "context",
                                           "prompt", "wait", "context"]), r
    follow = worker_prompts(r, host)[1]
    assert prompt_session(follow, host) == "ses_1"
    assert "address the review deficiencies" in prompt_text(follow, host)
    # the follow-up lands in the worker's session/worktree — no second tree
    wt = create_dir(creates(r, host)[0], host)
    if host == "v1":
        assert worker_prompts(r, host)[0]["query"]["directory"] == wt
        assert follow["query"]["directory"] == wt
    else:
        assert prompt_session(worker_prompts(r, host)[0], host) == "ses_1"
    trees = [l for l in git("worktree", "list", cwd=ws / "api").splitlines() if "api--TST-1" in l]
    assert len(trees) == 1, trees


@pytest.mark.parametrize("host", HOSTS)
def test_prompt_is_routed_to_the_worktree_not_the_orchestrator_dir(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="web", ticket="TST-11", host=host)
    wt = create_dir(creates(r, host)[0], host)
    assert wt != str(ws)
    if host == "v1":
        # `query.directory` on every worker call routes it to the worktree, not the orch dir
        assert worker_prompts(r, host)[0]["query"]["directory"] == wt


@pytest.mark.parametrize("host", HOSTS)
def test_unknown_or_foreign_task_id_is_refused(host):
    out, ws = emit_oc(), workspace()
    for tid in ("ses_parent", "ses_someone_elses"):
        r = dispatch(out, ws, agent="build", ticket="TST-1", task_id=tid, host=host)
        assert r["calls"] == [], r
        assert "task_id" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_second_dispatch_for_the_same_ticket_without_task_id_is_refused(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"agent": "build", "repo": "api", "ticket": "TST-13"},
                 {"agent": "build", "repo": "api", "ticket": "TST-13"}, host=host)
    # the first launched; the second is refused with the holder's task_id (no calls of its own)
    assert run_ops(r, host) == sync_ops(host), r
    assert "task_id" in result_text(r["result"], host)


@pytest.mark.parametrize("host", HOSTS)
def test_session_create_failure_rolls_the_worktree_back(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-16",
                 env={"HARNESS_FAIL": "create"}, host=host)
    assert "failed" in result_title(r["result"], host), r
    assert "TST-16" not in git("worktree", "list", cwd=ws / "api")
    # and the ticket is dispatchable again
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-16", host=host)
    assert run_ops(r, host) == sync_ops(host), r


@pytest.mark.parametrize("host", HOSTS)
def test_runs_survive_a_restart_of_the_plugin(host):
    """A new plugin instance (opencode restarted) must still continue a worker by task_id
    and must not strand a ticket whose worktree exists."""
    out, ws = emit_oc(), workspace()
    first = dispatch(out, ws, agent="build", repo="api", ticket="TST-17", host=host)
    wt = create_dir(creates(first, host)[0], host)
    # new process = new instance: resume works and lands in the same session/worktree
    r = dispatch(out, ws, agent="build", ticket="TST-17", task_id="ses_1", host=host)
    if host == "v1":
        assert run_ops(r, host) == ["prompt"], r
        assert worker_prompts(r, host)[0]["query"]["directory"] == wt
    else:
        assert run_ops(r, host) == sorted(["prompt", "wait", "context"]), r
        assert prompt_session(worker_prompts(r, host)[0], host) == "ses_1"
    # a fresh dispatch names the holder instead of refusing blindly
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-17", host=host)
    assert r["calls"] == [] and "ses_1" in result_text(r["result"], host), r


@pytest.mark.parametrize("host", HOSTS)
def test_dispatch_returns_immediately_with_the_task_id(host):
    """Non-blocking: the launcher creates + prompts the worker and returns the task_id at
    once — the orchestrator never blocks on the worker's turn."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-10", host=host)
    assert run_ops(r, host) == sync_ops(host), r
    assert "ses_1" in result_text(r["result"], host) and "launched" in result_text(r["result"], host)


# --- same-turn width: parallel dispatches ---------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_parallel_dispatches_in_one_turn_get_separate_worktrees(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"agent": "build", "repo": "api", "ticket": "TST-19"},
        {"agent": "build", "repo": "api", "ticket": "TST-20"},
        {"agent": "build", "repo": "web", "ticket": "TST-21"},
    ]}, host=host)
    if host == "v1":
        assert run_ops(r, host) == ["create"] * 3 + ["prompt"] * 3, r
    else:
        assert run_ops(r, host) == \
            ["context"] * 3 + ["create"] * 3 + ["prompt"] * 3 + ["wait"] * 3, r
    dirs = {create_dir(c, host) for c in creates(r, host)}
    assert len(dirs) == 3 and all(Path(x).is_dir() for x in dirs), dirs
    assert "TST-19" in git("worktree", "list", cwd=ws / "api") and "TST-21" in git("worktree", "list", cwd=ws / "web")
    # every worker is remembered (no lost update between concurrent saves): each resumes
    for tid in ("ses_1", "ses_2", "ses_3"):
        r2 = dispatch(out, ws, agent="build", ticket="x", task_id=tid, host=host)
        resumed = ["prompt"] if host == "v1" else sorted(["prompt", "wait", "context"])
        assert run_ops(r2, host) == resumed, (tid, r2)


@pytest.mark.parametrize("host", HOSTS)
def test_two_same_turn_dispatches_for_one_ticket_land_one_writer_in_one_worktree(host):
    """The stale-snapshot race: both dispatches in one turn snapshot an EMPTY registry
    (a worker is only recorded AFTER session.create), so holderOf sees no holder for
    either. Without an in-flight reservation the first caller creates the tree and yields
    at its first await; the second then finds the tree on disk, takes the reuse path, and
    both become writers in ONE working tree. The module-level claim serializes them: one
    writer, one worktree; the sibling is refused and told to continue by task_id."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, {"parallel": [
        {"agent": "build", "repo": "api", "ticket": "TST-22"},
        {"agent": "build", "repo": "api", "ticket": "TST-22"},
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
    """A worker failure is never swallowed — it reaches the orchestrator. 2.x awaits the
    prompt admit, so the error surfaces in the immediate result; 1.x fires the worker prompt
    and returns at once (it cannot block), so the error rides the <run-closed> postback."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-14",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    if host == "v2":
        assert "failed" in result_title(r["result"], host), r
        assert "no such session" in result_text(r["result"], host), r
    else:
        posts = postbacks(r, host)
        assert posts, f"a worker failure posted nothing back: {r['calls']}"
        text = postback_text(posts[0], host)
        assert "error" in text and "no such session" in text, text


# --- the orchestrator picks the model per task, inside the org policy ------------

@pytest.mark.parametrize("host", HOSTS)
def test_allowed_model_is_forwarded_per_call(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-2",
                 model="amazon-bedrock/us.openai.gpt-5-2025-08-07", host=host)
    if host == "v1":
        # the worker's own prompt carries the model
        body = worker_prompts(r, host)[0]["body"]
        assert body["model"] == {"providerID": "amazon-bedrock",
                                 "modelID": "us.openai.gpt-5-2025-08-07"}, body
    else:
        ci = creates(r, host)[0]
        assert ci["model"] == {"providerID": "amazon-bedrock",
                               "id": "us.openai.gpt-5-2025-08-07"}, ci


@pytest.mark.parametrize("host", HOSTS)
def test_variant_is_forwarded_on_the_2x_create(host):
    """model/variant is a launch parameter (ADR 0017 §4): the 2.x create carries the
    variant alongside the model id."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-24",
                 model="amazon-bedrock/us.openai.gpt-5-2025-08-07", variant="thinking", host=host)
    if host == "v2":
        ci = creates(r, host)[0]
        assert ci["model"].get("variant") == "thinking", ci


@pytest.mark.parametrize("host", HOSTS)
def test_unset_model_is_omitted_so_the_agent_default_applies(host):
    """The launcher pins NO hardcoded default (ADR 0017 model floor decision): an unset
    model is omitted from the create/prompt, so the graph-agent's own frontmatter default
    (the org floor) governs — never a launcher-baked constant."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-23", host=host)
    if host == "v1":
        assert "model" not in worker_prompts(r, host)[0]["body"], worker_prompts(r, host)[0]
    else:
        assert "model" not in creates(r, host)[0], creates(r, host)[0]


@pytest.mark.parametrize("host", HOSTS)
def test_banned_model_is_refused_before_anything_is_created(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-3",
                 model="amazon-bedrock/us.anthropic.claude-haiku-4-5", host=host)
    assert r["calls"] == [], r
    assert "haiku" in result_text(r["result"], host)
    assert "TST-3" not in git("worktree", "list", cwd=ws / "api")


@pytest.mark.parametrize("host", HOSTS)
def test_model_outside_the_org_provider_is_refused(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-4",
                 model="anthropic/claude-sonnet-4-5", host=host)
    assert r["calls"] == [], r
    assert "amazon-bedrock" in result_text(r["result"], host)


# --- fail closed on a missing envelope ------------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_dispatch_needs_a_ticket_or_a_task_id(host):
    """Fail closed with neither a ticket (a fresh worker's envelope) nor a task_id (a
    worker to continue): nothing is created, no worktree is made."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="build", host=host)
    assert r["calls"] == [], r
    assert "ticket" in result_text(r["result"], host), r
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_a_missing_agent_is_refused(host):
    """The graph-agent is required — the launcher names the worker's agent at create. A
    call with no agent fails closed, nothing created."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, ticket="TST-5", repo="api", host=host)
    assert r["calls"] == [], r
    assert "agent" in result_text(r["result"], host)
    assert not (ws / ".worktrees").exists()


@pytest.mark.parametrize("host", HOSTS)
def test_repo_cannot_escape_the_workspace(host):
    out, ws = emit_oc(), workspace()
    outside = Path(tempfile.mkdtemp(prefix="outside-")) / "repo"
    outside.mkdir(); git("init", "-q", cwd=outside)
    rel = os.path.relpath(outside, ws)
    for repo in (rel, str(outside), "api/../../x"):
        r = dispatch(out, ws, agent="build", repo=repo, ticket="TST-15", host=host)
        assert r["calls"] == [], (repo, r)
    assert not (ws / ".worktrees").exists()


# --- the artifact itself: ONE tool, both entrypoints -----------------------------

def test_the_emitted_plugin_carries_one_tool_and_both_entrypoints():
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    for needle in ("async setup(", "async server(", "id: "):
        assert needle in src, f"dispatch.js lost {needle!r}"
    # the 1.x SDK must be a DYNAMIC import only — a static one fails the whole module on 2.x
    assert 'from "@opencode-ai/plugin"' not in src, "static 1.x SDK import would break 2.x"
    assert 'import("@opencode-ai/plugin")' in src
    # exactly ONE tool now — the retired delegation-store readers are gone (ADR 0017)
    assert 'name: "dispatch"' in src
    for gone in ('name: "dispatch_read"', 'name: "dispatch_list"',
                 "dispatch_read: tool(", "dispatch_list: tool("):
        assert gone not in src, f"dispatch.js still carries the retired {gone!r}"
    rem = (out / "plugin" / "reminders.js").read_text()
    for needle in ("async setup(", "async server(", 'hook("compaction"'):
        assert needle in rem, f"reminders.js lost {needle!r}"


def test_the_v2_path_marshals_the_tool_result_to_the_native_shape():
    """forge#25, emit level: a 2.x tool result carrying `output` while the tool definition
    declares no output schema DIES (core/src/tool/runtime.ts:46). The 2.x path must marshal
    the shared `{title, output}` result to the native no-schema shape: text under `content`,
    the title under `metadata.title`. The sole tool marshals at ONE boundary — the
    registration site, not the handler body. The 1.x path keeps the native {title, output}."""
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    wrapped = src.count("execute: native(")
    assert wrapped == 1, f"expected the one 2.x tool marshaled, found {wrapped}"
    assert "metadata: { title: r.title }" in src, "2.x marshal must carry the title in metadata"
    # the 1.x path is untouched: server() still returns the 1.x-native {title, output}
    assert 'output: `task_id=${sessionID} launched;' in src


@pytest.mark.parametrize("host", HOSTS)
def test_every_result_is_the_native_shape_and_none_dies_on_the_2x_runtime(host):
    """forge#25, behaviour: no dispatch result may carry `output` on the 2.x host (the
    runtime's die condition) and the text + title must survive in the native shape; 1.x
    keeps {title, output}. Covers the success, the refuse and the failure paths — the
    reasons are the orchestrator's steering."""
    out, ws = emit_oc(), workspace()
    # success: a launch returns the task_id + a launched notice
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-25", host=host)
    res = r["result"]
    assert "died" not in res, res
    assert "ses_1" in result_text(res, host), res
    assert result_title(res, host) == "build TST-25", res
    # refuse: the reason survives
    r = dispatch(out, ws, agent="build", host=host)
    res = r["result"]
    assert "died" not in res and "ticket" in result_text(res, host), res
    assert result_title(res, host) == "dispatch refused", res
    # failure: the error survives (immediately on 2.x; via the postback on 1.x)
    r = dispatch(out, ws, agent="build", repo="api", ticket="TST-26",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    res = r["result"]
    assert "died" not in res, res
    if host == "v2":
        assert "failed" in result_title(res, host) and "no such session" in result_text(res, host), res
    else:
        posts = postbacks(r, host)
        assert posts and "no such session" in postback_text(posts[0], host), r


# --- dispatch is agent-agnostic; the spawnable set is allowlisted elsewhere ------------

def test_dispatch_carries_no_node_kind_table():
    """ADR 0017: dispatch is a thin launcher, agent-agnostic — it takes an `agent` arg and
    has NO baked node-kind table (the retired produce/validate NODE_KINDS). Node kinds live
    in the graph (opencode.nodes), and validate routing is the skill's/native tool's job."""
    out = emit_oc()
    src = (out / "plugin" / "dispatch.js").read_text()
    assert "NODE_KINDS" not in src, "dispatch still bakes a node-kind table"
    assert 'name: "dispatch"' in src
    assert "agent: { type:" in src or "agent: tool.schema.string()" in src, \
        "dispatch does not take an `agent` argument"


def test_validate_runs_deny_dispatch_and_the_spawnable_set_is_allowlisted():
    """The validating boundary lives in the validating agent's own frontmatter (the native
    tool derives the child session's permissions from it), the validating agent denies
    `dispatch` (no laundering a write through a child run), and the org config's `task` rule
    allowlists exactly the spawnable set under a '*': deny."""
    out = emit_oc()
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
