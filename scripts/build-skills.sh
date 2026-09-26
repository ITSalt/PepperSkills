#!/usr/bin/env bash
# Build .skill ZIP archives for every PepperSkills plugin.
#
# The canonical source is plugins/<name>/skills/<name>. Legacy top-level
# directories are symlinks kept for one transition release.
#
# Usage:
#   scripts/build-skills.sh            # build all skills
#   scripts/build-skills.sh <slug>...  # build only the given skill(s)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python3}"
"$PYTHON" scripts/sync-plugin-manifests.py --check
"$PYTHON" scripts/build-chat-prompts.py --check

if [[ $# -gt 0 ]]; then
  SKILLS=("$@")
else
  SKILLS=()
  for dir in "$REPO_ROOT"/plugins/pepper-*/; do
    [[ -d "${dir}skills/$(basename "$dir")" ]] || continue
    SKILLS+=("$(basename "$dir")")
  done
fi

if [[ ${#SKILLS[@]} -eq 0 ]]; then
  echo "no plugin skills found" >&2
  exit 1
fi

for skill in "${SKILLS[@]}"; do
  src="$REPO_ROOT/plugins/$skill"
  skill_src="$src/skills/$skill"
  out="$REPO_ROOT/$skill/$skill.skill"

  # Skills that ship a chat edition generate it from the same sources, so the two
  # editions cannot drift apart. Regenerate before packaging.
  if [[ -f "$REPO_ROOT/$skill/chat-prompt.template.md" ]]; then
    "$PYTHON" "$REPO_ROOT/scripts/build-chat-prompt.py"
  fi

  if [[ ! -d "$skill_src" ]]; then
    echo "skip: $skill has no plugins/$skill/skills/$skill directory" >&2
    continue
  fi

  staging="$(mktemp -d -t pepper-skill-build.XXXXXX)"
  mkdir -p "$staging/$skill"
  cp -R "$skill_src/." "$staging/$skill/"
  find "$staging" -name '.DS_Store' -delete
  find "$staging" -type f \( -name '*.zip' -o -name '*.skill' \) -delete
  # Байт-код Python в релизе не нужен и тащит в архив абсолютные пути машины,
  # на которой собирали.
  find "$staging" -name '__pycache__' -type d -prune -exec rm -rf {} +

  # Локальные снапшоты госреестров в релиз не входят: данные протухают, а
  # устаревший реестр даёт ложный PASS вместо честного UNKNOWN.
  find "$staging" -path '*/assets/registries-snapshot/*.json' -delete

  # Normalize mtimes so repeated builds produce byte-identical ZIP metadata.
  find "$staging" -exec touch -t 198001010000 {} +

  rm -f "$out"
  (cd "$staging" && zip -r -X "$out" "$skill" >/dev/null)

  size_human="$(du -h "$out" | awk '{print $1}')"
  entry_count="$(unzip -l "$out" | tail -1 | awk '{print $2}')"
  echo "built: ${skill}.skill (${size_human}, ${entry_count} entries)"

  rm -rf "$staging"
done
