#!/usr/bin/env python3
"""Fail on traces of private machines and projects in tracked files.

Checks every tracked text file, and the text members of tracked archives (.skill, .zip), for
absolute home-directory paths (macOS, Linux and Windows user directories). When the untracked
file `.private-terms.local` exists in the repository root (one term per line, `#` comments), its
terms are searched too, case-insensitively: names of private projects stay on the maintainer's
machine and never enter the public tree. Standard library + git only.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = '.private-terms.local'
# Built from pieces so that this file does not match itself.
HOME_PATHS = re.compile('(' + '|'.join([
    '/' + 'Users/[^/\\s]+',
    '/' + 'home/[a-z_][^/\\s]*',
    '[A-Za-z]:' + r'\\\\?' + 'Users' + r'\\\\?[^\\\s]+',
]) + ')')
ARCHIVES = ('.skill', '.zip')
# Tracked files that may keep a match on purpose: {path: reason}.
EXCEPTIONS = {}


def tracked(root):
    out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], check=True, capture_output=True).stdout
    return [p for p in out.decode('utf-8').split('\0') if p]


def load_terms(root):
    path = Path(root) / TERMS_FILE
    if not path.is_file():
        return []
    terms = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            terms.append(line.lower())
    return terms


def texts(root, rel):
    """(name, text) pairs of a tracked file: the file itself, or the text members of an archive."""
    path = Path(root) / rel
    if not path.is_file():
        return
    data = path.read_bytes()
    if rel.endswith(ARCHIVES):
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    blob = archive.read(member)
                    if b'\0' not in blob:
                        yield f'{rel}!{member}', blob.decode('utf-8', errors='replace')
        except zipfile.BadZipFile:
            pass
        return
    if b'\0' in data:
        return
    yield rel, data.decode('utf-8', errors='replace')


def findings(root, terms=None):
    terms = load_terms(root) if terms is None else terms
    found = []
    for rel in tracked(root):
        if rel in EXCEPTIONS:
            continue
        for name, text in texts(root, rel):
            lower = text.lower()
            for number, line in enumerate(text.splitlines(), 1):
                if HOME_PATHS.search(line):
                    found.append(f'{name}:{number}: absolute home-directory path')
            for term in terms:
                if term in lower:
                    line = lower[:lower.index(term)].count('\n') + 1
                    found.append(f'{name}:{line}: private term from {TERMS_FILE}')
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default=str(ROOT), help='repository root (default: this repository)')
    args = parser.parse_args(argv)
    found = findings(Path(args.root))
    for item in found:
        print(f'private trace: {item}', file=sys.stderr)
    if found:
        print('Use repository-relative paths and neutral examples (example.com); see CONTRIBUTING.md.',
              file=sys.stderr)
        return 1
    print('No private traces in tracked files' +
          (f' (with {TERMS_FILE})' if (Path(args.root) / TERMS_FILE).is_file() else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
