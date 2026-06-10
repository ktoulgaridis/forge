---
description: Wire a new tracker/SCM/chat/CI adapter into an existing forge-stamped project.
---

# /forge:add-adapter — Add a tool adapter

Pull in a new integration: a chat MCP for notifications, a CI status reporter, an additional tracker. Updates the skills + config.

## Invocation

```
/forge:add-adapter <type>/<name>
```

Examples:
```
/forge:add-adapter chat/slack
/forge:add-adapter tracker/linear        # add Linear in addition to existing tracker
/forge:add-adapter ci/github-actions
```

## What this command does

1. Read `.forge.config.yaml`
2. Locate the adapter at `adapters/<type>/<name>.md` in this plugin's repo
3. Read the adapter's `required_clis` and `optional_mcp_servers`; check what's installed locally
4. Print install hints for missing pieces; pause for user to install (or skip)
5. Inject the adapter's snippets into:
   - `.claude/skills/prime/SKILL.md` (tracker/SCM adapters affect how prime pulls live state)
   - `.claude/skills/dispatch/SKILL.md` (tracker/SCM adapters affect how dispatch creates work items)
   - For chat adapters: add notification hooks in role files where appropriate
6. Update `.forge.config.yaml` — append to `integrations[]`
7. Open a wiki MR

## Multi-tracker case

A project can use more than one tracker (e.g., Jira for product issues + Linear for engineering bugs). When adding a second tracker:

- Mark which tracker each stream uses in `.forge.config.yaml`
- The skill templates branch on stream → tracker

## Cleanup

If you added an adapter that turned out to be unused, run `/forge:configure` to remove it. The plugin doesn't auto-remove integrations.
