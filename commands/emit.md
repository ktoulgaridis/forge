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
/forge:emit [--config <path>] [--out <dir>] [--target {claude-code,opencode}]
```

- `--config` — the org-tier config. Defaults to `./.forge.org.yaml`
  (see `.forge.org.example.yaml` for the shape).
- `--out` — where to write the package. Defaults to `../<plugin.name>`.
- `--target` — the host to package for. Defaults to `claude-code` (a Claude Code plugin:
  `skills/` + `agents/` + `hooks/` + `.claude-plugin/`). `opencode` emits an opencode
  configuration (`opencode.json` + `agent/` + `command/` + `skill/` + `plugin/dispatch.js`) from the **same**
  config and requires the `opencode:` block. The skill bodies are shared byte-for-byte
  across targets except at the `{{#TARGET_*}}` conditionals and the host-noun scalars.

## Step 0 — the interview (when there is no `.forge.org.yaml` yet)

The org's answers ARE the product. Ask them once, conversationally, one topic at a
time, and write `.forge.org.yaml`. Every question has a sane default; say the default,
let the engineer accept or change it, never assume. Then continue with "Run it".

| Topic | Ask | Default |
|---|---|---|
| Identity | org name/slug, package name, author, homepage, license | derived from the org name |
| Host(s) | Claude Code, opencode, or both | the host this interview runs in |
| Provider + model | the ONE provider id to allowlist and the default model | what the current session runs on |
| Model policy | banned models, floor | none banned; floor = default model |
| Tracker | github / jira-acli (full snippet set, both hosts); gitlab / jira-mcp / linear (Claude Code target only until they carry the nine `TRACKER_*` snippets incl. `TRACKER_READONLY_COMMANDS`) | the SCM's own issues |
| SCM | github / gitlab | the tracker's host |
| Wiki | exists? path env + default path; which pages prime reads | `<org>-wiki` next to the workspace; operating-model.md + CLAUDE.md |
| Methodology | kanban / scrum / rfc-first / formal-methods (V-model) bundle | kanban |
| Verbs | rename any of the nine | canonical names |
| Graphs | the graph catalog (`graphs:`): each graph's verb, launch (worker / main_thread), isolation, tools, cap and node-set | `build` (worker `builder`) from `examples/graph-catalog.forge.org.yaml` |
| Operating model | comms, identity, gates, autonomy, capture default | trigger-gated capture, no auto-promotion |
| Distribution (opencode) | how engineers install the bundle: a Homebrew tap + formula (+ its installer CLI, which must provide `install`/`update`/`doctor`) → `opencode.distribution.homebrew: {tap, formula, cli?}`; documentation only | none — the README documents a manual copy |

Provider credentials, regions and profiles are never asked and never written: they are
the host's (`opencode auth login`, `provider.<id>.options`).

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
homepage, license), `org_wiki:` (incl. `prime_reads`), `tracker:`, `graphs:` and
`supplementary_reviewer:`. A leftover `graph:` or `agents:` key (forge ≤ 0.8) **stops**
with the exact migration (the 0.9.0 hard cut, ADR 0019). If
any identity field is missing or still carries an example value (`acme`, `Acme`,
`janedoe`, `example`), it **stops** — never emit with placeholder identity.

**The graph catalog is fail-closed.** Emit refuses: a loop with no `max_visits` node; a
node unreachable from `entry`; a graph with no terminal; an unknown node skill (they live
in `templates/node-skills/`; a main-thread node may name its own verb) or rubric (any
`templates/org-plugin/rubrics/*.md.template` — discovered by glob, no registry) or check
(`verify`); a rubric node with no FAIL edge (`next`); a check node without both its pass
(`terminal`) and fail (`next`) edges; an execute worker whose graph has no `check: verify`
node, or whose emitted verify gate (Claude Code hook / opencode plugin) does not name it;
`gate:` in a worker; a verb as a worker node skill; an entry preload that sets
`disable-model-invocation`; a worker named like a Claude Code or opencode built-in
(`build`, `general`, `explore`, `compaction`, `title`, `summary`, `plan`, `Explore`,
`Plan`, `general-purpose`, `claude`, `statusline-setup`, `claude-code-guide`), `validate`,
or the opencode `primary_agent`; two graphs binding one verb; an unknown graph or node key;
a worker `allow:` granting fan-out; a banned worker model pin; a worker graph with no
body template (`templates/graphs/<graph>/agent.md.template`).

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
| `{{BUILD_AGENT}}` | the agent of the worker graph bound to `execute` (`builder`) |
| `{{RESULT_LINE}}` | the one result-line format every worker ends with |
| `{{GRAPH_*}}` | per graph, in the per-graph render loop only (agent file + index skill) |
| `{{VERIFY_GATE_*}}` | the verify gate: the agents whose PR create it checks (from each worker graph with `check: verify`), its per-run bound and the hook timeout |
| `{{TRACKER_*_SNIPPET}}` | inlined from `adapters/tracker/<tracker.type>.md` as ONE fenced block (a template that already fenced the placeholder keeps its fence) |

### 3. Render `templates/org-plugin/` → `--out`

`render_tree()` (in `lib/render.py`, the **shared** engine) does `{{VAR}}`
substitution, `{{#array}}…{{/array}}` repeats, conditional sections, and
adapter-snippet inlining. Emit differs from `/forge:new` only in *source tree*
(`templates/org-plugin/`) and *config source* (`.forge.org.yaml`); the engine is
identical. Each `*.template` renders to the mirrored path under `--out` with the
`.template` suffix dropped. It asserts **no unresolved `{{...}}`** survive.

Then the **per-graph render loop** (ADR 0019) renders, for every graph, its T1 index
skill (`templates/graphs/index/` → `skills/<graph>-graph/` for a worker, `nodes/<graph>-graph.md`
for a main-thread graph) and the node skills it binds (`templates/node-skills/<name>/` →
`skills/<name>/` for a worker's entry node, `nodes/<name>.md` otherwise), and for every **worker** graph its
own body template (`templates/graphs/<graph>/agent.md.template` → `agents/<agent>.md`).
A `check:` node renders its node file (`templates/checks/<name>.md.template` →
`nodes/check-<name>.md`), and the `verify` check's script
(`templates/checks/verify-gate.py.template`) renders beside its host wrapper:
`hooks/scripts/verify-gate.{sh,py}` (a PreToolUse hook on Bash) on Claude Code,
`plugin/verify.js` + `plugin/verify-gate.py` on opencode. Emit then asserts, on the
artifact, that the gate names exactly the verify-gated worker(s) and, on Claude Code, that
hooks.json runs it with a timeout above two bounded test runs.
Each emitted worker is re-checked on the artifact: it preloads only its index + entry
node (never a verb skill), `maxTurns` equals its `max_total_steps`, and it carries no
fan-out tool. This produces:

```
<out>/
  .claude-plugin/plugin.json     (org identity; skills auto-loaded, agents auto-discovered)
  README.md                      (neutral harness front-door doc)
  skills/<verb>/SKILL.md         (the org's verbs)
  skills/<graph>-graph/SKILL.md  (each worker graph's index) + skills/<entry>/SKILL.md (its entry node)
  nodes/*.md                     (every other node + each main-thread graph's index, read by path)
  agents/<agent>.md              (one per worker graph: builder, triager, …) + agents/validate.md (optional reviewer)
  rubrics/*.md                   (every rubric template: review, gate, agent-ready, diagnosis, …)
```

On `--target opencode` the same catalog emits `agent/<agent>.md` per worker (`steps` =
its cap; `dispatch`/`subagent`/`task`/`question` denied), `rubric/`, the index + node
skills under `skill/`, and a `plugin/dispatch.js` whose `WORKERS` table is exactly the
catalog's workers (re-checked post-render).

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
