# Changelog

## 2026-09-26 — repository layout transition

Published Creative Mode 2.0.0, Prompt Engineer 2.5.0 and RU Web Compliance 2.0.0.
[Release links and acceptance record](docs/releases/2026-09-26-transition.md).

| Previous path | Canonical path |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `<name>/chat-prompt.md` | `plugins/<name>/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |
| Root `RELEASE-NOTES-v1.4.*.md` | `docs/releases/` |
| `docs/modernization-*.ru.md` | `docs/history/` |

The root skill paths remain as transition symlinks during Phase A. Existing user
installations are not rewritten. See the [installation guide](docs/installation-and-updates.md)
and [Russian transition map](docs/installation-and-updates.ru.md).

Root `.skill` files are frozen previous builds from repository revision
`v1.4.1-1-g4128fe6` (commit `4128fe6`). They are not rebuilt and do not represent
current plugin versions; new archives are built in `dist/<name>/<version>/`.

### Chat compatibility corrections after review

Chat bodies match checkpoint `e2c7d4f` (including whitespace), except the rebuild
command and six deliberately repaired local-reference labels. The full prompts
already had dangling Markdown links with Russian appendix labels at that checkpoint;
these now name the included appendix directly (English in Creative Mode, Russian in
Compliance). The compact Creative Mode names the full-skill reference without adding
its 5 KB appendix. Appendix selection is explicit in templates. Golden hashes and
exact allowed replacements are recorded in `scripts/fixtures/chat-goldens.json`.
