#!/usr/bin/env python3
"""The OPTIONAL supplementary reviewer is a read-only agent on BOTH targets (ADR 0018 §5
as amended by ADR 0019 §7). On Claude Code it was a general-purpose Agent with write
tools and no turn cap; now it is an emitted agent that cannot edit, spawn or load a verb,
is capped by the host, and runs only on a COMPLETED PR — never inside the build loop.

Run:  uv run --with pytest --with pyyaml pytest tests/test_cc_supplementary_reviewer.py -q
"""
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def emit_cc(cfg=None):
    out = Path(tempfile.mkdtemp(prefix="emit-supp-cc-")) / "out"
    emit.TARGETS["claude-code"](cfg or CFG, out)
    return out


def split(md):
    _, fm, body = md.split("---", 2)
    return yaml.safe_load(fm), body


def test_enabled_reviewer_is_a_read_only_capped_cc_agent():
    fm, body = split((emit_cc() / "agents" / "validate.md").read_text())
    assert fm["name"] == "validate", fm
    tools = [t.strip() for t in fm["tools"].split(",")]
    assert tools == ["Read", "Bash"], tools
    disallowed = [t.strip() for t in fm["disallowedTools"].split(",")]
    for t in ("Edit", "Write", "NotebookEdit", "Agent", "Skill"):
        assert t in disallowed, (t, disallowed)
    assert fm["maxTurns"] == CFG["supplementary_reviewer"]["max_steps"], fm
    assert fm["model"] == "inherit", fm
    assert "completed" in body.lower() and "gh pr diff" in body, body


def test_disabled_reviewer_emits_no_cc_agent():
    out = emit_cc(cfg_with(lambda c: c["supplementary_reviewer"].__setitem__("enabled", False)))
    assert not (out / "agents" / "validate.md").exists()


def test_both_reviewers_can_read_the_pr_they_judge():
    oc = Path(tempfile.mkdtemp(prefix="emit-supp-oc-")) / "out"
    emit.TARGETS["opencode"](CFG, oc)
    fm, body = split((oc / "agent" / "validate.md").read_text())
    for pat in ("gh pr diff *", "gh pr view *"):
        assert fm["permission"]["bash"].get(pat) == "allow", fm["permission"]["bash"]
    assert "cannot edit code" in body and "reach the network" not in body, body


def test_the_verdict_names_severity_and_confidence():
    for body in (split((emit_cc() / "agents" / "validate.md").read_text())[1],):
        assert "severity" in body and "confidence" in body, body
