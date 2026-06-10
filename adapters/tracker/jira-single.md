---
type: tracker
name: jira-single
description: Jira Cloud or Server with a single project/board, streams as labels
required_clis:
  - name: jira
    test: "jira me"
    install_hint:
      macos: "brew install ankitpokhrel/tap/jira-cli"
      linux: "go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest"
optional_mcp_servers:
  - name: atlassian
    settings_snippet: |
      "atlassian": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-atlassian"]
      }
config_schema:
  base_url: { type: string, required: true }
  project_key: { type: string, required: true, example: "PLAT" }
  installation: { type: string, enum: [cloud, server], default: cloud }
---

# Adapter: jira-single

Jira with one project; streams represented as labels (`stream:A`, `stream:B`, etc.) within that project.

## Setup

```bash
jira init --installation cloud --server https://acme.atlassian.net --project PLAT
```

## Skill snippets

### `prime`

```bash
# All roles
jira issue list --project "{{tracker.config.project_key}}" \
  --assignee "$(jira me --plain)" --status "In Progress"

# Orchestrator (per-stream, via labels)
{{#streams}}
echo "Stream {{id}}:"
jira issue list --project "{{tracker.config.project_key}}" \
  --label "stream:{{id}}" --status "To Do" --assignee "x"
{{/streams}}
```

### `dispatch`

```bash
jira issue create \
  --project "{{tracker.config.project_key}}" \
  --summary "$ISSUE_TITLE" \
  --body "$ISSUE_BODY" \
  --type "Task" \
  --label "theme:$THEME_LABEL,area:$AREA_LABEL,size:$SIZE_LABEL,stream:$STREAM_ID"
```

## Doctor

```bash
command -v jira >/dev/null || error "jira-cli not installed"
jira me --plain >/dev/null 2>&1 || error "jira not configured"
jira issue list --project "{{tracker.config.project_key}}" --paginate 1 >/dev/null \
  || error "Cannot access {{tracker.config.project_key}}"
```

## Notes

- For multi-project Jira setups, use `jira-multi` instead
- Methodology bundles (Scrum vs. Kanban) tweak the status filters
- See `jira-multi.md` for general Jira notes about workflows, sprints, smart commits
