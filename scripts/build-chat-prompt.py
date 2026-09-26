#!/usr/bin/env python3
"""
Generate pepper-prompt-engineer/chat-prompt.md from the skill's canonical sources.

Why this exists
---------------
The chat edition used to be a hand-maintained restatement of the whole methodology.
It drifted: the same stale model identifiers and unsupported figures had to be fixed
in two places, and only one of them ever got fixed. This generator removes the second
source of truth for everything that drifts.

What is generated vs. hand-written
----------------------------------
The template keeps the chat edition's condensed phrasing and its chat-specific parts
(activation protocol, behavioural examples) — those carry no version-dependent facts
and the condensation is what keeps the pasted prompt a usable size.

Everything that *did* drift is pulled from the skill at build time via
`{{include: <path>#<Heading>}}` directives: conditional modules, per-target formatting
and reasoning control, output templates, hard rules, and the self-check list.

Usage
-----
    python3 scripts/build-chat-prompt.py            # write chat-prompt.md
    python3 scripts/build-chat-prompt.py --check    # fail if the file is out of date
"""

import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "plugins" / "pepper-prompt-engineer" / "skills" / "pepper-prompt-engineer"
TEMPLATE = REPO_ROOT / "plugins" / "pepper-prompt-engineer" / "adapters" / "chat" / "chat-prompt.template.md"
OUTPUT = REPO_ROOT / "plugins" / "pepper-prompt-engineer" / "adapters" / "chat" / "chat-prompt.md"

INCLUDE_RE = re.compile(r"^\{\{include:\s*([^#}]+?)\s*(?:#\s*(.+?)\s*)?\}\}\s*$", re.M)

# Intra-skill file references are dangling inside a single pasted chat prompt.
# Rewrite them to the block that carries the same content.
REFMAP = {
    "references/target-models.md": "BLOCK 8",
    "references/conditional-modules.md": "BLOCK 5",
    "references/methodology.md": "BLOCK 4",
    "references/question-strategy.md": "BLOCK 7",
    "references/scope-check.md": "BLOCK 6",
    "references/security.md": "BLOCK 11",
    "references/output-format.md": "BLOCK 2",
    "target-models.md": "BLOCK 8",
    "conditional-modules.md": "BLOCK 5",
    "methodology.md": "BLOCK 4",
    "question-strategy.md": "BLOCK 7",
    "scope-check.md": "BLOCK 6",
    "security.md": "BLOCK 11",
    "output-format.md": "BLOCK 2",
    "SKILL.md": "this prompt",
    "scripts/validate.py": "the validator in the full skill edition",
    "scripts/README.md": "the full skill edition",
}


def heading_level(line: str) -> int | None:
    m = re.match(r"^(#{1,6})\s+\S", line)
    return len(m.group(1)) if m else None


def extract_section(text: str, heading: str) -> str:
    """Body under `heading`, up to the next heading of the same or shallower level."""
    lines = text.split("\n")
    target = heading.strip().lower()
    start = None
    level = None
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl is None:
            continue
        if line[lvl:].strip().lower() == target:
            start, level = i + 1, lvl
            break
    if start is None:
        raise KeyError(f"heading not found: {heading!r}")
    end = len(lines)
    for j in range(start, len(lines)):
        lvl = heading_level(lines[j])
        if lvl is not None and lvl <= level:
            end = j
            break
    return "\n".join(lines[start:end]).strip("\n")


def strip_front_matter_and_title(text: str) -> str:
    """Drop YAML front matter, the H1 title, and a leading '## Contents' section."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    lines = text.split("\n")
    out, skipping_contents = [], False
    for line in lines:
        lvl = heading_level(line)
        if lvl == 1:
            continue
        if lvl == 2 and line[2:].strip().lower() == "contents":
            skipping_contents = True
            continue
        if skipping_contents:
            if lvl is not None and lvl <= 2:
                skipping_contents = False
            else:
                continue
        out.append(line)
    return "\n".join(out).strip("\n")


def resolve(path_str: str) -> pathlib.Path:
    # The transition template used `anthropic/` paths. Treat that prefix as the
    # canonical skill root so old templates remain buildable while there is one
    # editable source tree.
    if path_str.startswith("anthropic/"):
        path_str = path_str[len("anthropic/"):]
    path = SKILL_DIR / path_str
    if not path.exists():
        raise FileNotFoundError(f"include source not found: {path}")
    return path


def expand(template: str) -> str:
    def repl(match: re.Match) -> str:
        path_str, heading = match.group(1), match.group(2)
        text = resolve(path_str).read_text(encoding="utf-8")
        return extract_section(text, heading) if heading else strip_front_matter_and_title(text)

    prev = None
    out = template
    # One nesting level is enough today; loop guards against an included file
    # itself carrying a directive.
    for _ in range(3):
        prev, out = out, INCLUDE_RE.sub(repl, out)
        if out == prev:
            break
    return out


def apply_refmap(text: str) -> str:
    for src, dst in sorted(REFMAP.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(f"`{src}`", dst)
    text = text.replace("`anthropic/SKILL.md`", "`../../skills/pepper-prompt-engineer/SKILL.md`")
    text = text.replace("(./anthropic/SKILL.md)", "(../../skills/pepper-prompt-engineer/SKILL.md)")
    return text


def outer_fence(body: str) -> str:
    """Pick a fence longer than any backtick run the body already opens a block with.

    The whole system prompt ships as one copyable code block. Included reference files
    contain their own ``` and ````  fences, so a fixed ``` outer fence would be
    terminated early and the page would render as broken markdown.
    """
    runs = [len(m.group(1)) for m in re.finditer(r"(?m)^\s*(`{3,})", body)]
    return "`" * (max(runs, default=2) + 1)


def build() -> str:
    if not TEMPLATE.exists():
        print(f"Error: template not found: {TEMPLATE}", file=sys.stderr)
        sys.exit(2)
    body = apply_refmap(expand(TEMPLATE.read_text(encoding="utf-8")))
    body = body.replace("{{FENCE}}", outer_fence(body))
    header = (
        "<!-- GENERATED FILE — do not edit by hand.\n"
        "     Source: chat-prompt.template.md + skills/pepper-prompt-engineer/ (SKILL.md, references/).\n"
        "     Rebuild: python3 scripts/build-chat-prompt.py -->\n\n"
    )
    if not body.endswith("\n"):
        body += "\n"
    return header + body


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate chat-prompt.md from the skill.")
    parser.add_argument("--check", action="store_true", help="fail if the output is stale")
    args = parser.parse_args()

    generated = build()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != generated:
            print("chat-prompt.md is out of date — run: python3 scripts/build-chat-prompt.py",
                  file=sys.stderr)
            sys.exit(1)
        print("chat-prompt.md is up to date.")
        return

    OUTPUT.write_text(generated, encoding="utf-8")
    words = len(generated.split())
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(generated):,} bytes, {words:,} words)")


if __name__ == "__main__":
    main()
