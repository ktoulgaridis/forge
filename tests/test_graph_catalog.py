#!/usr/bin/env python3
"""Emit-time refusals of the graph catalog (ADR 0019 §1, §4, §5). Every rule is
fail-closed: a mis-declared catalog does not emit, on either target.

Run:  uv run --with pytest --with pyyaml pytest tests/test_graph_catalog.py -q
"""
import copy
import sys
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


# --- the hard cut: legacy keys fail with a targeted migration message -------------------

def test_a_leftover_graph_key_refuses_with_a_migration_message():
    def m(c):
        c["graph"] = copy.deepcopy(c["graphs"]["build"])
    refuses(m, r"`graph:`.*0\.9\.0.*graphs\.build")


def test_a_leftover_agents_key_refuses_with_a_migration_message():
    def m(c):
        c["agents"] = [{"name": "build", "model": "sonnet"}]
    refuses(m, r"`agents:`.*graphs\.<name>\.model")


# --- structure: loops are capped, every node is reachable, a terminal exists -----------

def test_a_loop_with_no_max_visits_node_refuses():
    refuses(lambda c: nodes(c)["review"].pop("max_visits"), r"loop .*max_visits")


def test_a_self_loop_with_no_max_visits_refuses():
    def m(c):
        nodes(c)["validate"]["next"] = ["validate", "review"]
    refuses(m, r"loop .*validate.*max_visits")


def test_a_capped_loop_passes():
    emit.build_bindings(CFG)


def test_an_unreachable_node_refuses():
    def m(c):
        nodes(c)["orphan"] = {"skill": "build-fix", "terminal": "done"}
    refuses(m, r"orphan.*unreachable")


def test_a_graph_with_no_terminal_refuses():
    def m(c):
        n = nodes(c)
        n["clear"] = {"rubric": "gate", "next": "understand", "max_visits": 2}
    refuses(m, r"no terminal")


# --- names: node skills, rubrics, verbs --------------------------------------------------

def refine_graph(skill="refine"):
    """A main-thread graph (walked by the session running the refine verb)."""
    return {
        "verb": "refine", "launch": "main_thread", "tools": "read_only",
        "entry": "load",
        "nodes": {
            "load": {"skill": skill, "next": "validation"},
            "validation": {"skill": skill, "gate": "product", "max_visits": 3,
                           "next": ["ready", "load"]},
            "ready": {"skill": skill, "max_visits": 4, "next": ["mark", "load"]},
            "mark": {"skill": skill, "gate": "engineer", "terminal": "label_applied"},
        },
    }


def test_an_unknown_node_skill_refuses():
    refuses(lambda c: nodes(c)["build"].__setitem__("skill", "nonesuch"),
            r"nonesuch.*not a node skill")


def test_an_unknown_rubric_refuses():
    refuses(lambda c: nodes(c)["review"].__setitem__("rubric", "nonesuch"),
            r"rubric 'nonesuch'.*not a rubric")


def test_rubrics_are_discovered_by_glob_not_a_registry(tmp_path, monkeypatch):
    """A sibling adds a rubric by adding its template — emit.py is not touched."""
    import shutil
    rubrics = tmp_path / "rubrics"
    shutil.copytree(emit.RUBRICS_DIR, rubrics)
    (rubrics / "agent-ready.md.template").write_text("# agent-ready ({{ORG_NAME}})\n")
    monkeypatch.setattr(emit, "RUBRICS_DIR", rubrics)
    emit.build_bindings(cfg_with(lambda c: nodes(c)["review"].__setitem__(
        "rubric", "agent-ready")))


def test_a_verb_as_a_worker_node_skill_refuses():
    refuses(lambda c: nodes(c)["build"].__setitem__("skill", "execute"),
            r"verb.*worker node skill")


