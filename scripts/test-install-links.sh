#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$repo/scripts/link-skill.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/plugins/pepper-test/skills/pepper-test" "$tmp/pepper-test"
printf '# test skill\n' > "$tmp/plugins/pepper-test/skills/pepper-test/SKILL.md"
source="$(cd "$tmp/plugins/pepper-test/skills/pepper-test" && pwd -P)"
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
  old="$tmp/pepper-test/anthropic"
  ln -s "$tmp/pepper-test/anthropic" "$tmp/$shell_name/shared/legacy-good"
  "$runner" "$script" pepper-test "$tmp/$shell_name/shared/legacy-good" "$source"
  test "$(readlink "$tmp/$shell_name/shared/legacy-good")" = "$source"
  # Recognized broken legacy path is repairable.
  ln -s "$tmp/pepper-test/anthropic" "$tmp/$shell_name/shared/legacy-broken"
  "$runner" "$script" pepper-test "$tmp/$shell_name/shared/legacy-broken" "$source"
  test -f "$tmp/$shell_name/shared/legacy-broken/SKILL.md"
  # Existing directory and unrelated/broken links must be preserved and rejected.
  mkdir "$tmp/$shell_name/shared/existing-directory"
  if "$runner" "$script" pepper-test "$tmp/$shell_name/shared/existing-directory" "$source" 2>/dev/null; then exit 1; fi
  ln -s "$tmp/unrelated" "$tmp/$shell_name/shared/unrelated"
  if "$runner" "$script" pepper-test "$tmp/$shell_name/shared/unrelated" "$source" 2>/dev/null; then exit 1; fi
  test "$(readlink "$tmp/$shell_name/shared/unrelated")" = "$tmp/unrelated"
done
echo 'PASS safe skill links in Bash and Zsh'
