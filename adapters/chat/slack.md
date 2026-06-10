---
type: chat
name: slack
description: Slack notifications + handoff messages via Slack MCP
required_clis: []
optional_mcp_servers:
  - name: slack
    required: true
    settings_snippet: |
      "slack": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {
          "SLACK_BOT_TOKEN": "xoxb-...",
          "SLACK_TEAM_ID": "T..."
        }
      }
config_schema:
  workspace:
    type: string
    required: true
    example: "acme"
  channels:
    type: object
    required: true
    description: Channel names (without #) for various notification kinds
    properties:
      handoffs: { type: string, example: "agent-handoffs" }
      blockers: { type: string, example: "agent-blockers" }
      releases: { type: string, example: "releases" }
---

# Adapter: slack

Slack notifications for inter-agent handoffs and human escalations.

## Setup

1. Create a Slack app + bot in your workspace
2. Grant scopes: `chat:write`, `chat:write.public`, `channels:read`
3. Install to workspace; copy bot token (`xoxb-...`)
4. Add Slack MCP server to `~/.claude/settings.json` with the token
5. Restart Claude Code; `/mcp` should show slack connected

## What this adapter adds

### Notification hooks in role files

Stamped role files get a "Handoff" section that includes Slack notification:

```markdown
## Handoff (with Slack)

When this role completes a unit of work, post to Slack:

mcp__slack__post_message \
  --channel="{{chat.config.channels.handoffs}}" \
  --text=":hand: <role-name> completed <issue-id> — handing off to <next-role>"
```

### Escalation hook in Orchestrator

When the orchestrator surfaces a decision that exceeds delegated authority:

```markdown
mcp__slack__post_message \
  --channel="{{chat.config.channels.blockers}}" \
  --text=":raised_hands: Need human input on <issue-id>: <summary>"
```

### Release announcements

The release-manager role (if added) posts to `releases` channel on deploy success.

## Doctor

```bash
grep -q '"slack"' ~/.claude/settings.json || error "slack MCP not in settings.json"
# Connectivity check is implicit — first MCP call will surface auth issues
```

## Notes

- **Don't spam channels.** Notifications are for handoffs (agent→agent or agent→human), blockers, and major status changes — not for every commit.
- **Channel naming.** Conventions vary; default to `agent-handoffs`, `agent-blockers`, `releases`. Adjust per-org.
- **Threading.** Long-running discussion (e.g., a debate about an ADR) should thread under the original message, not flood the channel.
- **Bot user vs. user token.** Use a bot token; user tokens lock notifications to one human and break when they leave.
- **Rate limits.** Slack's rate limits are forgiving for bot apps but not infinite; cap notifications to ~1/sec per channel under burst conditions.
