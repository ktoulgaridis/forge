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


def migrate_subagents_to_nodes(cfg, subagents) -> dict:
    """Migrate the retired `opencode.subagents` cast to the graph (`opencode.nodes`).

    Mechanical and lossless: each VALIDATING role (one with a `toolFilter.allow`)
    becomes a validate node — `fresh_context: true` (no-self-review was always the
    contract), the `read_surface` from the role's `toolFilter.allow`, the `max_steps`
    from the role's cap in `agents[]` (or the default for that role), and the role's
    model as a node pin when the role pinned one. The produce role (no `toolFilter`)
    needs no node — produce is the default writer kind; its cap comes from `agents[]`.

    A legacy `agents[]` model is a SHORTHAND ("sonnet", "opus") — the org's model
    naming, not a full provider/model ref. The migration resolves it through the org's
    provider and model map so the node pin is a full ref (the definition-time policy
    requires it). A shorthand with no mapping in `opencode.model` is dropped (the org
    floor applies) rather than emit an off-provider pin.
    """
    # The role's model + cap live in the org's `agents[]` block, keyed by role name.
    agents_by_name = {a.get("name"): a for a in cfg.get("agents", [])}
    oc = cfg.get("opencode", {})
    prov_id = (oc.get("provider") or {}).get("id", "")
    # The org's model map: shorthand name -> full model id. The org floor's own model
    # is the canonical mapping for its shorthand; an org that names models by shorthand
    # in agents[] typically maps them in opencode.model (model / small_model).
    model_map = {}
    for key in ("model", "small_model"):
        mid = (oc.get("model") or {}).get(key)
        if mid:
            # map both the full id and its last dotted segment as shorthand keys
            model_map[mid] = mid
            model_map[mid.split(".")[-1].split("-")[0] if "." in mid else mid] = mid
            # common shorthand: "sonnet" -> a sonnet model id, "opus" -> an opus id
            for name in ("sonnet", "opus", "haiku"):
                if name in mid.lower():
                    model_map[name] = mid
    # Legacy role names map to the canonical node names (the cast's "reviewer" was
    # the review node; "clearance" was the gate). A role whose name is already a node
    # name keeps it.
    ROLE_TO_NODE = {"reviewer": "review", "clearance": "gate", "gate": "gate",
                    "review": "review"}
    nodes = {}
    for role, spec in subagents.items():
        tool_filter = (spec or {}).get("toolFilter") or {}
        allow = tool_filter.get("allow")
        if not allow:
            continue  # a produce role (no read-only contract) — no node to migrate
        agent = agents_by_name.get(role) or {}
        name = ROLE_TO_NODE.get(role, role)
        node = {
            "kind": "validate",
            "fresh_context": True,
            "read_surface": list(allow),
            "max_steps": agent.get("max_steps", DEFAULT_MAX_STEPS.get(name, 40)),
        }
        shorthand = agent.get("model")
        if shorthand:
            full = model_map.get(str(shorthand).lower())
            if full:
                node["model"] = f"{prov_id}/{full}" if "/" not in full else full
            # else: no mapping — drop the pin (the org floor applies) rather than
            # emit an off-provider ref
        nodes[name] = node
    return nodes

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

    # THE GRAPH, not the cast (ADR 0001, forge#28): validating nodes are declared as
    # process data under `opencode.nodes`, each carrying its contract — kind, fresh
    # context, read surface, cap. Every load-bearing rule below is fail-closed: a
    # mis-declared graph refuses to emit, exactly as a mis-declared role did before.
    graph = oc.get("nodes") or {}

    # Safe upgrade path (the package is distributed via a brew tap — an org upgrades
    # by re-running the generator over its existing config): a pre-#28 config carries
    # the retired `opencode.subagents` cast and no `nodes`. MIGRATE it, mechanically
    # and losslessly, rather than hard-fail with no path forward. The graph wins when
    # both are present (the cast block is dead config, not a conflict).
    if not graph and oc.get("subagents"):
        graph = migrate_subagents_to_nodes(cfg, oc["subagents"])
        print("emit: opencode.subagents is retired (ADR 0001) — migrated to "
              "opencode.nodes. Delete the subagents block and declare the graph "
              "directly; the migration is lossless but will be removed in a future "
              "release.", file=sys.stderr)

    require(isinstance(graph, dict) and graph,
            "opencode.nodes is required — the graph's validating nodes are declared "
            "here as data (the fixed role cast is gone; ADR 0001). A pre-#28 config "
            "with opencode.subagents is migrated automatically; any other config must "
            "declare the graph.")
    # The model policy is validated at EMIT time, not discovered at run time: a node
    # pin or the org floor that is off-provider or banned does not emit (the glm-5.3
    # balance incident + the astra retention failure are the evidence — a run with no
    # explicit model inherits the host default, which can be banned or rejected).
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
        # A node pin must be a FULL provider/model ref — a bare model id silently
        # inherits whatever provider the host resolves, which is the fail-open the
        # policy exists to close. (The org floor in opencode.model is assembled from
        # provider+model by the emit itself, so it is always full.)
        require(ref_prov == prov_id,
                f"{where}: model {ref!r} is off-provider — the org's only provider is "
                f"{prov_id!r} and a node pin must name it explicitly "
                f"(a run with no explicit model inherits the host default; the policy "
                f"is enforced at definition time, not run time)")
        hit = next((b for b in banned_models if b in ref_model.lower()), None)
        require(not hit,
                f"{where}: model {ref!r} is banned by the org's model policy ({hit})")

    for name, node in graph.items():
        require(isinstance(node, dict),
                f"opencode.nodes.{name} must be a mapping (the node's contract)")
        kind = node.get("kind")
        require(kind in ("produce", "validate"),
                f"opencode.nodes.{name}.kind must be produce|validate (got {kind!r})")
        cap = node.get("max_steps")
        require(isinstance(cap, int) and cap > 0,
                f"opencode.nodes.{name}.max_steps must be a positive int — a node with "
                f"no declared cap does not emit (silence is fail-open)")
        if node.get("model"):
            check_model_ref(node["model"], f"opencode.nodes.{name}.model")
        if kind == "validate":
            require(node.get("fresh_context") is True,
                    f"opencode.nodes.{name}.fresh_context must be true — a validating "
                    f"node that shares its produce node's context does not emit "
                    f"(no-self-review is a property of the node)")
            surface = node.get("read_surface")
            require(isinstance(surface, list) and surface,
                    f"opencode.nodes.{name}.read_surface must be a NON-EMPTY list — a "
                    f"validating node with no read-only contract does not emit")
            bad = sorted(set(str(a).lower() for a in surface) & set(OC_FORBIDDEN_IN_READONLY_ALLOW))
            require(not bad,
                    f"opencode.nodes.{name}.read_surface carries write/delegate "
                    f"capabilities {bad} — a validating node is read-only by contract "
                    f"(forbidden: {OC_FORBIDDEN_IN_READONLY_ALLOW})")

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

    # The validating-node deny set, DERIVED from the union of the graph's read
    # surfaces — one deny set applied at dispatch time to any validating run,
    # whatever agent occupies the node (ADR 0001: the boundary attaches to the node).
    validate_surface = sorted({str(a).lower() for n in graph.values()
                               if n.get("kind") == "validate" for a in n.get("read_surface", [])})
    validate_deny = derived_deny(validate_surface)
    for cap in ("edit", "bash", "task", "dispatch"):
        require(cap in validate_deny,
                f"opencode.nodes: the validating nodes' derived deny set is missing "
                f"{cap!r} — a validating run must never keep write/exec/delegate")

    ttype = cfg["tracker"]["type"]
    adapter_text = (FORGE_ROOT / f"adapters/tracker/{ttype}.md").read_text()
    try:
        block = extract_snippet(adapter_text, "TRACKER_READONLY_COMMANDS", {})
    except SystemExit:
        raise SystemExit(f"emit: tracker adapter '{ttype}' has no TRACKER_READONLY_COMMANDS "
                         f"section — the opencode target needs it to grant read-only roles "
                         f"their tracker reads (adapters with the full set: jira-acli, github)")
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

    # The validating agent's frontmatter model: the deepest validating node's pin when
    # one is declared (a validating run never runs shallower than its deepest node),
    # else the org floor. Definition-time, never the host default.
    validate_pins = [n["model"] for n in graph.values()
                     if n.get("kind") == "validate" and n.get("model")]
    validate_model = validate_pins[0] if validate_pins else default_ref
    if "/" not in validate_model:
        validate_model = f"{model_provider}/{validate_model}"

    b["scalars"].update({
        "HOST_NOUN": "an opencode configuration",
        "HOST_DISPATCH_NOUN": "the task tool",
        "OC_DEFAULT_MODEL_REF": default_ref,
        "OC_SMALL_MODEL_REF": small_ref,
        "OC_VALIDATE_MODEL_REF": validate_model,
        "OC_PROVIDER_ID": prov["id"],
        "OC_PRIMARY_AGENT": oc.get("primary_agent", "build"),
        # The validating-node contract, rendered for the dispatch machinery and the
        # preamble: one deny set, applied at session create to any validating run.
        "OC_VALIDATE_DENY_LIST": ", ".join(c for c in validate_deny if c != "bash"),
        "OC_VALIDATE_STEPS": str(min(n["max_steps"] for n in graph.values()
                                     if n.get("kind") == "validate")),
        "OC_PRODUCE_STEPS": str(min((n["max_steps"] for n in graph.values()
                                     if n.get("kind") == "produce"), default=120)),
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
    # command/ and skill/ ARE verb-named; agent/ carries exactly ONE file (the
    # validating agent, Path B) whose name is fixed by the native tool's
    # subagent_type — there is no cast to rename (ADR 0001).
    renames = rename_verbs(out, resolve_verbs(cfg), skills_dir="skill",
                           agents_dir=None, commands_dir="command")
    sc = bindings["scalars"]

    # Post-render assertions on the artifact itself, not on the config.
    conf = json.loads((out / "opencode.json").read_text())
    require(conf.get("enabled_providers") == [sc["OC_PROVIDER_ID"]],
            f"opencode.json enabled_providers must be exactly "
            f"[{sc['OC_PROVIDER_ID']!r}] — the allowlist is the only-Bedrock "
            f"control that survives an ambient ANTHROPIC_API_KEY/OPENAI_API_KEY "
            f"(got {conf.get('enabled_providers')!r})")
    require(int(conf.get("subagent_depth", 1)) >= 2,
            f"opencode.json subagent_depth must be >= 2 — a workflow agent (depth 1) "
            f"spawns its validating nodes as native subagents (depth 2); the default "
            f"of 1 would hard-error the review node (got {conf.get('subagent_depth')!r})")

    # Path B (forge#28): the validating agent file is the native path's contract, and
    # the org config's `task` rule allowlists exactly the spawnable set — a typo'd
    # subagent_type must never fall back to the full-permission primary agent.
    require((out / "agent" / "validate.md").is_file(),
            "agent/validate.md — the contract-carrying validating agent — was not "
            "rendered; the native path has no contract to derive from")
    task_perm = (conf.get("permission") or {}).get("task")
    require(isinstance(task_perm, dict)
            and task_perm.get("*") == "deny"
            and task_perm.get(sc["OC_PRIMARY_AGENT"]) == "allow"
            and task_perm.get("validate") == "allow",
            f"opencode.json permission.task must allowlist exactly the spawnable set "
            f"({sc['OC_PRIMARY_AGENT']!r} + 'validate') under a '*': deny — got "
            f"{task_perm!r}")
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
