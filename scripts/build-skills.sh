#!/usr/bin/env bash
# Build .skill ZIP archives for every pepper-* skill in this repository.
#
# Each archive contains a single root folder named after the skill, holding
# everything from <skill>/anthropic/ (SKILL.md, references/, examples/, plus
# optional INSTALL.md, scripts/, evals/). This is the layout Anthropic's
# Skills spec requires so that the relative links inside SKILL.md resolve.
#
# Usage:
#   scripts/build-skills.sh            # build all skills
#   scripts/build-skills.sh <slug>...  # build only the given skill(s)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ $# -gt 0 ]]; then
  SKILLS=("$@")
else
  SKILLS=()
  for dir in "$REPO_ROOT"/pepper-*/; do
    [[ -d "${dir}anthropic" ]] || continue
    SKILLS+=("$(basename "$dir")")
  done
fi

if [[ ${#SKILLS[@]} -eq 0 ]]; then
  echo "no pepper-*/anthropic skills found" >&2
  exit 1
fi

for skill in "${SKILLS[@]}"; do
  src="$REPO_ROOT/$skill/anthropic"
  out="$REPO_ROOT/$skill/$skill.skill"

  if [[ ! -d "$src" ]]; then
    echo "skip: $skill has no anthropic/ directory" >&2
    continue
  fi

  staging="$(mktemp -d -t pepper-skill-build.XXXXXX)"
  mkdir -p "$staging/$skill"
  cp -R "$src/." "$staging/$skill/"
  find "$staging" -name '.DS_Store' -delete

  rm -f "$out"
  (cd "$staging" && zip -r -X "$out" "$skill" >/dev/null)

  size_human="$(du -h "$out" | awk '{print $1}')"
  entry_count="$(unzip -l "$out" | tail -1 | awk '{print $2}')"
  echo "built: ${skill}.skill (${size_human}, ${entry_count} entries)"

  rm -rf "$staging"
done
