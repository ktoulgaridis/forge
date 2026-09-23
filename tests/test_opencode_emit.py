#!/usr/bin/env python3
"""`emit --target opencode` — the second emit target.

One org config, N hosts. These tests hold the multi-target abstraction honest:

  1. The opencode.json we emit is real, parseable, and Bedrock-ONLY.
  2. THE load-bearing control: the optional supplementary reviewer (agent/validate.md,
     when enabled) is read-only by `permission: <cap>: deny` — including `task`/`dispatch`,
     without which a "read-only" reviewer could spawn an unrestricted writer and launder
     writes. Mutating the config to weaken that control must FAIL the emit, not emit a
     fail-open harness. (Detail in tests/test_validate_native.py + test_graph_nodes.py.)
  3. The skill BODIES are shared with the Claude Code target byte-for-byte, except at the
     {{#TARGET_*}} conditionals and the host-noun scalars.
  4. The Claude Code target still renders the single-locus build graph-agent shape
     (ADR 0018 regression guard).

Run:  uv run --with pyyaml python tests/test_opencode_emit.py
  or: uv run --with pytest --with pyyaml pytest tests/test_opencode_emit.py -q
"""
import copy
import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402
from render import LEAK_RE  # noqa: E402  (the same gate emit runs)

VERBS = ["intro", "setup", "prime", "inception", "refine", "execute", "wiki", "handoff"]

ORG_FLOOR = "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# The graph catalog (ADR 0019): each named graph is a worker agent or a main-thread walk.
# The build graph's worker is `builder` — one persistent context that traverses the
# nodes; review is a rubric node of that one agent; the OPTIONAL supplementary reviewer
# (top level) is the only fresh-context validator.
GRAPHS = {
    "build": {
        "agent": "builder",
        "verb": "execute",
        "launch": "worker",
        "isolation": "worktree",
        "tools": "write",
        "model": "sonnet",
        "effort": "high",
        "max_total_steps": 400,
        "entry": "understand",
        "nodes": {
            "understand": {"skill": "build-understand", "next": "build"},
            "build": {"skill": "build-implement", "next": "validate"},
            "validate": {"skill": "build-validate", "next": "review"},
            "review": {"rubric": "review", "max_visits": 4, "next": ["clear", "fix"]},
            "fix": {"skill": "build-fix", "next": "validate"},
            "clear": {"rubric": "gate", "terminal": "pr_open"},
        },
    },
}

SUPP = {
    "enabled": True,
    "fresh_context": True,
    "read_surface": ["read", "grep", "glob"],
    "model": ORG_FLOOR,
    "max_steps": 40,
}

