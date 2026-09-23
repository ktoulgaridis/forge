#!/usr/bin/env python3
"""The org brain loads structurally, and the reminders plugin is live but advisory.

- opencode.json `instructions` points at the wiki's prime reads via the ENV-VAR path
  ONLY (the portable pointer), so the operating model is in context at session start
  without the engineer having to remember the prime verb. No machine-specific absolute
  clone path is baked into the distributed artifact. Missing files are skipped by opencode.
- reminders.js binds the VERIFIED event names: a top-level session start nudges the
  prime verb (a child session does not), and compaction injects the handoff line into
  the continuation summary. Never blocking, never editing.
- Both behaviours are proven on BOTH host entrypoints: 1.x (`server()`, toast +
  compaction push) and 2.x (`setup()`, compaction hook). The toast has no 2.x
  server-side equivalent — that half is asserted 1.x-only by design.
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

HARNESS = ROOT / "tests" / "reminders_harness.mjs"


def emit_oc():
    out = Path(tempfile.mkdtemp(prefix="emit-wiki-")) / "out"
    emit.TARGETS["opencode"](CFG, out)
    return out


def run(out, scenario, host="v1"):
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "reminders.js"),
                        json.dumps(scenario), host], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_wiki_prime_reads_are_opencode_instructions():
    conf = json.loads((emit_oc() / "opencode.json").read_text())
    ins = conf["instructions"]
    assert ins[0] == "AGENTS.md"
    for read in CFG["org_wiki"]["prime_reads"]:
        # ONLY the env-var form is emitted — the portable pointer.
        assert f"{{env:{CFG['org_wiki']['local_path_env']}}}/{read}" in ins, ins
    # The machine-specific default clone path must NEVER be baked into the
    # org-wide distributed artifact (it is a per-person location, and when the
    # env var equals it the wiki double-loads).
    default = CFG["org_wiki"]["default_local_path"]
    assert not any(default in entry for entry in ins), ins
    # Exactly AGENTS.md + one env-var entry per prime read, nothing doubled.
    assert len(ins) == 1 + len(CFG["org_wiki"]["prime_reads"]), ins


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_top_level_session_start_nudges_prime_but_child_sessions_do_not():
    """The toast nudge is the 1.x half: `server()` + client.tui.showToast."""
    out = emit_oc()
    top = run(out, {"event": {"type": "session.created", "properties": {"info": {"id": "s1"}}}})
    assert len(top["toasts"]) == 1 and "/prime" in top["toasts"][0]["message"], top
    child = run(out, {"event": {"type": "session.created",
                                "properties": {"info": {"id": "s2", "parentID": "s1"}}}})
    assert child["toasts"] == [], child
    other = run(out, {"event": {"type": "session.idle", "properties": {"sessionID": "s1"}}})
    assert other["toasts"] == [], other


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_on_host_v2_no_toast_is_attempted():
    """2.x has no server-side toast API; the emitted 2.x half must stay silent on
    session start (advisory, never fabricated) — documented, by design."""
    r = run(emit_oc(), {"event": {"type": "session.created",
                                  "properties": {"info": {"id": "s1"}}}}, host="v2")
    assert r["toasts"] == [] and r["system"] == [], r


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
@pytest.mark.parametrize("host", ["v1", "v2"])
def test_compaction_injects_the_handoff_line(host):
    out = emit_oc()
    r = run(out, {"compacting": True}, host=host)
    line = (r["context"] or [None])[0] if host == "v1" else (r["system"] or [None])[0]
    assert line is not None, r
    assert "/handoff" in line and CFG["org_wiki"]["name"] in line, r


# --- wiki-pull: a clone left on a branch is reported, not silently skipped -----------

PULL_HARNESS = ROOT / "tests" / "wiki_pull_harness.mjs"


def run_pull(out, wiki, host="v1"):
    env = {k: v for k, v in os.environ.items()}
    env[CFG["org_wiki"]["local_path_env"]] = str(wiki)
    p = subprocess.run(["node", str(PULL_HARNESS), str(out / "plugin" / "wiki-pull.js"), host],
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def branch_of(wiki):
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=wiki,
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_wiki_pull_tells_the_engineer_when_the_clone_is_off_main(tmp_path):
    from test_session_surface import make_wiki
    _, wiki = make_wiki(tmp_path, branch="knowledge/left-behind")
    r = run_pull(emit_oc(), wiki)
    # one toast for the whole process, not one per session start / interval tick
    assert len(r["toasts"]) == 1, r
    msg = r["toasts"][0]["message"]
    assert "knowledge/left-behind" in msg and "main" in msg, msg
    assert str(wiki) in msg, "the engineer needs the path to switch it back"
    # still advisory: it reports, it does not move the engineer's branch
    assert branch_of(wiki) == "knowledge/left-behind"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_wiki_pull_is_silent_on_a_clean_main_clone(tmp_path):
    from test_session_surface import make_wiki
    _, wiki = make_wiki(tmp_path)
    r = run_pull(emit_oc(), wiki)
    assert r["toasts"] == [], r
    assert branch_of(wiki) == "main"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_wiki_pull_v2_setup_runs_and_never_moves_the_branch(tmp_path):
    from test_session_surface import make_wiki
    _, wiki = make_wiki(tmp_path, branch="knowledge/left-behind")
    r = run_pull(emit_oc(), wiki, host="v2")
    assert r["toasts"] == [], r
    assert branch_of(wiki) == "knowledge/left-behind"


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
@pytest.mark.parametrize("host", ["v1", "v2"])
def test_compaction_line_leaves_cycling_to_the_engineer(host):
    """The line reaches the continuing model: it says where state lives and offers
    /handoff to the engineer, rather than telling the model to cycle the session."""
    r = run(emit_oc(), {"compacting": True}, host=host)
    line = (r["context"] if host == "v1" else r["system"])[0]
    line = line.split("\n")[-1]  # 2.x wraps it in an include-verbatim instruction
    assert "if the engineer" in line.lower(), line
    assert "to cycle the session" not in line, line
    assert len(line) <= 175, (len(line), line)  # no longer than the line it replaced


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_wiki_pull_report_fails_open_when_the_toast_cannot_be_shown(tmp_path):
    from test_session_surface import make_wiki
    _, wiki = make_wiki(tmp_path, branch="knowledge/left-behind")
    r = run_pull(emit_oc(), wiki, host="v1-noclient")  # asserts exit 0 (no unhandled rejection)
    assert r["toasts"] == [], r
