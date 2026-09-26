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

Each product has one editable skill at `plugins/<name>/skills/<name>/`. The
plugin's `plugin.json` is canonical for product metadata and version. The
`.codex-plugin`, `.claude-plugin`, `.cursor-plugin` files, chat adapters,
OpenAI `submission/listing.json`, plugin LICENSE copies, and transition
`INSTALL.md` pointers, compliance `references/checklist.md`, and the JSON twins
of `rules.yaml` / `signatures.yaml` are generated. Edit their sources or templates, then
regenerate them; do not hand-edit generated files.

The vendored schema in `scripts/schemas/agent-plugin-1.0.0.json` is checked
offline. `submission/listing-extra.json` contains only OpenAI submission fields
that do not exist in the manifest interface. It may not override manifest data.

```bash
python -m pip install -r scripts/requirements-build.txt
python scripts/sync-skill-versions.py --write
python scripts/sync-plugin-manifests.py --write
python scripts/sync-plugin-metadata.py --write
python plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance/scripts/gen_checklist.py --write
python scripts/build-chat-prompts.py --write
bash scripts/build-skills.sh  # or: bash scripts/build-plugins.sh
```

Both wrappers refresh the complete pair (`<name>.zip` and `<name>.plugin.zip`) and
`SHA256SUMS` in `dist/<name>/<version>/`. The low-level `--kind` option is retained
for compatibility, but never reuses a previously built sibling archive. Builders
reject stale generation and only write distribution outputs.

Chat templates use `{{include: path#Heading}}` for selected source sections,
`{{appendix: path}}` for explicitly selected full appendices, and `{{FENCE}}` for
the outer prompt fence. Merely mentioning a reference does not append it. Changes
to chat content must update the reviewed golden differences in
`scripts/fixtures/chat-goldens.json` deliberately.

`plugin.json` owns the shipped version; `sync-skill-versions.py` updates only
`metadata.version` in the corresponding `SKILL.md` frontmatter. Current product
versions are 2.0.0 for Creative Mode and Compliance and 2.5.0 for Prompt
Engineer. Future release tags use `<name>-v<version>`; existing historical tags
remain unchanged.

The root skill paths are transition links for Phase A. Do not remove them or
repoint user installations automatically. Removing legacy paths is a separate
Phase B change after client ZIP acceptance, publication of replacement packages
for all products, and a transition release. See the [installation guide](docs/installation-and-updates.md)
and [migration report](docs/history/repository-structure-2026-09-26.ru.md).

Full local check (network calls are blocked and recorded):

```bash
python -m pip install -r scripts/requirements-build.txt
bash scripts/check.sh
```

Live browser and PDF checks are separate and require Chromium, as documented
in the compliance plugin's submission/README.md. Filesystem symlink tests do
not substitute for installation/update/disable acceptance in actual clients.
