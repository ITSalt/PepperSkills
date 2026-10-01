#!/usr/bin/env python3
"""Point edits of workspace files: exactly one match, backup, size check.

State files are never rewritten wholesale. A replacement succeeds only when the
old fragment occurs exactly once; the previous content is copied to a backup
directory first, the new content is written atomically, and the resulting size
is compared with the expected size. Standard library only.

CLI:
  safe_edit.py FILE --old TEXT --new TEXT
  safe_edit.py FILE --old-file PATH --new-file PATH
  safe_edit.py FILE --stdin                       (fragments on stdin, see below)
  safe_edit.py FILE --create --new-file PATH      (refuses to overwrite)
  safe_edit.py FILE --create --stdin              (whole stdin is the new file)

With --stdin the fragments come on stdin, so no temporary files are needed. One or more
blocks; each old fragment must occur exactly once (checked in order, on the text as edited by
the previous blocks); nothing is written unless every block applies:

  <<<<<<< OLD
  exact text to replace
  =======
  new text
  >>>>>>> NEW

Backups go to .orch-backup/ next to orch.yaml; ORCH_BACKUP_DIR overrides the place,
and when that directory cannot be written the system temporary directory is used.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from functools import wraps
import state_io

BACKUP_DIR_NAME = '.orch-backup'


class EditError(Exception):
    """Raised when an edit would be ambiguous, destructive or unverifiable."""


def _locked(func):
    @wraps(func)
    def run(path, *args, **kwargs):
        with state_io.transaction(state_io.root_for(path)):
            return func(path, *args, **kwargs)
    return run


def _backup_root(path: Path) -> Path:
    """Use the workspace backup directory when orch.yaml is found above the file."""
    for parent in [path.parent, *path.parent.parents]:
        if (parent / 'orch.yaml').is_file():
            return parent / BACKUP_DIR_NAME
    return path.parent / BACKUP_DIR_NAME


def backup(path: Path) -> Path:
    stamp = time.strftime('%Y%m%dT%H%M%S') + f'-{time.time_ns() % 1_000_000_000:09d}'
    override = os.environ.get('ORCH_BACKUP_DIR')
    roots = [Path(override)] if override else [_backup_root(path)]
    roots.append(Path(tempfile.gettempdir()) / 'orch-backup')
    for root in roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
            target = root / f'{path.name}.{stamp}'
            shutil.copy2(path, target)
            return target
        except OSError:
            continue
    raise EditError(f'{path}: no writable backup directory')


MARKERS = ('<<<<<<< OLD', '=======', '>>>>>>> NEW')
MARKER_LINE = re.compile(r'(?m)^(?:<<<<<<< |>>>>>>> |=======$)')


def parse_stdin_blocks(text):
    """Split one or more OLD/NEW blocks into [(old, new), ...]."""
    pairs, state, old, new = [], 'outside', [], []
    for number, line in enumerate(text.split('\n'), 1):
        if state == 'outside':
            if line == MARKERS[0]:
                state, old, new = 'old', [], []
            elif line.strip():
                raise EditError(f'stdin line {number}: text outside an OLD/NEW block')
        elif state == 'old':
            if line == MARKERS[1]:
                state = 'new'
            elif line in (MARKERS[0], MARKERS[2]):
                raise EditError(f'stdin line {number}: {line!r} inside the OLD part')
            else:
                old.append(line)
        else:
            if line == MARKERS[2]:
                pairs.append(('\n'.join(old), '\n'.join(new)))
                state = 'outside'
            elif line in (MARKERS[0], MARKERS[1]):
                raise EditError(f'stdin line {number}: {line!r} inside the NEW part')
            else:
                new.append(line)
    if state != 'outside':
        raise EditError('stdin ended inside an OLD/NEW block')
    if not pairs:
        raise EditError('stdin must hold blocks: <<<<<<< OLD / ======= / >>>>>>> NEW')
    return pairs


def parse_stdin_block(text):
    """Backward-compatible single block parser."""
    pairs = parse_stdin_blocks(text)
    if len(pairs) != 1:
        raise EditError(f'expected one OLD/NEW block, found {len(pairs)}')
    return pairs[0]


def _atomic_write(path: Path, data: bytes, create_only=False) -> None:
    state_io.record(path, data)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        if create_only:
            os.link(tmp, path)  # atomic create: refuses even a non-cooperating writer's file
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
        state_io.fsync_directory(path.parent)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@_locked
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
    if not updated.strip():
        raise EditError(f'{path}: refusing to leave the file empty or whitespace-only')
    expected = len(original) - len(old_b) + len(new_b)
    if len(updated) != expected:
        raise EditError(f'{path}: size mismatch before write')
    backup(path)
    _atomic_write(path, updated)
    actual = path.stat().st_size
    if actual != expected:
        raise EditError(f'{path}: size after write is {actual}, expected {expected}')


@_locked
def replace_many(path, pairs) -> None:
    """Apply several exactly-once replacements atomically: all of them or none."""
    path = Path(path)
    if not path.is_file():
        raise EditError(f'file not found: {path}')
    original = path.read_bytes()
    text = original.decode('utf-8')
    for index, (old, new) in enumerate(pairs, 1):
        if not old:
            raise EditError(f'block {index}: old fragment must not be empty')
        if MARKER_LINE.search(new) or MARKER_LINE.search(old):
            raise EditError(f'block {index}: conflict-style marker line inside a fragment')
        count = text.count(old)
        if count != 1:
            raise EditError(f'{path}: block {index}: expected exactly one occurrence, found {count}')
        text = text.replace(old, new, 1)
    updated = text.encode('utf-8')
    if not updated.strip():
        raise EditError(f'{path}: refusing to leave the file empty or whitespace-only')
    backup(path)
    _atomic_write(path, updated)
    if path.stat().st_size != len(updated):
        raise EditError(f'{path}: size after write is {path.stat().st_size}, expected {len(updated)}')


@_locked
def create(path, content: str) -> None:
    """Create a new file; never overwrite an existing one."""
    path = Path(path)
    if path.exists():
        raise EditError(f'refusing to overwrite existing file: {path}')
    data = content.encode('utf-8')
    if not data.strip():
        raise EditError(f'refusing to create an empty or whitespace-only file: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, data, create_only=True)
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
    parser.add_argument('--stdin', action='store_true', help='read fragments from stdin')
    args = parser.parse_args(argv)
    try:
        if args.stdin:
            data = sys.stdin.read()
            if args.create:
                create(args.file, data)
            else:
                replace_many(args.file, parse_stdin_blocks(data))
            print(f'safe_edit: ok {args.file}')
            return 0
        new = args.new_file.read_text(encoding='utf-8') if args.new_file else args.new
        if new is None:
            parser.error('--new, --new-file or --stdin is required')
        if args.create:
            create(args.file, new)
        else:
            old = args.old_file.read_text(encoding='utf-8') if args.old_file else args.old
            if old is None:
                parser.error('--old or --old-file is required')
            replace_once(args.file, old, new)
    except (EditError, state_io.StateError) as error:
        print(f'safe_edit: {error}', file=sys.stderr)
        return 1
    print(f'safe_edit: ok {args.file}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
