#!/usr/bin/env python3
"""TEC-3478 — prime is lean, progressively-disclosed, scope-aware (Org-default).

Renders the org-plugin tree from a real (non-example) config and asserts the
EMITTED prime SKILL.md exhibits the behavioral W2 half:
  1. T1-only by default; deep per-project reads DEFERRED / progressive.
  2. prime SELF-RESOLVES scope (ticket/repo/wiki/handoff/tracker) and only
     ESCALATES to a human when no source answers — never forces a declaration.
  3. defaults to ORG when scope is unresolved / cross-cutting / SRE / one-off.
  4. ORG MODE skips the project-hub ADR + workspace repo-index (step 7) and the
     single-repo load (step 8); those are PROJECT-MODE-ONLY.
  5. calibration summary still emitted (step 9) and now carries a Scope line.

Run:  uv run --with pyyaml python tests/test_prime_scope_aware.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402
from render import render_tree  # noqa: E402

CFG = {
    "org": {"name": "Testco", "slug": "testco"},
    "plugin": {
        "name": "testco-harness", "version": "0.1.0", "description": "d",
        "author": {"name": "Testco Platform Engineering", "url": "https://github.com/testco"},
        "homepage": "https://github.com/testco/testco-harness", "license": "UNLICENSED",
    },
    "org_wiki": {
        "name": "testco-wiki", "remote": "git@github.com:testco/testco-wiki.git",
        "local_path_env": "TESTCO_WIKI", "default_local_path": "~/work/testco-wiki",
        "prime_reads": ["operating-model.md"],
    },
    "tracker": {"type": "jira-acli", "config": {
        "cloud_id": "00000000-0000-0000-0000-000000000000",
        "project_key": "TST", "base_url": "https://testco.atlassian.net",
    }},
    "agents": [
        {"name": "implementer", "model": "sonnet"},
        {"name": "reviewer", "model": "sonnet"},
        {"name": "gate", "model": "sonnet"},
    ],
}


def emit_prime() -> str:
    bindings = emit.build_bindings(CFG)
    tmp = Path(tempfile.mkdtemp(prefix="emit-verify-3478-test-"))
    render_tree(bindings, ROOT / "templates/org-plugin", tmp, ROOT, leak_check=True)
    # canonical skill dir is 'prime'; org may rename, but Testco uses defaults.
    matches = list(tmp.rglob("skills/*prime*/SKILL.md")) or list(tmp.rglob("skills/prime/SKILL.md"))
    assert matches, f"no emitted prime SKILL.md under {tmp}"
    return matches[0].read_text()


def test_leak_clean_and_no_unresolved():
    # render_tree raises SystemExit on unresolved placeholders or identity leaks.
    txt = emit_prime()
    assert "{{" not in txt, "unresolved placeholder survived in emitted prime"
    low = txt.lower()
    assert "forge" not in low and "toulgaridis" not in low, "identity leak in emitted prime"


def test_t1_only_by_default():
    txt = emit_prime().lower()
    assert "progressive" in txt or "defer" in txt, "no progressive-disclosure framing"
    assert "tier-1" in txt or "t1" in txt, "T1 not named as the default read set"
    # deep per-project reads must be explicitly deferred, not eager.
    assert "promote" in txt and "detail" in txt, "no promote-to-detail-on-demand language"


def test_self_resolves_scope():
    txt = emit_prime().lower()
    assert "resolve" in txt and "scope" in txt, "no scope-resolution step"
    # the resolution sources must be named.
    for src in ["ticket", "repo", "wiki", "handoff"]:
        assert src in txt, f"scope-resolution source '{src}' not named"
    # escalate to a human ONLY as last resort; never force a declaration.
    assert "escalat" in txt, "no human-escalation fallback"
    assert "not force" in txt or "never force" in txt or "without forcing" in txt, \
        "does not promise NOT to force a project declaration"


def test_defaults_to_org():
    txt = emit_prime().lower()
    assert "default" in txt and "org" in txt, "no org-default framing"
    # cross-cutting / SRE / one-off work defaults to org.
    assert "cross-cutting" in txt or "sre" in txt or "one-off" in txt, \
        "cross-cutting/SRE/one-off org-default case missing"


def test_project_reads_conditional():
    txt = emit_prime().lower()
    # both the project-hub-ish read and the repo-index/single-repo reads are
    # gated on PROJECT MODE.
    assert "project mode" in txt, "no explicit 'project mode' gating"
    assert "skip" in txt and "org mode" in txt, "org mode does not skip project-only reads"
    # repo index is named and gated.
    assert "repo index" in txt, "workspace repo-index read not present"


def test_calibration_summary_has_scope_line():
    txt = emit_prime()
    low = txt.lower()
    assert "calibration summary" in low, "calibration summary contract lost"
    # the new Scope line, formatted Scope (Org | <project>).
    assert "scope (org" in low, "calibration summary missing 'Scope (Org | <project>)' line"


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
        except SystemExit as e:
            failed += 1
            print(f"FAIL {fn.__name__}: emit/render raised SystemExit: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
