---
type: tracker
name: jira-mcp
description: Jira Cloud accessed via the Atlassian MCP server (no CLI). Streams as labels or sub-tasks within one project.
required_clis: []
optional_mcp_servers:
  - name: atlassian
    settings_snippet: |
      "atlassian": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"]
      }
config_schema:
  cloud_id: { type: string, required: true, example: "00000000-0000-0000-0000-000000000000" }
  project_key: { type: string, required: true, example: "ABC" }
  base_url: { type: string, required: true, example: "https://acme.atlassian.net" }
---

# Adapter: jira-mcp

Jira via the **Atlassian MCP** (`mcp__plugin_atlassian_atlassian__*` tools), not the
`jira` CLI. Use this when the org drives Jira through MCP tool calls. Coordination
and traceability flow through Jira; this adapter supplies the snippets the org-plugin
skills inline.

## Skill snippets

These map to the `{{TRACKER_*_SNIPPET}}` placeholders in `templates/org-plugin/`.
`cloud_id` is substituted from `.forge.org.yaml`; `project_key` is an OPTIONAL default
board only (my-work and the swarm-ready gate span every board you can see, and
single-ticket lookups derive their board from the ticket KEY PREFIX at runtime).

### `TRACKER_PRIME_SNIPPET`

```
Pull live state via the Atlassian MCP (cloudId `{{tracker.config.cloud_id}}`):
- My in-flight work, ACROSS EVERY board I can see — do NOT pin one project; the
  assignee filter already scopes it to me, and an engineer's work spans multiple boards:
  searchJiraIssuesUsingJql — jql: "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
    (Optionally narrow to a default board by prefixing `project = {{tracker.config.project_key}} AND …`
     — an OPTIONAL scope, not the default. My-work spans all my boards.)
- A specific ticket (if a key was passed): the board/project is DERIVED FROM THE KEY
  PREFIX at runtime (e.g. ABC-123 → project ABC); Jira keys are globally unique, so no
  hardcoded config value is needed to resolve it:
  getJiraIssue — issueIdOrKey: <ticket-key>, responseContentFormat: "markdown"
Surface results at T1 (key, summary, status); pull full bodies only when a step needs them.
```

### `TRACKER_VIEW_ISSUE_SNIPPET`

```
Load the ticket via the Atlassian MCP:
  getJiraIssue — cloudId: "{{tracker.config.cloud_id}}", issueIdOrKey: <key>, responseContentFormat: "markdown"
Read the summary + status first; promote to the full description only when a decision requires it.
```

### `TRACKER_COMMENT_SNIPPET`

```
Persist to the ticket via the Atlassian MCP:
- Update fields/description:
  editJiraIssue — cloudId: "{{tracker.config.cloud_id}}", issueIdOrKey: <key>, fields: { ... }
- Or add a comment:
  addCommentToJiraIssue — cloudId: "{{tracker.config.cloud_id}}", issueIdOrKey: <key>, commentBody: "<update>"
- Transition state when the flow says so:
  getTransitionsForJiraIssue then transitionJiraIssue (cloudId "{{tracker.config.cloud_id}}").
```

### `TRACKER_CREATE_TASK_SNIPPET`

```
Create a child task via the Atlassian MCP. A child lives on the SAME board as its
parent story, so DERIVE the project from the parent's KEY PREFIX (e.g. <story-key>
ABC-123 → project ABC) rather than a hardcoded config value. Don't assume the
project's hierarchy either — discover it, then create the right type:
  getJiraProjectIssueTypesMetadata — cloudId: "{{tracker.config.cloud_id}}", projectIdOrKey: "<key-prefix of <story-key>>"
    → pick the child type this project uses under a story (Sub-task, or Task with a parent).
  createJiraIssue — cloudId: "{{tracker.config.cloud_id}}", projectKey: "<key-prefix of <story-key>>",
                    issueTypeName: "<discovered child type>", parent: "<story-key>", summary: "<repo>: <concern>",
                    description: "<acceptance criteria + test expectations + constraints + deps>"
Link dependencies with createIssueLink (type "Blocks") to encode the DAG.
```

### `TRACKER_BACKLOG_SNIPPET`

