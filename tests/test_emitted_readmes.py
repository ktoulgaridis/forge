#!/usr/bin/env python3
"""The emitted READMEs describe the package they ship in (the 0.9 graph catalog).

  - opencode: when the org declares a Homebrew distribution (`opencode.distribution.
    homebrew`), Install leads with the brew path (tap -> trust -> install -> the
    installer's `install` -> restart -> `doctor`) and Upgrading is `brew upgrade` + the
    installer's `update`; the tap/formula/CLI names come from the config, never the
    template. The manual copy is secondary. With no distribution declared, the README
    stays generic (no brew commands).
  - Neither README describes the retired single `graph:` block or "one build agent".
  - The Layout block lists exactly what the emit wrote: agents, rubrics and verbs
    (commands on opencode, skills on Claude Code) — the triage verb, the `triager` worker
    and every rubric included.

Run:  uv run --with pytest --with pyyaml pytest tests/test_emitted_readmes.py -q
"""
import re
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402

EXAMPLE = ROOT / "examples" / "graph-catalog.forge.org.yaml"
BREW = {"tap": "fictco/tools", "formula": "fictco-harness-opencode"}


def load(brew=None):
    cfg = yaml.safe_load(EXAMPLE.read_text())
    cfg["org"] = {"name": "Fictco", "slug": "fictco"}
    cfg["plugin"].update({"name": "fictco-harness",
                          "author": {"name": "Fictco Eng", "url": "https://github.com/fictco"},
                          "homepage": "https://github.com/fictco/fictco-harness"})
    cfg["opencode"].pop("distribution", None)
    if brew is not None:
        cfg["opencode"]["distribution"] = {"homebrew": dict(brew)}
    return cfg


def emit_to(target, cfg):
    out = Path(tempfile.mkdtemp(prefix=f"emit-readme-{target}-")) / "out"
    emit.TARGETS[target](cfg, out)
    return out


def layout_entries(readme: str, dirname: str) -> list[str]:
    """The ` · `-separated names on the Layout block's `<dirname>/` line."""
    block = readme.split("## Layout", 1)[-1] if "## Layout" in readme else readme
    m = re.search(rf"^{re.escape(dirname)}/\s+(.+?)(?:\s+—\s|\s+\(|$)", block, re.M)
    assert m, f"no `{dirname}/` line in the Layout block:\n{block[:1500]}"
    return [n.strip().strip("`") for n in m.group(1).split("·")]


def stems(d: Path) -> set[str]:
    return {p.stem for p in d.glob("*.md")}


# --- opencode: install + upgrade ---------------------------------------------------

def test_opencode_readme_leads_with_the_brew_install_path():
    readme = (emit_to("opencode", load(BREW)) / "README.md").read_text()
    steps = ["brew tap fictco/tools", "brew trust fictco/tools",
             "brew install fictco-harness-opencode", "fictco-harness-opencode install",
             "restart opencode", "fictco-harness-opencode doctor"]
    at = [readme.find(s) for s in steps]
    assert all(i >= 0 for i in at), dict(zip(steps, at))
    assert at == sorted(at), f"brew install steps out of order: {dict(zip(steps, at))}"
    # the manual copy survives only as the secondary option
    if "cp -R" in readme:
        assert readme.find("cp -R") > at[-1], "manual copy precedes the brew install path"


def test_opencode_readme_upgrade_is_brew_upgrade_then_update():
    readme = (emit_to("opencode", load(BREW)) / "README.md").read_text()
    up = readme.split("## Upgrading", 1)[1].split("\n## ", 1)[0]
    i, j = up.find("brew upgrade fictco-harness-opencode"), up.find("fictco-harness-opencode update")
    assert 0 <= i < j, up
    assert "graphs:" in up, "Upgrading does not describe the graphs: catalog"


def test_brew_cli_defaults_to_the_formula_and_can_be_named():
    readme = (emit_to("opencode", load({**BREW, "cli": "fh"})) / "README.md").read_text()
    assert "brew install fictco-harness-opencode" in readme and "fh install" in readme
    assert "fh doctor" in readme and "fictco-harness-opencode install" not in readme


def test_no_distribution_keeps_the_readme_generic():
    readme = (emit_to("opencode", load()) / "README.md").read_text()
    assert "brew " not in readme, "brew commands rendered with no distribution declared"
    assert "cp -R" in readme, "the generic README lost its manual install"


@pytest.mark.parametrize("bad", [{"tap": "fictco/tools"}, {"formula": "x"},
                                 {**BREW, "tap": ""}, {**BREW, "channel": "beta"}])
def test_a_malformed_homebrew_block_does_not_emit(bad):
    with pytest.raises(SystemExit):
        emit_to("opencode", load(bad))


@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_readme_never_describes_the_retired_single_graph_block(target):
    readme = (emit_to(target, load(BREW)) / "README.md").read_text()
    assert "graph:" not in readme, "README describes the retired single `graph:` block"
    assert "`cp -R ./`" not in readme
    assert "one build agent" not in readme


# --- the Layout block is what the emit wrote -----------------------------------------

def test_opencode_layout_lists_what_was_emitted():
    out = emit_to("opencode", load(BREW))
    readme = (out / "README.md").read_text()
    assert set(layout_entries(readme, "agent")) == stems(out / "agent")
    assert set(layout_entries(readme, "rubric")) == stems(out / "rubric")
    assert set(layout_entries(readme, "command")) == stems(out / "command")
    assert {"triager", "builder"} <= stems(out / "agent")
    assert {"triage"} <= stems(out / "command")
    assert {"agent-ready", "diagnosis"} <= stems(out / "rubric")


def test_claude_code_layout_lists_what_was_emitted():
    cfg = load()
    out = emit_to("claude-code", cfg)
    readme = (out / "README.md").read_text()
    assert set(layout_entries(readme, "agents")) == stems(out / "agents")
    assert set(layout_entries(readme, "rubrics")) == stems(out / "rubrics")
    workers = [g for g, v in cfg["graphs"].items() if v["launch"] == "worker"]
    verbs = {d.name for d in (out / "skills").iterdir()
             if not any(d.name.startswith(f"{w}-") for w in workers)}
    assert set(layout_entries(readme, "skills")) == verbs
    assert "triage" in verbs and "triager" in stems(out / "agents")


LAYOUT_ROWS = {
    "claude-code": [".claude-plugin/plugin.json", "skills/", "agents/", "skills/<graph>-*",
                    "nodes/", "rubrics/", "hooks/", "README.md"],
    "opencode": ["opencode.json", "AGENTS.md", "agent/", "rubric/", "node/", "command/",
                 "skill/", "plugin/"],
}


@pytest.mark.parametrize("supp", [True, False])
@pytest.mark.parametrize("target", ["claude-code", "opencode"])
def test_layout_block_keeps_one_row_per_path(target, supp):
    """A conditional closing at a line end eats the newline — two rows would merge."""
    cfg = load(BREW)
    cfg["supplementary_reviewer"]["enabled"] = supp
    readme = (emit_to(target, cfg) / "README.md").read_text()
    block = readme.split("## Layout", 1)[1].split("```", 2)[1]
    rows = [ln.split()[0] for ln in block.strip("\n").splitlines()]
    assert rows == LAYOUT_ROWS[target], block
