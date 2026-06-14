#!/usr/bin/env python3
"""Driver for /forge:emit — turn a .forge.org.yaml into an org-owned plugin.

Computes the org-tier bindings from the config, then calls the SHARED renderer
(lib/render.py) with the leak gate on. This is the deterministic engine behind
the /forge:emit command; the command doc is the human-facing procedure.

Usage:
  uv run --with pyyaml python lib/emit.py --config <.forge.org.yaml> --out <dir>
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_tree  # noqa: E402

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
        },
        "arrays": {"PRIME_READS": wiki["prime_reads"]},
        "conditionals": {},
        "snippets": [
            {"placeholder": p, "adapter": adapter, "label": p, "vars": snippet_vars}
            for p in ("TRACKER_PRIME_SNIPPET", "TRACKER_VIEW_ISSUE_SNIPPET",
                      "TRACKER_COMMENT_LIST_SNIPPET", "TRACKER_COMMENT_SNIPPET",
                      "TRACKER_CREATE_TASK_SNIPPET", "TRACKER_BACKLOG_SNIPPET",
                      "TRACKER_GATE_SNIPPET", "TRACKER_DOCTOR_SNIPPET")
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge emit driver")
    ap.add_argument("--config", default=".forge.org.yaml")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    bindings = build_bindings(cfg)
    out = Path(args.out)
    rendered = render_tree(
        bindings,
        FORGE_ROOT / "templates/org-plugin",
        out,
        FORGE_ROOT,
        leak_check=True,
    )

    # Rename emitted skill dirs / the gate agent file to the org's verb names. The
    # templates ship canonical (skills/inception, agents/gate.md); the org's `name:`
    # frontmatter is already org-rendered via {{VERB_*}}, so the invocable name is
    # correct regardless — but renaming the paths keeps the OUTPUT tidy and matching.
    verbs = resolve_verbs(cfg)
    renames = 0
    for canon, name in verbs.items():
        if name == canon:
            continue
        sd = out / "skills" / canon
        if sd.is_dir():
            sd.rename(out / "skills" / name)
            renames += 1
    # the gate verb is also an agent file
    gate_name = verbs["gate"]
    if gate_name != "gate":
        gf = out / "agents" / "gate.md"
        if gf.is_file():
            gf.rename(out / "agents" / f"{gate_name}.md")
            renames += 1

    print(f"OK emitted {cfg['plugin']['name']} v{cfg['plugin']['version']} "
          f"→ {args.out} ({len(rendered)} files, {renames} verb renames)")
    print("leak gate: clean (no generator identity in output)")


if __name__ == "__main__":
    main()
