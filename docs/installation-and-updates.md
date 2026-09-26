# Installing, using, and updating PepperSkills

Documentation snapshot: 26 September 2026. Canonical sources live in
`plugins/<name>/skills/<name>/`. [Русская версия](installation-and-updates.ru.md).

## What you install

| Item | Contents | Use |
| --- | --- | --- |
| Skill | `SKILL.md`, references, scripts, assets | An agent discovers the directory and loads instructions |
| Plugin | Skills, manifest, optional MCP/hooks/commands | Installed through the client |
| Chat adapter | Standalone text | Pasted into a conversation or instruction field |
| Marketplace | Catalogue of plugin locations | Discovery and distribution |

Portable instructions do not guarantee Python, a browser, network, or permissions
in every environment. Renaming a directory does not change its package format.

## Installation models

| Model | Best for | Update owner |
| --- | --- | --- |
| Shared directory and symlinks | Several local agents share one source | Source checkout owner |
| Skills manager | CLI discovery, installation, updates | Manager; do not edit its managed copy |
| Project-local | Skills delivered with a team project | Project Git or pinned bootstrap |
| Clone and direct link | Immediate testing of skill development | Skill author |
| Plugin / marketplace | Metadata and integrations with skills | Client/plugin publisher |
| ZIP / account / organization | Claude Chat, Cowork, managed delivery | Upload or product sync |
| Chat prompt | One-off use without a skill loader | User pastes updated text |
| API / server runtime | Automation beyond the desktop | Runtime deployment pipeline |

These are delivery models of one methodology. Project/global scope is another
axis. CLI and Desktop may share a package; a local link does not deliver it to a
cloud or server runtime.

## Shared directory and symlinks

Vercel Skills CLI offers copy or symlink installation and selected agents with
project/global scope. `skillsync` uses a shared `~/.agents/skills/` registry and
agent links. Both are optional third-party tools, not PepperSkills dependencies.

For a hand-managed installation the shared folder can be a link into the checkout:
`~/.claude/skills/<name> → ~/.agents/skills/<name> → clone/plugins/<name>/skills/<name>`.
A manager may instead keep a real managed copy there; do not mix ownership models
for the same skill name or link entire agent configuration/cache directories.

| Client | Documented skill directories | Notes |
| --- | --- | --- |
| Codex | `.agents/skills/`, `~/.agents/skills/` | Individual skill directory links supported |
| Claude Code | `.claude/skills/`, `~/.claude/skills/` | Individual skill directory links supported |
| Gemini CLI | `.gemini/skills/`, `~/.gemini/skills/`; `.agents/skills/`, `~/.agents/skills/` aliases | Shared directory alias documented |

Check the documentation for other clients and your installed version. Manager
catalogues may still list `~/.codex/skills`; do not create both locations automatically.

### macOS / Linux: existing checkout

Adjust the checkout path and product name. Omit the second helper invocation if
you do not use Claude Code. Both Bash and Zsh can run this example:

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.claude/skills/$pepper_name" "$HOME/.agents/skills/$pepper_name"
)
```

The subshell preserves your shell variables and options. Helpers reject ordinary
files/directories and unrelated links; an existing chain resolving to the canonical
source is valid. Recognized legacy PepperSkills links can be migrated safely.

Before updating, inspect the link with `readlink` and run `git status --short` in
the checkout. Use `git pull --ff-only` only for a clean checkout following a branch.
For pinned installations and rollback use a separate installation checkout at a
tag/commit. Verify activation in a fresh session. When uninstalling, check the path
is a symlink, disconnect dependent agent links first, then remove only your link;
keep the source while another installation uses it.

### Windows and WSL

Native Windows uses profile directories. Symlinks may require Developer Mode or
elevation; use a supported copy installer or native plugin workflow if unavailable.
WSL and native Windows have different home directories and runtimes: install in
the environment where the agent actually runs.

## Skills CLI

From the checkout, `npx skills add ./plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer --list`
discovers skills. Removing `--list` and adding `-g -a codex -a claude-code` installs
for those agents globally. `npx` may download the CLI. For remote installation use
a published Git source; local uncommitted changes are not available remotely.

`npx skills list`, `npx skills update`, and `npx skills remove` manage installations.
Pin the CLI version and source in automation. A local-path install is not a promise
of a live link: inspect where the manager stores its canonical copy.

## Project-local installation

Codex uses `<project>/.agents/skills/<name>`; Claude Code uses
`<project>/.claude/skills/<name>`. Commit actual files or supply a bootstrap pinned
to a source revision. Personal absolute symlinks are not reproducible for a team.
Avoid duplicate standalone/plugin installations unless you intend to manage two
entry points; matching skill names are not merged by Codex.

## Plugins and marketplaces

The repository includes `.agents/plugins/marketplace.json`,
`.claude-plugin/marketplace.json`, and `.cursor-plugin/marketplace.json`; all point
to `plugins/<name>`. Files in Git do not establish publication or client acceptance.

**OpenAI:** portable `plugin.json`, `.codex-plugin` compatibility, local/repository
marketplaces and a public directory. Documentation describes
`codex plugin marketplace add ./local-marketplace-root` and Desktop installation
and testing. Availability depends on your environment.

**Claude:** a plugin bundles skills and other components; the marketplace is a
separate catalogue. Invocation may use `/plugin-name:skill-name`. Update and disable
through the client.

**Cursor:** use its manifest and marketplace or actual supported local plugin files.
A symlink from `~/.cursor/plugins/local` to a plugin outside that directory is skipped.
Standalone-skill symlink practices do not apply automatically to whole plugins.

Client caches are managed copies. Edit the source checkout and deliver an update;
do not replace or edit the entire plugin cache.

## Claude Chat, Cowork, and ZIP files

Custom skills use a ZIP with one top-level `<name>/` directory containing `SKILL.md`
and resources. Upload the skill package, not the whole PepperSkills repository.
Standalone archives are `<name>.zip`; plugin packages are `<name>.plugin.zip`.
Local `~/.claude/skills` and account/Cowork uploads are separate installation scopes.
Enable the skill on the surface you will use, then test invocation, update, and disable.
For scripted skills, check that code execution is enabled in that environment.

Root `.skill` files are frozen previous builds from repository revision
`v1.4.1-1-g4128fe6` (commit `4128fe6`); they are never rebuilt and do not represent the
current plugin versions. New builds go to `dist/<name>/<version>/`. Replacement ZIP
upload and publication are release gates; use an accepted published package when
available. Old releases and tags remain available throughout the transition.

## Chat adapters

Use generated files under `plugins/<name>/adapters/chat/`:

| Product | Files |
| --- | --- |
| Prompt Engineer | `chat-prompt.md` |
| Creative Mode | `system-prompt.md`, `custom-instructions.md` |
| RU Web Compliance | `system-prompt.md`, `custom-instructions.md`, `manual-checklist.md` |

Paste the appropriate text into a supported instruction field or a conversation;
respect the field's size limit. A user message does not become an API system message.
Compliance manual mode requires evidence supplied in the conversation and the manual
checklist; it does not perform the full skill's browser collection.

## Moving existing PepperSkills links

Repository updates do not rewrite your installed links. Phase A retains old paths;
create new links to canonical sources. Removal is a separate Phase B after verified
ZIP uploads, replacement packages for all products, and a transition release warning.

| Old path | Canonical path |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `pepper-prompt-engineer/chat-prompt.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |

For a hand-managed shared skill (change product and checkout as needed):

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
)
```

Inspect with `readlink` and invoke in a fresh session. The former
`anthropic/INSTALL.md` holds a temporary pointer to this guide, excluded from new
ZIPs. For chat aliases or prompt files use the helper with the matching path type:

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
"$pepper_repo/scripts/link-path.sh" chat pepper-creative-mode \
  "$HOME/.local/share/pepper-creative-mode" \
  "$pepper_repo/plugins/pepper-creative-mode/adapters/chat"
"$pepper_repo/scripts/link-path.sh" file pepper-prompt-engineer \
  "$HOME/.local/share/pepper-prompt-engineer-chat.md" \
  "$pepper_repo/plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md"
)
```

Ordinary directories and unrelated links are refused, not overwritten. Repeat for
other product links explicitly; your user installations are never changed automatically.

## Troubleshooting

- **No activation:** check the installed `SKILL.md` description and enabled state,
  then explicitly request the skill by name in a fresh session. Prompt Engineer
  activates for prompt construction, not ordinary task execution.
- **Unexpected activation:** report an example in an issue. Creative Mode should
  skip math, fact checks, debugging, and other tasks with a single correct answer.
- **Only SKILL.md appears, or resources are missing:** install the complete skill
  folder/ZIP including references, examples, scripts and evals where present.
  Do not upload an isolated `SKILL.md`. Match the folder name to its `name` field
  (lowercase letters, digits and hyphens; at most 64 characters); do not use colons
  or spaces. Check reserved-name restrictions in the target client's specification.
- **Creative Mode has no seed or remains biased:** verify complete activation and
  the package contents. Check temperature (zero/fixed seed reduces variability),
  independent trials in fresh sessions, and the model's arithmetic/reasoning ability.
  A sequence of flips in one conversation is not independent. There is no universal
  guarantee of improvement, particularly for an already fair binary baseline; consult
  the installed `references/when-not-to-use.md` for the QwQ-32B caveat and mixed tasks.
- **Prompt Engineer output too short/long or incomplete:** use the validator and
  eval runner described in its installed `scripts/README.md` to locate missing or
  overlong CRAFT+ blocks. Request JSON explicitly (`output json`, `формат json`,
  or `--json`); Markdown is the default.
- **Compliance browser/PDF unavailable:** Python 3.10+ is required for scripts;
  Playwright and Chromium are optional separate installations described in the
  installed `scripts/README.md`. Without the browser, collection is degraded and
  browser-dependent checks must remain UNKNOWN.

## References

- [Agent Skills specification](https://agentskills.io/specification)
- [Agent Plugins specification](https://agent-plugins.org/)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)
- [OpenAI plugins and marketplaces](https://developers.openai.com/plugins/build/plugins)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude plugins](https://code.claude.com/docs/en/plugins), [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude custom skills ZIP guidance](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Gemini CLI skills](https://geminicli.com/docs/cli/using-agent-skills/)
- [Cursor plugins](https://prod.cursor.com/docs/plugins)
- [Vercel Skills CLI](https://github.com/vercel-labs/skills)
- [skillsync](https://github.com/Akemid/skillsync), [Windows](https://github.com/Akemid/skillsync#windows-powershell)
