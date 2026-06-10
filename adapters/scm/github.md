---
type: scm
name: github
description: GitHub for source control + Pull Requests
required_clis:
  - name: gh
    test: "gh auth status"
    install_hint:
      macos: "brew install gh"
      linux: "apt install gh  # or https://cli.github.com/manual/installation"
optional_mcp_servers:
  - name: github
    settings_snippet: |
      "github": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"]
      }
config_schema:
  host: { type: string, default: github.com }
  default_branch: { type: string, default: main }
  pr_template_path: { type: string, default: ".github/pull_request_template.md" }
---

# Adapter: github SCM

Source control + PR management on GitHub.

## Skill snippets

### `dispatch` — branch + PR conventions

The Implementer's prompt template includes:

```bash
# Branch naming: <issue-id>/<short-slug>
git checkout -b "$ISSUE_ID/$SLUG"

# Commits: structure or behavior, never both
git commit -m "$THEME: $verb $what ($ISSUE_ID)"

# Push + create PR
git push -u origin "$ISSUE_ID/$SLUG"
gh pr create \
  --title "[$ISSUE_ID] $THEME: $TITLE" \
  --body "$BODY" \
  --base "{{scm.config.default_branch}}"

# Companion wiki PR (in wiki repo)
( cd "$WIKI_PATH" && \
  git checkout -b "wiki/$ISSUE_ID" && \
  # ... wiki MR content ... \
  gh pr create --title "wiki: update for $ISSUE_ID" --body "..." )
```

### `prime` — Reviewer's MR fetch

```bash
gh pr view "$PR_URL"
gh pr diff "$PR_URL"
gh pr checkout "$PR_URL"  # Pull the branch locally to run tests
```

### `prime` — Implementer's recent activity

```bash
gh pr list --author=@me --state=open
```

## Doctor

```bash
command -v gh >/dev/null || error "gh not installed"
gh auth status 2>&1 | grep -q "Logged in" || error "gh not authed"
```

## Notes

- gh handles host selection automatically based on the repo's remote URL
- For org-level features (CODEOWNERS auto-assign, branch protection), configure in GitHub UI; forge doesn't manage those
- PR template at `.github/pull_request_template.md` is honored automatically by `gh pr create`
- GitHub Actions integrates well with `gh` for CI status (`gh pr checks`)