CFG = {
    "org": {"name": "Testco", "slug": "testco"},
    "plugin": {
        "name": "testco-harness", "version": "0.1.0", "description": "d",
        "author": {"name": "Testco Platform Engineering", "url": "https://github.com/testco"},
        "homepage": "https://github.com/testco/testco-harness", "license": "UNLICENSED",
    },
    "org_wiki": {
        "name": "testco-wiki", "remote": "git@github.com:testco/testco-wiki.git",
        "local_path_env": "TESTCO_WIKI", "default_local_path": "~/work/testco-wiki",
        "prime_reads": ["operating-model.md", "CLAUDE.md"],
    },
    "tracker": {"type": "jira-acli", "config": {
        "project_key": "TST", "base_url": "https://testco.atlassian.net",
    }},
    "model_policy": {"banned": ["haiku"], "default": "sonnet", "rule": "Set model explicitly."},
    "graphs": GRAPHS,
    "supplementary_reviewer": SUPP,
    "opencode": {
        "provider": {"id": "amazon-bedrock"},
        "model": {"provider": "amazon-bedrock",
                  "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
        "primary_agent": "build",
        "disabled_providers": ["opencode"],
        "skills": list(VERBS),
    },
}


def cfg_with(mutate=None):
    c = copy.deepcopy(CFG)
    if mutate:
        mutate(c)
    return c


def emit_target(target, cfg=None):
    out = Path(tempfile.mkdtemp(prefix=f"emit-{target}-test-")) / "out"
    emit.TARGETS[target](cfg or CFG, out)
    return out


# --- opencode.json ---------------------------------------------------------------

def test_opencode_json_allowlists_exactly_the_configured_provider():
    out = emit_target("opencode")
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["$schema"] == "https://opencode.ai/config.json", conf.get("$schema")
    # the ALLOWLIST is the load-bearing control (a deny-list does not cover a provider
    # auto-detected from an ambient ANTHROPIC_API_KEY / OPENAI_API_KEY)
    assert conf["enabled_providers"] == ["amazon-bedrock"], conf.get("enabled_providers")
    assert "opencode" in conf["disabled_providers"], conf["disabled_providers"]
    assert conf["model"] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    # no provider options, no credentials: auth is opencode's (`opencode auth login`)
    assert "provider" not in conf, conf.get("provider")
    # external-dir reads allowed (the harness reads the wiki, which lives outside cwd)
    assert conf["permission"]["external_directory"] == "allow", conf.get("permission")
    for bad in ("agents", "commands", "permissions", "plugins"):
        assert bad not in conf, f"emitted rejected plural top-level key {bad!r}"


def test_provider_takes_only_an_id():
    """Provider options (region, profile, keys) are opencode's business, not the org's."""
    try:
        emit_target("opencode", cfg_with(
            lambda c: c["opencode"]["provider"].__setitem__("region", "us-east-1")))
    except SystemExit as e:
        assert "only `id`" in str(e), e
        return
    raise AssertionError("emitted with provider options in the org config")


# --- leak gate: generator identity out, the org's own identity in -------------------

def test_leak_gate_allows_the_orgs_own_identity_but_not_the_generators():
    """A template that hardcodes the generator trips the gate; the same token coming
    from the org's own config (its name, its repo) does not."""
    tpl = Path(tempfile.mkdtemp()) / "tpl"
    tpl.mkdir()
    (tpl / "x.md.template").write_text("tracker repo: {{REPO}}\n")
    from render import render_tree
    b = {"scalars": {"REPO": "ktoulgaridis/forge"}}
    try:
        render_tree(b, tpl, tpl.parent / "out1", ROOT, leak_check=True)
    except SystemExit as e:
        assert e.code == 3
    else:
        raise AssertionError("gate did not trip on the generator's identity")
    render_tree(b, tpl, tpl.parent / "out2", ROOT, leak_check=True,
                leak_allow={"ktoulgaridis/forge"})  # the org spelled it → not a leak
    # the allowance is for the org's STRING on that line, not for the token everywhere:
    # a template hardcoding the generator still trips when the config merely mentions it
    (tpl / "y.md.template").write_text("made with forge\n")
    try:
        render_tree(b, tpl, tpl.parent / "out3", ROOT, leak_check=True,
                    leak_allow={"ktoulgaridis/forge", "forge ahead"})
    except SystemExit as e:
        assert e.code == 3
    else:
        raise AssertionError("a hardcoded generator token slipped through the allowance")
    (tpl / "y.md.template").unlink()

    # end to end: the maintainer's own org emits
    def m(c):
        c["org"]["name"] = "ktoulgaridis"
        c["tracker"] = {"type": "github", "config": {"repo": "ktoulgaridis/forge"}}
    out = emit_target("opencode", cfg_with(m))
    assert "ktoulgaridis/forge" in (out / "skill" / "prime" / "SKILL.md").read_text()


# --- THE read-only control -------------------------------------------------------

def frontmatter(txt):
    import yaml
    return yaml.safe_load(txt.split("---", 2)[1])


def assert_read_only(txt, who, extra_denied=("webfetch", "websearch")):
    """Read-only = cannot write, delegate or reach out; bash is an ALLOWLIST of the
    adapter's read-only tracker/SCM commands under a `*: deny`, never a blanket deny —
    a validating role that cannot read its ticket wanders instead of judging."""
    perm = frontmatter(txt)["permission"]
    for cap in ("edit", "task", "dispatch", *extra_denied):
        assert perm.get(cap) == "deny", f"{who} does not deny {cap}: {perm}"
    bash = perm["bash"]
    assert isinstance(bash, dict) and bash.get("*") == "deny", f"{who} bash is not an allowlist: {bash}"
    keys = list(bash)
    allowed = [p for p, a in bash.items() if a == "allow"]
    assert allowed, f"{who} allows no read-only commands — it cannot read the ticket"
    # opencode matches the WHOLE command text (redirections included) and the LAST
    # matching rule wins: an allowed read followed by `> file` or `--output file` would
    # write. So the trailing rules deny those shapes, and they must come after the allows.
    for tail in ("*>*", "*--output*"):
        assert bash.get(tail) == "deny", f"{who} lacks the {tail!r} deny: {bash}"
        assert keys.index(tail) > max(keys.index(p) for p in allowed), \
            f"{who}: {tail!r} deny must follow the allows (last match wins)"
    assert not any(p.startswith("gh api") for p in allowed), \
        f"{who} allows `gh api` — -X POST/PUT/DELETE is a full write path"
    return bash


def test_mutation_credential_in_provider_fails_closed():
    def m(c):
        c["opencode"]["provider"]["profile"] = "AKIAIOSFODNN7EXAMPLE"
    try:
        emit_target("opencode", cfg_with(m))
    except SystemExit:
        return
    raise AssertionError("credential-looking provider value emitted instead of failing")


def test_enabled_providers_tracks_the_configured_provider_id():
    def m(c):
        c["opencode"]["provider"]["id"] = "bedrock-alt"
        c["opencode"]["model"]["provider"] = "bedrock-alt"
        # the supplementary reviewer's pin must be on the same provider (it is validated
        # on-provider at emit) — track the mutated provider so the emit is coherent
        c["supplementary_reviewer"]["model"] = \
            "bedrock-alt/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    conf = json.loads((emit_target("opencode", cfg_with(m)) / "opencode.json").read_text())
    assert conf["enabled_providers"] == ["bedrock-alt"], conf["enabled_providers"]


def test_mutation_enabled_providers_dropped_from_template_fails_closed():
    """Delete the allowlist from the emitted config and emit must refuse — otherwise the
    only-Bedrock claim is theater that no test would notice."""
    tpl = ROOT / "templates/opencode/opencode.json.template"
    original = tpl.read_text()
    stripped = "\n".join(l for l in original.splitlines()
                         if "enabled_providers" not in l) + "\n"
    assert stripped != original, "template no longer carries enabled_providers"
    try:
        tpl.write_text(stripped)
        try:
            emit_target("opencode")
        except SystemExit:
            return
        raise AssertionError("emitted a config with no enabled_providers allowlist")
    finally:
        tpl.write_text(original)


def test_mutation_zen_provider_left_enabled_fails_closed():
    def m(c):
        c["opencode"]["disabled_providers"] = []
    try:
        emit_target("opencode", cfg_with(m))
    except SystemExit:
        return
    raise AssertionError("emitted a config that does not hide the built-in provider")


# --- shared skill bodies ---------------------------------------------------------

def _normalize(text: str) -> str:
    """Strip the places a shared skill is ALLOWED to differ per target: the host-noun
    scalars, and the target-conditional sections (execute steps 4–5, refine step 7).
    Everything else must match byte-for-byte."""
    for host in ("a Claude Code plugin", "an opencode configuration"):
        text = text.replace(host, "<HOST>")
    for dispatch in ("Workflow stages", "the task tool"):
        text = text.replace(dispatch, "<DISPATCH>")
    # execute's step 3a (the native-todo walk), step 4 (the execution-ready gate) and
    # step 5 (the dispatch section) are per-target, bounded by the next shared line
    # (the trailing blank line goes with the stripped section, so the two targets
    # rejoin byte-identically)
    text = re.sub(r"^### 3a\..*?(?=^### 4\.)", "", text, flags=re.S | re.M)
    text = re.sub(r"^### 4\..*?(?=^\*\*Context economy)", "", text, flags=re.S | re.M)
    # refine's step 7 (the agent-ready gate) is per-target, bounded by the next heading
    text = re.sub(r"^### 7\..*?(?=^### 8\.)", "", text, flags=re.S | re.M)
    # a stripped section can leave a doubled blank line behind on one target
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def test_shared_skill_bodies_are_identical_across_targets():
    oc, cc = emit_target("opencode"), emit_target("claude-code")
    for verb in VERBS:
        o = oc / "skill" / verb / "SKILL.md"
        c = cc / "skills" / verb / "SKILL.md"
        assert o.is_file(), f"missing emitted skill/{verb}/SKILL.md"
        assert c.is_file(), f"missing emitted skills/{verb}/SKILL.md"
        no, nc = _normalize(o.read_text()), _normalize(c.read_text())
        assert no == nc, f"shared body for {verb} diverged between targets"


def test_execute_dispatch_is_target_specific():
    oc = (emit_target("opencode") / "skill" / "execute" / "SKILL.md").read_text()
    cc = (emit_target("claude-code") / "skills" / "execute" / "SKILL.md").read_text()

    # opencode: one build graph-agent per task via dispatch (root-session worker); the
    # in-loop review is a SELF-CHECK, not a dispatched validator (ADR 0018).
    assert "`dispatch`" in oc, "opencode execute does not dispatch via the dispatch tool"
    assert "dispatch({ agent:" in oc, "opencode execute does not launch a build graph-agent"
    assert "task_id" in oc, "opencode execute does not explain the feedback loop (task_id)"
    assert "worktree" in oc, "opencode execute does not state per-worker worktrees"
    assert "isolation: 'worktree'" not in oc, "CC worktree syntax leaked into opencode execute"
    assert "pipeline(tasks" not in oc and "agentType" not in oc, \
        "a retired Workflow pipeline() call leaked into opencode execute (ADR 0018)"

    # claude-code: one build graph-agent per task via the native Agent tool, isolation
    # worktree — single-locus, NO Workflow pipeline() driver, NO in-loop validate subagent.
    assert "isolation: 'worktree'" in cc, "claude-code execute lost the worktree guidance"
    assert "pipeline(tasks" not in cc and "agentType" not in cc, \
        "claude-code execute still drives a retired Workflow pipeline (ADR 0018)"
    assert "graph-agent" in cc, "claude-code execute does not launch a build graph-agent"
    assert "subagent_type" not in cc, "opencode native-subagent text leaked into the CC execute"

    # single-locus on BOTH: the review node is a self-check of the one agent
    for txt, host in ((oc, "opencode"), (cc, "claude-code")):
        assert "self-check" in txt, f"{host} execute does not frame review as a self-check node"


def test_intro_names_its_host():
    oc = (emit_target("opencode") / "skill" / "intro" / "SKILL.md").read_text()
    cc = (emit_target("claude-code") / "skills" / "intro" / "SKILL.md").read_text()
    assert "an opencode configuration" in oc, "opencode intro does not name its host"
    assert "Claude Code plugin" not in oc, "CC host noun leaked into the opencode intro"
    assert "Claude Code plugin" in cc, "claude-code intro lost its host noun"


# --- hygiene ---------------------------------------------------------------------

def test_opencode_version_parsing():
    assert emit.parse_opencode_version("opencode v2.0.8") == (2, 0, 8)
    assert emit.parse_opencode_version("opencode 1.18.29") == (1, 18, 29)
    assert emit.parse_opencode_version("opencode v2.0.8-beta.1\n") == (2, 0, 8)
    assert emit.parse_opencode_version("not a version") is None
    assert emit.parse_opencode_version("") is None


def test_opencode_floor_fails_old_hosts():
    """The dual entrypoint needs 1.18.29+; check_opencode_host fails closed below it."""
    with patch.object(emit, "opencode_host_version", return_value=(1, 18, 28)):
        with pytest.raises(SystemExit, match="1.18.29"):
            emit.check_opencode_host()


def test_opencode_floor_accepts_both_hosts():
    for v, half in (((1, 18, 29), "server() (1.18.29+)"),
                    ((2, 0, 8), "setup() (2.x)")):
        buf = io.StringIO()
        with patch.object(emit, "opencode_host_version", return_value=v):
            with redirect_stdout(buf):
                emit.check_opencode_host()  # must not raise
        assert half in buf.getvalue()


def test_no_unresolved_placeholders_and_leak_clean():
    out = emit_target("opencode")
    files = [p for p in out.rglob("*") if p.is_file()]
    assert files, "opencode target emitted nothing"
    for p in files:
        txt = p.read_text()
        assert "{{" not in txt, f"unresolved placeholder in {p.relative_to(out)}"
        hit = LEAK_RE.search(txt)
        assert not hit, f"identity leak ({hit.group(0)!r}) in {p.relative_to(out)}"


def test_exactly_one_target_true_per_target():
    for target, builder in (("claude-code", emit.build_bindings),
                            ("opencode", emit.build_bindings_opencode)):
        conds = builder(CFG)["conditionals"]
        targets = {k: v for k, v in conds.items() if k.startswith("TARGET_")}
        assert set(targets) == {"TARGET_CC", "TARGET_OPENCODE"}, conds
        assert sum(1 for v in targets.values() if v) == 1, f"{target}: {conds}"
    assert emit.build_bindings(CFG)["conditionals"]["TARGET_CC"] is True
    assert emit.build_bindings_opencode(CFG)["conditionals"]["TARGET_OPENCODE"] is True


def test_opencode_layout():
    out = emit_target("opencode")
    for rel in ["opencode.json", "AGENTS.md", "README.md", "plugin/reminders.js",
                "plugin/dispatch.js"]:
        assert (out / rel).is_file(), f"missing {rel}"
    for verb in VERBS:
        assert (out / "command" / f"{verb}.md").is_file(), f"missing command/{verb}.md"
    # a command runs as the primary agent; execute must NOT be forced into a subagent
    ex = (out / "command" / "execute.md").read_text()
    assert "agent: build" in ex, ex.splitlines()[:6]
    assert "subtask" not in ex, "execute command forces a subtask; the orchestrator is long-lived"
    # gate is an agent, never a verb/skill on this host
    assert not (out / "skill" / "gate").exists(), "gate emitted as a skill"


# --- claude-code regression ------------------------------------------------------

def test_claude_code_target_still_renders():
    out = emit_target("claude-code")
    for rel in ["README.md", ".claude-plugin/plugin.json", "agents/builder.md",
                "rubrics/review.md", "rubrics/gate.md", "skills/execute/SKILL.md"]:
        assert (out / rel).is_file(), f"CC regression: missing {rel}"
    # the retired role cast is gone (ADR 0018)
    for gone in ("agents/implementer.md", "agents/reviewer.md", "agents/gate.md"):
        assert not (out / gone).exists(), f"CC still emits the retired {gone}"
    ex = (out / "skills" / "execute" / "SKILL.md").read_text()
    assert "pipeline(tasks" not in ex and "agentType" not in ex, \
        "CC execute still drives a retired Workflow pipeline (ADR 0018)"
    assert "graph-agent" in ex and "isolation: 'worktree'" in ex, \
        "CC execute lost the single-locus build-graph-agent dispatch"
    intro = (out / "skills" / "intro" / "SKILL.md").read_text()
    assert "agent harness** — a Claude Code plugin that helps" in intro, "CC host noun changed"
    assert "graph-agent" in intro and "single context" in intro, \
        "CC intro lost the single-locus node note"
    assert not (out / "command").exists(), "CC target emitted an opencode command dir"
    # the build graph's worker is `builder` (ADR 0019): its own agent file
    build = (out / "agents" / "builder.md").read_text()
    assert "self-check" in build, "builder.md does not frame review as a self-check node"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
