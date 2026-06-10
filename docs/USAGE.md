# Daily usage

How to run a forge-stamped project after `/forge:new` has stamped it.

This complements [BOOTSTRAP.md](BOOTSTRAP.md) (one-time setup) and [METHOD.md](METHOD.md) (the principles). USAGE.md is the operations manual.

## The starting state

After `/forge:new <project>`:
- Wiki repo exists at `<wiki_remote_url>` and locally at `~/Work/<project>/`
- `socwave-platform`-style code repo(s) exist (likely empty if this is a new build)
- `.forge.config.yaml` captures all the choices
- Templates are stamped: ADR template, service template, theme template, role files, skills

But: no themes yet, no tickets, no ADRs filled in. The Architect's first job is to populate.

## Day 1 — first orchestrator session

```bash
cd ~/Work/<project>
claude
> /prime orchestrator
```

Outputs a calibration summary. Empty queues across streams (no tickets yet).

**Your first dispatch as the human:** ask Architect to draft the first ADR(s) capturing what you know:

```
Hey orchestrator — dispatch Architect to draft the foundational ADRs.
Context: <whatever you know about the project>.
Architect should produce:
- ADR 0001: <whatever the first big decision is>
- ADR 0002: <next>
... and the first theme breakdown if it's clear.
```

Orchestrator either dispatches via TeamCreate (Architect ephemeral session) or hands you the new-session snippet from `_snippets/new-session.md` to spawn manually in another terminal.

After Architect returns with ADRs + theme tickets, orchestrator dispatches Implementer+Reviewer pairs for the first wave.

## Daily rhythm (rough)

```
Morning:
  cd ~/Work/<project> && claude
  > /prime orchestrator       # daily re-prime; loads fresh tracker state
  Review what landed overnight (merged MRs, closed tickets, blockers)
  Decide what's worth dispatching today
  Dispatch 2-4 Implementer+Reviewer pairs in parallel
  (Optional) Dispatch Wiki Maintainer for a `lint --consolidate` pass
              if it's been a week since the last one

Throughout the day:
  Pop in occasionally to:
    - Approve ADRs that are sitting in Proposed status
    - Answer escalations from agents (architectural questions)
    - Merge code MRs after Reviewer approves
    - Merge wiki MRs after Wiki Maintainer approves

End of day:
  Re-prime if needed
  Glance at the tracker board — anything stuck?
```

The orchestrator session can stay open all day. **Don't compact it.** Re-prime instead — `/prime orchestrator` is fast and refreshes everything from the tracker.

## Re-priming cadence

| Trigger | Action |
|---|---|
| First thing in the morning | `/prime orchestrator` |
| After lunch / mid-day shift | `/prime orchestrator` |
| After major direction change from you | `/prime orchestrator` |
| After 2+ hours of non-orchestrator work in this session | `/prime orchestrator` |
| Context window approaches 50% used | `/prime orchestrator` (or fresh session) |
| Harness offers compaction | **Re-prime, don't compact.** See `docs/SESSIONS.md` |

Re-priming is cheap. Compaction is lossy. Bias toward re-priming hard.

## Common operations

### Adding a new theme

```
> /prime orchestrator
> "We need to start working on T8 — <description>. Dispatch Architect."
```

Orchestrator calls Architect (TeamCreate or new-session snippet). Architect:
- Updates `themes/T8-<slug>.md`
- Files tickets in the tracker
- Drafts any ADRs the theme requires (status: Proposed)
- Reports back with ticket IDs

### Approving a Proposed ADR

ADRs are filed by Architect with status: Proposed. **You** flip them to Accepted by reviewing + merging the wiki MR.

```
gh pr view <wiki-mr-url>     # or glab mr view
# Read the ADR
# If you accept it: edit the file in the MR to change Status: Proposed → Accepted
# Merge
```

Orchestrator picks up the merge automatically on next re-prime.

### Handling a stalled ticket

A ticket that's been "in progress" for >2 days without a code MR is stalled. Causes:

1. **Implementer agent hit a blocker and didn't escalate.** Re-dispatch with a fresh ephemeral session — old session probably hit context limits.
2. **Acceptance criteria are wrong/unclear.** Architect re-scopes; Orchestrator re-dispatches.
3. **Dependency wasn't ready.** Check upstream tickets. If unblocked, re-dispatch. If still blocked, ask Architect to revise the dependency graph in the theme page.

