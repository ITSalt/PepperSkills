#!/usr/bin/env python3
"""
Harness for evals/evals.json.

Two jobs:
  1. Validate the eval file's shape and fail loudly if it is malformed.
  2. Print a run sheet — each scenario's query plus its expected_behavior items as a
     checklist — so a run against a live model can be scored consistently.

It deliberately does not call a model. Scoring a prompt-construction skill requires
judgement about the prompt it produced; the harness structures that judgement rather
than faking it.

Usage:
    python run_evals.py                # print the run sheet
    python run_evals.py --check-only   # schema validation only
    python run_evals.py --json         # machine-readable
    python run_evals.py --id creative-gpt-ssot   # one scenario

Exit codes:
    0 — eval file is well-formed
    1 — schema problems found
    2 — invalid invocation
"""

import argparse
import json
import pathlib
import sys

EVALS_PATH = pathlib.Path(__file__).resolve().parent.parent / "evals" / "evals.json"

REQUIRED_KEYS = ("id", "skills", "query", "files", "expected_behavior")


def load(path: pathlib.Path) -> dict:
    if not path.exists():
        print(f"Error: eval file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: {path} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def check(data: dict) -> list[str]:
    """Return a list of problems; empty means the file is well-formed."""
    problems: list[str] = []

    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        return ["'evals' must be a non-empty list"]

    seen_ids: set[str] = set()
    for index, case in enumerate(evals):
        label = case.get("id", f"#{index}")

        for key in REQUIRED_KEYS:
            if key not in case:
                problems.append(f"{label}: missing required key '{key}'")

        case_id = case.get("id")
        if isinstance(case_id, str):
            if case_id in seen_ids:
                problems.append(f"{label}: duplicate id")
            seen_ids.add(case_id)
        elif "id" in case:
            problems.append(f"{label}: 'id' must be a string")

        if not isinstance(case.get("skills", []), list):
            problems.append(f"{label}: 'skills' must be a list")
        if not isinstance(case.get("files", []), list):
            problems.append(f"{label}: 'files' must be a list")

        query = case.get("query")
        if not isinstance(query, str) or not query.strip():
            problems.append(f"{label}: 'query' must be a non-empty string")

        behaviors = case.get("expected_behavior")
        if not isinstance(behaviors, list) or not behaviors:
            problems.append(f"{label}: 'expected_behavior' must be a non-empty list")
        elif any(not isinstance(b, str) or not b.strip() for b in behaviors):
            problems.append(f"{label}: every 'expected_behavior' item must be a non-empty string")

        for missing in case.get("files", []) or []:
            if not (EVALS_PATH.parent / missing).exists():
                problems.append(f"{label}: referenced file not found: {missing}")

    return problems


def run_sheet(evals: list[dict]) -> str:
    lines: list[str] = []
    for case in evals:
        lines.append("=" * 78)
        lines.append(f"{case['id']}")
        lines.append("=" * 78)
        lines.append("")
        lines.append("QUERY:")
        lines.append(f"  {case['query']}")
        if case.get("files"):
            lines.append(f"FILES: {', '.join(case['files'])}")
        lines.append("")
        lines.append("EXPECTED BEHAVIOR:")
        for behavior in case["expected_behavior"]:
            lines.append(f"  [ ] {behavior}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and print the eval run sheet.")
    parser.add_argument("--check-only", action="store_true", help="schema validation only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--id", help="restrict output to one scenario id")
    parser.add_argument("--file", default=str(EVALS_PATH), help="path to evals.json")
    args = parser.parse_args()

    path = pathlib.Path(args.file)
    data = load(path)
    problems = check(data)

    evals = data.get("evals", [])
    if args.id:
        evals = [c for c in evals if c.get("id") == args.id]
        if not evals:
            print(f"Error: no scenario with id {args.id!r}", file=sys.stderr)
            sys.exit(2)

    if args.json:
        print(json.dumps({"problems": problems, "evals": evals}, ensure_ascii=False, indent=2))
    else:
        if problems:
            print(f"Schema problems ({len(problems)}):")
            for problem in problems:
                print(f"  - {problem}")
            print("")
        else:
            print(f"Schema OK — {len(data.get('evals', []))} scenarios well-formed.\n")
        if not args.check_only:
            print(run_sheet(evals))

    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
