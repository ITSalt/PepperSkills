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
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.exit('Build dependency missing: use uv run --no-project --with jsonschema scripts/sync-plugin-manifests.py')
    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    for plugin in sorted((ROOT / 'plugins').glob('pepper-*')):
        manifest = json.loads((plugin / 'plugin.json').read_text())
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
                if not path.exists() or path.read_text() != content:
                    sys.exit(f'stale adapter: {path}')
            else:
                path.parent.mkdir(exist_ok=True)
                path.write_text(content)
        print(f'valid + synchronized: {plugin.name}')


if __name__ == '__main__':
    main()
