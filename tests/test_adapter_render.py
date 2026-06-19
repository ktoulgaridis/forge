#!/usr/bin/env python3
"""Golden-render harness for tracker adapters (docs/ADAPTERS.md §"Adapter
doctor self-tests").

This is the anti-regression net the docs SPECIFIED but that was never built —
the gap that let the jira-acli read-path ship comment-blind (no `comment list`
in prime/refine/execute). See fix/acli-comment-read (PR1); this harness (PR2)
encodes that contract as an executable test.

What it does:
  - builds org-tier bindings from a tiny fixture .forge.org.yaml wired to the
    jira-acli adapter (lib.emit.build_bindings),
  - renders the whole templates/org-plugin tree (lib.render.render_tree),
  - SEMANTIC GUARD: asserts the rendered prime/refine/execute SKILL.md each
    carry `comment list` in their ticket-read path (NOT comment-blind),
  - asserts the full render completes with no unresolved {{placeholders}}
    (render_tree raises SystemExit(2) on any survivor).

Run:  uv run --with pytest --with pyyaml pytest tests/test_adapter_render.py -q

Mirrors tests/test_model_policy_binding.py for import/style (sys.path → lib).
"""
import sys
from pathlib import Path

import yaml

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import emit  # noqa: E402
import render  # noqa: E402

FORGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = FORGE_ROOT / "adapters/tracker/_test/sample.forge.org.yaml"
TEMPLATES = FORGE_ROOT / "templates/org-plugin"

# The rendered read-path skills (canonical verb names; the fixture sets no
# `verbs:` overrides, so emit keeps these dir names).
READ_PATH_SKILLS = ("prime", "refine", "execute")


def _render(out_dir: Path) -> dict:
    """Build bindings from the fixture, render the org-plugin tree, return
    {skill_name: rendered SKILL.md text}. Raises SystemExit on any unresolved
    placeholder (that IS assertion (c))."""
    cfg = yaml.safe_load(FIXTURE.read_text())
    bindings = emit.build_bindings(cfg)
    render.render_tree(bindings, TEMPLATES, out_dir, FORGE_ROOT)
    return {
        name: (out_dir / "skills" / name / "SKILL.md").read_text()
        for name in READ_PATH_SKILLS
    }


def test_read_path_skills_are_not_comment_blind(tmp_path):
    """SEMANTIC GUARD (load-bearing): prime, refine, AND execute must each
    inline `comment list` in their ticket-read path. This is what FAILS against
    pre-PR1 state (the jira-acli adapter had no comment-read snippet) and PASSES
    with PR1's fix wired in."""
    skills = _render(tmp_path / "emit")
    for name in READ_PATH_SKILLS:
        assert "comment list" in skills[name], (
            f"{name}/SKILL.md read path is COMMENT-BLIND: no `comment list` "
            f"found. The adapter's read snippets must fetch comments — "
            f"`view` excludes them. (Regression of fix/acli-comment-read.)"
        )


def test_prime_my_work_does_not_hard_filter_one_project(tmp_path):
    """BOARD-FROM-KEY (TEC-3416): the prime my-work query must span the boards
    the user can see, NOT hard-filter `project = <one key>`. The fixture's
    project_key (FIX) may survive only as an OPTIONAL default/example, never as
    a hard filter on the my-work search.

    FAILS against the pre-3416 adapter (`project = FIX AND assignee =
    currentUser()`); PASSES once my-work drops the single-project filter."""
    skills = _render(tmp_path / "emit")
    prime = skills["prime"]
    my_work_clause = "assignee = currentUser() AND statusCategory != Done"
    assert my_work_clause in prime, "prime my-work query changed shape unexpectedly"
    # The my-work line must not pin a single project. Check every line that
    # carries the my-work clause: none may also carry `project = <KEY>`.
    for line in prime.splitlines():
        if my_work_clause in line:
            assert "project = " not in line, (
                "prime my-work query HARD-FILTERS one project: "
                f"{line.strip()!r}. It must span all boards the user can see "
                "(board-from-key), not pin a single project_key."
            )


def test_single_lookup_derives_board_from_key_prefix(tmp_path):
    """BOARD-FROM-KEY (TEC-3416): a single-ticket lookup must derive its
    board/project from the ticket KEY PREFIX at runtime, not a config value.
    The adapter prose must say so (key-prefix → project)."""
    skills = _render(tmp_path / "emit")
    prime = skills["prime"].lower()
    assert "key prefix" in prime or "key-prefix" in prime, (
        "prime does not explain that a single-ticket lookup derives its "
        "board/project from the ticket KEY PREFIX at runtime."
    )


def test_full_render_has_no_unresolved_placeholders(tmp_path):
    """Clean full render: render_tree raises SystemExit(2) if ANY {{...}}
    survives. Reaching the assert means the whole org-plugin tree resolved."""
    skills = _render(tmp_path / "emit")
    # Belt-and-suspenders: no stray mustache tokens in the read-path output.
    for name, text in skills.items():
        assert "{{" not in text, f"{name}/SKILL.md has an unresolved placeholder"


if __name__ == "__main__":
    import tempfile

    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"PASS {fn.__name__}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {fn.__name__}: {e}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
