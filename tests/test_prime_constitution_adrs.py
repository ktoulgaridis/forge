#!/usr/bin/env python3
"""prime names the org's constitution ADRs instead of "read the relevant ones".

`org_wiki.constitution_adrs` lists wiki-relative ADR paths. When set, the emitted prime
reads exactly those files and leaves every other ADR on demand. When unset, prime keeps
the generic "constitution-class ADRs" instruction.

Run:  uv run --with pytest --with pyyaml pytest tests/test_prime_constitution_adrs.py -q
"""
import copy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from render import render_tree  # noqa: E402
from test_prime_scope_aware import CFG  # noqa: E402

ADRS = ["decisions/0001-constitution.md", "decisions/0003-disclosure.md"]


def emit_prime(cfg) -> str:
    tmp = Path(tempfile.mkdtemp(prefix="emit-prime-adrs-"))
    render_tree(emit.build_bindings(cfg), ROOT / "templates/org-plugin", tmp, ROOT,
                leak_check=True)
    return (tmp / "skills/prime/SKILL.md").read_text()


def with_adrs():
    cfg = copy.deepcopy(CFG)
    cfg["org_wiki"]["constitution_adrs"] = ADRS
    return cfg


def test_named_adrs_are_read_by_path():
    txt = emit_prime(with_adrs())
    for adr in ADRS:
        assert f'cat "$WIKI/{adr}"' in txt, adr
    assert "Read the ones relevant" not in txt


def test_unset_keeps_generic_instruction():
    txt = emit_prime(CFG)
    assert "constitution-class ADRs" in txt
    assert 'cat "$WIKI/decisions/' not in txt


def test_execute_gate_check_names_no_missing_rubric():
    # Both targets' step 4 pointed at a gate "lens"/wiki rules that do not exist.
    txt = (ROOT / "templates/org-plugin/skills/execute/SKILL.md.template").read_text()
    assert "execution-ready lens" not in txt
    assert "execution-ready gate rules" not in txt
