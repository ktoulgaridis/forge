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
