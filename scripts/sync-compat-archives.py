#!/usr/bin/env python3
"""Refresh or check the supported legacy download against its versioned skill ZIP."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = ap.parse_args()
    name = 'pepper-ru-web-compliance'
    version = json.loads((ROOT / 'plugins' / name / 'plugin.json').read_text())['version']
    source = ROOT / 'dist' / name / version / (name + '.zip')
    target = ROOT / name / (name + '.skill')
    if not source.is_file():
        ap.error('Build versioned ZIPs first: bash scripts/build-skills.sh ' + name)
    if not target.exists() or source.read_bytes() != target.read_bytes():
        if args.check:
            print('Stale .skill download; run python3 scripts/sync-compat-archives.py --write')
            return 1
        shutil.copyfile(source, target)
    print(f'Compatibility archive matches {name} {version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
