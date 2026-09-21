# Anthropic-style auto mode for opencode — gap analysis + plugin design

Status: **research note, decision pending** ([forge#22](https://github.com/ktoulgaridis/forge/issues/22)).
Method: Anthropic semantics pinned from their docs + engineering post (2026-03); opencode
semantics verified against the **pinned v2.0.8 source tag** (`anomalyco/opencode`), then
**probed live** on the installed v2.0.8 build — every claim below is either source-cited,
probe-cited (`S1`–`S7`, below), or both. Docs were not trusted: the 2.x plugin README does
not mention `ctx.permission` at all, and two of its most important facts (the evaluate hook
and the `.opencode/plugin/` install path) exist only in source and probes.

**Verdict up front:** opencode 2.x does **not** already satisfy Anthropic's auto-mode
semantics. Its closest built-in, the `--auto` flag, is a blanket client-side approver —
no risk classification, no block categories, and `ask` rules do not hold under it. But the
2.x permission pipeline has exactly one well-shaped extension point — the
`permission.evaluate` plugin hook — through which the missing semantics can be added
without touching the host. The design (section 4) is a standalone, publishable plugin.
The wiki capture of the decision is a **follow-up after maintainer review**, per the
ticket.

---

## 1. What Anthropic's auto mode actually is

Auto mode is a Claude Code permission mode (research preview, v2.1.83+, Team plan at
announcement) in which a **classifier model substitutes for the human approver**. Sources:
[permission modes](https://code.claude.com/docs/en/permission-modes),
[auto mode config](https://code.claude.com/docs/en/auto-mode-config),
[permissions](https://code.claude.com/docs/en/permissions),
[engineering deep dive](https://www.anthropic.com/engineering/claude-code-auto-mode)
(2026-03-25), [announcement](https://claude.com/blog/auto-mode) (2026-03-24).

**The classifier.** A transcript classifier (Sonnet 4.6) reviews each action before it
runs, in two stages: a fast single-token filter that errs toward blocking, then
chain-of-thought re-evaluation only when flagged. It sees user messages, tool calls, and
`CLAUDE.md` — Claude's own messages and tool results are stripped ("reasoning-blind by
design"), and a separate server-side probe scans incoming tool results for hostile
content before Claude reads them.

**Fixed decision order — first match wins:**

1. Actions matching allow/ask/deny rules resolve immediately — **except** writes to
   protected paths (`.git`, `.claude`, `.vscode`, …) and critical-path `rm`/`rmdir`, which
   route to the classifier even when an allow rule matches, and content-scoped ask rules
   (`Bash(git push *)`) which fall back to a prompt.
2. Read-only actions and file edits inside the working directory are auto-approved
   (protected paths excepted).
3. Everything else goes to the classifier.
4. If the classifier blocks, the model receives the reason and tries an alternative —
   it is not supposed to route around the block.

**Denied by default:** `curl | bash`-style download-and-execute; sending sensitive data to
external endpoints; production deploys and migrations; mass deletion on cloud storage;
granting IAM or repo permissions; modifying shared infrastructure; irreversibly
destroying files that predate the session; force push or pushing directly to `main`.
**Allowed by default:** local file operations in the working directory; installing
dependencies declared in lock files or manifests; reading `.env` and sending its
credentials to their matching API; read-only HTTP requests; pushing the session's working
branch. The engineering post groups the deny logic into four categories: *destroy or
exfiltrate; degrade security posture; cross trust boundaries; bypass review or affect
others.*

**Rules still rule.** Deny rules block **before** the classifier and nothing overrides
them (managed settings highest). Explicit ask rules **always prompt** — the classifier
cannot auto-approve a matching action. On *entering* auto mode, broad allow rules that
grant arbitrary code execution are **dropped** (blanket `Bash(*)`, wildcarded interpreters
like `Bash(python*)`, package-manager run commands, `Agent` rules); narrow rules carry
over, and dropped rules are restored on exit. `autoMode.classifyAllShell` suspends every
shell allow rule instead.

**Circuit breaker.** 3 consecutive blocks or 20 total blocks pause auto mode and resume
manual prompting (thresholds not configurable; any allowed action resets the consecutive
counter). In headless mode there is no UI, so the process terminates instead.

**Subagents** are checked at three points: the delegated task description at spawn time,
each action under the same rules as the parent (frontmatter `permissionMode` ignored),
and the full action history after the run, with a security warning prepended to results
if flagged.

**Configuration.** `autoMode.environment` (trusted repos/buckets/domains), `allow`,
`soft_deny`, `hard_deny` — each an array of **prose rules read as natural language**,
inserted into a fixed classifier prompt. Precedence inside the classifier:
`hard_deny` > `soft_deny` > `allow` > explicit user intent. `"$defaults"` preserves the
built-in lists. Organizations can kill the mode entirely with
`permissions.disableAutoMode: "disable"`.

**Positioning.** Users approve 93% of prompts; auto mode trades prompt fatigue for
classifier judgment. Anthropic is explicit that it "reduces prompts but does not
guarantee safety" and is "not a drop-in replacement for careful human review on
high-stakes infrastructure."

## 2. What opencode 2.0.8 offers today — probed, not trusted

### 2.1 The evaluation pipeline (source: `packages/core/src/permission.ts`, all confirmed live)

Rules are `{action, resource, effect: "allow"|"ask"|"deny"}`. Wildcards: `*` → `.*`,
`?` → `.`, and a trailing `" *"` matches with or without the space (`packages/core/src/util/wildcard.ts`).
Evaluation is **last-match-wins** (`evaluate()` = `findLast` over the merged rulesets) —
unlike Claude Code's deny→ask→allow first-match order. When no rule matches at all, the
fallback effect is `ask`.

Ordered:

1. **Configured deny** — rules from the agent (config top-level `permissions` apply to
   *all* agents, then `agents.<id>.permissions`, then agent frontmatter) merged with the
   **session-scoped ruleset** (`session.create/update({permissions})` — "evaluated after
   the agent's rules; the last matching rule wins", `packages/schema/src/session.ts`).
   If any resource evaluates `deny`: **deny immediately — the plugin hook is never
   called and saved rules are not even merged** (probe S3: zero hook log lines for the
   denied marker).
2. **Saved approvals** — "always allow" replies persist `{projectID, action, resource}`
   rows in the global SQLite db (`packages/core/src/permission/saved.ts`,
   `permission.saved` API: list/remove), and are read back as **allow-only rules appended
   *after* the configured ruleset** — so a saved allow beats a configured `ask` (probe
   S6→S7) but can never beat a configured `deny` (step 1 runs first). Shell commands save
   as the command prefix + `" *"` (`packages/core/src/shell/parse.ts`; probes show
   `save: ["echo *"]`, `save: ["touch *"]`). After an "always", the server re-evaluates
   other pending requests and auto-resolves any that now evaluate allow.
3. **Per-resource effect** — any resource resolving `ask` makes the request `ask`.
4. **The `permission.evaluate` plugin hook** — fires with `{sessionID, agent, action,
   resources, metadata, source, effect, message}`, both `effect` and `message` **mutable**
   (`packages/plugin/src/promise/permission.ts`). A deny message becomes the
   model-facing block reason; an ask message rides on the request.
5. **Ask** — a pending request is created and `permission.asked` published (fields incl.
   `save` patterns); clients reply `once` | `always` | `reject` (with optional feedback
   that reaches the model); reject also rejects the session's other pending requests.

### 2.2 The built-in "auto": `--auto` is a client-side blanket approver

`--auto` exists on both `opencode` and `opencode run`: *"Auto-approve permissions that
are not explicitly denied."* Implementation is **client-side**:

- `opencode run`: on any `permission.asked`, reply `"once"` — or, without `--auto`,
  reply `"reject"` and interrupt the session (`packages/cli/src/run/noninteractive.ts`;
  probe S1 vs S2: same config ask rule, reject vs auto-once).
- The TUI: `--auto` selects the `autoaccept` mode (also a config
  `session.permissions: "prompt"|"autoaccept"`), which auto-replies `"once"` to **every**
  pending request (`packages/tui/src/routes/session/index.tsx`).

So: denies hold under `--auto` (they never become requests), but **`ask` rules do not** —
an explicit ask is auto-approved exactly like everything else. There is no classifier, no
risk tiers, no block categories, no circuit breaker, no ledger.

### 2.3 The default agent is allow-all

`Agent.Info.default` starts from
`{action: "*", resource: "*", effect: "allow"}` with asks carved out for
`external_directory` and `.env` reads (`packages/schema/src/agent.ts`). Probe: in a bare
project with no rules, a shell command ran with no prompt (and S7's log shows `glob`
evaluating `allow` with no matching rule). Consequence: out of the box, opencode asks for
almost **nothing** — `--auto` only changes behavior in projects that configure rules.
The permission system's structural strength (deny enforcement, saved approvals, ordered
rules) is real but **opt-in**.

### 2.4 The plugin surface (live-probed)

A zero-dependency local plugin at `<ancestor>/.opencode/plugin/` (discovery:
`packages/core/src/config/discovery.ts` + `config/plugin/source.ts` — the `.opencode`
directory found in the upward config walk, plus the global config dir; **not**
`<project-root>/plugin/`, which cost this probe a re-run and is documented nowhere in
the shipped README). Live probe (S0) of `ctx`:

- `ctx.permission` = `{list, get, reply, hook}` — reply is
  `{sessionID, requestID, decision: once|always|reject, message?}`; `hook("evaluate", fn)`
  registers the classifier choke point. **Neither the domain nor the hook appears in the
  plugin README** (`packages/plugin/src/README.md`).
- `ctx.event.subscribe()` streams `permission.asked` / `permission.replied` (probe-verified).
- `ctx.session.create({permissions})` — session-scoped rule replacement; already the
  enforcement mechanism for forge's read-only ad-hoc dispatches (`ADHOC_DENY`), verified
  live in forge#20.
- `ctx.generate.text({prompt, model?})` — one-shot text generation
  (`POST /api/experimental/generate`, experimental) — a possible in-process classifier.

### 2.5 Probe evidence (v2.0.8, live; JSONL at the probe workspace)

| Run | Setup | Observed |
|---|---|---|
| S1 | config ask rule `echo PROBE_CONFIG_ASK*`, `opencode run` (no `--auto`) | hook saw `effect=ask`; `asked` with `save=["echo *"]`; CLI auto-**rejected** + interrupted; model told "user declined" |
| S2 | same, `--auto` | same ask; CLI auto-replied `"once"`; command executed |
| S3 | config deny rule, `--auto` | **no hook call at all** (deny short-circuits), no `asked`; blocked with "Permission denied: shell" reaching the model |
| S4 | config ask rule `PROBE_HOOK_ALLOW*`; hook upgrades to allow; no `--auto` | hook fired with incoming `ask`, set `allow`; no `asked`; command ran unprompted |
| S5 | config allow rule `PROBE_HOOK_DENY*`; hook downgrades to deny; `--auto` | hook fired with incoming `allow`, set `deny` + message; **the model reported the plugin's own message verbatim**; plugin denies hold under `--auto` |
| S6 | config ask rule `touch PROBE_SAVE_ALWAYS*`; plugin replies `"always"` on `asked` | `asked` → replied `"always"` → saved approval persisted |
| S7 | same command, fresh process, no `--auto`, no plugin reply logic hit | hook saw incoming `effect=allow` — the **saved rule beat the configured ask** pre-hook; no `asked`; command ran |

Also verified live: 1.x `permission` blocks auto-translate on 2.x (`write|patch→edit`,
`task→subagent`, `bash→shell`; `packages/core/src/v1/config/migrate.ts`), matching the
forge#20 learning; the emitted kt-harness package's `plugin/` loads because its package
root **is** `~/Work/.opencode/` — consistent with 2.4 above, not a contradiction.

## 3. The gap

| # | Semantic | Claude Code auto mode | opencode 2.0.8 | Gap? |
|---|---|---|---|---|
| 1 | Approval logic | per-action classifier, two-stage, risk-categorized | client auto-replies `once` to every ask (`--auto`/autoaccept) | **yes** |
| 2 | Risk model | 4 block categories + default deny/allow lists + allow exceptions | none | **yes** |
| 3 | Explicit `ask` rules under auto | always prompt; classifier cannot approve them | auto-approved like everything else | **yes** |
| 4 | `deny` rules under auto | block before classifier, unoverridable | block before the hook; plugin can't even see them (S3) | no — parity, host-enforced |
| 5 | Broad allow-rule suspension on auto entry | dropped (blanket bash, wildcard interpreters, package runs, agent rules) | nothing equivalent | **yes** |
| 6 | Circuit breaker | 3 consecutive / 20 total → pause auto, resume prompting | none | **yes** |
| 7 | Denial ledger + human retry | Recently-denied tab, `r` to retry, `PermissionDenied` hook | none — a deny is a tool error; the human sees nothing unless watching | **yes** |
| 8 | Protected paths (`.git`, `.claude`, …) | writes route to the classifier in every mode | rules decide — and the **default agent allows them** | **yes** |
| 9 | Subagent gating | spawn-time + per-action + post-run review | per-action rules only (agent's ruleset applies); no spawn/post review | **yes** (partial) |
| 10 | Environment trust + prose policy config | `autoMode.environment/allow/soft_deny/hard_deny`, `hard > soft > allow > intent` | structural rules only; no semantic policy surface | **yes** |
| 11 | Org kill-switch | `permissions.disableAutoMode: "disable"` | `--auto` always available | **yes** |
| 12 | Prompt-injection hardening | classifier reasoning-blind; separate tool-result scanner | none | **yes** (host-level) |
| 13 | Saved "always allow" | exists; grants persist per project | exists; project-scoped SQLite, allow-only, never beats a deny (S6/S7) | no — parity |
| 14 | Session-scoped rules | — | `session.create({permissions})`, merged before the hook | no — opencode ahead |

Verdict: the **enforcement substrate** in opencode 2.x is sound and in one place
(ordered rules, host-enforced denies, saved approvals, one hook) — but the
**decision layer** Anthropic ships on top does not exist. `--auto` is not a partial
implementation of it; it is a different (weaker) semantic.

## 4. The design: `auto-mode`, a standalone plugin

Standalone and publishable (own repo, e.g. `ktoulgaridis/opencode-auto-mode`, MIT) —
separate from forge, per the ticket. Zero-dependency: node builtins only; everything real
arrives on `ctx` (the v2.0.8 loader resolves nothing else for local plugins — forge#20
learning).

### 4.1 The one extension point

`setup(ctx)` registers exactly one hook:

```js
await ctx.permission.hook("evaluate", classify)
```

Every permission evaluation that is not already denied passes through `classify`
(probes S4/S5: the hook can raise `ask→allow` and lower `allow→deny`, and its `message`
reaches the model verbatim). Configured denies **structurally never reach the plugin**
(S3) — "denies always enforced" is a host guarantee, not a plugin promise, which is
exactly the composition contract the saved-approvals system already promises.

### 4.2 Classification tiers (per evaluation)

1. **hard deny** — match against the plugin's `hard_deny` list (prose-pattern rules):
   `effect = "deny"` + reason. Non-negotiable; user intent and `allow` exceptions do not
   clear it (Anthropic's tier 1).
2. **known-safe** — read/glob/grep/list; edits inside the session directory;
   manifest-declared installs; push to the session's branch (mirrors Anthropic's
   default-allow list): allow.
3. **soft deny** — destructive patterns (force push, `rm -rf` on critical paths,
   `curl | bash`, credential-shaped egress, writes to `.opencode/`/`.git/`/`.claude/`
   — the protected-path gap, row 8): deny unless an `allow` exception matches
   (tier precedence `hard_deny > soft_deny > allow`, as in Anthropic's classifier).
4. **uncertain** — leave the incoming `effect` as `ask`: the human answers through the
   host's normal prompt. The plugin never silently upgrades what it cannot classify.

Two operating modes, set via plugin options (`ctx.options`, declared under `plugins` in
`opencode.json`):

- **`gate` (default)** — only intervenes downward (deny/ask). Rule-allowed and saved
  requests pass untouched. Turns the allow-all default agent into a risk-classified one
  **without changing what the org already allowed**.
- **`auto`** — additionally upgrades asks that arise from the no-match default (no
  explicit ask rule) to `allow` when classified known-safe: the Anthropic auto-mode
  experience — but unlike `--auto`, risky stays denied and uncertain still asks. Each
  upgrade is per-request: the plugin **never writes saved approvals**, so "safe →
  auto-allow once" is exactly that.

`ask`-floor: an explicit ask rule should always prompt (gap row 3). Limitation found
while probing: the evaluate event does **not** carry the matched rule, so the plugin
cannot distinguish an explicit `ask` rule from the no-match default. Mitigation: the
plugin re-reads the project's configured rules (from `ctx.location.directory`) and
treats an explicit ask as a floor; documented as a heuristic pending an upstream field.

### 4.3 The classifier is pluggable

- **`rules` (default, zero-dep)** — deterministic pattern engine over
  `(action, resources, metadata)`: prefixes, pipes/substitution, critical-path deletions,
  egress domains. Policy surfaces mirror Anthropic's: `environment`, `allow`,
  `soft_deny`, `hard_deny` in plugin options; `$defaults` semantics.
- **`model` (opt-in)** — evaluations that survive `rules` classify via
  `ctx.generate.text` (experimental) with a fixed prompt carrying the configured policy
  slots; single-token verdict, err toward deny on parse failure. Two-stage in spirit:
  the deterministic tier runs first, so model calls are spent only on the residue.
  Deliberate divergence from Anthropic: the plugin classifies **actions, not
  transcripts** — it is reasoning-blind *by omission*, which also means no
  tool-result-scanning tier (gap row 12 stays a host-level concern; do not fake it).

### 4.4 Circuit breaker + denial ledger (gap rows 6–7)

Configurable where Anthropic's thresholds are not: after N consecutive plugin-denials
(default 3) or M total (default 20), `auto` mode degrades to `gate` for the rest of the
session and a synthetic session message says so (`ctx.session.synthetic` — same
mechanism forge's dispatch plugin already uses). Every plugin decision is appended to an
on-disk JSONL ledger (the `.delegations` pattern from forge's dispatch) and exposed
read-only through a small tool the plugin registers (`ctx.tool.transform`) — the
human-review surface `--auto` never had.

### 4.5 Composition with the existing system

- **Configured deny** — never seen by the plugin (host-enforced, S3).
- **Saved approvals** — indistinguishable from rule allows in the hook event, and the
  plugin ctx has no `saved` accessor. If a human "always"-allowed something the plugin
  hard-denies, the plugin wins — deliberate, and the only sane direction for a
  security boundary (same stance as Anthropic: deny is not overridable).
- **Session-scoped rules** — merged before the hook: a read-only child session (forge's
  `ADHOC_DENY`) is denied before the plugin is consulted; auto-mode composes with
  forge's dispatch isolation for free.
- **`--auto` is a footgun here** — the plugin cannot see the client's `--auto`/
  autoaccept state (it is client-side). Running both means the client auto-approves
  exactly the `ask`s the plugin deliberately left for the human. Documented rule: run
  one or the other; if both are unavoidable, set the plugin's `uncertain` policy to
  `deny` (fail closed).

### 4.6 Host compatibility (the forge#20 dual-entrypoint pattern)

One artifact, both hosts: 2.x loads `setup(ctx)` (the classification core); 1.18.29+
loads `server()`, which **no-ops with a log line** — 1.x has no server-side
permission-evaluation hook, so an honest stub beats a silent approximation. The shared
policy data (rule lists, thresholds) is factored into a plain module both entrypoints
read, so the policy can be reused when 1.x grows an equivalent surface.

### 4.7 What it deliberately does not attempt

Sandboxing/isolation, tool-result content scanning, transcript classification, and any
UI beyond the existing ask prompt — all host-level concerns. The plugin is a decision
layer only; the enforcement substrate is the host's, and that is the point.

## 5. Open questions for the maintainer

1. Package name and home (`opencode-auto-mode`?), and whether v1 ships the `model`
   classifier tier or `rules` only.
2. The `ask`-floor heuristic (re-reading config) vs. asking upstream for the matched
   rule on the evaluate event — worth an upstream issue either way.
3. Whether forge should *reference* the plugin from the opencode emit (an org interview
   answer like `permission.auto_mode: plugin`) or keep it entirely standalone.
4. Confirming the wiki learning to capture after review: the probe facts
   (`ctx.permission` surface, deny-before-hook ordering, saved-approval precedence,
   `.opencode/plugin/` install path) and the decision on this design.
