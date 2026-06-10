---
type: tracker
name: gitlab
description: GitLab Issues (any host — gitlab.com or self-hosted)
required_clis:
  - name: glab
    test: "glab auth status"
    install_hint:
      macos: "brew install glab"
      linux: "apt install glab  # or download binary from https://gitlab.com/gitlab-org/cli/-/releases"
optional_mcp_servers: []
config_schema:
  host:
    type: string
    required: true
    example: "gitlab.com"
  project:
    type: string
    required: true
    example: "myorg/myproject"
---

# Adapter: gitlab tracker

GitLab Issues — works with `gitlab.com` or self-hosted instances. Uses [`glab`](https://gitlab.com/gitlab-org/cli) CLI.

## Setup

```bash
# Authenticate per host (multi-host glab supports several configured)
glab auth login --hostname gitlab.com
# or self-hosted:
glab auth login --hostname gitlab.acme.com

# Set the active host for this shell session
export GITLAB_HOST=gitlab.acme.com
```

The forge-stamped skills reference `$GITLAB_HOST` (set in role files; persisted to `.envrc` if `direnv` is detected during bootstrap).

## Skill snippets

### `prime` — live state

```bash
# All roles
glab issue list --assignee=@me --state=opened -R "{{tracker.config.project}}"

# Implementer / Migration Analyst
glab issue view "$ISSUE_ID" -R "{{tracker.config.project}}"

# Reviewer (uses scm/gitlab adapter)
glab mr view "$MR_URL"
glab mr diff "$MR_URL"

# Orchestrator (per-stream, by label)
{{#streams}}
echo "Stream {{id}} backlog:"
glab issue list -R "{{tracker.config.project}}" \
  --label "stream:{{id}}" --state=opened --assignee=null
{{/streams}}

# Wiki Maintainer
glab mr list -R "{{wiki.remote_url_path}}" --state=opened
```

### `dispatch` — work creation

```bash
glab issue create -R "{{tracker.config.project}}" \
  --title "$ISSUE_TITLE" \
  --description "$ISSUE_BODY" \
  --label "theme:$THEME_LABEL,area:$AREA_LABEL,size:$SIZE_LABEL,stream:$STREAM_ID"
```

## Doctor checks

```bash
command -v glab >/dev/null || error "glab not installed"
glab auth status 2>&1 | grep -q "Logged in" || error "glab not authed"
glab issue list -R "{{tracker.config.project}}" --paginate=1 >/dev/null 2>&1 \
  || error "Cannot access {{tracker.config.project}} — check permissions"
```

## Examples

```bash
# Smoke test
GITLAB_HOST=gitlab.example.com glab issue list -R socwave/socwave-platform --state=opened
```

## Notes

- glab supports multiple GitLab hosts simultaneously — the `GITLAB_HOST` env var picks active one
- For private GitLab instances, you may need to set `GITLAB_TOKEN` or `GITLAB_CLI_HOST` env vars; check `glab auth status`
- Issue work-items vs. legacy issues: glab transparently uses Work Items API on GitLab 16+ if available
