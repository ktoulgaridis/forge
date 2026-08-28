#!/usr/bin/env python3
"""`emit --target opencode` — the second emit target.

One org config, N hosts. These tests hold the multi-target abstraction honest:

  1. The opencode.json we emit is real, parseable, and Bedrock-ONLY.
  2. THE load-bearing control: the two validating agents (reviewer + gate) are read-only
     by `permission: <cap>: deny` — including `task`, without which a "read-only"
     reviewer can spawn an unrestricted implementer and launder writes. The implementer
     carries NO deny at all. Mutating the config to weaken that control must FAIL the
     emit, not emit a fail-open harness.
  3. The skill BODIES are shared with the Claude Code target byte-for-byte, except at the
     {{#TARGET_*}} conditionals and the host-noun scalars.
  4. The Claude Code target still renders what it rendered before the shared-template
     edits (regression guard).

Run:  uv run --with pyyaml python tests/test_opencode_emit.py
  or: uv run --with pytest --with pyyaml pytest tests/test_opencode_emit.py -q
"""
import copy
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import emit  # noqa: E402
from render import LEAK_RE  # noqa: E402  (the same gate emit runs)

VERBS = ["intro", "setup", "prime", "inception", "refine", "execute", "wiki", "handoff"]

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
    "agents": [
        {"name": "implementer", "model": "sonnet"},
        {"name": "reviewer", "model": "sonnet"},
        {"name": "gate", "model": "sonnet"},
    ],
    "opencode": {
        "provider": {
            "id": "amazon-bedrock", "region": "us-east-1",
            "models": ["us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                       "us.openai.gpt-5-2025-08-07"],
        },
        "model": {"provider": "amazon-bedrock",
                  "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
        "primary_agent": "build",
        "disabled_providers": ["opencode"],
        "subagents": {
            "implementer": {"agent": "implementer", "persona": "Ships small honest changes."},
            "reviewer": {"agent": "reviewer", "toolFilter": {"allow": ["read", "grep", "glob"]},
                         "persona": "Judges the diff."},
            "clearance": {"agent": "gate", "toolFilter": {"allow": ["read", "grep", "glob"]},
                          "persona": "Verdict plus deficiencies."},
        },
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

def test_opencode_json_is_bedrock_only():
    out = emit_target("opencode")
    conf = json.loads((out / "opencode.json").read_text())
    assert conf["$schema"] == "https://opencode.ai/config.json", conf.get("$schema")
    # the ALLOWLIST is the load-bearing only-Bedrock control (a deny-list does not cover
    # a provider auto-detected from an ambient ANTHROPIC_API_KEY / OPENAI_API_KEY)
    assert conf["enabled_providers"] == ["amazon-bedrock"], conf.get("enabled_providers")
    assert "opencode" in conf["disabled_providers"], conf["disabled_providers"]
    assert conf["model"].startswith("amazon-bedrock/"), conf["model"]
    assert conf["small_model"].startswith("amazon-bedrock/"), conf["small_model"]
    # no profile is pinned by default — each engineer adds their own in opencode settings
    opts = conf["provider"]["amazon-bedrock"]["options"]
    assert opts == {"region": "us-east-1"}, opts
    models = conf["provider"]["amazon-bedrock"]["models"]
    assert set(models) == set(CFG["opencode"]["provider"]["models"]), sorted(models)
    # singular keys only; the plural forms are a hard error in opencode
    for bad in ("agents", "commands", "permissions", "plugins"):
        assert bad not in conf, f"emitted rejected plural top-level key {bad!r}"


def test_profile_is_optional_pinned_only_when_configured():
    """Default: no profile in options (pinning one forces every engineer onto that name).
    When a profile IS configured, it is emitted verbatim."""
    out = emit_target("opencode", cfg_with(
        lambda c: c["opencode"]["provider"].__setitem__("profile", "acme-ai")))
    opts = json.loads((out / "opencode.json").read_text())["provider"]["amazon-bedrock"]["options"]
    assert opts == {"region": "us-east-1", "profile": "acme-ai"}, opts


# --- THE read-only control -------------------------------------------------------

def test_validating_agents_are_read_only():
    out = emit_target("opencode")
    for f in ("reviewer.md", "gate.md"):
        txt = (out / "agent" / f).read_text()
        for cap in ("edit", "bash", "task", "webfetch", "websearch"):
            assert f"{cap}: deny" in txt, f"agent/{f} does not deny {cap}"
        assert "tools:" not in txt, f"agent/{f} uses the deprecated tools: map"


def test_implementer_denies_nothing():
    txt = (emit_target("opencode") / "agent" / "implementer.md").read_text()
    assert "deny" not in txt, "implementer must keep full tools (no permission denies)"
    assert "mode: subagent" in txt, txt.splitlines()[:6]


def test_derived_deny_comes_from_the_allow_list_not_a_hardcoded_set():
    """The config must DRIVE the artifact: a reviewer allowed `webfetch` keeps webfetch,
    and still loses edit/bash/task. If the deny block were hardcoded this fails."""
    def m(c):
        c["opencode"]["subagents"]["reviewer"]["toolFilter"]["allow"] = [
            "read", "grep", "glob", "webfetch"]
    out = emit_target("opencode", cfg_with(m))
    txt = (out / "agent" / "reviewer.md").read_text()
    assert "webfetch: deny" not in txt, \
        "reviewer denies webfetch even though its allow-list grants it — the deny " \
        "block is hardcoded, not derived from toolFilter.allow"
    for cap in ("edit", "bash", "task", "websearch"):
        assert f"{cap}: deny" in txt, f"reviewer no longer denies {cap}"
    # and the clearance agent, whose allow-list did NOT change, still denies webfetch
    gate = (out / "agent" / "gate.md").read_text()
    assert "webfetch: deny" in gate, "per-agent deny sets collapsed into one shared set"


def test_dispatch_name_equals_the_agent_file_that_carries_the_deny_block():
    """THE blocker regression. Under a `verbs: {gate: review}` rename plus a non-default
    subagents.clearance.agent, the token the execute skill dispatches must name an agent
    FILE THAT EXISTS and that file must carry the read-only deny block. If the filename
    came from verbs['gate'] instead, the dispatch would miss and opencode would fall
    back to the full-permission primary agent — the gate would run with edit/bash/task.
    File presence alone is not enough: grep the skill body for the dispatched token."""
    def m(c):
        c["verbs"] = {"gate": "review"}
        c["opencode"]["subagents"]["clearance"]["agent"] = "critic"
        c["opencode"]["subagents"]["reviewer"]["agent"] = "judge"
    out = emit_target("opencode", cfg_with(m))
    body = (out / "skill" / "execute" / "SKILL.md").read_text()

    for role, token in (("clearance", "critic"), ("reviewer", "judge")):
        assert f"`{token}`" in body, \
            f"execute skill never dispatches the {role} agent name {token!r}"
        f = out / "agent" / f"{token}.md"
        assert f.is_file(), (
            f"{role} dispatch token {token!r} resolves to NO agent file "
            f"(present: {sorted(p.name for p in (out / 'agent').iterdir())}) — "
            f"opencode would fall back to the full-permission primary agent")
        txt = f.read_text()
        for cap in ("edit", "bash", "task"):
            assert f"{cap}: deny" in txt, \
                f"agent/{token}.md (the {role} the skill dispatches) does not deny {cap}"

    # the verb rename must NOT have produced a verb-named agent file
    assert not (out / "agent" / "review.md").exists(), \
        "agent file named from verbs['gate'] — filenames must come from subagents.*.agent"
    assert not (out / "agent" / "gate.md").exists()
    # the verb rename DOES still apply to the verb-named surfaces
    assert (out / "command" / "execute.md").is_file()


# --- the REVERSE direction: every dispatch token in every skill body resolves ------
# The forward test above asks "does the CONFIGURED name appear somewhere?". That cannot
# see the residual hole: a shared skill that names a role by some OTHER token (the verb,
# or a hardcoded 'implementer') still dispatches, the configured name still appears
# elsewhere, and the forward assertion passes — while the dispatch itself resolves to no
# agent file and opencode silently falls back to the FULL-PERMISSION primary agent. So
# scan the emitted bodies and demand the reverse: EVERY name used as a dispatch target
# is an agent file that exists, and no stale token is used as one anywhere.

# A line is dispatch CONTEXT if it instructs/relates a role invocation.
DISPATCH_CONTEXT_RE = re.compile(r"dispatch|agentType|\bagents?\b|task tool|`task`", re.I)
# Tokens that must never survive as a dispatch target under a full rename: the template
# defaults (implementer/reviewer/gate) and the gate VERB (review) — on opencode the agent
# file is named from subagents.<role>.agent, never from verbs['gate'].
STALE_DISPATCH_TOKENS = ["implementer", "reviewer", "review", "gate"]
RENAMED = {"implementer": "builder", "reviewer": "judge", "clearance": "critic"}


def _emphasized(token: str, line: str):
    """A role NAME is written as code or bold in these bodies (`x` / **x** / **`x`**);
    that emphasis is what distinguishes a dispatch token from prose about the role."""
    return re.search(r"(?:`|\*\*)%s(?:`|\*\*)" % re.escape(token), line)


def _dispatch_hits(out: Path, tokens):
    """{token: [(relpath, lineno, line)]} for every emphasized token on a dispatch line."""
    hits = {t: [] for t in tokens}
    bodies = sorted(out.glob("skill/*/SKILL.md")) + sorted(out.glob("command/*.md"))
    assert bodies, "no skill/command bodies emitted to scan"
    for f in bodies:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if not DISPATCH_CONTEXT_RE.search(line):
                continue
            for t in tokens:
                if _emphasized(t, line):
                    hits[t].append((str(f.relative_to(out)), i, line.strip()))
    return hits


def test_every_dispatched_role_token_resolves_to_an_agent_file_under_a_full_rename():
    """REVERSE-direction blocker test. Rename ALL THREE roles away from the template
    defaults AND rename the gate verb, then read the emitted bodies as opencode would:

      (a) every renamed name used as a dispatch target has an agent/<name>.md,
      (b) judge + critic (the validating roles) carry edit/bash/task deny; builder none,
      (c) NO stale token (implementer/reviewer/review/gate) is a dispatch target anywhere.

    (c) is the one the pre-fix templates fail: the clearance role was dispatched by VERB
    ({{VERB_GATE}} → 'review') in execute/refine/intro, which names no agent file here.
    """
    def m(c):
        c["verbs"] = {"gate": "review"}
        for role, name in RENAMED.items():
            c["opencode"]["subagents"][role]["agent"] = name
    out = emit_target("opencode", cfg_with(m))
    agents = sorted(p.name for p in (out / "agent").iterdir())
    assert agents == ["builder.md", "critic.md", "judge.md"], agents

    hits = _dispatch_hits(out, list(RENAMED.values()) + STALE_DISPATCH_TOKENS)

    # (c) no stale token may be dispatched — it would resolve to nothing (fail-OPEN).
    stale = {t: h for t in STALE_DISPATCH_TOKENS if (h := hits[t])}
    assert not stale, (
        "dispatch prose names a role by a token that is NOT an emitted agent file "
        "(opencode falls back to the full-permission primary agent): "
        + "; ".join(f"{t!r} at " + ", ".join(f"{p}:{i}" for p, i, _ in h)
                    for t, h in stale.items()))

    # (a) every role IS dispatched by its configured name, and that name resolves.
    for role, name in RENAMED.items():
        assert hits[name], (
            f"no dispatch site names the {role} agent {name!r} — the skills would "
            f"dispatch it by some other (unresolvable) token, or not at all")
        assert (out / "agent" / f"{name}.md").is_file(), (
            f"{role} dispatch token {name!r} resolves to no agent file (present: {agents})")

    # (b) the dispatched validating agents are the read-only ones; the builder is not.
    for name in ("judge", "critic"):
        txt = (out / "agent" / f"{name}.md").read_text()
        for cap in ("edit", "bash", "task"):
            assert f"{cap}: deny" in txt, f"agent/{name}.md (dispatched) does not deny {cap}"
    assert "deny" not in (out / "agent" / "builder.md").read_text(), \
        "agent/builder.md (the implementer) must keep full tools"


def test_role_dispatch_scalars_track_the_host_that_emits_the_files():
    """The scalars themselves: on claude-code they must name the files CC emits (the gate
    agent is VERB-renamed there); on opencode, subagents.<role>.agent. Same config."""
    def m(c):
        c["verbs"] = {"gate": "review"}
        for role, name in RENAMED.items():
            c["opencode"]["subagents"][role]["agent"] = name
    cfg = cfg_with(m)
    cc = emit.build_bindings(cfg)["scalars"]
    assert (cc["IMPLEMENTER_AGENT"], cc["REVIEWER_AGENT"], cc["CLEARANCE_AGENT"]) \
        == ("implementer", "reviewer", "review"), cc["CLEARANCE_AGENT"]
    oc = emit.build_bindings_opencode(cfg)["scalars"]
    assert (oc["IMPLEMENTER_AGENT"], oc["REVIEWER_AGENT"], oc["CLEARANCE_AGENT"]) \
        == ("builder", "judge", "critic"), oc

    # and on CC those three scalars name files the CC target actually emits
    out = emit_target("claude-code", cfg)
    for name in (cc["IMPLEMENTER_AGENT"], cc["REVIEWER_AGENT"], cc["CLEARANCE_AGENT"]):
        assert (out / "agents" / f"{name}.md").is_file(), \
            f"CC dispatch scalar {name!r} names no emitted agents/{name}.md"


def test_mutation_clearance_agent_name_not_in_agent_dir_fails_closed():
    """Directly mutate the wiring: if the emitted filenames stopped following the
    dispatch scalars, emit must fail rather than ship an unresolvable dispatch."""
    real = emit.rename_agent_files
    try:
        emit.rename_agent_files = lambda *a, **k: 0   # simulate "filenames not renamed"
        def m(c):
            c["opencode"]["subagents"]["clearance"]["agent"] = "critic"
        try:
            emit_target("opencode", cfg_with(m))
        except SystemExit:
            return
        raise AssertionError("emitted with a dispatch name that has no agent file")
    finally:
        emit.rename_agent_files = real


def test_mutation_duplicate_agent_names_fail_closed():
    def m(c):
        c["opencode"]["subagents"]["clearance"]["agent"] = "reviewer"
    try:
        emit_target("opencode", cfg_with(m))
    except SystemExit:
        return
    raise AssertionError("two roles sharing one agent name emitted instead of failing")


def test_mutation_empty_reviewer_allow_fails_closed():
    def m(c):
        c["opencode"]["subagents"]["reviewer"]["toolFilter"]["allow"] = []
    try:
        emit_target("opencode", cfg_with(m))
    except SystemExit:
        return
    raise AssertionError("empty reviewer toolFilter.allow emitted instead of failing")


def test_mutation_write_capability_in_allow_fails_closed():
    for role, cap in (("reviewer", "edit"), ("reviewer", "bash"),
                      ("clearance", "task"), ("clearance", "write")):
        def m(c, role=role, cap=cap):
            c["opencode"]["subagents"][role]["toolFilter"]["allow"] = ["read", cap]
        try:
            emit_target("opencode", cfg_with(m))
        except SystemExit:
            continue
        raise AssertionError(f"{role} allow-list containing {cap!r} emitted instead of failing")


def test_mutation_implementer_toolfilter_fails_closed():
    def m(c):
        c["opencode"]["subagents"]["implementer"]["toolFilter"] = {"allow": ["read"]}
    try:
        emit_target("opencode", cfg_with(m))
    except SystemExit:
        return
    raise AssertionError("implementer toolFilter accepted; it must have full tools")


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
    """Strip the two places a shared skill is ALLOWED to differ per target:
    the host-noun scalars, and the target-conditional dispatch section (execute step 5).
    Everything else must match byte-for-byte."""
    for host in ("a Claude Code plugin", "an opencode configuration"):
        text = text.replace(host, "<HOST>")
    for dispatch in ("Workflow stages", "the task tool"):
        text = text.replace(dispatch, "<DISPATCH>")
    # execute's step 5 is the per-target dispatch section, bounded by the next shared line
    return re.sub(r"^### 5\..*?(?=\*\*Context economy)", "", text, flags=re.S | re.M)


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

    assert "`task` tool" in oc, "opencode execute does not dispatch via the task tool"
    assert "branch-per-task" in oc.lower() or "own branch" in oc, \
        "opencode execute does not state branch-per-task isolation"
    assert "no worktree hook" in oc, "opencode execute does not say worktrees are absent"
    assert "isolation: 'worktree'" not in oc, \
        "opencode execute still promises worktree isolation"
    assert "Workflow" not in oc, "CC Workflow dispatch leaked into the opencode execute"

    assert "Workflow" in cc, "claude-code execute lost its Workflow dispatch"
    assert "isolation: 'worktree'" in cc, "claude-code execute lost the worktree guidance"
    assert "`task` tool" not in cc, "opencode task-tool text leaked into the CC execute"


def test_intro_names_its_host():
    oc = (emit_target("opencode") / "skill" / "intro" / "SKILL.md").read_text()
    cc = (emit_target("claude-code") / "skills" / "intro" / "SKILL.md").read_text()
    assert "an opencode configuration" in oc, "opencode intro does not name its host"
    assert "Claude Code plugin" not in oc, "CC host noun leaked into the opencode intro"
    assert "Claude Code plugin" in cc, "claude-code intro lost its host noun"


# --- hygiene ---------------------------------------------------------------------

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
                "agent/implementer.md", "agent/reviewer.md", "agent/gate.md"]:
        assert (out / rel).is_file(), f"missing {rel}"
    for verb in VERBS:
        assert (out / "command" / f"{verb}.md").is_file(), f"missing command/{verb}.md"
    # a command runs as the primary agent; execute must NOT be forced into a subagent
    ex = (out / "command" / "execute.md").read_text()
    assert "agent: build" in ex, ex.splitlines()[:6]
    assert "subtask" not in ex, "execute command forces a subtask; the orchestrator is long-lived"
    # gate is an agent, never a verb/skill on this host
    assert not (out / "skill" / "gate").exists(), "gate emitted as a skill"


def test_verb_renames_apply_to_commands_and_skills_but_not_agents():
    def m(c):
        c["verbs"] = {"execute": "engage", "gate": "clearance"}
    out = emit_target("opencode", cfg_with(m))
    assert (out / "command" / "engage.md").is_file(), "command not renamed to the org's verb"
    assert not (out / "command" / "execute.md").exists()
    assert (out / "skill" / "engage" / "SKILL.md").is_file(), "skill dir not renamed"
    # agent/ is NOT verb-named: the file name is the dispatch name (subagents.*.agent),
    # which here is still "gate". Verb-naming it would break the `task` lookup.
    assert (out / "agent" / "gate.md").is_file(), "agent file must follow subagents.*.agent"
    assert not (out / "agent" / "clearance.md").exists(), \
        "gate agent was verb-renamed away from its dispatch name"


def test_agent_filenames_follow_the_configured_agent_names():
    def m(c):
        c["opencode"]["subagents"]["implementer"]["agent"] = "builder"
        c["opencode"]["subagents"]["reviewer"]["agent"] = "judge"
        c["opencode"]["subagents"]["clearance"]["agent"] = "critic"
    out = emit_target("opencode", cfg_with(m))
    got = sorted(p.name for p in (out / "agent").iterdir())
    assert got == ["builder.md", "critic.md", "judge.md"], got


# --- claude-code regression ------------------------------------------------------

def test_claude_code_target_still_renders():
    out = emit_target("claude-code")
    for rel in ["README.md", ".claude-plugin/plugin.json", "agents/implementer.md",
                "agents/reviewer.md", "agents/gate.md", "skills/execute/SKILL.md"]:
        assert (out / rel).is_file(), f"CC regression: missing {rel}"
    ex = (out / "skills" / "execute" / "SKILL.md").read_text()
    assert "### 5. Dispatch agents as a Workflow" in ex, "CC lost its Workflow dispatch section"
    assert "pipeline(tasks," in ex, "CC lost the workflow pipeline example"
    intro = (out / "skills" / "intro" / "SKILL.md").read_text()
    assert "agent harness** — a Claude Code plugin that helps" in intro, "CC host noun changed"
    assert "instantiated by Workflow stages**" in intro, "CC dispatch noun changed"
    assert not (out / "command").exists(), "CC target emitted an opencode command dir"


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
