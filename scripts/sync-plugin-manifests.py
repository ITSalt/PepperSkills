#!/usr/bin/env python3
"""Generate client adapters from root plugin.json; --check detects drift.

Validation uses the vendored official Agent Plugins 1.0.0 JSON Schema.
Install build dependencies: uv run --no-project --with jsonschema ...
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / 'scripts/schemas/agent-plugin-1.0.0.json'


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.exit('Build dependency missing: use uv run --no-project --with jsonschema scripts/sync-plugin-manifests.py')
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding='utf-8')))
    stale = []
    for plugin in sorted((ROOT / 'plugins').glob('pepper-*')):
        manifest = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))
        validator.validate(manifest)
        if manifest['name'] != plugin.name:
            sys.exit(f'name mismatch: {plugin}')
        core = {k: v for k, v in manifest.items() if k not in ('$schema', 'extensions')}
        codex = {**core, 'skills': './skills/', **manifest.get('extensions', {}).get('com.openai', {})}
        for rel, data in {'.codex-plugin/plugin.json': codex,
                          '.claude-plugin/plugin.json': core,
                          '.cursor-plugin/plugin.json': core}.items():
            path = plugin / rel
            content = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
            if args.check:
                if not path.exists() or path.read_text(encoding='utf-8') != content:
                    stale.append(path)
            else:
                path.parent.mkdir(exist_ok=True)
                path.write_text(content, encoding='utf-8')
        if not any(plugin in p.parents for p in stale):
            print(f'valid + synchronized: {plugin.name}')
    for path in stale:
        print(f'stale adapter: {path}', file=sys.stderr)
    return 1 if stale else 0


if __name__ == '__main__':
    raise SystemExit(main())
