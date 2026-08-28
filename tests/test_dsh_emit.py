#!/usr/bin/env python3
"""Anti-regression net for the DSH (DeepSeek Harness) emit target.

`/forge:emit --target dsh` renders a DeepSeek Harness profile bundle from the
SAME .forge.org.yaml as the Claude Code target — one source, two emits. This
test locks the two load-bearing invariants of that second target:

  1. LEAK GATE: the emitted bundle carries ZERO generator identity (render_tree
     raises SystemExit(3) otherwise) and no unresolved {{placeholders}} (exit 2).
  2. READ-ONLY CONTROL: the reviewer and clearance subagent rows each carry a
     non-empty toolFilter.allow (edit/write/bash absent by omission → refused);
     the implementer row carries NO filter (full tool set). This is the control
     the whole no-self-review split rests on, so removing it must FAIL loud.

It also asserts build_bindings_dsh reuses build_bindings (one source of org
bindings) and flips the host target (TARGET_CC off, TARGET_DSH on).

Run:  uv run --with pytest --with pyyaml pytest tests/test_dsh_emit.py -q
"""
import sys
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import emit  # noqa: E402
import render  # noqa: E402

FORGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = FORGE_ROOT / "adapters/tracker/_test/sample.forge.org.yaml"


def _cfg():
    return yaml.safe_load(FIXTURE.read_text())


def test_dsh_bindings_reuse_org_bindings_and_flip_target():
    """build_bindings_dsh reuses build_bindings wholesale (one source) and flips
    the host conditionals so the DSH dispatch prose renders, not the CC prose."""
    cfg = _cfg()
    cc = emit.build_bindings(cfg)
    dsh = emit.build_bindings_dsh(cfg)
    # Every org scalar from the CC target survives unchanged in the DSH bindings.
    for k, v in cc["scalars"].items():
        assert dsh["scalars"][k] == v, f"DSH bindings dropped/changed org scalar {k}"
    # Host target flipped, plus the sigv4 auth conditionals (fixture default).
    assert cc["conditionals"] == {"TARGET_CC": True, "TARGET_DSH": False}
    assert dsh["conditionals"] == {
        "TARGET_CC": False, "TARGET_DSH": True,
        "DSH_AUTH_SIGV4": True, "DSH_AUTH_BEARER": False,
    }


def test_dsh_emit_is_leak_clean_and_fully_resolved(tmp_path):
    """emit_dsh renders with leak_check=True: reaching the asserts means no
    generator identity (exit 3) and no unresolved placeholder (exit 2) tripped."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)

    # The host shell + the folded shared skills are present.
    assert (out / "cordis.patch.yml").is_file()
    assert (out / "package.json").is_file()
    assert (out / "skills" / "execute" / "SKILL.md").is_file()  # fixture: no verb rename

    # Belt-and-suspenders leak scan over the whole emitted tree.
    for f in out.rglob("*"):
        if f.is_file():
            for i, line in enumerate(f.read_text().splitlines(), 1):
                assert not render.LEAK_RE.search(line), (
                    f"generator identity leaked into {f.relative_to(out)}:{i}: {line!r}"
                )


def test_dsh_reviewer_and_clearance_are_read_only_implementer_is_not(tmp_path):
    """LOAD-BEARING: in the rendered patch, reviewer + clearance carry a
    read-only toolFilter; the implementer carries none (full tools)."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)
    patch = (out / "cordis.patch.yml").read_text()

    assert "toolName: subagent_review" in patch
    assert "toolName: subagent_clearance" in patch
    assert "toolName: subagent_implement" in patch
    # Exactly two read-only filters (reviewer + clearance); the implementer row
    # must NOT introduce a third. Count is the guard against a mis-wired filter.
    assert patch.count("toolFilter:") == 2, (
        "expected exactly 2 toolFilter rows (reviewer + clearance); the "
        "implementer must have none"
    )
    assert "allow: [read, grep, glob]" in patch


