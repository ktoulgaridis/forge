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
- **An opencode configuration** (`--target opencode`) — `opencode.json` + `agent/` + `command/` + `skill/` + `plugin/dispatch.js`. The orchestrator's one primitive is `dispatch(role, ticket, repo?, model?, task_id?, command?, background?)`: the ticket is the whole envelope, N calls per turn run in parallel, `task_id` continues the same troop (cyclic implement → review → fix loops), writers get a worktree per repo under one workspace, and read-only roles run only the tracker's read commands.

**The opencode artifact is back/forward compatible by construction.** One emitted package runs unchanged on opencode **1.18.29+** and **2.x**:

- the emitted plugins carry both host entrypoints — 2.x loads `setup()`, 1.18.29+ loads `server()` — driving the same role allowlist, model policy and read-only boundary;
- the rest of the layout (`agent/`, `command/`, `skill/`, `opencode.json`) is natively understood by both hosts; 2.x translates the 1.x `permission` block automatically (`task` → `subagent`, `bash` → `shell`);
- `emit` detects the installed opencode and refuses hosts below the floor;
- known 2.x gaps, documented in the emitted package: `instructions` entries are not loaded (its `AGENTS.md` carries the same pointers) and the session-start toast nudge is 1.x-only until a 2.x TUI plugin ships.

## What an emit contains

1. The org's **pinned adapters** (tracker / SCM / chat / CI) — chosen once at the org tier, not re-chosen per project.
2. The **operating model** — rendered from the interview into a constitutional wiki chapter + machine-checkable permission blocks.
3. The **org brain seed** — one durable wiki (operating model + accumulating tribal knowledge) with a project layer (`projects/<codename>/`).
4. The **role archetypes** — implementer / reviewer / gate; the validating roles are read-only by construction, and no-self-review is enforced by context isolation, not convention.
5. The **verbs** — `prime · intro · setup · inception · refine · execute · wiki · handoff` (renamable per org) as commands + the skills each command reads.

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
- **Six role archetypes** — orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst.
- **Three skill verbs** — `prime` (calibrate), `dispatch` (invoke a role), `wiki` (propose / ingest / lint / query).
- **No-self-review** — the reviewer sees the diff, never the implementer's reasoning; context isolation, not separate terminals.
- **One orchestrator + dynamic workflows** — a single long-lived orchestrator spawns the work; the durable substrate (org brain + tracker + SCM) survives crashes.

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

v0.7.2 — early, opinionated, working but incomplete.

- ✅ `/forge:emit` — the generator entry point: interview → deterministic emit → validation, with a leak gate (zero generator identity in output) and fail-closed controls (a "read-only" role with a write-capable allow-list fails the emit, not the org)
- ✅ Two emit targets from one config: Claude Code plugin + opencode configuration
- ✅ Back/forward-compatible opencode artifact (1.18.29+ and 2.x, one package) with host-version detection
- ✅ Method documented (METHOD / ROLES / SESSIONS / USAGE / ADAPTERS / BOOTSTRAP); wiki templates; 6 role archetypes; skill verbs incl. `wiki lint --consolidate`
- ✅ Test suite: emit golden tests + behavioural tests for the emitted `dispatch` tool on both host entrypoints

## Roadmap

In implementation order:

1. **Org-brain templates** — org-wiki schema + operating-model chapter + the `learnings` capture contract + reference `ship-ticket.js` workflow with a context-isolated harvest phase.
2. **Methodology bundles** — Scrum, Kanban (default), RFC-first, and **Formal-methods / V-model** (must-have for regulated shops; USER-NEED → REQUIREMENT → SPEC → VERIFICATION → VALIDATION with traceability + audit gates; sub-variants for IEC 62304, DO-178C, ISO 26262). Composable *with* the operating model.
3. **CI adapters: github-actions, gitlab-ci** — skill snippets + sample pipeline templates.

## Reference engagements

- [examples/socwave.md](examples/socwave.md) — SocWave platform rebuild (gitlab.example.com + Azure)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions (commits, versioning, releases) and the generator-vs-package boundary: improvements to the shared generator land here; an org tailoring its own package re-runs the generator instead.
