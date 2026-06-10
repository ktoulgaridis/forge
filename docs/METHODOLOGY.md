# Methodology bundles

Forge's templates are **Kanban-shaped by default** today. Bundles let projects swap in a different methodology — adjusting ticket templates, sizing units, status filters, role additions, wiki structure additions, and traceability rules — without touching the core method (Karpathy schema, role pattern, skill verbs).

Status: **roadmap. Not implemented in v0.1.x.** This doc sketches the design so the next-session work has a starting point.

## The four bundles

| Bundle | Used by | Status |
|---|---|---|
| **kanban** | Default; agile teams without sprints | ✅ implicit (current templates) |
| **scrum** | Agile teams with sprints + story points | 🔜 roadmap |
| **rfc-first** | Teams requiring written design before tickets | 🔜 roadmap |
| **formal-methods** | Regulated / safety-critical / enterprise QA shops | 🔜 roadmap **(must-have for regulated industries)** |

## What a bundle changes

A bundle is a declarative overlay applied at `/forge:new` time (and via `/forge:configure` later). It adjusts:

| Layer | Bundle effect |
|---|---|
| **Ticket template body** | Sections required (Story, Acceptance, Definition of Done, Linked artifacts, etc.) |
| **Sizing unit** | story-points / agent-hours / t-shirt / formal-effort-bands |
| **Status filters in skills** | "To Do / In Progress / Done" vs. sprint-aware vs. gate-aware |
| **Wiki dir additions** | scrum: nothing extra; rfc-first: `rfcs/`; formal-methods: `requirements/`, `specifications/`, `verification/`, `validation/`, `traceability/` |
| **Role additions** | scrum: nothing extra; rfc-first: `rfc-author` (custom role); formal-methods: `requirements-engineer`, `verifier`, `validation-lead` |
| **Workflow gates** | scrum: sprint commit; rfc-first: RFC must merge before tickets; formal-methods: trace coverage gates each artifact transition |
| **CLAUDE.md schema clauses** | Bundle-specific invariants (e.g., "every specification cites a requirement") |
| **Tracker queries** | Sprint-aware for scrum; gate-aware for formal-methods |

## Bundle: scrum

- **Sizing:** Fibonacci story points (1, 2, 3, 5, 8, 13)
- **Sprint cadence:** declared in `.forge.config.yaml` (sprint length, start day)
- **Statuses:** "Backlog / Sprint Backlog / In Progress / In Review / Done"
- **Skill filters:** orchestrator's queue view filters to active sprint
- **Roles:** add `scrum-master` (custom role) for ceremony facilitation
- **Tracker:** Jira sprints, Linear cycles, GitHub Projects iterations all map cleanly

## Bundle: kanban (default)

- **Sizing:** agent-hours (1h, 3h, 8h, spike) — what's already in templates
- **Statuses:** "Backlog / Ready / In Progress / In Review / Done"
- **No sprint:** continuous flow
- **WIP limits:** optional, declared in `.forge.config.yaml`

## Bundle: rfc-first

- **Workflow gate:** every theme requires a merged RFC before tickets are filed
- **Wiki dir:** `rfcs/` with template (Problem, Proposal, Alternatives considered, Open questions, Decision)
- **Role:** add `rfc-author` (custom) — drafts RFCs, shepherds discussion
- **Architect:** still owns ADR cutting, but ADRs reference RFCs
- **Skill change:** `/dispatch` refuses to dispatch implementation tickets until the theme's RFC has merged
- **Used by:** teams that prefer written discussion over verbal alignment (Stripe-shaped culture)

## Bundle: formal-methods

The non-negotiable bundle for regulated and safety-critical shops. Models the artifact cascade explicitly with traceability.

### Artifact cascade

```
USER NEEDS                       (what stakeholders need, in business terms)
    ↓ traces to
REQUIREMENTS                     (what the system shall do, testable)
    ↓ traces to
SPECIFICATIONS                   (how the system shall do it, design-level)
    ↓ traces to
IMPLEMENTATION                   (code, with test cases)
    ↓ traces to
VERIFICATION                     (proves spec is met — unit + integration tests + reviews + analysis)
    ↓ traces to
VALIDATION                       (proves user need is met — end-to-end + UAT + field testing)
```

Every artifact at level N cites its parent(s) at level N-1.

### Wiki dir additions