Orchestrator surfaces stalled tickets on `/prime orchestrator`. You decide which path.

### Reviewing in flight architectural debate

If agents are disagreeing about an architectural choice in MR comments:

1. **Don't let it persist in conversation memory.** Capture it as an ADR (Proposed).
2. Architect drafts the ADR with both sides + a recommendation.
3. You decide; flip to Accepted or Superseded.
4. Future agents reference the ADR; debate ends.

The wiki is the resolution mechanism. Conversation is just the discovery.

### Handing off across human teams

When a real human teammate joins:

1. Share `~/Work/<project>` (clone the wiki repo + the code repos)
2. Tell them: `claude` → `/prime <role>` to take on a role
3. Give them the URL of `docs/USAGE.md` (this doc) for orientation
4. Give them the project-specific README (in their stamped wiki) — that's the project's "what is this" page

## What's safe to edit, what's forge-managed

| File | Safe to edit | Notes |
|---|---|---|
| `decisions/*.md` | ✅ Always | Project ADRs are yours. Add new ones; supersede old ones. |
| `services/*.md`, `themes/*.md` | ✅ Always | Project content. |
| `architecture.md`, `ROADMAP.md` | ✅ Always | Project content. |
| `roles/*.md` | ⚠️ Carefully | Default role files have `<!-- forge-managed -->` blocks; edit other parts but don't delete the boundaries section. Custom roles you add are fully yours. |
| `.claude/skills/*/SKILL.md` | ⚠️ Carefully | Stamped from forge templates. Adapter snippets are forge-managed. Project-specific additions can go in `<!-- project-customizable -->` blocks. |
| `CLAUDE.md` | ⚠️ Carefully | Schema is forge-managed; the `<!-- project-customizable -->` block at the end is yours. |
| `.forge.config.yaml` | ❌ Use `/forge:configure` | Direct edits drift from what's actually stamped. |

When in doubt: `/forge:configure` shows you what's drift-able and re-renders cleanly.

## Upgrading forge mid-project

When forge releases a new version:

```bash
cd ~/Work/<project>
claude
> /forge:configure
# Detects version drift
# Lists what changed since your stamped version
# Re-renders affected files (skills if adapters changed; role index if roles changed)
# Opens a wiki MR for review
# Does NOT touch ADRs, services, themes — those are project content
```

You merge the wiki MR; project continues with the new method.

## When to deviate from the method

The method is opinionated, not dogmatic. Real situations to deviate:

- **Solo human + agents only:** the Reviewer role can be the same human reading MRs in their browser; doesn't need an agent session. The method's "no self-review" rule means agent A doesn't review agent A's MR — the human reviewing is fine.
- **Trivial changes:** a typo fix doesn't need a wiki MR. Use judgment; the method is for substantive work.
- **Short-lived experiments:** spike tickets can skip the wiki MR if their output is "we now know X, add it as an ADR for the real implementation ticket." Spike → ADR → real ticket.

The boundaries in role files are firm. The workflow nicities (paired wiki MR, etc.) are negotiable for trivial cases.

## When something feels wrong

Three diagnostic re-primes:

```bash
# Stale tracker view, missed a merge, wrong dispatch decisions
> /prime orchestrator

# Implementer is going off the rails
# (in their session) > /prime implementer <issue-id>
# (re-loads role boundaries; usually corrects)

# Wiki has drifted into incoherence
# (in maintainer session) > /prime wiki-maintainer
# > /wiki lint --consolidate
```

Re-priming is the fix for most "this session feels off" feelings. The wiki + tracker + role files are the durable substrate.

## See also

- [METHOD.md](METHOD.md) — why the method works the way it does
- [ROLES.md](ROLES.md) — six default roles + custom role pattern
- [SESSIONS.md](SESSIONS.md) — ephemeral-by-default lifecycle + when to compact (rarely)
- [BOOTSTRAP.md](BOOTSTRAP.md) — one-time setup
- [ADAPTERS.md](ADAPTERS.md) — for forge contributors, how adapters work
