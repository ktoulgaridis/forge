# Audit: what the emitted opencode artifact duplicates that opencode 2.x ships natively

Audit of `templates/opencode/` + the opencode path in `lib/emit.py` against opencode 2.x's
native surface, with the back/forward-compat constraint applied: the artifact is ONE
package for opencode **1.18.29+ and 2.x** (forge#20, wiki learning
[ktoulgaridis/kt-wiki#1](https://github.com/ktoulgaridis/kt-wiki/issues/1)). "2.x has it
natively" is not sufficient to drop anything the 1.18.29 floor still needs.

**Method — probed, not doc-read.** Verified against the LIVE installed build
(opencode **v2.0.8** on this machine) via the scratch-plugin probe pattern from the wiki
learning, plus a real **v1.18.29** binary installed from npm (`opencode-ai@1.18.29`) to
test the floor empirically, plus the extracted v2.0.8 source and the `v1.18.29` tag
source (`sst/opencode`) for the seams a probe cannot see. Every load-bearing claim below
cites which of the four it comes from.

Key source locations (v2.0.8 tree): `packages/core/src/worktree.ts` +
`worktree/{strategies,git}.ts`, `packages/core/src/tool/plugin/subagent.ts`,
`packages/core/src/v1/config/{permission,migrate}.ts`,
`packages/core/src/config/plugin/{instruction,reference}.ts`,
`packages/core/src/session/compaction.ts`, `packages/schema/src/config.ts`.

---

## Summary table

| Candidate | Verdict | 1.18.29 impact if dropped |
|---|---|---|
| Worktree mgmt (`worktreeFor`/`removeWorktree`/`claimed`) | **KEEP** (core), lean native later | 1.x has no usable native worktree surface |
| `dispatch` tool itself | **KEEP** (core), shed nothing yet | 1.x `task` tool ≠ dispatch's contract |
| Permission model (1.x map + 2.x auto-translation) | **KEEP the 1.x map; do NOT emit the 2.x array** | array-only perms = fail-open read-only boundary on 1.x |
| `reminders.js` compaction hook | **KEEP** (the hook seam is the only content path on both hosts) | native config tunes thresholds only; the handoff line has no native equivalent |
| `instructions` in opencode.json | **KEEP** (needed by 1.x); it is inert on 2.x by design | 1.x loads it; dropping it silences the wiki pointers on 1.x |
| 2.x `references` | **NOT NOW** — noted as the future direction | tolerated by 1.x, but it is a pointer list, not a loader |

**Headline:** nothing the artifact ships is redundant *today*. The 2.x natives cover
different problems (generic delegation, generic worktrees, threshold tuning, pointer
lists) than the harness's specific contracts (role-allowlisted dispatch with ticket
envelopes, per-(repo,ticket) writer isolation with in-flight reservation, an injected
handoff line, wiki pointers that survive restart). Two forward-looking notes: the 2.x
`references` key is the eventual replacement for the `instructions` wiki pointers once
the 1.x floor can be raised, and 2.x native worktrees could replace the plumbing (not
the policy) of `worktreeFor` in the same future.

---

## 1. Worktree management — `worktreeFor` / `removeWorktree` / the `claimed` reservation

### What we ship

`plugin/dispatch.js` (emitted from `templates/opencode/plugin/dispatch.js.template`):

- `worktreeFor(workspace, repoDir, ticket, runs)` — one git worktree per `(repo, ticket)`,
  branch named `safe(ticket)`, path `<workspace>/.worktrees/<repo>--<branch>`. Reuses an
  existing tree whose run finished; refuses if a live run holds it (names the `task_id` to
  continue instead).
- `claimed` — an in-process `Set` reservation taken **synchronously** (no `await` between
  `has()` and `add()`) and held across the whole `session.create` + `recordRun` window, so
  two same-turn dispatches for one `(repo, ticket)` cannot both pass the empty-registry
  check. Released once the persisted registry (`.worktrees/.dispatch.json`) guards the path.
- `removeWorktree` — best-effort teardown when a fresh create fails before persisting.
- The registry itself: persisted task_id → {role, ticket, directory}, so continuation
  survives an opencode restart.

### What 2.x ships natively (verified live + source)

2.x has a full worktree subsystem: `ctx.worktree.{list,create,remove,refresh}` in the
plugin ctx (probe A), HTTP routes `GET/POST/DELETE /api/worktree` (live OpenAPI), and a
pluggable strategy model (`worktree/strategies.ts`) with a bundled `git` strategy
(`worktree/git.ts`).

Live behavior on v2.0.8 (probed against a scratch git repo):

- `POST /api/worktree {projectID, name}` creates a worktree; with no config it lands in
  **opencode-managed space** (`~/.local/share/opencode/worktree/<projectPrefix>/<name>`)
  as a **detached HEAD** checkout.
- `worktree: { directory: <base> }` in config re-bases creations (verified: trees appeared
  under the configured base).
- Collision handling appends `-2`, `-3`… suffixes rather than reusing (source:
  `worktree.ts` `create` loop, `suffix > 10 → DestinationExistsError`).
- `branch:` is only a **ref to check out** — passing a non-existent branch fails
  (`invalid reference: feature/probe2`); 2.x never *creates* a branch (source: `git.ts`
  passes `ref: input.branch` straight to `git worktree create`; detached HEAD when absent).
- There is **no per-ticket identity, no holder/reservation concept, and no task_id
  linkage** — 2.x tracks an inventory (DB rows of directories+strategy), not runs.
- The `subagent` tool does **not** create worktrees (source: `subagent.ts` creates only a
  child session in the same location).

Also relevant to the constraint: **v1.18.29 has none of this surface.** Its `worktree/`
module exists but is TUI/workspace-internal: the HTTP routes live under
`/experimental/workspace` behind the `OPENCODE_EXPERIMENTAL_WORKSPACES` flag (source:
`server/routes/instance/httpapi/groups/workspace.ts` root constant + the
`worktree-endpoint-repro.test.ts` flag setup), there is no `worktree` group in the server
handlers (source: handlers listing), and a live `GET /api/worktree` on the 1.18.29 binary
returns the web-app fallback, not an API.

### Recommendation: **KEEP**

What `worktreeFor` provides that 2.x native does not:

1. **The policy**: one tree per (repo, ticket) keyed by a tracker key, with a stable,
   guessable path (`<repo>--<ticket>`) that the org's docs and skills reference.
2. **The branch creation**: dispatch creates the branch when missing; 2.x refuses.
3. **The concurrency contract**: the `claimed` in-flight reservation + registry-holder
   check is what makes two same-turn dispatches for one ticket safe. 2.x's collision
   suffixing (`probe-wt3-2`) would silently put two writers in two trees for the same
   ticket — the opposite of the guarantee.
4. **The run linkage**: `task_id → directory` is what lets "continue this run" re-enter
   the right tree after a restart.

What is genuinely duplicated is only the raw `git worktree add/remove` mechanics — and
even that cannot lean on the native API without giving up items 1–4, and would break 1.x
outright (no usable native surface at the floor; probed live).

**What breaks on 1.18.29 if dropped:** everything — 1.x has no model-reachable worktree
surface at all. Writers would run in the orchestrator's tree, collapsing the isolation
that `README.md` promises ("Writers get a worktree… so runs work across many repos").

**Forward note:** if the floor ever rises to 2.x-only, the *plumbing* (git invocation,
path allocation) could move to `ctx.worktree` with a plugin-added strategy, keeping
`decide()`, the registry, and `claimed` as the policy layer. That is a rewrite of the
mechanism, not a deletion of the feature.

---

## 2. The `dispatch` tool vs 2.x's built-in `subagent` tool

### What we ship

`dispatch` (+ `dispatch_read` / `dispatch_list`) with: a **role allowlist** rendered from
the org config (`ROLES` table), **model policy** enforcement (one provider + banned list,
fail-closed), **ticket-as-envelope** (the child reads its own ticket from the tracker;
the orchestrator never re-authors a prompt), **worktree grant for writers**, the
**ad-hoc read-only ticketless mode** persisted to `.delegations/` with a lifecycle that
survives compaction/restart/crash, and **task_id continuation** restricted to runs this
workspace issued, under the same role.

### What 2.x ships natively (verified live + source)

The built-in `subagent` tool (present in the live registry on 2.0.8 — probe C enumerated
59 tools including `subagent`; source `tool/plugin/subagent.ts`):

- Input: `agent`, `description`, `prompt`, optional `model`, `sessionID` (continue),
  `background`.
- Spawns a child session with a chosen agent, blocks to completion (foreground) or
  returns immediately with a notification (background), and returns the sessionID for
  continuation.
- Depth-limited nesting (`experimental.subagent_depth`, default 1) and a permission
  assertion on `subagent` per agent id.
- It even augments its own description with the available subagents list
  (`ctx.session.hook("context", …)` in the source) — a nice touch we do not have.

v1.18.29's equivalent is the `task` tool (source: `packages/opencode/src/tool/task.ts` on
the v1.18.29 tag: `subagent_type`, `prompt`, `task_id` for resume, `background`) — the
same generic shape, which is exactly why the emitted agents deny it and route through
`dispatch`.

