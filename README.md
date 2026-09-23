# forge

**Align Claude Code — and opencode — to your org and its operational model.**

[![validate](https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml/badge.svg)](https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml) [![release](https://img.shields.io/github/v/release/ktoulgaridis/forge)](https://github.com/ktoulgaridis/forge/releases) [![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

forge is a **generator, not a scaffolder**. It interviews your organization — which tools you run, which process shape you're held to, and *how your org actually works* (how agents communicate, under what identity they act, what gates and autonomy govern them) — and **emits a standalone, org-owned harness** that makes agent-driven development behave like a member of *your* org.

Two levels, deliberately separate:

| Tier | What it is | Who owns it |
|---|---|---|
| **forge** (this repo) | The shared generator: adapters, method, operating-model facets, runtime templates | Everyone, upstream |
| **`acme-forge`** (the emit) | Your harness: your tools, your operating model, your compliance regime — baked in | Your org |

`forge@Acme ≠ forge@Globex` **by design** — same generator, different answers to the interview. **Nobody forks forge.** To upgrade, an org re-runs the generator over its `.forge.org.yaml` and re-emits.

> The full v2 design lives in [`docs/GENERATOR.md`](docs/GENERATOR.md) — the authoritative north star.

## One config, two hosts

`/forge:emit` reads one `.forge.org.yaml` and emits either:

- **A Claude Code plugin** (`--target claude-code`, the default) — skills + agents + hooks + a marketplace manifest, validated and ready to install.
- **An opencode configuration** (`--target opencode`) — `opencode.json` + `agent/` + `command/` + `skill/` + `rubric/` + `node/` + `plugin/dispatch.js`. The orchestrator's one primitive is `dispatch({ agent, ticket, repo?, model?, variant?, task_id?, command? })`: it launches only the workers the graph catalog declares, the ticket is the whole envelope, N calls per turn run in parallel, `task_id` continues the same worker, a worktree worker gets one git worktree per (repo, ticket), and the `<run-closed>` postback carries the worker's RESULT line.

**The opencode artifact is back/forward compatible by construction.** One emitted package runs unchanged on opencode **1.18.29+** and **2.x**:

- the emitted plugins carry both host entrypoints — 2.x loads `setup()`, 1.18.29+ loads `server()` — driving the same role allowlist, model policy and read-only boundary;
- the rest of the layout (`agent/`, `command/`, `skill/`, `opencode.json`) is natively understood by both hosts; 2.x translates the 1.x `permission` block automatically (`task` → `subagent`, `bash` → `shell`);
- `emit` detects the installed opencode and refuses hosts below the floor;
- known 2.x gaps, documented in the emitted package: `instructions` entries are not loaded (its `AGENTS.md` carries the same pointers) and the session-start toast nudge is 1.x-only until a 2.x TUI plugin ships.

## What an emit contains

1. The org's **pinned adapters** (tracker / SCM / chat / CI) — chosen once at the org tier, not re-chosen per project.
2. The **operating model** — rendered from the interview into a constitutional wiki chapter + machine-checkable permission blocks.
3. The **org brain seed** — one durable wiki (operating model + accumulating tribal knowledge) with a project layer (`projects/<codename>/`).
4. The **graph catalog** (`graphs:`, ADR 0019) — named graphs, each its own **worker** agent (a bounded graph-agent that walks its nodes in one context and ends every run with one RESULT line — the build graph's worker is `builder`) or walked by the engineer's **main thread** (e.g. refine, with human `gate:` nodes). Node-sets, loop caps (`max_visits`) and host caps (`maxTurns` / `steps`) are data; emit refuses an uncapped loop, an unreachable node, a verb as a worker node skill, a worker named like a host built-in, and a leftover single `graph:` block. See [`examples/graph-catalog.forge.org.yaml`](examples/graph-catalog.forge.org.yaml).
5. The **verbs** — `prime · intro · setup · inception · refine · execute · triage · wiki · handoff` (renamable per org) as commands + the skills each command reads. `triage` emits only when a worker graph binds it.

## Lifecycle: generate, distribute, re-generate

1. **Generate** — `/forge:emit` interviews the org and writes the standalone package, validated.
2. **Distribute** — publish the package internally (private registry, Git host, or vendored). Teams install it; agent-driven development across the org converges on one operating model, one set of role boundaries, one wiki schema.
3. **Re-generate to upgrade** — when the generator improves upstream, re-run it over the existing config. It rebases your org's choices onto the newer generator. No fork to maintain, no drift.

## Install

```bash
/plugin marketplace add ktoulgaridis/forge
/plugin install forge@forge
```

## Use

```bash
# 1. In the GENERATOR (this repo): emit your org's package
claude
> /forge:emit
# → interviews your org: tools, methodology, operating model, identity, gates
# → writes a standalone org-owned package, validated

# 2. Distribute the package internally, then inside it:
> /forge:new acme-platform-rebuild    # opens a project subspace in the org brain
> /forge:doctor                      # verifies CLIs + MCPs + operating-model invariants
```

The deterministic engine behind the command runs directly:

```bash
uv run --with pyyaml python lib/emit.py --config <.forge.org.yaml> --out <dir> \
    [--target claude-code|opencode]
```

## Method (in brief)

forge is opinionated about **how** agents work together, unopinionated about **which tools** they use (the adapters) and **how each org works** (the operating model, read from the wiki at runtime):

- **Karpathy schema** — raw sources / wiki / schema, federated across an org-wide layer and per-project subspaces; code-as-truth holds at both.
- **Graph-agents, not a cast** — the emitted harness ships one agent per worker graph (`builder` for build, `triager` for triage) plus the optional read-only `validate` reviewer. Main-thread graphs (e.g. refine) run in the engineer's own session.
- **One orchestrator, one worker per task** — the engineer's session dispatches one graph-agent per ready task; the worker reviews its own diff as a self-check node, the human merge gate + CI are the independent review, and the optional read-only reviewer may check a completed PR. The durable substrate (org brain + tracker + SCM) survives crashes.
- **Wiki role templates** — `/forge:new` seeds a project wiki with six role pages (`templates/wiki/roles/`: orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst) and its own `prime` / `dispatch` / `wiki` skills. These are wiki content for the project tier. The emitted harness does not run them as agents.

Full method: [`docs/METHOD.md`](docs/METHOD.md) · roles: [`docs/ROLES.md`](docs/ROLES.md) · sessions: [`docs/SESSIONS.md`](docs/SESSIONS.md) · usage: [`docs/USAGE.md`](docs/USAGE.md).

## Adapters

| Layer | Shipped | Planned | Out of scope |
|---|---|---|---|
| Tracker | github · jira-acli · jira-mcp · jira-multi · jira-single · gitlab · linear | asana | Notion / ClickUp / Monday |
| SCM | github · gitlab | bitbucket | — |
| Chat | slack | teams | discord (a "maybe later") |
| CI | — | github-actions · gitlab-ci | circleci, jenkins |
| Cloud | informational only — forge doesn't provision | — | azure / aws / gcp provisioning |

Stay-in-scope adapters get full skill snippets + doctor checks + working examples. Out-of-scope adapters are not added speculatively. Adapter contract: [`docs/ADAPTERS.md`](docs/ADAPTERS.md).

## Status

v0.9.6 — early, opinionated, working but incomplete.

- ✅ `/forge:emit` — the generator entry point: interview → deterministic emit → validation, with a leak gate (zero generator identity in output) and fail-closed controls (a "read-only" role with a write-capable allow-list fails the emit, not the org)
- ✅ Two emit targets from one config: Claude Code plugin + opencode configuration
- ✅ The graph catalog (`graphs:`, ADR 0019): worker graphs (build → `builder`, triage → read-only `triager`) and main-thread graphs (refine, with human gates), linted fail-closed
- ✅ Read-only code access for a read-only worker (`code: read`): search + git history through a shell each host walls to the declared commands (opencode permission patterns; a Claude Code PreToolUse gate keyed on the worker's agent type) — [`docs/notes/read-only-code-surface.md`](docs/notes/read-only-code-surface.md)
- ✅ Emitted READMEs list exactly what the package ships; the opencode README leads with the org's Homebrew install when `opencode.distribution.homebrew` is set
- ✅ Back/forward-compatible opencode artifact (1.18.29+ and 2.x, one package) with host-version detection
- ✅ Method documented (METHOD / ROLES / SESSIONS / USAGE / ADAPTERS / BOOTSTRAP); project-wiki templates incl. the six role pages; `wiki lint --consolidate`
- ✅ Test suite: emit golden tests + behavioural tests for the emitted `dispatch` tool on both host entrypoints

## Roadmap

In implementation order:

1. **Org-brain templates** — org-wiki schema + operating-model chapter + the `learnings` capture contract with a context-isolated harvest.
2. **Methodology bundles** — Scrum, Kanban (default), RFC-first, and **Formal-methods / V-model** (must-have for regulated shops; USER-NEED → REQUIREMENT → SPEC → VERIFICATION → VALIDATION with traceability + audit gates; sub-variants for IEC 62304, DO-178C, ISO 26262). Composable *with* the operating model.
3. **CI adapters: github-actions, gitlab-ci** — skill snippets + sample pipeline templates.

## Reference engagements

- [examples/socwave.md](examples/socwave.md) — SocWave platform rebuild (gitlab.example.com + Azure)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions (commits, versioning, releases) and the generator-vs-package boundary: improvements to the shared generator land here; an org tailoring its own package re-runs the generator instead.
