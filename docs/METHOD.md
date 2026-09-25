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

> **Note:** this METHOD doc describes the graph runtime as of forge 0.9 (ADR 0018 single locus, ADR 0019 graph catalog): one orchestrator, one bounded graph-agent per task, review as a self-check node, the human merge gate + CI as the independent review. The cast (six role archetypes as emitted agent files) is gone; the boundaries survive as graph contracts. `GENERATOR.md` is authoritative where they differ.

## Three layers (Karpathy schema)

Inspired by Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

| Layer | What it contains | Editability |
|---|---|---|
| **Raw sources** | Documents, design notes, customer emails, requirements YAML, prior plans | **Immutable.** Preserved verbatim. Reference only. |
| **The wiki** | LLM-maintained pages: ADRs, services, themes, role definitions, cohort-2026-style operational context | **Edited via merge requests reviewed by the wiki-maintainer agent.** No direct edits to main. |
| **The schema** | `CLAUDE.md` — defines wiki structure + maintenance rules + page templates | **Constitutional.** Rarely edited; changes go through ADR-style proposal. |

The schema governs the wiki. The wiki references the raw sources. Code is the ultimate source of truth — the wiki cites code, never duplicates it.

## The graph, not the cast

The process is data. The org config's `graphs:` catalog (ADR 0019) declares named graphs — each node's skill or rubric, its transitions, loop caps (`max_visits`) and the graph's host cap — and the emit lints it fail-closed. A graph is either:

- **a worker** — its own bounded graph-agent (e.g. `builder` for build, `triager` for triage) that walks its nodes in one context, never asks the human, and ends every run with one RESULT line. The orchestrator launches one per task (Claude Code: the Agent tool; opencode: `dispatch`, one worktree per (repo, ticket) for a writer); or
- **a main-thread walk** — the engineer's own session walks it through the verb's skill (e.g. refine); its `gate:` nodes are human sign-offs.

Review is a **self-check node** inside the builder (ADR 0018): the builder writes the failing test first and applies the review rubric to its own diff. The relied-upon independent review is the **human merge gate + CI**. The one fresh-context validator left is the OPTIONAL read-only supplementary reviewer (`validate`), run on a **completed** PR for a high-risk diff, never inside the loop.

The boundaries the cast encoded survive as graph contracts — see [ROLES.md](ROLES.md). Tool surface, isolation, caps and model policy attach to the graph and are enforced by the emitted agent definitions, not a persona file.

## The skill verbs

The emitted harness's verbs are `prime · intro · setup · inception · refine · execute · triage · wiki · handoff` (renamable per org). `prime` calibrates every session from the wiki; `execute` launches one builder per ready task; `triage` launches one read-only triager per trigger; `refine` is a main-thread walk; `wiki` reads and contributes to the org brain. Skills are emitted at `skills/<verb>/SKILL.md` (Claude Code) or `skill/<verb>/SKILL.md` + `command/<verb>.md` (opencode). A `/forge:new`-stamped project wiki carries its own `prime` / `dispatch` / `wiki` skills.

## Theme → ticket → MR + wiki MR workflow

```
Theme (a phase of work, e.g., "T1 — Platform bring-up")
  ↓ broken down by the orchestrator (with the engineer)
Tickets (in tracker — Jira/GitHub Issues/Linear/etc.)
  ↓ the orchestrator launches one builder per ready task: understand → build → validate → review (self-check) → fix → clear → verify (a script decides whether the PR opens)
Code MR + companion wiki MR (paired)
  ↓ code MR merged by a human once CI passes (the independent review)
  ↓ wiki MR merged after the harvest validates it
Theme status updated; the next node runs
```

Three invariants:
1. **Code MRs and wiki MRs are paired.** Every change to behavior includes a wiki update reflecting the change. The harvest judges whether the wiki claim matches the code.
2. **Independent review is human.** The builder reviews its own diff adversarially (tests first, a rubric), which is a self-check, not independence. The relied-upon independent review is the human merge gate + CI; the optional fresh-context reviewer may check a completed high-risk PR.
3. **Cascade.** If a fact changes on one wiki page, search for that fact elsewhere. The harvest's job is to enforce; the builder's job is to flag.

## Top-of-loop human + the graph

The human:
- Gives direction
- Approves scope-changing ADRs
- Runs final UAT with the customer
- Owns the **merge gate** — the independent review of each PR
- Does **not** implement or dispatch routinely (the orchestrator does that)

The graphs:
- The orchestrator launches one worker per task (a builder in its own worktree, a read-only triager in place) and holds only each worker's RESULT line
- Parallel workers only for genuinely-independent tasks (one worktree per (repo, ticket)); a coupled task is never split across agents
- Main-thread graphs (refine) run in the engineer's session, with human gates
- The harvest judges incoming wiki captures in its own context

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

forge is opinionated about: the **agent collaboration pattern**, the **wiki schema**, and the **graph contracts**. Everything else is your call.

## Why this method

- **Wiki as the LLM's external memory** — agents lose context across sessions; the wiki preserves it. Every session starts with prime → loads the wiki → has full project context immediately.
- **Bounded graph-agents enforce separation of concerns** — each worker graph has one mandate, an exact tool surface and a cap (the triager cannot write; the builder writes only in its worktree), which prevents "agent does everything badly".
- **Themes give parallelism a structure** — without themes, you get either chaos (everyone working on everything) or bottlenecks (waiting for the next ticket). Themes let multiple agents work without colliding.
- **Code-as-truth + wiki-as-explanation** — the wiki never claims something the code can't prove. Every status claim cites a commit/file/MR. This kills wiki-rot.
- **Tool-agnostic** — orgs have their own tools; forge meets them where they are.

## Session lifecycle — ephemeral by default

Sessions are not the substrate of memory. The wiki + tracker + SCM are. **Sessions are ephemeral front-ends to those persistent stores.**

- The orchestrator session is long-lived but re-primed often, not compacted.
- Worker runs (a builder, a triager) are ephemeral by ticket / trigger / unit of work.
- Each worker ends with one RESULT line the orchestrator reads (Claude Code: the Agent tool's result; opencode: `dispatch`'s `<run-closed>` postback) — no polling.
- Compaction is a failure mode, not a planned-for state. See [SESSIONS.md](SESSIONS.md).

This is what makes the method robust: agents can crash, sessions can end, context can drift — and the durable substrate is unaffected. Re-priming a fresh session restores full project context immediately.

## Reference

The first project built with this method (and the source of these patterns) is the SocWave engagement at [examples/socwave.md](../examples/socwave.md).

## See also

- [ROLES.md](ROLES.md) — why the cast went and where its boundaries went
- [SESSIONS.md](SESSIONS.md) — session lifecycle, ephemeral-by-default, compaction-as-failure-mode
- [USAGE.md](USAGE.md) — daily operation of a forge-stamped project
- [BOOTSTRAP.md](BOOTSTRAP.md) — one-time setup, first project walkthrough
- [ADAPTERS.md](ADAPTERS.md) — adapter contract (for forge contributors)
