#!/usr/bin/env python3
"""The execute verb (engage) and the builder speak ONE contract (ADR 0019 §2-4).

  - engage dispatches ONE builder per ready task — on Claude Code via the native Agent
    tool (`subagent_type: <plugin>:builder`), on opencode via `dispatch` — and never a
    Workflow or an in-loop reviewer;
  - the Claude Code isolation contract works from a multi-repo workspace root: isolation
    is passed on the Agent call only when the session's cwd IS the target repo; otherwise
    the orchestrator creates the worktree and names it in the envelope (the Agent tool
    always names its worktree `agent-worktree`, which the WorktreeCreate hook cannot map
    to a repo);
  - the model/effort text matches the artifacts: the builder inherits; the Agent tool's
    `model` takes only an alias and it has no effort parameter;
  - both ends use the ONE RESULT line; engage verifies a worker's claim against gh and
    the tracker before recording done, and treats a run with no RESULT line as CAPPED;
  - the gate rubric demands no green CI before the PR exists, and never treats a
    deferred validation test as passing.

Run:  uv run --with pytest --with pyyaml pytest tests/test_engage_contract.py -q
"""
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG  # noqa: E402


def emit_target(target):
    out = Path(tempfile.mkdtemp(prefix=f"emit-engage-{target}-")) / "out"
    emit.TARGETS[target](CFG, out)
    return out


@pytest.fixture(scope="module")
def cc():
    return emit_target("claude-code")


@pytest.fixture(scope="module")
def oc():
    return emit_target("opencode")


def engage(out, target):
    d = "skills" if target == "claude-code" else "skill"
    return (out / d / "execute" / "SKILL.md").read_text()


def test_cc_engage_dispatches_the_builder_through_the_agent_tool(cc):
    ex = engage(cc, "claude-code")
    assert 'subagent_type: "testco-harness:builder"' in ex, ex
    assert "Workflow" in ex and "no `Workflow`" in ex.replace("**", ""), \
        "engage does not rule out a Workflow driver"


def test_cc_isolation_contract_works_from_a_workspace_root(cc):
    ex = engage(cc, "claude-code")
    assert "agent-worktree" in ex, "engage does not explain why the hook cannot resolve"
    assert 'isolation: "worktree"' in ex and "cwd is the target repo" in ex, ex
    assert "git -C <repo> worktree add" in ex and "WORKTREE:" in ex, \
        "engage does not create the worktree and name it in the envelope"


def test_cc_model_and_effort_text_matches_the_artifacts(cc):
    ex = engage(cc, "claude-code")
    assert "pins its model + effort" not in ex, "engage still claims the builder pins"
    assert "only an alias" in ex and "no effort parameter" in ex, ex


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_both_ends_share_the_one_result_line(cc, oc, target):
    out = cc if target == "claude-code" else oc
    ex = engage(out, target)
    assert emit.RESULT_LINE in ex, f"{target} engage does not name the RESULT line"
    ad = "agents" if target == "claude-code" else "agent"
    assert emit.RESULT_LINE in (out / ad / "builder.md").read_text()
    for status in ("PASS", "FAIL", "BLOCKED", "CAPPED"):
        assert status in ex, (target, status)


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_engage_verifies_a_claim_before_recording_done(cc, oc, target):
    ex = engage(cc if target == "claude-code" else oc, target)
    assert "gh pr view" in ex and "--json" in ex, "no artifact check before done"
    assert "ticket key" in ex and "repo" in ex, "the PR is not matched to its task"
    assert "no RESULT line" in ex and "CAPPED" in ex, "a capped run is not handled"
    assert "nothing more" not in ex, "the 'consume only … nothing more' rule forbids the check"


def test_opencode_engage_dispatches_the_builder(oc):
    ex = engage(oc, "opencode")
    assert 'dispatch({ agent: "builder"' in ex, ex


def test_cc_supplementary_reviewer_is_the_emitted_read_only_agent(cc):
    ex = engage(cc, "claude-code")
    assert 'subagent_type: "testco-harness:validate"' in ex, ex


def test_engage_carries_no_boilerplate_or_generic_verb_leak(cc):
    ex = engage(cc, "claude-code")
    assert "## Implementation note" not in ex
    assert "Execute is the **second half**" not in ex


def test_gate_rubric_demands_no_green_ci_before_the_pr_exists(cc):
    gate = (cc / "rubrics" / "gate.md").read_text()
    assert "CI included" not in gate
    assert "pending" in gate and "deferred" in gate and "not passing" in gate, gate
    assert "RESULT" in gate and "CAPPED" in gate and "BLOCKED" in gate, gate


@pytest.mark.parametrize("rubric", ["review", "gate"])
def test_rubrics_name_the_wiki_path(cc, rubric):
    txt = (cc / "rubrics" / f"{rubric}.md").read_text()
    assert "${TESTCO_WIKI:-~/work/testco-wiki}" in txt, txt