def test_dsh_engage_skill_uses_direct_dispatch_not_workflow(tmp_path):
    """The DSH-target engage skill renders the direct-tool dispatch (TARGET_DSH)
    and drops the Claude Code Workflow/pipeline prose (TARGET_CC)."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)
    engage = (out / "skills" / "execute" / "SKILL.md").read_text()
    assert "subagent_implement" in engage and "subagent_review" in engage
    # The CC-only Workflow pipeline example must not survive into the DSH emit.
    assert "pipeline(tasks," not in engage


def test_dsh_empty_reviewer_allow_fails_loud():
    """MUTATION: emptying the reviewer's read-only allow-set must FAIL the emit
    (the read-only set is the load-bearing control, not a vacuous default)."""
    cfg = _cfg()
    cfg["dsh"]["subagents"]["reviewer"]["toolFilter"] = {"allow": []}
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_missing_section_fails_loud():
    """A config with no dsh: section cannot emit the DSH target."""
    cfg = _cfg()
    cfg.pop("dsh")
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_sigv4_mounts_llm_mantle_not_llm_pi_ai(tmp_path):
    """The fixture uses auth: sigv4, so the rendered patch mounts the standalone
    llm-mantle adapter (fixed routes signed from the ambient AWS chain) with only
    a region — no llm-pi-ai providers block, no apiKeyEnv, no minted token, and
    no route-level sigv4 block (the adapter owns signing)."""
    out = tmp_path / "bundle"
    emit.emit_dsh(_cfg(), out)
    patch = (out / "cordis.patch.yml").read_text()
    # A MOUNT, not a config-override. llm-mantle is NOT in dsh-base (base mounts
    # llm-pi-ai/llm-deepseek), so a bare top-level `- id: llm-mantle` override
    # finds no entry to patch and fails to compose ("entry not found"). It must
    # be inserted with its package name, which a config-override never carries.
    assert "name: '@deepseek-ai/dsh-llm-mantle'" in patch
    assert "- id: llm-mantle" in patch
    assert "region: us-east-1" in patch
    assert "- id: llm-pi-ai" not in patch
    assert "sigv4:" not in patch
    assert "apiKeyEnv:" not in patch
    assert "GW_TOKEN" not in patch and "MANTLE_TOKEN" not in patch


def test_dsh_bearer_mounts_llm_pi_ai_with_apikeyenv(tmp_path):
    """auth: bearer keeps the llm-pi-ai fallback path — each route carries its
    apiKeyEnv reference and no llm-mantle mount."""
    cfg = _cfg()
    cfg["dsh"]["auth"] = "bearer"
    for p in cfg["dsh"]["providers"]:
        p["apiKeyEnv"] = "GW_TOKEN"
    out = tmp_path / "bundle"
    emit.emit_dsh(cfg, out)
    patch = (out / "cordis.patch.yml").read_text()
    assert "- id: llm-pi-ai" in patch
    assert "apiKeyEnv: GW_TOKEN" in patch
    assert "- id: llm-mantle" not in patch
    assert "sigv4:" not in patch


def test_dsh_sigv4_requires_one_region(tmp_path):
    """MUTATION: sigv4 routes that disagree on region must fail the emit loud —
    llm-mantle mounts exactly one region for its fixed routes."""
    cfg = _cfg()
    cfg["dsh"]["auth"] = "sigv4"
    cfg["dsh"]["providers"][0]["region"] = "us-east-1"
    second = dict(cfg["dsh"]["providers"][0])
    second["route"] = "gw-gpt"
    second["region"] = "eu-west-2"
    cfg["dsh"]["providers"].append(second)
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_sigv4_requires_region():
    """MUTATION: a sigv4 route with no region must fail the emit loud."""
    cfg = _cfg()
    cfg["dsh"]["auth"] = "sigv4"
    for p in cfg["dsh"]["providers"]:
        p.pop("region", None)
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_bearer_requires_apikeyenv():
    """MUTATION: a bearer route with no apiKeyEnv must fail the emit loud."""
    cfg = _cfg()
    cfg["dsh"]["auth"] = "bearer"
    for p in cfg["dsh"]["providers"]:
        p.pop("apiKeyEnv", None)
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


def test_dsh_unknown_auth_fails_loud():
    """An auth mode other than sigv4/bearer is refused."""
    cfg = _cfg()
    cfg["dsh"]["auth"] = "oauth"
    with pytest.raises(SystemExit):
        emit.build_bindings_dsh(cfg)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
