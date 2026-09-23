# Read-only code access for a read_only worker (`code:`)

Status: **shipped in 0.9.6.** A read_only worker graph (e.g. `triage`) may declare

```yaml
code: read                      # forge's whole read-only set
code: [rg *, git log *]         # or a narrowing of it — never a widening
```

and gets code search + git history through a shell each host walls to exactly those
commands. Without `code:` (and without shell patterns in `allow`) the worker has no shell.

## The set, and why each entry is safe

| Pattern | Hazard it can carry | Wall (both hosts) |
|---|---|---|
| `rg *` | `--pre <cmd>` runs a preprocessor per file; `--hostname-bin <cmd>` runs a program | both options denied |
| `grep *`, `ls *`, `cat *`, `head *`, `tail *`, `wc *` | none (no write or exec option) | — |
| `find *` | `-exec`/`-execdir`/`-ok`/`-okdir` run a program; `-delete` deletes; `-fprint*`/`-fls` write | all denied |
| `git log *`, `git show *`, `git diff *` | `--output=<file>` writes the diff; `--ext-diff` runs `diff.external` | both denied |
| `git blame *`, `git rev-parse *`, `git ls-files *` | none | — |

On every command: no redirect, pipe, chain, substitution or expansion (below).

**Left out on purpose.** `git grep` — `-O`/`--open-files-in-pager` runs a program, and
git's bundled short options (`-nO<cmd>`) defeat a pattern-level deny on opencode, whose
patterns see the raw command text. `git status` — it rewrites the index. `sed`, `awk`
— in-place edits, `w`, `system()`. `xargs`, `env`, any interpreter or shell. Any git
subcommand that writes the repo, the index or a remote. `git -C <dir> …` as an opencode
pattern — the `*` it needs would also match `git -C x -c core.pager=<cmd> log`.

Note: `git diff` of the worktree may refresh the index's stat cache (no content change),
as any git read of the worktree can.

## opencode — permission patterns

Verified against upstream opencode **v2.0.12** source:

- `core/src/permission.ts` `evaluate`: the LAST rule whose action and resource patterns
  both match decides; any resource that evaluates to deny blocks the call.
- `core/src/util/wildcard.ts` `match`: `*` is `.*` (it spans spaces), `?` one char, and a
  trailing ` *` also matches the bare command (`git log *` matches `git log`).
- `core/src/v1/config/migrate.ts` `normalizeAction`: the `bash` key is the `shell` action.
- `core/src/tool/plugin/shell.ts` + `core/src/shell/parse.ts` `scanLegacy`: every command
  node of the parsed command (each side of `|`, `;`, `&&`, inside `$(…)`) is its own
  resource, checked separately; a redirected statement's resource includes the redirect.
- `schema/src/agent.ts`: an agent's rules follow the host default `"*": allow`.

So a code worker's block is `"*": deny`, then each declared pattern `allow`, then the
option denies (`"git *--output*": deny`, …) and the redirect denies (`"*>*"`, `"*<*"`),
last. read/grep/glob/list are allowed explicitly; `.env` files are denied (a worker has no
human to answer the default ask).

**Host gap (not closable by permission config).** A statement with no command node —
`> file` alone, or `git log -1; > file` — asks no shell permission at all
(`shell.ts`: `if (parsed.commands.length > 0) permission.assert(…)`; the empty result is
pinned by upstream's own `shell-parse-parity.test.ts`). It can create or truncate a file.
This applies to every opencode agent with a shell allowlist. It is why a worker without
shell patterns keeps its shell wholly disabled — the last shell rule stays the resource-`*`
deny, which removes the tool (`core/src/tool.ts` `whollyDisabled`) — and why the argument
denies are never emitted without an allowlist in front of them. Closing it needs an
opencode plugin guard or an upstream fix.

## Claude Code — a PreToolUse gate

Plugin subagents ignore `permissionMode`, `hooks` and `mcpServers` frontmatter
(code.claude.com/docs/en/sub-agents), so `tools:` can only grant Bash whole. The plugin's
`hooks/hooks.json` therefore runs `hooks/scripts/code-read-gate.sh` before every Bash call.
From code.claude.com/docs/en/hooks: inside a subagent, PreToolUse input carries
`agent_type` (a plugin subagent reports `<plugin>:<agent>`) and `agent_id`; exit 2 blocks
the call (stderr is the reason) and no other exit code blocks on its own. A live probe on
Claude Code 2.1.280 recorded `"agent_type": "<plugin>:triager"` in the hook input and saw
the gate block `date -u` and `git status` that `--allowedTools` had allowed, while
`git -C <repo> log -1` ran. The gate depends on that field: a host whose hook input did
not carry `agent_type` inside a subagent could not tell the worker apart, so the gate
would pass its calls through — use a Claude Code version whose hooks reference documents it.

For a gated worker the command must be ONE simple command: no `; & | < > ( ) { } #`, no
unquoted `* ? [ ]`, no `$`, backquote or backslash outside single quotes, no line break.
Its words must match a declared pattern (`git -C <dir>` is accepted in front of a git
read), and no word may be a denied option — its exact spelling, a longer one, or a git
abbreviation of a long option. An allowed call gets no decision (the user's permission
settings still apply); anything else exits 2. Every other agent, and the main thread,
passes through untouched.

Fail closed: input that names a gated worker and cannot be parsed blocks; a missing
`python3` blocks the gated worker (the shell prefilter only decides that a call cannot
come from one). A hook that times out does not block on Claude Code — the gate is short
and touches no file or network.

Emit refuses: a `code` pattern outside the set; `code:` on anything but a read_only worker;
a read_only worker shell pattern that is not literal words with an optional final ` *`;
and, on the artifact, a read_only worker whose emitted Bash the gate does not wall, or an
opencode worker whose shell block is not exactly deny-first, declared, denies-last.
