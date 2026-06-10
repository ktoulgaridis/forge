# Role pattern

Forge ships six default agent roles. Each is a self-contained markdown file with strict boundaries — what the role owns, what it does NOT do, who it hands off to.

This doc explains the pattern. For per-role details, see the templates at `templates/wiki/roles/`.

## Why explicit roles

Without role boundaries, an agent given a ticket tends to:

- Implement → review its own code → merge → declare done
- Edit anything that "looks wrong" along the way
- Skip the wiki update because it's "obvious"

Explicit roles enforce **separation of concerns**:

- Implementer can't review their own MR (different role, different session)
- Wiki update is mandatory (companion wiki MR, judged by Wiki Maintainer)
- Architectural decisions go through Architect (with human approval for ADR changes)
- Migration nuances captured by Migration Analyst before Implementer touches the code

Result: redundant safety nets, fewer dropped concerns, more reliable agent output.

## The six default roles

### orchestrator
- **Top-of-loop after the human.**
- Dispatches work to Implementer/Reviewer teams or child sessions
- Pulls live state from the tracker
- Escalates to human when a decision exceeds delegated authority
- **Does NOT implement. Does NOT review. Does NOT make ADR-level decisions alone.**

### architect
- **Decomposes themes into tickets.**
- Drafts ADRs (`Proposed` status until human accepts)
- Sizes tickets
- Keeps architecture coherent as code lands
- **Does NOT implement. Does NOT orchestrate dispatch. Does NOT review for code quality (only for arch alignment).**

### implementer
- **Picks up a ticket; ships a code MR + companion wiki MR.**
- Follows TDD (failing test first)
- Each commit is structure OR behavior, never both
- **Does NOT pick what to work on (orchestrator dispatches). Does NOT review own MR. Does NOT skip the wiki MR.**

### reviewer
- **Independent eye on every MR.**
- Pulls the branch, runs tests locally
- Checks: acceptance criteria, conventions, security, contract, performance
- **Does NOT write the code. Does NOT auto-merge. Does NOT review own work.**

### wiki-maintainer
- **Keeps the wiki accurate, coherent, and small.**
- Reviews wiki MRs from implementers/architects
- Lints periodically (stale claims, broken cross-links, contradictions, page count)
- **Has consolidation authority** — proactively cleans up editorial drift (dead links, near-duplicates, fragmented sections, stale pages). Bounded strictly to editorial: cannot alter what the wiki says, only where or how. Semantic conflicts get filed as Architect tickets.
- **Does NOT write code. Does NOT invent content. Does NOT alter semantic claims. Does NOT approve ADR substance (just format + cross-references). Does NOT auto-merge consolidation MRs.**

### migration-analyst
- **Bridges legacy → new.**
- Reads legacy code, writes port specs in `legacy/ports/<thing>.md`
- Specifies parity tests
- Identifies subtle behaviors a naive port would miss
- **Does NOT implement the port. Does NOT redesign behavior (bug-for-bug parity unless flagged).**

## Custom roles

Use `/forge:add-role <name>` to stamp custom roles. Common ones we've seen:

- **compliance-officer** — reviews PRs against compliance checklists (SOC2, GDPR, HIPAA)
- **release-manager** — owns release branches, deployment cadence, post-release verification
- **security-reviewer** — security-focused review variant for sensitive PRs (auth, crypto, data export)
- **data-analyst** — answers data-shaped questions from the wiki + queries
- **tech-writer** — handles external-facing documentation (separate from wiki)

The custom role template forces you to fill out boundaries — what NOT to do is as important as what to do.

## Role file format

Every role file (default or custom) follows this template:

```markdown
# Role: <name>

## Mission

One sentence.

## Owns

What artifacts / decisions this role is responsible for.

## Boundaries

What this role does NOT do. Who it hands off to.

## Inputs at session start

What context this role needs. (Loaded by /prime.)

## Output format

Expected deliverables: MR, issue, ADR, etc.

## Tools

Which tools / skills are appropriate for this role.

## When to escalate

Conditions where the role should stop and surface to human or another role.

## Handoff

Who picks up after this role completes a unit of work.

## Anti-patterns

What to avoid — common ways this role fails.
```

## How prime calibrates a role

`/prime <role> [arg]` runs:

1. Read `roles/<role>.md` — the boundaries above
2. Read `CLAUDE.md` — wiki schema
3. Read `architecture.md`, `ROADMAP.md`, recent ADRs — project context
4. Pull live state from tracker — assigned issues, MRs awaiting this role
5. Read repo-local `CLAUDE.md` if running inside a target repo
6. Emit calibration summary (who am I, what am I working on, what NOT to do, next concrete action)

## Why six and not more

Forge defaults to six because they cover the common cases without overlap:

- Plan (architect) → execute (implementer) → verify (reviewer)
- Document (wiki-maintainer) → analyze legacy (migration-analyst)
- Coordinate (orchestrator)

Adding more out-of-the-box would create overlap; we prefer to start with six and let users extend per-project.

## Why these six and not "developer + tester"

The "developer + tester" split is conventional but maps poorly to agent work:
- Tester implies post-hoc verification; reviewer captures the same idea but earlier (during MR review, not after deploy)
- Developer is too broad; we split it into architect (plans) + implementer (executes) + migration-analyst (specs ports)
- Wiki-maintainer is genuinely separate because writing about code requires reading the code while not being attached to having authored it

This isn't dogma. If your org's culture maps better to developer + tester + product-manager + tech-lead, write those role files. The forge method is the boundaries, not the names.
