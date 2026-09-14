#!/usr/bin/env python3
"""Driver for /forge:emit — turn a .forge.org.yaml into an org-owned harness.

Computes the org-tier bindings from the config, then calls the SHARED renderer
(lib/render.py) with the leak gate on. This is the deterministic engine behind
the /forge:emit command; the command doc is the human-facing procedure.

ONE config, N TARGETS. The org tier is host-neutral: the same .forge.org.yaml can
be emitted as a Claude Code plugin (`--target claude-code`, the default) or as an
opencode configuration (`--target opencode`). The skill bodies are SHARED byte-for-byte
between targets; only the host packaging (manifest vs opencode.json, agents/ vs agent/,
hooks vs plugin/) and the few host-specific lines behind {{#TARGET_*}} conditionals
differ.

Usage:
  uv run --with pyyaml python lib/emit.py --config <.forge.org.yaml> --out <dir> \
      [--target claude-code|opencode]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_tree, extract_snippet  # noqa: E402

FORGE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_TOKENS = {"acme", "Acme", "janedoe", "Jane Doe", "example", "example-project"}

# Canonical verb names the templates ship with. An org may rename any of them via the
# `verbs:` map in .forge.org.yaml (e.g. Acme: inception->plot, execute->engage,
# gate->clearance). Verb-picking is part of building an org's forge product — the
# generator stays neutral; the names are the org's creative choice. Each canonical
# skill lives at templates/org-plugin/skills/<canonical>/; emit renames the rendered
# dir to the org's word and substitutes {{VERB_<CANONICAL>}} everywhere it's referenced.
CANONICAL_VERBS = [
    "intro", "setup", "prime", "inception", "refine", "execute", "gate", "wiki", "handoff",
]


def resolve_verbs(cfg):
    """canonical name -> org's chosen name (defaults to canonical when unset)."""
    overrides = cfg.get("verbs", {}) or {}
    unknown = set(overrides) - set(CANONICAL_VERBS)
    if unknown:
        raise SystemExit(f"verbs: unknown verb key(s) {sorted(unknown)}; "
                         f"valid: {CANONICAL_VERBS}")
    return {v: overrides.get(v, v) for v in CANONICAL_VERBS}


# model_policy is the ORG's model floor for ALL agent work (named roles AND any ad-hoc
# agent() in a hand-authored Workflow). It is OPTIONAL and configurable per org — the
# generator never hardcodes a floor, so when the block is absent we supply sane, NEUTRAL
# defaults rather than requiring it. Exposed as scalars the same way agent models are,
# so the rendered skills can surface each org's floor via {{MODEL_POLICY_*}}.
MODEL_POLICY_DEFAULTS = {
    "default": "the role's configured model",
    "banned": [],
    "rule": "Set model explicitly on ad-hoc agent() calls; never leave it implicit.",
}


def model_policy_scalars(cfg):
    """Read optional cfg['model_policy'] → MODEL_POLICY_* scalars (all strings)."""
    mp = cfg.get("model_policy", {}) or {}
    banned = mp.get("banned", MODEL_POLICY_DEFAULTS["banned"])
    if isinstance(banned, (list, tuple)):
        banned = ", ".join(str(b) for b in banned)
    return {
        "MODEL_POLICY_DEFAULT": str(mp.get("default", MODEL_POLICY_DEFAULTS["default"])),
        "MODEL_POLICY_BANNED": str(banned),
        "MODEL_POLICY_RULE": str(mp.get("rule", MODEL_POLICY_DEFAULTS["rule"])),
    }


def agent_field(cfg, name, field, default=None):
    for p in cfg.get("agents", []):
        if p.get("name") == name:
            if field in p:
                return p[field]
            if default is not None:
                return default
            raise SystemExit(f"agents: '{name}' is missing '{field}' in .forge.org.yaml")
    raise SystemExit(f"agents: missing entry for '{name}' in .forge.org.yaml")


def require(cond, msg):
    if not cond:
        raise SystemExit(f"emit: {msg}")


