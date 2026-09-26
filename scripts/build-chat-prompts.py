#!/usr/bin/env python3
"""Generate all checked-in chat adapters from explicit Markdown templates."""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE_RE = re.compile(r"\{\{include:\s*([^#}]+?)\s*(?:#\s*(.+?)\s*)?\}\}")
PROMPT_REFMAP = {
    "references/target-models.md": "BLOCK 8", "references/conditional-modules.md": "BLOCK 5",
    "references/methodology.md": "BLOCK 4", "references/question-strategy.md": "BLOCK 7",
    "references/scope-check.md": "BLOCK 6", "references/security.md": "BLOCK 11",
    "references/output-format.md": "BLOCK 2", "target-models.md": "BLOCK 8",
    "conditional-modules.md": "BLOCK 5", "methodology.md": "BLOCK 4",
    "question-strategy.md": "BLOCK 7", "scope-check.md": "BLOCK 6",
    "security.md": "BLOCK 11", "output-format.md": "BLOCK 2",
    "SKILL.md": "this prompt", "scripts/validate.py": "the validator in the full skill edition",
    "scripts/README.md": "the full skill edition",
}


def heading_level(line):
    m = re.match(r'^(#{1,6})\s+\S', line)
    return len(m.group(1)) if m else None


def extract_section(text, heading):
    lines = text.split('\n')
    target = heading.strip().lower()
    start = level = None
    for i, line in enumerate(lines):
        n = heading_level(line)
        if n and line[n:].strip().lower() == target:
            start, level = i + 1, n
            break
    if start is None:
        raise ValueError(f'heading not found: {heading!r}')
    end = next((i for i in range(start, len(lines)) if (n := heading_level(lines[i])) and n <= level), len(lines))
    return '\n'.join(lines[start:end]).strip('\n')


def expand(template, plugin_dir, prompt=False):
    def replace(m):
        rel, heading = m.group(1).strip(), m.group(2)
        source = (plugin_dir / rel).resolve()
        if not source.is_relative_to(plugin_dir.resolve()) or not source.is_file():
            raise ValueError(f'include outside plugin or missing: {rel}')
        text = source.read_text(encoding='utf-8')
        return extract_section(text, heading) if heading else text.strip('\n')
    old = None
    for _ in range(4):
        pattern = re.compile(r"^\{\{include:\s*([^#}]+?)\s*(?:#\s*(.+?)\s*)?\}\}\s*$", re.M) if prompt else INCLUDE_RE
        old, template = template, pattern.sub(replace, template)
        if template == old:
            break
    if INCLUDE_RE.search(template):
        raise ValueError('nested or unresolved include directive')
    return template


def appendices(template, plugin_dir):
    """Append only the resources explicitly selected by the Markdown template."""
    def replace(match):
        source = (plugin_dir / match.group(1).strip()).resolve()
        if not source.is_relative_to(plugin_dir.resolve()) or not source.is_file():
            raise ValueError(f'invalid appendix: {source}')
        return '## ' + source.stem + '\n\n' + source.read_text(encoding='utf-8')
    return re.sub(r'\{\{appendix:\s*([^}]+?)\s*\}\}', replace, template)


def template_language(template):
    """Read explicit template metadata, independently of the prompt's prose."""
    match = re.match(r'\A<!-- chat-language: (en|ru) -->\n\n', template)
    if not match:
        raise ValueError('template must start with <!-- chat-language: en|ru --> and a blank line')
    return match.group(1), template[match.end():]


def local_reference_labels(body, *, language):
    """A pasted prompt cannot follow repository-relative Markdown links."""
    labels = {
        'en': ('appendix “{stem}”', 'the “{stem}” reference in the full skill edition'),
        'ru': ('приложение «{stem}»', 'справочный материал «{stem}» в полной версии скилла'),
    }
    included, external = labels[language]
    def label(match):
        stem = Path(match.group(1)).stem
        if re.search(r'^## ' + re.escape(stem) + r'$', body, re.M):
            return included.format(stem=stem)
        return external.format(stem=stem)
    body = re.sub(r'\[`references/[^`]+`\]\(\.?/?(references/[^)]+\.md)\)', label, body)
    return re.sub(r'`(references/[^`]+\.md)`', label, body)


def fence_for(body):
    runs = [len(m.group(1)) for m in re.finditer(r'(?m)^\s*(`{3,})', body)]
    return '`' * (max(runs, default=2) + 1)


def prompt_engineer(body, plugin_dir):
    for src, dst in sorted(PROMPT_REFMAP.items(), key=lambda kv: -len(kv[0])):
        body = body.replace(f'`{src}`', dst)
    body = body.replace('`skills/pepper-prompt-engineer/SKILL.md`', '`../../skills/pepper-prompt-engineer/SKILL.md`')
    body = body.replace('(./skills/pepper-prompt-engineer/SKILL.md)', '(../../skills/pepper-prompt-engineer/SKILL.md)')
    body = body.replace('{{FENCE}}', fence_for(body))
    return ('<!-- GENERATED FILE — do not edit by hand.\n'
            '     Source: chat-prompt.template.md + skills/pepper-prompt-engineer/.\n'
            '     Rebuild: python3 scripts/build-chat-prompts.py --write -->\n\n' + body.rstrip() + '\n')


def build_all():
    outputs = {}
    for plugin_dir in sorted((ROOT / 'plugins').glob('pepper-*')):
        chat_dir = plugin_dir / 'adapters/chat'
        for template_path in sorted(chat_dir.glob('*.template.md')):
            output_path = template_path.with_name(template_path.name.removesuffix('.template.md') + '.md')
            language, template = template_language(template_path.read_text(encoding='utf-8'))
            body = expand(template, plugin_dir, plugin_dir.name == 'pepper-prompt-engineer')
            if plugin_dir.name == 'pepper-prompt-engineer' and template_path.name == 'chat-prompt.template.md':
                generated = prompt_engineer(body, plugin_dir)
            else:
                body = local_reference_labels(appendices(body, plugin_dir), language=language)
                generated = '<!-- GENERATED: uv run --no-project scripts/build-chat-prompts.py --write; edit canonical skill sources and templates. -->\n\n' + body
            outputs[output_path] = generated
    return outputs


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    failed = False
    for path, content in build_all().items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                print(f'stale chat adapter: {path.relative_to(ROOT)}', file=sys.stderr)
                failed = True
        else:
            path.write_text(content, encoding='utf-8')
            print(f'generated: {path.relative_to(ROOT)}')
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
