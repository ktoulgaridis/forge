---
description: Tweak an existing forge-stamped project's adapter config (change tracker, swap SCM, add stream, etc.).
---

# /forge:configure — Reconfigure an existing project

Change the adapters or settings of a project that was already stamped.

## Invocation

```
/forge:configure
```

Run from inside the project's wiki dir. Reads `.forge.config.yaml`.

## What this command does

1. Read `.forge.config.yaml` and `forge_version` to know which template version generated the project
2. Show current config; prompt for what to change:
   - Tracker / SCM / chat adapter
   - Add or remove a stream
   - Add or remove a role
   - Toggle an integration (MCP server)
3. After changes:
   - Update `.forge.config.yaml`
   - Re-render the affected files (skills if adapters changed; role files if roles changed)
   - Open a wiki MR with the changes for review (don't push to main directly)
   - Print install hints for any newly required CLIs/MCPs
4. Run `/forge:doctor` to verify the new shape

## Safety

- Never overwrite ADRs, services, themes, or any human/agent-authored content
- Only re-render files that are forge-managed (carry the `<!-- forge-managed -->` marker comment)
- Backup the previous version of any modified file to `_backup/<timestamp>/` before overwriting

## When to use this vs. editing directly

- Editing a single role's role file: edit directly (it's wiki content)
- Adding a new role to the role bundle: use `/forge:add-role`
- Switching tracker from GitLab to Jira: use `/forge:configure` (skill templates need re-rendering)
- Adding Slack notifications: use `/forge:add-adapter slack`