def test_a_main_thread_graph_may_walk_its_verb_skill_after_verb_rename():
    """A main-thread node skill may name its verb — canonical or the org's rename."""
    def m(c):
        c["verbs"] = {"refine": "groom"}
        c["graphs"]["refine"] = refine_graph("groom")
    b = emit.build_bindings(cfg_with(m))
    g = next(g for g in b["graphs"] if g["name"] == "refine")
    assert g["verb"] == "refine" and g["verb_name"] == "groom", g
    lines = "\n".join(i["line"] for i in emit.node_lines(g, "claude-code", b["verbs"]))
    assert "skills/groom/SKILL.md" in lines, lines
    # and the canonical name resolves to the same emitted skill
    b2 = emit.build_bindings(cfg_with(lambda c: (c.__setitem__("verbs", {"refine": "groom"}),
                                                  c["graphs"].__setitem__("refine", refine_graph()))))
    g2 = next(g for g in b2["graphs"] if g["name"] == "refine")
    assert "skills/groom/SKILL.md" in "\n".join(
        i["line"] for i in emit.node_lines(g2, "claude-code", b2["verbs"]))


def test_a_gate_in_a_worker_graph_refuses():
    refuses(lambda c: nodes(c)["review"].__setitem__("gate", "engineer"),
            r"gate.*main_thread")


def test_two_graphs_binding_one_verb_refuse():
    def m(c):
        g = copy.deepcopy(c["graphs"]["build"])
        g["agent"] = "builder-two"
        c["graphs"]["build2"] = g
    refuses(m, r"verb 'execute'.*bound by both")


def test_a_worker_graph_with_no_execute_binding_leaves_nothing_to_dispatch():
    refuses(lambda c: c["graphs"]["build"].__setitem__("verb", "wiki"),
            r"no worker graph binds the `execute` verb")


# --- the preload must be loadable ------------------------------------------------------

def test_a_preload_that_sets_disable_model_invocation_refuses(tmp_path, monkeypatch):
    import shutil
    ns = tmp_path / "node-skills"
    shutil.copytree(emit.NODE_SKILLS_DIR, ns)
    f = ns / "build-understand" / "SKILL.md.template"
    f.write_text(f.read_text().replace("name: build-understand\n",
                                       "name: build-understand\ndisable-model-invocation: true\n"))
    monkeypatch.setattr(emit, "NODE_SKILLS_DIR", ns)
    refuses(lambda c: None, r"disable-model-invocation")


# --- identities: a worker name never shadows a host built-in --------------------------

@pytest.mark.parametrize("name", ["build", "general", "explore", "compaction", "title",
                                  "summary", "plan", "Explore", "Plan", "general-purpose",
                                  "claude", "statusline-setup", "claude-code-guide",
                                  "validate"])
def test_a_worker_named_like_a_host_built_in_refuses(name):
    refuses(lambda c: c["graphs"]["build"].__setitem__("agent", name), r"built-in|reserved")


def test_a_worker_named_like_the_opencode_orchestrator_refuses():
    def m(c):
        c["opencode"]["primary_agent"] = "builder"
    refuses(m, r"primary_agent")


def test_two_workers_sharing_an_agent_name_refuse():
    def m(c):
        c["graphs"]["other"] = {**copy.deepcopy(c["graphs"]["build"]), "verb": "wiki"}
    refuses(m, r"agent 'builder'.*more than one graph")


# --- strict schema: a typo or a retired key fails, it is not ignored ------------------

@pytest.mark.parametrize("key,match", [("max_fix_loops", r"unknown key.*max_fix_loops"),
                                       ("isolaton", r"unknown key.*isolaton")])
def test_an_unknown_graph_key_refuses(key, match):
    refuses(lambda c: c["graphs"]["build"].__setitem__(key, 3), match)


@pytest.mark.parametrize("key", ["effort", "mode", "max_visit"])
def test_an_unknown_or_retired_node_key_refuses(key):
    refuses(lambda c: nodes(c)["review"].__setitem__(key, "x"), rf"unknown key.*{key}")


