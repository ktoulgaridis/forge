#!/usr/bin/env python3
"""The org brain loads structurally, and the reminders plugin is live but advisory.

- opencode.json `instructions` points at the wiki's prime reads via the ENV-VAR path
  ONLY (the portable pointer), so the operating model is in context at session start
  without the engineer having to remember the prime verb. No machine-specific absolute
  clone path is baked into the distributed artifact. Missing files are skipped by opencode.
- reminders.js binds the VERIFIED event names: a top-level session start nudges the
  prime verb (a child session does not), and compaction injects the handoff line into
  the continuation summary. Never blocking, never editing.
"""
import json
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


def run(out, scenario):
    p = subprocess.run(["node", str(HARNESS), str(out / "plugin" / "reminders.js"),
                        json.dumps(scenario)], capture_output=True, text=True)
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
    out = emit_oc()
    top = run(out, {"event": {"type": "session.created", "properties": {"info": {"id": "s1"}}}})
    assert len(top["toasts"]) == 1 and "/prime" in top["toasts"][0]["message"], top
    child = run(out, {"event": {"type": "session.created",
                                "properties": {"info": {"id": "s2", "parentID": "s1"}}}})
    assert child["toasts"] == [], child
    other = run(out, {"event": {"type": "session.idle", "properties": {"sessionID": "s1"}}})
    assert other["toasts"] == [], other


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_compaction_injects_the_handoff_line():
    r = run(emit_oc(), {"compacting": True})
    assert len(r["context"]) == 1, r
    assert "/handoff" in r["context"][0] and CFG["org_wiki"]["name"] in r["context"][0], r
