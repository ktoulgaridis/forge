---
description: Generate a standalone, org-owned Claude Code plugin (the org's agent harness) from .forge.org.yaml. Reads the org interview, renders templates/org-plugin/, and validates that ZERO generator identity leaked into the output.
---

# /forge:emit — Emit an org-owned agent harness

The generative entry point of forge v2. `/forge:new` opens a project; **`/forge:emit`
mints the org's package**: a standalone Claude Code plugin that aligns the harness to
how *this* org works, owned entirely by the org.

> **The cardinal rule.** The emitted package is **org-owned**. forge's identity —
> the name "forge", the maintainer, the upstream repo URL — must **never** appear in
> the output. The org installs and distributes its package as its own; forge is the
> mill, not a runtime dependency. Step 5 below *fails the emit* if any generator
> identity leaks through.

## Invocation

```
/forge:emit [--config <path>] [--out <dir>]
```

- `--config` — the org-tier config. Defaults to `./.forge.org.yaml`
  (see `.forge.org.example.yaml` for the shape).
- `--out` — where to write the package. Defaults to `../<plugin.name>`.

## What this command does

### Run it

The whole pipeline below is implemented by the **shared renderer** — the same
engine `/forge:new` uses (`lib/render.py`), driven for the org tier by `lib/emit.py`:

```bash
uv run --with pyyaml python lib/emit.py \
  --config .forge.org.yaml --out ../<plugin.name>
```

`lib/emit.py` performs steps 1–5; step 6 is `claude plugin validate`. Read on for
what each step guarantees (and what to do when one fails).

### 1. Load + validate the org config

`lib/emit.py` reads `.forge.org.yaml` and requires: `org.name`/`org.slug`, the full
`plugin:` identity block (name, version, description, author.name, author.url,
homepage, license), `org_wiki:` (incl. `prime_reads`), `tracker:`, and `agents:`. If
any identity field is missing or still carries an example value (`acme`, `Acme`,
`janedoe`, `example`), it **stops** — never emit with placeholder identity.

It refuses to emit if `operating_model.cross_project_truth_adjudicator` is unset
**and** `capture_default` is `always-on` (default-deny: don't auto-promote
cross-project knowledge with no declared adjudicator).

### 2. Build the substitution map

`build_bindings()` maps org config → template placeholders:

| Placeholder | Source |
|---|---|
| `{{ORG_NAME}}` | `org.name` |
| `{{PLUGIN_NAME}}` | `plugin.name` |
| `{{PLUGIN_VERSION}}` | `plugin.version` |
| `{{PLUGIN_DESCRIPTION}}` | `plugin.description` |
| `{{PLUGIN_AUTHOR_NAME}}` | `plugin.author.name` |
| `{{PLUGIN_AUTHOR_URL}}` | `plugin.author.url` |
| `{{PLUGIN_HOMEPAGE}}` | `plugin.homepage` |
| `{{PLUGIN_LICENSE}}` | `plugin.license` |
| `{{ORG_WIKI_NAME}}` | `org_wiki.name` |
| `{{ORG_WIKI_REMOTE}}` | `org_wiki.remote` |
| `{{ORG_WIKI_PATH_ENV}}` | `org_wiki.local_path_env` |
| `{{ORG_WIKI_DEFAULT_PATH}}` | `org_wiki.default_local_path` |
| `{{PRIME_READS}}` | `org_wiki.prime_reads[]` (array section) |
| `{{AGENT_IMPLEMENTER_MODEL}}` | `agents[name=implementer].model` |
| `{{AGENT_REVIEWER_MODEL}}` | `agents[name=reviewer].model` |
| `{{AGENT_GATE_MODEL}}` | `agents[name=gate].model` |
| `{{TRACKER_*_SNIPPET}}` | inlined from `adapters/tracker/<tracker.type>.md` (prime / view / comment / create-task / gate) |

### 3. Render `templates/org-plugin/` → `--out`

`render_tree()` (in `lib/render.py`, the **shared** engine) does `{{VAR}}`
substitution, `{{#array}}…{{/array}}` repeats, conditional sections, and
adapter-snippet inlining. Emit differs from `/forge:new` only in *source tree*
(`templates/org-plugin/`) and *config source* (`.forge.org.yaml`); the engine is
identical. Each `*.template` renders to the mirrored path under `--out` with the
`.template` suffix dropped. It asserts **no unresolved `{{...}}`** survive.

This produces:

```
<out>/
  .claude-plugin/plugin.json     (org identity; skills auto-loaded, agents auto-discovered)
  README.md                      (neutral harness front-door doc)
  skills/{prime,refine,execute,handoff}/SKILL.md
  agents/{implementer,reviewer,gate}.md
```

Note: `agents/` **and** `hooks/hooks.json` are **auto-discovered** by Claude Code — the
manifest must declare neither. Declaring `"hooks": "./hooks/hooks.json"` double-loads it
(the standard path is already loaded automatically) and fails at runtime even though
`--strict` validate passes; the manifest `hooks` field is only for *additional* hook
files. The harness doc is `README.md` (plugin-root `CLAUDE.md` is not loaded as install
context, so it would only draw a `--strict` warning).

### 4. Handle the org wiki (never clobber a live brain)

If `org_wiki.exists: true`, **do not stamp a wiki** — the harness only points at it.
If `false`, seed the org-wiki skeleton (operating-model.md + CLAUDE.md schema) for the
org to fill in. Either way, the emitted plugin reads the wiki at runtime.

### 5. Leak gate — FAIL emission on any generator identity (mandatory)

`render_tree(..., leak_check=True)` scans every rendered line and **aborts** (exit 3)
if it finds the generator's identity — `\bforge\b` (word-boundary, so legit English
like "fire-and-forget" is fine), `ktoulgaridis`, or `toulgaridis`. The package is
never written when this trips. The word "forge" appearing in the *generator's*
templates is fine; it must be **zero** in the *emitted output*. If an org legitimately
needs a token like "forge" in its own name, spell it in `.forge.org.yaml` and narrow
the gate to whitelist that exact string.

