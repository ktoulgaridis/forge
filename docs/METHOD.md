# The forge method

forge is opinionated about **how agents collaborate** and unopinionated about **which tools they use**. This doc explains the method — the part that doesn't change between projects.

## Forge vs. the harness

It's worth being precise about what forge is and isn't, because the boundary defines everything else.

- **The agent harness** (Claude Code) is the runtime. It runs the agents, executes tools, manages sessions, holds context. forge does not replace it, wrap it, or compete with it.
- **forge is the infrastructure adjacent to the harness.** It supplies the *substrate the harness operates against* so that agent-driven development is optimal and consistent: durable memory (the wiki), separation of concerns (roles), the verbs that calibrate and route work (skills), the integrations to your real tools (adapters), and the working agreement your org is held to (methodology bundles).

```
        ┌─────────────────────────────────────────┐
        │  Agent harness (Claude Code)            │  ← runs the agents
        │   sessions · tools · context · model    │
        └─────────────────────────────────────────┘
                          ▲ operates against
                          │
        ┌─────────────────────────────────────────┐
        │  forge substrate (adjacent infra)       │  ← what forge stamps
        │   wiki (memory) · roles (boundaries)    │
        │   skills (verbs) · adapters (tools)     │
        │   methodology (the org's standard)      │
        └─────────────────────────────────────────┘
```

