#!/usr/bin/env python3
"""
CRAFT+ Prompt Validator

Programmatically checks a generated prompt against the 13-item CRAFT+ checklist.
Designed for use after the skill produces a prompt — especially valuable in
`improve` mode and for complex prompts where manual self-check might miss issues.

Usage:
    python validate.py <prompt-file> --target <claude|gpt|gemini|deepseek-chat|universal> [--use-ssot] [--mode improve|generate]
    cat prompt.txt | python validate.py --target claude --stdin

    # Or as a library:
    from validate import validate_prompt
    result = validate_prompt(prompt_text, target_model="claude", use_ssot=False)
    print(result.report())

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
    2 — invalid invocation
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Literal


TargetModel = Literal["claude", "gpt", "gemini", "deepseek-chat", "universal"]


# Block names CRAFT+ expects (semantic, not syntactic)
CRAFT_BLOCKS = [
    "role",
    "task",
    "context",
    "success_criteria",
    "actions",
    "constraints",
    "reasoning_mode",
    "output_format",
    "examples",
    "verification",
]

# Blocks that can be skipped for simple tasks
SKIPPABLE_BLOCKS = {"actions", "examples"}

# Vague phrases forbidden in success_criteria / verification (case-insensitive substring match)
VAGUE_PHRASES = [
    "write well",
    "make it quality",
    "be creative",
    "make it good",
    "make it interesting",
    "make it engaging",
    "be helpful",
    "do your best",
    "напиши хорошо",
    "сделай качественно",
    "будь креативным",
    "сделай интересно",
    "сделай хорошо",
]

# Aggressive emphasis patterns that hurt Claude 4.6+
AGGRESSIVE_PATTERNS = [
    r"\bCRITICAL:\s*YOU MUST\b",
    r"\bIMPORTANT!!!\b",
    r"\bMUST NOT\b.*\bMUST NOT\b.*\bMUST NOT\b",  # 3+ MUST NOT in close range
]

# "think step by step" injection patterns — bad for frontier reasoning models
THINK_STEP_PATTERNS = [
    r"think step[- ]by[- ]step",
    r"let's think step[- ]by[- ]step",
    r"thinking step[- ]by[- ]step",
]

# Uncertainty rule signature — must appear in CONSTRAINTS
UNCERTAINTY_SIGNATURE = "fabricate facts"  # core anchor; full rule contains "do not fabricate facts"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    target_model: TargetModel
    use_ssot: bool
    mode: str
    checks: list[CheckResult] = field(default_factory=list)
    word_count: int = 0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def report(self) -> str:
        lines = [
            f"CRAFT+ Prompt Validation Report",
            f"================================",
            f"Target model: {self.target_model}",
            f"useSSOT: {self.use_ssot}",
            f"Mode: {self.mode}",
            f"Word count: {self.word_count}",
            f"",
            f"Checks ({len(self.checks) - self.failed_count}/{len(self.checks)} passed):",
            "",
        ]
        for c in self.checks:
            symbol = "✅" if c.passed else "❌"
            lines.append(f"{symbol} {c.name}")
            if c.detail:
                lines.append(f"   {c.detail}")
        lines.append("")
        if self.all_passed:
            lines.append("RESULT: All checks passed.")
        else:
            lines.append(f"RESULT: {self.failed_count} check(s) failed — fix the prompt.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "target_model": self.target_model,
            "use_ssot": self.use_ssot,
            "mode": self.mode,
            "word_count": self.word_count,
            "all_passed": self.all_passed,
            "failed_count": self.failed_count,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _has_block_claude(prompt: str, block: str) -> bool:
    """Claude format uses XML tags."""
    return bool(re.search(rf"<{block}>.*?</{block}>", prompt, re.IGNORECASE | re.DOTALL))


def _has_block_gpt(prompt: str, block: str) -> bool:
    """GPT format uses # Markdown headers. Block names are title-cased with spaces."""
    header_text = block.replace("_", " ").title()  # e.g., "Success Criteria"
    pattern = rf"(?m)^#\s+{re.escape(header_text)}\s*$"
    return bool(re.search(pattern, prompt))


def _has_block_gemini(prompt: str, block: str) -> bool:
    """Gemini format uses ## Markdown headers."""
    header_text = block.replace("_", " ").title()
    pattern = rf"(?m)^##\s+{re.escape(header_text)}\s*$"
    return bool(re.search(pattern, prompt))


def _has_block_universal(prompt: str, block: str) -> bool:
    """Universal uses XML scaffold (same as Claude)."""
    return _has_block_claude(prompt, block)


def _has_block_deepseek(prompt: str, block: str) -> bool:
    """DeepSeek accepts either XML or Markdown headers."""
    return (
        _has_block_claude(prompt, block)
        or _has_block_gpt(prompt, block)
        or _has_block_gemini(prompt, block)
    )


_BLOCK_CHECKERS = {
    "claude": _has_block_claude,
    "gpt": _has_block_gpt,
    "gemini": _has_block_gemini,
    "deepseek-chat": _has_block_deepseek,
    "universal": _has_block_universal,
}


