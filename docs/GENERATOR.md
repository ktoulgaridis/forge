# forge as a generator (v2 north star)

> **Status:** design north star for forge v2. Not all of this is built. This doc is the spine that "build as we go" builds against. Where it conflicts with older docs (`SESSIONS.md`, `ROLES.md`, `METHOD.md`, the older parts of `README.md`/`CONTRIBUTING.md`), **this doc wins** and those docs are being reframed to match.

## The one-sentence shift

forge v1 *stamped a project wiki*. **forge v2 is a generator: it interviews an organization and emits a standalone, org-owned Claude Code plugin** that aligns the agent harness to *how that organization actually works*.

Tagline: **"align Claude Code to your org and its operational model."**

## Two levels, kept unmistakably separate

```
  forge  (the GENERATOR) ─────────────────────── OSS, identical everywhere
    install it → /forge:emit → it interviews your org → it EMITS:   ▲
        │                                                            │ improved
        │                                                            │ upstream
        ▼                                                            │ by all,
  ┌──────────────────────────────────────────────┐                  │ nobody
  │  acme-forge  (the GENERATED PACKAGE)           │ ◄── differs ─────┘ forks
  │  org-owned, private, distributed internally    │     per org
  │                                                │
  │   • its own plugin.json (org-namespaced)       │
  │   • its own marketplace.json (internal dist)   │
  │   • pinned adapters (the org's real tools)     │
  │   • the OPERATING MODEL  ← the new 4th layer   │
  │   • wiki templates                             │
  │   • the single-orchestrator workflow runtime   │
  │   • commands: /new, /doctor, /configure        │
  └──────────────────────────────────────────────┘
```

- **The generator** is the shared, eventually-open-source tool. Everyone improves it upstream: new adapters, new method refinements, new operating-model facets, better runtime templates, a better emitter. It is the *same tool everywhere*.
- **The generated package** (`acme-forge`) is private and org-owned. The org installs and distributes it as its internal standard; teams stamp projects *from it*, not from upstream forge.
- **`forge@Acme ≠ forge@Globex` by design** — same generator, different answers to the interview.

**Nobody forks forge.** To upgrade, an org *re-runs the generator* over its existing config; the generator re-emits the package, rebasing the org's choices onto the newer generator. (This is the correction to the v1 "extend then distribute by manual fork/vendor" framing, which is now the anti-pattern.)

### Two-tier config

The generator/package split forces config — *and knowledge* — into two tiers:

| Tier | Config | Knowledge | Lives |
|---|---|---|---|
| **Org** | `.forge.org.yaml` — pinned tools, methodology, **operating model**, default roles, compliance regime | the **org-wide layer** of the wiki (operating model + accumulated tribal knowledge) | baked/seeded into the emitted package; accumulates under org ownership |
| **Project** | `.forge.config.yaml` — codename, streams, target repos | a **project subspace** in the wiki (this engagement's architecture, ADRs, themes, services) | collected per engagement by the package's `/new` |

The org tier is **seeded once** by the generator (org schema + operating model rendered from the interview + section skeletons) and **accumulates** thereafter. **Re-emit rebases the org-wiki *schema* without ever overwriting accumulated tribal knowledge** — the knowledge-layer expression of "re-generate to upgrade, never fork."

### `/forge:new` relocates, it does not die

In v1, `/forge:new` was forge's only generative command (it stamped one project wiki). In v2:

- The new generative entry point is **`/forge:emit`** — its output is the org plugin repo.
- **`/forge:new` becomes a command *inside* the emitted package** — it opens a new **project subspace** in the org wiki (under `projects/<codename>/`) using the org's *pinned* tools and operating model, and registers it in the org wiki's `projects/` index. The capability is relocated, not deleted.

## The four differentiation axes

forge v1 had three axes; two orgs could share all of them. v2 adds the fourth, which is what actually makes orgs differ.

| # | Axis | Question it answers | Shared across orgs? |
|---|---|---|---|
| 1 | **Adapters** | *Which tools?* (tracker / SCM / chat / CI) | often |
| 2 | **Methodology** | *Which process shape?* (kanban / scrum / rfc-first / formal-methods) | often |
| 3 | **Roles** | *Who does what?* (the archetype boundaries) | often |
| 4 | **Operating model** | ***How do agents behave as members of this org?*** | **this is the differentiator** |

Two orgs both on Jira + GitLab + Slack + kanban + the same six role archetypes still produce different packages — because their **operating model** differs. That is the heart of org-differentiation.

## The operating model (the new fourth layer)

The operating model captures *how agents behave as organizational actors*. It is **not** folded into the methodology bundle (methodology = process *shape*; operating model = *behavior*). It is captured by **interview** and lives in the **wiki** as a near-constitutional page (`operating-model.md`) that every agent reads at prime.

### Facets the interview captures

These are *questions the generator asks the org*, not hardcoded defaults. The answers vary wildly between shops — the generator's job is to ask, not to assume.

1. **Inter-agent communication** — *how do agents coordinate with each other and with humans?* One shop runs everything through Jira tickets + comments like employees; another uses a Discord server; another keeps it ephemeral. **This must be fully generalizable** — adapter-shaped, pointed at whatever medium the org runs. forge does not ship a "default medium."
2. **Identity & attribution** — *who do agent actions appear as?* (See [Identity](#identity-is-dynamic-not-provisioned) — this one changed shape under the workflow runtime.)
3. **Formal process** — work states + allowed transitions, approval gates per transition, RACI sign-off per artifact, the org's Definition of Done, change-control discipline.
4. **Escalation & human-in-the-loop** — the enumerated triggers that must stop and surface to a human (scope change, ADR decision, security surface, cost over threshold, ambiguous acceptance), where they go, and whether they block.
5. **Autonomy budget** — the standing leash: max self-complete size, self-merge policy, spend/blast-radius limits, prod-action prohibition, parallelism caps.
6. **Cadence & ceremonies** — standup/status cadence + audience, release/freeze windows, consolidation-pass timing.
7. **Etiquette & redaction** — tone/register, @-mention rules, threading discipline, PII/secrets redaction, off-limits channels/repos.
8. **Safety envelope** — per-workflow/per-day token+$ budgets, agent-to-agent loop/round-trip depth limits, a human kill-switch.

### How a facet becomes behavior

The mechanism is **interview → wiki → dynamic runtime**, not baked presets:

```
  interview answer  ──►  operating-model.md  ──►  read at prime  ──►  workflow runtime
   (the org speaks)      (durable wiki page)      (every agent)        (behaves accordingly)
```

- A facet generates a section in the durable `operating-model.md` wiki page (the constitution).
- The hard, machine-checkable distillates get injected into the project `CLAUDE.md` (no-transition-without-gate, redaction list, prod-actions-forbidden, …).
- Where enforcement must be mechanical, hooks/scripts carry it.

**Presets are a crutch.** The real thing is the interview plus the wiki. The generator may offer named starting points for convenience, but the source of truth is *what the org answered*, captured durably in the wiki and read dynamically at runtime.

## The org brain (durable tribal knowledge)

> **North star:** *the org brain is durable and gated — durability is earned by citation, not granted by capture.*

The wiki is **not** a per-engagement artifact stamped fresh and discarded when a project ends. It is **the org's brain**: the durable, accumulating body of *tribal knowledge* acquired by any developer — human **or** agent — *during the act of development*. The gotchas, the "why service X is weird," the hard-won debugging lessons, the "how we actually do auth here" — everything that normally evaporates into Slack threads, people's heads, and closed tickets. The wiki captures it, keeps it, and makes it the substrate the next developer (human or agent) primes against.

This is an **elevation** of the v1 wiki, not a rewrite: every v1 invariant (code-as-truth, no claim without citation, the wiki-maintainer, `lint --consolidate`) survives and is *reused* to make the org brain trustworthy at scale.

### One wiki, two layers

The org brain is **one wiki with a project layer** — projects are separated *internally*, not scattered across separate repos:

```
  THE ORG BRAIN  (one wiki — durable, org-owned, accumulates over years)
  │
  ├── org-wide layer            ← cross-project tribal knowledge
  │     CLAUDE.md                 (the org schema: promotion gate, citation class, caps)
  │     operating-model.md        (the constitutional chapter — see below)
  │     standards/  gotchas/  patterns/  decisions/  glossary.md  tooling/
  │     legacy/                   (archived knowledge + promotion provenance)
  │
  └── projects/                 ← THE PROJECT LAYER (internal separation)
        <codename>/               each engagement, separated internally:
          CLAUDE.md                 (project schema + upward inheritance line)
          architecture.md  decisions/  themes/  services/
```

The relationship is **strictly directional**: a project subspace may **cite** org-wide pages (read "up", like citing a standard) and **promote** generalized lessons up through a gated verb. The org-wide layer never reaches *into* a project except as an evidence citation. Closing a project **archives its subspace** (read-only, still queryable) without touching org-wide knowledge.

> **Scale note.** One wiki with a project layer is the model. The `projects/` index and the sensitivity partitions are designed so that *if* an org ever hits true scale, a project subspace can **relocate** to its own repo with no schema change. Physical sharding is a deferred deployment knob — nobody pays that complexity until scale forces it.

### Operating model vs. tribal knowledge — same brain, different chapters

`operating-model.md` and the tribal-knowledge body are the **same brain**; they differ by *edit discipline*:

| | Operating model | Tribal knowledge |
|---|---|---|
| **Nature** | how we are **governed** (law) | how we **work** (craft) |
| **Edit discipline** | constitutional: amendment-only, human-ratified (ADR-style) | descriptive: MR-driven, grows continuously |
| **Litmus test** | violating it should **halt** an agent (a gate, a limit, a prohibited action) | it makes an agent **smarter/faster** (a pattern, a pitfall, a convention) |

The operating model is **not** a fourth Karpathy layer — it's the fourth *differentiation axis*, living inside the wiki as its constitutional chapter.

### Capturing tribal knowledge

v1 grew the wiki one way: a code MR paired with a wiki MR. That captures project *facts* but structurally **cannot** capture tribal knowledge — dead-ends and gotchas never produce a code diff to pair against, and the agent that learned them is ephemeral. v2 adds the missing pathway, anchored to the workflow runtime:

- **Subagents return a structured `learnings[]` array** alongside their work-product, written to a workflow-owned scratch file (`pending/learnings/<run-id>.jsonl`).
- **The orchestrator holds only the *path*, never the contents** — reading raw learnings into the one long-lived session is the exact context-bloat anti-pattern. After the produce phase, it dispatches *one* thing: a **wiki-maintainer (harvest) subagent** pointed at that file.
- The harvest maintainer runs in its **own isolated context** — it never saw the implementer's reasoning, only the structured learnings + the diff to cite against. **The same context isolation that protects review quality (no-self-review) protects capture quality** (the maintainer judges learnings it did not author).

Each learning carries: `kind` (gotcha / dead-end / decision-rationale / env-quirk / debugging-insight / convention), `claim`, `reuse_trigger` (a future agent hits this when…), `context_envelope` (the conditions under which it holds), `citation` (code / artifact / speculative), `sensitivity`, and an `emitted_by` attribution marker (wiki-driven identity, not credentials).

Two other pathways feed the same judge: a **`/wiki capture`** verb for out-of-band human capture (a postmortem, a "never do X again"), and **adapter-shaped ingestion** from ticket comments / chat (same adapter contract, under `adapters/knowledge/` — forge ships the contract, never a default source).

### Code-as-truth is the *promotion* gate

The key move that lets the brain hold soft tribal knowledge **without** reopening the wiki-rot hole: **capture is cheap, durability is earned.**

- A learning is **captured** freely (project-local, discardable).
- It is **promoted** into the durable brain only with a citation: **code** (gold standard) → admitted; **durable artifact** (ADR, postmortem/incident id, merged PR, benchmark, trace, ticket) → admitted, phrased as *observed-behavior-at-artifact*; **speculative** → routed to a **quarantine** page — searchable via `/wiki query`, marked UNVERIFIED, **never** cited as truth and **never** injected into `CLAUDE.md` distillates. A quarantined item promotes only when a later workflow produces the confirming citation.
- The promotion gate uses a **separate context** from capture (reuse no-self-review-by-isolation): the agent that captured a learning is never the one that promotes it.

### Rot controls at org scale

An everything-accumulates-forever store is the canonical wiki-rot deathtrap. The mechanisms that keep the brain accurate, small, and trustworthy:

- **Consolidation shards, never global** — the org-wide maintainer sees only the small org-wide layer; each project subspace consolidates itself. A hard **org-wide-learnings cap** creates eviction back-pressure; new learnings diff only against k-nearest neighbors (index-driven, not an O(n²) full walk).
- **Decay metadata** — every org learning carries `captured_date` / `last_verified` / TTL → states VERIFIED / STALE / ARCHIVED-not-deleted, with a freshness banner at read ("last verified 2024-03; source project CLOSED — treat as unverified"). If the cited code path no longer exists, auto-flag STALE.
- **Contradiction → context-qualified, not a winner-takes-all** — two learnings that disagree are kept side-by-side, each scoped to its `context_envelope` ("X is fast under read-heavy <10k QPS; slow under write-heavy >100k"). Only *genuinely overlapping* envelopes are a real conflict, escalated to an org-declared adjudicator (an operating-model facet; **default-deny** promotion if none declared).
- **Sensitive-knowledge scoping (default-deny)** — every learning gets a sensitivity tier at capture; a write-blocking redaction/secret scanner runs *before* the write; **security weaknesses are cited (ticket id), never restated** as durable narrative; agent prime reads are scoped to the workflow's authorization. `/forge:doctor` fails emission if the org store has no declared sensitivity scoping.
- **No SPOF / no contention** — append-only learning files (unique id, supersede rather than rewrite; only the generated index is recomputed); org-store reads **degrade gracefully** (an agent that can't reach the org layer proceeds on the project subspace — the brain is an *enrichment*, never a hard dependency); promotion is async/batched so **no workflow ever blocks** writing a learning.

## The runtime: one orchestrator, dynamic workflows

The emitted package's runtime is **a single long-lived master orchestrator that spawns dynamic workflows** — not a human hand-running six terminal sessions. The newer Claude Code primitives (the Workflow tool, subagents, structured output) make the multi-session fleet unnecessary.

### Roles survive — as subagent archetypes, not sessions

The six role archetypes (orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst) and **their boundary files survive** — the boundaries were always the asset. What changes is the *delivery vehicle*: a role is now a **distinct subagent inside a workflow** (with its own prompt, tools, and context), not a separate human-run session.

### No-self-review is preserved — it was never about sessions

The load-bearing insight: **"no self-review" was never a property of having six separate human sessions. It was a property of context isolation between the step that produces and the step that verifies.**

A workflow preserves it structurally:

- The **implementer** subagent writes the diff in its own context.
- The **reviewer** subagent runs in a *separate* context and sees only the *diff/MR pointer* — never the implementer's reasoning.
- Independence holds because the reviewer cannot anchor on reasoning it never saw.

It **regresses only** if a single agent loop implements-then-reviews its own diff in one context — the exact anti-pattern forge has always forbidden. `/forge:doctor` (and a runtime guard) must refuse to stamp or run a workflow whose review phase shares context with its implement phase.

Whether *platform backstops* (branch protection, required reviews, CODEOWNERS) are layered on top is itself an **operating-model facet the org declares** — not a fixed mechanism forge bakes in.

### Identity is dynamic, not provisioned

Under the multi-session model it was tempting to provision per-role service accounts (one login per role). **Under the workflow runtime that dissolves:** there is effectively *one tool identity* — whatever the master-orchestrator session authenticates as. Subagents are ephemeral compute inside the orchestrator's tool access; they don't each log in.

So identity reduces to:

- **One orchestrator identity** — and the one piece of the old advice that survives is *use a dedicated bot identity, not a human's account*. Acting under a human's account collapses the audit trail and hands agents full human privilege; it is incompatible with regulated bundles. (This is the correction to the early-session idea of agents acting under the human-in-charge's account.)
- **Wiki-driven attribution** — which archetype did what is recorded by *markers in the durable trail* (comment prefixes like `[forge/implementer]`, commit trailers), dynamically, read from the wiki/operating-model — not by separate credentials.

Dynamic and wiki-driven, exactly as it should be.

### Streams degrade gracefully

Streams (A=backend, B=frontend, …) were parallel *human-run* tracks in v1. Under one orchestrator they degrade to a **collision-avoidance partition key** (don't dispatch overlapping tickets into the same files) plus organizational labels. The orchestrator can still fan out concurrent subagents within a workflow; streams stop being "real wall-clock parallel sessions."

## What survives / changes / dies

**Survives (unchanged, central):**
- The Karpathy three-layer schema (raw sources / wiki / `CLAUDE.md`) and code-as-truth discipline — now *federated* across an org-wide layer and project subspaces, with code-as-truth holding at both (and serving as the *promotion* gate into the org brain).
- The six role *archetypes* and their boundary files.
- The three skill verbs (`prime` / `dispatch` / `wiki`) and prime-then-work-from-durable-substrate.
- The adapter contract shape (declarative frontmatter + `{{...}}` snippets + doctor checks + `_test/` fixtures) — reused for the operating-model overlay.
- The `{{...}}` renderer.
- No-self-review and the human ADR/scope gate **as invariants** (their enforcement changes; the rules do not).
- Ephemeral-by-default + durable-substrate-of-record resilience — re-expressed for subagents.

**Changes form:**
- The emitted artifact: from a project wiki to a standalone org-owned **plugin repo**.
- The knowledge surface: from a per-engagement wiki to **one durable org brain with a project layer** — org-wide tribal knowledge + per-project subspaces, accumulating over years.
- The wiki grows a new **capture pathway** (workflow harvest of subagent `learnings[]`) and a `capture`/`promote` verb, on top of the v1 paired-MR path.
- Config: splits into org-tier (`.forge.org.yaml`) vs project-tier (`.forge.config.yaml`).
- The runtime: from a human-run TeamCreate fleet to a single orchestrator + dynamic workflows.
- `dispatch`: default flips from `mode=team`/TeamCreate to *invoking a workflow* with distinct subagents.
- Role separation: re-expressed as *intra-workflow context isolation* (+ optional platform backstops) instead of session identity.
- `plugin.json`: from a static single-owner file to a templated, org-namespaced manifest the emitter mints.
- Methodology bundles: promoted to first-class org config, composable *with* (not part of) the operating model.

**Dies:**
- The prose, non-deterministic `/forge:new` wizard as the *generative entry point* (reproducibility is now required; emission must be deterministic).
- The framing that forge's only output is a per-engagement wiki — *and* that the wiki dies with the engagement (it now persists as the org brain).
- The orchestrator ever holding raw subagent learnings in its own context (it holds only the scratch-file path; a harvest subagent judges them).
- "Different sessions, different role primes" as the *literal mechanism* for independence (the principle survives; the six-terminal UX does not).
- `mode=team`/TeamCreate as the universal dispatch default.
- The assumption that streams imply real parallel human-run sessions.
- Agent actions defaulting to a human's account with no attribution.

## Foundation build order

Tight by design — get the basics right, then build as we go.

**must-have-now (the bones):**
1. **This doc** — the north star. ✅
2. **`commands/emit.md`** — `/forge:emit`, the generative entry point that writes the org plugin repo and validates it (`claude plugin validate --strict`). The single most load-bearing new file.
3. **`templates/org-plugin/.claude-plugin/plugin.json.template`** — the org-namespaced manifest the emitter mints.
4. **`templates/org-wiki/operating-model.md.template`** — the durable org-constitution chapter (the org brain's first page), one section per facet.
5. **`templates/org-wiki/CLAUDE.md.template`** — the **org schema**: the promotion gate, the tribal-knowledge citation class, the org-learnings cap, and the litmus test (*halts an agent → constitutional; makes an agent smarter → tribal knowledge*). The project-wiki schema gains an upward inheritance line + a `projects/` subspace.
6. **`.forge.org.example.yaml`** — the org-tier config carrying the `operating_model:` block (incl. the `knowledge_capture:` sub-block); re-scope `.forge.config.example.yaml` to project-tier only + an `org_wiki:` pointer.
7. **`templates/org-plugin/.claude/workflows/ship-ticket.js.template`** — the reference dynamic workflow (research → plan → implement → verify, each a distinct subagent) encoding no-self-review-by-context-isolation, **plus a terminal harvest phase** that hands the `learnings[]` scratch file to a wiki-maintainer subagent.

**soon:**
- Flip `dispatch/SKILL.md.template` from TeamCreate to workflow-invocation.
- Inject `## Operating model` into `CLAUDE.md.template`; load `operating-model.md` (org-wide) + relevant standards/gotchas, then the project subspace, in `prime`.
- The **learnings contract** (`templates/org-plugin/.claude/contracts/learnings.schema.json.template`) + the fifth wiki verb `capture` + `promote` flow + a wiki-maintainer **"Learnings triage"** section.
- Extend `doctor.md`: validate the emitted plugin, lint the operating-model block, **fail a workflow whose harvest phase shares context with a produce phase** (the no-self-review guard for capture), **fail emission if the org store has no declared sensitivity scoping**, crash-recovery test.
- **Re-cut `README.md` + `CONTRIBUTING.md`** off the fork/vendor framing onto the generator framing.

**later:**
- Reframe `SESSIONS.md` (multi-session → orchestrator+workflows) and `ROLES.md` (sessions → subagent archetypes); add the fourth layer + runtime + federated wiki to `METHOD.md`.

## Decisions locked

- **In-place major v2** of the same repo (not a parallel `forge-gen`). Method/schema/roles/adapter-contract survive; the artifact kind, runtime, and config tiering change.
- **Identity is dynamic + wiki-driven**, one dedicated (non-human) orchestrator identity + attribution markers. No per-role account provisioning; no acting under a human's account.
- **Comms medium is fully generalizable** (tickets / chat / Discord / ephemeral / …), interviewed per org, never a baked default.
- **No-self-review = context isolation between distinct subagents**, with platform backstops as an org-declared facet rather than a fixed mechanism.
- **The wiki is the org brain: one wiki with a project layer** (projects separated internally), durable and accumulating. Durability is *earned by citation* (code / artifact / 2+-engagement evidence), not granted by capture; tribal knowledge enters via a **context-isolated harvest**, never through the orchestrator's memory.
- **Two org-brain forks are per-org interview facets, not baked defaults** — *who adjudicates cross-project truth* (default-deny promotion if unset) and *capture default-on vs trigger-gated* (defaults to trigger-gated). Both ship with safe defaults; the org answers them at interview.

## See also

- [`METHOD.md`](METHOD.md) — the universal method (being reframed for the runtime).
- [`METHODOLOGY.md`](METHODOLOGY.md) — methodology bundles (axis 2), composable with the operating model.
- [`ADAPTERS.md`](ADAPTERS.md) — the adapter contract (axis 1), reused for the operating-model overlay.
- [`ROLES.md`](ROLES.md) — the role archetypes (axis 3), now delivered as subagents.
