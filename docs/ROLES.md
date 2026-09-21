# Node contracts, not a cast

> **Superseded by the graph (ADR 0001, #28).** The six role *archetypes* as emitted agent files are gone. What survives — what was always the asset — is the **boundaries**, re-anchored as properties of the **nodes** in the process graph. This doc explains the node-contract pattern; the old per-persona role files are retired.

## Why the cast died

The cast was an implementation detail of weaker models: a fixed persona with pinned permissions, steps, and model bought predictable behavior from models that could not yet be trusted to follow a procedure. Current models follow the graph. The process is already data (the wiki's operating model, read at prime); the cast was the one remaining place the generator *baked* structure it could read.

The critique that motivated ADR 0001: **keep the graph, ditch the agents.** The graph is the contract.

## The two node kinds

Every run stands on a **node** in the process graph. The node kind decides the engine and the boundary:

| Node kind | Engine | Boundary | Context |
|---|---|---|---|
| **produce** (implement) | `dispatch` | full tools, a per-(repo, ticket) worktree | its own session |
| **validate** (review, gate, agent-ready) | the native subagent tool (`subagent_type: "validate"`) | read-only by the validating agent's own frontmatter | fresh context (`fresh_context: true`) |

A node's contract is **process data**, declared in the org config's `opencode.nodes`:

```yaml
opencode:
  nodes:
    review:
      kind: validate
      fresh_context: true
      read_surface: [read, grep, glob]
      max_steps: 40
      model: amazon-bedrock/us.anthropic.claude-opus-4-8   # optional pin
    gate:
      kind: validate
      fresh_context: true
      read_surface: [read, grep, glob]
      max_steps: 25
```

The emit lints this fail-closed: a validating node with no read surface, no fresh-context flag, no cap, or a write capability in its surface **does not emit**. Silence is fail-open and is refused.

## The four load-bearing invariants, re-anchored

Each invariant the cast guarded survives — attached to the **node**, enforced by the machinery, not a persona file:

1. **No-self-review** — a property of the validate node's `fresh_context: true` and its separate engine. The produce run and the validate run are two contexts (two engines, one boundary); the validator sees the diff + the task spec, never the producer's reasoning. The graph-lint refuses a validating node without `fresh_context: true`.

2. **Read-only validation** — the validating agent's own frontmatter (`agent/validate.md`) carries the deny set, derived at emit from the union of the graph's read surfaces. The native subagent tool derives the child session's permissions from that block — deterministic, no rule-stomping machinery. `dispatch` is denied on the validating agent, so a validating run cannot launder a write through a child run.

3. **Step caps / budget discipline** — `max_steps` per node, declared in the graph, applied at the run. A node with no declared cap does not emit.

4. **Model policy** — the org floor (one provider, the banned list) enforced per dispatch call; the validating agent's model pinned in frontmatter at definition time; a per-node pin validated at emit. A run with no explicit model gets the org floor, never the host default.

## The spawnable set is allowlisted

The org config's `task` permission rule allows exactly the primary agent + `validate` under a `*: deny`. A typo'd `subagent_type` is denied — never silently the full-permission primary agent — and a hand-added agent file is not spawnable until the org config names it.

## What we lost (honestly)

- **The emit-time tripwires for personas.** The strongest guarantees used to be emit-time (a mis-declared role refused to emit); they are now graph-lint-time and dispatch-time. The posture (fail closed) survives; the moment it fires moved later.
- **Pre-loaded persona discipline.** The role files carried curated guidance (TDD-first, anti-pattern lists) into context before the first token. A general agent loads the node contract at the moment the process calls for it. This is the core bet: the cast was reliability bought from weaker models. If the org's model roster regresses, the graph re-grows depth pins in node contracts until it recovers.
- **Axis 3 as a differentiation surface.** Roles ("who does what") merge into axis 4 (the operating model): orgs still differ in *what their graph demands*, not in *who* executes it.

## The old six archetypes

For historical reference, the six default archetypes (orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst) and their boundary files are preserved at tag `archive/pre-forge-v0.3` and in the git history of `templates/opencode/agent/`. The boundaries they encoded are the node contracts above.

## See also

- [METHOD.md](METHOD.md) — the method: the graph, the two engines, the invariants
- [GENERATOR.md](GENERATOR.md) — the v2 north star: the runtime section is authoritative
- [ADR 0001](decisions/0001-graph-not-agents.md) — the decision: keep the graph, drop the cast
