#!/usr/bin/env python3
"""TEC-4094 — refine is a main_thread graph; plot hands off a sketch, not tasks.

Renders the SHARED refine + plot (inception) skills on BOTH targets (claude-code and
opencode), with the org renaming execute->engage and inception->plot, and asserts the
EMITTED text carries the ADR-0019 refine node-set:

  1. exactly the nodes load, need, validation, architecture, slos, cybersec, trace,
     deps, sketch, ready, mark — in that order; trace is regulated-repos-only;
  2. two human gates: `validation` (gate: product — sign-off is a tracker comment from
     product, with the Org-scope owning-engineer attestation flagged as pending an ADR
     open question) and `mark` (gate: engineer — the ONLY place the label is applied);
  3. state survives sessions: a `REFINE-STATE <node>` tracker comment is written at
     every node and every pause, and `load` resumes from the latest one;
  4. `ready` self-checks against rubrics/agent-ready.md, loops back at most 3 times,
     then escalates;
  5. refine writes a SKETCH (repo x concern); engage creates the tasks (both skills);
  6. the result line contract;
  7. the verified process-skills findings: no step headed "optional" (refine-01), no
     tracker snippet leaking `# comment` lines as H1 headings (all-01), namespaced verb
     invocations (engage-05), and plot's clearance parenthetical (plot-01).

The org config is the one tests/test_opencode_emit.py uses, so this file follows any
schema migration of that fixture instead of pinning its own copy of the graph block.

Run:  uv run --with pytest --with pyyaml pytest tests/test_refine_graph.py -q
"""
import copy
import re
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))
import emit  # noqa: E402
from test_opencode_emit import CFG as BASE_CFG  # noqa: E402

NODES = ["load", "need", "validation", "architecture", "slos", "cybersec", "trace",
         "deps", "sketch", "ready", "mark"]
RESULT_LINE = ("REFINE <key> <agent-ready|parked:<node>|escalated:<reason>> "
               "validation=<signed|pending|absent> deficiencies=<n> sketch=<n>")
PLUGIN = BASE_CFG["plugin"]["name"]
# The jira-acli adapter's label-APPLY command (the read form carries no --labels).
LABEL_APPLY = '--labels "agent-ready"'
TARGETS = {"claude-code": "skills", "opencode": "skill"}
RUBRIC_PATH = {"claude-code": "`${CLAUDE_PLUGIN_ROOT}/rubrics/agent-ready.md`",
               "opencode": "`rubric/agent-ready.md` in the opencode config directory"}


def _cfg():
    c = copy.deepcopy(BASE_CFG)
    c["verbs"] = {"inception": "plot", "execute": "engage", "gate": "clearance"}
    return c


_CACHE: dict = {}


def emitted(target: str) -> Path:
    if target not in _CACHE:
        out = Path(tempfile.mkdtemp(prefix=f"emit-refine-{target}-")) / "out"
        emit.TARGETS[target](_cfg(), out)
        _CACHE[target] = out
    return _CACHE[target]


def skill(target: str, verb: str) -> str:
    p = emitted(target) / TARGETS[target] / verb / "SKILL.md"
    assert p.is_file(), f"{target}: missing emitted {p}"
    return p.read_text()


def node_headings(text: str) -> list[str]:
    return re.findall(r"^### `([a-z]+)`", text, flags=re.M)


def section(text: str, heading_re: str) -> str:
    """The body under the first heading matching heading_re, up to the next ##/###,
    with whitespace collapsed so a prose assertion survives re-wrapping."""
    m = re.search(heading_re, text, flags=re.M)
    assert m, f"no heading matching {heading_re!r}"
    rest = text[m.end():]
    nxt = re.search(r"^#{2,3} ", rest, flags=re.M)
    return " ".join((rest[: nxt.start()] if nxt else rest).split())


def node(text: str, name: str) -> str:
    return section(text, r"^### `%s`.*$" % re.escape(name))


