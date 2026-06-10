---
description: Verify that the active forge project's required CLIs, MCP servers, and credentials are available.
---

# /forge:doctor — Check the forge environment

Run inside a forge-stamped project. Reports what's working, what's missing, and what to install.

## Invocation

```
/forge:doctor
```

## What this command does

1. Read `.forge.config.yaml`
2. For every adapter listed in `tracker`, `scm`, `integrations`:
   - Read the adapter's `required_clis` and `optional_mcp_servers`
   - Test each CLI: `command -v <cli>`; if present, run a smoke check (`gh auth status`, `glab auth status`, `jira me`, etc.)
   - Test each MCP server: check Claude Code's `/mcp` registration
3. For every role in `roles[]`:
   - Verify `roles/<name>.md` exists in the project
   - Verify `.claude/skills/prime/SKILL.md` recognizes the role name
4. For the wiki structure:
   - Verify `CLAUDE.md` exists at root
   - Verify `decisions/`, `services/`, `themes/`, `roles/` dirs exist
   - Verify `requirements/` (or equivalent canonical-requirements dir) exists
5. Print a tabular report:

```
forge:doctor v0.1.0  ──────────────────────────────────  ✓ N passed  ⚠ M warnings  ✖ K errors

CLIs (X/Y passed)
  ✓ git
  ✓ gh — authed as <user>
  ⚠ jira — installed but not configured (run `jira init`)
  ✖ glab — not installed
      └─ Install: brew install glab  (or apt install glab)

MCP servers (X/Y registered)
  ✓ figma — connected
  ⚠ slack — declared in config but not registered in /mcp
      └─ Add to ~/.claude/settings.json:
          { "mcpServers": { "slack": { "type": "http", "url": "..." } } }

Roles (X/Y present)
  ✓ orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst

Wiki structure (passed)
  ✓ CLAUDE.md present
  ✓ decisions/, services/, themes/, roles/ all populated
```

6. Exit code 0 if all checks pass; non-zero if errors

## When to run

- After `/forge:new` — confirms the bootstrap landed cleanly
- After `/forge:add-adapter` — confirms the new integration's dependencies are met
- Periodically — catches local environment drift (a CLI auth expired, etc.)
- In CI for the wiki repo — verify the wiki is forge-compliant

## Limitations

- Doesn't check token validity for tools (e.g., your Jira token might be expired but `jira me` will tell you that — we surface the error, we don't refresh)
- Doesn't install missing tools automatically (asks the user to)
- Doesn't validate the actual Cedar/Karpathy schema (that's `/wiki:lint`)
