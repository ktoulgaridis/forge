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

The opencode artifact is BACK/FORWARD COMPATIBLE: one emitted package runs unchanged
on opencode 1.18.29+ (the plugins' `server()` entrypoint) and on 2.x (`setup()`), so
an org re-emitting after a host upgrade — or distributing to machines on either —
ships ONE artifact. `emit --target opencode` also detects the installed opencode and
refuses hosts below the 1.18.29 floor (see check_opencode_host).

Usage:
  uv run --with pyyaml python lib/emit.py --config <.forge.org.yaml> --out <dir> \
      [--target claude-code|opencode]
"""
import argparse
import json
import re
import subprocess
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


# The intra-task graph (ADR 0018): the graph is a set of STATES one persistent `build`
# graph-agent traverses — understand → build → validate → review → (fix ↺) → clear — by
# swapping skill/rubric/effort per node, NOT a cast of agents that hand off. Review is a
# SELF-CHECK node of that one agent, never a separately-spawned validator; the ONE
# surviving fresh-context validator is the OPTIONAL supplementary reviewer, which runs on
# a COMPLETED PR (never inside the loop). The `graph:` block is SHARED and target-neutral
# — both the claude-code and opencode targets bind the SAME graph. Every rule below is
# fail-closed: a mis-declared graph refuses to emit.
BUILD_AGENT = "build"
# Capabilities a read-only surface may NEVER carry: write/exec/delegate.
GRAPH_READONLY_SURFACE_FORBIDDEN = ["edit", "write", "patch", "bash", "task", "dispatch"]


def _positive_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def graph_bindings(cfg: dict) -> tuple[dict, dict, bool]:
    """Validate the top-level `graph:` block; return (scalars, arrays, supp_enabled).

    Target-neutral: both targets bind the SAME graph. The on-provider/banned model check
    for the supplementary reviewer's pin is deferred to the opencode builder (only there
    does a provider exist); here we validate structure + loop-cap presence + the review
    self-check node + the supplementary reviewer's read-only contract.
    """
    g = cfg.get("graph")
    require(isinstance(g, dict) and g,
            "graph: the top-level graph block is required — the intra-task graph "
            "(the states one build agent traverses) is shared, target-neutral data (ADR 0018)")

    agent = g.get("agent")
    require(agent == BUILD_AGENT,
            f"graph.agent must be {BUILD_AGENT!r} — one persistent graph-agent traverses the "
            f"graph by changing mode (ADR 0018), it is not a cast of agents (got {agent!r})")

    nodes = g.get("nodes")
    require(isinstance(nodes, dict) and nodes,
            "graph.nodes is required — the explicit states the graph-agent traverses")

    entry = g.get("entry")
    require(isinstance(entry, str) and entry in nodes,
            f"graph.entry must name a declared node (got {entry!r}; nodes: {sorted(nodes)})")

    # HARD loop caps — presence REQUIRED (silence is fail-open). This replaces the old
    # per-role max_steps: a single self-walking agent with no cap can loop unbounded.
    for key in ("max_total_steps", "max_fix_loops"):
        require(_positive_int(g.get(key)),
                f"graph.{key} must be a positive int — a graph with no declared "
                f"{key} does not emit (the loop cap's presence is REQUIRED; silence is "
                f"fail-open)")

    # Per-node contract: a node carries exactly one of skill|rubric, an effort, and
    # exactly one of next|terminal. Build the rendered node walk as we go.
    lines = []
    for name, node in nodes.items():
        require(isinstance(node, dict),
                f"graph.nodes.{name} must be a mapping (the node's contract)")
        has_skill, has_rubric = "skill" in node, "rubric" in node
        require(has_skill ^ has_rubric,
                f"graph.nodes.{name} must carry exactly one of skill|rubric "
                f"(a node either applies a skill or applies a rubric)")
        require(node.get("effort"), f"graph.nodes.{name}.effort is required")
        is_terminal, has_next = "terminal" in node, "next" in node
        require(is_terminal ^ has_next,
                f"graph.nodes.{name} must carry exactly one of next|terminal")
        if has_next:
            targets = node["next"] if isinstance(node["next"], list) else [node["next"]]
            for t in targets:
                require(t in nodes, f"graph.nodes.{name}.next → {t!r} is not a declared node")
        carries = f"skill `{node['skill']}`" if has_skill else f"rubric `{node['rubric']}`"
        if is_terminal:
            flow = f"terminal ({node['terminal']})"
        elif isinstance(node["next"], list):
            flow = "→ " + " | ".join(str(t) for t in node["next"])
        else:
            flow = f"→ {node['next']}"
        mode = " [self-check]" if node.get("mode") == "self_check" else ""
        lines.append({"line": f"- **{name}** — {carries}, effort {node['effort']}{mode} {flow}"})

    review = nodes.get("review")
    require(isinstance(review, dict) and review.get("mode") == "self_check",
            "graph.nodes.review must exist with mode: self_check — review is a SELF-CHECK "
            "node of the one build agent (it re-reads its own diff adversarially), never a "
            "separately-spawned validator (ADR 0018 §3)")

    # The supplementary reviewer: the ONLY surviving fresh-context validator (ADR 0018 §5).
    # Runs on a COMPLETED PR, never in-loop. Structure validated here; the model's
    # on-provider/banned check is the opencode builder's.
    supp = g.get("supplementary_reviewer")
    require(isinstance(supp, dict) and "enabled" in supp,
            "graph.supplementary_reviewer is required (at least `enabled`) — the optional "
            "fresh-context reviewer for a completed PR (ADR 0018 §5)")
    supp_enabled = bool(supp.get("enabled"))
    if supp_enabled:
        require(supp.get("fresh_context") is True,
                "graph.supplementary_reviewer.fresh_context must be true when enabled — "
                "independence from the build context is its whole point")
        surface = supp.get("read_surface")
        require(isinstance(surface, list) and surface,
                "graph.supplementary_reviewer.read_surface must be a non-empty list")
        bad = sorted(set(str(a).lower() for a in surface) & set(GRAPH_READONLY_SURFACE_FORBIDDEN))
        require(not bad,
                f"graph.supplementary_reviewer.read_surface carries write/delegate "
                f"capabilities {bad} — the supplementary reviewer is read-only by contract "
                f"(forbidden: {GRAPH_READONLY_SURFACE_FORBIDDEN})")
        require(_positive_int(supp.get("max_steps")),
                "graph.supplementary_reviewer.max_steps must be a positive int")
        require(isinstance(supp.get("model"), str) and supp["model"],
                "graph.supplementary_reviewer.model must be a non-empty string (a full "
                "provider/model ref; validated on-provider by the opencode target)")

    scalars = {
        "BUILD_AGENT": BUILD_AGENT,
        "GRAPH_AGENT": agent,
        "GRAPH_ENTRY": entry,
        "GRAPH_MAX_TOTAL_STEPS": str(g["max_total_steps"]),
        "GRAPH_MAX_FIX_LOOPS": str(g["max_fix_loops"]),
        "GRAPH_REVIEW_MODE": str(review.get("mode")),
        "GRAPH_SUPP_REVIEWER_ENABLED": "true" if supp_enabled else "false",
    }
    arrays = {"GRAPH_NODES": lines}
    return scalars, arrays, supp_enabled


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

    graph_scalars, graph_arrays, supp_enabled = graph_bindings(cfg)

    return {
        "scalars": {
            **verb_scalars,
            **mp_scalars,
            **graph_scalars,
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
            # The ONE graph-agent's depth pin (ADR 0018): the build.md agent traverses
            # every node in a single context; its model/effort are pinned once in its
            # frontmatter (per-node effort switching is instruction-level in the body).
            "AGENT_BUILD_MODEL": agent_field(cfg, "build", "model"),
            "AGENT_BUILD_EFFORT": agent_field(cfg, "build", "effort", "high"),
            # Host nouns — the ONLY places a shared template names its host. The
            # opencode bindings override these; everything else stays identical.
            "HOST_NOUN": "a Claude Code plugin",
            # The dispatch noun: on both targets a ready task is one `build` graph-agent
            # run (ADR 0018), not a fan-out of role stages.
            "HOST_DISPATCH_NOUN": "graph-agent runs",
        },
        "arrays": {"PRIME_READS": wiki["prime_reads"], **graph_arrays},
        # Exactly one TARGET_* is true per emit. Shared templates gate host-specific
        # prose on these; a template with no conditional renders in every target.
        # SUPP_REVIEWER_ENABLED gates the optional-supplementary-reviewer prose/config.
        "conditionals": {"TARGET_CC": True, "TARGET_OPENCODE": False,
                         "SUPP_REVIEWER_ENABLED": supp_enabled},
        "snippets": [
            {"placeholder": p, "adapter": adapter, "label": p, "vars": snippet_vars}
            for p in ("TRACKER_PRIME_SNIPPET", "TRACKER_VIEW_ISSUE_SNIPPET",
                      "TRACKER_COMMENT_LIST_SNIPPET", "TRACKER_COMMENT_SNIPPET",
                      "TRACKER_CREATE_TASK_SNIPPET", "TRACKER_BACKLOG_SNIPPET",
                      "TRACKER_GATE_SNIPPET", "TRACKER_DOCTOR_SNIPPET")
        ],
    }


# --- opencode target -------------------------------------------------------------
# The dangerous capability set: write, command execution, delegation, egress. The
# OPTIONAL supplementary reviewer on opencode is made read-only by DENYING these (a
# bare-string `deny` removes the tool from the model's toolset AND refuses at exec).
# read/grep/glob/list stay default-allow — that is what a reviewer needs.
#
# The emitted deny block is DERIVED from the supplementary reviewer's own
# `read_surface` in the graph block: deny = DANGEROUS_CAPS - read_surface. The config
# is therefore load-bearing, not documentation — a write capability in the read
# surface fails the emit (graph_bindings, above).
DANGEROUS_CAPS = ["edit", "bash", "task", "dispatch", "webfetch", "websearch"]
# `bash` for a read-only reviewer is not a blanket deny but an ALLOWLIST: the tracker
# adapter's read commands (TRACKER_READONLY_COMMANDS) plus these SCM reads. A reviewer
# that cannot read its ticket or the diff wanders instead of judging.
SCM_READONLY_COMMANDS = ["git diff *", "git log *", "git show *", "git status*"]
# These may NEVER appear in a read-only surface: write/exec/delegate. `task`/`dispatch`
# are load-bearing — without them a "read-only" reviewer can spawn an unrestricted
# writer and launder writes. (graph_bindings enforces the same set on the graph block.)
OC_FORBIDDEN_IN_READONLY_ALLOW = GRAPH_READONLY_SURFACE_FORBIDDEN


def derived_deny(allow) -> list[str]:
    """The deny set a read surface implies: every dangerous cap NOT allowed."""
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

    # THE GRAPH (ADR 0018) is validated target-neutrally in graph_bindings (called by
    # build_bindings, above): the states one `build` graph-agent traverses, its loop
    # caps, and the review self-check node. The opencode layer here adds only what a
    # provider makes possible — the definition-time model policy (on-provider +
    # off-banned) — and the OPTIONAL supplementary reviewer's realization (agent file,
    # read-only permission block, task allowlist, subagent depth).
    #
    # The model policy is validated at EMIT time, not discovered at run time: the org
    # floor or the supplementary reviewer's pin, off-provider or banned, does not emit
    # (the glm-5.3 balance incident + the astra retention failure are the evidence — a
    # run with no explicit model inherits the host default, which can be banned/rejected).
    mp_cfg = cfg.get("model_policy", {}) or {}
    banned_models = [str(b).lower() for b in (mp_cfg.get("banned", []) or [])]

    def check_model_ref(ref, where):
        """A model ref must be on the org's provider and off the banned list."""
        require(isinstance(ref, str) and ref,
                f"{where}: model must be a non-empty string (got {ref!r})")
        prov_id = prov["id"]
        if "/" in ref:
            ref_prov, ref_model = ref.split("/", 1)
        else:
            ref_prov, ref_model = "", ref
        # A pin must be a FULL provider/model ref — a bare model id silently inherits
        # whatever provider the host resolves, which is the fail-open the policy exists
        # to close. (The org floor in opencode.model is assembled from provider+model
        # by the emit itself, so it is always full.)
        require(ref_prov == prov_id,
                f"{where}: model {ref!r} is off-provider — the org's only provider is "
                f"{prov_id!r} and a pin must name it explicitly "
                f"(a run with no explicit model inherits the host default; the policy "
                f"is enforced at definition time, not run time)")
        hit = next((b for b in banned_models if b in ref_model.lower()), None)
        require(not hit,
                f"{where}: model {ref!r} is banned by the org's model policy ({hit})")

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

    # The OPTIONAL supplementary reviewer (ADR 0018 §5) — the ONE surviving fresh-context
    # validator, dispatched on a COMPLETED PR, never inside the build loop. Its read
    # surface (validated read-only in graph_bindings) DERIVES the deny set the emitted
    # agent/validate.md carries; the org config's `task` rule then allowlists it and
    # subagent_depth is raised so the build agent can spawn it. When disabled, none of
    # that is emitted (agent/validate.md is dropped; task drops the validate allow).
    supp = (cfg.get("graph") or {}).get("supplementary_reviewer") or {}
    supp_enabled = bool(supp.get("enabled"))
    review_surface = ([str(a).lower() for a in supp.get("read_surface", [])]
                      if supp_enabled else ["read", "grep", "glob"])
    validate_deny = derived_deny(review_surface)
    for cap in ("edit", "bash", "task", "dispatch"):
        require(cap in validate_deny,
                f"graph.supplementary_reviewer: the reviewer's derived deny set is "
                f"missing {cap!r} — a fresh-context reviewer must never keep "
                f"write/exec/delegate")

    ttype = cfg["tracker"]["type"]
    adapter_text = (FORGE_ROOT / f"adapters/tracker/{ttype}.md").read_text()
    try:
        block = extract_snippet(adapter_text, "TRACKER_READONLY_COMMANDS", {})
    except SystemExit:
        raise SystemExit(f"emit: tracker adapter '{ttype}' has no TRACKER_READONLY_COMMANDS "
                         f"section — the opencode target needs it to grant the reviewer "
                         f"its tracker reads (adapters with the full set: jira-acli, github)")
    readonly_cmds = [ln.strip() for ln in block.splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
    readonly_cmds += SCM_READONLY_COMMANDS

    default_ref = f"{model_provider}/{model['model']}"
    small_ref = (f"{model_provider}/{model['small_model']}"
                 if model.get("small_model") else default_ref)
    # The org floor itself is validated: a banned or off-provider floor does not emit.
    check_model_ref(default_ref, "opencode.model.model")
    if model.get("small_model"):
        check_model_ref(small_ref, "opencode.model.small_model")

    # The supplementary reviewer's frontmatter model: its declared pin when enabled
    # (validated on-provider + off-banned), else the org floor. Definition-time, never
    # the host default.
    if supp_enabled:
        check_model_ref(supp["model"], "graph.supplementary_reviewer.model")
        validate_model = supp["model"]
    else:
        validate_model = default_ref
    if "/" not in validate_model:
        validate_model = f"{model_provider}/{validate_model}"
    validate_steps = str(supp["max_steps"]) if supp_enabled else "40"

    b["scalars"].update({
        "HOST_NOUN": "an opencode configuration",
        "OC_DEFAULT_MODEL_REF": default_ref,
        "OC_SMALL_MODEL_REF": small_ref,
        "OC_VALIDATE_MODEL_REF": validate_model,
        "OC_VALIDATE_STEPS": validate_steps,
        "OC_SUBAGENT_DEPTH": "2" if supp_enabled else "1",
        "OC_PROVIDER_ID": prov["id"],
        "OC_PRIMARY_AGENT": oc.get("primary_agent", BUILD_AGENT),
        # The supplementary reviewer's read-only contract, rendered into agent/validate.md:
        # one deny set (bash rendered separately as an allowlist).
        "OC_VALIDATE_DENY_LIST": ", ".join(c for c in validate_deny if c != "bash"),
    })
    mp = cfg.get("model_policy", {}) or {}
    banned = mp.get("banned", []) or []
    b["scalars"]["OC_MODEL_BANNED_JSON"] = ", ".join(json.dumps(str(x)) for x in banned)
    # The org brain loads structurally: each prime read, via the ENV-VAR path ONLY.
    # `default_local_path` is a per-person clone location — baking that machine-specific
    # absolute path into an org-wide distributed artifact is the anti-pattern (it also
    # double-loads the wiki when the env var already points at that same default). The
    # env var is the required, portable pointer; opencode skips paths that do not exist,
    # so an unset env var yields empty entries that are simply skipped.
    reads = cfg["org_wiki"].get("prime_reads") or []
    paths = [f"{{env:{cfg['org_wiki']['local_path_env']}}}/{r}" for r in reads]
    b["arrays"].update({
        "OC_WIKI_INSTRUCTIONS": [
            {"path": pth, "comma": "" if i == len(paths) - 1 else ","}
            for i, pth in enumerate(paths)
        ],
        # `comma` carries JSON separators so the emitted opencode.json parses.
        "OC_DISABLED_PROVIDERS": [
            {"name": p, "comma": "" if i == len(disabled) - 1 else ","}
            for i, p in enumerate(disabled)
        ],
        # The validating-node deny set, one `<cap>: deny` per line; bash renders as an
        # allowlist block (tracker reads + SCM reads), not a `bash: deny` line.
        "OC_VALIDATE_DENY": [{"cap": c} for c in validate_deny if c != "bash"],
        "OC_READONLY_BASH": [{"pattern": p} for p in readonly_cmds],
    })
    b["conditionals"] = {"TARGET_CC": False, "TARGET_OPENCODE": True,
                         "SUPP_REVIEWER_ENABLED": supp_enabled}
    return b


def rename_verbs(out: Path, verbs: dict, skills_dir: str = "skills",
                 agents_dir: str | None = "agents",
                 commands_dir: str | None = None) -> int:
    """Rename emitted skill dirs / commands to the org's verbs.

    The templates ship canonical (skills/inception); the org's `name:` frontmatter is
    already org-rendered via {{VERB_*}}, so the invocable name is correct regardless —
    but renaming the paths keeps the OUTPUT tidy and matching. Shared by every target;
    only the host's directory nouns differ.

    `agents_dir=None` skips the (legacy) gate-agent rename. Under ADR 0018 there is no
    gate AGENT to rename on either target — the gate is a rubric the build agent applies,
    not a dispatchable agent — so the gate branch below is a no-op when no agents/gate.md
    exists.
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
    # command/ and skill/ ARE verb-named; agent/ carries at most ONE file — the OPTIONAL
    # supplementary reviewer (agent/validate.md), when enabled — whose name is fixed by
    # the native tool's subagent_type. There is no cast to rename (ADR 0018).
    renames = rename_verbs(out, resolve_verbs(cfg), skills_dir="skill",
                           agents_dir=None, commands_dir="command")
    sc = bindings["scalars"]
    supp_enabled = bindings["conditionals"].get("SUPP_REVIEWER_ENABLED", False)

    # agent/validate.md always renders (render_tree renders every *.template); it is the
    # supplementary reviewer's contract, kept ONLY when the reviewer is enabled. When it
    # is disabled there is no fresh-context validator to emit — drop the file.
    validate_agent = out / "agent" / "validate.md"
    if not supp_enabled and validate_agent.is_file():
        validate_agent.unlink()
        rendered = [p for p in rendered if p != validate_agent]

    # Post-render assertions on the artifact itself, not on the config.
    conf = json.loads((out / "opencode.json").read_text())
    require(conf.get("enabled_providers") == [sc["OC_PROVIDER_ID"]],
            f"opencode.json enabled_providers must be exactly "
            f"[{sc['OC_PROVIDER_ID']!r}] — the allowlist is the only-Bedrock "
            f"control that survives an ambient ANTHROPIC_API_KEY/OPENAI_API_KEY "
            f"(got {conf.get('enabled_providers')!r})")

    # The `task` allowlist: '*': deny is NON-NEGOTIABLE (the orchestrator's only door to a
    # child run stays denied-by-default), and the primary build agent is allowlisted. The
    # `validate` allow + subagent_depth>=2 are GATED on the supplementary reviewer being
    # enabled — only then can the build agent spawn a fresh-context reviewer as a subagent.
    task_perm = (conf.get("permission") or {}).get("task")
    require(isinstance(task_perm, dict)
            and task_perm.get("*") == "deny"
            and task_perm.get(sc["OC_PRIMARY_AGENT"]) == "allow",
            f"opencode.json permission.task must be a '*': deny allowlist with "
            f"{sc['OC_PRIMARY_AGENT']!r} allowed — got {task_perm!r}")
    if supp_enabled:
        require(int(conf.get("subagent_depth", 1)) >= 2,
                f"opencode.json subagent_depth must be >= 2 when the supplementary "
                f"reviewer is enabled — the build agent (depth 1) spawns it as a native "
                f"subagent (depth 2) (got {conf.get('subagent_depth')!r})")
        require(validate_agent.is_file(),
                "agent/validate.md — the supplementary reviewer's contract — was not "
                "rendered though the reviewer is enabled")
        require(task_perm.get("validate") == "allow",
                f"opencode.json permission.task must allow 'validate' when the "
                f"supplementary reviewer is enabled — got {task_perm!r}")
    else:
        require(task_perm.get("validate") != "allow",
                "opencode.json permission.task allows 'validate' but the supplementary "
                "reviewer is disabled — a spawnable reviewer with no contract file")
    return rendered, renames


TARGETS = {
    "claude-code": emit_claude_code,
    "opencode": emit_opencode,
}


# --- opencode host version ------------------------------------------------------------
# The emitted configuration is ONE artifact for TWO hosts (the emitted plugins carry
# both entrypoints: 2.x loads setup(), 1.18.29+ loads server()). The floor is 1.18.29
# — the first 1.x release that accepts the object form with server(). Older hosts can
# only run the pre-dual releases of an org's emitted package.
OPENCODE_FLOOR = (1, 18, 29)


def parse_opencode_version(text: str) -> tuple[int, int, int] | None:
    """`opencode v2.0.8` / `opencode 1.18.29` → (2, 0, 8) / (1, 18, 29)."""
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def opencode_host_version() -> tuple[int, int, int] | None:
    """The installed opencode's version, or None when it is not on PATH."""
    try:
        out = subprocess.run(["opencode", "--version"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_opencode_version(out.stdout or "")


def check_opencode_host():
    """Warn or fail against the opencode actually installed where we emit.

    The artifact is the same either way (dual entrypoint); this only guards the
    floor and tells the operator which half will run on their host.
    """
    v = opencode_host_version()
    if v is None:
        print("opencode: not found on PATH — the artifact targets opencode "
              f">={'.'.join(map(str, OPENCODE_FLOOR))} and 2.x (both entrypoints)")
        return
    pretty = ".".join(map(str, v))
    if v < OPENCODE_FLOOR:
        raise SystemExit(
            f"emit: detected opencode v{pretty} — the emitted plugins' 1.x entrypoint "
            f"(server()) needs opencode >={'.'.join(map(str, OPENCODE_FLOOR))}. "
            "Upgrade opencode, or keep the previously emitted package.")
    half = "setup() (2.x)" if v >= (2, 0, 0) else "server() (1.18.29+)"
    print(f"opencode v{pretty} detected — artifact carries both entrypoints; "
          f"this host loads {half}")


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
    if args.target == "opencode":
        check_opencode_host()


if __name__ == "__main__":
    main()
