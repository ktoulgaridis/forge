---
type: tracker
name: jira-multi
description: Jira Cloud (Atlassian) with multiple boards, mapped one-to-one to streams. Each stream's queue lives on its own board.
required_clis:
  - name: jira
    test: "jira me"
    install_hint:
      macos: "brew install ankitpokhrel/tap/jira-cli"
      linux: "go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest"
optional_mcp_servers:
  - name: atlassian
    description: Richer Jira + Confluence access via MCP
    settings_snippet: |
      "atlassian": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-atlassian"],
        "env": {
          "ATLASSIAN_DOMAIN": "<your-org>.atlassian.net",
          "ATLASSIAN_EMAIL": "<your-email>",
          "ATLASSIAN_API_TOKEN": "<token>"
        }
      }
config_schema:
  base_url:
    type: string
    required: true
    example: "https://acme.atlassian.net"
  installation:
    type: string
    enum: [cloud, server]
    default: cloud
  boards:
    type: list
    required: true
    description: One entry per stream
    item_schema:
      stream_id: { type: string, required: true, example: "A" }
      project_key: { type: string, required: true, example: "BACKEND" }
      board_id: { type: number, required: false, description: "Numeric Jira board ID; needed for sprint queries" }
---

# Adapter: jira-multi

Jira (Atlassian Cloud) with **multiple boards**, one per stream. Use this when your org maps streams (backend / frontend / coord) to separate Jira projects or boards.

For single-board Jira, use `jira-single` instead.

## Setup

```bash
jira init --installation cloud --server https://acme.atlassian.net
# Follow prompts; provide email + API token (https://id.atlassian.com/manage-profile/security/api-tokens)
```

For multi-project setups, `jira` CLI uses the configured default project. forge's skills explicitly pass `--project` per call to switch.

## Skill snippets

### `prime` — live state

```bash
# All roles — show "my queue" across all configured boards
{{#tracker.config.boards}}
echo "[{{stream_id}}] My in-progress on {{project_key}}:"
jira issue list \
  --project "{{project_key}}" \
  --assignee "$(jira me --plain)" \
  --status "In Progress"
{{/tracker.config.boards}}

# Implementer / Migration Analyst
jira issue view "$ISSUE_ID"  # Jira keys are globally unique (PROJECT-NN)

# Reviewer (uses scm adapter for the MR/PR side)

# Orchestrator (per-stream queue)
{{#tracker.config.boards}}
echo "Stream {{stream_id}} backlog ({{project_key}}):"
jira issue list \
  --project "{{project_key}}" \
  --status "To Do" \
  --assignee "x"  # unassigned only
{{/tracker.config.boards}}
```

### `dispatch` — work creation

```bash
# Resolve which Jira project to use based on the stream
case "$STREAM_ID" in
{{#tracker.config.boards}}
  "{{stream_id}}") JIRA_PROJECT="{{project_key}}" ;;
{{/tracker.config.boards}}
  *) error "Unknown stream $STREAM_ID" ;;
esac

jira issue create \
  --project "$JIRA_PROJECT" \
  --summary "$ISSUE_TITLE" \
  --body "$ISSUE_BODY" \
  --type "Task" \
  --label "theme:$THEME_LABEL" \
  --label "size:$SIZE_LABEL" \
  --label "area:$AREA_LABEL"
```

### Mapping ticket → MR/PR

Jira ticket keys (e.g., `BACKEND-127`) should appear in MR/PR titles for auto-linking. The scm adapter handles MR/PR creation; titles include the key:

```
[BACKEND-127] T1-02 BFF chassis: chi, /healthz, OTel
```

Atlassian's GitHub/GitLab integration auto-links these.

## Doctor checks

```bash
command -v jira >/dev/null || error "jira-cli not installed"
jira me --plain >/dev/null 2>&1 || error "jira not configured (run 'jira init')"

{{#tracker.config.boards}}
jira issue list --project "{{project_key}}" --paginate 1 >/dev/null 2>&1 \
  || error "Cannot access project {{project_key}} — check permissions"
{{/tracker.config.boards}}
```

## Examples

Sample `.forge.config.yaml`:

```yaml
tracker:
  type: jira-multi
  config:
    base_url: https://acme.atlassian.net
    installation: cloud
    boards:
      - { stream_id: A, project_key: BACKEND }
      - { stream_id: B, project_key: FRONTEND }
      - { stream_id: C, project_key: COORD }
```

Then `prime orchestrator` runs, in effect:

```bash
jira issue list --project BACKEND  --status "To Do" --assignee x
jira issue list --project FRONTEND --status "To Do" --assignee x
jira issue list --project COORD    --status "To Do" --assignee x
```

## Notes

- **Workflows differ per Jira project.** "To Do", "In Progress", "Done" are common but your org may use "Open", "Doing", "Closed" or "Selected for Development". Adjust the status filters in the skills accordingly — adapter has sensible defaults but check your tenant's workflow.
- **Sprints (Scrum) vs no sprints (Kanban).** If methodology=scrum, the orchestrator's queue view should filter to active sprint. Add `--sprint "Active Sprint"` or specific sprint ID. forge's methodology=scrum bundle does this automatically.
- **Linking MRs/PRs to issues.** Smart Commits + branch naming (`BACKEND-127-bff-chassis`) helps Atlassian's bidirectional sync.
- **JQL escapes.** `jira-cli` accepts JQL via `--jql`; complex queries are easier than filter flags. Examples in the wiki's `themes/T*.md` orchestrator-prep notes.