def build_bindings(cfg: dict) -> dict:
    org, plugin, wiki, tracker = (
        cfg["org"], cfg["plugin"], cfg["org_wiki"], cfg["tracker"])

    # Identity must be filled in, not example-valued (emit.md step 1).
    for path, val in [
        ("org.name", org.get("name")), ("org.slug", org.get("slug")),
        ("plugin.name", plugin.get("name")),
        ("plugin.author.name", plugin.get("author", {}).get("name")),
        ("plugin.homepage", plugin.get("homepage")),
    ]:
        require(val, f"{path} is required")
        require(str(val) not in EXAMPLE_TOKENS,
                f"{path} still has an example value ({val!r}) — fill in your org")

    # Default-deny: no always-on cross-project promotion without an adjudicator.
    om = cfg.get("operating_model", {})
    require(not (om.get("capture_default") == "always-on"
                 and not om.get("cross_project_truth_adjudicator")),
            "operating_model: capture_default 'always-on' needs a "
            "cross_project_truth_adjudicator (default-deny)")

    tc = tracker["config"]
    snippet_vars = {
        "tracker.config.cloud_id": tc.get("cloud_id", ""),
        "tracker.config.project_key": tc.get("project_key", ""),
        "tracker.config.base_url": tc.get("base_url", ""),
        "tracker.config.repo": tc.get("repo", ""),
    }
    adapter = f"adapters/tracker/{tracker['type']}.md"

    verbs = resolve_verbs(cfg)
    verb_scalars = {f"VERB_{canon.upper()}": name for canon, name in verbs.items()}

    mp_scalars = model_policy_scalars(cfg)

    return {
        "scalars": {
            **verb_scalars,
            **mp_scalars,
            "ORG_NAME": org["name"],
            "PLUGIN_NAME": plugin["name"],
            "PLUGIN_VERSION": plugin["version"],
            "PLUGIN_DESCRIPTION": plugin["description"],
            "PLUGIN_AUTHOR_NAME": plugin["author"]["name"],
            "PLUGIN_AUTHOR_URL": plugin["author"]["url"],
            "PLUGIN_HOMEPAGE": plugin["homepage"],
            "PLUGIN_LICENSE": plugin["license"],
            "ORG_WIKI_NAME": wiki["name"],
            "ORG_WIKI_REMOTE": wiki["remote"],
            "ORG_WIKI_PATH_ENV": wiki["local_path_env"],
            "ORG_WIKI_DEFAULT_PATH": wiki["default_local_path"],
            "AGENT_IMPLEMENTER_MODEL": agent_field(cfg, "implementer", "model"),
            "AGENT_IMPLEMENTER_EFFORT": agent_field(cfg, "implementer", "effort", "high"),
            "AGENT_REVIEWER_MODEL": agent_field(cfg, "reviewer", "model"),
            "AGENT_REVIEWER_EFFORT": agent_field(cfg, "reviewer", "effort", "high"),
            "AGENT_GATE_MODEL": agent_field(cfg, "gate", "model"),
            "AGENT_GATE_EFFORT": agent_field(cfg, "gate", "effort", "medium"),
            # Role DISPATCH names — the token a shared skill must use whenever it tells
            # the orchestrator to dispatch a role. Every host names its agent files
            # differently, so a shared template may NEVER hardcode a role name: on
            # claude-code the emitted files are agents/implementer.md, agents/reviewer.md
            # and agents/<verbs['gate']>.md (rename_verbs verb-renames the gate agent), so
            # these bind to exactly those names; the opencode layer rebinds them to
            # subagents.<role>.agent. Bound here (not only in the opencode builder) so a
            # shared template's dispatch prose resolves to a REAL agent file in EVERY
            # target — a token that resolves to nothing is a fail-open (the host falls
            # back to the full-permission primary agent).
            "IMPLEMENTER_AGENT": "implementer",
            "REVIEWER_AGENT": "reviewer",
            "CLEARANCE_AGENT": verbs["gate"],
            # Host nouns — the ONLY places a shared template names its host. The
            # opencode bindings override these; everything else stays identical.
            "HOST_NOUN": "a Claude Code plugin",
            "HOST_DISPATCH_NOUN": "Workflow stages",
        },
        "arrays": {"PRIME_READS": wiki["prime_reads"]},
        # Exactly one TARGET_* is true per emit. Shared templates gate host-specific
        # prose on these; a template with no conditional renders in every target.
        "conditionals": {"TARGET_CC": True, "TARGET_OPENCODE": False},
        "snippets": [
            {"placeholder": p, "adapter": adapter, "label": p, "vars": snippet_vars}
            for p in ("TRACKER_PRIME_SNIPPET", "TRACKER_VIEW_ISSUE_SNIPPET",
                      "TRACKER_COMMENT_LIST_SNIPPET", "TRACKER_COMMENT_SNIPPET",
                      "TRACKER_CREATE_TASK_SNIPPET", "TRACKER_BACKLOG_SNIPPET",
                      "TRACKER_GATE_SNIPPET", "TRACKER_DOCTOR_SNIPPET")
        ],
    }


