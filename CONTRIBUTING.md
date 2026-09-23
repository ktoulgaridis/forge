# Contributing to forge

Notes for anyone picking up **forge generator** work in a fresh Claude Code session. This is about improving the *shared generator* — the OSS tool everyone uses. It is **not** about an org tailoring its own package.

## Generator vs. package — who does what

forge is a generator that emits org-owned packages (see [`docs/GENERATOR.md`](docs/GENERATOR.md) and the [README lifecycle](README.md#lifecycle-generate-distribute-re-generate)). There are two roles, and only one of them contributes here:

| You are… | What you do | Where it lands |
|---|---|---|
| **An upstream contributor** | Improve the shared generator — new adapter, new operating-model facet/preset, method refinement, methodology bundle, better runtime templates, better emitter | **This repo**, via PR / ADR |
| **An org consuming forge** | Run `/forge:emit` to generate your package; re-run the generator to upgrade | Your **own** `acme-forge` repo — *not here*. You don't fork forge and you don't send your package upstream. |

The shift from v1: orgs used to be told to *fork and vendor* forge. **They don't anymore.** They run the generator and own its output. So this file is just for generator contributors. Org operators don't contribute their package back; they re-run the public generator to upgrade.

## forge stays org-generic

forge never names a specific org — not its name, its repos, its products, or its MCP
servers and their tools — in code, comments, test fixtures, docs, commit messages or PR
descriptions. Org specifics reach an emitted package only through that org's
`.forge.org.yaml`. Use fictional names (`acme-*`) in fixtures and examples, and say
"an environment-switching tool" rather than one server's tool name; the org's `deny:`
names the actual tools.

`tests/test_forbidden_names.py` enforces this. It fails when a tracked file's path or
content contains a name from `FORGE_FORBIDDEN_NAMES` (comma-separated, case-insensitive),
and skips when that variable is unset. The list is never committed — committing it would
itself name the org. CI reads it from the repository variable of the same name. A fork
sets its own list:

```bash
gh variable set FORGE_FORBIDDEN_NAMES -R <owner>/<fork> --body "name1,name2"
FORGE_FORBIDDEN_NAMES="name1,name2" uv run --with pytest pytest tests/test_forbidden_names.py -q
```

## Adding to the graph catalog

- **A rubric** — add `templates/org-plugin/rubrics/<name>.md.template`. Emit discovers
  rubrics by glob; `lib/emit.py` needs no change. A node binds it as `rubric: <name>`.
- **A node skill** — add `templates/node-skills/<name>/SKILL.md.template` (a name that is
  not a verb). It renders only when a graph binds it: as a skill when it is a worker's
  (preloaded) entry node, so it must not set `disable-model-invocation`; otherwise as a
  plain path-read file in the node dir (`nodes/` / opencode `node/`), frontmatter stripped.
- **A worker graph** — declare it under `graphs:` and add its own body template,
  `templates/graphs/<graph>/agent.md.template` (both targets, `{{#TARGET_*}}` sections).
  A worker graph with no body template does not emit.

## Starting a fresh session

```bash
cd ~/Work/forge
claude
```

Then run:

```
/forge:prime
```

That's it. The skill reads the docs, pulls live git state, surfaces the roadmap and scope, and emits a calibration summary. Then asks for today's goal.

This mirrors the `/prime <role>` skill that forge stamps into projects — same pattern, applied to forge itself. The skill body lives at `commands/prime.md` and is the single source of truth for what a fresh session needs to know.

If `/forge:prime` is not available (plugin not installed locally yet), see the manual bootstrap fallback in [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md). For routine work, prefer `/forge:prime`.

## Picking the day's goal

Roadmap items, in implementation order. **The v2 generator reframe ([`docs/GENERATOR.md`](docs/GENERATOR.md)) is now the priority** — its foundation build order supersedes the older v1 list:

1. ~~**`/forge:emit`**~~ — shipped: interview → deterministic emit (two targets, the `graphs:` catalog) → validate.
2. **Org-brain templates** — org-wiki schema + operating-model chapter + `learnings` capture contract with a context-isolated harvest.
3. **Methodology bundles** (composable *with* the operating model): Scrum, RFC-first, then Formal-methods / V-model (largest lift; must-have for regulated industries), then sub-variants (IEC 62304, DO-178C, ISO 26262).
4. **CI adapters: github-actions, gitlab-ci** — can interleave anywhere; smaller than the above.

Explicitly out of scope (don't propose work on these):

- Tracker: asana
- SCM: bitbucket
- Chat: teams
- CI: circleci, jenkins
- Notion / ClickUp / Monday.com as trackers

Possible later (no commitment):

- Chat: discord
- GitHub Projects v2 as tracker variant

## Commit conventions

Subject line: lowercase, imperative, ≤72 chars.

Body: required for any non-trivial change. Explains the why, not the what (the diff shows the what).

Use `cat <<'EOF' ... EOF` heredocs for multi-paragraph messages — the precedent in `git log` shows the shape.

Don't co-author with `Generated with Claude Code` etc. unless explicitly requested.

## Version bumping

Bump `.claude-plugin/plugin.json` version when:
- A new capability ships (new adapter, new role, new skill verb, new doc that's user-facing)
- Behavior of existing capabilities changes meaningfully
- Roadmap milestones complete

**Don't bump for:**
- Typo fixes
- Documentation clarifications without new content
- Internal refactors

When you bump:
```bash
# Edit .claude-plugin/plugin.json — change "version"
git add -A && git commit -m "vX.Y.Z: <one-line summary>"
git push origin main
git tag -a vX.Y.Z -m "vX.Y.Z — <summary>"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z — <title>" --notes "$(cat <<'EOF'
... full release notes ...
EOF
)"
```

Semver loosely:
- Patch (0.x.Y) — small additions, doc improvements with new content, bug fixes
- Minor (0.X.0) — new methodology bundle, new adapter, new docs that change usage
- Major (X.0.0) — only after v1; reserved for breaking changes to the method itself

## Method changes (vs. content changes)

forge ships two kinds of changes:

| Kind | Where it lands | Example |
|---|---|---|
| **Method change** | `docs/`, role templates, skill templates | Adding `lint --consolidate` to wiki skill; codifying ephemeral-by-default; new bundle design |
| **Content change** | adapters, examples, README | New adapter; updated reference engagement |

Method changes need careful treatment:
- They affect every project stamped from forge going forward
- Existing forge-stamped projects need a migration story (`/forge:configure` re-renders affected templates)
- Drafted as MR-ready commits even though forge itself isn't using MR review yet

## Branching

forge is small enough that direct commits to `main` are fine for now. If/when contributors join:
- Switch to MR-driven flow
- Adopt the same MR conventions forge documents for stamped projects
- Add `.github/pull_request_template.md`

## Testing

```bash
uv run --with pytest --with pyyaml pytest tests/ -q
```

CI (`.github/workflows/validate.yml`) runs the same suite: emit golden tests on both targets, the graph-catalog lints, adapter render tests, and behavioural tests for the emitted opencode plugins under node. A change to a template or to `lib/emit.py` lands with a test that fails without it.

## Releases

Cut a GitHub release for every version bump:

```bash
gh release create vX.Y.Z --title "vX.Y.Z — <title>" --notes "..."
```

Release notes should cover:
- What's new (sub-headed by area)
- What changed
- What's deprecated (if any)
- Compatibility notes
- Diff summary

Look at v0.1.1's notes for the shape.

## When something feels wrong

- **Drift between docs and templates** — fix both in one commit; docs reference templates by path
- **Adapter snippet doesn't render correctly** — write a `_test/` fixture; fix the renderer or the snippet
- **Stamped project hits a forge bug** — file an issue (when public) or note in `examples/socwave.md` for now; fix in next minor

## Honest scope

forge is opinionated, working, **not done** (0.x: a deterministic emitter, two targets, the graph catalog; methodology bundles still ahead). v1.0 is far off — when forge has been used to stamp 5+ different engagements with different toolchains and the patterns have stabilized.

Don't pretend we're closer to v1.0 than we are. Honest status in README is the signal.

## See also

- `README.md` — overview + roadmap + scope
- `docs/METHOD.md` — the principles
- `docs/METHODOLOGY.md` — the bundle work that's next
- `examples/socwave.md` — the reference engagement that informs forge
