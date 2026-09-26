# PepperSkills

A library of portable skills and Agent Plugins. Plugins use client installation;
standalone skills can be linked from a repository clone.

## Skills

| Skill | Description | Folder |
|-------|-------------|--------|
| [`pepper-creative-mode`](./plugins/pepper-creative-mode/) | Distribution-faithful sampling and diverse generation via self-seeded randomness. | [`plugins/pepper-creative-mode/`](./plugins/pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./plugins/pepper-prompt-engineer/) | CRAFT+ prompt engineer: turns task descriptions into production-ready, target-model-specific prompts. | [`plugins/pepper-prompt-engineer/`](./plugins/pepper-prompt-engineer/) |
| [`pepper-ru-web-compliance`](./plugins/pepper-ru-web-compliance/) | Audits a website against Russian legal requirements: a note for the lawyer and a remediation plan for a developer agent. | [`plugins/pepper-ru-web-compliance/`](./plugins/pepper-ru-web-compliance/) |

## Install

See the [installation guide](./docs/installation-and-updates.md) for supported
clients, marketplace setup, shared skill directories, and chat prompts.

| Surface | Distribution |
| --- | --- |
| Codex, Claude Code | Plugin marketplace or standalone skill directory |
| Claude Chat and Cowork | Skill ZIP upload, after client acceptance |
| Cursor | Cursor marketplace or supported local plugin directory |
| Chat APIs and other prompt fields | Generated chat adapter |

The Russian [repository migration report](./docs/history/repository-structure-2026-09-26.ru.md)
documents the staged cleanup.

## Transition paths

| Old path | Canonical path |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `pepper-prompt-engineer/chat-prompt.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |

Root `.skill` files are frozen previous builds from repository revision
`v1.4.1-1-g4128fe6` (commit `4128fe6`). They are not rebuilt and do not represent
current plugin versions; new archives are built in `dist/<name>/<version>/`.

## Layout

Every plugin is a self-contained folder:

```
plugins/<plugin-name>/
├── plugin.json
├── skills/<plugin-name>/SKILL.md
├── adapters/chat/
├── README.md
├── README.ru.md
└── CHANGELOG.md
```

## Language versions

- English — this file
- Русский — [`README.ru.md`](./README.ru.md)

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). Security issues: [`SECURITY.md`](./SECURITY.md).
Conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

## License

[MIT](./LICENSE) © ITSalt.
