# ADR 0001 — Keep the graph, drop the fixed role cast: the process as data + skills, wielded by one general agent

Status: Proposed — the maintainer decides. Accepting this ADR is what would rewrite
`docs/GENERATOR.md` and the opencode emit; this document, by itself, changes no
template, no config, and no behavior.
Date: 2026-09-20
Owner: Architect (with human approval)
Ticket: ktoulgaridis/forge#23

## Context

What the opencode emit ships today (`emit --target opencode`), file by file:

- `opencode.json` — the one-provider allowlist (`enabled_providers`) plus the built-in `task` deny.
- `AGENTS.md` — the session preamble pointing at the org brain.
- `command/` — the eight verbs (intro · setup · prime · inception · refine · execute · wiki · handoff), org-renamable via the `verbs:` map.
- `skill/` — the procedure each command reads and follows; byte-identical to the Claude Code target's bodies except at the host conditionals.
- `agent/` — **the cast**: three role files (`implementer`, `reviewer`, `gate`), each carrying a per-role permission contract derived at emit time from the org config's `toolFilter.allow` (deny = the dangerous capabilities not allowed; `bash` becomes an allowlist of tracker reads + git reads), a per-role step cap, and the org's per-role model.
- `plugin/dispatch.js` — the delegation machinery: the role table (name → may it write, i.e. does it get a worktree), per-(repo, ticket) worktrees, the model policy enforced per call, ad-hoc ticketless read-only runs, and the on-disk delegation store.

