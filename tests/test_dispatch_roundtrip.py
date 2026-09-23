#!/usr/bin/env python3
"""Acceptance tests for the dispatch round trip (ADR 0017).

The launcher is non-blocking and poll-free: it returns the task_id at once, and a
DETACHED waiter posts a <run-closed> line back to the orchestrator when the worker
goes idle — with `resume: false` (2.x) / a `noReply` promptAsync (1.x), so the notice
surfaces on the orchestrator's next turn without waking one now. The postback fires on
EVERY terminal state, INCLUDING error finishes (a silent death would leave the
orchestrator believing the worker still lives).

Workers are ROOT sessions (no parentID / no metadata.parent) — the native session list
is the fleet view, so there is no parent link to assert; there is its absence.

Each test below holds one piece of the round trip to a checkable claim, on BOTH host
entrypoints (1.x `server()` and 2.x `setup()`):

  - a dispatch-created worker is a ROOT (no parentID on 1.x, no metadata.parent on 2.x);
  - a <run-closed> line posts back to the parent on completion AND on error, carrying the
    worker's status, its ticket, and its result line — via resume:false (2.x) / noReply (1.x);
  - a resume (task_id) re-prompts and posts its OWN close (each prompt is a fresh turn the
    original launch's waiter cannot catch).

Run:  uv run --with pytest --with pyyaml pytest tests/test_dispatch_roundtrip.py -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
from test_opencode_dispatch import (  # noqa: E402
    HOSTS, dispatch, emit_oc, workspace, creates, result_text,
    postbacks, postback_text,
)

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node required")


# --- a dispatch worker is a ROOT ------------------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_a_ticketed_worker_is_a_root_and_carries_its_ticket(host):
    """ADR 0017 retires the sidebar's parentID/metadata.parent grouping: workers are roots,
    the native session list is the fleet view. The create carries no parent link; the
    ticket still labels the run (2.x metadata)."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-40", host=host)
    ci = creates(r, host)[0]
    if host == "v1":
        assert "parentID" not in ci["body"], ci
    else:
        assert "parent" not in ci["metadata"], ci
        assert ci["metadata"]["ticket"] == "TST-40", ci


# --- the closing message posts back, on completion AND on error ------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_a_run_posts_its_closing_message_back_to_the_parent(host):
    """EVERY worker posts its <run-closed> line to the parent — the orchestrator learns the
    worker finished without polling. 2.x delivers it as a prompt with resume:false (admit,
    no wake); 1.x as a noReply promptAsync."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-41", host=host)
    posts = postbacks(r, host)
    assert posts, f"no closing message posted to the parent: {r['calls']}"
    text = postback_text(posts[0], host)
    assert "TST-41" in text and "complete" in text, text
    assert "PR https://x/pr/1" in text, text  # the result line rides the postback
    # 2.x admits the line WITHOUT scheduling a turn — resume:false is the no-wake contract
    if host == "v2":
        assert posts[0]["input"].get("resume") is False, posts[0]["input"]
    else:
        assert posts[0]["input"]["body"].get("noReply") is True, posts[0]["input"]


@pytest.mark.parametrize("host", HOSTS)
def test_an_error_finish_posts_back_too(host):
    """A silent death teaches the orchestrator nothing — error closes are exactly when the
    postback matters: the closing line must fire on error finishes, carrying the error."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, agent="builder", repo="api", ticket="TST-42",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    posts = postbacks(r, host)
    assert posts, f"an error finish posted NOTHING to the parent: {r['calls']}"
    text = postback_text(posts[0], host)
    assert "TST-42" in text and "error" in text, text
    assert "no such session" in text, text  # the error itself rides the postback


@pytest.mark.parametrize("host", HOSTS)
def test_a_resume_posts_its_own_close(host):
    """Non-blocking makes every prompt its own turn: the original launch's detached waiter
    already resolved, so a resume (task_id) must post its OWN <run-closed> — otherwise the
    orchestrator never learns the resumed turn finished. Two prompts → two postbacks."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"agent": "builder", "repo": "api", "ticket": "TST-44"},
                 {"agent": "builder", "ticket": "TST-44", "task_id": "ses_1",
                  "command": "address the review deficiencies"}, host=host)
    posts = postbacks(r, host)
    assert len(posts) == 2, f"expected a close per prompt (fresh + resume): {[p['input'] for p in posts]}"
    assert all("TST-44" in postback_text(p, host) for p in posts), posts
