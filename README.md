# PepperSkills

A library of portable prompt-engineering skills. Each skill ships in two
ecosystems side-by-side — **Anthropic (Claude)** and **OpenAI (GPT)** — so the
two formats can be compared and adapted.

## Skills

| Skill | Description | Folder |
|-------|-------------|--------|
| [`pepper-creative-mode`](./pepper-creative-mode/) | Distribution-faithful sampling and diverse generation via self-seeded randomness. | [`pepper-creative-mode/`](./pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./pepper-prompt-engineer/) | CRAFT+ prompt engineer: turns task descriptions into production-ready, target-model-specific prompts. | [`pepper-prompt-engineer/`](./pepper-prompt-engineer/) |
| [`pepper-ru-web-compliance`](./pepper-ru-web-compliance/) | Audits a website against Russian legal requirements: a note for the lawyer and a remediation plan for a developer agent. | [`pepper-ru-web-compliance/`](./pepper-ru-web-compliance/) |

## Install

- **Claude Desktop / claude.ai** — download the `.skill` archive for the
  skill you want from the [latest release](https://github.com/ITSalt/PepperSkills/releases/latest)
  and upload it via *Customize → Skills → Add → Upload skill*. Skills that ship
  scripts also need *Settings → Capabilities → Code execution and file creation*
  (on Team and Enterprise an admin enables it in *Organization settings →
  Skills*).
- **Claude Code** — copy the unpacked `<skill>/anthropic/` folder (renamed
  to match `name:` in `SKILL.md`) into `~/.claude/skills/` (personal) or
  `<project>/.claude/skills/` (per-project). Each skill's
  `anthropic/INSTALL.md` walks through both paths.
- **OpenAI / ChatGPT / GPT API** — copy the contents of `openai/system-prompt.md`
  (full) or `openai/custom-instructions.md` (compact, <1500 chars) into the
  corresponding field.

To rebuild the `.skill` archives from source, run `scripts/build-skills.sh`.

## Layout

Every skill group is a self-contained folder:

```
<skill-group>/
├── README.md         # skill overview (English)
├── README.ru.md      # skill overview (Russian)
├── anthropic/        # Claude variant — Anthropic Skill spec
│   ├── SKILL.md      #   YAML frontmatter + body
│   ├── examples/
│   └── references/
└── openai/           # GPT variant — OpenAI prompt format
    ├── system-prompt.md         # full API / Custom GPT prompt
    └── custom-instructions.md   # compact ChatGPT Custom Instructions
```

## Language versions

- English — this file
- Русский — [`README.ru.md`](./README.ru.md)

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). Security issues: [`SECURITY.md`](./SECURITY.md).
Conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

## License

[MIT](./LICENSE) © ITSalt.