def outside_fences(text: str) -> list[str]:
    lines, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


targets = pytest.mark.parametrize("target", list(TARGETS))


# --- 1. the node-set ------------------------------------------------------------------

@targets
def test_refine_walks_exactly_the_adr0019_nodes_in_order(target):
    got = node_headings(skill(target, "refine"))
    assert got == NODES, f"{target}: refine node headings {got} != {NODES}"


@targets
def test_trace_runs_only_for_regulated_repos(target):
    txt = skill(target, "refine")
    heading = re.search(r"^### `trace`.*$", txt, flags=re.M).group(0)
    assert "regulated" in heading, f"{target}: trace heading not scoped: {heading!r}"
    assert "design-controls/" in node(txt, "trace")


# --- 2. the two human gates -------------------------------------------------------------

@targets
def test_validation_is_a_product_gate_recorded_in_the_tracker(target):
    txt = skill(target, "refine")
    heading = re.search(r"^### `validation`.*$", txt, flags=re.M).group(0)
    assert "gate: product" in heading, f"{target}: validation is not a product gate"
    body = node(txt, "validation")
    assert "tracker comment" in body and "product" in body, \
        f"{target}: product sign-off is not recorded as a tracker comment"
    # fail-closed: no sign-off parks the run, it never advances to architecture
    assert "parked:validation" in body, f"{target}: an unsigned test does not park"
    assert "validation=pending" in body
    # Org scope: the owning engineer attests and the comment names who signed —
    # flagged as pending the ADR-0019 open question
    assert "owning engineer" in body and "attest" in body, \
        f"{target}: no Org-scope attestation rule"
    assert "names who signed" in body, f"{target}: attestation does not name the signer"
    assert "open question" in body and "ADR 0019" in body, \
        f"{target}: Org-scope signer not flagged as an ADR-0019 open question"


@targets
def test_mark_is_an_engineer_gate_and_the_only_place_the_label_is_applied(target):
    txt = skill(target, "refine")
    heading = re.search(r"^### `mark`.*$", txt, flags=re.M).group(0)
    assert "gate: engineer" in heading, f"{target}: mark is not an engineer gate"
    body = node(txt, "mark")
    assert LABEL_APPLY in body, f"{target}: mark does not carry the label-apply command"
    assert txt.count(LABEL_APPLY) == body.count(LABEL_APPLY), \
        f"{target}: the agent-ready label is applied outside the mark node"
    assert "approv" in body, f"{target}: mark applies the label without approval"


# --- 3. REFINE-STATE: tracker-persisted state across sessions --------------------------

@targets
def test_refine_state_is_written_back_at_every_node_and_pause(target):
    txt = skill(target, "refine")
    walk = section(txt, r"^## Walking the graph.*$")
    assert "REFINE-STATE <node>" in walk, f"{target}: no REFINE-STATE comment format"
    assert "at every node" in walk and "every pause" in walk, \
        f"{target}: REFINE-STATE write-back is not per node + per pause"
    assert "comment create" in walk, \
        f"{target}: the write-back carries no tracker comment command"
    # write-back is a side effect of every node, never a node of its own
    assert "REFINE-STATE" not in node_headings(txt)


@targets
def test_load_resumes_from_the_latest_refine_state(target):
    body = node(skill(target, "refine"), "load")
    assert "comment list" in body, f"{target}: load does not read the comments"
    assert "latest" in body and "REFINE-STATE" in body, \
        f"{target}: load does not resume from the latest REFINE-STATE"


# --- 4. ready: rubric self-check with a bounded loop -----------------------------------

@targets
def test_ready_self_checks_the_agent_ready_rubric_with_a_loop_cap(target):
    body = node(skill(target, "refine"), "ready")
    # Each target's own rubric location: CC ships rubrics/ at the plugin root; opencode
    # ships rubric/ (singular) in the config dir, beside skill/ (TEC-4092, emit.py).
    path = RUBRIC_PATH[target]
    assert path in body, f"{target}: ready does not name its rubric path {path!r}"
    assert "at most 3" in body, f"{target}: ready loop is not capped at 3"
    assert "escalated:" in body, f"{target}: ready does not escalate past the cap"
    assert "deficien" in body