```
Originate a backlog tree (epics + their stories) via the Atlassian MCP. Origination
targets ONE board — the one you're seeding — so pick the target project key here
(`{{tracker.config.project_key}}` is a sensible default, but use whichever board this
initiative lives on). Discover that project's hierarchy first — don't assume Epic/Story
exist by those names:
  getJiraProjectIssueTypesMetadata — cloudId: "{{tracker.config.cloud_id}}", projectIdOrKey: "<target project key>"
    → identify the top breakdown type (often "Epic") and the story-level type (often "Story").

Create an epic (projectKey = the target board you picked above):
  createJiraIssue — cloudId: "{{tracker.config.cloud_id}}", projectKey: "<target project key>",
                    issueTypeName: "<epic type>", summary: "<epic title>",
                    description: "<the slice of the initiative this epic delivers>"
Create a story under it (parent = the epic key; same board as its epic):
  createJiraIssue — cloudId: "{{tracker.config.cloud_id}}", projectKey: "<key-prefix of <epic-key>>",
                    issueTypeName: "<story type>", parent: "<epic-key>", summary: "a <user> needs to <do X>",
                    description: "<user need + which repos it touches + a first cut at the acceptance test>"
Encode ordering/dependencies between epics or stories with createIssueLink (type "Blocks").
Assign each created issue to the human owner — the human owns the backlog.

Stories are created in OUTLINE form here (need + repos + acceptance-test sketch).
They become agent-ready later via refine — do NOT label them agent-ready at creation.
```

### `TRACKER_GATE_SNIPPET`

```
The refine→execute gate is carried by a board-agnostic LABEL, not a board-specific
status. Every Jira project supports labels with no admin setup, so this works on any
team's board while leaving their own workflow states untouched.

The harness owns a small label namespace:
  agent-ready    — refine's gate passed (problem refined + acceptance/validation test defined). REQUIRED before execute.
  agent-blocked  — an agent surfaced a decision that needs the engineer.

Read the gate (does this ticket carry the label?):
  getJiraIssue — cloudId: "{{tracker.config.cloud_id}}", issueIdOrKey: <key>, fields: ["labels","summary","status"]
Find all swarm-ready work ACROSS EVERY board you can see — the label is board-agnostic,
so do NOT pin one project; each result's key prefix tells you which board it lives on:
  searchJiraIssuesUsingJql — jql: "labels = agent-ready AND statusCategory != Done"
    (Optionally narrow to one board by prefixing `project = {{tracker.config.project_key}} AND …`.)
Apply/clear the gate label (preserve existing labels — add, don't overwrite):
  editJiraIssue — cloudId: "{{tracker.config.cloud_id}}", issueIdOrKey: <key>, fields: { "labels": [<existing...>, "agent-ready"] }

A team MAY also mirror the gate to one of their real statuses. If the wiki's operating
model names that mapping (e.g. "agent-ready ⇒ status 'Ready for Dev'"), honor it by
discovering the transition and applying it too:
  getTransitionsForJiraIssue → transitionJiraIssue (cloudId "{{tracker.config.cloud_id}}").
But the LABEL is canonical and board-agnostic; the status mirror is optional polish.
```

## Doctor

### `TRACKER_DOCTOR_SNIPPET`

```
The Atlassian MCP server must be connected (the mcp__plugin_atlassian_atlassian__* tools
resolve). If they don't, run /mcp to reconnect. Verify access:
  searchJiraIssuesUsingJql — jql: "project = {{tracker.config.project_key}}", maxResults: 1
```

## Notes

- The MCP sometimes needs a `/mcp` reconnect before its tools surface.
- For Jira ADF vs markdown bodies, prefer `responseContentFormat: "markdown"` on reads
  and `contentFormat: "markdown"` on writes unless full ADF fidelity is needed.
- **Board-from-key (multi-board).** My-work and the swarm-ready gate search span every
  board the user can see (scoped by `assignee`/label, not `project`). Single-ticket
  lookups and child-task creation DERIVE their board/project from the ticket KEY PREFIX
  (`ABC-123` → `ABC`) at runtime, since Jira keys are globally unique. `project_key` in
  config is an OPTIONAL default to narrow a query, never a hard filter on my-work.
