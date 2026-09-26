# Installing, using, and updating PepperSkills

This guide describes the canonical repository layout: `plugins/<name>/skills/<name>/`.
A skill is a directory of instructions and resources; a plugin is a client-installable
bundle that can contain skills and other integrations. A chat adapter is standalone
text. A marketplace is a catalogue for discovering plugin packages.

## Choose an installation model

| Model | Best for | Update owner |
| --- | --- | --- |
| Shared directory and symlinks | Several local agents share one editable skill | Owner of the source checkout |
| Skills manager | Discovering and updating skills through a CLI | The manager; avoid editing its managed copy |
| Project-local | A team needs skills alongside a project | Project Git or pinned bootstrap |
| Clone and direct link | Skill development with immediate local changes | Skill author |
| Plugin or marketplace | A client-managed package with metadata and integrations | The client/plugin publisher |
| ZIP upload or account/org scope | Claude web, Cowork, or managed distribution | Product upload or sync |
| Chat prompt | One-off use or a client without a skill loader | User pastes the current generated text |
| API/server runtime | Automation outside a local desktop app | Runtime deployment pipeline |

These are delivery models, not separate implementations of the skill. Project/global
scope is another axis. CLI and Desktop may use the same package, while a local symlink
does not copy files into a cloud or server runtime.

## Shared skills directory and symlinks

A common setup keeps one source at `~/.agents/skills/<name>` and links each agent's
skill directory to it. Codex and Gemini CLI document the shared `.agents/skills`
location; Claude Code supports individual skill symlinks. Vercel Skills CLI is a
third-party installer that supports copy or symlink installation, selected agents,
global/project scope, and updates. `skillsync` is another example of a shared registry
with links. These tools are options, not dependencies of PepperSkills.

Example for an existing checkout on macOS/Linux (Bash or Zsh):

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
# Optional Claude Code link:
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.claude/skills/$pepper_name" "$HOME/.agents/skills/$pepper_name"
)
```

The subshell keeps shell options and variables out of the interactive shell. The
checks refuse to overwrite an existing file, directory, or link. To update a
hand-managed checkout, inspect it first and use `git pull --ff-only` only when clean.
For a pinned installation, use a separate checkout at a tag or commit. Verify a fresh
agent session after updating. Remove only the link you created, after checking that it
is a symlink; keep the source checkout if it is used elsewhere.

On Windows, creating symlinks may require Developer Mode or elevation; use a supported
copy installer or client plugin if unavailable. WSL and native Windows have different
home directories and runtimes. Install where the agent actually runs.

## Managers and project-local skills

Vercel Skills CLI can discover and install from a local path or remote source, list,
update, and remove skills. A local-path install should not be assumed to remain a live
link to the checkout; inspect where the manager stores its canonical copy. Pin the CLI
and source in automation. See [Vercel Skills](https://github.com/vercel-labs/skills).

For project-local use, Codex reads `<project>/.agents/skills/<name>` and Claude Code
reads `<project>/.claude/skills/<name>`. Commit the skill files or provide a bootstrap
that pins a source revision. Personal absolute paths are not reproducible for a team.
Avoid installing the same product as both a standalone skill and plugin unless you
intend to manage two entry points and versions.

## Plugins and marketplaces

Plugins package skills with client metadata and may include commands, hooks, or tools.
Marketplaces are catalogues that point to plugins; they are not the plugin itself.
Install and update using the target client's documented plugin workflow. Codex,
Claude Code, and Cursor have different manifests, local development options, caches,
and marketplace behavior, so do not assume a symlink technique for standalone skills
also works for whole plugins. Treat client caches as managed copies: edit the source
checkout and update through the client.

## Claude web, Cowork, and ZIP files

Claude's custom-skill workflow accepts a ZIP whose top-level folder contains
`<name>/SKILL.md` and its resources. A local `~/.claude/skills` directory is not the
same as an account-level or Cowork upload. Complete upload and enablement in the
surface where you intend to use the skill. PepperSkills' `.zip` artifacts are for
standalone skills; `.plugin.zip` artifacts contain the plugin directory.

## Chat adapters

Generated chat text lives in `plugins/<name>/adapters/chat/`. Copy the appropriate
adapter into the product's supported instruction field or use it in a conversation.
A text pasted as a normal user message does not become a system message for an API.
The compliance manual mode depends on evidence supplied in the conversation and does
not perform the browser collection available in the full skill.

## Moving existing PepperSkills links

A repository update does not rewrite links you previously created. During the
transition, old repository paths remain available. The new canonical paths are:

| Old path | Canonical path |
| --- | --- |
| `<name>/anthropic` | `plugins/<name>/skills/<name>` |
| `<name>/openai` | `plugins/<name>/adapters/chat` |
| `pepper-prompt-engineer/chat-prompt.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md` |

To repoint a manually managed shared skill link, change `pepper_name` and the checkout
path. This example updates only an existing symlink whose old or new target matches
the expected PepperSkills paths. It leaves directories and unrecognized links alone:

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
)
```

If you linked the old `anthropic/INSTALL.md`, this guide replaces its installation
instructions. During this transition the old location contains a short pointer to this
documentation. Client acceptance and publication of replacement packages are separate
release checks; local files alone do not prove installation in a target client.

## References

- [Agent Skills specification](https://agentskills.io/specification)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude custom skills ZIP guidance](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Gemini CLI skills](https://geminicli.com/docs/cli/using-agent-skills/)
