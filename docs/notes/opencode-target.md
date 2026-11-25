# The opencode target

`/forge:emit` reads one `.forge.org.yaml` and emits either:

- **A Claude Code plugin** (`--target claude-code`, the default) — skills + agents + hooks + a marketplace manifest, validated and ready to install.
- **An opencode configuration** (`--target opencode`) — `opencode.json` + `agent/` + `command/` + `skill/` + `rubric/` + `node/` + `plugin/dispatch.js`. The orchestrator's one primitive is `dispatch({ agent, ticket, repo?, model?, variant?, task_id?, command? })`: it launches only the workers the graph catalog declares, the ticket is the whole envelope, N calls per turn run in parallel, `task_id` continues the same worker, a worktree worker gets one git worktree per (repo, ticket), and the `<run-closed>` postback carries the worker's RESULT line.

**The opencode artifact is back/forward compatible by construction.** One emitted package runs unchanged on opencode **1.18.29+** and **2.x**:

- the emitted plugins carry both host entrypoints — 2.x loads `setup()`, 1.18.29+ loads `server()` — driving the same role allowlist, model policy and read-only boundary;
- the rest of the layout (`agent/`, `command/`, `skill/`, `opencode.json`) is natively understood by both hosts; 2.x translates the 1.x `permission` block automatically (`task` → `subagent`, `bash` → `shell`);
- `emit` detects the installed opencode and refuses hosts below the floor;
- `instructions` entries load on opencode 2.2.0 (checked 2026-11-25: a fresh session's stored instruction set held every listed file; directory entries are skipped, which is why emit drops them). Earlier 2.x builds did not load them, so the emitted `AGENTS.md` carries the same pointers;
- the session-start toast nudge is 1.x-only until a 2.x TUI plugin ships.
