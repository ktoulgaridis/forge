---
type: tracker
name: github
description: GitHub Issues (github.com or GitHub Enterprise Server)
required_clis:
  - name: gh
    test: "gh auth status"
    install_hint:
      macos: "brew install gh"
      linux: "apt install gh  # or https://cli.github.com/manual/installation"
optional_mcp_servers:
  - name: github
    description: Richer GitHub access via MCP (file reads, search, project management)
    settings_snippet: |
      "github": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..." }
      }
config_schema:
  host:
    type: string
    required: false
    default: "github.com"
    example: "github.acme.com"
  repo:
    type: string
    required: true
    example: "acme/platform"
---

# Adapter: github tracker

GitHub Issues. Works with github.com or GitHub Enterprise Server.

## Setup

```bash
gh auth login
# Pick host: github.com or your GHES URL
# Pick protocol: ssh (recommended) or https
# Authenticate via browser
```

For Enterprise Server:
```bash
gh auth login --hostname github.acme.com
```

## Skill snippets

### `prime` — live state

```bash
# All roles
gh issue list -R "{{tracker.config.repo}}" --assignee=@me --state=open

# Implementer / Migration Analyst
gh issue view "$ISSUE_ID" -R "{{tracker.config.repo}}"

# Reviewer
gh pr view "$PR_URL"
gh pr diff "$PR_URL"

# Orchestrator (per-stream, by label)
{{#streams}}
echo "Stream {{id}} backlog:"
gh issue list -R "{{tracker.config.repo}}" \
  --label "stream:{{id}}" --state=open --assignee="@none"
{{/streams}}

# Wiki Maintainer
gh pr list -R "{{wiki.remote_url_path}}" --state=open
```

### `dispatch` — work creation

```bash
gh issue create -R "{{tracker.config.repo}}" \
  --title "$ISSUE_TITLE" \
  --body "$ISSUE_BODY" \
  --label "theme:$THEME_LABEL,area:$AREA_LABEL,size:$SIZE_LABEL,stream:$STREAM_ID"
```

## Doctor checks

```bash
command -v gh >/dev/null || error "gh not installed"
gh auth status 2>&1 | grep -q "Logged in" || error "gh not authed"
gh repo view "{{tracker.config.repo}}" >/dev/null 2>&1 \
  || error "Cannot access {{tracker.config.repo}} — check permissions"
```

## Examples

```bash
gh issue list -R kyriakost/forge --state=open --label "size:1h"
gh issue create -R kyriakost/forge --title "T1-01 BFF chassis" --body "..." --label "theme:T1,area:bff,size:3h,stream:A"
```

## Notes

- GitHub Issues lack first-class boards (use Projects v2 if you want a board view; not required for forge's flow)
- Per-stream label convention works well; some orgs prefer milestones for themes — your choice
- Fine-grained PATs vs. classic PATs: classic recommended for `gh` CLI today; check `gh` docs for fine-grained support
