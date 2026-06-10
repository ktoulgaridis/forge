# Session lifecycle

The forge method is designed so that compaction should rarely happen. The principle: **ephemeral sessions for discrete work, one persistent orchestrator that mostly delegates.** When you find yourself compacting, you've usually let a session do work that should have been spawned out.

## Session types

| Type | Lifespan | Purpose |
|---|---|---|
| **Orchestrator session** | Long-lived (re-primed often, never compacted) | The human's interface. Reads tracker state. Dispatches work. Surfaces blockers to the human. **Does not implement.** |
| **Sub-agent session** (TeamCreate teammate or child Claude) | Ephemeral — dies when its unit of work completes | Implementer + Reviewer pair (paired via TeamCreate); Architect (per theme decomposition); Migration Analyst (per port spec); Wiki Maintainer (per consolidation pass). One role, one unit, one MR. |

## The principle

> Don't accumulate context that durable artifacts already hold.

Architectural decisions live in ADRs. Project state lives in the tracker. Code state lives in the SCM. Role identity lives in role files. Preferences live in memory. **Sessions are temporary front-ends to those persistent stores.**

When a session dies, nothing important is lost — because nothing important was ever only-in-session.

## Lifecycle of a typical unit of work

```
1. Orchestrator (long-lived, freshly primed) sees: "ticket BACKEND-127 is ready"
2. Orchestrator → /dispatch BACKEND-127
   → spawns TeamCreate(implementer + reviewer) — both fresh sessions
3. Implementer session: /prime implementer BACKEND-127
   → reads ticket, ADRs, repo CLAUDE.md, port spec if any
   → ships code MR + drafts wiki MR
   → session dies
4. Reviewer session: /prime reviewer <mr-url>
   → pulls MR, runs tests, judges
   → approves or change-request
   → session dies
5. (Maybe) Wiki Maintainer session: judges wiki MR, merges
   → session dies
6. Orchestrator (still alive) sees: ticket closed; pick next
```

The orchestrator is the only thing that persists across this. Everything else is a one-shot.

## When to spawn fresh vs. continue in-session

**Spawn fresh** (default):
- Any concrete unit of work (a ticket, a review, a port spec, a consolidation pass)
- Any role-changing context shift (you were architecting; now you need to implement → that's a new session)
- Any time context window is approaching pressure (>50% used) and the work is not finished

**Continue in-session** (rare, only for the orchestrator):
- Quick status checks ("show me the open MRs across streams")
- Triaging a blocker before deciding who to dispatch
- Direct conversation with the human about direction

The orchestrator gets re-primed (`/prime orchestrator`) far more often than it gets compacted. Re-priming is cheap — it loads fresh tracker state, current themes, recent ADRs. Compacting is expensive — it summarizes lossy.

## When compaction does happen

Sometimes a session genuinely runs long. If the harness compacts:

1. **Recovery is `/prime <role>`.** Everything important reloads from durable sources.
2. **Look at why it happened.** Three common causes:
   - Orchestrator did implementation work it should have dispatched — fix by adhering to role boundaries
   - In-flight architectural debate didn't land in an ADR — fix by writing the ADR earlier
   - A unit of work was scoped too large for one session — fix by tighter ticket sizing (≤8 agent-hours)
3. **No special "post-compaction" handling needed.** The orchestration substrate (wiki + tracker + roles + skills) was designed so sessions are interchangeable. Re-prime, continue.

## Anti-patterns

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| One session implements + reviews + merges + writes wiki MRs | Violates role separation; session bloats; review quality drops | Split into Implementer + Reviewer (separate sessions) + Wiki Maintainer (third session for the wiki MR review) |
| Orchestrator session "remembers" what was decided | Decisions belong in ADRs, not session memory | Write the ADR; orchestrator references it |
| "Let me just keep this session open and continue tomorrow" | Context drifts; agent identity blurs | Open a fresh session tomorrow; `/prime <role>`; continue |
| "I'll compact instead of cutting an ADR" | Compaction is lossy summarization; ADR is structured durable record | Cut the ADR, then start fresh session |
| Multi-week implementer sessions | Single agent juggling N tickets — boundaries collapse | One ticket, one session, one MR, one death |
| Orchestrator that hasn't been re-primed in days | Stale tracker view; missed MRs awaiting review | Re-prime daily (or per major direction change) |

## Pre-compaction checklist (orchestrator-only, since other sessions shouldn't reach this)

If you're a long-lived orchestrator and the harness offers compaction:

- [ ] Has every architectural choice in this conversation been written to an ADR?
- [ ] Is every dispatched ticket recorded in the tracker?
- [ ] Are open MRs visible via `glab mr list` / `gh pr list` / equivalent?
- [ ] Is the user's most recent direction reflected somewhere durable (memory, ADR, ticket comment)?

If yes to all four: compact safely; recovery is `/prime orchestrator`.

If any are no: **don't compact yet.** Land the missing artifact first.

## How dispatch enforces this

The `/dispatch` skill defaults to **TeamCreate** mode (Implementer + Reviewer paired ephemeral sessions) rather than child Claude session continuation. Even for size:1h tickets, a fresh ephemeral session is preferred over expanding the orchestrator's context.

The `/forge:doctor` script can flag orchestrator session age — if a session has been alive for >24h without a re-prime, doctor warns "consider re-priming."

## Why this matters

Three reasons it pays off:

1. **Role discipline.** A fresh ephemeral implementer session, primed with the role boundaries, follows them. A long-lived session that's been doing many things loses role identity.
2. **Cost.** Compaction-then-recovery costs more agent-hours than ephemeral spawn-and-die.
3. **Resilience.** If ten sessions are running in parallel and one crashes, the work is bounded — the durable substrate (wiki, tracker, SCM) survives. Long-lived sessions that "remember" decisions are single points of failure.

## The orchestrator's persistent state — what's allowed

The orchestrator session DOES carry some live state, by design:

- Active dispatch log ("which agents are working on what right now")
- Recent direction from the human
- A short-term plan ("after BACKEND-127 lands, dispatch FRONTEND-50")

This is fine because:
- The dispatch log can be persisted to a local file (`~/.local/state/<project>-dispatch.log`)
- Recent direction lives in conversation memory but is also memorialized as ADRs / ticket comments when consequential
- Short-term plans are derived from the tracker; if the orchestrator dies, the next orchestrator re-derives from tracker state

So even the orchestrator is **stateless in principle, stateful in practice** — every state it holds has a durable shadow elsewhere.

## Spawning sessions manually

When the orchestrator (or the human) wants to spawn an ephemeral session outside TeamCreate, use the snippets at `_snippets/new-session.md` (stamped into every forge project's wiki). Per-role copy-pasteable bootstrap text — paste as the first message of a fresh Claude Code session and the session knows what it is + what to stop at.

Use cases:
- Specific terminal/window for visibility
- Different machine for resource-heavy work
- Debugging interactively where TeamCreate would be opaque
- One-off ad-hoc work outside the normal ticket flow

For the routine ticket flow, `/dispatch <issue-id>` (TeamCreate) is preferred.

## See also

- [`docs/METHOD.md`](METHOD.md) — the broader Karpathy-schema + role pattern context
- [`docs/ROLES.md`](ROLES.md) — how role boundaries support ephemeral sessions
- `templates/wiki/_snippets/new-session.md.template` — copy-pasteable session bootstrap per role
- `templates/wiki/.claude/skills/dispatch/SKILL.md.template` — the dispatch primitive
- `templates/wiki/.claude/skills/prime/SKILL.md.template` — what a fresh session loads