### What dispatch still adds (none of it redundant)

1. **The role allowlist as policy.** `decide()` refuses unknown roles before anything is
   created. `subagent`/`task` accept any subagent-mode agent — including, on 1.x, one the
   org never sanctioned.
2. **Model policy enforcement.** `resolveModel()` enforces the single provider and the
   org's banned list per call; `subagent`'s `model` param is a free string (its
   description even encourages looking models up globally).
3. **Ticket-as-envelope.** `dispatch({role, ticket})` sends only "act on <ticket>" — the
   child pulls the envelope from the tracker. `subagent` requires the parent to inline
   the full prompt, which is precisely the orchestrator-context bloat the harness exists
   to avoid.
4. **The writer/reader fork with worktree grant** (see §1).
5. **The persisted ad-hoc store.** `subagent` background returns a sessionID but there is
   no durable titled/summarized result store; its completion notification is not
   queryable after the fact. `.delegations/` + `dispatch_read`/`dispatch_list` survives
   compaction, restart, and crash — the design the ticket calls out.
6. **Disciplined continuation.** `task_id` only continues runs this workspace issued,
   same role. `subagent`'s `sessionID` will happily continue any child of the session
   and even **switch agents mid-continuation** (source: `switchAgent` when
   `existing.agent !== agent.id`).