def test_a_main_thread_graph_cannot_claim_a_worktree():
    def m(c):
        g = refine_graph()
        g["isolation"] = "worktree"
        c["graphs"]["refine"] = g
    refuses(m, r"main_thread.*isolation")


@pytest.mark.parametrize("tool", ["Agent", "Skill", "Task", "dispatch", "subagent"])
def test_a_worker_allow_list_cannot_grant_fan_out(tool):
    refuses(lambda c: c["graphs"]["build"].__setitem__("allow", [tool]), r"fan-out")


# --- the model policy guards a worker pin on both targets (MH-05) ---------------------

def test_a_banned_worker_model_pin_refuses_on_both_targets():
    c = cfg_with(lambda c: c["graphs"]["build"].__setitem__("model", "haiku"))
    for builder in (emit.build_bindings, emit.build_bindings_opencode):
        with pytest.raises(SystemExit, match="banned"):
            builder(c)


def test_a_bogus_worker_effort_refuses():
    refuses(lambda c: c["graphs"]["build"].__setitem__("effort", "ultra"), r"effort.*ultra")


# --- a later graph is declarable: read-only, in place, with required MCP servers ------

def test_a_read_only_in_place_worker_with_required_mcp_servers_validates():
    """triage (ADR 0019 §8) is a later task; the schema must already declare it."""
    def m(c):
        c["graphs"]["triage"] = {
            "agent": "triager", "verb": "triage", "launch": "worker",
            "isolation": "none", "tools": "read_only", "max_total_steps": 150,
            "mcp_servers": {"o11y": {"claude-code": "plugin_proscia-o11y_proscia-o11y",
                                     "opencode": "proscia-o11y"},
                            "zd": {"claude-code": "plugin_proscia-zendesk_proscia-zendesk",
                                   "opencode": "proscia-zendesk"}},
            "allow": ["mcp__o11y__query", "git log *"],
            "entry": "intake",
            "nodes": {
                "intake": {"skill": "build-understand", "next": "diagnose"},
                "diagnose": {"skill": "build-validate", "max_visits": 4,
                             "next": ["report", "intake"]},
                "report": {"rubric": "review", "terminal": "drafts_returned"},
            },
        }
    b = emit.build_bindings(cfg_with(m))
    t = next(g for g in b["graphs"] if g["name"] == "triage")
    assert t["tools"] == "read_only" and t["isolation"] == "none", t
    assert t["mcp_servers"] == ["plugin_proscia-o11y_proscia-o11y",
                                "plugin_proscia-zendesk_proscia-zendesk"], t
    t = next(g for g in emit.build_bindings(cfg_with(m), "opencode")["graphs"]
             if g["name"] == "triage")
    assert t["mcp_servers"] == ["proscia-o11y", "proscia-zendesk"], t


# --- the rendered index reads in walk order, whatever the config's key order ----------

def test_the_node_walk_renders_in_walk_order_not_key_order():
    def m(c):
        n = c["graphs"]["build"]["nodes"]
        c["graphs"]["build"]["nodes"] = {k: n[k] for k in sorted(n)}  # a sorted YAML dump
    b = emit.build_bindings(cfg_with(m))
    g = next(g for g in b["graphs"] if g["name"] == "build")
    names = [i["line"].split("**")[1] for i in emit.node_lines(g, "claude-code", b["verbs"])]
    assert names == ["understand", "build", "validate", "review", "clear", "fix"], names


def test_a_main_thread_result_line_renders_without_nested_code(tmp_path):
    import tempfile
    c = cfg_with(lambda c: c["graphs"].__setitem__("refine", refine_graph()))
    out = Path(tempfile.mkdtemp(prefix="emit-idx-")) / "out"
    emit.TARGETS["claude-code"](c, out)
    idx = (out / "nodes" / "refine-graph.md").read_text()
    assert "**Result line:** the `refine` skill's own report" in idx, idx
