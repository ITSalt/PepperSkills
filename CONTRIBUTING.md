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

### Agent-workflow plugins

Plugins that coordinate agent sessions (planning, dispatch, review, verification) must meet
criteria 2 and 3 above as written. Criterion 1 (portable) is met by a **portable core with
client adapters**:

- **Portable core** — roles, state files, protocol, templates and scripts that use only the Python
  standard library and common CLIs (`git`, `gh`). The core works in any client that can read
  files and run commands, with a prompt-only change.
- **Client adapters** — anything that relies on one client's capabilities (subagent types,
  cross-session messaging, hooks, session start flags, short commands) lives in `agents/`,
  `hooks/`, `commands/` or `adapters/`. The core must not depend on an adapter: without it the
  skill still works, with the owner relaying what the adapter would automate.
- For criterion 3, the documented effectiveness boundaries live in the skill (when to apply the
  pattern and when it is overhead); criterion 2 means its modes can be run on a demo workspace
  against current models.

Project-specific details (repositories, trackers, environments) belong in the user's workspace
configuration, not in the plugin.

## Plugin folder layout

Every skill is a self-contained folder named `<namespace>-<slug>`:

```
plugins/<name>/
├── plugin.json
├── skills/<name>/SKILL.md
├── adapters/chat/       # generated or provider-light chat material
├── agents/ hooks/ commands/  # optional client adapters (agent-workflow plugins)
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

**Merge rule.** Anyone may open a pull request, agents included. Only the
maintainer merges into `main`, after review: `.github/CODEOWNERS` requests the
maintainer's review on every pull request, and branch protection on `main`
requires a pull request and green checks.

## Report a defect from an agent

Agents that hit a defect of a plugin report it instead of patching the plugin in
place. In pepper-orchestrator this is the `report` mode (`orch.py report
--check`, then `--apply --confirmed` after the owner's explicit yes): it collects
the plugin version, Claude Code, OS, Python, shell, the command and the first
lines of its output, replaces every name, path and address of the reporter's
program with placeholders, scans the result for private traces, searches
existing Issues by a fingerprint (plugin, version, first error line) and either
comments on a match or opens an Issue with the "Plugin defect (agent report)"
template and the labels `bug`, `from-agent`, `needs-triage`. Other plugins use
the same template by hand. Security problems go through `SECURITY.md`, never a
public Issue.

## Fix from an agent

A fix comes as a pull request from a fork: a separate developer session works in
the fork (branch from `main`, `bash scripts/check.sh` green, no private traces),
never the orchestrator session of a program. The pull request starts with
`Fixes #N` for the Issue it closes and follows the PR template. The maintainer
reviews and merges.

## Style

- **Markdown only.** No HTML except where unavoidable.
- **No emojis** in skill instructions, prompts, or documentation — they bias
  model behavior and clutter the source.
- **English is canonical.** Russian translations are welcome but optional and
  must not be the only version of any document.
- **Line length:** soft-wrap at ~80–100 columns in long-form prose; do not
  hard-wrap code blocks or YAML frontmatter.
- **Links** between files must be relative (`./foo.md`, `../bar/baz.md`).

## No private traces

This repository is public. Never commit names, addresses, domains or paths of private
projects, and never commit absolute paths of your machine (home directories on macOS,
Linux or Windows): use repository-relative paths, `~/projects/example` placeholders and
reserved example domains (`example.com`, `app.example.com`, RFC 2606). This covers
documentation, test fixtures, logs, commit messages, pull request bodies and built
archives.

`scripts/check-private-traces.py` (part of `scripts/check.sh` and CI) fails on absolute
home-directory paths in every tracked text file and in the text members of tracked
`.skill`/`.zip` archives. Keep your own list of private terms (project names, domains)
in `.private-terms.local` in the repository root, one term per line with `#` comments:
the file is gitignored, and when it exists the same check also fails on those terms, so
the names themselves never enter the public tree.

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

Chat templates declare their label language in a leading `<!-- chat-language: en -->`
or `<!-- chat-language: ru -->` comment followed by a blank line. The marker is not
included in generated output. Templates use `{{include: path#Heading}}` for selected source sections,
`{{appendix: path}}` for explicitly selected full appendices, and `{{FENCE}}` for
the outer prompt fence. Merely mentioning a reference does not append it. Changes
to chat content must update the reviewed golden differences in
`scripts/fixtures/chat-goldens.json` deliberately.

`plugin.json` owns the shipped version; `sync-skill-versions.py` updates only
`metadata.version` in the corresponding `SKILL.md` frontmatter. Current product
versions are 2.0.1 for Creative Mode, 2.3.0 for Compliance, 2.5.1 for Prompt
Engineer and 0.9.0 (public preview) for Orchestrator.
Future release tags use `<name>-v<version>`; existing historical tags
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