The unresolved-placeholder assertion (step 3) already guarantees no leftover `{{...}}`
remain, so the emitted `plugin.json` `author`/`homepage` are fully org-substituted.

### 6. Validate the plugin

```bash
claude plugin validate --strict "$OUT"
```

### 7. Print next steps

```
✓ Emitted <plugin.name> v<version> to <out>
✓ Leak gate: clean (no generator identity in output)
✓ claude plugin validate --strict: passed

Next:
  - Review the package; it is yours to own and version.
  - Distribute via your internal marketplace (<plugin.homepage>).
  - In a work session: install it, then /<plugin.name>:prime <ticket>.
```

## Reuse note

`/forge:emit` is deliberately thin. The heavy lifting — substitution, array repeats,
conditionals, adapter-snippet inlining, the unresolved-placeholder assertion, the leak
gate — is `lib/render.py`'s `render_tree(bindings, templates_dir, out_dir, forge_root,
leak_check)`. That is the **single engine**, with two drivers:

- `/forge:new` → builds project-tier bindings, calls `render_tree` over `templates/wiki/`.
- `/forge:emit` → `lib/emit.py` builds org-tier bindings, calls `render_tree` over
  `templates/org-plugin/` with `leak_check=True`.

The engine is dependency-free stdlib; `lib/emit.py` adds only PyYAML
(`uv run --with pyyaml`). Re-emitting the same config produces byte-identical output.

## Failure modes

- **Identity still example-valued** → stop; the org must fill in `.forge.org.yaml`.
- **Leak gate trips** → a template hardcoded generator identity; fix the *template*
  (parameterize it), never patch the output.
- **`claude plugin validate` fails** → fix the manifest template and re-emit.
- **`org_wiki.exists: true` but unreachable** → emit the plugin anyway (it reads the
  wiki at runtime), but warn the org to clone/set the wiki path.
