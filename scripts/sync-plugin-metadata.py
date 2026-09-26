#!/usr/bin/env python3
"""Generate plugin LICENSE copies and the OpenAI listing from canonical metadata."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
OPENAI_FIELDS = ('displayName', 'shortDescription', 'longDescription', 'developerName',
                 'category', 'websiteURL', 'capabilities', 'defaultPrompt', 'logo',
                 'composerIcon', 'brandColor')


def rendered(path, content, check):
    if check:
        if not path.is_file() or path.read_text(encoding='utf-8') != content:
            print(f'stale generated file: {path.relative_to(ROOT)}', file=sys.stderr)
            return False
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        print(f'generated: {path.relative_to(ROOT)}')
    return True


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = parser.parse_args()
    check = args.check
    ok = True
    license_text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
    for plugin in sorted((ROOT / 'plugins').glob('pepper-*')):
        ok &= rendered(plugin / 'LICENSE', license_text, check)
        pointer = ('<!-- GENERATED TRANSITION POINTER; excluded from distribution archives. -->\n'
                   'Installation instructions have moved to the repository guide:\n'
                   '- [English](../../../../docs/installation-and-updates.md)\n'
                   '- [Русский](../../../../docs/installation-and-updates.ru.md)\n')
        ok &= rendered(plugin / 'skills' / plugin.name / 'INSTALL.md', pointer, check)
    plugin = ROOT / 'plugins/pepper-ru-web-compliance'
    manifest = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))
    author = manifest['author']
    interface = manifest.get('extensions', {}).get('com.openai', {}).get('interface', {})
    extra_path = plugin / 'submission/listing-extra.json'
    extra = json.loads(extra_path.read_text(encoding='utf-8'))
    collisions = set(extra) & (set(OPENAI_FIELDS) | {'publisher'})
    if collisions:
        raise SystemExit('listing-extra.json overrides manifest fields: ' + ', '.join(sorted(collisions)))
    missing = set(OPENAI_FIELDS) - set(interface)
    if missing:
        raise SystemExit('plugin manifest missing OpenAI interface fields: ' + ', '.join(sorted(missing)))
    listing = {key: interface[key] for key in OPENAI_FIELDS}
    listing['publisher'] = {key: author[key] for key in ('name', 'email', 'url') if key in author}
    listing.update(extra)
    out = json.dumps(listing, ensure_ascii=False, indent=2) + '\n'
    ok &= rendered(plugin / 'submission/listing.json', out, check)
    return 0 if ok else 1

if __name__ == '__main__':
    raise SystemExit(main())
