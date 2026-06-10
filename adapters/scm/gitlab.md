---
type: scm
name: gitlab
description: GitLab for source control + Merge Requests
required_clis:
  - name: glab
    test: "glab auth status"
    install_hint:
      macos: "brew install glab"
      linux: "apt install glab"
optional_mcp_servers: []
config_schema:
  host: { type: string, default: gitlab.com }
  default_branch: { type: string, default: main }
  mr_template_path: { type: string, default: ".gitlab/merge_request_templates/Default.md" }
---

# Adapter: gitlab SCM

Source control + MR management on GitLab.

## Skill snippets

### `dispatch` — branch + MR conventions

```bash
git checkout -b "$ISSUE_ID/$SLUG"
git commit -m "$THEME: $verb $what ($ISSUE_ID)"
git push -u origin "$ISSUE_ID/$SLUG"

glab mr create \
  --title "[$ISSUE_ID] $THEME: $TITLE" \
  --description "$BODY" \
  --target-branch "{{scm.config.default_branch}}" \
  --remove-source-branch

# Companion wiki MR
( cd "$WIKI_PATH" && \
  git checkout -b "wiki/$ISSUE_ID" && \
  # ... wiki MR content ... \
  glab mr create --title "wiki: update for $ISSUE_ID" --description "..." )
```

### `prime` — Reviewer

```bash
glab mr view "$MR_URL"
glab mr diff "$MR_URL"
glab mr checkout "$MR_ID"
```

### `prime` — Implementer

```bash
glab mr list --author=@me --state=opened
```

## Doctor

```bash
command -v glab >/dev/null || error "glab not installed"
glab auth status 2>&1 | grep -q "Logged in" || error "glab not authed"
```

## Notes

- For self-hosted GitLab, set `GITLAB_HOST` env var (or `glab auth login --hostname your-host`)
- GitLab's MR template at `.gitlab/merge_request_templates/Default.md` is honored
- `glab mr create` flags differ slightly from `gh pr create` — see glab docs