```
requirements/
  REQ-NNN-<slug>.md            (per-requirement, with frontmatter linking user-need IDs)
specifications/
  SPEC-NNN-<slug>.md           (per-spec, links REQ IDs)
verification/
  VER-NNN-<slug>.md            (test plans + reports, links SPEC IDs)
validation/
  VAL-NNN-<slug>.md            (UAT + field-test plans + reports, links USER-NEED IDs)
traceability/
  matrix.md                    (auto-generated cross-reference matrix from frontmatter)
  gaps.md                      (which requirements have no spec yet, etc.)
```

### Role additions

- **`requirements-engineer`** — owns `requirements/`. Translates user needs into testable requirements. Cannot author specs (handoff to spec writer).
- **`verifier`** — owns `verification/`. Replaces or augments `reviewer`: not just checking code quality, but proving the spec is met via test artifacts. Cites SPEC IDs. Cannot validate (different role).
- **`validation-lead`** — owns `validation/`. Proves user needs are met. Coordinates UAT, field tests, customer sign-off.

The default `architect` role becomes the **specifications author** in formal-methods; ADRs become specification documents.

### Workflow gates

`/dispatch` enforces:
- Cannot dispatch an implementation ticket without a SPEC ID (which itself must trace to REQ IDs which trace to USER-NEED IDs)
- Cannot close a code MR without a linked verification artifact
- Cannot close a theme without validation evidence

Trace coverage is auditable: `/wiki lint --trace` (a formal-methods-specific lint) outputs gaps.

### Sub-variants

Different formal-methods regimes have different specifics. Bundle parameters:

```yaml
methodology:
  type: formal-methods
  variant: v-model           # v-model | iec-62304 | do-178c | iso-26262 | custom
  config:
    safety_class: B          # IEC 62304 software safety class
    # OR
    dal_level: C             # DO-178C Design Assurance Level (A-E)
    # OR
    asil_level: B            # ISO 26262 Automotive Safety Integrity Level
    # OR
    custom_phases:           # for custom regime
      - { id: USER-NEED, prefix: UN }
      - { id: REQUIREMENT, prefix: REQ }
      - { id: SPECIFICATION, prefix: SPEC }
      ...
```

Each sub-variant adjusts the artifact pyramid slightly:
- **V-model** — strict cascade; verification mirrors the descent (unit tests verify spec, integration tests verify req, system tests verify user need)
- **IEC 62304** — medical-device-specific; software safety class drives test rigor
- **DO-178C** — aviation; DAL level drives objectives + test depth
- **ISO 26262** — automotive; ASIL level drives effort
- **Custom** — shop defines its own pyramid; forge enforces traceability between declared phases

### Implementation cost

Building this bundle is the largest single piece of work in the methodology roadmap. Estimate: 3-5 days of agent work for the templates + skill snippets + lint extension + at least one sub-variant (V-model) shipped end-to-end. Sub-variants beyond V-model are incremental.

### Why must-have

For shops in regulated industries (medical, aviation, automotive, defense, financial services with SOX, government), formal-methods compliance is **not optional**. forge as currently scoped would not work for these orgs. They are also exactly the orgs that benefit most from agent-driven orchestration because their compliance overhead is high and trace-discipline-suited to mechanical enforcement.

## Shop-specific overrides

Bundles are not all-or-nothing. A project can:

- Apply a base bundle (e.g., kanban) and layer a partial overlay (e.g., "we want kanban for engineering tickets but RFC-first gates for any architectural change")
- Customize role definitions per the bundle (e.g., kanban + a custom `compliance-officer` role)
- Adjust trace requirements (e.g., formal-methods with relaxed validation requirements for prototypes)

Overrides live in `.forge.config.yaml` under the `methodology.overrides` block. The `/forge:configure` skill handles this; `/forge:doctor` reports trace gaps if overrides break invariants.

## Roadmap order

1. Implement **scrum** bundle first — well-understood, clear precedent (Atlassian Jira workflows, Linear cycles)
2. Implement **rfc-first** second — small lift, high value for some shops
3. Implement **formal-methods / V-model** third — biggest lift, needed before forge can claim "regulated industries"
4. Add **iec-62304 / do-178c / iso-26262** sub-variants on demand as shops materialize

## See also

- [METHOD.md](METHOD.md) — the underlying method (universal across bundles)
- [ROLES.md](ROLES.md) — role pattern (bundles add specific roles)
- [USAGE.md](USAGE.md) — daily ops (bundles affect cadence + ceremonies)
