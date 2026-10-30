"""Claude Code adapter for opt-in local autonomy.

Observation is model-free: `claude agents --json` lists live local sessions with
their PID, session ID, cwd and busy/idle/waiting status. Delivery is not a CLI
operation: the coordinator model sends TASK with its SendMessage tool and records
the tool result. Nothing here sends messages, compacts or launches sessions.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import state_io
import streams

# Cross-session messaging (2.1.224) plus notify_when_idle (2.1.236); 2.1.234 on native Windows.
MIN_VERSION = (2, 1, 236)
WAITING_FLAGS = {'permission prompt': 'waitingOnApproval', 'sandbox request': 'waitingOnApproval',
                 'input needed': 'waitingOnUserInput', 'dialog open': 'waitingOnUserInput',
                 'worker request': 'waitingOnUserInput'}


class ClaudeError(streams.StreamError):
    pass


def command():
    found = shutil.which('claude')
    if not found:
        raise ClaudeError('Claude Code CLI is not on PATH')
    return [found]


def version():
    try:
        r = subprocess.run([*command(), '--version'], capture_output=True, text=True, encoding='utf-8', timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClaudeError(f'claude --version failed: {error}') from error
    found = re.search(r'(\d+)\.(\d+)\.(\d+)', r.stdout)
    if r.returncode or not found:
        raise ClaudeError('cannot read the Claude Code version')
    return tuple(int(x) for x in found.groups())


def capabilities():
    current = version()
    if current < MIN_VERSION:
        raise ClaudeError('Claude Code ' + '.'.join(map(str, MIN_VERSION)) + '+ is required for cross-session '
                          'autonomy; found ' + '.'.join(map(str, current)))
    agents()  # Observation must work before any autonomy write.
    return {'available': True, 'version': '.'.join(map(str, current)), 'observation': 'claude agents --json',
            'delivery': 'coordinator SendMessage tool'}


def agents():
    """Live local sessions. Errors are never treated as an empty list."""
    try:
        r = subprocess.run([*command(), 'agents', '--json'], capture_output=True, text=True, encoding='utf-8',
                           timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClaudeError(f'claude agents --json failed: {error}') from error
    if r.returncode:
        raise ClaudeError('claude agents --json failed: ' + (r.stderr.strip() or str(r.returncode)))
    try:
        rows = json.loads(r.stdout)
    except ValueError as error:
        raise ClaudeError('claude agents --json returned invalid JSON') from error
    if not isinstance(rows, list):
        raise ClaudeError('claude agents --json returned an unexpected shape')
    return [row for row in rows if isinstance(row, dict) and row.get('sessionId')]


def normalize(row):
    """Map a live row to the thread shape shared with the Codex core.

    `waiting` (approval, input, held peer message) is busy, never idle.
    Model and effort are not observable from outside the session.
    """
    status = row.get('status')
    if status == 'idle':
        state = {'type': 'idle', 'activeFlags': []}
    elif status == 'busy':
        state = {'type': 'active', 'activeFlags': []}
    elif status == 'waiting':
        waiting = row.get('waitingFor') or 'unknown'
        state = {'type': 'active', 'activeFlags': [WAITING_FLAGS.get(waiting, 'waiting:' + waiting)]}
    else:
        state = {'type': 'systemError', 'activeFlags': ['unknown status ' + str(status)]}
    return {'id': row['sessionId'], 'createdAt': row.get('startedAt'), 'cwd': row.get('cwd'),
            'pid': row.get('pid'), 'name': row.get('name'), 'kind': row.get('kind'),
            'model': None, 'reasoningEffort': None, 'status': state, 'turns': []}


def read_session(session_id, rows=None):
    rows = agents() if rows is None else rows
    found = [row for row in rows if row.get('sessionId') == session_id]
    if len(found) > 1:
        raise ClaudeError('several live processes report one session ID; reconcile before autonomy')
    if not found:
        return {'id': session_id, 'createdAt': None, 'cwd': None, 'pid': None, 'name': None,
                'model': None, 'reasoningEffort': None, 'status': {'type': 'notLoaded', 'activeFlags': []}, 'turns': []}
    return normalize(found[0])


def recipient(session_id, name):
    """SendMessage addresses a name. It must resolve to exactly this live session."""
    rows = agents()
    named = [row for row in rows if row.get('name') == name]
    if len(named) != 1 or named[0].get('sessionId') != session_id:
        raise ClaudeError(f'session name {name!r} does not resolve to exactly the attached session; '
                          'rename the module session (/rename) and reattach')
    return normalize(named[0])


def settings_path(root, name):
    import session_settings
    return session_settings.settings_path(root, name)


def config_files(ws, module_id, directory):
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')))
    return [home / 'settings.json', Path(directory) / '.claude/settings.json',
            Path(directory) / '.claude/settings.local.json', Path(directory) / '.mcp.json',
            settings_path(ws.root, module_id)]


SKILL_ROOT = Path(__file__).resolve().parent.parent

# Changes of these tracked paths in a new base can change permissions, hooks, agents,
# commands or MCP servers of the session: owner preparation and reconfirmation first.
NATIVE_CONFIG = ('.claude', '.mcp.json')


def settings_current(ws, module):
    import session_settings
    cache = ws.__dict__.setdefault('_claude_settings_current', {})  # one render per module per plan
    if module.id not in cache:
        path = settings_path(ws.root, module.id)
        expected, _ = session_settings.module_settings(ws.config, ws.root, module, ws.in_repo, SKILL_ROOT)
        cache[module.id] = path.is_file() and path.read_text(encoding='utf-8') == session_settings.render(expected)
    return cache[module.id]


def launch(ws, module, wp, meta):
    import runtime_commands
    return runtime_commands.api().claude_start_command(ws, module, wp, warn=False)


def prepare_reuse(ws, wp, directory):
    """Module-owned environment setup in the reused worktree; settings stay as launched."""
    import runtime_commands
    return runtime_commands.reuse_setup(ws, wp, directory)


def compaction_path(root, session_id):
    import autonomy
    if not re.fullmatch(r'[0-9A-Za-z-]{8,64}', str(session_id)):
        raise ClaudeError('invalid session ID')
    return state_io.runtime_dir() / 'compactions' / autonomy.digest(str(Path(root).resolve())) / (session_id + '.json')


def record_compaction(root, payload):
    """PostCompact hook: a technical runtime receipt, never a coordinator document."""
    if payload.get('hook_event_name') != 'PostCompact' or not payload.get('session_id'):
        return None
    path = compaction_path(root, payload['session_id'])
    receipt = {'session_id': payload['session_id'], 'cwd': payload.get('cwd'),
               'trigger': payload.get('trigger'), 'at': time.time()}
    state_io.atomic(path, (json.dumps(receipt) + '\n').encode())
    return receipt


def read_compaction(root, session_id):
    path = compaction_path(root, session_id)
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    except (OSError, ValueError):
        return None

