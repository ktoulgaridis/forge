#!/usr/bin/env python3
"""Non-entry graph nodes are path-read FILES, not session skills (TEC-4098).

Every emitted skill costs every session an always-on listing line and is model-invocable
from the main session. A worker needs only its graph index + entry node preloaded (ADR
0019 §4); every other node is read by path on entry (ADR 0003). So, on BOTH targets:

  - the skills emitted are exactly the verbs + each worker's preloads (index + entry);
  - every other node skill, and a main_thread graph's index, lands as a plain file in the
    node dir beside the rubrics (CC `nodes/`, opencode `node/`), with no skill frontmatter;
  - each graph index names each node by a path that resolves in the emitted tree;
  - a dangling node reference fails the emit.

Run:  uv run --with pytest --with pyyaml pytest tests/test_node_files.py -q
"""
import re
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402

EXAMPLE = ROOT / "examples" / "graph-catalog.forge.org.yaml"
SKILLS = {"claude-code": "skills", "opencode": "skill"}
NODES = {"claude-code": "nodes", "opencode": "node"}
PRELOADS = {"build-graph", "build-understand", "triage-graph", "triage-intake"}
PATH_READ = {"build-implement", "build-validate", "build-fix", "triage-hypothesize",
             "triage-investigate", "triage-sanitize", "triage-report", "triage-propose"}


def load(mutate=None):
    cfg = yaml.safe_load(EXAMPLE.read_text())
    cfg["org"] = {"name": "Fictco", "slug": "fictco"}
    cfg["plugin"].update({"name": "fictco-harness",
                          "author": {"name": "Fictco Eng", "url": "https://github.com/fictco"},
                          "homepage": "https://github.com/fictco/fictco-harness"})
    if mutate:
        mutate(cfg)
    return cfg


def emitted(target, cfg=None):
    out = Path(tempfile.mkdtemp(prefix=f"emit-nodes-{target}-")) / "out"
    emit.TARGETS[target](cfg or load(), out)
    return out


@pytest.fixture(scope="module", params=["claude-code", "opencode"])
def tree(request):
    return request.param, emitted(request.param)


def index_text(out, target, graph):
    skill = out / SKILLS[target] / f"{graph}-graph" / "SKILL.md"
    return skill.read_text() if skill.is_file() else \
        (out / NODES[target] / f"{graph}-graph.md").read_text()


def refs(text, target):
    """Every node path an index line names, as a path relative to the emitted root."""
    lines = [ln for ln in text.splitlines() if ln.startswith("- **")]
    if target == "claude-code":
        return [m for ln in lines for m in re.findall(r"`\$\{CLAUDE_PLUGIN_ROOT\}/([^`]+)`", ln)]
    return [m for ln in lines for m in re.findall(r"\(`([a-z]+/[^`$ ]+\.md)`\)", ln)]


def test_the_emitted_skills_are_exactly_the_verbs_and_the_worker_preloads(tree):
    target, out = tree
    verbs = set(emit.build_bindings(load())["verbs"].values())
    got = {d.name for d in (out / SKILLS[target]).iterdir() if (d / "SKILL.md").is_file()}
    graph_skills = got - verbs
    assert graph_skills == PRELOADS, \
        f"{target}: graph skills beyond the preloads: {sorted(graph_skills - PRELOADS)}; " \
        f"missing: {sorted(PRELOADS - graph_skills)}"
    assert not PATH_READ & got, f"{target}: non-entry node(s) emitted as skills"


def test_non_entry_nodes_are_plain_files_in_the_node_dir(tree):
    target, out = tree
    for name in PATH_READ | {"refine-graph"}:
        f = out / NODES[target] / f"{name}.md"
        assert f.is_file(), f"{target}: {f.relative_to(out)} was not emitted"
        body = f.read_text()
        assert not body.startswith("---"), f"{target}: {name}.md still carries skill frontmatter"
        assert body.lstrip().startswith("# "), f"{target}: {name}.md lost its heading"
        assert "{{" not in body, f"{target}: {name}.md has an unresolved placeholder"
        assert not (out / SKILLS[target] / name).exists(), f"{target}: {name} is still a skill"


def test_the_node_dir_sits_beside_the_rubrics(tree):
    target, out = tree
    rubrics = {"claude-code": "rubrics", "opencode": "rubric"}[target]
    assert (out / rubrics).is_dir() and (out / NODES[target]).is_dir()
    assert (out / NODES[target]).parent == (out / rubrics).parent


@pytest.mark.parametrize("graph", ["build", "triage", "refine"])
def test_every_index_line_names_a_path_that_resolves(tree, graph):
    target, out = tree
    text = index_text(out, target, graph)
    got = refs(text, target)
    n = len(load()["graphs"][graph]["nodes"])
    assert len(got) == n, f"{target} {graph}: {len(got)} node paths for {n} nodes: {got}"
    for rel in got:
        assert (out / rel).is_file(), f"{target} {graph}: index names {rel}, not emitted"


def test_worker_indexes_name_the_entry_skill_and_node_files(tree):
    target, out = tree
    sk, nd = SKILLS[target], NODES[target]
    rb = {"claude-code": "rubrics", "opencode": "rubric"}[target]
    want = {
        "build": [f"{sk}/build-understand/SKILL.md", f"{nd}/build-implement.md",
                  f"{nd}/build-validate.md", f"{rb}/review.md", f"{rb}/gate.md",
                  f"{nd}/build-fix.md", f"{nd}/check-verify.md"],
        "triage": [f"{sk}/triage-intake/SKILL.md", f"{nd}/triage-hypothesize.md",
                   f"{nd}/triage-investigate.md", f"{rb}/diagnosis.md",
                   f"{nd}/triage-sanitize.md", f"{nd}/triage-report.md",
                   f"{nd}/triage-propose.md"],
    }
    for graph, paths in want.items():
        assert refs(index_text(out, target, graph), target) == paths, (target, graph)


def test_the_opencode_worker_body_names_the_same_resolvable_paths():
    out = emitted("opencode")
    for agent in ("builder", "triager"):
        body = (out / "agent" / f"{agent}.md").read_text()
        got = refs(body, "opencode")
        assert got and all((out / rel).is_file() for rel in got), (agent, got)
        assert any(rel.startswith("node/") for rel in got), (agent, got)


def test_a_main_thread_graphs_non_verb_node_skill_is_a_file_too():
    def m(c):
        c["graphs"]["refine"]["nodes"]["sketch"]["skill"] = "build-fix"
    for target in ("claude-code", "opencode"):
        out = emitted(target, load(m))
        assert (out / NODES[target] / "build-fix.md").is_file(), target
        assert f"{NODES[target]}/build-fix.md" in refs(index_text(out, target, "refine"), target)


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_a_dangling_node_reference_fails_the_emit(target, monkeypatch):
    real = emit._node_rel

    def dangling(kind, name, tgt):
        rel = real(kind, name, tgt)
        return rel.replace("build-fix", "build-fix-missing")
    monkeypatch.setattr(emit, "_node_rel", dangling)
    with pytest.raises(SystemExit, match=r"build-fix-missing.*not emitted|dangling"):
        emitted(target)
