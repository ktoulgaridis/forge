---
description: Bootstrap a new agent-orchestrated project from forge templates. Stamps a wiki repo + roles + skills + adapters configured for the org's tools.
---

# /forge:new — Bootstrap a new project

Create a fresh wiki repo + scaffold for an agent-driven engagement. This is the entry point: one command turns a project codename into a complete orchestration substrate.

## Invocation

```
/forge:new <project-codename>
```

Example: `/forge:new mojave`, `/forge:new acme-platform`.

## What this command does

Run an interactive wizard. Use AskUserQuestion (or sequential prompts) to gather config, then stamp.

### Step 1 — Resolve the wiki destination

Ask:

> "Where does the wiki repo live? Suggest options:
> 1. `github.com/<your-user>/<project>-wiki` (private)
> 2. `gitlab.<org>.com/<group>/<project>-wiki`
> 3. Custom (paste full URL)"

Capture: `wiki_remote_url`, `wiki_host` (github / gitlab / bitbucket).

### Step 2 — Tracker

Ask:

> "Issue tracker?
> 1. GitHub Issues
> 2. GitLab Issues
> 3. Jira (single board)
> 4. Jira (multi-board, mapped to streams)
> 5. Linear
> 6. Asana"

Capture: `tracker.type`. Then per type:

- **github** → confirm same host as wiki, or different
- **gitlab** → confirm host (gitlab.com or self-hosted)
- **jira-***  → ask base URL (`https://<org>.atlassian.net`); for multi-board, ask board keys per stream
- **linear** → ask team ID
- **asana** → ask workspace + project IDs

Read the matching adapter at `adapters/tracker/<type>.md` to understand what other config the adapter needs.

### Step 3 — SCM

Ask:

> "SCM (where the code lives)?
> 1. GitHub
> 2. GitLab
> 3. BitBucket"

Capture: `scm.type`, `scm.org_or_user`.

### Step 4 — Streams

Default to A=backend, B=frontend, C=coordination, D=human. Offer to override:

> "Streams (parallel work tracks)?
> 1. Default (A=backend, B=frontend, C=coordination, D=human)
> 2. Custom"

If custom, prompt for stream IDs + descriptions.

### Step 5 — Methodology

Ask:

> "Methodology (affects ticket templates + sizing units)?
> 1. Scrum (sprints, story points)
> 2. Kanban (continuous flow)
> 3. RFC-first (design doc before tickets)
> 4. Custom (use sensible defaults)"

Capture: `methodology.type` and any relevant settings (sprint length for Scrum; sizing unit).

### Step 6 — Roles

Default to all 6 (orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst). Offer:

> "Roles? Defaults are: orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst.
> Add custom roles? (e.g., release-manager, compliance-officer, security-reviewer)"

Capture: `roles[]`. Custom roles get a stub file from `templates/wiki/roles/_custom.md.template`.

### Step 7 — Optional integrations

Ask:

> "Optional MCP servers / CLIs to wire up:
> - [ ] github MCP server
> - [ ] slack MCP (notifications + handoffs)
> - [ ] sentry MCP (incident-driven tickets)
> - [ ] figma MCP (design-driven UI)
> - [ ] atlassian MCP (richer Jira/Confluence)
> - [ ] custom"

Capture: `integrations[]`.

Match each against `adapters/chat/<x>.md` or `adapters/tracker/<x>.md` for install hints.

### Step 8 — Confirm and stamp

Echo the captured config back and ask "proceed?". On confirm:

#### 8a. Build .forge.config.yaml

Write the full config under `~/Work/<project>/.forge.config.yaml`:

```yaml
forge_version: 0.1.0
project:
  name: <project>
  created: <iso-date>
wiki:
  remote_url: <captured>
  host: <captured>
tracker:
  type: <captured>
  config: { ... }
scm:
  type: <captured>
  config: { ... }
streams: [ ... ]
methodology:
  type: <captured>
roles: [ ... ]
integrations: [ ... ]
```

#### 8b. Create the wiki repo

Use the right CLI:

- `gh repo create <wiki-name> --private` for github
- `glab repo create <wiki-name> --private` for gitlab
- BitBucket: instruct user (no first-class CLI step)

#### 8c. Stamp the templates

Render `templates/wiki/**/*.template` into `~/Work/<project>/` using the **shared
engine** (`lib/render.py` — the same one `/forge:emit` drives):

1. Build a project-tier `bindings` object from `.forge.config.yaml`:
   - `scalars` — `{{PROJECT_NAME}}`, `{{TRACKER_TYPE}}`, `{{SCM_CLI}}`, `{{WIKI_LOCAL_PATH}}`, `{{HUMAN_OWNER}}`, `{{CREATED_DATE}}`, etc.
   - `arrays` — `{{#streams}}…{{/streams}}` from the streams list.
   - `conditionals` — e.g. `{{#integrations.figma}}…{{/integrations.figma}}` from selected integrations.
   - `snippets` — the `{{TRACKER_*_SNIPPET}}` / `{{SCM_*}}` blocks, each pointing at `adapters/<type>/<name>.md` and the relevant snippet label, so the engine inlines them.
2. Call `render_tree(bindings, "templates/wiki", dest, forge_root)` — **no** `leak_check` (project wikis are stamped from forge and may legitimately reference it).

The engine drops the `.template` suffix, asserts no unresolved `{{...}}` survive, and
mirrors the directory structure. Role files with no placeholders pass through verbatim.

#### 8d. Initial commit + push

```bash
cd ~/Work/<project>
git init
git add -A
git commit -m "forge: bootstrap <project-name> from forge v0.1.0"
git remote add origin <wiki_remote_url>
git push -u origin main
```

#### 8e. Run forge:doctor

Verify all required CLIs and MCP servers are available. Print missing ones with install instructions.

#### 8f. Print next steps

```
✓ Wiki repo created: <wiki_remote_url>
✓ Stamped X files
✓ Doctor: gh ✓, jira ✓, slack MCP not installed (optional)

Next steps:
  cd ~/Work/<project>
  claude
  /prime orchestrator

The orchestrator will pull live state from <tracker> and dispatch the first wave of work.
```

## Tools required

- `git`, `gh`, possibly `glab`
- The chosen tracker's CLI if applicable (`jira`, `linear`)
- `jq` for JSON manipulation

## Failure modes

- **Wiki repo already exists** → ask if user wants to clone + populate (instead of create + populate)
- **Tracker auth missing** → tell user to authenticate (`gh auth login`, `jira init`, etc.) and retry
- **Required CLI missing** → print install command from the adapter's `install_hint`; pause and let the user install
- **Permission denied creating repo** → surface the error, suggest target org change

## Idempotency

Re-running `/forge:new <project>` on an existing project should detect `.forge.config.yaml` and offer to:
1. Re-stamp specific files (e.g., re-render skills after a forge upgrade)
2. Reconfigure adapters
3. Add new roles

Don't blow away existing wiki content.
