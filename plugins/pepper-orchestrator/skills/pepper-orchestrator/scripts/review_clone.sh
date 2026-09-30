#!/usr/bin/env bash
# Disposable clone for reviews: clone at a SHA, set up, run tests, delete.
#   review_clone.sh --repo SRC --sha SHA [--setup CMD]... [--test CMD]... [--keep]
#   review_clone.sh --cleanup DIR
# SRC is a clone URL or a local path. The clone lives in a new temporary directory
# (TMPDIR, marked with .orch-review-clone) and is removed at the end unless --keep;
# --keep prints the directory for mutation runs, --cleanup removes only marked ones.
# Setup commands run in the clone root; ORCH_MAIN_CHECKOUT (if set by the caller) points to the
# repository's main checkout, for example to copy a gitignored env file.
# Exit: 0 all tests passed, 1 a setup or test command failed, 2 usage or clone error.
# Never pushes, never changes SRC.
set -uo pipefail
marker=".orch-review-clone"
usage() { sed -n '2,11p' "$0" >&2; exit 2; }
need() { [[ $# -ge 2 && -n "$2" ]] || { echo "review_clone: $1 needs a value" >&2; exit 2; }; }
repo="" sha="" keep=0 setups=() tests=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) need "$@"; repo="$2"; shift 2 ;;
    --sha) need "$@"; sha="$2"; shift 2 ;;
    --setup) need "$@"; setups+=("$2"); shift 2 ;;
    --test) need "$@"; tests+=("$2"); shift 2 ;;
    --keep) keep=1; shift ;;
    --cleanup)
      dir="${2:-}"
      if [[ -z "$dir" || ! -f "$dir/$marker" ]]; then
        echo "review_clone: $dir is not a review clone directory" >&2; exit 2
      fi
      rm -rf "$dir"; echo "removed $dir"; exit 0 ;;
    -h|--help) usage ;;
    *) echo "review_clone: unknown argument $1" >&2; usage ;;
  esac
done
[[ -n "$repo" && -n "$sha" ]] || usage
[[ "$sha" =~ ^[0-9a-fA-F]{7,40}$ ]] || { echo "review_clone: --sha must be a commit id" >&2; exit 2; }
work="$(mktemp -d "${TMPDIR:-/tmp}/orch-review.XXXXXX")" || { echo "review_clone: mktemp failed" >&2; exit 2; }
[[ -n "$work" && -d "$work" ]] || { echo "review_clone: no temporary directory" >&2; exit 2; }
touch "$work/$marker" || exit 2
cleanup() { if [[ $keep -eq 0 ]]; then rm -rf "$work"; fi; }
trap cleanup EXIT
clone="$work/repo"
if ! git clone -q --no-checkout "$repo" "$clone" 2>"$work/clone.log"; then
  echo "review_clone: clone failed: $(tail -n 3 "$work/clone.log")" >&2; exit 2
fi
if ! git -C "$clone" cat-file -e "$sha^{commit}" 2>/dev/null; then
  git -C "$clone" fetch -q origin "$sha" 2>/dev/null || true
fi
if ! git -C "$clone" -c advice.detachedHead=false checkout -q --detach "$sha" 2>"$work/checkout.log"; then
  echo "review_clone: $sha not found in $repo" >&2; exit 2
fi
echo "clone: $repo at $(git -C "$clone" rev-parse --short=10 HEAD)"
status=0
run_step() {
  local kind="$1"
  local cmd="$2"
  local log="$work/$1-$3.log"
  ( cd "$clone" && bash -c "$cmd" ) >"$log" 2>&1
  local code=$?
  echo "$kind: $cmd -> exit $code"
  if [[ $code -ne 0 ]]; then
    tail -n 30 "$log" | sed 's/^/    /'
    status=1
  fi
  return $code
}
i=0
for cmd in ${setups[@]+"${setups[@]}"}; do
  i=$((i + 1))
  if ! run_step setup "$cmd" "$i"; then
    echo "setup failed: tests not run"; exit 1
  fi
done
i=0
for cmd in ${tests[@]+"${tests[@]}"}; do
  i=$((i + 1))
  run_step test "$cmd" "$i" || true
done
if [[ ${#tests[@]} -eq 0 ]]; then
  echo "tests: none given"
fi
if [[ $keep -eq 1 ]]; then
  echo "clone kept: $clone"
  echo "remove with: bash $0 --cleanup $work"
fi
exit $status
