#!/usr/bin/env python3
"""Acceptance tests for the dispatch round trip (forge#28, step 3).

The maintainer's ruling: browsing covers BOTH engines — dispatch children carry
`metadata: { parent: <orchestrator sessionID>, ticket }` at create; the sidebar
groups on `parentID ?? metadata.parent`. And the closing message posts back to
the parent on EVERY terminal state — INCLUDING error finishes (the astra
retention death was silent: the orchestrator learned nothing; error closes are
exactly when the postback matters).

Each test below holds one piece of the round trip to a checkable claim, on BOTH
host entrypoints (the 1.x `server()` path and the 2.x `setup()` path):

  - every dispatch-created session carries metadata.parent = the orchestrator's
    session id (2.x; 1.x has native parentID) and metadata.ticket when ticketed;
  - a closing message posts back to the parent on completion AND on error —
    2.x via ctx.session.synthetic, 1.x via a noReply promptAsync — carrying the
    run's status, its ticket/node, and its result lines;
  - the postback fires for ticketed runs too, not only ad-hoc delegations;
  - resume (task_id) runs do not re-post (the run was already parented at
    create; the closing signal belongs to the run's terminal transition).

Run:  uv run --with pytest --with pyyaml pytest tests/test_dispatch_roundtrip.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
from test_opencode_dispatch import (  # noqa: E402
    HOSTS, dispatch, emit_oc, workspace, creates, result_text,
)

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node required")


def ops(r, name):
    return [c for c in r["calls"] if c["op"] == name]


# --- metadata.parent on every dispatch child ------------------------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_a_ticketed_child_carries_parent_and_ticket_in_metadata(host):
    """The sidebar groups on parentID ?? metadata.parent — a dispatch child has no
    native parentID on 2.x, so the parent link rides metadata. The ticket rides too:
    the tree labels the run by what it works on."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-40", host=host)
    ci = creates(r, host)[0]
    if host == "v1":
        # 1.x has native parentID at create — the tree groups natively
        assert ci["body"].get("parentID") == "ses_parent", ci
    else:
        assert ci["metadata"]["parent"] == "ses_parent", ci
        assert ci["metadata"]["ticket"] == "TST-40", ci


@pytest.mark.parametrize("host", HOSTS)
def test_an_adhoc_child_carries_parent_in_metadata(host):
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="validate", task="scope the review", host=host)
    ci = creates(r, host)[0]
    if host == "v1":
        assert ci["body"].get("parentID") == "ses_parent", ci
    else:
        assert ci["metadata"]["parent"] == "ses_parent", ci
        assert "ticket" not in ci["metadata"], ci  # ad-hoc: no ticket to carry


# --- the closing message posts back, on completion AND on error ------------------------

@pytest.mark.parametrize("host", HOSTS)
def test_a_ticketed_run_posts_its_closing_message_back_to_the_parent(host):
    """Today only ad-hoc runs signal; a ticketed run's close is silent. The round
    trip: EVERY dispatch child posts its closing message to the parent — the
    orchestrator learns the run finished without polling."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-41", host=host)
    if host == "v1":
        posts = [c for c in ops(r, "promptAsync")
                 if c["input"]["path"]["id"] == "ses_parent"]
    else:
        posts = [c for c in ops(r, "synthetic")
                 if c["input"]["sessionID"] == "ses_parent"]
    assert posts, f"no closing message posted to the parent: {r['calls']}"
    text = (posts[0]["input"]["body"]["parts"][0]["text"] if host == "v1"
            else posts[0]["input"]["text"])
    assert "TST-41" in text and "complete" in text, text
    assert "PR https://x/pr/1" in text, text  # the result lines ride the postback


@pytest.mark.parametrize("host", HOSTS)
def test_an_error_finish_posts_back_too(host):
    """The astra retention death was SILENT — the orchestrator learned nothing.
    Error closes are exactly when the postback matters: the closing message must
    fire on error finishes, carrying the error, not only on clean completions."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-42",
                 env={"HARNESS_FAIL": "prompt"}, host=host)
    if host == "v1":
        posts = [c for c in ops(r, "promptAsync")
                 if c["input"]["path"]["id"] == "ses_parent"]
    else:
        posts = [c for c in ops(r, "synthetic")
                 if c["input"]["sessionID"] == "ses_parent"]
    assert posts, f"an error finish posted NOTHING to the parent: {r['calls']}"
    text = (posts[0]["input"]["body"]["parts"][0]["text"] if host == "v1"
            else posts[0]["input"]["text"])
    assert "TST-42" in text and "error" in text, text
    assert "no such session" in text, text  # the error itself rides the postback


@pytest.mark.parametrize("host", HOSTS)
def test_a_background_ticketed_run_posts_back_when_it_finishes(host):
    """Background is where the postback is load-bearing: the orchestrator returned
    immediately, so the closing message is the ONLY way it learns the run finished."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws, node="produce", repo="api", ticket="TST-43",
                 background=True, host=host)
    assert "ses_1" in result_text(r["result"], host), r
    if host == "v1":
        posts = [c for c in ops(r, "promptAsync")
                 if c["input"]["path"]["id"] == "ses_parent"]
    else:
        posts = [c for c in ops(r, "synthetic")
                 if c["input"]["sessionID"] == "ses_parent"]
    assert posts, f"a background run's finish posted nothing: {r['calls']}"
    text = (posts[0]["input"]["body"]["parts"][0]["text"] if host == "v1"
            else posts[0]["input"]["text"])
    assert "TST-43" in text, text


@pytest.mark.parametrize("host", HOSTS)
def test_a_resume_does_not_repost(host):
    """The closing signal belongs to the run's terminal transition. A resumed run
    (task_id) was already parented at create and its original close already posted —
    a resume that re-posts would double-signal the parent."""
    out, ws = emit_oc(), workspace()
    r = dispatch(out, ws,
                 {"node": "produce", "repo": "api", "ticket": "TST-44"},
                 {"node": "produce", "ticket": "TST-44", "task_id": "ses_1",
                  "command": "address the review deficiencies"}, host=host)
    if host == "v1":
        posts = [c for c in ops(r, "promptAsync")
                 if c["input"]["path"]["id"] == "ses_parent"]
    else:
        posts = [c for c in ops(r, "synthetic")
                 if c["input"]["sessionID"] == "ses_parent"]
    # exactly ONE postback for the whole run — the first dispatch's close
    assert len(posts) == 1, f"the resume re-posted: {[p['input'] for p in posts]}"
