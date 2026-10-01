"""Synchronize only explicitly prepared shared blocks; preserve all other text."""
import difflib
import json
from pathlib import Path

import safe_edit
import state_io

START = '<!-- pepper:shared:start -->'
END = '<!-- pepper:shared:end -->'


class InstructionError(RuntimeError):
    pass


def paths(root):
    root = Path(root).resolve()
    result = []
    for name in ('CLAUDE.md', 'AGENTS.md'):
        matches = [p for p in root.iterdir() if p.name.lower() == name.lower()]
        if len(matches) > 1:
            raise InstructionError(f'ambiguous case variants of {name}: {matches}')
        result.append(matches[0] if matches else root / name)
    return result


def block(text):
    if START not in text and END not in text:
        return None
    if text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
        raise InstructionError('shared markers must occur exactly once, in order')
    return text[text.index(START) + len(START):text.index(END)].strip('\n')


def status(root):
    result = []
    shared = []
    for p in paths(root):
        text = p.read_text(encoding='utf-8') if p.exists() else ''
        value = block(text)
        result.append({'path': str(p), 'sha256': state_io.digest(p), 'managed': value is not None})
        shared.append(value)
    return {'files': result, 'synchronized': shared[0] is not None and shared[0] == shared[1]}


def check_tree(root):
    root = Path(root).resolve()
    parents = {root}
    for p in root.rglob('*'):
        if p.name.lower() in ('claude.md', 'agents.md') and not any(
                part in ('.git', 'node_modules', '.claude', '.codex') for part in p.relative_to(root).parts[:-1]):
            parents.add(p.parent)
    return [status(p) for p in sorted(parents)]


def sync(root, shared, expected_claude, expected_agents, apply=False):
    if START in shared or END in shared:
        raise InstructionError('shared input must not contain markers')
    shared = shared.strip('\n')
    if not shared.strip():
        raise InstructionError('shared instructions must not be empty')
    ps = paths(root)
    with state_io.transaction(state_io.root_for(ps[0])):
        for p, expected in zip(ps, (expected_claude, expected_agents)):
            if state_io.digest(p) != expected:
                raise InstructionError(f'changed since preparation: {p}; inspect and prepare again')
            if p.is_symlink():
                raise InstructionError(f'preserve symlink {p}; synchronize its target explicitly')
        edits, diffs = [], []
        for p in ps:
            old = p.read_bytes().decode('utf-8') if p.exists() else ''
            current = block(old)
            replacement = START + '\n' + shared + '\n' + END
            if current is None:
                new = old + ('\n' if old.endswith('\n') else '\n\n' if old else '') + replacement + '\n'
            else:
                segment = old[old.index(START):old.index(END) + len(END)]
                new = old.replace(segment, replacement, 1)
            edits.append((p, old, new))
            diffs.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                             fromfile=str(p), tofile=str(p)))
        if apply:
            for p, old, new in edits:
                if new != old:
                    if p.exists():
                        safe_edit.replace_once(p, old, new) if old else _fill_empty(p, new)
                    else:
                        safe_edit.create(p, new)
        return {'applied': apply, 'diff': ''.join(diffs), 'files': [str(p) for p in ps]}


def _fill_empty(path, text):
    safe_edit.backup(path)
    safe_edit._atomic_write(path, text.encode())


GUIDANCE = '''Before implementing, read both CLAUDE.md and AGENTS.md (including existing case variants)
and the applicable nested instruction files. Preserve all existing client-specific text.
If one file is missing or shared blocks differ, prepare confirmed common project rules and
use orch.py instructions status/sync with both expected hashes. Update both shared blocks
when a common rule changes. Do not decide contradictory existing instructions yourself:
send QUESTION with the conflict. Run orch.py instructions check --repo . before READY.
Only the module session edits its repository's instructions; the coordinator never does.
'''
