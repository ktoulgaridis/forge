# Bootstrap walkthrough

How to stamp your first project with forge.

## Prerequisites

```bash
# Claude Code installed
claude --version

# Git
git --version

# At least one tracker CLI (depending on your choice)
gh --version       # for GitHub
glab --version     # for GitLab
jira --version     # for Jira
linear --version   # for Linear
```

## Install forge

```bash
claude plugins install ktoulgaridis/forge
```

The plugin is a private repo today. To install you need:
- A GitHub PAT in your environment (`GITHUB_TOKEN`) with read access on the repo
- Or clone manually: `git clone git@github.com:ktoulgaridis/forge.git ~/.claude/plugins/forge`

Verify:

```bash
claude
> /help
# Should list /forge:new, /forge:configure, /forge:add-role, /forge:add-adapter, /forge:doctor
```

## First project

```bash
mkdir ~/Work && cd ~/Work
claude
> /forge:new mojave
```

The plugin asks ~7 questions. Sample answers for a GitLab + Azure setup:

```
Where does the wiki live?
> 1 (github.com/<your-user>/mojave-wiki, private)

Tracker?
> 2 (GitLab Issues)

Self-hosted GitLab? URL?
> https://gitlab.acme.com

SCM?
> 2 (GitLab)

Streams?
> 1 (default A=backend, B=frontend, C=coordination, D=human)

Methodology?
> 2 (Kanban)

Roles?
> defaults + add: release-manager

Optional MCPs?
> [x] github MCP, [x] slack MCP

Confirm?
> y
```

The plugin then:
1. Creates the wiki repo on the chosen host
2. Stamps `~/Work/mojave/` with templates rendered against your config
3. Initial commit + push
4. Runs `/forge:doctor` and reports

## Verify

```bash
cd ~/Work/mojave
ls
# Should show: README.md, CLAUDE.md, ROADMAP.md, architecture.md,
#   decisions/, services/, themes/, roles/, .claude/skills/, .forge.config.yaml

cat .forge.config.yaml
# Captured choices

claude
> /forge:doctor
# All required CLIs + MCPs verified
```

## Use it

In the project dir:

```bash
claude
> /prime orchestrator
# Calibrates as orchestrator, pulls live state from tracker, ready to dispatch
```

Or for a specific role:

```bash
> /prime architect T1
> /prime implementer ACME-123
> /prime reviewer https://gitlab.acme.com/.../-/merge_requests/42
> /prime wiki-maintainer
```

## Re-stamp / upgrade

When forge releases a new version, run inside an existing project:

```bash
> /forge:configure
# Detects forge_version from .forge.config.yaml
# Lists changes since that version (e.g., new adapter features)
# Re-renders affected files (skills, role index, etc.)
# Opens a wiki MR for review
```

Never blows away ADRs / services / themes — those are project content, not forge-managed.

## Add a role mid-project

```bash
> /forge:add-role security-reviewer
# Stamps roles/security-reviewer.md from template
# Updates roles/README.md and .claude/skills/prime/SKILL.md
# Opens wiki MR for you to fill in mission/boundaries/etc.
```

## Add an adapter mid-project

```bash
> /forge:add-adapter chat/slack
# Pulls in Slack MCP setup hints
# Inlines notification snippets where appropriate
# Updates .forge.config.yaml
```

## Common gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| `/forge:new` aborts on "wiki repo already exists" | Stale repo from prior attempt | Delete the GitHub/GitLab repo first, or pick a different name |
| `/prime <role>` fails with "live state pull error" | Tracker CLI not authed | Run `gh auth login` / `glab auth login` / `jira init` |
| Slack notifications don't fire | MCP not registered | `/mcp` to check; add to `~/.claude/settings.json` per the slack adapter doc |
| Wiki MR doesn't get auto-created | Implementer skipped `/wiki propose` | Ask the implementer (or re-prime them); not forge's job to enforce post-hoc |

## Reference

- [METHOD.md](METHOD.md) — the patterns forge stamps
- [ADAPTERS.md](ADAPTERS.md) — how adapters work
- [ROLES.md](ROLES.md) — the role pattern
- [examples/socwave.md](../examples/socwave.md) — a real engagement using these patterns
