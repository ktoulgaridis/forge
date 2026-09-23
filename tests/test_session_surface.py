#!/usr/bin/env python3
"""TEC-4093 — the session surface (prime / handoff / wiki / intro / setup + the hooks).

The exact scripts these skills hand the model are executed here against throwaway git
repos and a throwaway $HOME, because a gen-5 model runs an exact script literally: a
wrong script is a live bug, not a style nit.

Run:  uv run --with pytest --with pyyaml pytest tests/test_session_surface.py -q
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG  # noqa: E402

WIKI_ENV = CFG["org_wiki"]["local_path_env"]


def emit_target(target):
    out = Path(tempfile.mkdtemp(prefix=f"emit-surface-{target}-")) / "out"
    with redirect_stdout(io.StringIO()):
        emit.TARGETS[target](CFG, out)
    return out


def skill(name, target="claude-code"):
    out = emit_target(target)
    return (out / ("skills" if target == "claude-code" else "skill") / name / "SKILL.md").read_text()


def bash_block(md, marker):
    """The one ```bash fenced block in `md` that contains `marker`."""
    blocks = [b for b in re.findall(r"```bash\n(.*?)\n```", md, re.S) if marker in b]
    assert len(blocks) == 1, f"expected one bash block containing {marker!r}, got {len(blocks)}"
    return blocks[0]


def sh(cmd, cwd=None, env=None, check=True):
    p = subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True)
    if check:
        assert p.returncode == 0, f"{cmd!r} failed:\n{p.stdout}\n{p.stderr}"
    return p


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def make_wiki(tmp: Path, branch="main"):
    """A bare origin with one commit on main, and a clone of it (the engineer's wiki)."""
    origin = tmp / "origin.git"
    seed = tmp / "seed"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp)
    git("init", "-q", "-b", "main", str(seed), cwd=tmp)
    (seed / "CLAUDE.md").write_text("# schema\n")
    for a in (["add", "CLAUDE.md"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit",
                                     "-qm", "seed"], ["remote", "add", "origin", str(origin)],
              ["push", "-q", "origin", "main"]):
        git(*a, cwd=seed)
    wiki = tmp / "wiki"
    git("clone", "-q", str(origin), str(wiki), cwd=tmp)
    git("config", "user.name", "t", cwd=wiki)
    git("config", "user.email", "t@t", cwd=wiki)
    if branch != "main":
        git("switch", "-q", "-c", branch, cwd=wiki)
    return origin, wiki


def base_env(tmp: Path, **extra):
    env = {k: v for k, v in os.environ.items() if k != WIKI_ENV}
    env.update({"HOME": str(tmp / "home"), "GIT_CONFIG_NOSYSTEM": "1"})
    (tmp / "home").mkdir(exist_ok=True)
    env.update(extra)
    return env


# --- wiki contribute --------------------------------------------------------------

def contribute_script(page_text="a learning\n"):
    script = bash_block(skill("wiki"), "gh pr create")
    script = script.replace("<short-slug>", "test-slug")
    # the model writes the page at the marked point; the test does it with a shell line
    lines = []
    for line in script.splitlines():
        if line.lstrip().startswith("# write"):
            line = f'mkdir -p "$(dirname "$WIKI/$PAGE")" && printf %s {json.dumps(page_text)} > "$WIKI/$PAGE"'
        lines.append(line)
    return "\n".join(lines)


def run_contribute(tmp: Path, gh_exit=0):
    origin, wiki = make_wiki(tmp)
    (wiki / "scratch.txt").write_text("unrelated scratch\n")  # must not be committed
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "gh.log"
    (bin_dir / "gh").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit {gh_exit}\n')
    (bin_dir / "gh").chmod(0o755)
    env = base_env(tmp, **{WIKI_ENV: str(wiki), "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    p = sh(contribute_script(), cwd=tmp, env=env, check=False)
    return origin, wiki, log, p


def test_wiki_contribute_opens_the_pr_and_returns_the_clone_to_main(tmp_path):
    origin, wiki, log, p = run_contribute(tmp_path)
    assert "pr create" in log.read_text(), p.stderr
    # the clone is back on main, so wiki-pull keeps fast-forwarding and prime reads main
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wiki) == "main", p.stderr
    # the knowledge branch reached origin with the page, and only the page
    files = git("ls-tree", "-r", "--name-only", "knowledge/test-slug", cwd=origin).splitlines()
    assert "learnings/test-slug.md" in files, files
    assert "scratch.txt" not in files, "unrelated scratch in the clone was committed"
    assert "?? scratch.txt" in git("status", "--porcelain", cwd=wiki), "scratch file disturbed"


def test_wiki_contribute_returns_to_main_even_when_the_pr_step_fails(tmp_path):
    _, wiki, _, p = run_contribute(tmp_path, gh_exit=1)
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wiki) == "main", p.stderr
    # the commit is kept on the local branch so the engineer can retry the PR
    assert git("branch", "--list", "knowledge/test-slug", cwd=wiki), "branch lost"


def test_wiki_contribute_branches_from_origin_main_not_the_current_branch(tmp_path):
    origin, wiki = make_wiki(tmp_path, branch="stale-work")
    (wiki / "stale.md").write_text("stale\n")
    git("add", "stale.md", cwd=wiki)
    git("commit", "-qm", "stale", cwd=wiki)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "gh").chmod(0o755)
    env = base_env(tmp_path, **{WIKI_ENV: str(wiki), "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    sh(contribute_script(), cwd=tmp_path, env=env)
    files = git("ls-tree", "-r", "--name-only", "knowledge/test-slug", cwd=origin).splitlines()
    assert "stale.md" not in files, "the knowledge branch carried an unrelated local branch"