7. **Cross-host policy unity.** One `decide()` core drives both entrypoints (2.x `setup`
   and 1.x `server`), so role/model/read-only policy cannot drift between hosts. The
   native tools are host-specific implementations (2.x `subagent`, 1.x `task`) with
   different shapes — using them natively would fork the policy.

What the native tool *does* better, honestly: context-overflow-aware blocking, progress
notification plumbing, and the depth limit. None of those conflict with dispatch; the
first two are 2.x-session-mechanics that dispatch's `setup()` path already rides
(`ctx.session.wait`/`context`).

### Recommendation: **KEEP** — and this is the least redundant piece of the artifact

The redundancy is one-way and shallow: both hosts *have* a generic delegation primitive,
and the emitted agents deliberately deny it (`task: deny` in `opencode.json`; 2.x
translates that to `subagent: deny`; agents also deny `dispatch` themselves so children
cannot re-dispatch) so that **dispatch is the only door**. That denial is the control
that makes the role allowlist, model policy and read-only boundary meaningful. Removing
dispatch in favor of native `subagent` would not simplify the artifact — it would delete
the policy layer and re-expose the fail-open path (any agent, any model, prompt inline).

**What breaks on 1.18.29 if dropped:** the harness has no delegation primitive with
ticket envelopes (v1 `task` has no `location`, no worktree, no model policy, no result
store), so execute/refine lose the orchestrator pattern entirely on the floor host.

---

## 3. The permission model — 1.x map + 2.x auto-translation vs emitting the 2.x array

### What we ship

- Agent frontmatter: the 1.x `permission:` map (derived per-role from the org config's
  `toolFilter.allow`; bash as an ordered allowlist) — `templates/opencode/agent/*.md`.
- Config level: `"permission": { "external_directory": "allow", "task": "deny" }` in
  `opencode.json`.
- Dispatch's ad-hoc mode: 1.x enforces read-only via per-prompt `tools:` gates
  (`READ_ONLY_TOOLS`); 2.x via `permissions: ADHOC_DENY` at `session.create`.

### What 2.x ships natively (verified live + source)

The 2.x-native shape is a `permissions:` **array of rules** (`{action, resource, effect}`,
`Permission.Ruleset` in the live OpenAPI), settable in config, in agent frontmatter, and
per session-create.

Live findings on v2.0.8:

- The 1.x map is **auto-translated everywhere it appears** — config level and agent
  frontmatter (`task → subagent`, `bash → shell`, custom actions pass through, nested
  bash allowlists become ordered shell rules preserving order). Confirmed live: the
  emitted `wrap` artifact's `reviewer`/`gate` resolve with `edit/subagent/dispatch/
  webfetch/websearch: deny` + the exact allowlisted `shell` patterns + the redirect
  guards, and `build` gets `external_directory: allow` + `subagent: deny` from the
  config-level map. Source: `v1/config/migrate.ts` `permissions()` +
  `normalizeAction()`, applied to agents (`migrateAgent`).
- **Frontmatter precedence**: if BOTH shapes are present, the 1.x map wins and the array
  is **ignored** (live probe: an agent carrying both produced only the map-derived
  rules). Array-only works on 2.x (live probe: array-only agent resolved with the
  array's denies).

### The decisive floor probe (live v1.18.29 binary)

- An agent frontmatter carrying BOTH shapes: 1.x resolves fine (map rules present, extra
  `permissions` key silently ignored — verified via `opencode debug agent`).
- An agent carrying ONLY the array: **1.18.29 resolves it with NO denies** — the
  `edit: deny` simply does not exist (`debug agent` shows the default allow + the
  harness's unrelated `task: deny` from config; `edit` allowed). That is the read-only
  boundary **failing open** on the floor host.
- Config-level `"permissions": [...]` array: **hard error** on 1.18.29 —
  `Configuration is invalid … V2 permissions are not supported by OpenCode V1. Use V1
  "permission" rules or run opencode2.` The whole config is rejected, taking the rest of
  the artifact (model allowlist, agents, plugins) down with it.

### Recommendation: **KEEP the 1.x map; do NOT emit the 2.x-native array**

Emitting the 2.x `permissions` array — the "also emit native" idea in the ticket — would
be strictly harmful:

- In agent frontmatter alongside the map: ignored on 2.x (map wins), ignored on 1.x —
  dead weight at best.
- Array-only (replacing the map): **fail-open** on 1.18.29 (no edit deny → a "read-only"
  reviewer can edit). Violates the load-bearing constraint.
- In config: **hard-fails the entire config** on 1.18.29.

The 2.x auto-translation (forge#20, re-verified live here) means the 1.x map IS the
portable form: one shape, correct enforcement on both hosts, and the deny derivation in
`emit.py` (`derived_deny` + the `OC_FORBIDDEN_IN_READONLY_ALLOW` fail-closed checks)
stays the single source of truth. The only place a 2.x-native permission shape is
already used — `ADHOC_DENY` at session-create in the `setup()` path — is correctly
host-gated (1.x uses per-prompt tool gates for the same effect), so it needs no change.

**What breaks on 1.18.29 if dropped (i.e., if we switched to the array):** the read-only
boundary (silent fail-open) and, at config level, the entire artifact (config rejected).

---

## 4. `reminders.js` compaction hook vs 2.x native compaction config

### What we ship

A fail-open plugin: on 1.x, a session-start toast + `experimental.session.compacting`
pushing the handoff line into the continuation context; on 2.x,
`ctx.session.hook("compaction")` pushing an include-verbatim system part so the line
lands in the continuation summary.

### What 2.x ships natively (verified live + source)

- Config: `compaction: { auto, keep: { tokens }, buffer }` (`Config.InfoEncoded` in the
  live OpenAPI; `schema/src/config.ts`).
- Source (`session/compaction.ts`): these tune **when** compaction fires and **how much
  recent history is retained** (`DEFAULT_BUFFER = 20_000`, `DEFAULT_KEEP_TOKENS =
  15_000`), plus a structured summary template (Objective / Requirements / Decisions /
  Work State / Next Move / Relevant Files / Important Context).
- The plugin seam `ctx.session.hook("compaction", cb)` with
  `event.system: Array<SystemPart>` is a first-class, documented-in-type extension point
  (`packages/plugin/src/effect/session.ts`: `SessionCompaction extends SessionContext`).
  Our plugin's `event.system.push({type:"text", …})` is exactly the intended use.
- Manual compaction exists as an API (`POST /api/session/{id}/compact`) but that is a
  trigger, not content control.

### Recommendation: **KEEP** — the hook and the config are complements, not alternatives

The native config answers "when and how much"; it has **no way to inject the org's
handoff line** ("durable state lives in the tracker and the wiki; re-run prime…") into
the continuation. The only content path on either host is the hook seam (1.x:
`compacting.context` push; 2.x: `event.system` push) — both verified in the respective
sources. The 2.x summary template does carry forward workflow state generically, but it
explicitly forbids carrying "instructions and setup" and cannot know about the org wiki.

Tuning `compaction` in the emitted `opencode.json` (e.g. a larger keep budget) could be
a *future* org-config knob, but it is an org policy choice, not a redundancy: nothing
`reminders.js` does is replaced by it.

**What breaks on 1.18.29 if dropped:** the handoff line never reaches the cycled session
on either host (1.x's `experimental.session.compacting` is the only 1.x seam; the 2.x
config keys are not a content channel). The toast half is 1.x-only today regardless.

---

## 5. `instructions` in opencode.json vs 2.x `references`

### What we ship

`opencode.json` `instructions: ["AGENTS.md", "{env:WIKI}/operating-model.md", …]` —
the env-var-only wiki pointer path (forge#19 decision), plus `AGENTS.md` carrying the
same pointers in prose.

### What each host does (verified live + source)

- **1.18.29**: `config.instructions` is a first-class loader (source:
  `session/instruction.ts` — glob/absolute resolution of every entry into system
  context; `{env:VAR}` substitution in config files exists at the same version, source:
  `config/variable.ts`). The emitted entries genuinely load on the floor.
- **2.0.8**: the `instructions` config key still **parses** (live OpenAPI
  `Config.InfoEncoded.instructions`; `schema/src/config.ts` keeps the field) but has
  **no consumer** in the 2.x core outside v1-compat migration — the instruction pipeline
  is now discovery-driven: an internal plugin walks global + ancestor `AGENTS.md` files
  only (`config/plugin/instruction.ts`: candidates are the global config `AGENTS.md` and
  ancestor `AGENTS.md`s; nothing reads `config.instructions`). Live behavioral probe
  agreed: a location with an `instructions` entry pointing at a marker file, plus a
  `references` entry with a description, produced neither marker in the model's context
  (`INSTR=no REF=no AGENTS=no` — the refdir session reported no AGENTS.md content either,
  consistent with the probe dir not containing one).
- **2.x `references`**: parsed from config into the Reference service
  (`config/plugin/reference.ts`) and surfaced to the model as a **pointer list** —
  `<available_references>` name/path/description guidance in system context
  (`reference/instructions.ts`), only for entries that carry a `description`. It is a
  "these directories exist, use them when relevant" list, **not** a content loader, and
  it grants no access by itself (read access is still governed by
  `external_directory`/file-access rules).

### Recommendation: **KEEP `instructions` (1.x needs it); do NOT switch to `references` now**

- Dropping `instructions` breaks the wiki-pointer loading on 1.18.29 (the env-var path
  would go silent), violating the constraint. Keeping it costs nothing on 2.x (inert by
  design) — and `AGENTS.md` already carries the pointers for the 2.x host, so the
  current dual-carriage is the correct compat form, exactly as forge#20 left it.
- `references` is **tolerated** by 1.18.29 (live probe: config with `references` loads
  fine on the 1.x binary; `references:` is even a documented v1 config field), so it
  could be *added* today without breaking the floor. But it changes behavior on neither
  host in the way the artifact needs: on 2.x it injects a pointer list, not the wiki
  content; on 1.x it is a directory-reference config, not an instruction loader. It is
  the right **future** shape (env-var wiki reference + description) once the org decides
  the 1.x floor can move — worth a line in the org config docs, not a template change
  now (this audit makes no template changes).

**What breaks on 1.18.29 if dropped:** the structural wiki load (prime's precondition)
loses its config-level pointer on the floor host; prime's env-var prose in AGENTS.md
would be the only remaining path.

---

## 6. Candidates examined and found already-native-aligned (no action)

- **`enabled_providers` / `disabled_providers`**: still the live allowlist mechanism on
  2.x (config schema + `/api/provider`); the emit-time assertion in `emit.py` matches
  the live behavior. Nothing native replaces it.
- **`small_model`**: accepted on both hosts (2.x maps it to the title/summary auxiliaries
  via migration; live config schema still has it).
- **`default_agent`**: live 2.x config key (`Config.InfoEncoded.default_agent`), used as
  emitted.
- **`steps:` in agent frontmatter**: 2.x accepts it (live agent registry shows `steps`
  carried on the resolved agents; wiki learning already noted this) and 1.x is its home.
- **Per-prompt tool gates (`tools:` on 1.x prompt) vs 2.x create-time `permissions`:**
  already correctly host-split in `dispatch.js`; 2.x removed per-prompt gates, and the
  plugin uses the native replacement (`permissions: ADHOC_DENY` at session.create —
  the `SessionEvent.Permissions` merge path in `session/session.ts` confirms
  create-time rules are merged over agent rules).

---

## Bottom line

Every candidate resolves to **keep**. The artifact's opencode pieces are not re
-implementations of 2.x features; they are the org's policy layer (role allowlist,
ticket envelopes, per-ticket writer isolation, org handoff line, wiki pointers) that
2.x's natives deliberately do not provide. The two genuine "lean on native when
available" moves are both floor-gated future work, not now-work:

1. **`references`** as the eventual wiki-pointer shape (tolerated by 1.18.29, inert for
   our purpose today, the native idiom on 2.x).
2. **`ctx.worktree`** as the eventual worktree mechanism if/when the floor moves to
   2.x-only (1.18.29 has no usable native surface; probed live).

And one hard "do not": **never emit the 2.x `permissions` array** — it is ignored
(frontmatter) or fatal (config) on 1.18.29, and silently fails the read-only boundary
open there. The 1.x `permission` map + 2.x auto-translation is the compat mechanism
working as designed.
