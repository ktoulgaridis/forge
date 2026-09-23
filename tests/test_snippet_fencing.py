#!/usr/bin/env python3
"""Tracker snippets render inside fenced code blocks (render.py), exactly once.

An adapter snippet is a block of shell with `# comment` lines. Inlined bare, every
comment became a markdown H1 in the emitted skill and the commands lost the delimiter
that marks them as exact. The renderer now fences a bare placeholder, leaves a
placeholder that a template ALREADY fenced with a single fence (idempotent), indents a
placeholder that sits inside a list item, and carries the org's verb names into the
snippet text.

Run:  uv run --with pytest --with pyyaml pytest tests/test_snippet_fencing.py -q
"""
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
import render  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def emit_cc(cfg=None):
    out = Path(tempfile.mkdtemp(prefix="emit-fence-")) / "out"
    emit.TARGETS["claude-code"](cfg or CFG, out)
    return out


def headings_outside_fences(text):
    bad, fenced = [], False
    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"^# ", ln) and "acli" not in ln:
            bad.append(ln)
    return bad


def render_one(tmp_path, body, cfg=None):
    tpl = tmp_path / "t.md.template"
    tpl.write_text(body)
    dest = tmp_path / "out" / "t.md"
    render.render_file(emit.build_bindings(cfg or CFG), tpl, dest, ROOT)
    return dest.read_text()


def test_a_bare_placeholder_renders_inside_one_fence(tmp_path):
    txt = render_one(tmp_path, "Check:\n\n{{TRACKER_GATE_SNIPPET}}\n\nThen go.\n")
    assert "```bash\n# the " in txt.lower() or "```bash\n#" in txt, txt
    assert txt.count("```") % 2 == 0 and txt.count("```bash") == 1, txt
    assert not headings_outside_fences(txt), headings_outside_fences(txt)


def test_an_already_fenced_placeholder_is_not_fenced_twice(tmp_path):
    txt = render_one(tmp_path, "Check:\n\n```\n{{TRACKER_GATE_SNIPPET}}\n```\n\nThen go.\n")
    assert "```\n```" not in txt and "```bash" not in txt, txt
    assert txt.count("```") == 2, txt
    assert "acli jira workitem view <key>" in txt, txt


def test_an_indented_placeholder_keeps_the_list_item(tmp_path):
    txt = render_one(tmp_path, "- **Status** → sync the tracker.\n  {{TRACKER_COMMENT_SNIPPET}}\n- next\n")
    block = txt.split("- **Status** → sync the tracker.\n", 1)[1].split("- next", 1)[0]
    lines = [ln for ln in block.splitlines() if ln]
    assert lines[0] == "  ```bash" and lines[-1] == "  ```", lines
    assert all(ln.startswith("  ") for ln in lines), lines


def test_every_emitted_skill_has_no_snippet_comment_as_a_heading():
    """A skill has one H1 (its title); a snippet comment rendered unfenced adds more."""
    out = emit_cc()
    for f in sorted((out / "skills").glob("*/SKILL.md")):
        h1 = headings_outside_fences(f.read_text())
        assert len(h1) <= 1, (f.parent.name, h1)


def test_the_org_verbs_reach_the_snippet_text():
    out = emit_cc(cfg_with(lambda c: c.__setitem__("verbs", {"execute": "engage",
                                                             "refine": "groom"})))
    ex = (out / "skills" / "engage" / "SKILL.md").read_text()
    assert "refine→execute" not in ex and "groom→engage" in ex, ex


def test_the_acli_adapter_does_not_read_labels_through_json():
    text = (ROOT / "adapters/tracker/jira-acli.md").read_text()
    assert not re.search(r"view <key> --fields [^\n]*labels[^\n]*--json", text), \
        "`view --json` reports labels as null — a JSON label read at the gate lies"
    assert "labels" in text and "search" in text and "--csv" in text


def test_adapter_comments_are_not_shouting():
    text = (ROOT / "adapters/tracker/jira-acli.md").read_text()
    for shout in ("ACROSS EVERY", "DERIVED FROM THE KEY PREFIX", "Do NOT pin", "DISCOVER the"):
        assert shout not in text, shout


def test_the_default_model_rule_is_not_a_workflow_fossil():
    rule = emit.model_policy_scalars({})["MODEL_POLICY_RULE"]
    assert "agent()" not in rule and "Agent" in rule, rule
