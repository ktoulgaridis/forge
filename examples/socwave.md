# Example: SocWave engagement

The first engagement built using forge's patterns. Useful as a reference for what a stamped project looks like once it's been used for several themes.

## Project shape

- **Goal:** Port the legacy SocWave SOC-analyst training platform to a cloud-native rebuild on Azure with new features.
- **Wiki:** `gitlab.example.com/socwave/wiki`
- **Code:** `gitlab.example.com/socwave/socwave-platform` (monorepo: Go BFF + React SPA + Helm + Cedar policies)
- **Content:** `gitlab.example.com/socwave/socwave-curriculum` (markdown + YAML, agent-authored)
- **Calendar:** ~10 weeks (8-9 weeks of agent-driven work + parallel streams)

## Adapter config (excerpt)

```yaml
forge_version: 0.1.0
project:
  name: socwave
wiki:
  remote_url: git@gitlab.example.com:socwave/wiki.git
  host: gitlab
tracker:
  type: gitlab
  config:
    host: gitlab.example.com
    project: socwave/socwave-platform
scm:
  type: gitlab
  config:
    host: gitlab.example.com
streams:
  - { id: A, label: backend, description: "Go BFF, infra, content cache, integrations" }
  - { id: B, label: frontend, description: "React SPA + custom admin" }
  - { id: C, label: coordination }
  - { id: D, label: human, description: "Top-of-loop human" }
methodology:
  type: kanban
roles:
  - orchestrator
  - architect
  - implementer
  - reviewer
  - wiki-maintainer
  - migration-analyst
integrations:
  - figma          # for design-driven UI work in T6
```

## What this engagement proves

- **The method scales to a real project** — 16 ADRs, 7 services, 7 themes, 6 roles, 3 skills, 58 wiki files at bootstrap
- **The Karpathy schema absorbs change** — architecture pivoted from Hybrid Payload+Go → Go-only with content-as-git, captured cleanly via ADR supersedure (0001 → 0013, 0011 → 0014)
- **Adapters work end-to-end** — gitlab tracker + gitlab SCM combination is the v0.1 reference; everything in the skills uses `glab` cleanly

## What still needs to be proven

- **Multi-tracker setups** (Jira-multi-board for Stream A + Linear for Stream B) — not exercised by this engagement
- **Slack/chat integrations** — not used in SocWave
- **forge:configure mid-flight** — when SocWave eventually upgrades to forge v0.2+, this will exercise the upgrade path

## What we'd change for v0.2 of forge based on SocWave

(To be filled in as SocWave reveals gaps. Add notes here as we hit them.)

- Refine the prime skill's "live state" block — currently it pulls a lot; consider lazy / role-specific subsets
- The dispatch skill could surface a queue view by default
- Wiki maintainer's lint output format could be more agent-actionable

## Wiki structure (for reference)

```
socwave/wiki/
├── README.md
├── CLAUDE.md
├── ROADMAP.md
├── architecture.md
├── about.md                       (raw source — preserved verbatim)
├── architecture-legacy-plan.md    (raw source — preserved)
├── requirements/
│   └── user-needs.yaml            (raw source — canonical requirements)
├── decisions/                     (16 ADRs)
├── services/                      (7 services: go-bff, spa, content, cedar, sentinel-adapter, nats, guacamole-routing)
├── themes/                        (T1-T7)
├── roles/                         (orchestrator, architect, implementer, reviewer, wiki-maintainer, migration-analyst)
├── legacy/
│   ├── soc-backend-cms.md
│   ├── soc-frontend.md
│   └── cybergate.md
├── cohort-2026/                     (operational context for the active customer cohort)
└── .claude/skills/
    ├── prime/SKILL.md
    ├── dispatch/SKILL.md
    └── wiki/SKILL.md
```

This is exactly what `/forge:new socwave` would stamp (modulo the project-specific content of ADRs, services, themes — those get added as the engagement progresses, not at bootstrap).
