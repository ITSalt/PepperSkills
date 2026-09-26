# PepperSkills

Repository restructuring proposal (Russian): [design and migration map](./docs/repository-structure.ru.md).
The migration has not been applied; existing source paths remain in use.

A library of portable skills and Agent Plugins. Plugins use client installation;
standalone skills can be linked from a repository clone.

## Skills

| Skill | Description | Folder |
|-------|-------------|--------|
| [`pepper-creative-mode`](./plugins/pepper-creative-mode/) | Distribution-faithful sampling and diverse generation via self-seeded randomness. | [`plugins/pepper-creative-mode/`](./plugins/pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./plugins/pepper-prompt-engineer/) | CRAFT+ prompt engineer: turns task descriptions into production-ready, target-model-specific prompts. | [`plugins/pepper-prompt-engineer/`](./plugins/pepper-prompt-engineer/) |
| [`pepper-ru-web-compliance`](./plugins/pepper-ru-web-compliance/) | Audits a website against Russian legal requirements: a note for the lawyer and a remediation plan for a developer agent. | [`plugins/pepper-ru-web-compliance/`](./plugins/pepper-ru-web-compliance/) |

## Install

- **Plugin** — use the marketplace files in `.agents/plugins/`, `.claude-plugin/`,
  or `.cursor-plugin/` and install one directory from `plugins/`.
- **Clone + symlink** — link `plugins/<name>/skills/<name>` into the project or
  user skill directory supported by the agent.
- **Shared registry** — expose the skill under `~/.agents/skills/`; add a
  per-skill link for clients with a different discovery directory. Check each
  client's supported paths before adding links.
- **OpenAI review** — run `scripts/build-plugins.sh` and submit a skills-only
  archive through the OpenAI plugin submission portal.

To rebuild `.skill` archives, run `scripts/build-skills.sh`. To build portable
plugin archives, run `scripts/build-plugins.sh`.

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

Installation and update details: [`docs/installation-and-updates.ru.md`](./docs/installation-and-updates.ru.md).

## License

[MIT](./LICENSE) © ITSalt.
