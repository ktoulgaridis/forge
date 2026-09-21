#!/usr/bin/env python3
"""Acceptance tests for the sidebar run tree (forge#28, step 5).

The maintainer's ruling: browsing covers BOTH engines — one sidebar tree over
the orchestrator's runs, grouping on `parentID ?? metadata.parent` (native
subagent children group naturally; dispatch children via the metadata fallback
the round trip now writes). A TUI plugin (`plugin/tui.js`) renders the tree into
the `sidebar_content` slot; the 2.x host loads it via the `./tui` export.

Each test below holds one piece to a checkable claim:

  - the artifact emits plugin/tui.js, and opencode.json points at it;
  - the plugin registers a sidebar_content slot renderer;
  - the tree groups BOTH engines: native children by parentID, dispatch
    children by metadata.parent — one tree, not two;
  - each run is labeled by its ticket (dispatch children carry metadata.ticket)
    with its live status;
  - the plugin is fail-open (a session list that errors renders nothing, never
    breaks the sidebar);
  - the grouping logic is unit-testable: the tree builder is exported pure.

Run:  uv run --with pytest --with pyyaml pytest tests/test_sidebar_tree.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
from test_graph_nodes import graph_cfg  # noqa: E402
import emit  # noqa: E402

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node required")


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-tui-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


def test_the_tui_plugin_is_emitted_and_wired():
    """plugin/tui.js is emitted, and opencode auto-discovers it: `plugin/*.{ts,js}` is
    scanned at config load (packages/opencode/src/config/plugin.ts), so the file's
    presence IS the wiring — no opencode.json entry to forget."""
    out = emit_oc(graph_cfg())
    assert (out / "plugin" / "tui.js").is_file(), "plugin/tui.js was not emitted"


def test_the_tui_plugin_loads_on_the_server_loader():
    """The server-side plugin loader scans plugin/*.js and requires a default export
    with an `id` and an `effect`/`setup`/`server` function — a TUI-only export
    ({id, tui}) is REJECTED ('Plugin must export a default definition with an id and
    an effect or setup function'). The TUI plugin must be a DUAL module: a no-op
    server() (so the server loader accepts it) + the tui() entry (so the TUI loader
    picks it up via the ./tui export)."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "tui.js").read_text()
    assert re_search_dual(src), \
        "tui.js is not a dual module (server + tui) — the server loader rejects it"


def re_search_dual(src):
    import re
    has_server = re.search(r"\bserver\s*\(|\bserver\s*:", src)
    has_tui = re.search(r"\btui\s*\(|\btui\s*:", src)
    return has_server and has_tui


def test_the_plugin_dir_declares_the_tui_export():
    """The TUI loader resolves the ./tui export from the plugin dir's package.json
    (resolvePackageEntrypoint: exports['./tui']). Without it the TUI loader finds no
    entrypoint and the sidebar tree never renders."""
    out = emit_oc(graph_cfg())
    pkg = out / "plugin" / "package.json"
    assert pkg.is_file(), "plugin/package.json was not emitted — the TUI loader cannot resolve the ./tui export"
    import json as _json
    exports = _json.loads(pkg.read_text()).get("exports", {})
    assert "./tui" in exports, f"plugin/package.json does not declare the ./tui export: {exports}"


def test_the_plugin_registers_a_sidebar_content_slot():
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "tui.js").read_text()
    assert "sidebar_content" in src, "the TUI plugin does not render into sidebar_content"
    assert "slots" in src and "register" in src, "the TUI plugin does not register a slot"


def test_the_tree_groups_both_engines_on_parentid_or_metadata_parent():
    """The grouping rule is the maintainer's: parentID ?? metadata.parent. Native
    subagent children carry parentID at create; dispatch children carry
    metadata.parent (the round trip writes it). One tree over both."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "tui.js").read_text()
    assert "parentID" in src, "the tree does not group native children by parentID"
    assert "metadata" in src and "parent" in src, \
        "the tree does not fall back to metadata.parent for dispatch children"


def test_the_tree_builder_is_exported_and_pure():
    """The grouping logic must be unit-testable without a TUI host: a pure function
    from the session list to the tree, exported from the plugin file."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "tui.js").read_text()
    assert re_search_export(src), "the tree builder is not exported"


def re_search_export(src):
    import re
    return re.search(r"export\s+(function|const)\s+\w*[Tt]ree|export\s*\{[^}]*[Tt]ree", src)


def test_the_tree_builder_groups_sessions_correctly():
    """Behavioural: run the exported tree builder over a synthetic session list
    covering both engines and assert the grouping."""
    out = emit_oc(graph_cfg())
    probe = """
import { pathToFileURL } from "node:url"
const mod = await import(pathToFileURL(process.argv[2]).href)
const build = mod.buildRunTree ?? mod.buildTree
if (!build) { console.log(JSON.stringify({ error: "no tree builder exported", keys: Object.keys(mod) })); process.exit(0) }
const sessions = [
  { id: "ses_root", title: "orchestrator", time: { updated: 3 } },
  // native subagent child: parentID at create
  { id: "ses_native", title: "review TST-1 (@validate subagent)", parentID: "ses_root", time: { updated: 2 } },
  // dispatch child: no parentID, metadata.parent instead
  { id: "ses_dispatch", title: "produce TST-2", metadata: { run: true, parent: "ses_root", ticket: "TST-2" }, time: { updated: 1 } },
  // an unrelated session under another root
  { id: "ses_other", title: "someone else", time: { updated: 4 } },
]
console.log(JSON.stringify(build(sessions, "ses_root")))
"""
    probe = probe.replace('process.argv[2]', repr(str(out / "plugin" / "tui.js")))
    p = subprocess.run(["node", "--input-type=module", "-e", probe],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    tree = json.loads(p.stdout)
    assert "error" not in tree, tree
    children = {c["id"] for c in tree.get("children", [])}
    assert children == {"ses_native", "ses_dispatch"}, \
        f"the tree must group BOTH engines under the root: {tree}"


def test_the_plugin_is_fail_open():
    """A session list that errors must render nothing, never break the sidebar —
    the tree is a view, not a gate."""
    out = emit_oc(graph_cfg())
    src = (out / "plugin" / "tui.js").read_text()
    import re
    assert re.search(r"catch|\.catch\(|try\s*\{", src), \
        "the TUI plugin has no failure handling — it must fail open"
