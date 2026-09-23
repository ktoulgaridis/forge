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
`project_key` is an OPTIONAL default board from `.forge.org.yaml` — my-work and the
swarm-ready gate span every board you can see, and single-ticket lookups derive their
board from the ticket KEY PREFIX at runtime. Verbs validated against `acli` v1.3.19.

### `TRACKER_PRIME_SNIPPET`

```bash
# My in-flight work across every board I can see (CSV reads back without ADF
# noise). No project filter: an engineer's work spans boards, and the assignee
# filter already scopes it to me.
acli jira workitem search \
  --jql "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC" \
  --fields key,status,summary,project --csv
#   (Optionally narrow to a default board with `project = {{tracker.config.project_key}} AND …`
#    — but that is an OPTIONAL scope, not the default. My-work spans all my boards.)

# A specific ticket (if a key was passed): its board is derived from the
# key prefix at runtime (ABC-123 → project ABC), so any board works with no
# config value. Jira keys are globally unique, so `view` resolves it.
acli jira workitem view <key> --fields summary,status,labels,project
```

Surface results at T1 (key, summary, status); pull full bodies only when a step needs them.

### `TRACKER_VIEW_ISSUE_SNIPPET`

```bash
# Load the ticket. Read summary + status first; pull the full body only when a
# decision needs it. Read labels from this plain view, never from --json: `view
# --json` reports labels (and parent) as null even when they are set.
acli jira workitem view <key> --fields summary,status,labels
```

### `TRACKER_COMMENT_LIST_SNIPPET`

```bash
# Read the ticket's comments — `view` (plain or --json) does not include them.
# Decisions, refinements, and PR/RESULT lines live here.
acli jira workitem comment list --key <key>
```

### `TRACKER_COMMENT_SNIPPET`

```bash
# Persist an update as a comment. The verb is `comment create` (not `comment add`);
# body inline with --body, or from a file with --body-file.
acli jira workitem comment create --key <key> --body "<update>"
acli jira workitem comment create --key <key> --body-file ./update.md
```

### `TRACKER_CREATE_TASK_SNIPPET`

```bash
# Create a child task under a story. Discover the child type at runtime — boards
# differ per org, so don't assume an issue-type name. Inspect a sibling first:
acli jira workitem view <a-sibling-child-of-the-story> --fields issuetype --json
#   → read the issuetype name from the JSON and use it verbatim as <child-type>.

# A child lives on its parent story's board: derive the project from the parent's
# key prefix (ABC-123 → ABC), so this works on whichever board the story is on.
PROJECT="${STORY_KEY%%-*}"   # key prefix before the first '-' is the project key
acli jira workitem create \
  --project "$PROJECT" \
  --type "<child-type>" \
  --parent "$STORY_KEY" \
  --summary "<repo>: <concern>" \
  --description "<acceptance criteria + test expectations + constraints + deps>"

# No sibling to inspect? Attempt the create and, on a type error, retry with the
# --type the error suggests.
```

### `TRACKER_BACKLOG_SNIPPET`

```bash
# Swarm-ready work across every board I can see: the {{VERB_REFINE}}→{{VERB_EXECUTE}}
# gate is the board-agnostic `agent-ready` label, not a board status, so no project
# filter. Each result's key prefix tells you its board. (Labels and parent are read
# reliably through search --csv, never through view --json.)
acli jira workitem search \
  --jql "labels = agent-ready AND statusCategory != Done" \
  --fields key,status,summary,project --csv
#   (Optionally narrow to one board with `project = {{tracker.config.project_key}} AND …`.)
```

When originating a backlog tree (epics + their stories), don't assume issue-type names
exist by `Epic`/`Story` — discover the board's hierarchy first (inspect an existing
top-level item and a story under it with `acli jira workitem view <key> --fields
issuetype --json`), then `acli jira workitem create` the top-breakdown type, and create
stories under it with `--parent <epic-key>`. Stories are created in OUTLINE form (need +
repos + acceptance-test sketch) and become agent-ready later via refine — do NOT label
them agent-ready at creation. The human owns the backlog.

### `TRACKER_GATE_SNIPPET`

```bash
# The {{VERB_REFINE}}→{{VERB_EXECUTE}} gate is a board-agnostic label, not a board
# status. Every Jira project supports labels with no admin setup, so this works on any
# team's board and leaves its workflow states untouched.
#
# The harness owns a small label namespace:
#   agent-ready    — {{VERB_REFINE}}'s gate passed (problem refined + acceptance/validation test defined); required before {{VERB_EXECUTE}}.
#   agent-blocked  — an agent surfaced a decision that needs the engineer.

# Read the gate (does this ticket carry the label?):
acli jira workitem view <key> --fields summary,status,labels

# Apply the gate label (acli merges into existing labels):
acli jira workitem edit --key <key> --labels "agent-ready"
# Clear it:
acli jira workitem edit --key <key> --remove-labels "agent-ready"
```

```bash
# A team may also mirror the gate to one of its real statuses. If the wiki's operating
# model names that mapping (e.g. "agent-ready ⇒ status 'Ready for Dev'"), honor it.
# acli takes the target status name directly — no separate get-transitions step.
acli jira workitem transition --key <key> --status "<TargetStatus>"
```

The LABEL is canonical and board-agnostic; the status mirror is optional polish.

### `TRACKER_READONLY_COMMANDS`

The commands a read-only role (reviewer, gate) may run — everything else is denied.
One `bash` permission pattern per line.

```text
acli jira workitem view *
acli jira workitem search *
acli jira workitem comment list *
```

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
- Add `--json` on `view` only to parse fields such as issuetype. **Never read labels or
  parent through `view --json`** — it reports them as null even when set; read them
  from the plain `view` or through `search --jql … --csv`.
- **Board-from-key (multi-board).** My-work and backlog searches span every board the
  user can see (scoped by `assignee`/label, not `project`). A single-ticket lookup and
  child-task creation DERIVE their board/project from the ticket KEY PREFIX
  (`ABC-123` → `ABC`) at runtime, since Jira keys are globally unique. `project_key`
  in config is an OPTIONAL default to narrow a query, never a hard filter on my-work.
