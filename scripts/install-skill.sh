#!/usr/bin/env bash
# Copy canonical skills from this PepperSkills checkout into a skills directory.
# Meant for setup scripts of cloud environments, where plugins are not installed:
#   install-skill.sh [--pull] [--dest DIR] <plugin-name>...
# --pull   update this checkout first with `git pull --ff-only`
# --dest   target directory (default: $CLAUDE_SKILLS_DIR or ~/.claude/skills)
# Idempotent: each run replaces <dest>/<name> with a fresh copy. A symlinked target
# (a link-skill.sh installation) is left alone and reported as an error.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
pull=0
names=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull) pull=1; shift ;;
    --dest) dest="${2:?--dest needs a directory}"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    -*) echo "install-skill: unknown option $1" >&2; exit 2 ;;
    *) names+=("$1"); shift ;;
  esac
done
if [[ ${#names[@]} -eq 0 ]]; then
  echo "usage: $0 [--pull] [--dest DIR] <plugin-name>..." >&2
  exit 2
fi
if [[ $pull -eq 1 ]]; then
  git -C "$repo" pull --ff-only -q
fi
mkdir -p "$dest"
tmp=""
old=""
cleanup() { [[ -n "$tmp" && -d "$tmp" ]] && rm -rf "$tmp"; [[ -n "$old" && -d "$old" ]] && rm -rf "$old"; return 0; }
trap cleanup EXIT
for name in "${names[@]}"; do
  src="$repo/plugins/$name/skills/$name"
  if [[ ! -f "$src/SKILL.md" ]]; then
    echo "install-skill: no canonical skill $name in $repo" >&2
    exit 1
  fi
  target="$dest/$name"
  if [[ -L "$target" ]]; then
    echo "install-skill: $target is a symlink; remove it first or keep the linked installation" >&2
    exit 1
  fi
  version="$(sed -n 's/^  "version": "\([^"]*\)".*/\1/p' "$repo/plugins/$name/plugin.json" | head -n 1)"
  tmp="$(mktemp -d "$dest/.$name.new.XXXXXX")"
  (cd "$src" && tar cf - --exclude INSTALL.md --exclude __pycache__ --exclude .DS_Store --exclude '*.pyc' .) \
    | (cd "$tmp" && tar xf -)
  chmod 755 "$tmp"
  if [[ -e "$target" ]]; then
    old="$(mktemp -d "$dest/.$name.old.XXXXXX")"
    mv "$target" "$old/$name"
    mv "$tmp" "$target"
    rm -rf "$old"
  else
    mv "$tmp" "$target"
  fi
  tmp=""
  old=""
  echo "installed $name ${version:-unknown} -> $target"
done
