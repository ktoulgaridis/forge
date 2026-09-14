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
    required: false
    example: "acme/platform"   # default repo for keys written as "#123"; keys may
                              # always carry their own repo: "acme/platform#123"
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

These map to the `{{TRACKER_*_SNIPPET}}` placeholders in `templates/org-plugin/`.
A ticket key is `owner/repo#N`; a bare `#N` means `{{tracker.config.repo}}`. Every
snippet derives the repo from the key, so one org with many repos needs no board
config. Verbs validated against `gh` 2.x.

### `TRACKER_PRIME_SNIPPET`

```bash
# My in-flight work across every repo I can see (assignee already scopes it to me):
gh search issues --assignee=@me --state=open --json repository,number,title,labels \
  --jq '.[] | "\(.repository.nameWithOwner)#\(.number)\t\(.title)\t\([.labels[].name]|join(","))"'

# A specific ticket (if a key was passed): repo comes from the key, not from config.
KEY="<owner/repo#N or #N>"; REPO="${KEY%%#*}"; NUM="${KEY##*#}"; REPO="${REPO:-{{tracker.config.repo}}}"
gh issue view "$NUM" -R "$REPO" --json title,state,labels,body
```

Surface results at T1 (key, title, labels); pull bodies only when a step needs them.

### `TRACKER_VIEW_ISSUE_SNIPPET`

```bash
KEY="<owner/repo#N or #N>"; REPO="${KEY%%#*}"; NUM="${KEY##*#}"; REPO="${REPO:-{{tracker.config.repo}}}"
gh issue view "$NUM" -R "$REPO" --json title,state,labels          # T1
gh issue view "$NUM" -R "$REPO" --json title,state,labels,body     # full spec, when needed
```

### `TRACKER_COMMENT_LIST_SNIPPET`

```bash
# Comments carry the refinement, decisions and PR/VERDICT lines — `view` without
# --comments omits them.
gh issue view "$NUM" -R "$REPO" --comments
```

### `TRACKER_COMMENT_SNIPPET`

```bash
gh issue comment "$NUM" -R "$REPO" --body "<update>"
gh issue comment "$NUM" -R "$REPO" --body-file ./update.md
```

### `TRACKER_CREATE_TASK_SNIPPET`

```bash
# One task per (repo × concern), in THAT repo, linked to the story by reference —
# GitHub cross-links "owner/repo#N" automatically; no hierarchy feature is assumed.
gh issue create -R "<owner/target-repo>" \
  --title "<concern>" \
  --label "task" \
  --body "Part of ${STORY_REPO}#${STORY_NUM}

<acceptance criteria + test expectations + constraints + deps>"
# Then record the child on the story so the tree is readable from the top:
gh issue comment "$STORY_NUM" -R "$STORY_REPO" --body "Task: <owner/target-repo>#<new-N> — <concern>"
```

### `TRACKER_BACKLOG_SNIPPET`

```bash
# Swarm-ready work across every repo of the org: the refine→execute gate is the
# `agent-ready` LABEL (see TRACKER_GATE_SNIPPET), so no board or project is pinned.
OWNER="${REPO%%/*}"
gh search issues --owner "$OWNER" --label agent-ready --state=open \
  --json repository,number,title --jq '.[] | "\(.repository.nameWithOwner)#\(.number)\t\(.title)"'
```

Backlog origination is the human's: stories are plain issues in the repo they concern,
in OUTLINE form (need + repos + acceptance-test sketch); they become agent-ready via
refine, never at creation.

### `TRACKER_GATE_SNIPPET`

```bash
# The gate is a LABEL — every repo supports labels with no admin setup:
#   agent-ready    — refine passed (problem refined + acceptance/validation test defined). REQUIRED before execute.
#   agent-blocked  — an agent surfaced a decision that needs the engineer.
gh issue view "$NUM" -R "$REPO" --json labels --jq '[.labels[].name] | index("agent-ready") != null'

# Apply / clear (create the label once per repo if it does not exist yet):
gh label create agent-ready -R "$REPO" --color 0E8A16 --force >/dev/null
gh issue edit "$NUM" -R "$REPO" --add-label agent-ready
gh issue edit "$NUM" -R "$REPO" --remove-label agent-ready
```

### `TRACKER_READONLY_COMMANDS`

The commands a read-only role (reviewer, gate) may run — everything else is denied.
One `bash` permission pattern per line.

```text
gh issue view *
gh issue list *
gh search issues *
gh pr view *
gh pr diff *
gh pr checks *
gh api repos/*
```

## Doctor

### `TRACKER_DOCTOR_SNIPPET`

```bash
command -v gh >/dev/null || echo "install: https://cli.github.com"
gh auth status || gh auth login
```

## Notes

- No boards, no projects, no PM tool assumed: issues + labels + comments are the bus.
- Projects v2 can sit on top for a board view; the harness never depends on it.
