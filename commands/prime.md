---
description: Calibrate a Claude Code session for forge framework development. Loads docs, recent commits, version state, roadmap, scope. Run at the start of every forge work session.
---

# /forge:prime — Calibrate this session for forge work

The contributor analog to the `/prime <role>` skill that forge stamps into projects. Reads everything a fresh session needs to pick up forge framework development without prompting from the human.

## Invocation

```
/forge:prime
```

No arguments. Run from inside the forge repo (`~/Work/forge` or wherever cloned).

## What this command does

Run these steps in order. The agent reading this command performs each step itself; this is a structured prompt, not auto-executed automation.

### 1. Verify location

```bash
test -f .claude-plugin/plugin.json || { echo "not in forge repo"; exit 1; }
```

If not in forge, stop and tell the user `cd ~/Work/forge` first.

### 2. Load core context

Read these in order (cite them by path when summarizing):

```
README.md                   Status + roadmap + scope boundaries
CONTRIBUTING.md             Conventions: commits, versioning, releases, method-vs-content
docs/METHOD.md              The principles forge stamps into projects
docs/METHODOLOGY.md         The bundle work next on the roadmap
docs/SESSIONS.md            Ephemeral-by-default lifecycle
docs/USAGE.md               Day-to-day ops of stamped projects (so you understand what forge produces)
docs/ROLES.md               Role pattern stamped into projects
docs/ADAPTERS.md            Adapter contract; how adapters compose into skills
docs/BOOTSTRAP.md           First-time setup walkthrough for stamped projects
```

### 3. Pull live state

```bash
# Current version
jq -r .version .claude-plugin/plugin.json

# Recent commits (what landed in the last few sessions)
git log --oneline -15

# Releases cut so far
gh release list --limit 5

# Working tree state (anything mid-flight?)
git status -s

# Branches (any feature branches in flight?)
git branch -v
```

### 4. Inventory shipped capabilities

Walk these dirs and note what's actually in them:

```bash
ls adapters/tracker/        # which trackers ship
ls adapters/scm/            # which SCMs
ls adapters/chat/           # which chats
ls adapters/ci/             # which CI adapters (probably empty until v0.2)
ls templates/wiki/roles/    # default roles + custom template
ls templates/wiki/_snippets # session bootstrap snippets
ls commands/                # plugin slash commands available
```

### 5. Surface the roadmap

From `README.md` "Roadmap" section, list (in order):

1. Methodology bundles (scrum, kanban already implicit, rfc-first, formal-methods/V-model with sub-variants)
2. CI adapters (github-actions, gitlab-ci)
3. `/forge:new` wizard finalization (deterministic flow)

From the same file, list explicit "Out of scope" items so the session doesn't propose work on them:
- Tracker: asana
- SCM: bitbucket
- Chat: teams
- CI: circleci, jenkins
- Notion / ClickUp / Monday.com as trackers

And "possible later" items (no commitment):
- Chat: discord
- GitHub Projects v2

### 6. Emit calibration summary

After steps 1-5, the session should be able to state, in 6-10 lines:

```
## forge contributor — primed

Repo:        ~/Work/forge (github.com/ktoulgaridis/forge)
Version:     vX.Y.Z (next bump: <patch|minor> if today's work ships a capability)
HEAD:        <sha> <subject>
Releases:    v0.1.0, v0.1.1, ...
Working tree: <clean | dirty>
In flight:   <feature branches if any, else "none">

Shipped (v0.1.x):
- Adapters: tracker (gitlab, github, jira-single, jira-multi, linear), scm (github, gitlab), chat (slack)
- Method docs: METHOD, ROLES, SESSIONS, USAGE, ADAPTERS, BOOTSTRAP, METHODOLOGY
- Templates: wiki structure, 6 roles + custom, prime/dispatch/wiki skills, new-session snippets

Roadmap (next):
1. Scrum methodology bundle  ← suggested first
2. RFC-first methodology bundle
3. Formal-methods / V-model bundle (must-have for regulated)
4. Formal-methods sub-variants (IEC 62304, DO-178C, ISO 26262)
5. CI adapters (github-actions, gitlab-ci) — interleavable
6. /forge:new wizard finalization (after bundles)

Out of scope: asana, bitbucket, teams, circleci, jenkins
Possible later: discord, GitHub Projects v2

Conventions (from CONTRIBUTING.md):
- Describe every change (what/where/why)
- Lowercase imperative commit subjects; body explains why
- plugin.json version + git tag + GitHub release stay aligned for capability changes
- Method changes vs content changes — both careful, method changes affect every stamped project

Ready. What's today's goal?
```

### 7. Wait for the user's direction

After the summary, ask the user what to work on. Default suggestion if no direction given: take the next roadmap item that isn't blocked.

## What this skill does NOT do

- Implement anything — that's the user's go-ahead
- Touch the working tree without explicit instruction
- Make architectural decisions about the framework alone — those go through the user (forge contributor = you, the human)

## Implementation note

This skill body is meant to be FOLLOWED by the agent reading it, not auto-executed. Claude Code reads the file when `/forge:prime` is invoked, and the agent performs the steps via Read, Bash, etc.

The pattern mirrors the `/prime <role>` skill that forge stamps into projects. forge eating its own dog food: contributor sessions calibrate the same way agent sessions do.

## Why this exists

Without `/forge:prime`, every fresh session needed a manually-pasted bootstrap message to ground itself. That works but is brittle (humans forget to paste; pasted text drifts as the repo evolves). Making it a skill means:

- One place to update when conventions change (this file)
- Agent reads always-current state instead of stale paste text
- The act of priming itself is observable / debuggable

Same reason stamped projects have `/prime <role>` instead of "paste this onboarding doc."
