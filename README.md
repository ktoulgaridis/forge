<h1 align="center"><img src="docs/assets/logo.svg" alt="forge" width="480"></h1>

<p align="center"><b>Make your coding agents work the way your organization works.</b></p>

<p align="center">
<a href="https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml"><img src="https://github.com/ktoulgaridis/forge/actions/workflows/validate.yml/badge.svg" alt="validate"></a>
<a href="https://github.com/ktoulgaridis/forge/releases"><img src="https://img.shields.io/github/v/release/ktoulgaridis/forge" alt="release"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license: MIT"></a>
</p>

## What is forge?

Most teams bolt AI coding agents onto their process and hope they behave. forge does it
the other way round. It asks how your organization works: which tools you use, what
process you follow, who approves what, which rules you must never break. Then it
**generates a harness** that makes your agents follow those answers.

The harness is a Claude Code plugin, or an opencode configuration, that **your org
owns**. forge is the mill, not a dependency: nothing in the result points back here.

## What you get

- **One way of working for everyone.** The whole org installs the same plugin and gets
  the same commands: `prime`, `refine`, `execute`, `triage`, `wiki`, `handoff` and more
  (you can rename them).
- **Your process lives in your wiki, not in the plugin.** Agents read it at the start of
  every session, so changing how you work is a wiki edit, not a release.
- **Guardrails that hold.** The builder agent works test-first, and a script, not the
  agent, decides whether its pull request opens: the tests must pass, and any tests it
  wrote must fail without its change. Investigators are read-only. A human always merges.
- **Your tools.** Jira, GitHub, GitLab or Linear for tickets; GitHub or GitLab for code;
  Slack for chat.
- **Upgrades without forks.** When forge improves, re-run it over your config and you get
  the new version with your choices intact.

## Let your agent set it up

Paste this into Claude Code (or any coding agent with a shell):

```text
Set up forge for my organization: https://github.com/ktoulgaridis/forge

1. Clone it and read README.md, commands/emit.md (the procedure you will follow)
   and .forge.org.example.yaml (the config shape). You need git and uv.
2. Follow commands/emit.md: interview me one topic at a time, tell me each
   default, and write our .forge.org.yaml.
3. Emit our package (a Claude Code plugin, unless I ask for opencode) and run
   its validation.
4. Show me what was generated, then tell me how I install it and how my team
   gets it.

Ask me before you push or publish anything.
```

## Or install it yourself

In Claude Code:

```
/plugin marketplace add ktoulgaridis/forge
/plugin install forge@forge
```

Then, in a clone of this repo, run `/forge:emit`. It interviews you and writes your
package. The same engine also runs directly:

```bash
uv run --with pyyaml python lib/emit.py --config .forge.org.yaml --out <dir> \
    [--target claude-code|opencode]
```

## How it works

1. **Generate.** `/forge:emit` interviews your org and writes a standalone, validated
   package.
2. **Distribute.** Publish it internally (a private marketplace, a Git host, or
   vendored). Every team installs the same thing.
3. **Re-generate to upgrade.** Re-run forge over the same `.forge.org.yaml`. No fork to
   maintain, no drift.

Two orgs that answer the interview differently get two different harnesses from the same
generator. That is the point: **nobody forks forge.**

## Supported tools

| Layer | Shipped | Planned | Out of scope |
|---|---|---|---|
| Tracker | github · jira-acli · jira-mcp · jira-multi · jira-single · gitlab · linear | asana | Notion / ClickUp / Monday |
| SCM | github · gitlab | bitbucket | — |
| Chat | slack | teams | discord (a "maybe later") |
| CI | — | github-actions · gitlab-ci | circleci, jenkins |
| Cloud | informational only — forge doesn't provision | — | azure / aws / gcp provisioning |

The adapter contract is in [`docs/ADAPTERS.md`](docs/ADAPTERS.md).

## Learn more

| If you want to know | Read |
|---|---|
| What an emitted package contains, the method, and what ships today | [`docs/REFERENCE.md`](docs/REFERENCE.md) |
| The full design | [`docs/GENERATOR.md`](docs/GENERATOR.md) |
| How agents work together | [`docs/METHOD.md`](docs/METHOD.md) |
| The opencode target and its compatibility | [`docs/notes/opencode-target.md`](docs/notes/opencode-target.md) |
| A complete example config | [`examples/graph-catalog.forge.org.yaml`](examples/graph-catalog.forge.org.yaml) |
| A worked engagement | [`examples/socwave.md`](examples/socwave.md) |

## Status and roadmap

Early and opinionated: it works, and it is incomplete. See the
[releases](https://github.com/ktoulgaridis/forge/releases) for what changed.

Next, in order:

1. **Org-brain templates:** org-wiki schema, operating-model chapter, and the
   `learnings` capture contract.
2. **Methodology bundles:** Scrum, Kanban (default), RFC-first, and formal methods /
   V-model for regulated shops (IEC 62304, DO-178C, ISO 26262).
3. **CI adapters:** github-actions and gitlab-ci.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Improvements to the shared generator land here;
an org tailoring its own package re-runs the generator instead.

## License

MIT, see [LICENSE](LICENSE).
