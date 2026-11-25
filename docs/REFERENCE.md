# forge reference

The detail behind the [README](../README.md). The full design is [`GENERATOR.md`](GENERATOR.md).

## What an emit contains

1. The org's **pinned adapters** (tracker / SCM / chat / CI) — chosen once at the org tier, not re-chosen per project.
2. The **operating model** — rendered from the interview into a constitutional wiki chapter + machine-checkable permission blocks.
3. The **org brain seed** — one durable wiki (operating model + accumulating tribal knowledge) with a project layer (`projects/<codename>/`).
4. The **graph catalog** (`graphs:`, ADR 0019) — named graphs, each its own **worker** agent (a bounded graph-agent that walks its nodes in one context and ends every run with one RESULT line — the build graph's worker is `builder`) or walked by the engineer's **main thread** (e.g. refine, with human `gate:` nodes). Node-sets, loop caps (`max_visits`) and host caps (`maxTurns` / `steps`) are data; emit refuses an uncapped loop, an unreachable node, a verb as a worker node skill, a worker named like a host built-in, and a leftover single `graph:` block. See [`examples/graph-catalog.forge.org.yaml`](../examples/graph-catalog.forge.org.yaml).
5. The **verbs** — `prime · intro · setup · inception · refine · execute · triage · wiki · handoff` (renamable per org) as commands + the skills each command reads. `triage` emits only when a worker graph binds it.

## Method (in brief)

forge is opinionated about **how** agents work together, unopinionated about **which tools** they use (the adapters) and **how each org works** (the operating model, read from the wiki at runtime):

- **Karpathy schema** — raw sources / wiki / schema, federated across an org-wide layer and per-project subspaces; code-as-truth holds at both.
- **Graph-agents, not a cast** — the emitted harness ships one agent per worker graph (`builder` for build, `triager` for triage) plus the optional read-only `validate` reviewer. Main-thread graphs (e.g. refine) run in the engineer's own session.
- **One orchestrator, one worker per task** — the engineer's session dispatches one graph-agent per ready task; the worker reviews its own diff as a self-check node, the human merge gate + CI are the independent review, and the optional read-only reviewer may check a completed PR. The durable substrate (org brain + tracker + SCM) survives crashes.
- **Wiki role templates** — `/forge:new` seeds a project wiki with six role pages (`templates/wiki/roles/`: orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst) and its own `prime` / `dispatch` / `wiki` skills. These are wiki content for the project tier. The emitted harness does not run them as agents.

Full method: [`METHOD.md`](METHOD.md) · roles: [`ROLES.md`](ROLES.md) · sessions: [`SESSIONS.md`](SESSIONS.md) · usage: [`USAGE.md`](USAGE.md).

## What ships today

- ✅ `/forge:emit` — the generator entry point: interview → deterministic emit → validation, with a leak gate (zero generator identity in output) and fail-closed controls (a "read-only" role with a write-capable allow-list fails the emit, not the org)
- ✅ Two emit targets from one config: Claude Code plugin + opencode configuration
- ✅ The graph catalog (`graphs:`, ADR 0019): worker graphs (build → `builder`, triage → read-only `triager`) and main-thread graphs (refine, with human gates), linted fail-closed
- ✅ A deterministic verify gate on the builder's PR create (`check: verify`): the declared tests must pass at HEAD and fail with the change reverted; edited base tests are flagged `protected-edited` (a Claude Code PreToolUse hook; an opencode plugin guard) — [`docs/notes/verify-gate.md`](notes/verify-gate.md)
- ✅ Read-only code access for a read-only worker (`code: read`): search + git history through a shell each host walls to the declared commands (opencode permission patterns + a plugin guard holding every call to one simple command; a Claude Code PreToolUse gate keyed on the worker's agent type) — [`docs/notes/read-only-code-surface.md`](notes/read-only-code-surface.md)
- ✅ Emitted READMEs list exactly what the package ships; the opencode README leads with the org's Homebrew install when `opencode.distribution.homebrew` is set
- ✅ Back/forward-compatible opencode artifact (1.18.29+ and 2.x, one package) with host-version detection
- ✅ Method documented (METHOD / ROLES / SESSIONS / USAGE / ADAPTERS / BOOTSTRAP); project-wiki templates incl. the six role pages; `wiki lint --consolidate`
- ✅ Test suite: emit golden tests + behavioural tests for the emitted `dispatch` tool on both host entrypoints