The **process**, by contrast, is already data. The harness is neutral about it by
rule (`.forge.org.example.yaml`: the harness "does not hardcode the org's process;
it READS the operating model from the org wiki at runtime"), the skills already
describe the flow — prime → refine (agent-ready gate) → execute (decompose,
execution-ready gate, dispatch) → pre-merge gate — and the gates' rules are read
from the wiki, not baked into the skills.

So today's product is one move away from the thesis: the process is data, but the
**cast** — `agent/`, the `opencode.subagents` block, the per-role permission
derivation, the per-role caps and models in `lib/emit.py` — is still structure
the generator *bakes* rather than reads.

The critique that motivates this ADR (#23): with today's models, a fixed role
cast is old-school — "keep the graph, ditch the agents." The graph is the
contract; the cast was an implementation detail of weaker models. The alternative:
forge describes ONLY the process, as skills, and a single general agent wields
them when the process calls for them.

The method docs already concede the load-bearing parts:

- [`docs/ROLES.md`](../ROLES.md): "The forge method is the boundaries, not the names" — and "This isn't dogma."
- [`docs/GENERATOR.md`](../GENERATOR.md): "the boundaries were always the asset. What changes is the *delivery vehicle*," and no-self-review "was never a property of having six separate human sessions. It was a property of context isolation between the step that produces and the step that verifies."
- [`docs/METHOD.md`](../METHOD.md): forge is "opinionated about the agent collaboration pattern" — the pattern, not the personnel.

This ADR takes those statements at their word and asks: if the boundaries are
the asset and the names are not, what is still worth pinning per-archetype — and
where do those controls go?

## Thesis

**Keep the graph, drop the cast.** The emitted product on the opencode target
becomes: **the process as data** (the wiki operating model + the gates' rules,
already read at prime) + **the skills** (the procedures) + **the delegation
machinery** (dispatch, worktrees, the delegation store — unchanged in role).
All of it is wielded by **one general agent** — the primary agent the verbs
already run as (`opencode.primary_agent`).

The named archetypes stop being an emitted fixture. Where the graph needs
isolation, read-only enforcement, a budget, or a model floor, the requirement
attaches to the **node** — the step in the process (review, gate, harvest) — and
is enforced **at dispatch time** by the machinery, not by a persona file. A
node's contract is process data: *this step runs in a fresh context, sees only
the diff, may not write, is capped at N steps, runs at the org's floor.*

The cast was an implementation detail of weaker models: a fixed persona with
pinned permissions, steps, and model bought predictable behavior from models that
could not yet be trusted to follow a procedure. The bet of this ADR is that
current models can follow the graph — that a strong general agent, handed the
process and the machinery, plays the roles the process demands at the moment it
demands them. (What happens to that bet when the roster regresses is owned in
[What we lose](#what-we-lose).)

## The four load-bearing invariants

Each below: today's mechanism, the proposed design, what keeps it fail-closed,
and the residual risk. #23 demands an answer to each; the ADR does not get to
wave any of them through.

### 1. No-self-review

**Today.** The reviewer is a distinct subagent file, run in a separate context
via a separate dispatch; it sees the diff + the task spec, never the
implementer's reasoning. The emit fails closed around the mechanism: the
dispatch tokens the skills use must resolve to emitted agent files (the
post-render assertion in `lib/emit.py`), because a `task` agent name that
resolves to no file falls back to the **full-permission primary agent** — a
fail-open. [`docs/GENERATOR.md`](../GENERATOR.md) already names the true
property: *context isolation between the step that produces and the step that
verifies.*

**Proposed.** The invariant stays a property of the **review node in the
graph**, not a named archetype. The review skill requires a **fresh-context
invocation**: the skill body instructs the orchestrator to run the review as a
child run whose envelope is the diff + the spec — never this session's
reasoning — and the delegation machinery is what the skill uses to make that
true. opencode's subagent mechanism becomes an implementation detail the skill
invokes, not a named role file forge emits.

Concretely: `dispatch({ node: "review", ticket, ... })` creates a genuinely
separate session (the machinery already does exactly this for ticketed runs —
a fresh session per dispatch, the ticket as the envelope). The skill says
*what*; the node contract says *how the run must be shaped*; the machinery says
*that it ran that way*.

**Fail-closed posture.** Moves from emit time to graph-lint and dispatch time:

- the process data must mark the review node `fresh-context: true`; a doctor check refuses a graph whose review node shares context with its produce node — the same check [`docs/GENERATOR.md`](../GENERATOR.md)'s build order already demands for harvest phases;
- there is no "review inline" path for the machinery to offer: the review node's contract *is* the child run.

**Residual risk.** Today the isolation is guaranteed by a file existing and
resolving at emit; this ADR moves that guarantee to process data + machinery. If
the skill prose and the node contract drift apart, nothing at emit time notices
— the doctor check is new machinery that must be built and tested before the old
guard is deleted. This is a real weakening of the *locus* of enforcement, not of
the invariant (owned in [What we lose](#what-we-lose)).

### 2. Read-only validation

**Today.** Per-role permission blocks, derived at emit from each validating
role's `toolFilter.allow` in the org config: `deny = [edit, bash, task, dispatch,
webfetch, websearch] − allow`, with `bash` as an **allowlist** (the tracker
adapter's read commands + git reads; redirections and `--output` denied after
the allows). `task` is denied on purpose — a read-only reviewer that can spawn an
unrestricted writer launders writes. The config is load-bearing: an empty
allow-list, or a write capability inside one, fails the emit (the mutation
battery in `tests/test_opencode_emit.py`).

**Proposed.** The boundary attaches to the **node**, applied at dispatch time as
**session-level permission rules** — the exact mechanism the ad-hoc mode already
proves: `ADHOC_DENY` (edit/shell/subagent/dispatch denied at session create on
2.x; tool gates on the prompt body on 1.x), shipped through #20's dual-host
ad-hoc mode after #15 introduced the primitive and #17 the ad-hoc fork. When the
graph says a node is validating, dispatch creates that run with the read-only
deny set — whatever agent occupies it. One general agent, read-only when it
stands on a validating node.

The deny set itself survives nearly verbatim, because none of it was
persona-specific: it derives from the tracker adapter (the read commands) plus
the SCM reads — process-level data. The org config keeps declaring the validating
nodes' read surface (today `toolFilter.allow`; tomorrow the node contract); it
stays load-bearing under the same rule: a validating node with no declared
read-only contract fails emission — silence is fail-open and must not emit.

**Platform backstops** (branch protection, required reviews, CODEOWNERS) remain
the org-declared operating-model facet they already are ([`docs/GENERATOR.md`](../GENERATOR.md),
"decisions locked") — layered on top, never the primary mechanism.

**Residual risk.** Same locus shift as invariant 1: today a mis-declared role
fails the *emit*; tomorrow a mis-declared graph fails the emit (the node
contract must exist), but a machinery bug fails at *run* time. The read-only
bash allowlist's shape — whole-command matching, trailing redirection denies —
is subtle and currently tested per-role; it must be carried into the node
contract and re-tested there.

### 3. Step caps / budget discipline

**Today.** Per-role `max_steps` in each agent file's frontmatter — implementer
120, reviewer 40, gate 25 — overridable via `agents[].max_steps` in the org
config; a run that has not concluded by then answers in text.

**Proposed.** Caps attach to the node and are applied when dispatch creates the
run. The graph's process data declares a budget per phase: produce nodes get the
deep cap, validate nodes the shallow one. The numbers survive as **process
data**; only their keying changes (node, not persona). This is arguably more
honest about *why* a cap exists: review is capped at 40 because reviewing one
diff is bounded work — not because the agent "is a reviewer."

The org-level budget discipline is untouched: the operating model's **autonomy
budget** and **safety envelope** facets ([`docs/GENERATOR.md`](../GENERATOR.md):
per-workflow/per-day token+$ budgets, loop/round-trip depth limits, a human
kill-switch) were always org facets, never role properties, and the general agent
inherits them at prime as every agent does today.

**Residual risk.** A per-node cap is only as good as the graph data declaring
it. The proposal: **fail closed** — a produce or validate node with no declared
cap does not emit. (Today the default table in `lib/emit.py` silently supplies
120/40/25; the graph version should refuse silence rather than default it.)

### 4. Model policy

**Today.** Per-role `model` + `effort` pinned in each agent file's frontmatter;
the org-level floor — one provider (the `enabled_providers` allowlist in
`opencode.json`), the banned list — enforced per dispatch call by `resolveModel`
in `plugin/dispatch.js`; the floor surfaced in the skills via the
`MODEL_POLICY_*` scalars, with a standing rule that is already persona-free:
"Always set model explicitly on ad-hoc agent() calls; never leave it implicit."

**Proposed.** The org-level controls survive unchanged — they were never role
properties: the provider allowlist stays in `opencode.json`, the banned list
stays enforced at dispatch, the floor stays the default at session create. The
per-role pins go. Depth becomes a **node property**: where the graph wants a
deep run (produce), the node contract sets the model/effort explicitly;
everywhere else the org floor applies. The existing discipline survives verbatim
— model is set explicitly on every non-floor run, never implicit — and it is
*more* load-bearing now, because there is no per-role frontmatter to inherit
from silently.

**Residual risk.** Today a stage with no `agentType` and no explicit model can
silently land on a bad model (the skills already warn about exactly this case);
with no archetype frontmatter at all, *every* run is that case. The mitigation
is the rule plus the machinery: dispatch refuses an off-provider or banned model
per call — the floor is enforced by the tool, not by prose.

## The emit diff sketch (opencode target)

What changes in the emitted artifact if this ADR is accepted. Scoped to the
opencode target — a sketch, not an implementation plan; the accepting PR owns
that.

**Removed (or emptied):**

- `agent/` (the cast) — the three role files and their frontmatter contracts (permission blocks, step caps, models), sourced from `templates/opencode/agent/`. No agent files remain to name, so the filename-is-the-contract machinery (`rename_agent_files` and its post-render assertions) goes with them.
- The `opencode.subagents` block in the org config — per-role agent names, `toolFilter.allow`, personas — replaced by node contracts in the process data.
- The per-role permission derivation in `lib/emit.py` (`derived_deny`, `OC_FORBIDDEN_IN_READONLY_ALLOW`, the per-role deny arrays, `DEFAULT_MAX_STEPS` keyed by role) — replaced by one validating-node deny set, applied at dispatch.
- The per-role `agents[]` entries (model/effort/max_steps per archetype) — the block shrinks to the org floor.
- The dispatch role table's *names* — but not its shape: the table is already just `name → writes: true/false`; it becomes `node → writes: true/false` (produce/validate), the same two-kind table with better keys.

**Kept (the actual product):**

- `skill/` — the eight verb bodies, byte-identical across targets, org-renamable. The skills are the procedures the general agent follows; with the cast gone they are the whole behavioral product.
- The wiki graph as the product: the operating model read at prime, the gates' rules read from the wiki, the tracker adapter contract (the read-only bash allowlist derives from it — process data, not persona data).
- `plugin/dispatch.js` — the delegation machinery: per-(repo, ticket) worktrees, the ticket-as-envelope discipline, ad-hoc ticketless read-only runs, `dispatch_read`/`dispatch_list`, the model policy enforcement. It *simplifies* — fewer roles to allowlist; the role fork becomes the node fork — but stays the worktree/delegation machinery it is.
- `command/`, `AGENTS.md`, `plugin/reminders.js`, and `opencode.json`'s controls (the provider allowlist, the `task` deny — the orchestrator's only door to a child run stays `dispatch`).
- No-self-review, the human ADR/scope gate, code-as-truth, ephemeral-by-default — as invariants, unchanged.

**Added:**

- The graph as explicit data: node contracts (fresh-context, read-only, capped, model depth) for the validating nodes, read from the operating model / process data — no longer implied by which file exists.
- A `node:` dimension on `dispatch`: the review/gate/harvest invocations name the node they are running; the machinery applies that node's contract at session create.
- Doctor/graph-lint checks that inherit the emit's fail-closed posture: a validating node with no read-only contract does not emit; a review node sharing context with its produce node does not emit; a node with no declared cap does not emit.

## Failure modes: what the old design guarded against, and what guards it now

| The old guard | The failure it prevented | The new guard |
|---|---|---|
| The reviewer file denies `edit`/`bash`/`task`/`dispatch`, derived at emit; weakening config fails the emit | A validating agent edits the code, or launders a write by spawning an unrestricted writer | The validating node's deny set is applied at session create (the proven `ADHOC_DENY` mechanism); `subagent`/`dispatch` denied on the run, so no writer can be spawned from a review; a validating node with no read-only contract fails emission |
| The reviewer is a distinct subagent in a separate context | Self-review: the implementer's own reasoning anchors and rubber-stamps its own diff | The review node is `fresh-context: true` in the graph; dispatch creates a separate session with a diff-only envelope; doctor refuses a graph whose review runs in the producer's context; platform backstops per the org's declared facet |
| Agent filenames are the dispatch contract (`rename_agent_files` + post-render assertions) | A dispatch token that resolves to no file falls back to the full-permission primary agent — fail-open | No agent files to miss: dispatch creates sessions directly, attaching the node's permissions to the run rather than looking them up by name; the `task` deny stays, so `dispatch` remains the only door |
| Per-role `max_steps` (120/40/25) | A runaway or stuck run burns budget indefinitely | Per-node caps applied at dispatch from the graph's process data; a node with no declared cap does not emit; the org's safety-envelope facet (per-day budgets, loop depth, kill-switch) overlays everything |
| Per-role model pins + `resolveModel` at dispatch | A stage silently lands on a banned or off-provider model | The provider allowlist and banned list survive unchanged, enforced per dispatch call; the org floor is the session default; depth is set explicitly by the node contract, never inherited from a persona |
| `toolFilter.allow` must be non-empty and write-free (emit fails otherwise) | A "read-only" role that is silently permissive | The same rule re-keyed: a validating node must declare its read surface; silence fails emission — the fail-closed posture survives, moved from role config to graph data |

## What we lose

- **The locus of fail-closed.** Today the strongest guarantees are *emit-time*: a mis-declared org config refuses to emit, before any agent runs — a whole mutation battery proves it. This ADR moves much of that to dispatch time and graph-lint time. The posture (fail closed, never silently open) survives; the *moment* it fires moves later, where a machinery bug — not a config mistake — is what breaks it. We keep the guarantee but lose its earliest tripwire.
- **Pre-loaded contracts.** The role files carried curated discipline (TDD-first, anti-pattern lists, "you are read-only by construction") into context before the first token of work. A general agent must load the node contract at the moment the process calls for it — one more thing a strong model does right and a weaker model forgets. This is the core bet: **the cast was reliability bought from weaker models.** If the org's model roster regresses, the graph must re-grow the cast, or the org pins depth in node contracts until the roster recovers. Accept this ADR with that price tag on the table.
- **Inspectability.** Three files you can read, diff per release, and hand to a new engineer; a config block that fails loudly. The new product's behavior is more emergent — graph data + skill prose + machinery — and drifts silently where the old one failed loudly. The doctor/lint checks are the compensation, and they are new machinery that must be built and tested before the old guards are deleted.
- **Test coverage, temporarily.** A meaningful slice of `tests/test_opencode_emit.py` guards the per-role derivation (derived deny sets, `toolFilter` mutations, filename/dispatch-token resolution in both directions). That machinery — and its tests — dies with the cast. The equivalent node-level guarantees must be re-proven (new tests for the node-contract checks, the dispatch-time deny application, the fresh-context requirement) **before** the old tests are deleted, or coverage regresses on the exact invariants this ADR promises to preserve.
- **Axis 3 as a differentiation surface.** [`docs/GENERATOR.md`](../GENERATOR.md) names Roles ("who does what") as differentiation axis 3, and orgs rename and personify roles today (`opencode.subagents.*.agent` + personas). Collapsing the cast merges axis 3 into axis 4 (the operating model): orgs still differ in *what their graph demands*, but stop differing in *who* executes it. Some orgs will experience that as a simplification; others as a lost customization surface. Either way it is a real narrowing of the product's shape.
- **Cross-target symmetry, possibly.** On Claude Code, the cast survives as Workflow-stage archetypes that pin `agentType`/`model`/`effort` — the same pins this ADR removes on opencode. Accepting this for the opencode target means the two targets disagree about what the product *is*, unless the maintainer also adopts the thesis for the Claude Code target. That question is deliberately out of scope here; this ADR is scoped to the opencode emit and says so.

## Consequences

**Enables:**

- An emit that is all product — the graph, the skills, the machinery — with no baked structure the wiki does not already own.
- Simpler dispatch (node kinds, not a role allowlist); fewer files; no filename-as-contract failure class at all.
- Role-shaped work the org invents *without* an emit: a new gate is a wiki edit + a node contract, not a new agent file + config entry + re-emit.

**Forecloses / costs:**

- Per-archetype personas, permissions, caps, and models as emitted fixtures — gone.
- The emit-time tripwires for those fixtures — replaced by graph-lint checks that do not exist yet and must be built before the fixtures are removed.

**Known tradeoffs accepted (if the maintainer accepts this ADR):**

- The model-capability bet, named above, with node-contract depth pins as the hedge.
- The locus shift from emit time to dispatch/graph-lint time, compensated by new doctor checks.

## Alternatives considered

- **Keep the cast (status quo).** Rejected *as the proposal's answer* because the critique stands: the process is already data, and the cast is the one remaining place the generator bakes structure it could read. But the status quo remains fully functional and guarded — the maintainer keeping it is exactly what PROPOSED means.
- **Shrink the cast to one general-agent file.** Keep `agent/` with a single `general.md` (full tools, org floor). Considered and rejected as ceremony: the primary agent already is that file (`opencode.primary_agent`) — emitting a second copy of it adds a fixture with no boundary to carry.
- **Hybrid: one general agent + one retained validating archetype.** Keep a single named reviewer subagent as the one irreducible fixture; everything else becomes graph + skills. A serious contender — it keeps the strongest invariant at emit time while still deleting most of the cast. Rejected as the *primary* proposal because it preserves the fail-open-by-fallback class (a missed dispatch name still falls back to the full-permission primary agent) and keeps axis 3 half-alive. Worth revisiting if the node-contract machinery proves harder than sketched.
- **Platform backstops only.** Trust branch protection / required reviews; emit nothing that enforces isolation. Rejected: backstops are an org-declared *facet* ([`docs/GENERATOR.md`](../GENERATOR.md), "decisions locked"), not a substitute — an org that declines them gets nothing, and the failure modes above go unguarded.
- **Wait for the models to make it obvious.** Deferred-decision is real and cheap. Rejected as the *proposal* because the question is already live (#23), and the invariant-preserving design above is what makes waiting safe: the graph, the node contracts, and the doctor checks are worth building even if the cast is kept — they are how either design gets *audited*.

## References

- Tracker ticket: ktoulgaridis/forge#23 — the thesis, the four invariants, and the deliverable this ADR answers.
- Method docs: [`docs/METHOD.md`](../METHOD.md) — the method: the collaboration pattern over the tools; the three invariants; skills as verbs. [`docs/ROLES.md`](../ROLES.md) — why explicit roles existed, and "the boundaries, not the names." [`docs/GENERATOR.md`](../GENERATOR.md) — the v2 north star: context isolation as the true no-self-review; platform backstops as a facet; the four axes.
- Code ground truth: `lib/emit.py` (the per-role derivation, `DEFAULT_MAX_STEPS`, the filename contract), `templates/opencode/agent/` (the cast), `templates/opencode/plugin/dispatch.js.template` (the delegation machinery + `ADHOC_DENY`), `templates/opencode/opencode.json.template` (the allowlist + `task` deny), `.forge.org.example.yaml` (the neutral-harness rule), `tests/test_opencode_emit.py` (the mutation battery this ADR retires).
- History: #15 (the dispatch primitive), #17 (ad-hoc ticketless read-only delegations), #20 (the dual-host ad-hoc mode — `ADHOC_DENY` at session create, the mechanism this ADR generalizes).
