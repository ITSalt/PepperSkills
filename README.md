# PepperSkills

A library of portable prompt-engineering skills. Each skill ships in two
ecosystems side-by-side — **Anthropic (Claude)** and **OpenAI (GPT)** — so the
two formats can be compared and adapted.

## Skills

| Skill | Description | Folder |
|-------|-------------|--------|
| [`pepper-creative-mode`](./pepper-creative-mode/) | Distribution-faithful sampling and diverse generation via self-seeded randomness. | [`pepper-creative-mode/`](./pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./pepper-prompt-engineer/) | CRAFT+ prompt engineer: turns task descriptions into production-ready, target-model-specific prompts. | [`pepper-prompt-engineer/`](./pepper-prompt-engineer/) |

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
