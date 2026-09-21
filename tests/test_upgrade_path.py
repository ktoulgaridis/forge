#!/usr/bin/env python3
"""Acceptance tests for the safe upgrade path (forge#28 follow-up).

The emitted package is distributed via a brew tap: an org upgrades by re-running
the generator over its existing `.forge.org.yaml`. A config that emitted
yesterday must NOT hard-fail today with no path forward — the retired
`opencode.subagents` block must MIGRATE to the graph (`opencode.nodes`), with a
clear deprecation notice, so the upgrade is a re-emit, not a hand-edit.

The migration is mechanical and lossless:
  - each validating role (one with a `toolFilter.allow`) becomes a validate node:
    `fresh_context: true` (no-self-review was always the contract), the
    `read_surface` from the role's `toolFilter.allow`, the `max_steps` from the
    role's cap (or the default for that role), and the role's model as a node
    pin when the role pinned one;
  - the produce role (no `toolFilter`) needs no node — produce is the default
    writer kind, its cap comes from the role's `max_steps`;
  - a config that ALREADY declares `nodes` ignores `subagents` entirely (the
    graph wins; the cast block is dead config);
  - the migration WARNS — the org should delete the retired block.

Run:  uv run --with pytest --with pyyaml pytest tests/test_upgrade_path.py -q
"""
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import emit  # noqa: E402
from test_opencode_emit import CFG, cfg_with  # noqa: E402


def emit_oc(cfg):
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="emit-upgrade-")) / "out"
    emit.TARGETS["opencode"](cfg, out)
    return out


# A pre-#28 config: the retired subagents cast, no nodes graph.
LEGACY_SUBAGENTS = {
    "implementer": {"agent": "implementer", "persona": "Ships the smallest honest change."},
    "reviewer": {"agent": "reviewer",
                 "toolFilter": {"allow": ["read", "grep", "glob"]},
                 "persona": "Judges the diff, never the author."},
    "clearance": {"agent": "clearance",
                  "toolFilter": {"allow": ["read", "grep", "glob"]},
                  "persona": "A pass/fail verdict plus specific deficiencies."},
}


def legacy_cfg(**subagents):
    """A config with the retired cast block and NO nodes graph."""
    c = cfg_with(lambda c: c.get("opencode", {}).pop("nodes", None))
    c["opencode"]["subagents"] = {**LEGACY_SUBAGENTS, **subagents}
    return c


# --- the migration ------------------------------------------------------------------

def test_a_legacy_config_with_subagents_still_emits():
    """The upgrade path: a pre-#28 config re-emits without a hand-edit."""
    out = emit_oc(legacy_cfg())
    assert (out / "opencode.json").is_file()


def test_the_migration_produces_the_same_graph_as_a_native_config():
    """The migrated graph must be indistinguishable from a hand-written one: the
    validating agent's deny set, the steps cap, the model — all identical."""
    import json
    import yaml
    legacy = emit_oc(legacy_cfg())
    native = emit_oc(cfg_with())  # CFG carries the nodes graph natively
    l_conf = json.loads((legacy / "opencode.json").read_text())
    n_conf = json.loads((native / "opencode.json").read_text())
    assert l_conf["permission"] == n_conf["permission"], \
        "the migrated config's permission block differs from the native graph's"
    l_agent = yaml.safe_load((legacy / "agent" / "validate.md").read_text().split("---", 2)[1])
    n_agent = yaml.safe_load((native / "agent" / "validate.md").read_text().split("---", 2)[1])
    assert l_agent["permission"] == n_agent["permission"], \
        "the migrated validating agent's deny set differs from the native graph's"
    assert l_agent["steps"] == n_agent["steps"], \
        "the migrated validating agent's step cap differs from the native graph's"
    assert l_agent["model"] == n_agent["model"], \
        "the migrated validating agent's model differs from the native graph's"


def test_the_migration_warns_that_subagents_is_retired():
    """The org should delete the retired block — the migration says so, on stderr."""
    buf = io.StringIO()
    with redirect_stderr(buf):
        emit_oc(legacy_cfg())
    out = buf.getvalue().lower()
    assert "subagents" in out and ("retired" in out or "deprecat" in out or "migrat" in out), \
        f"no deprecation notice for the retired subagents block: {buf.getvalue()!r}"


def test_a_config_with_both_nodes_and_subagents_uses_the_graph():
    """The graph wins: a config that already declares `nodes` ignores the retired
    `subagents` block entirely (it is dead config, not a conflict)."""
    c = cfg_with()  # carries nodes natively
    c["opencode"]["subagents"] = LEGACY_SUBAGENTS
    out = emit_oc(c)
    assert (out / "opencode.json").is_file()


def test_a_legacy_role_with_a_model_pin_migrates_the_pin():
    """A role that pinned a model carries the pin to its node — resolved through the
    org's model map (a shorthand like "sonnet" becomes the full provider/model ref)."""
    import yaml
    c = legacy_cfg()
    c["agents"] = [
        {"name": "implementer", "model": "sonnet"},
        {"name": "reviewer", "model": "sonnet"},   # the reviewer pinned sonnet
        {"name": "gate", "model": "sonnet"},
    ]
    out = emit_oc(c)
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    # the validating agent's model is the validating pin, resolved to the full ref
    assert fm["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm


def test_a_legacy_role_with_an_unmappable_model_pin_drops_it_to_the_org_floor():
    """A shorthand with no mapping in opencode.model (e.g. "opus" when the org floor
    is sonnet) cannot become a full ref — the migration drops the pin (the org floor
    applies) rather than emit an off-provider or invented ref."""
    import yaml
    c = legacy_cfg()
    c["agents"] = [
        {"name": "implementer", "model": "sonnet"},
        {"name": "reviewer", "model": "opus"},   # no opus mapping in this config
        {"name": "gate", "model": "sonnet"},
    ]
    out = emit_oc(c)
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    # the unmappable pin is dropped; the mappable one (gate's sonnet) wins
    assert fm["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0", fm


def test_a_legacy_role_with_no_toolfilter_is_a_produce_node_not_a_validate_node():
    """The implementer (no toolFilter) must NOT become a validating node — it is the
    produce kind. The migrated graph's validating nodes are exactly the roles that
    carried a toolFilter."""
    import yaml
    out = emit_oc(legacy_cfg())
    fm = yaml.safe_load((out / "agent" / "validate.md").read_text().split("---", 2)[1])
    # the validating deny set derives from the union of the VALIDATING nodes' read
    # surfaces — if the implementer had been migrated as a validate node, the deny
    # set would be empty (its surface is full tools)
    assert fm["permission"].get("edit") == "deny", \
        f"the implementer leaked into the validating nodes: {fm['permission']}"
