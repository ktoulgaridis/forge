#!/usr/bin/env python3
"""The WorktreeCreate hook, driven the way the host drives it (dogfood 2026-09-23).

The native Agent tool always sends worktree_name='agent-worktree' — there is no naming
control — so from a multi-repo workspace root the hook's repo-in-name rule can never
fire. The hook must (a) keep working when the session's cwd IS a repo, (b) fail closed
from a workspace root with a message that tells the orchestrator what to do instead
(create the worktree itself and pass WORKTREE: in the envelope), and (c) accept a
WORKTREE_REPO that is an absolute path — the target repo may not live under the
workspace root at all.

Run:  uv run --with pytest --with pyyaml pytest tests/test_worktree_hook.py -q
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq required")


@pytest.fixture(scope="module")
def hook():
    out = Path(tempfile.mkdtemp(prefix="emit-hook-")) / "out"
    emit.TARGETS["claude-code"](CFG, out)
    return out / "hooks" / "scripts" / "worktree-create.sh"


def repo(path):
    path.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "README").write_text("x")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def run(hook, cwd, env=None, name="agent-worktree"):
    payload = json.dumps({"cwd": str(cwd), "worktree_name": name, "session_id": "s"})
    e = {k: v for k, v in os.environ.items() if k != "WORKTREE_REPO"}
    return subprocess.run(["sh", str(hook)], input=payload, capture_output=True, text=True,
                          env={**e, **(env or {})})


def test_a_repo_cwd_still_gets_its_worktree(hook, tmp_path):
    r = run(hook, repo(tmp_path / "api"))
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()).is_dir(), r.stdout


def test_a_workspace_root_fails_closed_and_says_what_to_do(hook, tmp_path):
    repo(tmp_path / "api")
    repo(tmp_path / "web")
    r = run(hook, tmp_path)
    assert r.returncode != 0, r
    assert "agent-worktree" in r.stderr and "WORKTREE:" in r.stderr, r.stderr


def test_an_absolute_worktree_repo_outside_the_workspace_resolves(hook, tmp_path):
    ws = tmp_path / "ws"
    repo(ws / "api")
    repo(ws / "web")
    elsewhere = repo(tmp_path / "elsewhere" / "forge")
    r = run(hook, ws, env={"WORKTREE_REPO": str(elsewhere)})
    assert r.returncode == 0, r.stderr
    wt = r.stdout.strip()
    assert wt in subprocess.run(["git", "worktree", "list"], cwd=elsewhere,
                                capture_output=True, text=True).stdout


def test_a_relative_worktree_repo_still_resolves(hook, tmp_path):
    repo(tmp_path / "api")
    repo(tmp_path / "web")
    r = run(hook, tmp_path, env={"WORKTREE_REPO": "web"})
    assert r.returncode == 0, r.stderr


def test_remove_finds_a_worktree_anchored_outside_the_workspace(hook, tmp_path):
    ws = tmp_path / "ws"
    repo(ws / "api")
    repo(ws / "web")
    elsewhere = repo(tmp_path / "elsewhere" / "forge")
    env = {"WORKTREE_REPO": str(elsewhere)}
    wt = run(hook, ws, env=env).stdout.strip()
    rm = hook.parent / "worktree-remove.sh"
    payload = json.dumps({"cwd": str(ws), "worktree_path": wt})
    subprocess.run(["sh", str(rm)], input=payload, text=True, check=True,
                   env={**os.environ, **env})
    listed = subprocess.run(["git", "worktree", "list"], cwd=elsewhere,
                            capture_output=True, text=True).stdout
    assert wt not in listed, listed
