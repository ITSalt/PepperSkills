#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$repo/scripts/link-skill.sh"
path_script="$repo/scripts/link-path.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/plugins/pepper-test/skills/pepper-test" "$tmp/plugins/pepper-test/adapters/chat" "$tmp/pepper-test"
printf '# test skill\n' > "$tmp/plugins/pepper-test/skills/pepper-test/SKILL.md"
printf '# chat adapter\n' > "$tmp/plugins/pepper-test/adapters/chat/system-prompt.md"
printf '# prompt\n' > "$tmp/plugins/pepper-test/adapters/chat/chat-prompt.md"
source="$(cd "$tmp/plugins/pepper-test/skills/pepper-test" && pwd -P)"
chat_source="$(cd "$tmp/plugins/pepper-test/adapters/chat" && pwd -P)"
file_source="$chat_source/chat-prompt.md"
run_bash() { bash -c 'set -e; before=untouched; set +u; "$@"; test "$before" = untouched; [[ $- != *u* ]]' _ "$@"; }
run_zsh() { zsh -c 'set -e; before=untouched; set +u; "$@"; test "$before" = untouched; [[ $- != *u* ]]' _ "$@"; }
for shell_name in bash zsh; do
  if ! command -v "$shell_name" >/dev/null 2>&1; then echo "missing shell: $shell_name" >&2; exit 1; fi
  runner="run_$shell_name"
  link="$tmp/$shell_name/shared/pepper-test"
  "$runner" "$script" pepper-test "$link" "$source"
  test -L "$link" && test "$(readlink "$link")" = "$source"
  "$runner" "$script" pepper-test "$link" "$source" # already-correct link
  # Recognized good legacy path is safely repointed.
  mkdir -p "$tmp/$shell_name/pepper-test"
  old="$tmp/$shell_name/pepper-test/anthropic"
  ln -s "$source" "$old"
  ln -s "$old" "$tmp/$shell_name/shared/legacy-good"
  test -f "$tmp/$shell_name/shared/legacy-good/SKILL.md"
  "$runner" "$script" pepper-test "$tmp/$shell_name/shared/legacy-good" "$source"
  test "$(readlink "$tmp/$shell_name/shared/legacy-good")" = "$source"
  # Recognized broken legacy path is repairable.
  ln -s "$tmp/pepper-test/anthropic" "$tmp/$shell_name/shared/legacy-broken"
  test ! -e "$tmp/$shell_name/shared/legacy-broken"
  "$runner" "$script" pepper-test "$tmp/$shell_name/shared/legacy-broken" "$source"
  test -f "$tmp/$shell_name/shared/legacy-broken/SKILL.md"
  # Existing agent -> shared-directory -> canonical chains remain valid.
  ln -s pepper-test "$tmp/$shell_name/shared/agent-chain"
  "$runner" "$script" pepper-test "$tmp/$shell_name/shared/agent-chain" "$source"
  test "$(readlink "$tmp/$shell_name/shared/agent-chain")" = pepper-test
  # Existing directory and unrelated/broken links must be preserved and rejected.
  mkdir "$tmp/$shell_name/shared/existing-directory"
  if "$runner" "$script" pepper-test "$tmp/$shell_name/shared/existing-directory" "$source" 2>/dev/null; then exit 1; fi
  ln -s "$tmp/unrelated" "$tmp/$shell_name/shared/unrelated"
  if "$runner" "$script" pepper-test "$tmp/$shell_name/shared/unrelated" "$source" 2>/dev/null; then exit 1; fi
  test "$(readlink "$tmp/$shell_name/shared/unrelated")" = "$tmp/unrelated"

  # Chat aliases and prompt files receive the same type-checked migration.
  chat_link="$tmp/$shell_name/shared/chat"
  "$runner" "$path_script" chat pepper-test "$chat_link" "$chat_source"
  test -f "$chat_link/system-prompt.md"
  ln -s "$chat_source" "$tmp/$shell_name/pepper-test/openai"
  ln -s "$tmp/$shell_name/pepper-test/openai" "$tmp/$shell_name/shared/chat-legacy"
  test -f "$tmp/$shell_name/shared/chat-legacy/system-prompt.md"
  "$runner" "$path_script" chat pepper-test "$tmp/$shell_name/shared/chat-legacy" "$chat_source"
  test "$(readlink "$tmp/$shell_name/shared/chat-legacy")" = "$chat_source"
  ln -s "$tmp/pepper-test/openai" "$tmp/$shell_name/shared/chat-broken"
  "$runner" "$path_script" chat pepper-test "$tmp/$shell_name/shared/chat-broken" "$chat_source"
  test -f "$tmp/$shell_name/shared/chat-broken/system-prompt.md"

  file_link="$tmp/$shell_name/shared/chat-prompt.md"
  "$runner" "$path_script" file pepper-test "$file_link" "$file_source"
  test -f "$file_link" && test "$(readlink "$file_link")" = "$file_source"
  ln -s "$file_source" "$tmp/$shell_name/pepper-test/chat-prompt.md"
  ln -s "$tmp/$shell_name/pepper-test/chat-prompt.md" "$tmp/$shell_name/shared/prompt-legacy"
  test -f "$tmp/$shell_name/shared/prompt-legacy"
  "$runner" "$path_script" file pepper-test "$tmp/$shell_name/shared/prompt-legacy" "$file_source"
  test "$(readlink "$tmp/$shell_name/shared/prompt-legacy")" = "$file_source"
done
echo 'PASS safe skill, chat, and prompt links in Bash and Zsh'
