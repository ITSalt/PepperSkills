# Contributing to PepperSkills

Thanks for your interest in contributing. PepperSkills is a curated library of
portable Agent Plugins. Each plugin has one canonical skill source and small
adapters for clients that expose different capabilities.

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

## Plugin folder layout

Every skill is a self-contained folder named `<namespace>-<slug>`:

```
plugins/<name>/
├── plugin.json
├── skills/<name>/SKILL.md
├── adapters/chat/       # generated or provider-light chat material
├── README.md
├── README.ru.md
└── CHANGELOG.md
```

### Chat adapters

Chat-only material belongs in `adapters/chat/` and is generated from the
canonical skill where possible. It is an adapter for environments without code,
browser or network access; it is not a second editable skill implementation.

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

## Generated plugin artifacts

`plugins/<name>/plugin.json` is canonical metadata. Compatibility adapters in
`.codex-plugin`, `.claude-plugin`, `.cursor-plugin` are generated, not edited.
The vendored schema in `scripts/schemas/agent-plugin-1.0.0.json` comes from
https://agent-plugins.org/schemas/1.0.0/plugin.schema.json (retrieved 2026-09-21).
Builds validate the official schema offline and reject adapter drift.

```bash
uv run --no-project --with jsonschema scripts/sync-plugin-manifests.py
uv run --no-project plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance/scripts/gen_checklist.py
python3 scripts/build-chat-adapters.py
python3 scripts/build-chat-prompt.py
uv run --no-project --with jsonschema bash scripts/build-skills.sh
uv run --no-project --with jsonschema bash scripts/build-plugins.sh
```

Plugin version describes the distribution package. Skill `metadata.version`
describes the skill protocol and may differ: e.g. package 2.0.0 contains
prompt-engineer 2.4.0. Generated chat adapters use current skill sections and
references; changes to them require regeneration before packaging.

Full local release check:

```bash
uv run --no-project --with jsonschema --with pyyaml bash scripts/check.sh
```

Live browser and PDF checks are separate and require Chromium, as documented
in the compliance plugin's submission/README.md. Filesystem symlink tests do
not substitute for installation/update/disable acceptance in actual clients.
