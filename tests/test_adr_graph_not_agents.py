#!/usr/bin/env python3
"""Acceptance tests for the ADR answering ktoulgaridis/forge#23.

The deliverable (#23): an ADR draft at docs/decisions/NNNN-graph-not-agents.md,
status PROPOSED — the maintainer decides; the ADR does not rewrite GENERATOR.md
by itself. Each test below holds one demanded piece of that deliverable to a
checkable claim:

  - the artifact exists, is Proposed, and names its home ticket;
  - the thesis: forge describes ONLY the process (the graph) as data + skills,
    wielded by ONE general agent — the fixed cast was an implementation detail
    of weaker models;
  - an invariant-preserving design for each of the four load-bearing
    invariants: no-self-review, read-only validation, step caps / budget
    discipline, model policy;
  - the emit diff sketch: what is removed / kept / added on the opencode target;
  - the failure modes the old design guarded against, each still guarded;
  - an honest "what we lose" section;
  - citations to the method docs, with every cited repo path resolving.

Run:  uv run --with pytest pytest tests/test_adr_graph_not_agents.py -q
  or: python3 tests/test_adr_graph_not_agents.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR = ROOT / "docs" / "decisions" / "0001-graph-not-agents.md"

# Repo-root prefixes a cited path may carry. Anything else backticked is prose —
# an emitted-artifact noun (`agent/`, `plugin/dispatch.js`) or a scalar
# (`toolFilter.allow`) — and is not a repo path to validate.
REPO_TOP = ("docs/", "lib/", "templates/", "tests/", "adapters/", "commands/",
            "examples/", ".forge.org.example.yaml", ".forge.config.example.yaml",
            "README.md", "CONTRIBUTING.md", "LICENSE")
BACKTICKED = re.compile(r"`([A-Za-z0-9_./-]+)`")
LINK_TARGET = re.compile(r"\]\(([^)#\s]+)\)")


# --- doc scaffolding --------------------------------------------------------------

def _sections(doc):
    """[(heading, body), ...] — the doc split at every markdown heading."""
    parts = re.split(r"^(#{1,4} .+)$", doc, flags=re.M)
    out = [("(preamble)", parts[0])] if parts[0].strip() else []
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i].lstrip("#").strip(), parts[i + 1]))
    return out


def _section(doc, pattern, what):
    """The body of the first section whose heading matches `pattern`."""
    for head, body in _sections(doc):
        if re.search(pattern, head, re.I):
            return body
    raise AssertionError(f"the ADR has no section heading matching {pattern!r} ({what})")


def _between(body, start, end):
    """The text after the `start` marker, up to (not including) the `end` marker."""
    s = re.search(start, body)
    assert s, f"no marker matching {start!r} in the section"
    rest = body[s.end():]
    e = re.search(end, rest)
    return rest[:e.start()] if e else rest


# --- 1. the artifact ----------------------------------------------------------------

def test_adr_0001_exists_proposed_with_ticket_home():
    """docs/decisions/NNNN-graph-not-agents.md is THE deliverable; Proposed, dated,
    with its home ticket named so the trace is bidirectional."""
    assert ADR.is_file(), (
        "docs/decisions/0001-graph-not-agents.md — the #23 deliverable — does not exist")
    doc = ADR.read_text()
    assert re.search(r"^Status:\s*\S*proposed", doc, re.I | re.M), "no Proposed status line"
    assert re.search(r"^Date:\s*\d{4}-\d{2}-\d{2}", doc, re.M), "no ISO date line"
    assert re.search(r"#23\b", doc), "the ADR does not name its home ticket (#23)"


# --- 2. the thesis --------------------------------------------------------------------

def test_thesis_process_and_skills_wielded_by_one_general_agent():
    doc = ADR.read_text()
    body = _section(doc, r"thesis", "the thesis")
    assert re.search(r"(one|single) general agent", body, re.I), \
        "the thesis does not state who wields the process: ONE general agent"
    for word in ("process", "graph", "skills", "cast"):
        assert re.search(word, body, re.I), f"the thesis does not mention {word!r}"
    assert re.search(r"weaker models", body, re.I), \
        "the thesis does not name the bet: the cast was an implementation detail of weaker models"


# --- 3. the four load-bearing invariants -----------------------------------------------

def test_invariant_no_self_review_becomes_a_property_of_the_review_node():
    doc = ADR.read_text()
    body = _section(doc, r"no-self-review", "invariant 1")
    assert re.search(r"separate (context|session|subagent)", body, re.I), \
        "does not state today's mechanism (a separate-context reviewer subagent)"
    assert re.search(r"fresh[- ]context", body, re.I), \
        "the proposed design is not a fresh-context invocation"
    assert re.search(r"\bskills?\b", body, re.I), \
        "the review skill is not the carrier of the requirement"
    assert re.search(r"\bnode\b", body, re.I), \
        "the invariant is not re-anchored as a property of the review NODE in the graph"


def test_invariant_read_only_moves_to_session_permissions_at_dispatch():
    doc = ADR.read_text()
    body = _section(doc, r"read-only", "invariant 2")
    assert re.search(r"derived at emit", body, re.I), \
        "does not state today's mechanism (per-role permission blocks derived at emit)"
    assert "ADHOC_DENY" in body, \
        "does not name the proven candidate mechanism (forge#20's ADHOC_DENY)"
    assert re.search(r"session", body, re.I) and re.search(r"dispatch", body, re.I), \
        "the boundary is not session-level permission rules applied at dispatch"
    assert re.search(r"#20", body), "does not cite forge#20's ad-hoc mode as the proof"
    assert re.search(r"platform backstop", body, re.I), \
        "platform backstops are not named as the org-declared fallback"


def test_invariant_step_caps_attach_to_nodes_not_personas():
    doc = ADR.read_text()
    body = _section(doc, r"step cap|budget discipline", "invariant 3")
    assert "max_steps" in body, "does not name today's mechanism (per-role max_steps)"
    assert re.search(r"\b(120|40|25)\b", body), "today's caps (120/40/25) are not stated"
    assert re.search(r"\bnode", body, re.I), "caps do not attach to the node/phase"
    assert re.search(r"dispatch", body, re.I), "caps are not applied at dispatch"


def test_invariant_model_policy_survives_as_org_floor_with_node_depth():
    doc = ADR.read_text()
    body = _section(doc, r"model policy", "invariant 4")
    assert re.search(r"per-role", body, re.I), \
        "does not state today's mechanism (per-role models pinned per archetype)"
    assert re.search(r"banned", body, re.I), "the org banned list is not addressed"
    assert re.search(r"provider", body, re.I), "the provider allowlist is not addressed"
    assert re.search(r"\bnode", body, re.I), "model depth does not attach to the node"


# --- 4. the emit diff sketch -------------------------------------------------------------

def test_emit_diff_sketch_removed_kept_added_on_the_opencode_target():
    doc = ADR.read_text()
    body = _section(doc, r"emit diff", "the emit diff sketch")
    assert re.search(r"opencode", body, re.I), "the sketch is not scoped to the opencode target"

    removed = _between(body, r"\*\*Removed", r"\*\*Kept")
    assert "`agent/`" in removed, "the sketch does not remove the agent/ dir (the cast)"
    assert re.search(r"subagents", removed, re.I), \
        "the sketch does not remove the subagents config block"
    assert re.search(r"derivation", removed, re.I), \
        "the sketch does not remove the per-role permission derivation"

    kept = _between(body, r"\*\*Kept", r"\*\*Added")
    assert re.search(r"skills?", kept, re.I), "the skills (the procedures) are not kept"
    assert re.search(r"wiki|operating model", kept, re.I), \
        "the wiki graph / operating model is not kept"
    assert re.search(r"dispatch", kept, re.I), \
        "dispatch — the worktree/delegation machinery — is not kept"

    added = _between(body, r"\*\*Added", r"\Z")
    assert re.search(r"\bnode", added, re.I), "no node contracts are added"
    assert re.search(r"graph|process data", added, re.I), "the graph-as-data is not added"


# --- 5. failure modes ----------------------------------------------------------------------

def test_failure_modes_table_maps_old_guards_to_new_guards():
    doc = ADR.read_text()
    body = _section(doc, r"failure mode", "the failure-modes mapping")
    rows = [ln for ln in body.splitlines() if ln.lstrip().startswith("|")]
    data = [r for r in rows if not re.search(r"^\|[\s:|-]+\|$", r.strip())]
    assert len(data) >= 5, f"expected >=5 failure-mode rows (one per old guard), got {len(data)}"
    for r in data:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        assert len(cells) >= 3 and all(cells), \
            f"a failure-mode row lacks old-guard/failure/new-guard cells: {r!r}"
    text = " ".join(data)
    for phrase, what in (
        (r"full-permission primary agent", "the fail-open fallback"),
        (r"launder", "write laundering via a spawned writer"),
        (r"self-review|anchor", "anchoring / self-review"),
        (r"banned", "the banned/off-provider model failure"),
        (r"steps?|cap|budget", "the runaway-budget failure"),
    ):
        assert re.search(phrase, text, re.I), f"the table does not cover {what}"


# --- 6. what we lose -------------------------------------------------------------------------

def test_what_we_lose_is_honest_and_specific():
    doc = ADR.read_text()
    body = _section(doc, r"what we lose", "the honest losses")
    items = [ln for ln in body.splitlines() if ln.strip().startswith("-")]
    assert len(items) >= 4, f"expected >=4 named losses, got {len(items)}"
    assert re.search(r"emit", body, re.I) and re.search(r"dispatch|run ?time", body, re.I), \
        "the locus shift (emit-time guarantees becoming dispatch/run-time) is not owned"
    assert re.search(r"weaker models|model roster|model quality|the bet", body, re.I), \
        "the model-capability bet is not named as a loss or hedge"
    assert re.search(r"test_opencode_emit|coverage", body, re.I), \
        "the test-coverage regression is not owned"
    assert re.search(r"axis|differentiation|persona", body, re.I), \
        "the lost differentiation surface (personas / axis 3) is not owned"


# --- 7. citations -------------------------------------------------------------------------------

def test_cites_the_method_docs():
    doc = ADR.read_text()
    for p in ("docs/METHOD.md", "docs/ROLES.md", "docs/GENERATOR.md"):
        assert p in doc, f"the ADR does not cite {p}"


def test_every_cited_repo_path_resolves():
    doc = ADR.read_text()
    cited = set(BACKTICKED.findall(doc))
    repo_paths = {p for p in cited if any(p == t or p.startswith(t) for t in REPO_TOP)}
    # Paths the ADR cites as REMOVED by its own accepting rework (forge#28) — the
    # citation is the historical record of what died; the path is gone on purpose.
    retired = {"templates/opencode/agent/"}
    repo_paths -= retired
    links = {t for t in LINK_TARGET.findall(doc) if not t.startswith("http")}
    assert repo_paths or links, "the ADR cites no repo paths or links at all"
    for p in sorted(repo_paths):
        assert (ROOT / p).exists(), f"cited repo path does not resolve: {p}"
    for p in sorted(links):
        assert (ADR.parent / p).exists(), \
            f"cited link does not resolve from docs/decisions/: {p}"


# --- 8. proposal-only -----------------------------------------------------------------------------

def test_adr_is_a_proposal_the_maintainer_decides():
    """#23: PROPOSED status — the maintainer decides; this does not rewrite
    GENERATOR.md by itself. The ADR must say so up front, not bury it."""
    doc = ADR.read_text()
    head = doc[:2000]
    assert re.search(r"maintainer", head, re.I), \
        "the status block does not say the maintainer decides"
    assert "GENERATOR.md" in head, \
        "the status block does not address GENERATOR.md"
    assert re.search(r"by itself|on its own|changes? no (template|behavior)", head, re.I), \
        "the proposal-only claim (changes nothing by itself) is absent"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
