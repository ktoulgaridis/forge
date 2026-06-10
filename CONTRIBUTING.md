# Contributing to forge

Notes for anyone picking up **forge generator** work in a fresh Claude Code session. This is about improving the *shared generator* — the OSS tool everyone uses. It is **not** about an org tailoring its own package.

## Generator vs. package — who does what

forge is a generator that emits org-owned packages (see [`docs/GENERATOR.md`](docs/GENERATOR.md) and the [README lifecycle](README.md#lifecycle-generate-distribute-re-generate)). There are two roles, and only one of them contributes here:

| You are… | What you do | Where it lands |
|---|---|---|
| **An upstream contributor** | Improve the shared generator — new adapter, new operating-model facet/preset, method refinement, methodology bundle, better runtime templates, better emitter | **This repo**, via PR / ADR |
| **An org consuming forge** | Run `/forge:emit` to generate your package; re-run the generator to upgrade | Your **own** `acme-forge` repo — *not here*. You don't fork forge and you don't send your package upstream. |

The shift from v1: orgs used to be told to *fork and vendor* forge. **They don't anymore.** They run the generator and own its output. So this file is just for generator contributors. Org operators don't contribute their package back; they re-run the public generator to upgrade.

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

1. **`/forge:emit`** — the generator entry point (interview → emit org-owned plugin → validate). Start with a thin vertical slice. *The most load-bearing piece.*
2. **Org-brain templates** — org-wiki schema + operating-model chapter + `learnings` capture contract + reference `ship-ticket.js` workflow.
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

Today: manual. forge has no test suite at v0.1.

Next: per `docs/ADAPTERS.md` "Adapter doctor self-tests", each adapter should ship a `_test/` dir with sample config + expected rendered skill files. CI-ready format. Land this when the second methodology bundle ships (the renderer needs to be solid by then).

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

forge is opinionated, working, **not done**. v0.1.x is "method codified, basic adapters, manual wizard." v0.2.0 will be "methodology bundles + first deterministic wizard." v1.0 is far off — when forge has been used to stamp 5+ different engagements with different toolchains and the patterns have stabilized.

Don't pretend we're closer to v1.0 than we are. Honest status in README is the signal.

## See also

- `README.md` — overview + roadmap + scope
- `docs/METHOD.md` — the principles
- `docs/METHODOLOGY.md` — the bundle work that's next
- `examples/socwave.md` — the reference engagement that informs forge
