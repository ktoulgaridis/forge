#!/usr/bin/env python3
"""The shipped example configs are real catalogs: they validate and emit on BOTH targets
(with the example identity swapped for a fictional org, since emit refuses example
tokens on purpose). examples/graph-catalog.forge.org.yaml declares the build worker and a
main-thread refine graph with the ADR 0019 node names and its two human gates.

Run:  uv run --with pytest --with pyyaml pytest tests/test_example_configs.py -q
"""
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402

EXAMPLES = [ROOT / ".forge.org.example.yaml", ROOT / "examples" / "graph-catalog.forge.org.yaml"]
REFINE_NODES = ["load", "need", "validation", "architecture", "slos", "cybersec", "trace",
                "deps", "sketch", "ready", "mark"]


def load(path):
    cfg = yaml.safe_load(path.read_text())
    cfg["org"] = {"name": "Fictco", "slug": "fictco"}
    cfg["plugin"].update({"name": "fictco-harness",
                          "author": {"name": "Fictco Eng", "url": "https://github.com/fictco"},
                          "homepage": "https://github.com/fictco/fictco-harness"})
    return cfg


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_the_example_emits(path, target):
    out = Path(tempfile.mkdtemp(prefix="emit-example-")) / "out"
    emit.TARGETS[target](load(path), out)
    ad = "agents" if target == "claude-code" else "agent"
    assert (out / ad / "builder.md").is_file()


def test_the_catalog_example_declares_the_adr_0019_refine_graph():
    cfg = load(EXAMPLES[1])
    refine = cfg["graphs"]["refine"]
    assert refine["launch"] == "main_thread" and list(refine["nodes"]) == REFINE_NODES
    assert refine["nodes"]["validation"]["gate"] == "product"
    assert refine["nodes"]["mark"]["gate"] == "engineer"
    out = Path(tempfile.mkdtemp(prefix="emit-example-")) / "out"
    emit.TARGETS["claude-code"](cfg, out)
    idx = (out / "skills" / "refine-graph" / "SKILL.md").read_text()
    assert "gate: product" in idx and "gate: engineer" in idx, idx
    assert "Walked by the session running `refine`" in idx, idx
