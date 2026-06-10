---
description: Stamp a new agent role into an existing forge-stamped project.
---

# /forge:add-role — Add a custom role

Stamp a new role file from the template. Useful for org-specific roles like `release-manager`, `compliance-officer`, `security-reviewer`, `tech-writer`, `data-analyst`.

## Invocation

```
/forge:add-role <name>
```

Run from inside the project's wiki dir.

## What this command does

1. Read `.forge.config.yaml` — fail if not a forge project
2. Check that `roles/<name>.md` doesn't already exist
3. Copy `templates/wiki/roles/_custom.md.template` → `roles/<name>.md`
4. Substitute placeholders: `{{ROLE_NAME}}`, `{{PROJECT_NAME}}`
5. Open the file for editing — the user fills in mission, owns, boundaries, inputs, output format, tools, handoff
6. Update `roles/README.md` to add the new role to the index
7. Update `.claude/skills/prime/SKILL.md` to recognize the new role name in arg parsing
8. Update `.forge.config.yaml` — append to `roles[]`
9. Open a wiki MR with the changes (don't push directly)

## Conventions

- Role names are kebab-case (`release-manager`, not `releaseManager`)
- One file per role under `roles/<name>.md`
- The template forces the user to think about boundaries — what this role does NOT do is as important as what it does

## When NOT to use this

- For agent variants of existing roles (e.g., "implementer-frontend" vs "implementer-backend") — those are tag/label conventions, not separate roles
- For one-off ad-hoc tasks — those are tickets, not roles
- For external collaborators (humans only) — roles are for agent calibration; humans don't need a role file
