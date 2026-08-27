#!/usr/bin/env python3
"""Anti-regression net for the DSH (DeepSeek Harness) emit target.

`/forge:emit --target dsh` renders a DeepSeek Harness profile bundle from the
SAME .forge.org.yaml as the Claude Code target — one source, two emits. This
test locks the two load-bearing invariants of that second target:

  1. LEAK GATE: the emitted bundle carries ZERO generator identity (render_tree
     raises SystemExit(3) otherwise) and no unresolved {{placeholders}} (exit 2).
  2. READ-ONLY CONTROL: the reviewer and clearance subagent rows each carry a
     non-empty toolFilter.allow (edit/write/bash absent by omission → refused);
     the implementer row carries NO filter (full tool set). This is the control
     the whole no-self-review split rests on, so removing it must FAIL loud.

It also asserts build_bindings_dsh reuses build_bindings (one source of org
bindings) and flips the host target (TARGET_CC off, TARGET_DSH on).

Run:  uv run --with pytest --with pyyaml pytest tests/test_dsh_emit.py -q
"""
import sys
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import emit  # noqa: E402
import render  # noqa: E402

FORGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = FORGE_ROOT / "adapters/tracker/_test/sample.forge.org.yaml"


def _cfg():
    return yaml.safe_load(FIXTURE.read_text())


def test_dsh_bindings_reuse_org_bindings_and_flip_target():
    """build_bindings_dsh reuses build_bindings wholesale (one source) and flips
    the host conditionals so the DSH dispatch prose renders, not the CC prose."""
    cfg = _cfg()
    cc = emit.build_bindings(cfg)
    dsh = emit.build_bindings_dsh(cfg)
    # Every org scalar from the CC target survives unchanged in the DSH bindings.
    for k, v in cc["scalars"].items():
        assert dsh["scalars"][k] == v, f"DSH bindings dropped/changed org scalar {k}"
    # Host target flipped.
    assert cc["conditionals"] == {"TARGET_CC": True, "TARGET_DSH": False}
    assert dsh["conditionals"] == {"TARGET_CC": False, "TARGET_DSH": True}


def test_dsh_emit_is_leak_clean_and_fully_resolved(tmp_path):
    """emit_dsh renders with leak_check=True: reaching the asserts means no
    generator identity (exit 3) and no unresolved placeholder (exit 2) tripped."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)

    # The host shell + the folded shared skills are present.
    assert (out / "cordis.patch.yml").is_file()
    assert (out / "package.json").is_file()
    assert (out / "skills" / "execute" / "SKILL.md").is_file()  # fixture: no verb rename

    # Belt-and-suspenders leak scan over the whole emitted tree.
    for f in out.rglob("*"):
        if f.is_file():
            for i, line in enumerate(f.read_text().splitlines(), 1):
                assert not render.LEAK_RE.search(line), (
                    f"generator identity leaked into {f.relative_to(out)}:{i}: {line!r}"
                )


def test_dsh_reviewer_and_clearance_are_read_only_implementer_is_not(tmp_path):
    """LOAD-BEARING: in the rendered patch, reviewer + clearance carry a
    read-only toolFilter; the implementer carries none (full tools)."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)
    patch = (out / "cordis.patch.yml").read_text()

    assert "toolName: subagent_review" in patch
    assert "toolName: subagent_clearance" in patch
    assert "toolName: subagent_implement" in patch
    # Exactly two read-only filters (reviewer + clearance); the implementer row
    # must NOT introduce a third. Count is the guard against a mis-wired filter.
    assert patch.count("toolFilter:") == 2, (
        "expected exactly 2 toolFilter rows (reviewer + clearance); the "
        "implementer must have none"
    )
    assert "allow: [read, grep, glob]" in patch


def test_dsh_engage_skill_uses_direct_dispatch_not_workflow(tmp_path):
    """The DSH-target engage skill renders the direct-tool dispatch (TARGET_DSH)
    and drops the Claude Code Workflow/pipeline prose (TARGET_CC)."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)
    engage = (out / "skills" / "execute" / "SKILL.md").read_text()
    assert "subagent_implement" in engage and "subagent_review" in engage
    # The CC-only Workflow pipeline example must not survive into the DSH emit.
    assert "pipeline(tasks," not in engage


def test_dsh_empty_reviewer_allow_fails_loud():
    """MUTATION: emptying the reviewer's read-only allow-set must FAIL the emit
    (the read-only set is the load-bearing control, not a vacuous default)."""
    cfg = _cfg()
    cfg["dsh"]["subagents"]["reviewer"]["toolFilter"] = {"allow": []}
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_missing_section_fails_loud():
    """A config with no dsh: section cannot emit the DSH target."""
    cfg = _cfg()
    cfg.pop("dsh")
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
