#!/usr/bin/env bash
# Create a user link, or repoint only a recognized PepperSkills legacy symlink.
set -euo pipefail
if [[ $# -ne 4 ]]; then
  echo "usage: $0 <skill|chat|file> <product-name> <link-path> <canonical-path>" >&2
  exit 2
fi
kind="$1"
product="$2"
link_path="$3"
source_path="$4"
[[ "$product" =~ ^[a-z0-9-]+$ ]] || { echo "invalid product name" >&2; exit 2; }
case "$kind" in
  skill) [[ -f "$source_path/SKILL.md" ]] || { echo "missing canonical SKILL.md: $source_path" >&2; exit 1; } ;;
  chat) [[ -d "$source_path" && -n "$(find "$source_path" -maxdepth 1 -type f -name '*.md' -print -quit)" ]] || { echo "missing canonical chat adapter directory: $source_path" >&2; exit 1; } ;;
  file) [[ -f "$source_path" ]] || { echo "missing canonical file: $source_path" >&2; exit 1; } ;;
  *) echo "unsupported link kind: $kind" >&2; exit 2 ;;
esac
if [[ -d "$source_path" ]]; then
  source_abs="$(cd "$source_path" && pwd -P)"
else
  source_abs="$(cd "$(dirname "$source_path")" && printf '%s/%s\n' "$(pwd -P)" "$(basename "$source_path")")"
fi
if [[ -L "$link_path" ]]; then
  current="$(readlink "$link_path")"
  case "$kind:$current" in
    "$kind:$source_abs") exit 0 ;;
    skill:*/"$product"/anthropic|skill:*/plugins/"$product"/skills/"$product") ;;
    chat:*/"$product"/openai|chat:*/plugins/"$product"/adapters/chat) ;;
    file:*/"$product"/chat-prompt.md|file:*/"$product"/chat-prompt.template.md|file:*/plugins/"$product"/adapters/chat/chat-prompt.md|file:*/plugins/"$product"/adapters/chat/chat-prompt.template.md) ;;
    *) echo "refusing to replace unrecognized symlink: $link_path -> $current" >&2; exit 1 ;;
  esac
  rm "$link_path"
  ln -s "$source_abs" "$link_path"
elif [[ -e "$link_path" ]]; then
  echo "refusing to replace existing non-symlink: $link_path" >&2
  exit 1
else
  mkdir -p "$(dirname "$link_path")"
  ln -s "$source_abs" "$link_path"
fi
