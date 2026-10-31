#!/usr/bin/env python3
"""Synchronize only metadata.version in each skill frontmatter from plugin.json."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
VERSION_LINE = re.compile(r"(?m)^(  version:\s*)([^\r\n]+)$")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    failed = False
    for plugin_dir in sorted((ROOT / 'plugins').glob('pepper-*')):
        manifest = json.loads((plugin_dir / 'plugin.json').read_text(encoding='utf-8'))
        version = manifest['version']
        entrypoints = [plugin_dir / 'skills' / plugin_dir.name / 'SKILL.md']
        codex = plugin_dir / 'codex/skills' / plugin_dir.name / 'SKILL.md'
        if codex.is_file(): entrypoints.append(codex)
        for skill_path in entrypoints:
            original = skill_path.read_text(encoding='utf-8')
            if not original.startswith('---\n') or '\n---\n' not in original[4:]:
                sys.exit(f'Invalid frontmatter: {skill_path}')
            end = original.index('\n---\n', 4)
            frontmatter, rest = original[:end], original[end:]
            matches = list(VERSION_LINE.finditer(frontmatter))
            if len(matches) > 1:
                sys.exit(f'Expected at most one metadata.version field: {skill_path}')
            if matches:
                current = matches[0].group(2).strip().strip('"\'')
                updated_frontmatter = VERSION_LINE.sub(lambda m: m.group(1) + version, frontmatter, count=1)
            else:
                if re.search(r'(?m)^metadata:\s*$', frontmatter):
                    sys.exit(f'metadata exists without version: {skill_path}')
                current = None
                updated_frontmatter = frontmatter + f'\nmetadata:\n  version: {version}'
            if current != version:
                if args.check or not args.write:
                    print(f'stale skill version: {skill_path}: {current} != {version}', file=sys.stderr)
                    failed = True
                else:
                    skill_path.write_text(updated_frontmatter + rest, encoding='utf-8')
                    print(f'updated: {skill_path.relative_to(ROOT)} -> {version}')
            else:
                print(f'current: {plugin_dir.name} {version}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
