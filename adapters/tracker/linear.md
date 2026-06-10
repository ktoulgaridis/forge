---
type: tracker
name: linear
description: Linear — issue tracking via Linear MCP server (no first-class CLI)
required_clis: []
optional_mcp_servers:
  - name: linear
    description: Linear MCP server (required for this adapter; Linear has no production CLI)
    required: true
    settings_snippet: |
      "linear": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-linear"],
        "env": { "LINEAR_API_KEY": "lin_api_..." }
      }
config_schema:
  team_id:
    type: string
    required: true
    description: Linear team ID (e.g., "ENG")
---

# Adapter: linear

Linear — fast, modern issue tracker with no production CLI. Uses Linear's MCP server for all interactions.

## Setup

1. Generate a Linear API key: https://linear.app/settings/api
2. Add the MCP server to `~/.claude/settings.json` (snippet above)
3. Restart Claude Code; verify with `/mcp`

## Skill snippets

### `prime`

```
# All roles — via Linear MCP
mcp__linear__list_issues --team-id="{{tracker.config.team_id}}" --status="In Progress" --assignee="me"

# Implementer / Migration Analyst
mcp__linear__get_issue --id="$ISSUE_ID"

# Orchestrator (per-stream — Linear uses labels for streams)
{{#streams}}
mcp__linear__list_issues --team-id="{{tracker.config.team_id}}" --label="stream:{{id}}" --status="Todo" --unassigned
{{/streams}}
```

### `dispatch`

```
mcp__linear__create_issue \
  --team-id="{{tracker.config.team_id}}" \
  --title="$ISSUE_TITLE" \
  --description="$ISSUE_BODY" \
  --labels="theme:$THEME_LABEL,area:$AREA_LABEL,size:$SIZE_LABEL,stream:$STREAM_ID"
```

## Doctor

```bash
# Verify MCP is registered
# Note: doctor for MCP-backed adapters is partial — we can only check registration, not connectivity
grep -q '"linear"' ~/.claude/settings.json || error "linear MCP not in settings.json"
```

The actual connectivity check is "try to use a Linear MCP tool" — `/forge:doctor` does this implicitly by calling `mcp__linear__list_issues` and reporting failure if it errors.

## Notes

- Linear's data model uses **states** not **statuses** (Backlog, Todo, In Progress, Done, Canceled). Adapter snippets use Linear's terminology.
- Linear's **cycles** are similar to Scrum sprints; the methodology bundle adjusts queries accordingly.
- Linear's **projects** are higher-level than themes; we typically use Linear's project for our "theme" concept and Linear labels for stream/area/size.
- Linear's **Slack integration** is excellent — pair with the `chat/slack` adapter for handoff notifications.
- API rate limits: Linear's API is fast; rate limits are reasonable but not unlimited. Don't paginate gigantic result sets in tight loops.