The harness is general-purpose; forge makes a *specific organization's* agent-driven development repeatable. forge does this as a **generator**: it interviews an org and emits a standalone, org-owned plugin (`acme-forge`) carrying that org's tools, operating model, and runtime — see [`GENERATOR.md`](GENERATOR.md), the v2 north star, and the [README lifecycle](../README.md#lifecycle-generate-distribute-re-generate).

> **Note:** this METHOD doc describes the graph runtime (ADR 0001, #28): one orchestrator walking the process graph, the node kind deciding the engine. The cast (six role archetypes as emitted agent files) is gone; the boundaries survive as node contracts. `GENERATOR.md` is authoritative where they differ.

## Three layers (Karpathy schema)

Inspired by Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

| Layer | What it contains | Editability |
|---|---|---|
| **Raw sources** | Documents, design notes, customer emails, requirements YAML, prior plans | **Immutable.** Preserved verbatim. Reference only. |
| **The wiki** | LLM-maintained pages: ADRs, services, themes, role definitions, cohort-2026-style operational context | **Edited via merge requests reviewed by the wiki-maintainer agent.** No direct edits to main. |
| **The schema** | `CLAUDE.md` — defines wiki structure + maintenance rules + page templates | **Constitutional.** Rarely edited; changes go through ADR-style proposal. |

The schema governs the wiki. The wiki references the raw sources. Code is the ultimate source of truth — the wiki cites code, never duplicates it.

## The graph, not the cast

The process is data. The org config's `opencode.nodes` declares the validating nodes (review, gate, agent-ready) with their contracts — kind, fresh-context, read surface, step cap, optional model pin — and the emit lints it fail-closed. One general agent carries a workflow; the node kind decides the engine:

- **Produce nodes → `dispatch`** (the per-(repo, ticket) worktree grant);
- **Validate nodes → the native subagent tool** (`subagent_type: "validate"`; read-only by the validating agent's own frontmatter, fresh-context by construction).

The boundaries the cast encoded survive as node contracts — see [ROLES.md](ROLES.md). The invariants (no-self-review, read-only validation, step caps, model policy) attach to the node, enforced by the machinery, not a persona file.

## The skill verbs

| Skill | Who uses it | Purpose |
|---|---|---|
| `prime` | Every session at start | Calibrate: load the operating model + schema + live state from the tracker |
| `dispatch` | The orchestrator only | Hand produce work to a child run (the worktree grant); ad-hoc read-only delegations |
| `wiki` | Any run (`query`/`capture`); the harvest validates (`promote`) | Wiki maintenance verbs |

Skills are emitted into the package at `skill/<verb>/SKILL.md`. They reference the node contracts and adapter snippets to function. The native subagent tool (not `dispatch`) carries validate runs.

## Theme → ticket → MR + wiki MR workflow

```
Theme (a phase of work, e.g., "T1 — Platform bring-up")
  ↓ broken down by the orchestrator (with the engineer)
Tickets (in tracker — Jira/GitHub Issues/Linear/etc.)
  ↓ the orchestrator walks the graph: produce runs (dispatch) → validate runs (native subagent)
Code MR + companion wiki MR (paired)
  ↓ code MR merged after the validate node's verdict passes
  ↓ wiki MR merged after the harvest validates it
Theme status updated; the next node runs
```

Three invariants:
1. **Code MRs and wiki MRs are paired.** Every change to behavior includes a wiki update reflecting the change. The harvest judges whether the wiki claim matches the code.
2. **No self-review.** The produce run and the validate run are two contexts — two engines, one boundary. A validating node is `fresh_context: true` in the graph; the validator sees the diff, never the producer's reasoning.
3. **Cascade.** If a fact changes on one wiki page, search for that fact elsewhere. The harvest's job is to enforce; the produce run's job is to flag.

## Top-of-loop human + the graph

The human:
- Gives direction
- Approves scope-changing ADRs
- Runs final UAT with the customer
- Does **not** implement, review individual MRs, or dispatch routinely (the orchestrator does those)

The graph:
- The orchestrator walks it, spawning produce runs (dispatch, worktree-isolated) and validate runs (native subagent, read-only, fresh-context) as the process demands
- Parallel produce runs for parallelizable work (one worktree per (repo, ticket))
- A validate run per produce run (separate context, separate engine)
- The harvest (a validate node) runs on incoming wiki captures

Streams (typically A=backend, B=frontend, C=coordination, D=human) parallelize work without stepping on each other. Streams may map to different boards in Jira-multi-board setups; that's an adapter concern.

## Adapter contract

To support a new tracker / SCM / chat tool, write an adapter at `adapters/<type>/<name>.md` providing:

1. **Required CLIs** with install hints
2. **Optional MCP servers** with registration snippets for `~/.claude/settings.json`
3. **Config schema** — what `.forge.config.yaml` fields the adapter needs
4. **Skill snippets** — text blocks that get inlined into `prime`, `dispatch`, and possibly other skills when the adapter is used
5. **Doctor checks** — CLI smoke tests + auth verifications
6. **Examples** — actual command invocations against a sample project

See [`docs/ADAPTERS.md`](ADAPTERS.md) for the full adapter contract.

## What forge is NOT

- Not the agent harness — Claude Code runs the agents; forge is the substrate adjacent to it (see [Forge vs. the harness](#forge-vs-the-harness))
- Not a runtime — it doesn't run continuously; it stamps and steps out
- Not a CI/CD platform — it informs about CI but doesn't manage pipelines
- Not a tracker replacement — it adapts to your tracker; doesn't replace it
- Not a project management tool — it's a way of organizing agent collaboration on top of whatever PM tools you use
- Not opinionated about the application architecture — that's a project decision (lives in your project's ADRs)

forge is opinionated about: the **agent collaboration pattern**, the **wiki schema**, and the **role boundaries**. Everything else is your call.

## Why this method

- **Wiki as the LLM's external memory** — agents lose context across sessions; the wiki preserves it. Every session starts with prime → loads the wiki → has full project context immediately.
- **Roles enforce separation of concerns** — implementer + reviewer + wiki-maintainer split prevents "agent does everything badly" because each role has a narrow mandate and explicit boundaries.
- **Themes give parallelism a structure** — without themes, you get either chaos (everyone working on everything) or bottlenecks (waiting for the next ticket). Themes let multiple agents work without colliding.
- **Code-as-truth + wiki-as-explanation** — the wiki never claims something the code can't prove. Every status claim cites a commit/file/MR. This kills wiki-rot.
- **Tool-agnostic** — orgs have their own tools; forge meets them where they are.

## Session lifecycle — ephemeral by default

Sessions are not the substrate of memory. The wiki + tracker + SCM are. **Sessions are ephemeral front-ends to those persistent stores.**

- The orchestrator session is long-lived but re-primed often, not compacted.
- Produce runs (dispatch children) and validate runs (native subagent children) are ephemeral by ticket / MR / unit of work.
- The round trip posts every run's closing message back to the orchestrator — on completion and on error — so the orchestrator learns a run finished without polling.
- Compaction is a failure mode, not a planned-for state. See [SESSIONS.md](SESSIONS.md).

This is what makes the method robust: agents can crash, sessions can end, context can drift — and the durable substrate is unaffected. Re-priming a fresh session restores full project context immediately.

## Reference

The first project built with this method (and the source of these patterns) is the SocWave engagement at [examples/socwave.md](../examples/socwave.md).

## See also

- [ROLES.md](ROLES.md) — the node-contract pattern (the cast is gone; the boundaries survive)
- [SESSIONS.md](SESSIONS.md) — session lifecycle, ephemeral-by-default, compaction-as-failure-mode
- [USAGE.md](USAGE.md) — daily operation of a forge-stamped project
- [BOOTSTRAP.md](BOOTSTRAP.md) — one-time setup, first project walkthrough
- [ADAPTERS.md](ADAPTERS.md) — adapter contract (for forge contributors)
