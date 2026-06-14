# Adapters

An adapter is the recipe for integrating a tool (tracker, SCM, chat, CI, cloud) into a forge-stamped project. Adapters are declarative — they tell `/forge:new` and `/forge:doctor` how to handle the tool, and they provide skill snippets that get inlined when the project is stamped.

## File location

```
forge/adapters/
├── tracker/
│   ├── gitlab.md
│   ├── github.md
│   ├── jira-single.md
│   ├── jira-multi.md
│   ├── linear.md
│   └── asana.md
├── scm/
│   ├── github.md
│   ├── gitlab.md
│   └── bitbucket.md
├── chat/
│   ├── slack.md
│   ├── teams.md
│   └── discord.md
├── ci/
│   ├── github-actions.md
│   ├── gitlab-ci.md
│   ├── circleci.md
│   └── jenkins.md
└── cloud/
    ├── azure.md
    ├── aws.md
    └── gcp.md
```

## Adapter file format

Each adapter is a markdown doc with a YAML frontmatter block declaring metadata. Example (`adapters/tracker/jira-multi.md`):

```markdown
---
type: tracker
name: jira-multi
description: Jira (Atlassian Cloud), multi-board, streams mapped to boards
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
        "args": ["-y", "@modelcontextprotocol/server-atlassian"]
      }
config_schema:
  base_url:
    type: string
    required: true
    example: "https://acme.atlassian.net"
  boards:
    type: list
    required: true
    item_schema:
      key: { type: string, required: true }
      stream_id: { type: string, required: true }
---

# Adapter: jira-multi

(Documentation about how this adapter works, what to expect, etc.)

## Skill snippets

### prime — live state pull

```bash
# Per role, replace the generic block in prime/SKILL.md
# All roles
{{#streams}}
jira issue list --board={{board.key}} --assignee=$(jira me) --status="In Progress"
{{/streams}}

# Implementer
jira issue view "$ISSUE_ID"

# Reviewer
# (uses scm adapter for the MR side)

# Orchestrator (per-stream queue)
{{#streams}}
echo "Stream {{id}} queue (board {{board.key}}):"
jira issue list --board={{board.key}} --status="To Do" --assignee=null
{{/streams}}
```

### dispatch — work creation

```bash
# Replace the create-issue block in dispatch/SKILL.md
jira issue create \
  --board="$BOARD_KEY" \
  --summary="$ISSUE_TITLE" \
  --description="$ISSUE_BODY" \
  --type=Task \
  --label="theme:$THEME_LABEL" \
  --label="size:$SIZE_LABEL" \
  --assignee="$AGENT_USER"
```

## Doctor checks

```bash
# Test that the CLI is installed and authed
command -v jira || error "jira-cli not installed"
jira me >/dev/null || error "jira not configured (run 'jira init')"

# Verify board access for each configured board
{{#boards}}
jira issue list --board={{key}} --paginate=1 >/dev/null \
  || error "Cannot access board {{key}} — check permissions"
{{/boards}}
```

## Examples

```bash
# Set up
jira init --installation cloud --server https://acme.atlassian.net

# What forge stamps in prime/SKILL.md (with boards substituted)
jira issue list --board=BACKEND --assignee=$(jira me) --status="In Progress"
jira issue list --board=FRONTEND --assignee=$(jira me) --status="In Progress"
```
```

## Snippet syntax

Snippets use `{{...}}` for substitution. Variables come from `.forge.config.yaml`:

- `{{PROJECT_NAME}}`, `{{TRACKER_TYPE}}`, `{{SCM_TYPE}}`
- `{{#streams}}...{{/streams}}` — repeats for each stream
- `{{#boards}}...{{/boards}}` — repeats for each board (jira-multi)
- `{{board.key}}`, `{{stream.id}}`, etc. — context-specific

The renderer is intentionally simple — text substitution + repeats. No complex logic; if an adapter needs branching, write multiple snippets.

## Adapter doctor self-tests

Each adapter should ship a `_test/` dir with:
- A sample `.forge.config.yaml`
- An expected rendered `prime/SKILL.md`
- An expected rendered `dispatch/SKILL.md`

The forge plugin's CI runs these to catch regressions (see
`tests/test_adapter_render.py`, wired into `.github/workflows/validate.yml`).

> **Mirror on the published side (TODO).** The render harness guards the
> *generator*. The EMITTED package repo (e.g. `proscia-techops/proscia-hyperdrive`)
> should carry an equivalent guard in its own CI — a grep/test asserting the
> published skills' ticket-read paths include `comment list` (i.e. are not
> comment-blind). That mirror is a re-emit follow-up, out of scope for forge.

## Writing a new adapter

1. Pick the right type dir (`tracker/`, `scm/`, `chat/`, `ci/`, `cloud/`)
2. Copy `_template.md` (forthcoming) and fill out the YAML frontmatter
3. Write the prose doc (what is this tool? when to use it?)
4. Write the skill snippets — make them concrete, copy-pasteable
5. Add doctor checks
6. Add examples
7. Submit a PR with `_test/` fixtures included

## Roadmap (next adapters to write)

1. **CI: github-actions, gitlab-ci** — skill snippets + sample pipeline templates. The two CI systems we actually use.
2. **Methodology bundles** — not adapters in the strict sense, but the same shape: declarative overlays that substitute into skill snippets. See [`METHODOLOGY.md`](METHODOLOGY.md). Four variants: Scrum, Kanban, RFC-first, **formal-methods (V-model and sub-variants for regulated industries — must-have)**.

## Out of scope (deliberately not building)

To keep focus and quality high, these will not be added:

- **Tracker: asana** — not used
- **SCM: bitbucket** — not used
- **Chat: teams** — not used
- **CI: circleci, jenkins** — not used
- **Notion** as a tracker — API not write-side-friendly
- **ClickUp, Monday.com** — not on the path

## Possible later (no commitment)

- **Chat: discord** — only if a project needs it
- **GitHub Projects v2** — complement to GitHub Issues; could be a tracker variant

If a future project genuinely requires one of the out-of-scope tools, an adapter can be added at that time. v0.1 keeps the surface tight.
