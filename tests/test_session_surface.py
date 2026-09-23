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


# --- the wiki default path resolves when the env var is unset -----------------------

def default_wiki(tmp: Path) -> Path:
    """The config's default clone path (`~/…`) under the throwaway $HOME."""
    rel = CFG["org_wiki"]["default_local_path"]
    assert rel.startswith("~/"), rel
    return tmp / "home" / rel[2:]


def test_prime_finds_the_default_wiki_when_the_env_var_is_unset(tmp_path):
    wiki = default_wiki(tmp_path)
    wiki.mkdir(parents=True)
    (wiki / "CLAUDE.md").write_text("# schema\n")
    block = bash_block(skill("prime"), 'test -f "$WIKI/CLAUDE.md"')
    p = sh(block, cwd=tmp_path, env=base_env(tmp_path), check=False)
    assert p.returncode == 0 and "not found" not in p.stdout, p.stdout + p.stderr


def test_prime_reminder_finds_the_default_wiki_when_the_env_var_is_unset(tmp_path):
    wiki = default_wiki(tmp_path)
    wiki.mkdir(parents=True)
    (wiki / "CLAUDE.md").write_text("# schema\n")
    ctx = run_hook(tmp_path, "prime-reminder.sh", base_env(tmp_path))["hookSpecificOutput"]
    assert "not found" not in ctx["additionalContext"].lower(), ctx


def test_wiki_skill_scripts_resolve_the_default_path():
    md = skill("wiki")
    # a quoted ${VAR:-~/…} never expands the tilde (bash, sh and zsh agree)
    assert '"${%s:-~' % WIKI_ENV not in md, "quoted default path keeps a literal ~"


def run_hook(tmp: Path, name, env, payload=""):
    script = emit_target("claude-code") / "hooks" / "scripts" / name
    p = subprocess.run(["sh", str(script)], input=payload, env=env, cwd=tmp,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


# --- prime ------------------------------------------------------------------------

def run_prime_locate(tmp: Path, wiki: Path):
    block = bash_block(skill("prime"), 'test -f "$WIKI/CLAUDE.md"')
    return sh(block, cwd=tmp, env=base_env(tmp, **{WIKI_ENV: str(wiki)}))


def test_prime_tells_the_engineer_when_the_wiki_clone_is_off_main(tmp_path):
    _, wiki = make_wiki(tmp_path, branch="knowledge/left-behind")
    out = run_prime_locate(tmp_path, wiki).stdout
    assert "knowledge/left-behind" in out and "main" in out, out
    # prime only reads: it reports, it does not switch the engineer's branch
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wiki) == "knowledge/left-behind"


def test_prime_locate_is_quiet_on_main(tmp_path):
    _, wiki = make_wiki(tmp_path)
    assert run_prime_locate(tmp_path, wiki).stdout.strip() == ""


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_prime_ends_without_inviting_unscoped_work(target):
    low = skill("prime", target).lower()
    assert "begin work" not in low, "prime invites work the user did not ask for"
    assert "stop after the summary" in low, "prime does not say to stop when calibration was the ask"
    assert "only reads" in low, "prime lost its read-only contract"


def test_prime_does_not_reread_the_auto_loaded_workspace_index():
    md = skill("prime")
    assert "cat ./CLAUDE.md" not in md, "re-reads the workspace CLAUDE.md the host already loaded"
    assert "already in context" in md.lower(), "no read-only-if-missing guidance for the repo index"


# --- setup: persisting the wiki path is idempotent ----------------------------------

def run_setup_persist(tmp: Path, workspace: Path):
    block = bash_block(skill("setup"), "WIKI_ABS=")
    (workspace / CFG["org_wiki"]["name"]).mkdir(parents=True, exist_ok=True)
    return sh(block, cwd=workspace, env=base_env(tmp, SHELL="/bin/zsh"))


def exports(rc: Path):
    return [ln for ln in rc.read_text().splitlines() if ln.startswith(f"export {WIKI_ENV}=")]


def test_setup_rerun_does_not_append_the_export_again(tmp_path):
    rc = tmp_path / "home" / ".zshrc"
    (tmp_path / "home").mkdir()
    rc.write_text("alias ll='ls -l'\n")
    ws = tmp_path / "ws"
    for _ in range(3):
        run_setup_persist(tmp_path, ws)
    wiki_abs = (ws / CFG["org_wiki"]["name"]).resolve()
    assert exports(rc) == [f'export {WIKI_ENV}="{wiki_abs}"'], rc.read_text()
    assert "alias ll='ls -l'" in rc.read_text(), "unrelated rc content lost"


def test_setup_rerun_after_the_wiki_moved_replaces_the_export(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "zshrc"
    real.write_text("alias ll='ls -l'\n")
    (home / ".zshrc").symlink_to(real)  # dotfile managers symlink the rc
    run_setup_persist(tmp_path, tmp_path / "old")
    run_setup_persist(tmp_path, tmp_path / "new")
    rc = home / ".zshrc"
    moved = (tmp_path / "new" / CFG["org_wiki"]["name"]).resolve()
    assert exports(rc) == [f'export {WIKI_ENV}="{moved}"'], rc.read_text()
    assert rc.is_symlink(), "rewriting the rc replaced the engineer's symlink"
    assert "alias ll='ls -l'" in real.read_text()
