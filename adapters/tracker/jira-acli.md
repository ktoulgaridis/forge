---
type: jira-acli
name: jira-acli
description: Jira Cloud driven through Atlassian's official `acli` CLI (no MCP). Streams as labels within one project; auth lives in acli's own context.
required_clis:
  - name: acli
    test: "acli jira auth status"
    install_hint:
      macos: "brew tap atlassian/homebrew-acli && brew install acli"
      linux: "https://developer.atlassian.com/cloud/acli/guides/install-acli/"
optional_mcp_servers: []
config_schema:
  project_key: { type: string, required: true, example: "TEAM" }
  base_url: { type: string, required: true, example: "https://your-team.atlassian.net" }
---

# Adapter: jira-acli

Jira via Atlassian's official **`acli`** CLI (`acli jira workitem …`), not the MCP and
not the third-party `jira` CLI. Use this when the org drives Jira through `acli` and
prefers a CLI auth context over an MCP connection. `acli` authenticates itself (`acli
jira auth login`); there is **no `cloud_id`** to configure here — `acli` resolves the
site from its own auth context. Coordination and traceability flow through Jira; this
adapter supplies the snippets the org-plugin skills inline.

## Skill snippets

These map to the `{{TRACKER_*_SNIPPET}}` placeholders in `templates/org-plugin/`.
`project_key` is substituted from `.forge.org.yaml`. Verbs validated against `acli`
v1.3.19.

### `TRACKER_PRIME_SNIPPET`

```bash
# My in-flight work (CSV so the agent can read it back without ADF noise):
acli jira workitem search \
  --jql "project = {{tracker.config.project_key}} AND assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC" \
  --fields key,status,summary --csv

# A specific ticket (if a key was passed):
acli jira workitem view <key> --fields summary,status,labels
```

Surface results at T1 (key, summary, status); pull full bodies only when a step needs them.

### `TRACKER_VIEW_ISSUE_SNIPPET`

```bash
# Load the ticket. Read summary + status first; promote to the full body only when a
# decision requires it. Add --json when you need to parse fields programmatically.
acli jira workitem view <key> --fields summary,status,labels
acli jira workitem view <key> --fields summary,status,labels --json
```

### `TRACKER_COMMENT_LIST_SNIPPET`

```bash
# Read the ticket's COMMENTS. `view` and `--json` do NOT include comments — they
# must be fetched separately. Decisions, refinements, and PR/VERDICT lines live here.
acli jira workitem comment list --key <key>
```

### `TRACKER_COMMENT_SNIPPET`

```bash
# Persist an update to the ticket as a comment. NOTE: the verb is `comment create`
# (NOT `comment add`). Body inline with --body, or from a file with --body-file:
acli jira workitem comment create --key <key> --body "<update>"
acli jira workitem comment create --key <key> --body-file ./update.md
```

### `TRACKER_CREATE_TASK_SNIPPET`

```bash
# Create a child task under a story. DISCOVER the child type at runtime — boards differ
# per org, so do NOT assume an issue-type name. First inspect a sibling to learn what
# type children use under a story:
acli jira workitem view <a-sibling-child-of-the-story> --fields issuetype --json
#   → read the issuetype name from the JSON and use it verbatim as <child-type>.

acli jira workitem create \
  --project {{tracker.config.project_key}} \
  --type "<child-type>" \
  --parent <story-key> \
  --summary "<repo>: <concern>" \
  --description "<acceptance criteria + test expectations + constraints + deps>"

# If the board has no sibling to inspect, attempt the create and, on a type error,
# retry with a corrected --type from the error's hint. Discover, do not assume.
```

### `TRACKER_BACKLOG_SNIPPET`

```bash
# Find swarm-ready work: the refine→execute gate is carried by the board-agnostic
# `agent-ready` LABEL (see TRACKER_GATE_SNIPPET), not a board-specific status.
acli jira workitem search \
  --jql "project = {{tracker.config.project_key}} AND labels = agent-ready AND statusCategory != Done" \
  --fields key,status,summary --csv
```

When ORIGINATING a backlog tree (epics + their stories), do NOT assume issue-type names
exist by `Epic`/`Story` — DISCOVER the board's hierarchy first (inspect an existing
top-level item and a story under it with `acli jira workitem view <key> --fields
issuetype --json`), then `acli jira workitem create` the top-breakdown type, and create
stories under it with `--parent <epic-key>`. Stories are created in OUTLINE form (need +
repos + acceptance-test sketch) and become agent-ready later via refine — do NOT label
them agent-ready at creation. The human owns the backlog.

### `TRACKER_GATE_SNIPPET`

```bash
# The refine→execute gate is a board-agnostic LABEL, not a board-specific status. Every
# Jira project supports labels with no admin setup, so this works on any team's board
# while leaving their own workflow states untouched.
#
# The harness owns a small label namespace:
#   agent-ready    — refine's gate passed (problem refined + acceptance/validation test defined). REQUIRED before execute.
#   agent-blocked  — an agent surfaced a decision that needs the engineer.

# Read the gate (does this ticket carry the label?):
acli jira workitem view <key> --fields summary,status,labels

# Apply the gate label (acli merges into existing labels):
acli jira workitem edit --key <key> --labels "agent-ready"
# Clear it:
acli jira workitem edit --key <key> --remove-labels "agent-ready"
```

```bash
# A team MAY also mirror the gate to one of their real statuses. If the wiki's operating
# model names that mapping (e.g. "agent-ready ⇒ status 'Ready for Dev'"), honor it.
# acli takes the TARGET status name directly — no separate get-transitions step:
acli jira workitem transition --key <key> --status "<TargetStatus>"
```

The LABEL is canonical and board-agnostic; the status mirror is optional polish.

## Doctor

### `TRACKER_DOCTOR_SNIPPET`

```bash
# 1. acli installed?
command -v acli >/dev/null \
  || echo "install: brew tap atlassian/homebrew-acli && brew install acli"

# 2. authenticated? (exit 0 = authed)
acli jira auth status \
  || acli jira auth login --web
```

## Notes

- `acli` authenticates per-machine via `acli jira auth login --web`; there is no
  `cloud_id` in this adapter's config — `acli` resolves the site from its auth context.
- The verb for comments is `comment create` (not `comment add`); `edit` takes
  `--labels` / `--remove-labels`; `transition` takes the target `--status` name directly.
- `view` (and `view --json`) exclude comments — they return only the configured
  `--fields`. The read verb for comments is `comment list --key <key>`; use it whenever
  you need a ticket's full state (prior decisions/refinements/PR/VERDICT lines).
- Add `--json` on `view` when you need to parse fields (e.g. issuetype discovery);
  prefer `--csv` on `search` for compact, parseable list output.
