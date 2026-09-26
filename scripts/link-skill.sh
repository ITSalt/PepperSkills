#!/usr/bin/env bash
# Create a shared skill symlink or repoint a recognized PepperSkills legacy link.
set -euo pipefail
if [[ $# -ne 3 ]]; then
  echo "usage: $0 <skill-name> <link-path> <canonical-skill-path>" >&2
  exit 2
fi
skill_name="$1"
link_path="$2"
source_path="$3"
[[ "$skill_name" =~ ^[a-z0-9-]+$ ]] || { echo "invalid skill name" >&2; exit 2; }
[[ -f "$source_path/SKILL.md" ]] || { echo "missing canonical SKILL.md: $source_path" >&2; exit 1; }
source_abs="$(cd "$source_path" && pwd -P)"
if [[ -L "$link_path" ]]; then
  current="$(readlink "$link_path")"
  case "$current" in
    "$source_abs") exit 0 ;;
    */"$skill_name"/anthropic|*/plugins/"$skill_name"/skills/"$skill_name")
      rm "$link_path"
      ln -s "$source_abs" "$link_path"
      ;;
    *) echo "refusing to replace unrecognized symlink: $link_path -> $current" >&2; exit 1 ;;
  esac
elif [[ -e "$link_path" ]]; then
  echo "refusing to replace existing non-symlink: $link_path" >&2
  exit 1
else
  mkdir -p "$(dirname "$link_path")"
  ln -s "$source_abs" "$link_path"
fi