# --- opencode target -------------------------------------------------------------
# The dangerous capability set: write, command execution, delegation, egress. A
# reviewer/gate agent on opencode is made read-only by DENYING these permissions (a
# bare-string `deny` removes the tool from the model's toolset AND refuses at exec).
# read/grep/glob/list stay default-allow — that is what a reviewer needs.
#
# The emitted deny block is DERIVED, per agent, from that agent's own
# `toolFilter.allow` in the config: deny = DANGEROUS_CAPS - allow. The config is
# therefore load-bearing, not documentation — delete a capability from an allow-list
# and the artifact changes; add `task` to one and the emit fails (below).
DANGEROUS_CAPS = ["edit", "bash", "task", "dispatch", "webfetch", "websearch"]
# `bash` for a read-only role is not a blanket deny but an ALLOWLIST: the tracker
# adapter's read commands (TRACKER_READONLY_COMMANDS) plus these SCM reads. A validating
# role that cannot read its ticket or the diff wanders instead of judging.
SCM_READONLY_COMMANDS = ["git diff *", "git log *", "git show *", "git status*"]
# Step caps: a troop that has not concluded by then answers in text. Sane defaults,
# overridable per role via agents[].max_steps.
DEFAULT_MAX_STEPS = {"implementer": 120, "reviewer": 40, "gate": 25}
# These may NEVER appear in a read-only agent's allow-list: write/exec/delegate.
# `task` is the load-bearing one — without it a "read-only" reviewer can spawn an
# unrestricted implementer and launder writes.
OC_FORBIDDEN_IN_READONLY_ALLOW = ["edit", "write", "patch", "bash", "task", "dispatch"]


def derived_deny(allow) -> list[str]:
    """The deny set an agent's allow-list implies: every dangerous cap NOT allowed."""
    allowed = {str(a).lower() for a in (allow or [])}
    return [c for c in DANGEROUS_CAPS if c not in allowed]

