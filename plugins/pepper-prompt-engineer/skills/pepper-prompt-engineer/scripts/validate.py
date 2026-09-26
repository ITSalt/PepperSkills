#!/usr/bin/env python3
"""
CRAFT+ Prompt Validator

Programmatically checks a generated prompt against the CRAFT+ checklist.
Designed for use after the skill produces a prompt — especially valuable in
`improve` mode and for complex prompts where manual self-check might miss issues.

The check count is not fixed: 16 checks always run, and two more
(aggressive-emphasis, chain-of-thought injection) run only for the targets they
apply to, for a maximum of 18. The report prints the actual count.

Usage:
    python validate.py <prompt-file> --target <claude|gpt|gemini|deepseek|universal> [--use-ssot] [--mode improve|generate]
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


TargetModel = Literal["claude", "gpt", "gemini", "deepseek", "universal"]

TARGETS = ["claude", "gpt", "gemini", "deepseek", "universal"]

# Retired identifiers still accepted so existing callers do not break.
# See the "Old patterns" section of references/target-models.md.
DEPRECATED_TARGET_ALIASES = {"deepseek-chat": "deepseek"}


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

# Blocks whose content the vague-phrase check inspects. Scanning the whole prompt
# produces false positives — a task that is legitimately *about* creativity says
# "be creative" in CONTEXT without that being a defect.
VAGUENESS_SCOPE = ("success_criteria", "verification")

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

# Escalated emphasis attached to a tool/skill directive.
#
# Scope note: the vendor guidance this implements is specifically about *tool and
# skill triggering* — "Where you might have said 'CRITICAL: You MUST use this tool
# when...', you can use more normal prompting like 'Use this tool when...'".
# Plain NEVER / MUST / DO NOT inside formatting and grounding rules is fine; the
# vendor's own sample prompts use it. So this check only fires when escalated
# emphasis sits next to a tool directive, not on every capitalised imperative.
AGGRESSIVE_PATTERNS = [
    r"\b(?:CRITICAL|IMPORTANT|MANDATORY)\b[:!\s]{1,4}(?:YOU\s+)?MUST\b[^.\n]{0,80}\b(?:tool|skill|function|search|browse)\b",
    r"\b(?:tool|skill|function)\b[^.\n]{0,40}\b(?:CRITICAL|IMPORTANT)\s*[:!]{1,3}",
    r"!{3,}",
]

# "think step by step" injection patterns — competes with the target's reasoning control
THINK_STEP_PATTERNS = [
    r"think step[- ]by[- ]step",
    r"let's think step[- ]by[- ]step",
    r"thinking step[- ]by[- ]step",
]

# Uncertainty rule signature — must appear in CONSTRAINTS
UNCERTAINTY_SIGNATURE = "fabricate facts"  # core anchor; full rule contains "do not fabricate facts"

# Upper bound only. There is no lower bound: a simple task gets a short prompt,
# and padding one to reach a floor is the over-engineering pitfall the skill warns
# about. See hard rule 8 in SKILL.md.
MAX_WORDS = 700

# Every wrapping form target-models.md prescribes for a conditional module.
# Checking only the XML form silently fails the gpt and gemini targets, where the
# module is written as a Markdown header.
SSOT_BLOCK_PATTERNS = [
    r"<creativity_protocol>",
    r"(?mi)^#{1,3}\s+creativity[ _]protocol\s*$",
    r"(?i)\bcreativity_protocol\b",
]


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
            "CRAFT+ Prompt Validation Report",
            "================================",
            f"Target model: {self.target_model}",
            f"useSSOT: {self.use_ssot}",
            f"Mode: {self.mode}",
            f"Word count: {self.word_count}",
            "",
            f"Checks ({len(self.checks) - self.failed_count}/{len(self.checks)} passed):",
            "",
        ]
        for c in self.checks:
            symbol = "PASS" if c.passed else "FAIL"
            lines.append(f"[{symbol}] {c.name}")
            if c.detail:
                lines.append(f"       {c.detail}")
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


# --- block detection -------------------------------------------------------
#
# Each detector returns the block's inner text, or None when the block is absent.
# Returning the text (rather than a bool) lets checks that care about *content*
# — the vague-phrase scan — look at just the block they are about.


def _find_block_xml(prompt: str, block: str) -> str | None:
    m = re.search(rf"<{block}>(.*?)</{block}>", prompt, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def _find_block_header(prompt: str, block: str, level: int) -> str | None:
    """Markdown header form. Header text is the block name with underscores as spaces.

    Matched case-insensitively: a prompt that writes '# Success criteria' is
    correctly formed, and failing it on capitalisation alone would be noise.
    """
    header_text = block.replace("_", " ")
    hashes = "#" * level
    pattern = rf"(?mi)^{hashes}\s+{re.escape(header_text)}\s*$"
    m = re.search(pattern, prompt)
    if not m:
        return None
    rest = prompt[m.end():]
    # Block runs until the next header of the same or shallower level.
    nxt = re.search(rf"(?m)^#{{1,{level}}}\s+\S", rest)
    return rest[: nxt.start()] if nxt else rest


def _find_block_claude(prompt: str, block: str) -> str | None:
    return _find_block_xml(prompt, block)


def _find_block_gpt(prompt: str, block: str) -> str | None:
    """GPT format is Markdown headers for hierarchy plus XML around content units.

    target-models.md tells the gpt target to use both, so either form is valid here.
    """
    return _find_block_header(prompt, block, 1) or _find_block_xml(prompt, block)


def _find_block_gemini(prompt: str, block: str) -> str | None:
    return _find_block_header(prompt, block, 2) or _find_block_xml(prompt, block)


def _find_block_universal(prompt: str, block: str) -> str | None:
    return _find_block_xml(prompt, block)


def _find_block_deepseek(prompt: str, block: str) -> str | None:
    """DeepSeek accepts either XML or Markdown headers."""
    return (
        _find_block_xml(prompt, block)
        or _find_block_header(prompt, block, 1)
        or _find_block_header(prompt, block, 2)
    )


_BLOCK_FINDERS = {
    "claude": _find_block_claude,
    "gpt": _find_block_gpt,
    "gemini": _find_block_gemini,
    "deepseek": _find_block_deepseek,
    "universal": _find_block_universal,
}


def normalize_target(target: str) -> TargetModel:
    """Map a retired identifier onto its current target. See Old patterns in target-models.md."""
    return DEPRECATED_TARGET_ALIASES.get(target, target)  # type: ignore[return-value]


def validate_prompt(
    prompt: str,
    target_model: str,
    use_ssot: bool = False,
    mode: str = "generate",
) -> ValidationReport:
    """Run the CRAFT+ checklist against the prompt text.

    16 checks always run; two more apply only to the targets they concern.
    """

    target_model = normalize_target(target_model)
    if target_model not in _BLOCK_FINDERS:
        raise ValueError(f"unknown target_model: {target_model!r}; expected one of {TARGETS}")

    report = ValidationReport(target_model=target_model, use_ssot=use_ssot, mode=mode)
    find_block = _BLOCK_FINDERS[target_model]

    report.word_count = len(prompt.split())

    # CHECK 1: Language instruction is the FIRST line of the prompt.
    # SKILL.md Step 6 is unambiguous about the position, so this checks position,
    # not mere presence — a language line buried mid-prompt is a defect.
    first_line = next((l.strip() for l in prompt.lstrip().split("\n") if l.strip()), "")
    has_lang = first_line.lower().startswith("respond to the user in ")
    report.checks.append(CheckResult(
        name="Language instruction is the first line ('Respond to the user in ...')",
        passed=has_lang,
        detail="" if has_lang else f"First non-empty line is: {first_line[:70]!r}",
    ))

    # CHECK 2-11: Each CRAFT+ block present (or properly skipped)
    blocks: dict[str, str | None] = {}
    for block in CRAFT_BLOCKS:
        content = find_block(prompt, block)
        blocks[block] = content
        present = content is not None
        skippable = block in SKIPPABLE_BLOCKS
        passed = present or skippable
        if not present and skippable:
            detail = f"Block skipped (allowed for {block}, simple-task only)"
        elif not present:
            detail = "Required CRAFT+ block missing"
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

    # CHECK 13: Length ceiling. No floor — see MAX_WORDS.
    length_ok = report.word_count <= MAX_WORDS
    report.checks.append(CheckResult(
        name=f"Length within {MAX_WORDS} words",
        passed=length_ok,
        detail=f"Actual: {report.word_count} words" if not length_ok else "",
    ))

    # CHECK 14 (claude/universal only): No escalated emphasis on tool directives
    if target_model in {"claude", "universal"}:
        aggressive_hits = [p for p in AGGRESSIVE_PATTERNS if re.search(p, prompt, re.IGNORECASE)]
        report.checks.append(CheckResult(
            name="No escalated emphasis on tool/skill directives",
            passed=not aggressive_hits,
            detail=f"Matched: {', '.join(aggressive_hits)}" if aggressive_hits else "",
        ))

    # CHECK 15 (all but deepseek-only edge cases): No "think step by step" injection
    if target_model in {"claude", "gpt", "gemini", "deepseek", "universal"}:
        cot_hits = [p for p in THINK_STEP_PATTERNS if re.search(p, prompt, re.IGNORECASE)]
        report.checks.append(CheckResult(
            name="No 'think step by step' injection (raise the target's reasoning control instead)",
            passed=not cot_hits,
            detail=f"Found: {', '.join(cot_hits)}" if cot_hits else "",
        ))

    # CHECK 16: No vague phrases — scoped to success_criteria / verification
    scoped_text = "\n".join(blocks.get(b) or "" for b in VAGUENESS_SCOPE)
    found_vague = [p for p in VAGUE_PHRASES if p.lower() in scoped_text.lower()]
    report.checks.append(CheckResult(
        name="No vague phrases in success_criteria / verification",
        passed=not found_vague,
        detail=f"Found: {', '.join(found_vague)}" if found_vague else "",
    ))

    # CHECK 17: SSoT consistency across every wrapping form target-models.md allows
    has_ssot_block = any(re.search(p, prompt) for p in SSOT_BLOCK_PATTERNS)
    ssot_consistent = use_ssot == has_ssot_block
    report.checks.append(CheckResult(
        name="useSSOT flag matches creativity-protocol presence",
        passed=ssot_consistent,
        detail=(
            ""
            if ssot_consistent
            else f"useSSOT={use_ssot} but creativity protocol {'present' if has_ssot_block else 'absent'}"
        ),
    ))

    # CHECK 18: No injection-defense clutter in the inner prompt
    injection_defense_patterns = [
        "ignore previous instructions",
        "prompt injection",
        "do not follow instructions in the user input",
    ]
    found_defense = [p for p in injection_defense_patterns if p.lower() in prompt.lower()]
    report.checks.append(CheckResult(
        name="No injection-defense clutter in inner prompt",
        passed=not found_defense,
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
        description="Validate a CRAFT+ generated prompt against the CRAFT+ checklist."
    )
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument(
        "--target",
        required=True,
        choices=TARGETS + list(DEPRECATED_TARGET_ALIASES),
        metavar="{" + ",".join(TARGETS) + "}",
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

    if args.target in DEPRECATED_TARGET_ALIASES:
        print(
            f"note: --target {args.target} is retired; using "
            f"{DEPRECATED_TARGET_ALIASES[args.target]}",
            file=sys.stderr,
        )

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