def validate_prompt(
    prompt: str,
    target_model: TargetModel,
    use_ssot: bool = False,
    mode: str = "generate",
) -> ValidationReport:
    """Run the 13-item CRAFT+ checklist against the prompt text."""

    report = ValidationReport(target_model=target_model, use_ssot=use_ssot, mode=mode)
    has_block = _BLOCK_CHECKERS[target_model]

    # Word count for check #12
    report.word_count = len(prompt.split())

    # CHECK 1: Language instruction present at the start of the prompt
    # For Claude (XML format), instruction sits inside the first <role> block; for others,
    # it's typically the literal first line. Check in the first ~10 non-empty lines.
    head_lines = [l.strip() for l in prompt.lstrip().split("\n")[:15] if l.strip()]
    has_lang = any(
        l.lower().startswith("respond to the user in ") for l in head_lines
    )
    report.checks.append(CheckResult(
        name="Language instruction at the start ('Respond to the user in ...')",
        passed=has_lang,
        detail="" if has_lang else "Missing language instruction in the first 15 lines of the prompt",
    ))

    # CHECK 2-11: Each CRAFT+ block present (or properly skipped)
    for block in CRAFT_BLOCKS:
        present = has_block(prompt, block)
        skippable = block in SKIPPABLE_BLOCKS
        passed = present or skippable
        if not present and skippable:
            detail = f"Block skipped (allowed for {block}, simple-task only)"
        elif not present:
            detail = f"Required CRAFT+ block missing"
        else:
            detail = ""
        report.checks.append(CheckResult(
            name=f"CRAFT+ block: {block}",
            passed=passed,
            detail=detail,
        ))

    # CHECK 12: Uncertainty rule embedded in constraints
    has_uncertainty = UNCERTAINTY_SIGNATURE.lower() in prompt.lower()
    report.checks.append(CheckResult(
        name="Uncertainty rule embedded ('do not fabricate facts')",
        passed=has_uncertainty,
        detail="" if has_uncertainty else "Missing the mandatory uncertainty rule in CONSTRAINTS",
    ))

    # CHECK 13: Length 200-700 words
    length_ok = 200 <= report.word_count <= 700
    report.checks.append(CheckResult(
        name="Length 200-700 words",
        passed=length_ok,
        detail=f"Actual: {report.word_count} words" if not length_ok else "",
    ))

    # CHECK 14: No aggressive emphasis (Claude/universal targets are sensitive)
    if target_model in {"claude", "universal"}:
        aggressive_hits = []
        for pattern in AGGRESSIVE_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                aggressive_hits.append(pattern)
        no_aggressive = not aggressive_hits
        report.checks.append(CheckResult(
            name="No aggressive emphasis (Claude/Universal sensitivity)",
            passed=no_aggressive,
            detail=f"Found: {', '.join(aggressive_hits)}" if aggressive_hits else "",
        ))

    # CHECK 15: No "think step by step" injection (Claude/GPT/Gemini do CoT internally)
    if target_model in {"claude", "gpt", "gemini", "universal"}:
        cot_hits = []
        for pattern in THINK_STEP_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                cot_hits.append(pattern)
        no_cot = not cot_hits
        report.checks.append(CheckResult(
            name="No 'think step by step' injection (frontier models do CoT internally)",
            passed=no_cot,
            detail=f"Found: {', '.join(cot_hits)}" if cot_hits else "",
        ))

    # CHECK 16: No vague phrases in success_criteria/verification
    found_vague = [p for p in VAGUE_PHRASES if p.lower() in prompt.lower()]
    no_vague = not found_vague
    report.checks.append(CheckResult(
        name="No vague phrases ('write well', 'be creative' etc.)",
        passed=no_vague,
        detail=f"Found: {', '.join(found_vague)}" if found_vague else "",
    ))

    # CHECK 17: SSoT consistency (useSSOT=true ↔ creativity_protocol present)
    has_ssot_block = "<creativity_protocol>" in prompt or "creativity_protocol" in prompt.lower()
    ssot_consistent = use_ssot == has_ssot_block
    report.checks.append(CheckResult(
        name="useSSOT flag matches creativity_protocol presence",
        passed=ssot_consistent,
        detail=(
            ""
            if ssot_consistent
            else f"useSSOT={use_ssot} but creativity_protocol {'present' if has_ssot_block else 'absent'}"
        ),
    ))

    # CHECK 18: No injection-defense clutter in the inner prompt
    injection_defense_patterns = [
        "ignore previous instructions",
        "prompt injection",
        "do not follow instructions in the user input",
    ]
    found_defense = [p for p in injection_defense_patterns if p.lower() in prompt.lower()]
    no_defense = not found_defense
    report.checks.append(CheckResult(
        name="No injection-defense clutter in inner prompt",
        passed=no_defense,
        detail=f"Found: {', '.join(found_defense)}" if found_defense else "",
    ))

    return report


def _read_prompt(args: argparse.Namespace) -> str:
    if args.stdin:
        return sys.stdin.read()
    if not args.prompt_file:
        print("Error: provide a prompt file path or use --stdin", file=sys.stderr)
        sys.exit(2)
    with open(args.prompt_file, "r", encoding="utf-8") as f:
        return f.read()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a CRAFT+ generated prompt against the 13-item checklist."
    )
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument(
        "--target",
        required=True,
        choices=["claude", "gpt", "gemini", "deepseek-chat", "universal"],
        help="Target model the prompt was built for",
    )
    parser.add_argument("--use-ssot", action="store_true", help="SSoT module is expected in the prompt")
    parser.add_argument(
        "--mode",
        default="generate",
        choices=["generate", "improve"],
        help="Generation mode (default: generate)",
    )
    parser.add_argument("--stdin", action="store_true", help="Read prompt from stdin")
    parser.add_argument("--json", action="store_true", help="Output report as JSON")

    args = parser.parse_args()
    prompt = _read_prompt(args)

    report = validate_prompt(
        prompt=prompt,
        target_model=args.target,
        use_ssot=args.use_ssot,
        mode=args.mode,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.report())

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
