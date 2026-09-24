# The verify gate: a script decides whether the builder's PR opens

**Why.** The builder reviews its own diff in the same context that wrote it (ADR 0018).
An agent that reviews its own work repeats its own mistakes, and agents claim success on
patches whose tests fail or whose tests they edited. So forge takes that call away from
the builder. A script's exit code decides whether the builder's PR create runs, and the
script's verdict, not the builder's claim, goes in the PR body and the RESULT line.

## In the graph

`verify` is a **check** node: a node whose exit a script decides. Its pass is `terminal`
and its fail is `next`:

```yaml
review: { rubric: review, max_visits: 4, next: [clear, fix] }
fix:    { skill: build-fix, next: validate }
clear:  { rubric: gate, next: [verify, fix] }                  # gate FAIL, in scope -> fix
verify: { check: verify, next: fix, terminal: pr_open }       # the PR-create gate decides
```

A rubric node is a verdict, so it must declare its FAIL edge in `next`. Before this,
`clear` was `{ rubric: gate, terminal: pr_open }` while the gate rubric looped `clear`
back to `fix`, and the loop check could not see that edge. Now every loop through `clear`
or `verify` passes through `review`, which is capped. The execute worker's graph must
carry `check: verify`: emit refuses it without one, and prints the two lines to add.

## The check (`templates/checks/verify-gate.py.template`)

For the worktree the PR create runs in (a leading `cd <dir> &&`, else the shell's working
directory):

1. The builder declared its test command in `validate`, in
   `$(git rev-parse --absolute-git-dir)/verify-test`. The file lives in the worktree's own
   git dir, never in the tree, so it is never committed. It holds `command: <cmd>` and
   optional `test: <pattern>` lines.
2. In a **temporary worktree** of HEAD, the command must pass.
3. With every non-test change reverted to the merge-base with the default branch
   (`origin/HEAD`, else `origin/main`, `origin/master`, `main`, `master`), keeping the new
   and changed tests, the command must fail.
4. A test file that existed at the merge-base and was modified or deleted is reported as
   `protected-edited`. It does not block.
5. The PR body must carry the verdict, `verify=<pass|no-tests|protected-edited>`, in the
   command or in its `--body-file`. The gate checks that a verdict line is present before
   it runs anything, and that it matches after.

A diff with no test change is `no-tests`: the command must still pass at HEAD, but there
is nothing to revert against. A diff that changes only tests has no non-test change to
revert, so it is `pass` (or `protected-edited`).

Test files are found by name: `*_test.go`, `*.test.*`, `*.spec.*`, `test_*.py`,
`*_test.py`, and anything under a `tests/`, `test/` or `__tests__/` directory. The
declaration can add patterns but cannot remove these. Adding a path can only make the
gate stricter: a source file declared as a test stays at HEAD in the reverted run, so the
command still passes there, and the gate fails.

The builder's own tree is never touched. The temporary worktree is removed on every exit
path: a normal exit, a refusal, an error, a timeout, and SIGTERM / SIGINT / SIGHUP (the
running test process group is killed first). Each test run is bounded at 1500 s, fixed at
emit (`VERIFY_RUN_TIMEOUT` in `lib/emit.py`) so that nothing at run time can raise it past
the host's hook timeout. Anything the script cannot check blocks the PR create: a missing
declaration, no default branch, a git error, a timeout or a signal.

## Enforcement per host

**Claude Code.** `hooks/hooks.json` runs `hooks/scripts/verify-gate.sh` as a PreToolUse
hook on Bash, with a `timeout` of 3600 s (two bounded runs plus 600 s). A hook the host
times out does not block, so the host limit must exceed two bounded runs, and emit asserts
that it does. The hook keys on
`agent_type`: a plugin subagent reports `<plugin>:<agent>`, and the bare name covers a copy
of the agent run outside the plugin. This is the same contract as `code-read-gate`; see
[read-only-code-surface.md](read-only-code-surface.md). Exit 2 blocks, with the reason on
stderr. The shell wrapper runs the Python gate in the background and forwards
TERM/INT/HUP to it, so the gate can remove its worktree before it exits.

**opencode.** `plugin/verify.js` guards the shell tool (`bash` on 1.x, `shell` on 2.x) and
runs `plugin/verify-gate.py` beside it. Both hosts load only `*.js`/`*.ts` from `plugin/`
(1.x `config/plugin.ts` globs `{plugin,plugins}/*.{ts,js}`; 2.x
`plugin/source-directory.ts` takes `.ts`/`.js` files), so the script is never loaded as a
plugin.

- **2.x:** `ctx.tool.hook("execute.before", …)`. The event carries `agent`
  (`packages/plugin/src/promise/tool.ts` @ v2.0.14).
- **1.x:** `tool.execute.before`. Its input is `{ tool, sessionID, callID }` with no agent
  (`packages/plugin/src/index.ts`). `chat.params` fires before every model request with
  `{ sessionID, agent }` (`session/llm/request.ts`), so the guard records each session's
  agent there. A PR create from a session it never recorded is blocked.

A throw rejects the call on both hosts. On 1.x the hook runs through `Effect.promise`
(`plugin/index.ts` trigger), and the tool call fails with the error. On 2.x a promise
hook's rejection is a defect (`packages/plugin/src/promise/adapter.ts`). The step runner
turns that defect into a failure of that tool call and continues the turn
(`packages/core/src/session/runner/step.ts`, `classifyToolExits` →
`failUnsettledTools`). These are read from source; this change did not run a live host.

## Limits (what the gate does not see)

- It matches `gh pr create` and `gh pr new`. A PR opened another way (the REST API, a
  browser, another client, an MCP tool the session carries) is not gated. The `verify`
  node tells the builder that the gate is the only way the graph reaches `pr_open`, but a
  builder that ignores the node can bypass it. The human merge gate and CI remain the relied-upon review.
- It checks the committed HEAD, not uncommitted changes. That is what the PR carries.
- The declared command runs from the root of a **fresh checkout**, so it must set itself
  up the way CI does (`npm ci && npm test`, a `uv run …`, `git submodule update --init`).
  A command that names the builder's worktree path is refused.
- Tests for behavior the default branch already has cannot pass next to other changes
  (reverting the other changes leaves them passing). A test-only PR passes. The builder
  is told to split such work, or to end `BLOCKED`.
- A run at the loop cap opens no PR at all, drafts included: the builder pushes its branch
  and reports `pr=none`.
- The builder chooses the command. The revert check does not care which command it is:
  whatever it declares must pass at HEAD and fail without the change. The gate rubric asks
  that it be the same command as the RESULT line's `tests=`.
- SIGKILL cannot be trapped. A gate killed that way leaves its temporary directory
  behind. `git worktree prune` drops the stale metadata once that directory is gone.

## Proof

`tests/test_verify_gate.py` emits both targets and runs the emitted gate against
throwaway git repos, with a real shell test command. It covers pass; tests that still pass
with the source reverted (fail); a command that fails at HEAD; protected tests modified
and deleted (flagged); no tests changed (`no-tests`); declared test paths; the verdict in
a body file; the builder's tree unchanged after a pass, after a failure and after a
SIGTERM; and every other agent, tool and command ignored. The Claude Code tests execute
the hook script. The opencode tests drive `plugin/verify.js` through
`tests/verify_harness.mjs` on both host entrypoints.