def test_agent_ready_rubric_is_emitted_and_maps_to_the_nodes():
    # Claude Code renders every org-plugin template; the opencode rubric dir is the
    # multi-graph schema's (sibling TEC-4092) and is not asserted here.
    rubric = emitted("claude-code") / "rubrics" / "agent-ready.md"
    assert rubric.is_file(), "rubrics/agent-ready.md not emitted on claude-code"
    txt = rubric.read_text()
    for n in ("need", "validation", "architecture", "slos", "cybersec", "trace",
              "deps", "sketch"):
        assert f"`{n}`" in txt, f"agent-ready rubric maps no criterion to `{n}`"
    assert "operating model" in txt, "rubric criteria not mapped to the operating model"
    assert "signed" in txt and "tracker comment" in txt, \
        "rubric does not require a signed validation test"
    assert "`mark`" in txt, "rubric does not leave the label to the mark gate"


# --- 5. sketch, not tasks ---------------------------------------------------------------

@targets
def test_refine_writes_a_sketch_and_engage_creates_the_tasks(target):
    body = node(skill(target, "refine"), "sketch")
    assert "repo × concern" in body, f"{target}: sketch is not a repo x concern list"
    assert "does not create" in body, f"{target}: refine may create tasks"
    assert f"/{PLUGIN}:engage" in body, f"{target}: sketch does not hand off to engage"


@targets
def test_plot_creates_stories_not_tasks(target):
    txt = skill(target, "plot")
    assert "sketch" in txt and f"/{PLUGIN}:engage" in txt, \
        f"{target}: plot does not state the sketch/task boundary"
    assert "does not create tasks" in txt, f"{target}: plot may create tasks"
    assert LABEL_APPLY not in txt, f"{target}: plot applies the agent-ready label"


# --- 6. the result line -----------------------------------------------------------------

@targets
def test_refine_ends_with_the_result_line_contract(target):
    txt = skill(target, "refine")
    assert RESULT_LINE in txt, f"{target}: result line contract missing or changed"


# --- 7. verified process-skills findings -------------------------------------------------

@targets
def test_no_required_step_is_headed_optional(target):
    """refine-01: a heading reading 'optional' is followed literally as permission."""
    txt = skill(target, "refine")
    bad = [h for h in re.findall(r"^#{2,4} .*$", txt, flags=re.M) if "optional" in h.lower()]
    assert not bad, f"{target}: refine headings read as optional: {bad}"


@targets
@pytest.mark.parametrize("verb", ["refine", "plot"])
def test_tracker_snippets_are_fenced_not_h1_headings(target, verb):
    """all-01: an unfenced snippet turns each `# comment` line into a top-level H1."""
    bad = [l for l in outside_fences(skill(target, verb)) if l.startswith("# ")]
    assert len(bad) == 1, f"{target}/{verb}: H1 lines outside a fence: {bad}"


@targets
def test_invocations_are_namespaced_and_verbs_follow_the_rename(target):
    """engage-05: the org's verb names, invoked as /<plugin>:<verb>."""
    txt = skill(target, "refine")
    assert f"/{PLUGIN}:refine <ticket-key>" in txt, f"{target}: bare /refine invocation"
    assert "the execute phase" not in txt, f"{target}: generic verb leaks through"
    assert f"/{PLUGIN}:engage" in txt


@targets
def test_plot_names_clearance_as_a_phase_not_a_skill(target):
    """plot-01 (downgraded): clearance is a live phase, but no clearance skill ships."""
    txt = skill(target, "plot")
    assert "clearance" in txt and "not a skill" in txt, \
        f"{target}: plot does not say clearance is a phase, not a skill"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
