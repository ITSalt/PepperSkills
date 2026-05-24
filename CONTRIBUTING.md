# Contributing to PepperSkills

Thanks for your interest in contributing. PepperSkills is a curated library of
portable prompt-engineering skills, each shipped in parallel for **Anthropic
(Claude)** and **OpenAI (GPT)** so the two formats can be compared and adapted.

## Ways to contribute

- **Report a bug** in an existing skill (wrong instruction, broken link, an
  example that fails on current models). Open a [Bug report](https://github.com/ITSalt/PepperSkills/issues/new?template=bug.yml).
- **Propose a new skill** (technique, paper, or pattern worth packaging in both
  formats). Open a [Skill request](https://github.com/ITSalt/PepperSkills/issues/new?template=skill-request.yml)
  *before* opening a PR — we want to align on scope first.
- **Improve an existing skill** (clearer wording, additional example, better
  trigger phrases). Small PRs are welcome without prior discussion.

## Repository scope

A skill belongs here only if it meets all of:

1. **Portable** — implementable on at least both Anthropic and OpenAI stacks
   with a prompt-only change (no provider-specific tooling required).
2. **Reproducible** — the behavior can be observed by running the example
   prompts against current frontier models.
3. **Cited** — backed by a paper, a reproducible benchmark, or a well-defined
   pattern with documented effectiveness boundaries.

Internal / project-specific skills do not belong here.

## Skill folder layout

Every skill is a self-contained folder named `<namespace>-<slug>`:

```
<namespace>-<slug>/
├── README.md         # skill overview (English, canonical)
├── README.ru.md      # skill overview (Russian, optional)
├── anthropic/
│   ├── SKILL.md      # YAML frontmatter + body, follows Anthropic Skill spec
│   ├── examples/     # one .md per worked example
│   └── references/   # one .md per supporting reference doc
└── openai/
    ├── system-prompt.md         # full API / Custom GPT prompt
    └── custom-instructions.md   # compact (<1500 chars) ChatGPT Custom Instructions
```

### Alternative: universal chat prompt

If the skill's mechanism is a single system prompt that behaves identically in
any chat UI (Claude.ai / ChatGPT / Gemini / DeepSeek) without per-vendor
adaptation, you may ship a top-level `chat-prompt.md` at the skill root **in
place of** the `openai/` folder. The Anthropic `anthropic/SKILL.md` variant is
still required so the skill remains installable inside Claude Code. See
`itsalt-prompt-builder/` for a worked example.

When you add a skill, also add a row to the **Skills** table in the root
`README.md` (and `README.ru.md` if you maintain a Russian translation).

## Pull request flow

1. **Fork** the repository — direct pushes to `main` are restricted to
   maintainers.
2. **Branch** off `main` with a descriptive name: `add-<skill-slug>`,
   `fix-<skill-slug>-<short-desc>`, `docs-<short-desc>`.
3. **Commit** in small, focused units. Imperative commit subjects
   (`add ...`, `fix ...`, `docs ...`). One logical change per commit.
4. **Open a PR** against `main`. Fill in the PR template — at minimum, link the
   issue (if any), describe what changed, and confirm you ran the examples
   against a current model and they behave as documented.
5. **Review.** A maintainer will respond within a few days. Changes may be
   requested; please rebase rather than merge `main` into your branch.

## Style

- **Markdown only.** No HTML except where unavoidable.
- **No emojis** in skill instructions, prompts, or documentation — they bias
  model behavior and clutter the source.
- **English is canonical.** Russian translations are welcome but optional and
  must not be the only version of any document.
- **Line length:** soft-wrap at ~80–100 columns in long-form prose; do not
  hard-wrap code blocks or YAML frontmatter.
- **Links** between files must be relative (`./foo.md`, `../bar/baz.md`).

## Reporting security issues

Do not open a public issue for security problems. See [SECURITY.md](./SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](./LICENSE).