def build_bindings_opencode(cfg: dict) -> dict:
    """Org bindings + the opencode-target layer. Fail-closed on every control."""
    b = build_bindings(cfg)          # org scalars stay IDENTICAL across targets

    oc = cfg.get("opencode")
    require(isinstance(oc, dict) and oc,
            "opencode: block is required for --target opencode")

    # The provider is the org's choice and is ONLY an id: auth and provider options are
    # opencode's business (`opencode auth login`, `provider.<id>.options` if needed).
    prov = oc.get("provider") or {}
    require(prov.get("id"), "opencode.provider.id is required")
    require(set(prov) == {"id"},
            f"opencode.provider takes only `id`; got {sorted(set(prov) - {'id'})} — "
            f"provider options and credentials belong in opencode, not the org config")

    model = oc.get("model") or {}
    require(model.get("model"), "opencode.model.model is required")
    model_provider = model.get("provider") or prov["id"]

    subs = oc.get("subagents") or {}
    for role in ("implementer", "reviewer", "clearance"):
        require(isinstance(subs.get(role), dict) and subs[role],
                f"opencode.subagents.{role} is required")
        require(subs[role].get("agent"), f"opencode.subagents.{role}.agent is required")
        require(str(subs[role]["agent"]).strip(),
                f"opencode.subagents.{role}.agent must be a non-empty name")

    # THE agent NAME is the dispatch token AND the emitted filename (see
    # rename_agent_files). Two roles sharing a name would collapse two different
    # permission contracts onto one file — the read-only boundary would then depend on
    # render order. Fail closed.
    names = [str(subs[r]["agent"]).strip() for r in ("implementer", "reviewer", "clearance")]
    require(len(set(names)) == len(names),
            f"opencode.subagents.*.agent names must be DISTINCT (got {names}) — the name "
            f"is both the dispatch token and the agent filename")

    # THE load-bearing control: the two validating roles are read-only. An empty or
    # write-capable allow-list is a fail-OPEN, so it fails the emit loudly.
    for role in ("reviewer", "clearance"):
        allow = ((subs[role].get("toolFilter") or {}).get("allow"))
        require(isinstance(allow, list) and allow,
                f"opencode.subagents.{role}.toolFilter.allow must be a NON-EMPTY list "
                f"(read-only means an explicit read-only allow-list, not silence)")
        bad = sorted(set(str(a).lower() for a in allow) & set(OC_FORBIDDEN_IN_READONLY_ALLOW))
        require(not bad,
                f"opencode.subagents.{role}.toolFilter.allow contains write/delegate "
                f"capabilities {bad} — {role} is read-only by contract "
                f"(forbidden: {OC_FORBIDDEN_IN_READONLY_ALLOW})")
    require("toolFilter" not in subs["implementer"],
            "opencode.subagents.implementer must NOT declare a toolFilter — the "
            "implementer needs full tools (it writes code, runs tests, opens the PR)")

    skills = oc.get("skills") or []
    require(isinstance(skills, list) and skills, "opencode.skills must be a non-empty list")
    unknown = [s for s in skills if s not in CANONICAL_VERBS]
    require(not unknown,
            f"opencode.skills has unknown verb(s) {sorted(unknown)}; valid: {CANONICAL_VERBS}")

    # Only-Bedrock is enforced by the ALLOWLIST (`enabled_providers`), which is the
    # only control that holds when the environment already carries ambient provider
    # keys (ANTHROPIC_API_KEY / OPENAI_API_KEY) — those get auto-detected as providers
    # that `disabled_providers: ["opencode"]` does NOT cover. The deny entry stays as
    # belt-and-suspenders (it also hides the built-in Zen provider by name).
    # Absent means "use the default"; PRESENT-but-wrong is a fail-open and must not emit.
    disabled = oc["disabled_providers"] if "disabled_providers" in oc else ["opencode"]
    require("opencode" in disabled,
            "opencode.disabled_providers must include 'opencode' — the built-in Zen "
            "provider is named explicitly, belt-and-suspenders under the allowlist")

    # Per-agent deny sets, DERIVED from each role's own allow-list (FIX: the config
    # drives the artifact — the two roles may legitimately differ).
    reviewer_deny = derived_deny(subs["reviewer"]["toolFilter"]["allow"])
    clearance_deny = derived_deny(subs["clearance"]["toolFilter"]["allow"])
    for role, deny in (("reviewer", reviewer_deny), ("clearance", clearance_deny)):
        for cap in ("edit", "bash", "task", "dispatch"):
            require(cap in deny,
                    f"opencode.subagents.{role}: derived deny set is missing {cap!r} — "
                    f"a read-only agent must never keep write/exec/delegate")

    adapter_text = (FORGE_ROOT / f"adapters/tracker/{cfg['tracker']['type']}.md").read_text()
    readonly_cmds = [ln.strip() for ln in
                     extract_snippet(adapter_text, "TRACKER_READONLY_COMMANDS", {}).splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
    readonly_cmds += SCM_READONLY_COMMANDS

    default_ref = f"{model_provider}/{model['model']}"
    small_ref = (f"{model_provider}/{model['small_model']}"
                 if model.get("small_model") else default_ref)

    b["scalars"].update({
        "HOST_NOUN": "an opencode configuration",
        "HOST_DISPATCH_NOUN": "the task tool",
        "OC_DEFAULT_MODEL_REF": default_ref,
        "OC_SMALL_MODEL_REF": small_ref,
        "OC_PROVIDER_ID": prov["id"],
        "OC_PRIMARY_AGENT": oc.get("primary_agent", "build"),
        "OC_IMPLEMENTER_AGENT": subs["implementer"]["agent"],
        "OC_IMPLEMENTER_PERSONA": subs["implementer"].get("persona", ""),
        "OC_REVIEWER_AGENT": subs["reviewer"]["agent"],
        "OC_REVIEWER_PERSONA": subs["reviewer"].get("persona", ""),
        "OC_CLEARANCE_AGENT": subs["clearance"]["agent"],
        "OC_CLEARANCE_PERSONA": subs["clearance"].get("persona", ""),
        # Re-point the SHARED dispatch scalars at the names THIS host emits. On opencode
        # an agent resolves by filename (agent/<name>.md) and the filename comes from
        # subagents.<role>.agent — NOT from the verb — so a shared template that named
        # the clearance role by verb would resolve to nothing and opencode would fall
        # back to the full-permission primary agent.
        "IMPLEMENTER_AGENT": subs["implementer"]["agent"],
        "REVIEWER_AGENT": subs["reviewer"]["agent"],
        "CLEARANCE_AGENT": subs["clearance"]["agent"],
        "OC_REVIEWER_DENY_LIST": ", ".join(reviewer_deny),
        "OC_CLEARANCE_DENY_LIST": ", ".join(clearance_deny),
        **{f"OC_{role.upper()}_STEPS":
           str(agent_field(cfg, role, "max_steps", DEFAULT_MAX_STEPS[role]))
           for role in DEFAULT_MAX_STEPS},
    })
    mp = cfg.get("model_policy", {}) or {}
    banned = mp.get("banned", []) or []
    b["scalars"]["OC_MODEL_BANNED_JSON"] = ", ".join(json.dumps(str(x)) for x in banned)
    roles = [(subs["implementer"]["agent"], True), (subs["reviewer"]["agent"], False),
             (subs["clearance"]["agent"], False)]
    # The org brain loads structurally: each prime read, via the env-var path and the
    # default path (opencode skips paths that do not exist; unset env → empty → skipped).
    reads = cfg["org_wiki"].get("prime_reads") or []
    paths = [f"{{env:{cfg['org_wiki']['local_path_env']}}}/{r}" for r in reads] + \
            [f"{cfg['org_wiki']['default_local_path']}/{r}" for r in reads]
    b["arrays"].update({
        "OC_WIKI_INSTRUCTIONS": [
            {"path": pth, "comma": "" if i == len(paths) - 1 else ","}
            for i, pth in enumerate(paths)
        ],
        # The dispatch tool's role table: name → may it write (gets a worktree).
        "OC_DISPATCH_ROLES": [
            {"name": n, "writes": "true" if w else "false",
             "comma": "" if i == len(roles) - 1 else ","}
            for i, (n, w) in enumerate(roles)
        ],
        # `comma` carries JSON separators so the emitted opencode.json parses.
        "OC_DISABLED_PROVIDERS": [
            {"name": p, "comma": "" if i == len(disabled) - 1 else ","}
            for i, p in enumerate(disabled)
        ],
        # The deny sets the read-only agent templates render, one `<cap>: deny` per
        # line — one array per role, each derived from that role's allow-list.
        # bash is rendered as an allowlist block, not a `bash: deny` line.
        "OC_REVIEWER_DENY": [{"cap": c} for c in reviewer_deny if c != "bash"],
        "OC_CLEARANCE_DENY": [{"cap": c} for c in clearance_deny if c != "bash"],
        "OC_READONLY_BASH": [{"pattern": p} for p in readonly_cmds],
    })
    b["conditionals"] = {"TARGET_CC": False, "TARGET_OPENCODE": True}
    return b


def rename_agent_files(out: Path, agents_dir: str, names: dict) -> int:
    """Name each emitted agent file after its DISPATCH name (subagents.<role>.agent).

    On opencode an agent is resolved by filename: `task` with `agent: <name>` loads
    `agent/<name>.md`. If the filename came from anywhere else than the dispatch token —
    e.g. from `verbs['gate']` — the two can disagree, the lookup misses, and opencode
    falls back to the FULL-PERMISSION primary agent. That is a fail-OPEN of the whole
    read-only boundary: the gate would run with edit/bash/task allowed. So the filename
    is derived from the same scalar the skills dispatch, and the two are equal by
    construction. `names` maps template stem (implementer/reviewer/gate) -> agent name.
    """
    renames = 0
    for stem, name in names.items():
        if name == stem:
            continue
        src = out / agents_dir / f"{stem}.md"
        if src.is_file():
            src.rename(out / agents_dir / f"{name}.md")
            renames += 1
    return renames


def rename_verbs(out: Path, verbs: dict, skills_dir: str = "skills",
                 agents_dir: str | None = "agents",
                 commands_dir: str | None = None) -> int:
    """Rename emitted skill dirs / commands / the gate agent file to the org's verbs.

    The templates ship canonical (skills/inception, agents/gate.md); the org's `name:`
    frontmatter is already org-rendered via {{VERB_*}}, so the invocable name is correct
    regardless — but renaming the paths keeps the OUTPUT tidy and matching. Shared by
    every target; only the host's directory nouns differ.

    `agents_dir=None` skips the gate-agent rename — for a host where an agent file is
    named by its DISPATCH name, not by the verb (see rename_agent_files).
    """
    renames = 0
    for canon, name in verbs.items():
        if name == canon:
            continue
        sd = out / skills_dir / canon
        if sd.is_dir():
            sd.rename(out / skills_dir / name)
            renames += 1
        if commands_dir:
            cf = out / commands_dir / f"{canon}.md"
            if cf.is_file():
                cf.rename(out / commands_dir / f"{name}.md")
                renames += 1
    # the gate verb is also an agent file (on hosts that name agents by verb)
    gate_name = verbs["gate"]
    if agents_dir and gate_name != "gate":
        gf = out / agents_dir / "gate.md"
        if gf.is_file():
            gf.rename(out / agents_dir / f"{gate_name}.md")
            renames += 1
    return renames


def org_strings(cfg) -> set[str]:
    """Every string the org wrote in its config — its own identity is never a leak."""
    out = set()
    def walk(v):
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    walk(cfg)
    return out


def emit_claude_code(cfg: dict, out: Path):
    """Target: a Claude Code plugin (skills/ + agents/ + hooks/ + .claude-plugin/)."""
    bindings = build_bindings(cfg)
    rendered = render_tree(
        bindings,
        FORGE_ROOT / "templates/org-plugin",
        out,
        FORGE_ROOT,
        leak_check=True, leak_allow=org_strings(cfg),
    )
    renames = rename_verbs(out, resolve_verbs(cfg))
    return rendered, renames


def emit_opencode(cfg: dict, out: Path):
    """Target: an opencode configuration (opencode.json + agent/ + command/ + skill/).

    Two passes. Pass 1 renders the opencode-specific packaging. Pass 2 folds the SHARED
    skill bodies (the same templates the Claude Code target renders) into skill/<verb>/,
    so a skill's prose is byte-identical across targets except where a {{#TARGET_*}}
    conditional or a host-noun scalar deliberately differs.
    """
    bindings = build_bindings_opencode(cfg)
    rendered = render_tree(
        bindings,
        FORGE_ROOT / "templates/opencode",
        out,
        FORGE_ROOT,
        leak_check=True, leak_allow=org_strings(cfg),
        clean=True,
    )
    for canon in cfg["opencode"]["skills"]:
        src = FORGE_ROOT / "templates/org-plugin/skills" / canon
        require(src.is_dir(), f"opencode.skills: no shared skill template for '{canon}'")
        rendered += render_tree(
            bindings, src, out / "skill" / canon, FORGE_ROOT,
            leak_check=True, clean=False, leak_allow=org_strings(cfg),
        )
    # command/ and skill/ ARE verb-named; agent/ is NOT (agents_dir=None) — an agent
    # file is named by its dispatch token so the skills' `task` calls resolve.
    renames = rename_verbs(out, resolve_verbs(cfg), skills_dir="skill",
                           agents_dir=None, commands_dir="command")
    sc = bindings["scalars"]
    agent_names = {
        "implementer": sc["OC_IMPLEMENTER_AGENT"],
        "reviewer": sc["OC_REVIEWER_AGENT"],
        "gate": sc["OC_CLEARANCE_AGENT"],
    }
    renames += rename_agent_files(out, "agent", agent_names)

    # Post-render assertions on the artifact itself, not on the config.
    for role, name in agent_names.items():
        require((out / "agent" / f"{name}.md").is_file(),
                f"agent/{name}.md is missing — the {role} dispatch name does not resolve "
                f"to an emitted agent file (opencode would fall back to the "
                f"full-permission primary agent)")
    conf = json.loads((out / "opencode.json").read_text())
    require(conf.get("enabled_providers") == [sc["OC_PROVIDER_ID"]],
            f"opencode.json enabled_providers must be exactly "
            f"[{sc['OC_PROVIDER_ID']!r}] — the allowlist is the only-Bedrock "
            f"control that survives an ambient ANTHROPIC_API_KEY/OPENAI_API_KEY "
            f"(got {conf.get('enabled_providers')!r})")
    return rendered, renames


TARGETS = {
    "claude-code": emit_claude_code,
    "opencode": emit_opencode,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge emit driver")
    ap.add_argument("--config", default=".forge.org.yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default="claude-code", choices=sorted(TARGETS),
                    help="host to emit for (default: claude-code)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    out = Path(args.out)
    rendered, renames = TARGETS[args.target](cfg, out)

    print(f"OK emitted {cfg['plugin']['name']} v{cfg['plugin']['version']} "
          f"→ {args.out} ({len(rendered)} files, {renames} verb renames)")
    print("leak gate: clean (no generator identity in output)")


if __name__ == "__main__":
    main()
