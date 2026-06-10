# forge

**Align Claude Code to your org and its operational model.**

[![validate](https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml/badge.svg)](https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml) [![release](https://img.shields.io/github/v/release/ktoulgaridis/forge)](https://github.com/ktoulgaridis/forge/releases) [![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

forge is a **generator**. It interviews your organization — which tools you run, which process shape you're held to, and *how your org actually works* (how agents communicate, under what identity they act, what gates and autonomy govern them) — and **emits a standalone, org-owned Claude Code plugin** that makes agent-driven development behave like a member of *your* org.

> **forge v2 is a generator, not a scaffolder.** The full design lives in [`docs/GENERATOR.md`](docs/GENERATOR.md) — the authoritative north star. Some of v2 is still being built; v0.1.x ships the v1 flow.

Two levels, kept separate:

- **forge — the generator** (shared, eventually open source, the *same tool everywhere*). Everyone improves it upstream: adapters, methodology bundles, operating-model facets, runtime templates.
- **`acme-forge` — the generated package** (org-owned, private, distributed internally). Your tools, your operating model, your compliance regime, baked in. Teams stamp projects *from it*.

`forge@Acme ≠ forge@Globex` **by design** — same generator, different answers to the interview. Nobody forks forge; to upgrade, an org **re-runs the generator** over its config and re-emits.

A Claude Code plugin. `/forge:emit` interviews your org and writes the package; inside that package, `/forge:new <codename>` stamps a per-project wiki using the org's pinned tools and operating model.

## What forge emits when you `/forge:emit`

A standalone, **org-owned Claude Code plugin** (`acme-forge`) — the artifact your org installs and distributes. It contains:

1. Its own `.claude-plugin/plugin.json` + `marketplace.json` (org-namespaced; for internal distribution).
2. The **pinned adapters** for the org's real tools (tracker / SCM / chat / CI) — not re-chosen per project.
3. The **operating model** — how *your* org's agents behave (comms, identity, gates, autonomy), rendered from the interview into a constitutional wiki chapter + machine-checkable rules.
4. The **org brain** seed — one durable wiki (operating model + accumulating tribal knowledge) with a **project layer** (`projects/<codename>/`).
5. The **single-orchestrator workflow runtime** — `.claude/workflows/*.js` the master orchestrator invokes; role archetypes (implementer / reviewer / architect / wiki-maintainer) run as *distinct subagents*, not human-run sessions.
6. The relocated `/forge:new` (opens a project subspace), `/forge:doctor`, `/forge:configure`.

Then, *inside* the package, `/forge:new <codename>` opens a per-project subspace in the org brain using the org's pinned tools and operating model.

## Method

forge is opinionated about **how** agents work together (the method) and unopinionated about **which tools** they use (the adapters) and **how each org works** (the operating model). The full v2 design is in [`docs/GENERATOR.md`](docs/GENERATOR.md); the universal method below survives from v1, re-expressed for the workflow runtime.

### The method (universal)

- **Karpathy schema** — three layers (raw sources / wiki / schema), now *federated* across an org-wide layer and per-project subspaces; code-as-truth holds at both.
- **Six role archetypes** — orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst. The boundaries survive; the delivery vehicle changes from separate *sessions* to distinct *subagents inside workflows*.
- **Three skill verbs** — `prime` (calibrate), `dispatch` (now: invoke a workflow), `wiki` (`propose` / `ingest` / `lint` / `query`, gaining `capture` / `promote` for tribal knowledge).
- **No-self-review** — preserved by *context isolation* between distinct subagents (the reviewer sees the diff, never the implementer's reasoning), not by separate terminals.
- **One orchestrator + dynamic workflows** — a single long-lived orchestrator spawns workflows; the durable substrate (org brain + tracker + SCM) survives crashes.

### The adapters (per-org)

| Layer | Shipped | Planned |
|---|---|---|
| Tracker | gitlab · github · jira-single · jira-multi · jira-mcp · linear | asana |
| SCM | github · gitlab | bitbucket |
| Chat | slack | teams · discord |
| CI | github-actions · gitlab-ci | circleci · jenkins |
| Cloud | — (informational only; forge doesn't provision) | azure · aws · gcp notes |

Each adapter declares: required CLIs, optional MCP servers, and skill snippets that get substituted into the stamped `prime` / `dispatch` skills.

## Lifecycle: generate, distribute, re-generate

forge is not a base you fork. It's a **generator** you run; the *output* is the thing your org owns and distributes. Three stages:

1. **Generate** — install the (shared) generator, run `/forge:emit`. It interviews your org — tools, methodology, and your **operating model** (how agents communicate, under what identity, what gates/autonomy apply) — and writes a standalone org plugin repo (`acme-forge`), validated and ready to install.
2. **Distribute** — publish `acme-forge` (private plugin registry, internal Git host, or vendored) as the org-wide standard. Every team stamps projects *from it* via its internal `/new`, so agent-driven development across the org converges on one operating model, one set of role boundaries, one wiki schema.
3. **Re-generate to upgrade** — when the generator improves upstream, **re-run it** over your existing `.forge.org.yaml`. It re-emits the package, rebasing your org's choices onto the newer generator. No fork to maintain, no drift.

The payoff: an org doesn't get N teams each inventing their own agent-orchestration conventions, *and* it doesn't get a forked copy of forge rotting away from upstream. It gets **one operating model, mechanically generated**, that still adapts per-project via `.forge.config.yaml`. The two-tier config (org vs project) and the full model are in [`docs/GENERATOR.md`](docs/GENERATOR.md).

## Install

```bash
/plugin marketplace add ktoulgaridis/forge
/plugin install forge@forge
```

## Use

```bash
# 1. In the GENERATOR (this repo): emit your org's package
claude
> /forge:emit
# → interviews your org: tools, methodology, operating model, identity, gates
# → writes a standalone org-owned plugin repo (acme-forge), validated

# 2. Distribute acme-forge internally, then inside it:
> /forge:new acme-platform-rebuild
# → opens a project subspace in the org brain using the org's pinned tools

> /forge:doctor
# → verifies CLIs + MCPs + the operating-model invariants for the active project
```

> **Note:** `/forge:emit` is the v2 entry point and is still being built (see Roadmap). v0.1.x ships the v1 `/forge:new` wiki-stamping flow; v2 relocates it inside the emitted package.

## Contributing to forge itself

```bash
cd ~/Work/forge
claude
> /forge:prime
# → reads docs + git state + roadmap + scope; emits calibration summary; asks for today's goal
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for conventions (commits, versioning, releases).

## Status

v0.3.0 — early, opinionated, working but incomplete. **v2 reframe designed** ([`docs/GENERATOR.md`](docs/GENERATOR.md)), build in progress.

v1 (shipped):
- ✅ Method documented (`docs/METHOD.md`, `docs/ROLES.md`, `docs/SESSIONS.md`, `docs/USAGE.md`, `docs/ADAPTERS.md`, `docs/BOOTSTRAP.md`)
- ✅ Wiki templates (from the SocWave reference engagement)
- ✅ Role files (6 default roles + custom-role template)
- ✅ Skill templates (prime, dispatch, wiki — including `lint --consolidate` proactive cleanup)
- ✅ Tracker adapters: gitlab, github, jira-single, jira-multi, linear; SCM: github, gitlab; Chat: slack

v2 (designed, in `docs/GENERATOR.md`):
- ✅ North star: forge = generator → emits org-owned plugin
- ✅ Operating model (the 4th differentiation axis); the org brain (one wiki, project layer, durable tribal knowledge)
- ✅ Single-orchestrator + dynamic-workflow runtime; identity dynamic + wiki-driven
- 🔜 `/forge:emit` + templates + reference workflow (the build)

## Roadmap

Concrete next work, in order:

1. **`/forge:emit` (the generator entry point)** — interview → emit a standalone org-owned plugin → `claude plugin validate --strict`. Start with a thin vertical slice (minimal valid installable plugin), then the full operating-model interview. The single most load-bearing v2 piece — see the foundation build order in [`docs/GENERATOR.md`](docs/GENERATOR.md).
2. **Org-brain templates** — org-wiki schema + operating-model chapter + the `learnings` capture contract + reference `ship-ticket.js` workflow with a context-isolated harvest phase.
3. **Methodology bundles.** Four variants — see [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md): Scrum, Kanban (default), RFC-first, and **Formal-methods / V-model** (must-have for regulated shops; USER-NEED → REQUIREMENT → SPEC → VERIFICATION → VALIDATION with traceability + audit gates; sub-variants for IEC 62304, DO-178C, ISO 26262). Composable *with* the operating model.
4. **CI adapters: github-actions, gitlab-ci.** Skill snippets + sample pipeline templates.

## Out of scope

Deliberately not building these — narrowing focus to what gets used:

- ❌ Tracker: asana
- ❌ SCM: bitbucket
- ❌ Chat: teams
- ❌ CI: circleci, jenkins
- 🤔 Chat: discord — possible later if a project needs it; not on the roadmap

Stay-in-scope adapters get full skill snippets + doctor checks + working examples. Out-of-scope adapters won't be added speculatively.

## Reference engagements

- [examples/socwave.md](examples/socwave.md) — SocWave platform rebuild (gitlab.example.com + Azure)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Private repo today. If/when public:
- File issues for adapter requests
- PRs welcome for new adapters and role bundles
- Method changes go through ADR-style proposals (in `docs/decisions/`)
