#!/usr/bin/env python3
"""Point edits of workspace files: exactly one match, backup, size check.

State files are never rewritten wholesale. A replacement succeeds only when the
old fragment occurs exactly once; the previous content is copied to a backup
directory first, the new content is written atomically, and the resulting size
is compared with the expected size. Standard library only.

CLI:
  safe_edit.py FILE --old TEXT --new TEXT
  safe_edit.py FILE --old-file PATH --new-file PATH
  safe_edit.py FILE --create --new-file PATH      (refuses to overwrite)
"""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

BACKUP_DIR_NAME = '.orch-backup'


class EditError(Exception):
    """Raised when an edit would be ambiguous, destructive or unverifiable."""


def _backup_root(path: Path) -> Path:
    """Use the workspace backup directory when orch.yaml is found above the file."""
    for parent in [path.parent, *path.parent.parents]:
        if (parent / 'orch.yaml').is_file():
            return parent / BACKUP_DIR_NAME
    return path.parent / BACKUP_DIR_NAME


def backup(path: Path) -> Path:
    root = _backup_root(path)
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%S') + f'-{time.time_ns() % 1_000_000_000:09d}'
    target = root / f'{path.name}.{stamp}'
    shutil.copy2(path, target)
    return target


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def replace_once(path, old: str, new: str) -> None:
    """Replace the single occurrence of old with new, or raise EditError."""
    path = Path(path)
    if not path.is_file():
        raise EditError(f'file not found: {path}')
    if not old:
        raise EditError('old fragment must not be empty')
    original = path.read_bytes()
    old_b, new_b = old.encode('utf-8'), new.encode('utf-8')
    count = original.count(old_b)
    if count != 1:
        raise EditError(f'{path}: expected exactly one occurrence, found {count}')
    updated = original.replace(old_b, new_b, 1)
    expected = len(original) - len(old_b) + len(new_b)
    if len(updated) != expected:
        raise EditError(f'{path}: size mismatch before write')
    backup(path)
    _atomic_write(path, updated)
    actual = path.stat().st_size
    if actual != expected:
        raise EditError(f'{path}: size after write is {actual}, expected {expected}')


def create(path, content: str) -> None:
    """Create a new file; never overwrite an existing one."""
    path = Path(path)
    if path.exists():
        raise EditError(f'refusing to overwrite existing file: {path}')
    data = content.encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, data)
    umask = os.umask(0)
    os.umask(umask)
    path.chmod(0o666 & ~umask)
    if path.stat().st_size != len(data):
        raise EditError(f'{path}: size after write does not match content')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('file', type=Path)
    parser.add_argument('--old')
    parser.add_argument('--new')
    parser.add_argument('--old-file', type=Path)
    parser.add_argument('--new-file', type=Path)
    parser.add_argument('--create', action='store_true')
    args = parser.parse_args(argv)
    new = args.new_file.read_text(encoding='utf-8') if args.new_file else args.new
    if new is None:
        parser.error('--new or --new-file is required')
    try:
        if args.create:
            create(args.file, new)
        else:
            old = args.old_file.read_text(encoding='utf-8') if args.old_file else args.old
            if old is None:
                parser.error('--old or --old-file is required')
            replace_once(args.file, old, new)
    except EditError as error:
        print(f'safe_edit: {error}', file=sys.stderr)
        return 1
    print(f'safe_edit: ok {args.file}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
