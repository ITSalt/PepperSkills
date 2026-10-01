#!/usr/bin/env python3
"""Workspace CLI for the single-orchestrator (hub-and-spoke) method.

Keeps program state in plain Markdown files: status.md (work packages, owner
queue, journal) and decisions.md. Every edit of an existing file goes through
safe_edit.replace_once: exactly one match, backup, size check. Standard library
plus git only, so the core runs on any agent stack.

Commands:
  init <program>                         create the workspace and orch.yaml
  new-wp <MOD> <slug>                    new work package file + status row
  set <WP> <column> <text>               edit one cell of a WP row
  journal "<event>"                      add a journal line on top
  owner add R|P "<text>"                 add an owner action or question
  owner close|drop <id> "<fact>"         close with a verified fact / drop
  queue                                  list open owner items
  decide D|A|Q "<text>"                  append a decision/assumption/question
  lint                                   workspace integrity checks
  commit "<message>"                     lint, commit the workspace, push if set
  dispatch <WP>                          checks, locks, start command, DISPATCHING
  overlap                                declared and actual path overlaps, repo checks
  lock acquire|release|list              locks on shared paths and resources
  merge add|done|list                    merge queue per repository
  worktrees                              worktrees of every repository (read-only)
  upgrade                                add 0.2.0 tables to a 0.1.0 status.md
  ready                                  pushed branches of dispatched packages (READY without messages)
  review-start <WP>                      automatic review findings, report skeleton, clone command
  model <WP> <model> --reason "..."      implementer model and effort of a package
  owner carry <id> "<reason>"            move an open owner item to backlog.md
  close --check | --apply                completion check; closeout report, state: closed
  reopen "<reason>"                      make a closed program active again
  settings <module|all|orchestrator>     Claude Code settings files of the sessions (--settings)
  verify <WP> --env test|prod            deploy run, served version, verify commands; report, status
  report --check | --apply | --status    anonymized report of a plugin defect; Issue after the owner's yes
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import safe_edit  # noqa: E402
import session_settings  # noqa: E402
import plugin_report  # noqa: E402
import streams  # noqa: E402
import verification  # noqa: E402
import state_io  # noqa: E402
import id_allocator  # noqa: E402
import project_instructions  # noqa: E402
import codex_adapter  # noqa: E402
import codex_transport  # noqa: E402
import runtime_commands  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / 'templates'
LANGUAGES = ('en', 'ru')

STATUSES = ('DRAFT', 'READY', 'DISPATCHING', 'IN_PROGRESS', 'REVIEW', 'REVISE', 'ACCEPTED',
            'MERGED', 'TEST-APPLIED', 'DEPLOYED_TEST', 'VERIFYING', 'VERIFIED_TEST', 'PROD', 'DONE')
REASON_STATUSES = ('BLOCKED', 'CANCELLED')

# Machine markers: tables are located by these comments, never by localized headings.
TABLES = {
    'wp': ('<!-- orch:wp -->', ('wp', 'module', 'title', 'status', 'session', 'pr', 'updated')),
    'owner': ('<!-- orch:owner -->', ('id', 'text', 'where', 'opened', 'closed')),
    'journal': ('<!-- orch:journal -->', ('date', 'wp', 'event', 'evidence')),
    'decisions': ('<!-- orch:decisions -->', ('id', 'date', 'text', 'source')),
    'locks': ('<!-- orch:locks -->', ('lock', 'repo', 'holder', 'since', 'waiting', 'note')),
    'merge': ('<!-- orch:merge -->', ('n', 'repo', 'wp', 'pr', 'rebase_after', 'status')),
    'backlog': ('<!-- orch:backlog -->', ('id', 'date', 'item', 'origin', 'reason')),
}
SETTABLE = ('title', 'status', 'session', 'pr')

SECRET_PATTERNS = [
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{40,}'),
    re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),
    re.compile(r'\b[a-z][a-z0-9+.-]*://[^/\s:@<>]+:[^/\s@<>]+@'),
    re.compile(r'(?i)(?<![A-Za-z0-9])[A-Za-z_]*(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*'
               r'[\'"]?(?![<$({])[^\s\'"`<>{}|]{8,}'),
]


class OrchError(Exception):
    pass


# ---------------------------------------------------------------- YAML subset

def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in '\'"':
            quote = ch
        elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
            return line[:i].rstrip()
    return line.rstrip()


def _split_flow(text):
    items, depth, quote, current = [], 0, None, ''
    for ch in text:
        if quote:
            current += ch
            if ch == quote:
                quote = None
            continue
        if ch in '\'"':
            quote = ch
        elif ch in '[{':
            depth += 1
        elif ch in ']}':
            depth -= 1
        elif ch == ',' and depth == 0:
            items.append(current.strip())
            current = ''
            continue
        current += ch
    if current.strip():
        items.append(current.strip())
    return items


def _split_key(text):
    """Split 'key: value' outside quotes; return None when there is no key."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in '\'"':
            quote = ch
        elif ch == ':' and (i + 1 == len(text) or text[i + 1] == ' '):
            return text[:i].strip().strip('\'"'), text[i + 1:].strip()
    return None


def _scalar(text):
    text = text.strip()
    if text.startswith('[') and text.endswith(']'):
        return [_scalar(item) for item in _split_flow(text[1:-1])]
    if text.startswith('{') and text.endswith('}'):
        result = {}
        for item in _split_flow(text[1:-1]):
            pair = _split_key(item)
            if pair is None:
                raise OrchError(f'orch.yaml: invalid flow mapping item: {item}')
            result[pair[0]] = _scalar(pair[1])
        return result
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            return json.loads(text)
        except ValueError:
            return text[1:-1]
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text in ('', '~', 'null'):
        return None
    if text in ('true', 'false'):
        return text == 'true'
    if re.fullmatch(r'-?\d+', text):
        return int(text)
    return text


def parse_yaml(source):
    """Parse the orch.yaml subset: block maps/lists, flow lists/maps, scalars."""
    lines = []
    for number, raw in enumerate(source.splitlines(), 1):
        if '\t' in raw[:len(raw) - len(raw.lstrip())]:
            raise OrchError(f'orch.yaml:{number}: tabs are not allowed for indentation')
        content = _strip_comment(raw)
        if content.strip():
            lines.append((len(content) - len(content.lstrip(' ')), content.strip(), number))

    def block(i, indent):
        if i >= len(lines):
            return None, i
        if lines[i][1].startswith('- ') or lines[i][1] == '-':
            return seq(i, lines[i][0])
        return mapping(i, lines[i][0])

    def mapping(i, indent):
        result = {}
        while i < len(lines) and lines[i][0] == indent:
            _, text, number = lines[i]
            pair = _split_key(text)
            if pair is None or text.startswith('- '):
                raise OrchError(f'orch.yaml:{number}: expected "key: value"')
            key, value = pair
            i += 1
            if value:
                result[key] = _scalar(value)
            elif i < len(lines) and (lines[i][0] > indent or
                                     (lines[i][0] == indent and lines[i][1].startswith('- '))):
                result[key], i = block(i, lines[i][0])
            else:
                result[key] = None
        if i < len(lines) and lines[i][0] > indent:
            raise OrchError(f'orch.yaml:{lines[i][2]}: unexpected indentation')
        return result, i

    def seq(i, indent):
        result = []
        while i < len(lines) and lines[i][0] == indent and (
                lines[i][1].startswith('- ') or lines[i][1] == '-'):
            _, text, number = lines[i]
            rest = text[1:].strip()
            if not rest:
                value, i = block(i + 1, indent + 2)
                result.append(value)
                continue
            pair = _split_key(rest) if not rest.startswith(('[', '{', '"', "'")) else None
            if pair is None:
                result.append(_scalar(rest))
                i += 1
                continue
            # "- key: value" opens a mapping whose other keys sit at indent + 2.
            item_indent = indent + 2
            lines[i] = (item_indent, rest, number)
            value, i = mapping(i, item_indent)
            result.append(value)
        return result, i

    if not lines:
        return {}
    value, i = block(0, lines[0][0])
    if i != len(lines):
        raise OrchError(f'orch.yaml:{lines[i][2]}: could not parse')
    if not isinstance(value, dict):
        raise OrchError('orch.yaml: top level must be a mapping')
    return value


# ---------------------------------------------------------------- workspace

def today():
    """Calendar date in UTC, the same zone as the journal."""
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%MZ')


def cell(text):
    """One table cell: single line, escaped pipes, no machine marker lookalikes."""
    text = ' '.join(str(text).split()).replace('|', '\\|').replace('<!--', '&lt;!--')
    return text or '—'


def row(values):
    return '| ' + ' | '.join(cell(v) for v in values) + ' |'


def split_row(line):
    parts = re.split(r'(?<!\\)\|', line.strip())
    if len(parts) < 3 or parts[0].strip() or parts[-1].strip():
        return None
    return [p.strip() for p in parts[1:-1]]


def find_nested_configs(cwd, depth=4):
    """orch.yaml files up to depth levels below cwd (in-repo workspaces such as docs/orchestration/x)."""
    found = []
    for dirpath, dirnames, filenames in os.walk(cwd):
        rel = Path(dirpath).relative_to(cwd)
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != 'node_modules'
                       and len(rel.parts) < depth]
        if 'orch.yaml' in filenames and rel.parts:
            found.append(Path(dirpath) / 'orch.yaml')
    return sorted(found)


def find_workspace(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not (path / 'orch.yaml').is_file():
            raise OrchError(f'no orch.yaml in {path}')
        return path
    env = os.environ.get('ORCH_WORKSPACE')
    if env:
        return find_workspace(env)
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / 'orch.yaml').is_file():
            return parent
    candidates = sorted(cwd.glob('features/*/orch.yaml')) or find_nested_configs(cwd)
    if len(candidates) > 1:  # closed programs are never picked automatically among several
        active = [c for c in candidates if parse_yaml(c.read_text(encoding='utf-8')).get('state') != 'closed']
        candidates = active or candidates
    if len(candidates) == 1:
        return candidates[0].parent
    if candidates:
        names = ', '.join(str(c.parent.relative_to(cwd)) for c in candidates)
        raise OrchError(f'several workspaces found ({names}); pass --workspace')
    raise OrchError('workspace not found: run inside it, set ORCH_WORKSPACE or pass --workspace')


class Workspace:
    def __init__(self, root):
        self.root = Path(root)
        self.config = parse_yaml((self.root / 'orch.yaml').read_text(encoding='utf-8'))
        self.status = self.root / 'status.md'
        self.decisions = self.root / 'decisions.md'
        self.wp_dir = self.root / 'work-packages'

    @property
    def tag(self):
        return str(self.config.get('tag') or self.config.get('program', 'ORCH')).upper()

    def modules(self):
        modules = self.config.get('modules') or []
        return {str(m.get('id')).lower(): m for m in modules if isinstance(m, dict)}

    def streams(self):
        """(repos, modules, errors) with the 0.1.0 form mapped to implicit repositories.

        Resolved once per Workspace so that Repo objects compare by identity."""
        if not hasattr(self, '_streams'):
            self._streams = streams.resolve(self.config, base_dir=self.git_top)
        return self._streams[:3]

    def stream_warnings(self):
        self.streams()
        return self._streams[3]

    @property
    def closed(self):
        return self.config.get('state') == 'closed'

    def require_open(self, action):
        if self.closed:
            raise OrchError(f'program {self.config.get("program")} is closed: {action} is not allowed. A new goal is '
                            'a new program (init); to continue this one, reopen "<reason>"')

    @property
    def git_top(self):
        if not hasattr(self, '_git_top'):
            self._git_top = streams.git_toplevel(self.root) or self.root.resolve()
        return self._git_top

    @property
    def in_repo(self):
        return self.config.get('workspace_mode') == 'in-repo'

    @property
    def workspace_branch(self):
        return str(self.config.get('workspace_branch') or f'orch/{self.config.get("program", "program")}')

    @property
    def lang(self):
        lang = self.config.get('owner_language')
        return lang if lang in LANGUAGES else 'en'

    @property
    def coordinator(self):
        program = self.config.get('program', 'program')
        return self.config.get('coordinator_session') or f'{program}-coord'

    def has_table(self, path, name):
        return path.is_file() and TABLES[name][0] in path.read_text(encoding='utf-8')

    def wp_rows(self):
        return {plain_id(r['wp']): r for r in self.table(self.status, 'wp')[2]}

    def wp_path(self, row_value):
        link = re.match(r'^\[[^\]]+\]\(([^)]+)\)$', row_value)
        return self.root / link.group(1) if link else None

    # -- tables

    def table(self, path, name):
        """Return (block_text, header_cells, rows) for the marked table in path."""
        marker, columns = TABLES[name]
        text = path.read_text(encoding='utf-8')
        if text.count(marker) != 1:
            raise OrchError(f'{path.name}: expected exactly one {marker}')
        start = text.index(marker)
        lines = text[start:].split('\n')
        block = [lines[0]]
        for line in lines[1:]:
            if line.startswith('|'):
                block.append(line)
            else:
                break
        if len(block) < 3:
            raise OrchError(f'{path.name}: table after {marker} needs a header and separator')
        header = split_row(block[1])
        if header is None or len(header) != len(columns):
            raise OrchError(f'{path.name}: table {name} must have {len(columns)} columns')
        rows = []
        for line in block[3:]:
            cells = split_row(line)
            if cells is None or len(cells) != len(columns):
                raise OrchError(f'{path.name}: malformed row in table {name}: {line}')
            rows.append(dict(zip(columns, cells)))
        return '\n'.join(block), header, rows

    def rewrite_table(self, path, name, transform):
        with state_io.transaction(self.root):
            block, _, _ = self.table(path, name)
            lines = block.split('\n')
            head, body = lines[:3], lines[3:]
            new_body = transform(body)
            safe_edit.replace_once(path, block, '\n'.join(head + new_body))

    def journal(self, event, wp='—', evidence='—'):
        line = row([now_utc(), wp, event, evidence])
        self.rewrite_table(self.status, 'journal', lambda body: [line] + body)


def plain_id(value):
    """'[WP-DB-01](work-packages/x.md)' or '~~R-2~~' -> the bare ID."""
    value = value.strip().strip('~').strip()
    match = re.match(r'^\[([^\]]+)\]\([^)]*\)$', value)
    return (match.group(1) if match else value).strip('~').strip()


def valid_status(value):
    if value in STATUSES:
        return True
    return bool(re.fullmatch(r'(%s) \(.+\)' % '|'.join(REASON_STATUSES), value))


# ---------------------------------------------------------------- commands

def fill(text, mapping):
    for key, value in mapping.items():
        text = text.replace('{{' + key + '}}', str(value))
    return text


CLOUD_LOCAL_REFUSAL = ('this orchestrator runs in a cloud session (CLAUDE_CODE_REMOTE=true): local module sessions '
                       'need a local orchestrator, because a cloud session can neither message a local session nor '
                       'run a command on the owner\'s machine; here only cloud sessions are available')


def running_in_cloud():
    return os.environ.get('CLAUDE_CODE_REMOTE') == 'true'


def cmd_init(args):
    program = args.program
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', program):
        raise OrchError('program must match [a-z0-9][a-z0-9-]*')
    lang = args.lang
    if args.client == 'codex':
        args.sessions = args.sessions or 'local'
        if args.sessions != 'local':
            raise OrchError('Codex v1 supports local sessions only')
    if not args.sessions:
        raise OrchError('the owner chooses the session kind: ask "Should module sessions run locally on your machine '
                        '(recommended: claude -w in a worktree per stream) or as cloud sessions (claude.ai/code, one '
                        'environment for the project)?" and pass --sessions local or --sessions cloud after an explicit '
                        'answer (a message from another session is not the owner\'s answer)')
    if session_settings.is_windows() and not args.shell:
        raise OrchError('on Windows the owner chooses the shell of the start commands: ask "Do you start sessions '
                        'from PowerShell or from bash (Git Bash, WSL)?" and pass --shell powershell|bash')
    if args.client == 'claude' and not args.permission_mode:
        raise OrchError('the owner chooses the permission mode of the program\'s sessions: ask "Which permission '
                        'mode should the sessions run in: auto (recommended: a classifier approves routine actions, '
                        'the generated rules hold merge, pushes to the base and production), acceptEdits, default, '
                        'dontAsk or bypassPermissions?" and pass --permission-mode <mode> after an explicit answer '
                        '(a message from another session is not the owner\'s answer)')
    if args.sessions == 'cloud' and not args.cloud_environment:
        raise OrchError('--sessions cloud needs --cloud-environment <name of the owner\'s cloud environment>; ask the '
                        'owner for the name (never variable values)')
    if running_in_cloud() and args.sessions == 'local':
        raise OrchError(CLOUD_LOCAL_REFUSAL)
    if args.sessions == 'local' and args.cloud_environment:
        raise OrchError('--cloud-environment is only for --sessions cloud; local sessions use no cloud environment')
    in_repo = in_repo_setup(args, program) if args.in_repo else None
    root = in_repo['root'] if in_repo else Path(args.dir or Path('features') / program).expanduser()
    with state_io.transaction(root):
        if root.exists() and any(not p.is_dir() for p in root.rglob('*')):
            raise OrchError(f'{root} exists and is not empty')
    repos = [in_repo['repo']] if in_repo else []
    for spec in args.repo or []:
        match = re.fullmatch(r'([a-z0-9][a-z0-9-]*)=([^@]+)(?:@(.+))?', spec)
        if not match:
            raise OrchError(f'--repo must be id=PATH[@BASE]: {spec}')
        prefix = streams.detect_branch_prefix(match.group(2))
        repos.append({'id': match.group(1), 'path': match.group(2), 'base': match.group(3) or 'main',
                      'branch_prefix': prefix, 'detected': prefix is not None})
    repo_ids = {r['id'] for r in repos}
    areas = []
    for kind, specs in (('area', args.area or []), ('domain', args.domain or [])):
        for spec in specs:
            match = re.fullmatch(r'([a-z0-9][a-z0-9-]*)=([a-z0-9][a-z0-9-]*):(.+)', spec)
            if not match or match.group(2) not in repo_ids:
                raise OrchError(f'--{kind} must be id=REPO_ID:GLOB[,GLOB...] with a --repo id: {spec}')
            areas.append({'id': match.group(1), 'kind': kind, 'repo': match.group(2),
                          'paths': streams.split_top(match.group(3)),
                          'session': f'{program}-{match.group(1)}'})
    parent = root.resolve().parent
    while not parent.exists():
        parent = parent.parent
    top = streams.git_toplevel(parent)
    conflict = streams.module_repo_conflict(
        parent, [streams.Repo(r, program=program, base_dir=top) for r in repos] +
        [streams.Repo({'id': m, 'path': spec.split('=', 1)[1].split('@')[0]}, program=program)
         for spec in args.module or [] for m in [spec.split('=', 1)[0]] if '=' in spec])
    if conflict:
        raise OrchError(conflict)
    for a in areas:
        for pattern in a['paths']:
            try:
                streams.expand_braces(pattern)
            except streams.StreamError as error:
                raise OrchError(f'--{a["kind"]} {a["id"]}: {error}')
    tag = (args.tag or program.split('-')[0]).upper()
    title = args.title or program
    base = {'PROGRAM': program, 'PROGRAM_TITLE': title, 'TAG': tag, 'LANG': lang,
            'COORDINATOR': f'{program}-coord', 'DATE': today(),
            'WORKSPACE': str(root.resolve()), 'PERMISSION_MODE': args.permission_mode}
    modules = []
    for spec in args.module or []:
        match = re.fullmatch(r'([a-z0-9][a-z0-9-]*)=([^@]+)(?:@(.+))?', spec)
        if not match:
            raise OrchError(f'--module must be id=REPO[@BASE]: {spec}')
        modules.append({'id': match.group(1), 'repo': match.group(2),
                        'base': match.group(3) or 'main', 'session': f'{program}-{match.group(1)}'})
    source = TEMPLATES / lang
    files = {
        'README.md': source / 'README.md',
        'PLAN.md': source / 'PLAN.md',
        'status.md': source / 'status.md',
        'decisions.md': source / 'decisions.md',
        'orchestration/protocol.md': source / 'protocol.md',
        'work-packages/_TEMPLATE.md': source / 'work-package.md',
        'bugs/_TEMPLATE.md': source / 'bug.md',
        'orchestration/bootstrap-prompt.md': source / 'bootstrap-prompt.md',
    }
    module_rows = '\n'.join([row([m['id'], m['repo'], m['base'], m['session']]) for m in modules] +
                            [row([a['id'], a['repo'] + ' (' + a['kind'] + ')',
                                  ', '.join(a['paths']), a['session']]) for a in areas])
    with state_io.transaction(root):
        if root.exists() and any(not p.is_dir() for p in root.rglob('*')):
            raise OrchError(f'{root} became nonempty during init; retry')
        for rel, template in files.items():
            text = template.read_text(encoding='utf-8')
            text = text.replace('{{MODULE_ROWS}}\n', module_rows + '\n' if module_rows else '')
            text = fill(text, base)
            if args.client == 'codex' and rel == 'orchestration/bootstrap-prompt.md':
                text = ('# Codex coordinator bootstrap\n\nRead README.md, PLAN.md, orch.yaml, status.md, '
                        'decisions.md and protocol.md. Use the Codex adapter. Coordinate independent '
                        'owner-launched module sessions; delegate only research/review/verification. '
                        'Run orch.py settings all and use its generated Codex start command.\n')
            safe_edit.create(root / rel, text)
        config_text = render_config(base, modules, repos, areas, in_repo, args.sessions, args.cloud_environment)
        if args.client == 'codex':
            config_text = 'client: codex\ncodex:\n  approval_policy: on-request\n  sandbox_mode: workspace-write\n' + config_text
            config_text = re.sub(r'(?m)^permission_mode: .*\n', '', config_text)
            config_text = config_text.replace('branch_prefix: ' + program + '/', 'branch_prefix: codex/')
        if args.sessions == 'local':
            scope = id_allocator.new_scope()
            id_allocator.register(scope, {})
            config_text += '\nnumbering:\n  scope: ' + scope + '\n  version: 1\n'
        if args.shell and args.shell != 'bash':
            if args.client == 'claude':
                config_text = config_text.replace('\npermission_mode: ', f'\nshell: {args.shell}\npermission_mode: ', 1)
            else:
                config_text = config_text.replace('client: codex\n', f'client: codex\nshell: {args.shell}\n', 1)
        safe_edit.create(root / 'orch.yaml', config_text)
        safe_edit.create(root / '.gitignore', safe_edit.BACKUP_DIR_NAME + '/\n' +
                         session_settings.SETTINGS_DIR + '/*.local.json\n')
        ws = Workspace(root)
        ws.journal(f'workspace created ({lang})', evidence='orch.py init')
        ws.journal(f'session kind: {args.sessions}' + (f', environment {args.cloud_environment}' if args.cloud_environment
                                                       else '') + ', confirmed by the owner', evidence='orch.py init')
        if args.client == 'claude':
            ws.journal(f'permission mode: {args.permission_mode}, confirmed by the owner', evidence='orch.py init')
        else:
            ws.journal('client Codex; local launch policy defaults in orch.yaml', evidence='orch.py init --client codex')
        print(f'workspace: {root}')
        for line in write_settings(ws, 'all'):
            print(line)
        for proposal in worktreeinclude_proposals(ws):
            cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='P', text=proposal,
                                         where='orch.py init', quiet=True))
            print(f'owner question: {proposal}')
    if not running_in_cloud():
        print(orchestrator_start(ws))
    if in_repo and in_repo['override']:
        ws.journal(f'deploy check overridden by {in_repo["override"]}', evidence='orch.py init --in-repo')
    if in_repo:
        print(f'in-repo workspace on branch {in_repo["branch"]}, directory {in_repo["dir"]}')
        for note in in_repo['notes']:
            print(f'deploy check: {note}')
    for warning in lint_warnings(ws):
        print(f'warning: {warning}')
    for r in repos:
        if not r['detected']:
            print(f'note: repo {r["id"]}: branch_prefix not found in the repository convention; '
                  f'set to {program}/ - confirm with the owner')
    return 0


def orchestrator_start(ws):
    """Start command of the orchestrator session with its settings file, and the /config alternative."""
    if ws.config.get('client') == 'codex':
        import shlex
        return 'orchestrator start command:\n' + codex_adapter.shell_join([
            'codex', '--cd', str(ws.root.resolve()), *codex_adapter.read_flags(ws, 'orchestrator'),
            'Use Pepper Orchestrator in this program. Read status.md, orch.yaml and both project instruction files. '
            'Coordinate module sessions; do not edit their code. Check session capabilities before sending tasks.'], ws.config.get('shell'))
    mode = ws.config.get('permission_mode')
    rel = f'{session_settings.SETTINGS_DIR}/{session_settings.ORCHESTRATOR}.json'
    command = session_settings.shell_command(
        f'cd {shlex_quote(session_settings.command_path(ws.root.resolve()))} && claude --name {ws.coordinator}'
        + (f' --permission-mode {mode}' if mode else '') + f' --settings {rel}', ws.config.get('shell'))
    return (f'orchestrator start command (session name {ws.coordinator}):\n{command}\n'
            'alternative for message delivery in every session of the owner: /config -> "Messages from your '
            'other sessions" -> accept (user settings). Without accept, messages between sessions of different '
            'permission classes wait for approval and are dropped after 5 minutes.')


def write_settings(ws, target):
    """Write orchestration/settings/<name>.json for local modules and the orchestrator; returns report lines.

    Idempotent: an unchanged file is only touched (newer than orch.yaml). <name>.local.json is never touched."""
    if ws.config.get('client') == 'codex':
        return codex_adapter.write_settings(ws, target)
    _, modules, errors = ws.streams()
    if errors:
        raise OrchError('fix orch.yaml first: ' + '; '.join(errors))
    names = sorted(modules) if target == 'all' else [] if target == session_settings.ORCHESTRATOR else [target]
    for name in names:
        if name not in modules:
            raise OrchError(f'unknown module {name!r} (orch.yaml modules: {", ".join(sorted(modules)) or "none"})')
    outputs, lines = build_settings(ws, names, target in ('all', session_settings.ORCHESTRATOR))
    for name, data in outputs:
        problems = session_settings.settings_errors(data)
        if problems:
            raise OrchError(f'settings {name}: ' + '; '.join(problems))
        path = session_settings.settings_path(ws.root, name)
        text = session_settings.render(data)
        if path.is_file() and path.read_text(encoding='utf-8') == text:
            os.utime(path)
            lines.append(f'settings {name}: unchanged ({path})')
            continue
        if path.exists():
            safe_edit.replace_once(path, path.read_text(encoding='utf-8'), text)
        else:
            safe_edit.create(path, text)
        lines.append(f'settings {name}: written ({path})')
    return lines


def build_settings(ws, names, orchestrator=True):
    """([(name, settings dict)], report lines) for the given local modules and the orchestrator."""
    repos, modules, _ = ws.streams()
    lines, outputs = [], []
    for name in names:
        module = modules[name]
        if module.cloud:
            lines.append(f'settings {name}: skipped (cloud sessions: permissions come from the cloud environment)')
            continue
        try:
            data, notes = session_settings.module_settings(ws.config, ws.root, module, ws.in_repo)
        except session_settings.PathError as error:
            raise OrchError(f'settings {name}: {error}')
        outputs.append((name, data))
        lines.extend(f'settings {name}: note: {n}' for n in notes)
    if orchestrator:
        try:
            outputs.append((session_settings.ORCHESTRATOR, session_settings.orchestrator_settings(
                ws.config, ws.root, modules, repos, SKILL_DIR, ws.workspace_branch if ws.in_repo else None)))
        except session_settings.PathError as error:
            raise OrchError(f'settings {session_settings.ORCHESTRATOR}: {error}')
    return outputs, lines


def settings_warnings(ws):
    """Missing or stale settings files (content differs from what `settings` writes now)."""
    _, modules, errors = ws.streams()
    if errors:
        return []
    if ws.config.get('client') == 'codex':
        result = []
        for name in [*modules, 'orchestrator']:
            try:
                codex_adapter.read_flags(ws, name)
            except (streams.StreamError, ValueError) as e:
                result.append(str(e))
        return result
    warnings = []
    try:
        outputs, _ = build_settings(ws, sorted(modules))
    except (OrchError, streams.StreamError, ValueError):
        return []
    for name, data in outputs:
        path = session_settings.settings_path(ws.root, name)
        rel = path.relative_to(ws.root)
        if not path.is_file():
            if name == session_settings.ORCHESTRATOR:
                warnings.append(f'{rel} is missing: run orch.py settings all, then start the orchestrator with '
                                f'--settings {rel} (see init.md)')
            else:
                warnings.append(f'{rel} is missing: dispatch of module {name} refuses until orch.py settings all '
                                '(or pass --no-settings for the pre-0.6.0 start command)')
        elif path.read_text(encoding='utf-8') != session_settings.render(data):
            warnings.append(f'{rel} is older than orch.yaml or the plugin (differs from what orch.py settings '
                            'writes now): run orch.py settings all' +
                            ('; restart the orchestrator with it' if name == session_settings.ORCHESTRATOR else ''))
    return warnings


def cmd_settings(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('settings')
    for line in write_settings(ws, args.target.lower()):
        print(line)
    if ws.config.get('client') == 'codex':
        print('Codex uses launch arguments, native agent files and existing user/project configuration.')
        return 0
    if not ws.config.get('permission_mode'):
        print('note: orch.yaml has no permission_mode: ask the owner (auto recommended) and add '
              '`permission_mode: <mode>`; dispatch then adds --permission-mode')
    print(f'owner changes go to {session_settings.SETTINGS_DIR}/<name>.local.json, which settings never touches '
          'and dispatch never passes: merge them into the generated rules by hand or into your own settings')
    return 0


def worktreeinclude_proposals(ws):
    """P-n texts: a .worktreeinclude for each local repository with worktree streams that has none."""
    _, modules, _ = ws.streams()
    seen, out = set(), []
    for module in modules.values():
        repo = module.repo
        if module.cloud or not module.worktree_mode or repo.key in seen or not repo.local.is_dir():
            continue
        seen.add(repo.key)
        if (repo.local / '.worktreeinclude').exists():
            continue
        listed = streams.git(repo.local, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory')
        found = [f for f in listed.stdout.split('\n') if f and re.search(r'(^|/)\.env(\.[^/]+)?$', f)
                 and not session_settings.SAMPLE_ENV.search(f)]
        content = ', '.join(found) if found else '.env, .env.local'
        out.append(f'Repository {repo.id}: add `.worktreeinclude` in its root (a change of the project, made by a '
                   f'package there) so that every new worktree gets the gitignored files it needs: {content} '
                   '(gitignore syntax, one pattern per line; directories as dir/**). Recommend (a) yes: sessions '
                   'then never copy secrets or settings themselves')
    return out


def in_repo_setup(args, program):
    """In-repo workspace: branch orch/<program> of the current repository, in a directory every
    push workflow ignores, judged from the workflows of the ref that will be pushed. Unknown
    workflow forms and unsafe directories are refused unless the owner decided otherwise
    (--deploy-override D-n). Switches the checkout only after every check passed."""
    top = streams.git_toplevel(Path.cwd())
    if top is None:
        raise OrchError('--in-repo must run inside the repository checkout')
    branch = f'orch/{program}'
    override = args.deploy_override
    if override and not re.fullmatch(r'D-\d+', override):
        raise OrchError('--deploy-override takes the owner decision id, for example D-3')
    if streams.git(top, 'remote', 'get-url', 'origin').returncode:
        raise OrchError('--in-repo needs an origin remote: the workspace branch is pushed there')
    fetched = streams.git(top, 'fetch', '-q', '--prune', 'origin')
    if fetched.returncode:
        raise OrchError(f'git fetch origin failed: {fetched.stderr.strip()}')
    base = args.base
    if not base:
        head = streams.git(top, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
        base = head.stdout.strip().split('/', 1)[-1] if head.returncode == 0 and head.stdout.strip() else 'main'
    remote_branch = streams.ref_exists(top, f'origin/{branch}')
    ref = f'origin/{branch}' if remote_branch else f'origin/{base}'
    if not streams.ref_exists(top, ref):
        raise OrchError(f'neither origin/{branch} nor origin/{base} exists: nothing to judge the deploy by')
    candidates, notes, refusals, any_dir = streams.deploy_safe_dirs(top, branch, program, ref)
    if refusals and not override:
        where = (f'--deploy-override D-n (the workspace then goes to {candidates[0]}, the first directory the '
                 'readable workflows ignore) or --deploy-override D-n --dir <directory>' if candidates else
                 '--deploy-override D-n together with --dir <directory>: no readable workflow leaves a directory '
                 'known to be safe')
        raise OrchError('the deploy check cannot tell whether workspace commits would start a workflow: '
                        + '; '.join(refusals) + f'. {streams.DEPLOY_FORMS}. Ask the owner; after a '
                        f'recorded decision pass {where}')
    if args.dir:
        rel = os.path.normpath(os.path.relpath(Path(args.dir).expanduser().resolve(), top))
        if rel.startswith('..'):
            raise OrchError(f'--dir {args.dir} is outside the repository')
        if not streams.dir_is_safe(rel, candidates, any_dir) and not override:
            raise OrchError(f'{rel} is not a non-hidden directory that every push workflow ignores '
                            f'(safe: {", ".join(candidates) or "none"}); ask the owner, then pass '
                            '--deploy-override D-n with the recorded decision')
    else:
        if not candidates:
            reasons = ('no non-hidden directory is ignored by every push workflow '
                       f'({"; ".join(notes) or "no readable push workflow"})')
            if refusals:
                reasons = ('the deploy check cannot verify ' + '; '.join(refusals) + ', and ' + reasons)
            raise OrchError(f'{reasons}; ask the owner where the workspace may live, then pass --dir <directory>'
                            + (' (with --deploy-override D-n, already given)' if override else
                               ' (and --deploy-override D-n if the owner accepts an unverifiable check)'))
        if not any_dir and not override and not candidates[0].startswith('docs/'):
            raise OrchError(f'no docs/ directory is ignored by the deploy; candidates: {", ".join(candidates)}. '
                            'Ask the owner which one to use, then pass --dir')
        rel = candidates[0]
    if remote_branch and not streams.git(top, 'cat-file', '-e', f'{ref}:{rel}/orch.yaml').returncode:
        raise OrchError(f'a workspace already exists in {rel} on {ref}: switch to {branch} and resume')
    target = top / rel
    if target.exists() and any(target.iterdir()):
        raise OrchError(f'{target} exists and is not empty')
    current = streams.current_branch(top)
    if current != branch:
        if streams.git(top, 'status', '--porcelain').stdout.strip():
            raise OrchError(f'the checkout has uncommitted changes; cannot switch to {branch}')
        if streams.ref_exists(top, branch):
            switch = ['switch', '-q', branch]
        elif remote_branch:
            switch = ['switch', '-q', '-c', branch, '--track', f'origin/{branch}']
        else:
            switch = ['switch', '-q', '--no-track', '-c', branch, f'origin/{base}']  # never track the base
        result = streams.git(top, *switch)
        if result.returncode:
            raise OrchError(f'git {" ".join(switch)} failed: {result.stderr.strip()}')
    if refusals or (args.dir and not streams.dir_is_safe(rel, candidates, any_dir)):
        notes.append(f'deploy check overridden by owner decision {override}: {"; ".join(refusals) or rel}')
    prefix = streams.detect_branch_prefix(str(top))
    repo = {'id': args.in_repo, 'path': '.', 'base': base, 'branch_prefix': prefix,
            'detected': prefix is not None}
    return {'root': target, 'dir': rel, 'branch': branch, 'repo': repo, 'notes': notes,
            'override': override if (refusals or args.dir and not streams.dir_is_safe(rel, candidates, any_dir)) else None}


def yaml_list(values):
    return '[' + ', '.join(json.dumps(v, ensure_ascii=False) for v in values) + ']'


def render_config(base, modules, repos=(), areas=(), in_repo=None, sessions=None, cloud_environment=None):
    title = json.dumps(base['PROGRAM_TITLE'], ensure_ascii=False)
    text = fill((TEMPLATES / 'orch.yaml').read_text(encoding='utf-8'),
                {**base, 'PROGRAM_TITLE_YAML': title})
    if sessions:
        env = f'cloud_environment: {json.dumps(cloud_environment, ensure_ascii=False)}\n' if cloud_environment else ''
        text = text.replace('sessions: local\n', f'sessions: {sessions}\n{env}', 1)
    if in_repo:
        text = text.replace('workspace_mode: separate\n',
                            'workspace_mode: in-repo\n'
                            f'workspace_branch: {in_repo["branch"]}\n'
                            f'workspace_dir: {in_repo["dir"]}\n'
                            + (f'deploy_check_override: {in_repo["override"]}\n' if in_repo['override'] else ''))
        text = text.replace('push_after_milestone: false', 'push_after_milestone: true')
    if repos:
        blocks = []
        for r in repos:
            blocks.append('\n'.join([
                f'  - id: {r["id"]}',
                f'    path: {r["path"]}',
                f'    base: {r["base"]}',
                f'    branch_prefix: {r["branch_prefix"] or base["PROGRAM"] + "/"}',
                '    worktree_root: .claude/worktrees',
                '    worktree_setup: []',
                '    merge_policy: sequential',
                '    shared_paths: []',
                '    resources: []',
                '    checks: []',
            ]))
        text = text.replace('repos: []\n', 'repos:\n' + '\n'.join(blocks) + '\n')
    blocks = []
    if modules:
        for m in modules:
            blocks.append('\n'.join([
                f'  - id: {m["id"]}',
                f'    repo: {m["repo"]}',
                f'    base: {m["base"]}',
                f'    session: {m["session"]}',
                '    tests: []',
            ]))
    for a in areas:
        blocks.append('\n'.join([
            f'  - id: {a["id"]}',
            f'    kind: {a["kind"]}',
            f'    repo: {a["repo"]}',
            f'    paths: {yaml_list(a["paths"])}',
            f'    session: {a["session"]}',
        ]))
    if blocks:
        text = text.replace('modules: []\n', 'modules:\n' + '\n'.join(blocks) + '\n')
    return text


def cmd_new_wp(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('new-wp')
    mod = args.module.lower()
    modules = ws.modules()
    if mod not in modules:
        known = ', '.join(sorted(modules)) or 'none'
        raise OrchError(f'unknown module {mod!r} (orch.yaml modules: {known})')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', args.slug):
        raise OrchError('slug must match [a-z0-9][a-z0-9-]*')
    module = modules[mod]
    prefix = f'WP-{mod.upper()}-'
    _, _, rows = ws.table(ws.status, 'wp')
    numbers = [int(m.group(1)) for p in ws.wp_dir.glob(prefix + '*.md')
               if (m := re.match(re.escape(prefix) + r'(\d+)', p.name))]
    numbers += [int(m.group(1)) for r in rows
                if (m := re.fullmatch(re.escape(prefix) + r'(\d+)', plain_id(r['wp'])))]
    number = runtime_commands.allocate(ws, prefix.rstrip('-'), max(numbers, default=0) + 1,
                                       getattr(args, 'request_id', None))
    wp = f'{prefix}{number:02d}'
    path = ws.wp_dir / f'{wp}-{args.slug}.md'
    title = args.title or args.slug.replace('-', ' ')
    if getattr(args, 'request_id', None):
        existing = ws.wp_rows().get(wp)
        if existing:
            if ws.wp_path(existing['wp']) != path or existing['title'] != title:
                raise OrchError('request-id already created a WP with different slug or title')
            print(f'{wp} {path} (already created)')
            return 0
        if any(ws.wp_dir.glob(wp + '-*.md')):
            raise OrchError('reserved WP has a different or orphaned file; reconcile it before retry')
    _, stream_modules, _ = ws.streams()
    sm = stream_modules[mod]
    session = sm.session
    mapping = {'WP': wp, 'WP_TITLE': title, 'MODULE': mod, 'REPO': sm.repo.path,
               'BASE': sm.repo.base, 'SESSION': session,
               'TAG': ws.tag, 'WP_PATH': str(path.resolve()), 'DATE': today(),
               'COORDINATOR': ws.coordinator}
    workspace = {'mode': 'in-repo' if ws.in_repo else 'separate', 'branch': ws.workspace_branch,
                 'wp_rel': os.path.relpath(path.resolve(), ws.git_top) if ws.in_repo else None}
    mapping.update(streams.wp_fields(ws.lang, sm, wp, args.slug, str(path.resolve()), ws.tag,
                                     ws.coordinator, workspace, streams.active_models(ws.config)))
    if ws.config.get('client') == 'codex':
        mapping.update(codex_adapter.fields(ws.lang, sm, wp, args.slug, str(path.resolve()), ws.tag,
                                            ws.coordinator, streams.active_models(ws.config)))
    else:
        prompt = mapping['START_PROMPT']
        mapping['START_PROMPT'] += '\n\n' + project_instructions.GUIDANCE
        mapping['START_COMMAND'] = mapping['START_COMMAND'].replace(prompt, mapping['START_PROMPT'])
    template = ws.wp_dir / '_TEMPLATE.md'
    text = template.read_text(encoding='utf-8')
    for old in OLD_SETTINGS_NOTES:  # templates before 0.6.0 contradict the start command dispatch prints
        text = text.replace(old, '{{START_NOTE}}')
    safe_edit.create(path, fill(text, mapping))
    link = f'[{wp}](work-packages/{path.name})'
    line = row([link, mod, title, 'DRAFT', session, '—', today()])
    ws.rewrite_table(ws.status, 'wp', lambda body: body + [line])
    ws.journal(f'{wp} created (DRAFT)', wp=wp, evidence=f'work-packages/{path.name}')
    print(f'{wp} {path}')
    return 0


OLD_SETTINGS_NOTES = (
    'No `--settings` in this version: settings files are generated only in a later version.',
    'Без `--settings` в этой версии: файлы настроек появятся только в следующей версии.',
)


def cmd_set(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('set')
    column = args.column.lower()
    if column not in SETTABLE:
        raise OrchError(f'column must be one of: {", ".join(SETTABLE)}')
    value = ' '.join(args.text.split())
    if column == 'status' and not valid_status(value):
        raise OrchError(f'invalid status {value!r}; allowed: {", ".join(STATUSES)}, '
                        'BLOCKED (reason), CANCELLED (reason)')
    columns = TABLES['wp'][1]
    _has_wp(ws, args.wp)
    found = {}

    def transform(body):
        result = []
        for line in body:
            cells = split_row(line)
            if cells and plain_id(cells[0]) == args.wp:
                found['old'] = cells[columns.index(column)]
                cells[columns.index(column)] = cell(value)
                cells[columns.index('updated')] = today()
                line = '| ' + ' | '.join(cells) + ' |'
            result.append(line)
        return result

    ws.rewrite_table(ws.status, 'wp', transform)
    if column == 'status':
        ws.journal(f'{args.wp}: {found["old"]} -> {value}', wp=args.wp,
                   evidence=args.evidence or '—')
        if value in ('REVIEW', 'DONE') or value.startswith('CANCELLED'):
            release_on_demand(ws, args.wp)
    if not getattr(args, 'quiet', False):
        print(f'{args.wp} {column} = {value}')
    return 0


def release_on_demand(ws, wp):
    """READY (status REVIEW) or the end of a package gives back its on-demand locks."""
    if not ws.has_table(ws.status, 'locks'):
        return
    repos = repos_by_id(ws)
    for lock in locks(ws):
        repo = repos.get(lock['repo'])
        if lock['holder'] != wp or repo is None or not repo.on_demand(lock['lock'].split(':', 1)[-1]):
            continue
        waiting = release(ws, lock['lock'], wp)
        ws.journal(f'on-demand lock {lock["lock"]} released at READY' +
                   (f'; next in queue: {", ".join(waiting)}' if waiting else ''), wp=wp, evidence='orch.py set')
        print(f'lock {lock["lock"]}: released' + (f'; next in queue: {", ".join(waiting)}' if waiting else ''),
              file=sys.stderr)


def _has_wp(ws, wp):
    _, _, rows = ws.table(ws.status, 'wp')
    count = sum(1 for r in rows if plain_id(r['wp']) == wp)
    if count != 1:
        raise OrchError(f'{wp}: expected exactly one row in the WP table, found {count}')
    return True


def cmd_model(args):
    """Set the implementer model, effort and reason of a package (header rows and start command)."""
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('model')
    model, effort = args.model, args.effort
    errors = streams.model_errors('model', model, effort, ws.config.get('client', 'claude'))
    if errors:
        raise OrchError('; '.join(errors))
    r, module, _ = wp_context(ws, args.wp)
    path = ws.wp_path(r['wp'])
    text = path.read_text(encoding='utf-8')
    header = streams.wp_header(text)
    labels = {key: next((l for l in streams.WP_LABELS[key] if l in header), None)
              for key in ('model', 'effort', 'model_reason')}
    if not all(labels.values()):
        raise OrchError(f'{args.wp}: the package has no Model/Effort/Model reason rows (created before 0.5.0); '
                        'add them by point edit first')
    values = {'model': f'`{model}`', 'effort': f'`{effort}`' if effort else '—', 'model_reason': cell(args.reason)}
    pairs = []
    for key, label in labels.items():
        line = next(l for l in text.split('\n') if l.startswith(f'| {label} |'))
        pairs.append((line, f'| {label} | {values[key]} |'))
    commands = [b for b in re.findall(r'```bash\n(.*?)\n\s*```', text, re.S)
                if b.strip().startswith('cd ') and ' claude ' in b]
    if commands and not module.cloud:
        pairs.append((commands[-1], streams.apply_model_flags(commands[-1], model, effort)))
    safe_edit.replace_many(path, [(o, n) for o, n in pairs if o != n])
    ws.journal(f'{args.wp}: model {model}' + (f', effort {effort}' if effort else '') + f' ({args.reason})',
               wp=args.wp, evidence='orch.py model')
    print(f'{args.wp}: model {model}' + (f', effort {effort}' if effort else ''))
    return 0


def cmd_cloud_env(args):
    """Record the owner's cloud environment name (program level, or one module)."""
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('cloud-env')
    config = ws.root / 'orch.yaml'
    text = config.read_text(encoding='utf-8')
    value = json.dumps(args.name, ensure_ascii=False)
    if args.module:
        match = re.search(r'(?m)^  - id: ' + re.escape(args.module) + r'\n((?:    .*\n)*)', text)
        if not match:
            raise OrchError(f'module {args.module} not found in orch.yaml')
        block = match.group(0)
        current = re.search(r'(?m)^    cloud_environment: .*\n', block)
        new_block = (block.replace(current.group(0), f'    cloud_environment: {value}\n') if current
                     else block + f'    cloud_environment: {value}\n')
        safe_edit.replace_once(config, block, new_block)
    else:
        current = re.search(r'(?m)^cloud_environment: .*$', text)
        if current:
            safe_edit.replace_once(config, current.group(0) + '\n', f'cloud_environment: {value}\n')
        else:
            line = re.search(r'(?m)^sessions: .*$', text) or re.search(r'(?m)^program: .*$', text)
            safe_edit.replace_once(config, line.group(0) + '\n', f'{line.group(0)}\ncloud_environment: {value}\n')
    ws.journal(f'cloud environment {args.name}' + (f' for module {args.module}' if args.module else ''),
               evidence='owner answer; orch.py cloud-env')
    print(f'cloud environment: {args.name}')
    return 0


def cmd_journal(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.journal(args.event, wp=args.wp or '—', evidence=args.evidence or '—')
    print('journal: ok')
    return 0


def next_id(ids, prefix, ws=None):
    numbers = [int(m.group(1)) for i in ids if (m := re.fullmatch(prefix + r'-(\d+)', i))]
    number = runtime_commands.allocate(ws, prefix, max(numbers, default=0) + 1) if ws else max(numbers, default=0) + 1
    return f'{prefix}-{number}'


def cmd_owner(args):
    ws = Workspace(find_workspace(args.workspace))
    _, _, rows = ws.table(ws.status, 'owner')
    if args.action == 'add':
        if not getattr(args, 'allow_closed', False):
            ws.require_open('owner add')
        kind = args.target.upper()
        if kind not in ('R', 'P'):
            raise OrchError('owner add takes R (action) or P (question)')
        new = next_id([plain_id(r['id']) for r in rows], kind, ws)
        cells = [new, cell(args.text), cell(args.where or '—'), today(), '']
        line = '| ' + ' | '.join(cells) + ' |'
        ws.rewrite_table(ws.status, 'owner', lambda body: body + [line])
        ws.journal(f'{new} opened for owner', evidence=args.where or '—')
        if not getattr(args, 'quiet', False):
            print(new)
        return 0
    target = args.target.upper()
    matches = [r for r in rows if plain_id(r['id']) == target]
    if len(matches) != 1:
        raise OrchError(f'{target}: expected exactly one owner row, found {len(matches)}')
    if matches[0]['closed']:
        raise OrchError(f'{target} is already closed: {matches[0]["closed"]}')
    if args.action == 'carry':
        carry_to_backlog(ws, target, matches[0], args.text)
    note = {'close': f'{today()}: {args.text}', 'drop': f'{today()} dropped: {args.text}',
            'carry': f'{today()} carried to backlog.md: {args.text}'}[args.action]

    def transform(body):
        result = []
        for line in body:
            cells = split_row(line)
            if cells and plain_id(cells[0]) == target:
                line = '| ' + ' | '.join([f'~~{target}~~', f'~~{cells[1]}~~', cells[2], cells[3],
                                          cell(note)]) + ' |'
            result.append(line)
        return result

    ws.rewrite_table(ws.status, 'owner', transform)
    verb = {'close': 'closed', 'drop': 'dropped', 'carry': 'carried to backlog'}[args.action]
    ws.journal(f'{target} {verb}', evidence=args.text)
    print(f'{target} {verb}')
    return 0


def carry_to_backlog(ws, item_id, item, reason):
    """Append an open owner item to backlog.md (created from the template on first use)."""
    path = ws.root / 'backlog.md'
    if not path.is_file():
        template = (TEMPLATES / ws.lang / 'backlog.md').read_text(encoding='utf-8')
        safe_edit.create(path, fill(template, {'PROGRAM_TITLE': ws.config.get('title') or ws.config.get('program')}))
    _, _, rows = ws.table(path, 'backlog')
    new = next_id([plain_id(r['id']) for r in rows], 'B', ws)
    line = row([new, today(), item['text'], item_id, reason])
    ws.rewrite_table(path, 'backlog', lambda body: body + [line])
    return new


def open_owner_items(ws):
    _, _, rows = ws.table(ws.status, 'owner')
    return [r for r in rows if not r['closed'] and not r['id'].startswith('~~')]


def cmd_queue(args):
    ws = Workspace(find_workspace(args.workspace))
    items = open_owner_items(ws)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print('owner queue: empty')
    for item in items:
        print(f'{item["id"]} | {item["text"]} | {item["where"]} | {item["opened"]}')
    return 0


def cmd_decide(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.require_open('decide')
    kind = args.kind.upper()
    if kind not in ('D', 'A', 'Q'):
        raise OrchError('decide takes D (decision), A (assumption) or Q (question)')
    _, _, rows = ws.table(ws.decisions, 'decisions')
    new = next_id([plain_id(r['id']) for r in rows], kind, ws)
    source = args.source or (args.closes and f'answer to {args.closes.upper()}') or '—'
    line = row([new, today(), args.text, source])
    if args.closes:
        target = args.closes.upper()
        owner_rows = [r for r in open_owner_items(ws) if r['id'] == target]
        if len(owner_rows) != 1:
            raise OrchError(f'{target}: not an open owner item')
    ws.rewrite_table(ws.decisions, 'decisions', lambda body: body + [line])
    ws.journal(f'{new} recorded', evidence=source)
    if args.closes:
        cmd_owner(argparse.Namespace(workspace=str(ws.root), action='close', target=target,
                                     text=f'answered by {new}'))
    print(new)
    return 0


# ---------------------------------------------------------------- lint

def lint(ws):
    errors = []
    config = ws.config
    for key in ('program', 'tag', 'owner_language'):
        if not config.get(key):
            errors.append(f'orch.yaml: missing {key}')
    if config.get('owner_language') not in (None, *LANGUAGES):
        errors.append(f'orch.yaml: owner_language must be one of {LANGUAGES}')
    if config.get('spec_graph', 'none') not in ('none', 'nacl'):
        errors.append('orch.yaml: spec_graph must be none or nacl')
    if config.get('permission_mode') is not None and \
            config.get('permission_mode') not in session_settings.PERMISSION_MODES:
        errors.append(f'orch.yaml: permission_mode must be one of {", ".join(session_settings.PERMISSION_MODES)}')
    raw_points = [config.get('checkpoints')] + [m.get('checkpoints') for m in config.get('modules') or []
                                               if isinstance(m, dict)]
    for points in raw_points:
        for point in streams.as_list(points):
            if point not in session_settings.CHECKPOINTS:
                errors.append(f'orch.yaml: checkpoint {point!r} must be one of '
                              f'{", ".join(session_settings.CHECKPOINTS)}')
    if config.get('bug_reports') not in (None, 'confirm', 'auto'):
        errors.append('orch.yaml: bug_reports must be confirm or auto')
    if config.get('bug_reports') == 'auto':
        _, problem = report_policy(ws)
        if problem:
            errors.append(f'orch.yaml: {problem}')
    if config.get('shell') is not None and config.get('shell') not in session_settings.SHELLS:
        errors.append(f'orch.yaml: shell must be one of {", ".join(session_settings.SHELLS)}')
    vtimeout = config.get('verify_timeout')
    if vtimeout is not None and not (isinstance(vtimeout, int) and not isinstance(vtimeout, bool) and vtimeout > 0):
        errors.append('orch.yaml: verify_timeout must be a positive whole number of seconds')
    for kind, items in (('repo', config.get('repos') or []), ('module', config.get('modules') or [])):
        for item in items:
            if isinstance(item, dict):
                errors.extend(verification.pattern_errors(item, f'{kind} {item.get("id")}'))
    stale = config.get('lock_stale_hours')
    if stale is not None and not (isinstance(stale, int) and stale > 0):
        errors.append('orch.yaml: lock_stale_hours must be a positive whole number')
    ids = [str(m.get('id')) for m in config.get('modules') or [] if isinstance(m, dict)]
    for module in config.get('modules') or []:
        if not isinstance(module, dict) or not module.get('id') or not module.get('repo'):
            errors.append(f'orch.yaml: module needs id and repo: {module}')
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f'orch.yaml: duplicate module id {dup}')
    errors.extend(ws.streams()[2])

    tables = {}
    for path, name in ((ws.status, 'wp'), (ws.status, 'owner'), (ws.status, 'journal'),
                       (ws.decisions, 'decisions')):
        try:
            tables[name] = ws.table(path, name)[2]
        except (OrchError, FileNotFoundError) as error:
            errors.append(str(error))
    wp_rows = tables.get('wp', [])
    wp_ids = [plain_id(r['wp']) for r in wp_rows]
    for dup in sorted({i for i in wp_ids if wp_ids.count(i) > 1}):
        errors.append(f'status.md: duplicate WP {dup}')
    for r in wp_rows:
        if not valid_status(r['status']):
            errors.append(f'status.md: {plain_id(r["wp"])} has invalid status {r["status"]!r}')
        link = re.match(r'^\[[^\]]+\]\(([^)]+)\)$', r['wp'])
        if link and not (ws.root / link.group(1)).is_file():
            errors.append(f'status.md: {plain_id(r["wp"])} links to missing {link.group(1)}')
    files = sorted(p for p in ws.wp_dir.glob('WP-*.md')) if ws.wp_dir.is_dir() else []
    for path in files:
        meta = streams.wp_meta(path, None)
        errors.extend(f'work-packages/{path.name}: {e}'
                      for e in streams.model_errors('header', meta.get('model'), meta.get('effort'), ws.config.get('client', 'claude')))
    for path in files:
        wp = re.match(r'^(WP-[A-Z0-9-]+?-\d+)', path.name)
        if not wp or wp.group(1) not in wp_ids:
            errors.append(f'work-packages/{path.name}: no row in the status.md WP table')
    owner_ids = [plain_id(r['id']) for r in tables.get('owner', [])]
    for dup in sorted({i for i in owner_ids if owner_ids.count(i) > 1}):
        errors.append(f'status.md: duplicate owner item {dup}')
    for r in tables.get('owner', []):
        if not re.fullmatch(r'[RP]-\d+', plain_id(r['id'])):
            errors.append(f'status.md: owner item id must be R-n or P-n: {r["id"]}')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['opened']):
            errors.append(f'status.md: {plain_id(r["id"])} has no opened date')
        if r['id'].startswith('~~') and not re.match(r'\d{4}-\d{2}-\d{2}', r['closed']):
            errors.append(f'status.md: {plain_id(r["id"])} struck through without closing date')
    dates = [r['date'] for r in tables.get('journal', [])]
    for i, date in enumerate(dates):
        if not re.match(r'\d{4}-\d{2}-\d{2}', date):
            errors.append(f'status.md: journal line {i + 1} has no date')
    if dates != sorted(dates, reverse=True):
        errors.append('status.md: journal must be newest first')
    for name in ('locks', 'merge'):
        if ws.has_table(ws.status, name):
            try:
                tables[name] = ws.table(ws.status, name)[2]
            except OrchError as error:
                errors.append(str(error))
    backlog_path = ws.root / 'backlog.md'
    if backlog_path.is_file():
        try:
            backlog_ids = [plain_id(r['id']) for r in ws.table(backlog_path, 'backlog')[2]]
            for dup in sorted({i for i in backlog_ids if backlog_ids.count(i) > 1}):
                errors.append(f'backlog.md: duplicate {dup}')
        except OrchError as error:
            errors.append(str(error))
    lock_names = [r['lock'] for r in tables.get('locks', [])]
    for dup in sorted({n for n in lock_names if lock_names.count(n) > 1}):
        errors.append(f'status.md: lock {dup} appears twice')
    for r in tables.get('locks', []):
        if r['holder'] == FREE:
            if not waiting_of(r):
                errors.append(f'status.md: free lock {r["lock"]} without a queue should be removed')
        elif r['holder'] not in wp_ids:
            errors.append(f'status.md: lock {r["lock"]} held by unknown WP {r["holder"]}')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*:.+', r['lock']):
            errors.append(f'status.md: lock name must be <repo>:<name>: {r["lock"]}')
    queued = [r['wp'] for r in tables.get('merge', []) if r['status'] == 'queued']
    for dup in sorted({w for w in queued if queued.count(w) > 1}):
        errors.append(f'status.md: {dup} queued for merge twice')
    for r in tables.get('merge', []):
        if r['wp'] not in wp_ids:
            errors.append(f'status.md: merge queue has unknown WP {r["wp"]}')
        if r['status'] not in ('queued', 'merged', 'dropped'):
            errors.append(f'status.md: merge queue status must be queued, merged or dropped: {r["status"]}')
        if not r['n'].isdigit():
            errors.append(f'status.md: merge queue position must be a number: {r["n"]}')
    if config.get('state', 'active') not in ('active', 'closed'):
        errors.append('orch.yaml: state must be active or closed')
    if config.get('state') == 'closed' and (ws.status).is_file():
        try:
            for r in ws.table(ws.status, 'wp')[2]:
                if not is_terminal(r['status']):
                    errors.append(f'status.md: program is closed but {plain_id(r["wp"])} is {r["status"]}')
        except OrchError:
            pass
    if config.get('workspace_mode', 'separate') not in ('separate', 'in-repo'):
        errors.append('orch.yaml: workspace_mode must be separate or in-repo')
    if ws.in_repo:
        if not ws.workspace_branch.startswith('orch/'):
            errors.append('orch.yaml: workspace_branch must start with orch/')
        rel = os.path.relpath(ws.root.resolve(), ws.git_top)
        if config.get('workspace_dir') and os.path.normpath(str(config['workspace_dir'])) != rel:
            errors.append(f'orch.yaml: workspace_dir {config["workspace_dir"]} does not match the workspace '
                          f'location {rel}')
    dec_ids = [plain_id(r['id']) for r in tables.get('decisions', [])]
    for dup in sorted({i for i in dec_ids if dec_ids.count(i) > 1}):
        errors.append(f'decisions.md: duplicate {dup}')

    for path in sorted(ws.root.rglob('*')):
        rel = path.relative_to(ws.root)
        if safe_edit.BACKUP_DIR_NAME in rel.parts or '.git' in rel.parts or not path.is_file():
            continue
        if not path.read_bytes().strip():
            errors.append(f'{rel}: empty file')
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f'{rel}: looks like a secret ({pattern.pattern[:24]}...)')
                break
        if safe_edit.MARKER_LINE.search(text):
            errors.append(f'{rel}: leftover edit marker line (<<<<<<< / ======= / >>>>>>>)')
        if path.name != '_TEMPLATE.md' and re.search(r'\{\{[A-Z_]+\}\}', text):
            errors.append(f'{rel}: unresolved template placeholder')
    return errors


def in_repo_deploy_problem(ws):
    """Why a state commit of an in-repo workspace could start a deploy, or None."""
    if not ws.in_repo or ws.config.get('deploy_check_override'):
        return None
    top, branch = ws.git_top, ws.workspace_branch
    base = next((m.repo.base for m in ws.streams()[1].values() if m.repo.key == str(top)), 'main')
    ref = next((r for r in (f'origin/{branch}', f'origin/{base}') if streams.ref_exists(top, r)), None)
    if ref is None:
        return f'neither origin/{branch} nor origin/{base} exists to judge the deploy by'
    candidates, _, refusals, any_dir = streams.deploy_safe_dirs(top, branch, ws.config.get('program', ''), ref)
    if refusals:
        return 'the deploy check cannot verify the workflows: ' + '; '.join(refusals)
    rel = os.path.relpath(ws.root.resolve(), top)
    if not streams.dir_is_safe(rel, candidates, any_dir):
        return f'{rel} is not under a directory every push workflow ignores (safe: {", ".join(candidates) or "none"})'
    return None


def lint_warnings(ws):
    """Non-blocking findings: 0.1.0 modules sharing a checkout, workspace in a module's main checkout."""
    warnings = list(ws.stream_warnings())
    _, modules, _ = ws.streams()
    problem = in_repo_deploy_problem(ws)
    if problem:
        warnings.append(f'in-repo workspace: {problem}; commit refuses until the owner decides '
                        '(deploy_check_override: D-n)')
    if ws.wp_dir.is_dir():
        for path in sorted(ws.wp_dir.glob('WP-*.md')):
            meta = streams.wp_meta(path, None)
            if meta.get('effort') and not meta.get('model'):
                warnings.append(f'work-packages/{path.name}: Effort without Model has no effect on the start command')
    local = [m for m in modules.values() if not m.cloud]
    warning = streams.main_checkout_warning(ws.root, local)
    if warning:
        warnings.append(warning)
    if ws.config.get('client', 'claude') == 'claude' and not ws.config.get('permission_mode'):
        warnings.append('orch.yaml has no permission_mode (workspace before 0.6.0): ask the owner which permission '
                        'mode the sessions run in (auto recommended), add `permission_mode: <mode>` and run '
                        'orch.py settings all')
    warnings.extend(settings_warnings(ws))
    seen = set()
    for module in local:
        repo = module.repo
        if repo.key in seen:
            continue
        seen.add(repo.key)
        for command in session_settings.secret_copies(repo.worktree_setup):
            warnings.append(f'repo {repo.id}: worktree_setup `{command}` copies secrets or session settings into '
                            f'the worktree: {session_settings.WORKTREEINCLUDE_HINT}')
    template = ws.wp_dir / '_TEMPLATE.md'
    if template.is_file() and '{{IF_DENIED}}' not in template.read_text(encoding='utf-8'):
        warnings.append('work-packages/_TEMPLATE.md predates 0.6.0 (no section 6 "If a permission is denied"): new '
                        'packages lack it while dispatch starts sessions with --settings; copy section 6 and the '
                        f'Start command note from the plugin template templates/{ws.lang}/work-package.md by point '
                        'edit (new-wp already replaces the old "No --settings" note)')
    if ws.wp_dir.is_dir():
        rows = ws.wp_rows()
        for path in sorted(ws.wp_dir.glob('WP-*.md')):
            wp = re.match(r'^(WP-[A-Z0-9-]+?-\d+)', path.name)
            module = modules.get(rows.get(wp.group(1), {}).get('module', '').lower()) if wp else None
            if module is None:
                continue
            _, unknown = lock_names(module.repo, streams.wp_meta(path, module))
            for name in unknown:
                warnings.append(f'work-packages/{path.name}: `{name}` in the Shared paths or Resources row is not '
                                f'a lock of repo {module.repo.id} (not in its shared_paths or resources); '
                                'dispatch ignores it')
    warnings.extend(stale_on_demand(ws))
    return warnings


def clock():
    """Now in UTC; ORCH_NOW ('YYYY-MM-DD HH:MMZ') replaces it for age checks in tests."""
    fixed = os.environ.get('ORCH_NOW')
    if fixed:
        return dt.datetime.strptime(fixed, '%Y-%m-%d %H:%MZ').replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def repos_by_id(ws):
    repos, modules, _ = ws.streams()
    found = {m.repo.id: m.repo for m in modules.values()}
    found.update(repos)
    return found


def stale_on_demand(ws):
    """On-demand locks held longer than lock_stale_hours (default 4): the session may have forgotten UNLOCK."""
    if not ws.has_table(ws.status, 'locks'):
        return []
    limit = ws.config.get('lock_stale_hours') or 4
    limit = limit if isinstance(limit, int) and limit > 0 else 4
    repos = repos_by_id(ws)
    out = []
    try:
        rows = locks(ws)
    except OrchError:
        return []
    for lock in rows:
        repo = repos.get(lock['repo'])
        name = lock['lock'].split(':', 1)[-1]
        if lock['holder'] == FREE or repo is None or not repo.on_demand(name):
            continue
        try:
            since = dt.datetime.strptime(lock['since'], '%Y-%m-%d %H:%MZ').replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        hours = (clock() - since).total_seconds() / 3600
        if hours >= limit:
            out.append(f'on-demand lock {lock["lock"]} held by {lock["holder"]} for {int(hours)} h (limit {limit} h): '
                       f'ask the session whether it still needs it; release with orch.py lock release {name} '
                       f'--wp {lock["holder"]} after its UNLOCK')
    return out


def cmd_lint(args):
    ws = Workspace(find_workspace(args.workspace))
    errors = lint(ws)
    for warning in lint_warnings(ws):
        print(f'lint: warning: {warning}', file=sys.stderr)
    for error in errors:
        print(f'lint: {error}', file=sys.stderr)
    if not errors:
        print(f'lint: clean ({ws.root})')
    return 1 if errors else 0


def git(root, *args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check, text=True,
                          capture_output=True)


def commit_preconditions(ws):
    """Everything that must hold before a workspace commit; raises OrchError. Returns the branch."""
    if git(ws.root, 'rev-parse', '--is-inside-work-tree', check=False).returncode:
        raise OrchError(f'{ws.root} is not inside a git repository')
    branch = streams.current_branch(ws.root)
    if not branch or branch == 'HEAD':
        raise OrchError('detached HEAD: check out a branch first; nothing committed')
    repos, modules, _ = ws.streams()
    all_repos = list({m.repo.key: m.repo for m in modules.values()}.values()) + list(repos.values())
    conflict = streams.module_repo_conflict(ws.root, all_repos)
    if conflict:
        raise OrchError(conflict + '; nothing committed')
    if ws.in_repo:
        problem = in_repo_deploy_problem(ws)
        if problem:
            raise OrchError(f'in-repo workspace: {problem}; nothing committed. After an owner decision set '
                            'deploy_check_override: D-n in orch.yaml')
        if branch != ws.workspace_branch:
            raise OrchError(f'in-repo workspace: commits go only to {ws.workspace_branch}, the checkout is on '
                            f'{branch}; nothing committed')
    return branch


def push_branch(ws, root, branch):
    """Push the current branch to the same-named branch of its remote (never via an upstream that
    points elsewhere). A closed in-repo program whose branch is gone from origin (archived by the
    owner) is not pushed again. Returns False when the push failed."""
    remote = git(root, 'config', f'branch.{branch}.remote', check=False).stdout.strip() or 'origin'
    if ws.closed and ws.in_repo:
        heads = git(root, 'ls-remote', '--heads', remote, branch, check=False)
        if heads.returncode == 0 and not heads.stdout.strip():
            print(f'note: {branch} is no longer on {remote} (archived): committed locally, not pushed')
            return True
    upstream = git(root, 'rev-parse', '--abbrev-ref', '@{u}', check=False)
    push = ['push', remote, f'HEAD:refs/heads/{branch}']
    if upstream.returncode:
        push.insert(1, '-u')
    elif upstream.stdout.strip() != f'{remote}/{branch}':
        print(f'note: upstream {upstream.stdout.strip()} left as is; pushed to {remote}/{branch}', file=sys.stderr)
    result = git(root, *push, check=False)
    if result.returncode:
        print(f'push failed: {result.stderr.strip()}', file=sys.stderr)
        return False
    print('push: ok')
    return True


def cmd_commit(args):
    ws = Workspace(find_workspace(args.workspace))
    errors = lint(ws)
    if errors:
        for error in errors:
            print(f'lint: {error}', file=sys.stderr)
        raise OrchError('lint failed; nothing committed')
    branch = commit_preconditions(ws)
    for warning in lint_warnings(ws):
        print(f'lint: warning: {warning}', file=sys.stderr)
    git(ws.root, 'add', '-A', '--', '.')
    if not git(ws.root, 'diff', '--cached', '--name-only', '--', '.').stdout.strip():
        print('commit: nothing to commit')
        return 0
    git(ws.root, 'commit', '-q', '-m', args.message, '--', '.')
    sha = git(ws.root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    print(f'commit: {sha}')
    if ws.config.get('push_after_milestone') and not args.no_push:
        return 0 if push_branch(ws, ws.root, branch) else 1
    return 0


# ---------------------------------------------------------------- streams: locks, queue, dispatch

UPGRADE_SECTIONS = {
    'en': ('## Locks\n\nShared paths and resources of a repository; only the holder may change a shared\n'
           'path, push a migration, verify on the stand or run the dev stack on fixed ports. The\n'
           'holder releases after merge or verification. Waiting: packages queued for the lock.\n\n'
           '<!-- orch:locks -->\n| Lock | Repo | Holder | Since | Waiting | Note |\n'
           '|------|------|--------|-------|---------|------|\n\n'
           '## Merge queue\n\nWith `merge_policy: sequential`: one merge at a time; after each merge wait for\n'
           'the green stand deploy and health check, then rebase the next package.\n\n'
           '<!-- orch:merge -->\n| # | Repo | WP | PR | Rebase after | Status |\n'
           '|---|------|----|----|--------------|--------|\n\n'),
    'ru': ('## Замки\n\nОбщие пути и ресурсы репозитория; только держатель правит общий путь, пушит миграцию,\n'
           'проверяет на стенде, запускает dev-стек на фиксированных портах. Держатель отдаёт замок\n'
           'после merge или проверки. «Ждут» — пакеты в очереди на замок.\n\n'
           '<!-- orch:locks -->\n| Замок | Репозиторий | Держатель | С | Ждут | Примечание |\n'
           '|-------|-------------|-----------|---|------|------------|\n\n'
           '## Очередь слияний\n\nПри `merge_policy: sequential`: по одному; после каждого merge — зелёный деплой\n'
           'стенда и health-check, затем rebase следующего пакета.\n\n'
           '<!-- orch:merge -->\n| # | Репозиторий | WP | PR | Rebase после | Статус |\n'
           '|---|-------------|----|----|--------------|--------|\n\n'),
}


def require_table(ws, name):
    if not ws.has_table(ws.status, name):
        raise OrchError(f'status.md has no {TABLES[name][0]} table; run `orch.py upgrade` first')


def cmd_upgrade(args):
    ws = Workspace(find_workspace(args.workspace))
    if ws.has_table(ws.status, 'locks') and ws.has_table(ws.status, 'merge'):
        print('upgrade: status.md already has the locks and merge queue tables')
        return 0
    if ws.has_table(ws.status, 'locks') or ws.has_table(ws.status, 'merge'):
        raise OrchError('status.md has only one of the 0.2.0 tables; fix it by hand')
    text = ws.status.read_text(encoding='utf-8')
    marker = TABLES['journal'][0]
    head = text[:text.index(marker)]
    heading = head.rfind('\n## ')
    if heading < 0:
        raise OrchError('status.md: no heading before the journal table')
    anchor = text[heading + 1:text.index(marker) + len(marker)]
    safe_edit.replace_once(ws.status, anchor, UPGRADE_SECTIONS[ws.lang] + anchor)
    ws.journal('status.md upgraded: locks and merge queue tables', evidence='orch.py upgrade')
    print('upgrade: added locks and merge queue tables')
    return 0


def locks(ws):
    return ws.table(ws.status, 'locks')[2] if ws.has_table(ws.status, 'locks') else []


def wp_context(ws, wp):
    """(row, module, meta) of a work package, resolved against orch.yaml."""
    rows = ws.wp_rows()
    if wp not in rows:
        raise OrchError(f'{wp}: no row in the WP table')
    r = rows[wp]
    _, modules, _ = ws.streams()
    module = modules.get(r['module'].lower())
    if module is None:
        raise OrchError(f'{wp}: module {r["module"]} is not in orch.yaml')
    path = ws.wp_path(r['wp'])
    meta = streams.wp_meta(path, module) if path and path.is_file() else {
        'paths': module.paths, 'shared': [], 'resources': [], 'depends': [], 'branch': None}
    return r, module, meta


def lock_key(repo, name):
    return f'{repo.id}:{name}'


FREE = '—'


def waiting_of(lock):
    return [w for w in lock['waiting'].split(', ') if w and w != FREE]


def lock_kind(repo, name):
    """'resource' or 'path'; anything else is refused (typos must not create new locks)."""
    if name in repo.resources:
        return 'resource'
    try:
        if any(streams.patterns_overlap(name, shared) for shared in repo.shared_paths):
            return 'path'
    except streams.StreamError as error:
        raise OrchError(str(error))
    raise OrchError(f'unknown lock {name!r} in repo {repo.id}: not one of its resources '
                    f'({", ".join(repo.resources) or "none"}) and not within its shared_paths '
                    f'({", ".join(repo.shared_paths) or "none"})')


def lock_names(repo, meta):
    """(known, unknown) backticked names of the Shared paths and Resources rows: only names within the
    repository's shared_paths or resources are locks; other text is a lint warning, never a refusal."""
    known, unknown = [], []
    for name in meta['shared'] + meta['resources']:
        try:
            lock_kind(repo, name)
        except OrchError:
            unknown.append(name)
            continue
        known.append(name)
    return known, unknown


def lock_conflicts(ws, repo, name, wp):
    """Locks of the same repository held by others that collide with name (paths by glob)."""
    kind = lock_kind(repo, name)
    found = []
    for lock in locks(ws):
        if lock['repo'] != repo.id or lock['holder'] in (wp, FREE):
            continue
        other = lock['lock'].split(':', 1)[-1]
        other_kind = 'resource' if other in repo.resources else 'path'
        if kind == other_kind and (other == name or (kind == 'path' and streams.patterns_overlap(other, name))):
            found.append(lock)
    return found


def update_lock(ws, key, change=None, remove=False):
    def transform(body):
        out = []
        for line in body:
            cells = split_row(line)
            if cells and cells[0] == key:
                if remove:
                    continue
                values = dict(zip(TABLES['locks'][1], cells))
                values.update(change or {})
                line = '| ' + ' | '.join(cell(values[c]) if c in (change or {}) else values[c]
                                         for c in TABLES['locks'][1]) + ' |'
            out.append(line)
        return out
    ws.rewrite_table(ws.status, 'locks', transform)


def queue_wp(ws, lock, wp):
    waiting = waiting_of(lock)
    if wp not in waiting:
        update_lock(ws, lock['lock'], {'waiting': ', '.join(waiting + [wp])})


def leave_queues(ws, repo, wp):
    """wp got what it waited for: drop it from every queue of the repository."""
    for lock in locks(ws):
        if lock['repo'] != repo.id or wp not in waiting_of(lock):
            continue
        rest = [w for w in waiting_of(lock) if w != wp]
        if lock['holder'] == FREE and not rest:
            update_lock(ws, lock['lock'], remove=True)
        else:
            update_lock(ws, lock['lock'], {'waiting': ', '.join(rest) or FREE})


def acquire(ws, repo, name, wp, note='—'):
    """Take a lock; when it (or an overlapping one) is busy, queue wp and return the holders."""
    key = lock_key(repo, name)
    busy = lock_conflicts(ws, repo, name, wp)
    if busy:
        for lock in busy:
            queue_wp(ws, lock, wp)
        return sorted({lock['holder'] for lock in busy})
    exact = [lock for lock in locks(ws) if lock['lock'] == key]
    if exact and exact[0]['holder'] == wp:
        return []
    if exact:  # a free row that keeps its queue
        waiting = waiting_of(exact[0])
        if waiting and wp not in waiting:
            queue_wp(ws, exact[0], wp)
            return [f'queue ({waiting[0]} first)']
        update_lock(ws, key, {'holder': wp, 'since': now_utc(), 'note': note,
                              'waiting': ', '.join(w for w in waiting if w != wp) or FREE})
        leave_queues(ws, repo, wp)
        return []
    line = row([key, repo.id, wp, now_utc(), FREE, note])
    ws.rewrite_table(ws.status, 'locks', lambda body: body + [line])
    leave_queues(ws, repo, wp)
    return []


def release(ws, key, wp):
    """Release a lock held by wp; a lock with a queue stays as a free row keeping the queue."""
    rows = [r for r in locks(ws) if r['lock'] == key]
    if not rows:
        raise OrchError(f'lock {key} is not held')
    if rows[0]['holder'] != wp:
        raise OrchError(f'lock {key} is held by {rows[0]["holder"]}, not {wp}')
    waiting = waiting_of(rows[0])
    if waiting:
        update_lock(ws, key, {'holder': FREE, 'since': now_utc(), 'note': f'released by {wp}'})
    else:
        update_lock(ws, key, remove=True)
    return waiting


def resolve_lock_name(ws, name, wp, repo_id):
    repos, modules, _ = ws.streams()
    if wp:
        _, module, _ = wp_context(ws, wp)
        repo = module.repo
    elif repo_id:
        candidates = {r.id: r for m in modules.values() for r in [m.repo]}
        candidates.update(repos)
        if repo_id not in candidates:
            raise OrchError(f'unknown repo {repo_id}')
        repo = candidates[repo_id]
    else:
        all_repos = {m.repo.key: m.repo for m in modules.values()}
        all_repos.update({r.key: r for r in repos.values()})
        if len(all_repos) != 1:
            raise OrchError('several repositories: pass --wp or --repo')
        repo = next(iter(all_repos.values()))
    return repo, (name if ':' in name else lock_key(repo, name))


def cmd_lock(args):
    ws = Workspace(find_workspace(args.workspace))
    if args.action != 'list':
        ws.require_open(f'lock {args.action}')
    require_table(ws, 'locks')
    if args.action == 'list':
        rows = locks(ws)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif not rows:
            print('locks: none')
        repos = repos_by_id(ws)
        for r in [] if args.json else rows:
            holder = 'free' if r['holder'] == FREE else f'holder {r["holder"]}'
            repo = repos.get(r['repo'])
            mode = ' (on-demand)' if repo and repo.on_demand(r['lock'].split(':', 1)[-1]) else ''
            print(f'{r["lock"]}{mode} | {holder} | since {r["since"]} | waiting {r["waiting"]}')
        for warning in [] if args.json else stale_on_demand(ws):
            print(f'warning: {warning}')
        return 0
    if not args.name or not args.wp:
        raise OrchError(f'lock {args.action} needs a lock name and --wp')
    repo, key = resolve_lock_name(ws, args.name, args.wp, args.repo)
    name = key.split(':', 1)[1]
    if args.action == 'acquire':
        holders = acquire(ws, repo, name, args.wp, args.note or '—')
        if holders:
            ws.journal(f'{args.wp} waits for lock {key} ({", ".join(holders)})', wp=args.wp,
                       evidence='orch.py lock acquire')
            print(f'lock {key}: busy ({", ".join(holders)}); {args.wp} queued', file=sys.stderr)
            return 1
        ws.journal(f'lock {key} acquired', wp=args.wp, evidence=args.note or 'orch.py lock')
        print(f'lock {key}: held by {args.wp}')
        return 0
    waiting = release(ws, key, args.wp)
    ws.journal(f'lock {key} released', wp=args.wp, evidence=args.note or 'orch.py lock')
    print(f'lock {key}: released' + (f'; next in queue: {", ".join(waiting)}' if waiting else ''))
    return 0


def dispatch_problems(ws, wp):
    """Reasons that forbid dispatching wp now, and the locks it would take."""
    r, module, meta = wp_context(ws, wp)
    problems = []
    if r['status'] != 'READY':
        problems.append(f'{wp} is {r["status"]}, not READY')
    rows = ws.wp_rows()
    for dep in meta['depends']:
        status = rows.get(dep, {}).get('status')
        if status not in streams.SATISFIED:
            problems.append(f'depends on {dep} ({status or "unknown"}), not merged yet')
    for other, orow in rows.items():
        if other == wp or orow['status'] not in streams.ACTIVE:
            continue
        try:
            _, omodule, ometa = wp_context(ws, other)
        except OrchError:
            continue
        if omodule.repo.key != module.repo.key:
            continue
        if not module.worktree_mode or not omodule.worktree_mode:
            problems.append(f'{other} ({orow["status"]}) is writing in the same repository and one of '
                            'them is the whole repository: one writing session at a time')
        elif omodule.id == module.id:
            problems.append(f'{other} ({orow["status"]}) already runs in stream {module.id}')
        else:
            for a, b in streams.overlap_outside_shared(meta['paths'], ometa['paths'],
                                                       module.repo.shared_paths):
                problems.append(f'paths overlap with {other} outside shared paths: {a} ~ {b}')
    wanted, busy = [], {}
    known, _ = lock_names(module.repo, meta)
    for name in known:
        if module.repo.resource_modes.get(name) == 'sequence':
            if lock_conflicts(ws, module.repo, name, wp):
                problems.append(f'old numbering lock {name} still held; stop/reconcile its writer first')
            runtime_commands.check_sequence(ws, module.repo, name)
            continue
        if module.repo.on_demand(name):
            continue  # taken by a LOCK message while the package runs, not at dispatch
        conflicts = lock_conflicts(ws, module.repo, name, wp)
        wanted.append(name)
        for lock in conflicts:
            busy[lock['lock']] = lock
            problems.append(f'lock {lock["lock"]} is held by {lock["holder"]}'
                            + (f' (overlaps {name})' if lock['lock'] != lock_key(module.repo, name) else ''))
        exact = [l for l in locks(ws) if l['lock'] == lock_key(module.repo, name)]
        if exact and exact[0]['holder'] == FREE and waiting_of(exact[0]) and wp not in waiting_of(exact[0]):
            busy[exact[0]['lock']] = exact[0]
            problems.append(f'lock {exact[0]["lock"]} is free but {waiting_of(exact[0])[0]} is first in its queue')
    if module.cloud and module.repo.push_deploys:
        if 'staging' not in module.repo.resources:
            problems.append(f'repo {module.repo.id} deploys on every push (push_deploys) but has no `staging` '
                            'resource: a cloud package needs the stand slot while it runs')
        elif 'staging' not in wanted:
            wanted.append('staging')
            for lock in lock_conflicts(ws, module.repo, 'staging', wp):
                busy[lock['lock']] = lock
                problems.append(f'lock {lock["lock"]} (stand slot) is held by {lock["holder"]}')
    wp_path = ws.wp_path(r['wp'])
    if wp_path and wp_path.is_file():
        header_meta = streams.wp_meta(wp_path, module)
        for error in streams.model_errors(f'{wp} header', header_meta.get('model'), header_meta.get('effort'), ws.config.get('client', 'claude')):
            problems.append(f'{error}; fix it with orch.py model {wp} <model> --reason "..."')
    if module.cloud and not module.cloud_environment:
        problems.append(f'module {module.id} runs cloud sessions but no cloud environment is set: ask the owner for '
                        'its name and record it with: orch.py cloud-env "<name>"' +
                        (f' --module {module.id}' if module.raw.get('sessions') == 'cloud' else ''))
    if not module.cloud and running_in_cloud():
        problems.append(CLOUD_LOCAL_REFUSAL)
    if module.cloud and ws.in_repo:
        path = ws.wp_path(r['wp'])
        rel = os.path.relpath(path.resolve(), ws.git_top) if path else None
        streams.git(ws.git_top, 'fetch', '-q', 'origin', ws.workspace_branch)
        shown = streams.git(ws.git_top, 'show', f'origin/{ws.workspace_branch}:{rel}') if rel else None
        if not shown or shown.returncode:
            problems.append(f'{rel} is not on origin/{ws.workspace_branch} yet: run orch.py commit first, '
                            'the cloud session reads the package from there')
        elif shown.stdout != path.read_text(encoding='utf-8'):
            problems.append(f'{rel} on origin/{ws.workspace_branch} differs from the local file: '
                            'run orch.py commit first')
    return problems, wanted, busy, r, module


def cmd_dispatch(args):
    ws = Workspace(find_workspace(args.workspace))
    state_version = runtime_commands.state_version(ws)
    ws.require_open('dispatch')
    wp = args.wp
    problems, wanted, busy, r, module = dispatch_problems(ws, wp)
    is_codex = ws.config.get('client') == 'codex'
    settings = codex_adapter.settings_path(ws.root, module.id) if is_codex else session_settings.settings_path(ws.root, module.id)
    use_settings = not module.cloud and not args.live and not args.no_settings
    if use_settings and not settings.is_file():
        raise OrchError(f'{settings.relative_to(ws.root)} is missing: run orch.py settings {module.id} (the session '
                        'starts with --settings <that file>); --no-settings keeps the pre-0.6.0 start command')
    _, _, meta0 = wp_context(ws, wp)
    known, unknown = lock_names(module.repo, meta0)
    for name in unknown:
        print(f'dispatch: warning: `{name}` in the Shared paths or Resources row is not a lock of repo '
              f'{module.repo.id} (not in its shared_paths or resources): ignored', file=sys.stderr)
    on_demand = [n for n in known if module.repo.on_demand(n)]
    if on_demand:
        print(f'dispatch: on-demand locks, taken when the session sends LOCK: {", ".join(on_demand)}', file=sys.stderr)
    if wanted:
        require_table(ws, 'locks')
    if problems:
        for problem in problems:
            print(f'dispatch refused: {problem}', file=sys.stderr)
        if not args.dry_run:
            for lock in busy.values():
                queue_wp(ws, lock, wp)
            ws.journal(f'dispatch of {wp} refused: ' + '; '.join(problems), wp=wp,
                       evidence='orch.py dispatch')
            if busy:
                print(f'queued: {wp} waits in the lock table for ' + ', '.join(busy), file=sys.stderr)
        return 1
    path = ws.wp_path(r['wp'])
    text = path.read_text(encoding='utf-8') if path else ''
    meta = streams.wp_meta(path, module) if path and path.is_file() else {}
    model, effort = meta.get('model'), meta.get('effort')
    if module.cloud:
        prompt = re.search(r'## 5\.[^\n]*\n+```text\n(.*?)\n```', text, re.S)
        prompt = prompt.group(1).strip() if prompt else f'{wp}: no start prompt in section 5'
        if args.inline or not ws.in_repo:
            prompt = prompt + '\n\n---\n' + text.strip()
        handover = streams.cloud_block(ws.lang, wp, module, prompt, model, effort)
    elif is_codex:
        runtime_commands.check_capabilities(ws)
        handover = codex_adapter.launch(ws, module, wp, meta)
        if args.live:
            print('Use session send to queue the task to a registered thread; dispatch does not claim delivery.')
    else:
        blocks = [b.strip() for b in re.findall(r'```bash\n(.*?)\n\s*```', text, re.S)]
        commands = [b for b in blocks if b.startswith('cd ') and ' claude ' in b]
        command = streams.apply_model_flags(commands[-1], model, effort) if commands else None
        legacy_prompt = re.search(r'## 5\.[^\n]*\n+```text\n(.*?)\n```', text, re.S)
        if command and legacy_prompt and 'Before implementing, read both' not in command:
            brief = legacy_prompt.group(1)
            command = command.replace(brief, brief + '\n\n' + project_instructions.GUIDANCE)
        if not command:
            slug = path.stem[len(wp) + 1:]
            command = streams.wp_fields(ws.lang, module, wp, slug, str(path.resolve()), ws.tag,
                                        ws.coordinator, models=streams.active_models(ws.config))['START_COMMAND']
            command = streams.apply_model_flags(command, model, effort)
        existing = [e for e in streams.worktrees(module.repo) if e.get('branch') == meta.get('branch')]
        if existing and streams.is_linked_worktree(existing[0]['path']):
            slug = path.stem[len(wp) + 1:]
            prompt = streams.wp_fields(ws.lang, module, wp, slug, str(path.resolve()), ws.tag,
                                       ws.coordinator, models=streams.active_models(ws.config))['START_PROMPT']
            prompt += ('\nUse this existing worktree and branch; skip worktree creation and client-specific '
                       'startup instructions retained in the package from a previous client.\n' + project_instructions.GUIDANCE)
            command = f'cd {shlex_quote(existing[0]["path"])} && claude --name {module.session} {shlex_quote(prompt)}'
            command = streams.apply_model_flags(command, model, effort)
        if command and use_settings:
            command = session_settings.apply_flags(command, settings.resolve(), ws.config.get('permission_mode'))
            expected, _ = session_settings.module_settings(ws.config, ws.root, module, ws.in_repo)
            if settings.read_text(encoding='utf-8') != session_settings.render(expected):
                print(f'dispatch: warning: {settings.relative_to(ws.root)} is older than orch.yaml: run orch.py '
                      f'settings {module.id} before handing the command over', file=sys.stderr)
        if command:
            command = session_settings.shell_command(command, ws.config.get('shell'))
        if args.live:
            rel = path.relative_to(ws.root) if path else wp
            handover = f'[{ws.tag}] TASK {wp} :: {r["title"]} :: ref={ws.root / rel}'
        else:
            handover = command or f'{wp}: no start command in the work package; use its Start prompt section'
    model_note = f'model {model or "owner default"}' + (f', effort {effort}' if effort else '')
    if args.dry_run:  # never writes anything, for any kind of module
        print(f'dispatch {wp}: ok (dry run); locks to take: {", ".join(wanted) or "none"}; {model_note}')
        print(handover)
        return 0
    with state_io.transaction(ws.root):
        if runtime_commands.state_version(ws) != state_version:
            raise OrchError("program state changed during external checks; retry from current files")
        for name in wanted:
            if acquire(ws, module.repo, name, wp, 'dispatch'):
                raise OrchError(f'lock {name} became busy during dispatch; nothing handed over')
        wanted = [lock_key(module.repo, n) for n in wanted]
        evidence = ('cloud session prompt handed to the owner' if module.cloud else
                    'TASK message to live session' if args.live else 'start command handed to the owner')
        cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='DISPATCHING', quiet=True,
                                   evidence=evidence + f'; {model_note}' + (f'; locks {", ".join(wanted)}' if wanted else '')))
    print(handover)
    return 0


def cmd_merge(args):
    ws = Workspace(find_workspace(args.workspace))
    if args.action != 'list':
        ws.require_open(f'merge {args.action}')
    require_table(ws, 'merge')
    _, _, rows = ws.table(ws.status, 'merge')
    if args.action == 'list':
        queued = [q for q in rows if q['status'] == 'queued']
        if args.json:
            print(json.dumps(queued, ensure_ascii=False, indent=2))
            return 0
        if not queued:
            print('merge queue: empty')
        for q in queued:
            print(f'{q["n"]}. {q["repo"]} {q["wp"]} {q["pr"]} (rebase after {q["rebase_after"]})')
        return 0
    if not args.wp:
        raise OrchError(f'merge {args.action} needs a WP')
    _, module, _ = wp_context(ws, args.wp)
    if args.action == 'add':
        if any(q['wp'] == args.wp and q['status'] == 'queued' for q in rows):
            raise OrchError(f'{args.wp} is already in the merge queue')
        same = [q for q in rows if q['repo'] == module.repo.id and q['status'] == 'queued']
        after = same[-1]['wp'] if same and module.repo.merge_policy == 'sequential' else '—'
        number = runtime_commands.allocate(ws, 'MERGE', max([int(q['n']) for q in rows if q['n'].isdigit()], default=0) + 1)
        line = row([number, module.repo.id, args.wp, args.pr or '—', after, 'queued'])
        ws.rewrite_table(ws.status, 'merge', lambda body: body + [line])
        ws.journal(f'{args.wp} queued for merge ({module.repo.merge_policy})', wp=args.wp,
                   evidence=args.pr or '—')
        print(f'{args.wp}: merge queue position {number}' + (f', rebase after {after}' if after != '—' else ''))
        return 0
    queued = [q for q in rows if q['wp'] == args.wp and q['status'] == 'queued']
    if not queued:
        raise OrchError(f'{args.wp} is not queued for merge')
    new_status = 'merged' if args.action == 'done' else 'dropped'

    def transform(body):
        out = []
        for line in body:
            cells = split_row(line)
            if cells and cells[2] == args.wp and cells[5] == 'queued':
                cells[5] = new_status
                line = '| ' + ' | '.join(cells) + ' |'
            out.append(line)
        return out
    ws.rewrite_table(ws.status, 'merge', transform)
    released, kept, waiting = [], [], []
    if args.action == 'done' and ws.has_table(ws.status, 'locks'):
        resources = {lock_key(module.repo, n) for n in module.repo.resources}
        for lock in locks(ws):
            if lock['holder'] != args.wp:
                continue
            if lock['lock'] in resources:
                kept.append(lock['lock'])
            else:
                for w in release(ws, lock['lock'], args.wp):
                    waiting.append(f'{w} (waits for {lock["lock"]})')
                released.append(lock['lock'])
    ws.journal(f'{args.wp} {new_status} in the merge queue' +
               (f'; released {", ".join(released)}' if released else ''), wp=args.wp,
               evidence=args.evidence or '—')
    nxt = [q for q in rows if q['repo'] == module.repo.id and q['status'] == 'queued' and q['wp'] != args.wp]
    print(f'{args.wp}: {new_status}' + (f'; released {", ".join(released)}' if released else ''))
    if kept:
        print(f'still held (release after verification): {", ".join(kept)}')
    if waiting:
        print(f'waiting for the released locks (dispatch them now): {", ".join(waiting)}')
    if nxt:
        print(f'next: rebase {nxt[0]["wp"]} on the new base after the green deploy and health check')
    return 0


def file_findings(wp, meta, repo, files, held):
    """Findings for the files a package's branch changes: outside its paths, shared paths
    undeclared or changed without the package holding the lock."""
    found = []
    for f in files:
        if streams.matches_any(f, repo.shared_paths) or streams.matches_any(f, meta['shared']):
            if not streams.matches_any(f, meta['shared']):
                found.append(f'{wp}: shared path {f} changed but not declared')
            elif not streams.matches_any(f, held):
                found.append(f'{wp}: shared path {f} changed without the lock')
        elif not streams.matches_any(f, meta['paths']):
            found.append(f'{wp}: {f} is outside the allowed paths')
    return found


def run_checks(repo, branches):
    """The repository's own check commands (contract in SKILL.md); failures become findings."""
    found = []
    if not repo.checks or not repo.local.is_dir():
        return found
    env = {**os.environ, 'ORCH_BASE_REF': streams.base_ref(repo), 'ORCH_BRANCHES': ' '.join(branches)}
    for check in repo.checks:
        try:
            result = subprocess.run(check, shell=True, cwd=repo.local, env=env, text=True,
                                    capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            found.append(f'{repo.id}: `{check}` timed out')
            continue
        if result.returncode:
            out = (result.stdout + result.stderr).strip().split('\n')[:5]
            found.append(f'{repo.id}: `{check}` failed: ' + ' / '.join(out))
    return found


def review_auto(ws, wp, module, meta, ref):
    """Automatic review findings for one package at ref: paths, shared paths and locks, a stale
    merge-base, repository checks. Returns (sha, files, findings) with findings as (kind, text)."""
    repo = module.repo
    resolved = streams.resolve_ref(repo, ref)
    if resolved is None:
        raise OrchError(f'{ref} not found in {repo.path} (fetch it or pass --ref <sha>)')
    sha = streams.git(repo.local, 'rev-parse', resolved).stdout.strip()
    base = streams.base_ref(repo)
    files = [f for f in streams.git(repo.local, 'diff', '--name-only', f'{base}...{sha}').stdout.split('\n') if f]
    held = [l['lock'].split(':', 1)[-1] for l in locks(ws) if l['holder'] == wp]
    findings = [('paths', t) for t in file_findings(wp, meta, repo, files, held)]
    mb, behind, overlapping = streams.merge_base_report(repo, sha, files)
    if behind:
        if overlapping:
            findings.append(('merge-base', f'{wp}: branch point {mb[:10]} is {behind} commits behind {base}, which '
                                           f'changed {len(overlapping)} of the branch\'s files since: '
                                           + ', '.join(overlapping[:10]) + ' - rebase and re-run the tests'))
        else:
            findings.append(('merge-base', f'{wp}: branch point {mb[:10]} is {behind} commits behind {base} '
                                           '(no overlapping files) - rebase before merge'))
    findings.extend(('check', t) for t in run_checks(repo, [sha]))
    return sha, files, findings


REPORT_TEXT = {
    'en': {'none': 'none found', 'kinds': {'paths': 'paths and locks', 'merge-base': 'merge-base',
                                          'check': 'repository check'}},
    'ru': {'none': 'не найдено', 'kinds': {'paths': 'пути и замки', 'merge-base': 'merge-base',
                                          'check': 'проверка репозитория'}},
}


def cmd_review_start(args):
    """Start a review round: automatic findings, report skeleton, clone command, status REVIEW."""
    ws = Workspace(find_workspace(args.workspace))
    state_version = runtime_commands.state_version(ws)
    ws.require_open('review-start')
    wp = args.wp
    r, module, meta = wp_context(ws, wp)
    if not module.repo.local.is_dir():
        raise OrchError(f'{module.repo.path} is not available locally: clone it (read-only) or pass --workspace '
                        'from a place where it is')
    if not args.no_fetch:  # updates the remote-tracking refs of the module repository
        fetched = streams.git(module.repo.local, 'fetch', '-q', 'origin')
        if fetched.returncode:
            raise OrchError(f'git fetch origin failed in {module.repo.path}: {fetched.stderr.strip()} '
                            '(pass --no-fetch to review the refs as they are)')
    warnings = []
    ref = args.ref
    if not ref:
        branch = meta['branch']
        if not branch or not streams.ref_exists(module.repo.local, f'origin/{branch}'):
            raise OrchError(f'{wp}: no pushed branch origin/{branch or "?"}; pass --ref <PR head sha>')
        ref = f'origin/{branch}'
        local = streams.git(module.repo.local, 'rev-parse', '--verify', '-q', branch).stdout.strip()
        remote = streams.git(module.repo.local, 'rev-parse', ref).stdout.strip()
        if local and local != remote:
            warnings.append(f'local branch {branch} ({local[:10]}) differs from {ref} ({remote[:10]}); '
                            f'reviewing {ref} - pass --ref <PR head sha> to be explicit')
    sha, files, findings = review_auto(ws, wp, module, meta, ref)
    base = streams.base_ref(module.repo)
    base_sha = streams.git(module.repo.local, 'rev-parse', base).stdout.strip()
    text = REPORT_TEXT[ws.lang]
    auto = '\n'.join(f'- **{text["kinds"][k]}**: {t}' for k, t in findings) or f'- {text["none"]}'
    stat = streams.git(module.repo.local, 'diff', '--shortstat', f'{base}...{sha}').stdout.strip()
    revision = ''
    if args.since:
        old = streams.resolve_ref(module.repo, args.since)
        if old is None:
            raise OrchError(f'--since {args.since} not found')
        revision = (f'git -C {module.repo.path} range-diff {base}..{old} {base}..{sha}'
                    if streams.git(module.repo.local, 'merge-base', '--is-ancestor', old, sha).returncode
                    else f'git -C {module.repo.path} diff {old} {sha}')
    date = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    reports = ws.root / 'reports'
    name = f'{wp.lower()}-review-{date}' + (f'-r{args.round}' if args.round else '') + '.md'
    path = reports / name
    template = (TEMPLATES / ws.lang / 'review-report.md').read_text(encoding='utf-8')
    escalation = None
    if (args.round or 1) >= 3:
        models = ws.config.get('models') if isinstance(ws.config.get('models'), dict) else {}
        target = str(models.get('escalate') or 'opus')
        if ws.config.get('client') == 'codex':
            models = streams.active_models(ws.config) or {}
            target = models.get('escalate')
            if not target:
                warnings.append('round 3+: ask owner to select a Codex escalation model; no Claude model mapping')
        target_effort = models.get('escalate_effort')
        flags = f'--model {target}' + (f' --effort {target_effort}' if target_effort else '')
        if ws.config.get('client') == 'codex':
            how = ('owner restarts the registered Codex session with --model ' + str(target) +
                   ' after stopping its writer') if target else 'owner selects the Codex model'
        elif module.cloud:
            how = (f'in the same cloud session choose {target} in the model list (or send `/model {target}`'
                   + (f' and `/effort {target_effort}`' if target_effort else '') + ')')
        else:
            where = module.repo.path if module.repo.path.startswith(('/', '~')) else str(module.repo.local)
            how = f'cd {where} && claude --resume {module.session} {flags}'
        escalation = (f'round {args.round}: the same REVISE items are still open - restart the module session on '
                      f'{target}: {how}')
        warnings.append(escalation)
    base_label = f'{module.repo.base} @ {base_sha[:10]}'
    if escalation:
        auto += f'\n- **escalation**: {escalation}'
    body = fill(template, {'WP': wp, 'PR': args.pr or r['pr'], 'SHA': sha[:10], 'BASE': base_label, 'DATE': today(),
                           'ROUND': str(args.round or 1), 'FILES': str(len(files)), 'STAT': stat or '—',
                           'AUTO': auto, 'REVISION': revision or '—'})
    with state_io.transaction(ws.root):
        if runtime_commands.state_version(ws) != state_version:
            raise OrchError("program state changed during external checks; retry from current files")
        safe_edit.create(path, body)
        if args.pr:
            cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='pr', text=args.pr, quiet=True,
                                       evidence=None))
        already = any(item['text'].startswith(f'{wp}: round ') and 'restart the module session' in item['text']
                      for item in open_owner_items(ws))
        if escalation and not already:
            cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='R', where=f'reports/{name}',
                                         quiet=True, text=f'{wp}: {escalation} ; expected: the session continues on the stronger '
                                              'model with its context'))
        if r['status'] in ('DISPATCHING', 'IN_PROGRESS', 'REVISE'):
            cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='REVIEW', quiet=True,
                                       evidence=f'{sha[:10]}; report reports/{name}'))
        else:
            ws.journal(f'{wp}: review round {args.round or 1} started at {sha[:10]}', wp=wp,
                       evidence=f'reports/{name}')
    origin = streams.git(module.repo.local, 'config', '--get', 'remote.origin.url').stdout.strip()
    tests = module.tests if isinstance(module.tests, dict) else {'full': module.tests or []}
    commands = [c for c in streams.as_list(tests.get('scoped')) + streams.as_list(tests.get('full'))]
    clone = [f'ORCH_MAIN_CHECKOUT={module.repo.local}', 'bash', str(SKILL_DIR / 'scripts' / 'review_clone.sh'),
             '--repo', origin or str(module.repo.local), '--sha', sha]
    for c in module.repo.review_setup:
        clone += ['--setup', c]
    for c in commands:
        clone += ['--test', c]
    result = {'wp': wp, 'sha': sha, 'base': base_label, 'files': files, 'stat': stat, 'report': str(path),
              'warnings': warnings,
              'findings': [{'kind': k, 'finding': t} for k, t in findings],
              'clone_command': ' '.join(shlex_quote(c) for c in clone), 'revision_diff': revision or None}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    for warning in warnings:
        print(f'warning: {warning}')
    if escalation:
        print(f'escalation: {escalation}')
    print(f'review {wp} at {sha[:10]} against {base_label}: {stat or "no changes"}')
    print(f'report: {path}')
    for k, t in findings:
        print(f'[{k}] {t}')
    if not findings:
        print('automatic findings: none')
    print(f'clone and tests: {result["clone_command"]}')
    if revision:
        print(f'revision diff: {revision}')
    return 0


def redact(text):
    """Mask secret-looking fragments in command output before it reaches a report."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub('[redacted]', text)
    return text


def pr_url(value):
    match = re.search(r'https?://\S+/pull/\d+', value or '')
    return match.group(0) if match else None


def verify_plan(ws, module, env):
    """(checks, notes): the planned checks of one environment, in order."""
    checks = [('deploy', wf) for wf in verification.workflows(module, env)]
    url, pattern = verification.version_source(module, env)
    if url:
        checks.append(('version', url + (f' ~ /{pattern}/' if pattern else '')))
    checks += [('command', c) for c in verification.commands(module, env)]
    return checks


def repo_base(module):
    return module.repo.base


def next_bug(ws):
    numbers = [int(m.group(1)) for p in (ws.root / 'bugs').glob('BUG-*.md')
               if (m := re.match(r'BUG-(\d+)', p.name))]
    return runtime_commands.allocate(ws, 'BUG', max(numbers, default=0) + 1)


def write_bug(ws, wp, module, env, sha, report_rel, failed):
    t = verification.TEXT[ws.lang]
    number = next_bug(ws)
    rel = f'bugs/BUG-{number}-verify-{wp.lower()}-{env}.md'
    fmt = {'wp': wp, 'env': env, 'sha': sha[:10] if sha else '?', 'date': today(), 'report': report_rel}
    field, *heads = t['heads']
    lines = [f'# BUG-{number} — {t["bug_title"].format(**fmt)}', '', f'| {field} |', '|------|----------|',
             f'| {heads[0]} | {t["bug_found"].format(**fmt)} |', f'| {heads[1]} | {env.upper()}, `{fmt["sha"]}` |',
             f'| {heads[2]} | {module.id} |', f'| {heads[3]} | {t["bug_severity"]} |',
             f'| {heads[4]} | {t["bug_status"]} ({wp}) |', '', f'## {heads[5]}', '', t['bug_symptom'], '']
    lines += [f'- {r["kind"]}: `{r["target"]}` -> {r["exit"]}: ' + (' / '.join(r['output']) or '—') for r in failed]
    lines += ['', f'## {heads[6]}', '', '1. ' + t['bug_repro'].format(**fmt), '', f'## {heads[7]}', '',
              t['bug_expected'].format(**fmt), '', f'## {heads[8]}', '', f'[{report_rel}](../{report_rel})', '',
              f'## {heads[9]}', '', t['bug_cause'], '']
    safe_edit.create(ws.root / rel, '\n'.join(lines))
    return rel


def cmd_verify(args):
    """Verify a package on test or prod by facts: deploy run for the SHA, served version, verify commands."""
    ws = Workspace(find_workspace(args.workspace))
    state_version = runtime_commands.state_version(ws)
    if args.list:
        return verify_list(ws)
    if not args.wp or not args.env:
        raise OrchError('verify needs a WP and --env test|prod (or --list)')
    ws.require_open('verify')
    wp, env = args.wp, args.env
    r, module, meta = wp_context(ws, wp)
    checks = verify_plan(ws, module, env)
    if not checks:
        raise OrchError(f'nothing to verify on {env} for module {module.id}: set verify_{env} (read-only commands), '
                        f'version_url or deploy_workflows in orch.yaml')
    accepted = env == 'test' and r['status'] == 'ACCEPTED'
    if r['status'] not in verification.VERIFIABLE[env] and not accepted:
        raise OrchError(f'{wp} is {r["status"]}: verify --env {env} needs one of '
                        f'{", ".join(verification.VERIFIABLE[env])}'
                        + (' (or ACCEPTED with a merged PR)' if env == 'test' else ''))
    branch = verification.branch(module, env)
    pr = pr_url(r['pr'])
    target = verification.TARGET[env]
    if args.dry_run:  # never runs a check, never calls gh, never writes
        sha = args.sha or (f'merge commit of {pr} (gh)' if pr else 'unknown: pass --sha')
        print(f'verify {wp} --env {env} (dry run): SHA {sha}, branch {branch}, '
              f'timeout {verification.timeout(ws.config)} s')
        for i, (kind, what) in enumerate(checks, 1):
            print(f'{i}. {kind}: {what}')
        if accepted:
            print(f'{wp} is ACCEPTED: first confirms through gh that {pr or "its PR"} is merged, then sets MERGED')
        if env == 'prod' and branch != repo_base(module):
            print(f'expected SHA on prod: the tip of origin/{branch} when it contains the merge commit (else pass --sha)')
        print(f'PASS -> status {target}' + (' (kept: already later)' if r['status'] in verification.LATER[env] else '')
              + f'; FAIL -> status stays {r["status"]}, a defect in bugs/, a journal line')
        return 0
    repo = module.repo
    if not repo.local.is_dir():
        raise OrchError(f'{repo.path} is not available locally: verify runs in the repository\'s main checkout')
    needs_gh = any(k == 'deploy' for k, _ in checks) or not args.sha or accepted
    name = streams.origin_name(repo)
    if needs_gh and not shutil_which('gh'):
        raise OrchError('verify needs gh for workflow runs and merge commits (gh auth login), or: pass --sha <sha> '
                        'and leave deploy_workflows empty for this environment; runs can also be read with the '
                        'session\'s GitHub tools and recorded by hand')
    if needs_gh and not name:
        raise OrchError(f'{repo.path} has no hosted origin: deploy runs and merge commits need one; pass --sha')
    if accepted:
        if not pr:
            raise OrchError(f'{wp} is ACCEPTED and has no PR link: record it (orch.py set {wp} pr <url>) or set MERGED '
                            'with evidence first')
        try:
            state, oid = verification.pr_state(name, pr)
        except RuntimeError as error:
            raise OrchError(f'{wp}: cannot read {pr}: {error}')
        if state != 'MERGED':
            raise OrchError(f'{wp} is ACCEPTED and {pr} is {state or "unknown"}, not merged: verify after the merge')
        with state_io.transaction(ws.root):
            if runtime_commands.state_version(ws) != state_version:
                raise OrchError('program state changed during PR verification; retry')
            cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='MERGED', quiet=True,
                                       evidence=f'gh pr view {pr}: MERGED at {(oid or "?")[:10]}'))
            state_version = runtime_commands.state_version(ws)
        r = dict(r, status='MERGED')
    sha = args.sha
    if not sha:
        if not pr:
            raise OrchError(f'{wp} has no PR link in the WP table: pass --sha <deployed sha>')
        try:
            sha = verification.merge_commit(name, pr)
            if env == 'prod' and branch != repo_base(module):
                sha = verification.prod_tip(repo, branch, sha)
        except RuntimeError as error:
            raise OrchError(f'{wp}: {error}; pass --sha <deployed sha>')
    url = verification.base_url(module, env)
    rows, limit = [], verification.timeout(ws.config)
    t = verification.TEXT[ws.lang]
    for kind, what in checks:
        if kind == 'deploy':
            try:
                verdict, detail = verification.deploy_run(name, what, sha, branch)
            except RuntimeError as error:
                verdict, detail = 'FAIL', f'gh: {error}'
            if verdict == 'WAIT':  # the deploy is under way: later checks would see the old version
                ws.journal(f'{wp}: verify on {env} waits for the deploy run ({detail})', wp=wp,
                           evidence='orch.py verify')
                print(f'verify {wp} --env {env}: WAIT at {sha[:10]}: {detail}; status stays {r["status"]}, '
                      'no defect; run verify again when the run has finished', file=sys.stderr)
                return 2
            rows.append({'kind': t['deploy'], 'target': what, 'exit': '—', 'output': [detail], 'verdict': verdict,
                         'deploy': True})
        elif kind == 'version':
            vurl, pattern = verification.version_source(module, env)
            verdict, detail = verification.served_version(vurl, pattern, sha, args.expect_version)
            rows.append({'kind': t['version'], 'target': vurl, 'exit': '—', 'output': [redact(detail)],
                         'verdict': verdict})
        else:
            verdict, code, output = verification.run_command(
                what, repo.local, verification.command_env(env, sha, wp, url), limit, redact)
            rows.append({'kind': t['command'], 'target': what, 'exit': code, 'output': output, 'verdict': verdict})
    failed = [x for x in rows if x['verdict'] != 'PASS']
    verdict = 'FAIL' if failed else 'PASS'
    date = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    with state_io.transaction(ws.root):
        if runtime_commands.state_version(ws) != state_version:
            raise OrchError("program state changed during external checks; retry from current files")
        reports = ws.root / 'reports'
        stem = f'verify-{wp}-{env}-{date}'
        path = reports / f'{stem}.md'
        n = 2
        while path.exists():
            path = reports / f'{stem}-{n}.md'
            n += 1
        rel = str(path.relative_to(ws.root))
        summary = (t['passed'].format(n=len(rows)) if not failed else t['failed'].format(
            n=len(failed), total=len(rows), items=', '.join(f'{x["kind"]} `{x["target"]}`' for x in failed)))
        note = '' if env == 'test' or r['status'] in ('VERIFIED_TEST', 'PROD', 'DONE') else \
            t['no_vtest'].format(status=r['status'])
        template = (TEMPLATES / ws.lang / 'verify-report.md').read_text(encoding='utf-8')
        safe_edit.create(path, fill(template, {
            'WP': wp, 'ENV': env, 'SHA': sha[:12], 'DATE': today(), 'VERDICT': verdict, 'SUMMARY': summary + note,
            'BRANCH': branch, 'BASE_URL': url or '—', 'STATUS': r['status'], 'ROWS': verification.table(rows, ws.lang)}))
        if not failed:
            if r['status'] in verification.LATER[env]:
                ws.journal(f'{wp}: verified on {env} at {sha[:10]} (status {r["status"]} kept)', wp=wp, evidence=rel)
            else:
                cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text=target, quiet=True,
                                           evidence=f'verify --env {env} {sha[:10]}: {rel}'))
            print(f'verify {wp} --env {env}: PASS at {sha[:10]} ({summary}); status '
                  f'{r["status"] if r["status"] in verification.LATER[env] else target}')
            print(f'report: {path}')
            print('next: the live scenario of the package (verify mode), recorded in the report\'s "Live scenario" section')
            return 0
        bug = write_bug(ws, wp, module, env, sha, rel, failed)
        ws.journal(f'{wp}: verification on {env} failed at {sha[:10]}: {summary}', wp=wp, evidence=f'{rel}; {bug}')
        owner = None
        deploy_failed = [x for x in failed if x.get('deploy')]
        if deploy_failed:
            owner = (f'{wp}: no successful deploy run on {env} for {sha[:10]} ({deploy_failed[0]["output"][0]}); a deploy '
                     f'or a re-run needs your rights ; expected: the run succeeds, then orch.py verify {wp} --env {env}')
            if not any(item['text'].startswith(f'{wp}: no successful deploy run on {env}') for item in open_owner_items(ws)):
                cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='R', text=owner, where=rel,
                                             quiet=True))
        print(f'verify {wp} --env {env}: FAIL at {sha[:10]} ({summary}); status stays {r["status"]}', file=sys.stderr)
        print(f'report: {path}', file=sys.stderr)
        print(f'defect: {ws.root / bug}', file=sys.stderr)
        if owner:
            print(f'owner item: {owner}', file=sys.stderr)
        return 1


def verify_list(ws):
    """Packages waiting for verification: merged or on the stand without VERIFIED_TEST, and verified on test."""
    rows = ws.wp_rows()
    found = False
    for wp, r in rows.items():
        if r['status'] in ('MERGED', 'TEST-APPLIED', 'DEPLOYED_TEST', 'VERIFYING'):
            env = 'test'
        elif r['status'] == 'VERIFIED_TEST':
            env = 'prod'
        else:
            continue
        try:
            _, module, _ = wp_context(ws, wp)
        except OrchError:
            continue
        found = True
        hint = f'orch.py verify {wp} --env {env}'
        if env == 'prod':
            hint += ' (after the owner\'s release)'
        if not verify_plan(ws, module, env):
            hint += f' - configure verify_{env}, version_url or deploy_workflows first'
        print(f'{wp} ({r["status"]}): {hint}')
    if not found:
        print('verify: no package waits for verification')
    return 0


REPORT_ID = re.compile(r'PLUGIN-BUG-(\d+)\.md$')


def plugin_bugs(ws):
    """{id: path} of the workspace's plugin defect records, in number order."""
    found = {}
    for path in (ws.root / 'bugs').glob('PLUGIN-BUG-*.md'):
        match = REPORT_ID.search(path.name)
        if match:
            found[int(match.group(1))] = path
    return {f'PLUGIN-BUG-{n}': found[n] for n in sorted(found)}


def record_field(text, label):
    match = re.search(r'^\| ' + re.escape(label) + r' \| (.*?) \|$', text, re.M)
    return match.group(1).strip() if match else None


def report_policy(ws):
    """(auto, problem): bug_reports auto needs a recorded owner decision (bug_reports_decision: D-n)."""
    mode = ws.config.get('bug_reports') or 'confirm'
    if mode != 'auto':
        return False, None
    decision = str(ws.config.get('bug_reports_decision') or '')
    if not re.fullmatch(r'D-\d+', decision):
        return False, 'bug_reports: auto needs bug_reports_decision: D-n (the owner\'s recorded decision)'
    try:
        ids = [plain_id(r['id']) for r in ws.table(ws.decisions, 'decisions')[2]]
    except (OrchError, FileNotFoundError):
        ids = []
    if decision not in ids:
        return False, f'bug_reports_decision {decision} is not in decisions.md'
    return True, None


def report_context(ws):
    repos, modules, _ = ws.streams()
    names = plugin_report.private_names(ws.config, repos, modules, ws.root, ws.git_top)
    terms = plugin_report.load_terms(ws.root, ws.git_top, *{m.repo.local for m in modules.values()})
    return repos, modules, names, terms


def cmd_report(args):
    ws = Workspace(find_workspace(args.workspace))
    if args.status:
        return report_status(ws)
    repos, modules, names, terms = report_context(ws)
    if args.security:
        print('A security problem is never a public Issue: report it privately as SECURITY.md says '
              f'(https://github.com/{plugin_report.REPOSITORY}/security/advisories/new). Nothing was written.')
        return 0
    if args.apply:
        return report_apply(ws, args, names, terms)
    return report_check(ws, args, repos, modules, names, terms)


def report_check(ws, args, repos, modules, names, terms):
    facts = plugin_report.environment_facts(SKILL_DIR, ws.config)
    if args.log:
        problem = plugin_report.log_problem(Path(args.log).expanduser())
        if problem:
            raise OrchError(f'--log refused: {problem}; copy only the failing command\'s output into a file')
        lines = Path(args.log).expanduser().read_text(encoding='utf-8', errors='replace').splitlines()
    else:
        lines = [f'{r["date"]} {r["wp"]} {r["event"]}' for r in ws.table(ws.status, 'journal')[2][:10]]
    lines = lines[:plugin_report.OUTPUT_LINES]

    def clean(text):
        return plugin_report.anonymize(text, names, terms, SECRET_PATTERNS)

    output = clean('\n'.join(lines)) or '—'
    # The journal is context, not the error: without --log the fingerprint comes from the title.
    error = plugin_report.first_error_line(output.split('\n')) if args.log else ''
    title = clean(' '.join((args.title or error or 'plugin defect').split()))[:100]
    fp = plugin_report.fingerprint(facts['plugin'], facts['version'], error or title)
    expected_actual = clean(args.expected_actual or 'Expected: as the mode documentation says. Actual: the output above.')
    workaround = clean(args.workaround or 'none found yet')
    existing = plugin_bugs(ws)
    with state_io.transaction(ws.root):
        number = runtime_commands.allocate(ws, 'PLUGIN-BUG', max([int(i.split('-')[-1]) for i in existing], default=0) + 1)
        rid = f'PLUGIN-BUG-{number}'
        issue_rel = f'bugs/{rid}.issue.md'
        values = {'ID': rid, 'TITLE': title, 'DATE': today(), 'PLUGIN': facts['plugin'], 'VERSION': facts['version'],
                  'CLAUDE': clean(facts['claude']), 'OS': facts['os'], 'PYTHON': facts['python'], 'SHELL': facts['shell'],
                  'SHAPE': plugin_report.workspace_shape(ws.config, repos, modules), 'FINGERPRINT': fp,
                  'COMMAND': clean(args.command or '—'), 'OUTPUT': output, 'EXPECTED_ACTUAL': expected_actual,
                  'WORKAROUND': workaround, 'ISSUE_FILE': issue_rel}
        record = fill((TEMPLATES / ws.lang / 'plugin-bug.md').read_text(encoding='utf-8'), values)
        issue = fill((TEMPLATES / 'issue-body.md').read_text(encoding='utf-8'), values)
        problems = plugin_report.leaks(record + '\n' + issue, names, terms, SECRET_PATTERNS)
        if problems:
            raise OrchError('the report still looks private after anonymization (' + ', '.join(sorted(set(problems)))
                            + '); nothing was written: shorten --log or --command to the failing lines')
        safe_edit.create(ws.root / f'bugs/{rid}.md', record)
        safe_edit.create(ws.root / issue_rel, issue)
        ws.journal(f'plugin defect {rid} recorded (anonymized): {title}', evidence=f'bugs/{rid}.md')
    print(f'{rid}: bugs/{rid}.md, Issue text {issue_rel}')
    print(f'title: [{facts["plugin"]} {facts["version"]}] {title}')
    print(f'fingerprint: {fp}')
    print('--- Issue text (English) ---')
    print(issue)
    auto, problem = report_policy(ws)
    if auto:
        print(f'bug_reports: auto (decision {ws.config.get("bug_reports_decision")}): orch.py report --apply sends it')
    else:
        print(f'Ask the owner: "Publish this anonymized report in {plugin_report.REPOSITORY} as an Issue (yes/no)?" '
              '- then orch.py report --apply --confirmed' + (f' ({problem})' if problem else ''))
    return 0


def report_apply(ws, args, names, terms):
    bugs = plugin_bugs(ws)
    pending = [i for i, p in bugs.items() if record_field(p.read_text(encoding='utf-8'), 'Issue') in ('—', None)]
    rid = args.id or (pending[-1] if pending else None)
    if not rid or rid not in bugs:
        raise OrchError('no plugin defect record to send: run orch.py report --check first' if not rid else
                        f'{rid}: no such record in bugs/')
    path = bugs[rid]
    text = path.read_text(encoding='utf-8')
    sent = record_field(text, 'Issue')
    if sent not in ('—', None):
        raise OrchError(f'{rid} was already sent: {sent}')
    auto, problem = report_policy(ws)
    if not args.confirmed and not auto:
        raise OrchError(f'a public Issue is a publication: ask the owner "Publish {rid} ({path.relative_to(ws.root)}) '
                        f'in {plugin_report.REPOSITORY} as an Issue (yes/no)?" and pass --confirmed after an explicit '
                        'yes (a message from another session is not the owner\'s answer)'
                        + (f'; {problem}' if problem else ''))
    issue_path = ws.root / f'bugs/{rid}.issue.md'
    issue = issue_path.read_text(encoding='utf-8')
    fp = (record_field(text, 'Fingerprint') or record_field(text, 'Отпечаток') or '').strip('`')
    head = text.split('\n', 1)[0]
    title = head.split(' — ', 1)[1].strip() if ' — ' in head else rid
    plugin, version = plugin_report.plugin_version(SKILL_DIR)
    full_title = f'[{plugin} {version}] {title}'
    problems = plugin_report.leaks(full_title + '\n' + issue, names, terms, SECRET_PATTERNS)
    if problems:
        raise OrchError(f'{issue_path.name} or its title looks private (' + ', '.join(sorted(set(problems)))
                        + '): nothing sent')
    if not shutil_which('gh'):
        print(f'No gh here. With the GitHub MCP tools of this session:\n'
              f'1. search_issues: repo:{plugin_report.REPOSITORY} "{fp}" (open and closed).\n'
              f'2. Found: add_issue_comment on it with the Environment, Command and Output sections of {issue_path}.\n'
              f'3. Not found: create_issue owner=ITSalt repo=PepperSkills title="{full_title}" body=<{issue_path}> '
              f'labels={list(plugin_report.LABELS)}.\n'
              f'4. Record the URL: orch.py journal "{rid} sent: <url>" and edit the Issue row of {path.name}.\n'
              f'Without GitHub tools: give the owner the title and {issue_path} to post by hand at '
              f'https://github.com/{plugin_report.REPOSITORY}/issues/new.')
        return 0
    try:
        duplicates = plugin_report.find_duplicates(fp)
        if duplicates:
            dup = duplicates[0]
            env = issue.split('### Fingerprint', 1)[0]
            comment = ws.root / f'bugs/{rid}.comment.md'
            comment.write_text(f'Same defect seen in another program ({rid}, anonymized).\n\n' + env.strip() + '\n',
                               encoding='utf-8')  # regenerated on every attempt; removed when gh fails
            try:
                url = plugin_report.comment_issue(dup['number'], comment)
            except plugin_report.ReportError:
                comment.unlink()
                raise
            what, missing = (f'comment on #{dup["number"]} ({str(dup.get("state", "?")).lower()}, '
                             f'{dup.get("url", "")})'), False
        else:
            url, missing = plugin_report.create_issue(full_title, issue_path)
            what = 'new Issue'
    except plugin_report.ReportError as error:
        raise OrchError(f'gh failed: {error}; nothing recorded')
    safe_edit.replace_once(path, '| Issue | — |', f'| Issue | {cell(url)} |')
    ws.journal(f'{rid} sent to {plugin_report.REPOSITORY}: {what}', evidence=url)
    cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='R', where=str(path.relative_to(ws.root)),
                                 quiet=True, text=f'FYI, no action needed: plugin defect {rid} reported ({what}): {url} ; '
                                                  'close this item when read'))
    print(f'{rid}: {what}: {url}')
    if missing:
        print(f'note: labels from-agent/needs-triage are missing in {plugin_report.REPOSITORY}; the maintainer creates '
              'them: gh label create from-agent --repo ITSalt/PepperSkills && gh label create needs-triage '
              '--repo ITSalt/PepperSkills')
    return 0


def report_status(ws):
    """Plugin defects of this program with their Issues, and one line when a newer plugin version exists."""
    bugs = plugin_bugs(ws)
    for rid, path in bugs.items():
        issue = record_field(path.read_text(encoding='utf-8'), 'Issue')
        print(f'{rid}: {"Issue " + issue if issue not in ("—", None) else "not sent (orch.py report --apply)"}')
    if not bugs:
        print('report: no plugin defects recorded')
    if shutil_which('gh'):
        plugin, installed = plugin_report.plugin_version(SKILL_DIR)
        try:
            latest = plugin_report.latest_version()
        except (plugin_report.ReportError, ValueError):
            latest = ''
        if latest and plugin_report.version_key(latest) > plugin_report.version_key(installed):
            print(f'update available: {plugin} {installed} -> {latest} '
                  '(claude plugin update pepper-orchestrator@pepperskills)')
    return 0


def shlex_quote(text):
    import shlex
    return shlex.quote(text)


def cmd_overlap(args):
    ws = Workspace(find_workspace(args.workspace))
    repos, modules, errors = ws.streams()
    findings = [('declared', e) for e in errors if 'overlap' in e]
    rows = ws.wp_rows()
    live = {}
    for wp, r in rows.items():
        if r['status'] in streams.ACTIVE + ('READY',):
            try:
                live[wp] = wp_context(ws, wp)
            except OrchError as error:
                findings.append(('declared', str(error)))
    items = sorted(live.items())
    for i, (a, (ra, ma, meta_a)) in enumerate(items):
        for b, (rb, mb, meta_b) in items[i + 1:]:
            if ma.repo.key != mb.repo.key:
                continue
            for x, y in streams.overlap_outside_shared(meta_a['paths'], meta_b['paths'],
                                                       ma.repo.shared_paths):
                findings.append(('declared', f'{a} and {b}: paths overlap outside shared paths: {x} ~ {y}'))
            both = set(meta_a['shared']) & set(meta_b['shared'])
            for p in sorted(both):
                findings.append(('declared', f'{a} and {b} both declare shared path {p}: '
                                 'serialize them with the lock'))
            for res in sorted(set(meta_a['resources']) & set(meta_b['resources'])):
                if res in ma.repo.resources and not ma.repo.on_demand(res):
                    findings.append(('declared', f'{a} and {b} both declare resource {res}: '
                                     'serialize them with the lock'))
    if not args.planned:
        held = {}
        for lock in locks(ws):
            held.setdefault(lock['holder'], []).append(lock['lock'].split(':', 1)[-1])
        touched = {}
        for wp, (r, module, meta) in items:
            if r['status'] not in streams.ACTIVE or not module.repo.local.is_dir():
                continue
            branch = meta['branch']
            files = streams.branch_files(module.repo, branch) if branch else None
            if files is None:
                findings.append(('actual', f'{wp}: branch {branch or "?"} not found in {module.repo.path}'))
                continue
            for f in files:
                touched.setdefault((module.repo.key, f), []).append(wp)
            findings.extend(('actual', text) for text in file_findings(wp, meta, module.repo, files,
                                                                        held.get(wp, [])))
        for (_, f), wps in sorted(touched.items(), key=lambda kv: kv[0][1]):
            if len(wps) > 1:
                findings.append(('actual', f'{" and ".join(wps)} both change {f}'))
        if not args.no_checks:
            branches = {}
            for wp, (r, module, meta) in items:
                if r['status'] in streams.ACTIVE and meta['branch']:
                    branches.setdefault(module.repo.key, []).append(meta['branch'])
            seen = {}
            for module in modules.values():
                seen[module.repo.key] = module.repo
            seen.update({r.key: r for r in repos.values()})
            for key, repo in seen.items():
                findings.extend(('check', text) for text in run_checks(repo, branches.get(key, [])))
    if args.json:
        print(json.dumps([{'kind': k, 'finding': f} for k, f in findings], ensure_ascii=False, indent=2))
    else:
        for kind, finding in findings:
            print(f'[{kind}] {finding}')
        if not findings:
            print('overlap: none')
    return 1 if findings else 0


def cmd_worktrees(args):
    ws = Workspace(find_workspace(args.workspace))
    repos, modules, _ = ws.streams()
    seen = {m.repo.key: m.repo for m in modules.values()}
    seen.update({r.key: r for r in repos.values()})
    branches = {}
    for wp, r in ws.wp_rows().items():
        try:
            _, _, meta = wp_context(ws, wp)
        except OrchError:
            continue
        if meta['branch']:
            branches[meta['branch']] = wp
    report = []
    for repo in seen.values():
        if not repo.local.is_dir():
            report.append({'repo': repo.id, 'error': f'not found: {repo.path}'})
            continue
        for entry in streams.worktrees(repo):
            entry = {'repo': repo.id, **entry}
            entry['wp'] = branches.get(entry.get('branch'), '—')
            report.append(entry)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for e in report:
        if 'error' in e:
            print(f'{e["repo"]}: {e["error"]}')
            continue
        dirty = {True: 'dirty', False: 'clean', None: '?'}[e.get('dirty')]
        print(f'{e["repo"]} | {e.get("branch", "?")} | {dirty} | ahead {e.get("ahead", "?")} '
              f'behind {e.get("behind", "?")} | {e["wp"]} | {e["path"]}')
    return 0


def cmd_ready(args):
    """Packages whose branch is on origin: READY candidates when messages cannot arrive."""
    ws = Workspace(find_workspace(args.workspace))
    report = []
    for wp, r in ws.wp_rows().items():
        if r['status'] not in ('DISPATCHING', 'IN_PROGRESS', 'REVISE'):
            continue
        try:
            _, module, meta = wp_context(ws, wp)
        except OrchError:
            continue
        entry = {'wp': wp, 'status': r['status'], 'branch': meta['branch'], 'sha': None, 'pr': None,
                 'note': None}
        if meta['branch'] and module.repo.local.is_dir():
            heads = streams.git(module.repo.local, 'ls-remote', '--heads', 'origin', meta['branch'])
            if heads.returncode == 0 and heads.stdout.strip():
                entry['sha'] = heads.stdout.split()[0][:12]
                name = streams.origin_name(module.repo)
                if name and shutil_which('gh'):
                    prs = subprocess.run(['gh', 'pr', 'list', '--repo', name, '--head', meta['branch'],
                                          '--state', 'open', '--json', 'url,body'],
                                         text=True, capture_output=True)
                    try:
                        found = json.loads(prs.stdout or '[]')
                    except ValueError:
                        found = []
                    with_id = [pr['url'] for pr in found if wp in (pr.get('body') or '')]
                    entry['pr'] = with_id[0] if with_id else None
                    if found and not with_id:
                        entry['note'] = 'open PR without the package id in its body'
        elif meta['branch']:
            entry['note'] = f'repository {module.repo.path} is not available locally'

        report.append(entry)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for e in report:
        if e['sha']:
            where = e['pr'] or e['note'] or ('find the open PR by head branch with the package id in its body '
                                             '(gh, or the session GitHub tools)')
            print(f'{e["wp"]}: branch {e["branch"]} pushed at {e["sha"]} -> {where}')
        elif e['note']:
            print(f'{e["wp"]}: {e["note"]}; ask the owner for the PR link')
        else:
            print(f'{e["wp"]}: no pushed branch {e["branch"] or "?"} yet ({e["status"]})')
    if not report:
        print('ready: no dispatched packages')
    return 0


def shutil_which(name):
    """Find a CLI; ORCH_NO_GH=1 hides gh (offline checks, deterministic tests)."""
    import shutil
    if name == 'gh' and os.environ.get('ORCH_NO_GH') == '1':
        return None
    return shutil.which(name)


TERMINAL = ('DONE',)
PR_EVIDENCE = re.compile(r'/pull/\d+|list_pull_requests|search_pull_requests|gh pr (list|view)', re.I)


def is_terminal(status):
    return status in TERMINAL or status.startswith('CANCELLED (')


def section(text, headings):
    """Body of the first '## <heading>' found, up to the next '## '."""
    for heading in headings:
        match = re.search(r'(?m)^## ' + re.escape(heading) + r'[^\n]*\n(.*?)(?=^## |\Z)', text, re.S)
        if match:
            return match.group(1).strip()
    return ''


def completion_condition(ws):
    """(goal section, condition text or None when missing or still a template placeholder)."""
    plan = (ws.root / 'PLAN.md').read_text(encoding='utf-8') if (ws.root / 'PLAN.md').is_file() else ''
    goal = section(plan, ('Goal and completion condition', 'Цель и условие завершения', 'Goal', 'Цель'))
    match = re.search(r'(?:Completion condition|Условие завершения):\s*(.+)', goal)
    condition = match.group(1).strip() if match else None
    if condition and condition.startswith('<'):
        condition = None
    return goal, condition


def close_blockers(ws, prs_verified=None):
    """(blockers, verified, sessions): blockers by fact; verified lists what only --prs-verified clears."""
    blockers, unverified = [], []
    rows = ws.wp_rows()
    for wp, r in rows.items():
        if not is_terminal(r['status']):
            blockers.append(f'{wp} is {r["status"]}: finish it (DONE after verification) or cancel it with a reason')
    gh = shutil_which('gh')
    for wp, r in rows.items():
        try:
            _, module, meta = wp_context(ws, wp)
        except OrchError as error:
            unverified.append(f'{wp}: {error}')
            continue
        branch = meta['branch']
        url = r['pr'] if re.match(r'https?://', r['pr'] or '') else None
        if url and gh:
            state = subprocess.run(['gh', 'pr', 'view', url, '--json', 'state', '-q', '.state'], text=True,
                                   capture_output=True)
            if state.returncode:
                unverified.append(f'{wp}: cannot read {url} with gh')
            elif state.stdout.strip() == 'OPEN':
                blockers.append(f'{wp}: PR {url} is open')
        elif url:
            unverified.append(f'{wp}: recorded PR {url} cannot be checked here (no gh)')
        if not branch:
            continue
        if not module.repo.local.is_dir():
            unverified.append(f'{wp}: repository {module.repo.path} is not available here to check {branch}')
            continue
        name = streams.origin_name(module.repo)
        if name and gh:
            prs = subprocess.run(['gh', 'pr', 'list', '--repo', name, '--head', branch, '--state', 'open',
                                  '--json', 'url', '-q', '.[].url'], text=True, capture_output=True)
            if prs.returncode:
                unverified.append(f'{wp}: cannot list PRs of {branch} with gh')
            elif prs.stdout.strip():
                blockers.append(f'{wp}: open PR {prs.stdout.split()[0]} for {branch}')
            continue
        heads = streams.git(module.repo.local, 'ls-remote', '--heads', 'origin', branch)
        if heads.returncode:
            unverified.append(f'{wp}: git ls-remote failed for {branch}')
        elif heads.stdout.strip():
            unverified.append(f'{wp}: branch {branch} is still on origin and its PRs cannot be listed here')
    if unverified and not prs_verified:
        blockers.extend(f'{u}; verify with the session GitHub tools (list_pull_requests head=<branch> state=open) '
                        'or a PR URL from the owner, then pass --prs-verified "<evidence>"' for u in unverified)
    for lock in locks(ws):
        blockers.append(f'lock {lock["lock"]} is still in the lock table (holder {lock["holder"]}, waiting '
                        f'{lock["waiting"]}): release it or clear its queue')
    if ws.has_table(ws.status, 'merge'):
        for q in ws.table(ws.status, 'merge')[2]:
            if q['status'] == 'queued':
                blockers.append(f'{q["wp"]} is still queued for merge')
    for item in open_owner_items(ws):
        blockers.append(f'{item["id"]} is open: close it with a verified fact, drop it, or carry it to the backlog '
                        f'(orch.py owner carry {item["id"]} "<reason>")')
    _, modules, _ = ws.streams()
    sessions = sorted({r['session'] for r in rows.values() if r['session'] not in ('', '—')} |
                      {m.session for m in modules.values()})
    return blockers, (unverified if prs_verified else []), sessions


def workspace_dirty(ws):
    return bool(git(ws.root, 'status', '--porcelain', '--', '.', check=False).stdout.strip())


def cmd_close(args):
    ws = Workspace(find_workspace(args.workspace))
    state_version = runtime_commands.state_version(ws)
    in_git = streams.git_toplevel(ws.root) is not None
    if ws.closed:
        if args.apply and in_git and workspace_dirty(ws):
            print('program is closed but not committed yet: finishing the commit and the archive')
            finish_close(ws, args)
            return 0
        print(f'program {ws.config.get("program")} is already closed')
        return 0
    if args.prs_verified and not PR_EVIDENCE.search(args.prs_verified):
        raise OrchError('--prs-verified needs concrete evidence: a PR URL with its state (closed/merged), or the '
                        'output of list_pull_requests / gh pr list for the branch with state=open')
    goal, condition = completion_condition(ws)
    if not condition and not args.goal_confirmed:
        raise OrchError('PLAN.md has no filled completion condition ("Completion condition: ..." in "Goal and '
                        'completion condition"); fill it, or pass --goal-confirmed "<evidence the goal is reached>"')
    blockers, verified, sessions = close_blockers(ws, args.prs_verified)
    for item in verified:
        print(f'note: {item}; verified: {args.prs_verified}')
    if blockers:
        for blocker in blockers:
            print(f'close blocked: {blocker}', file=sys.stderr)
        return 1
    print('close check: no blockers')
    print('module sessions to close: ' + (', '.join(sessions) or 'none'))
    if args.check:
        return 0
    # Everything the commit and the archive need is checked before anything changes.
    if in_git and not args.no_commit:
        errors = lint(ws)
        if errors:
            raise OrchError('lint failed; nothing changed: ' + '; '.join(errors))
        commit_preconditions(ws)
    with state_io.transaction(ws.root):
        if runtime_commands.state_version(ws) != state_version:
            raise OrchError("program state changed during external checks; retry from current files")
        rows = ws.wp_rows()
        date = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
        plan = (ws.root / 'PLAN.md').read_text(encoding='utf-8') if (ws.root / 'PLAN.md').is_file() else ''
        risks = section(plan, ('Risks', 'Риски')) or '—'
        packages = '\n'.join(row([wp, r['module'], r['title'], r['status'], r['pr'], '<release or merge commit>'])
                             for wp, r in sorted(rows.items()))
        decisions = '\n'.join(f'- {r["id"]} ({r["date"]}): {r["text"]}' for r in ws.table(ws.decisions, 'decisions')[2]
                              if r['id'].startswith('D-')) or '—'
        backlog_path = ws.root / 'backlog.md'
        backlog = ('\n'.join(f'- {r["id"]}: {r["item"]} (from {r["origin"]}; {r["reason"]})'
                             for r in ws.table(backlog_path, 'backlog')[2]) if backlog_path.is_file() else '') or '—'
        checks = []
        if verified:
            checks.append(f'PRs without gh: {"; ".join(verified)} - evidence: {args.prs_verified}')
        if not condition:
            checks.append(f'completion condition not written in PLAN.md; goal confirmed by: {args.goal_confirmed}')
        name = f'closeout-{date}.md'
        report = ws.root / 'reports' / name
        template = (TEMPLATES / ws.lang / 'closeout.md').read_text(encoding='utf-8')
        safe_edit.create(report, fill(template, {
            'PROGRAM_TITLE': ws.config.get('title') or ws.config.get('program'), 'PROGRAM': ws.config.get('program'),
            'DATE': today(), 'GOAL': goal or '—', 'SUMMARY': args.summary or '<result against the completion condition>',
            'PACKAGES': packages or '| — | — | — | — | — | — |', 'DECISIONS': decisions, 'BACKLOG': backlog,
            'RISKS': risks, 'SESSIONS': ', '.join(sessions) or '—', 'CHECKS': '\n'.join(f'- {c}' for c in checks) or '—'}))
        set_state(ws, 'closed')
        status_text = ws.status.read_text(encoding='utf-8')
        first = status_text.split('\n', 1)[0]
        banner = {'en': f'> **Closed {today()}.** Closeout: [reports/{name}](reports/{name}). A new goal is a new program.',
                  'ru': f'> **Закрыта {today()}.** Итог: [reports/{name}](reports/{name}). Новая цель — новая программа.'}
        safe_edit.replace_once(ws.status, first + '\n', first + '\n\n' + banner[ws.lang] + '\n')
        if verified:
            ws.journal('PRs verified without gh: ' + '; '.join(verified), evidence=args.prs_verified)
        if not condition:
            ws.journal('completion condition confirmed without PLAN.md text', evidence=args.goal_confirmed)
        ws.journal('program closed', evidence=f'reports/{name}')
        print(f'closeout: {report}')
    if in_git and not args.no_commit:
        finish_close(ws, args)
    return 0


def finish_close(ws, args):
    """Commit the closeout, then the in-repo archive items (tied to that commit) or the archive move."""
    ws = Workspace(ws.root)
    program = ws.config.get('program')
    branch = commit_preconditions(ws)
    push = ws.config.get('push_after_milestone')
    git(ws.root, 'add', '-A', '--', '.')
    git(ws.root, 'commit', '-q', '-m', f'{program}: close program', '--', '.')
    sha = git(ws.root, 'rev-parse', 'HEAD').stdout.strip()
    print(f'commit: {sha[:10]}')
    if push and not push_branch(ws, ws.root, branch):
        raise OrchError('push failed after closing; fix the remote and run close --apply again')
    if ws.in_repo:
        archive_items(ws, sha)
        git(ws.root, 'add', '-A', '--', '.')
        git(ws.root, 'commit', '-q', '-m', f'{program}: archive steps for the owner', '--', '.')
        if push:
            push_branch(ws, ws.root, branch)
        return
    top = streams.git_toplevel(ws.root)
    if top == ws.root.resolve():
        print(f'note: the workspace is the root of its repository; archive it yourself (it stays at {ws.root})')
        return
    if ws.root.parent.name == '_archive':
        return
    target = ws.root.parent / '_archive' / ws.root.name
    if target.exists():
        print(f'note: {target} exists; the workspace stays at {ws.root}')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    moved = streams.git(ws.root.parent, 'mv', str(ws.root), str(target))
    if moved.returncode:
        raise OrchError(f'git mv to the archive failed: {moved.stderr.strip()}')
    streams.git(target, 'commit', '-q', '-m', f'{program}: archive workspace', '--', str(ws.root), str(target))
    print(f'archived: {target}')
    print(f'closeout now: {target / "reports"}')
    if push:
        push_branch(ws, target, branch)


def archive_items(ws, sha):
    """In-repo archive steps for the owner, tied to the closeout commit; the plugin never runs them."""
    program, branch = ws.config.get('program'), ws.workspace_branch
    tag = f'orch-{program}-closed-{today().replace("-", "")}'
    command = f'git push origin {sha}:refs/tags/{tag} && git push origin --delete {branch}'
    cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='R', where='reports/closeout',
                                 allow_closed=True,
                                 text=f'Archive the workspace branch (from any clone of the repository): {command} ; '
                                      f'expected: tag {tag} on origin at {sha[:10]}, branch {branch} deleted'))
    cmd_owner(argparse.Namespace(workspace=str(ws.root), action='add', target='P', where='reports/closeout',
                                 allow_closed=True,
                                 text='Keep the workspace as history in docs/ of the base branch through a PR? '
                                      '(a) yes, one PR copying the workspace (b) no, the tag is enough ; '
                                      'recommendation: (b)'))


def set_state(ws, state):
    config = ws.root / 'orch.yaml'
    text = config.read_text(encoding='utf-8')
    current = re.search(r'(?m)^state: .*$', text)
    if current:
        safe_edit.replace_once(config, current.group(0) + '\n', f'state: {state}\n')
    else:
        program_line = re.search(r'(?m)^program: .*$', text).group(0)
        safe_edit.replace_once(config, program_line + '\n', f'{program_line}\nstate: {state}\n')


def cmd_reopen(args):
    ws = Workspace(find_workspace(args.workspace))
    if not ws.closed:
        raise OrchError(f'program {ws.config.get("program")} is not closed')
    set_state(ws, 'active')
    text = ws.status.read_text(encoding='utf-8')
    banner = re.search(r'(?m)^> \*\*(Closed|Закрыта) [^\n]*\n', text)
    if banner:
        note = {'en': f'> Reopened {today()}: {cell(args.reason)}\n', 'ru': f'> Открыта снова {today()}: {cell(args.reason)}\n'}
        safe_edit.replace_once(ws.status, banner.group(0), banner.group(0) + note[ws.lang])
    ws.journal(f'program reopened: {args.reason}', evidence='orch.py reopen')
    print(f'program {ws.config.get("program")} reopened')
    if ws.root.parent.name == '_archive':
        print(f'note: the workspace is in the archive; to move it back: git mv {ws.root} '
              f'{ws.root.parent.parent / ws.root.name}')
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog='orch.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--workspace', help='workspace directory (contains orch.yaml)')
    # Also accepted after the subcommand; SUPPRESS keeps the global value when absent.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--workspace', default=argparse.SUPPRESS,
                        help='workspace directory (contains orch.yaml)')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('init', parents=[common], help='create a program workspace')
    p.add_argument('program')
    p.add_argument('--dir', help='workspace directory (default: features/<program>)')
    p.add_argument('--title')
    p.add_argument('--tag')
    p.add_argument('--lang', choices=LANGUAGES, required=True,
                   help="owner's language for owner-facing files; ask the owner")
    p.add_argument('--module', action='append', metavar='ID=REPO[@BASE]',
                   help='module that is a whole repository (0.1.0 form)')
    p.add_argument('--repo', action='append', metavar='ID=PATH[@BASE]',
                   help='repository shared by several modules')
    p.add_argument('--area', action='append', metavar='ID=REPO_ID:GLOB[,GLOB]',
                   help='module that is an area (section) of a --repo')
    p.add_argument('--domain', action='append', metavar='ID=REPO_ID:GLOB[,GLOB]',
                   help='module that is a domain of a --repo')
    p.add_argument('--in-repo', metavar='REPO_ID',
                   help='workspace inside this repository on branch orch/<program>, in a deploy-ignored '
                        'directory (session kind still comes from --sessions)')
    p.add_argument('--base', help='base branch of the --in-repo repository (default: origin HEAD)')
    p.add_argument('--sessions', choices=('local', 'cloud'),
                   help='required, the owner\'s explicit choice: module sessions run locally (recommended) or in the cloud')
    p.add_argument('--client', choices=('claude', 'codex'), default='claude')
    p.add_argument('--cloud-environment', '--cloud-env', dest='cloud_environment', metavar='NAME',
                   help='name of the owner\'s cloud environment, required with --sessions cloud (no variable values)')
    p.add_argument('--shell', choices=session_settings.SHELLS,
                   help='shell of the start commands (asked on Windows; default bash)')
    p.add_argument('--permission-mode', choices=session_settings.PERMISSION_MODES,
                   help='required, the owner\'s explicit choice: permission mode of the sessions (auto recommended)')
    p.add_argument('--deploy-override', metavar='D-n',
                   help='owner decision that accepts an unverifiable deploy check or an unsafe --dir')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('new-wp', parents=[common], help='create a work package')
    p.add_argument('module')
    p.add_argument('slug')
    p.add_argument('--title')
    p.add_argument('--request-id', help='stable allocator request key for retry')
    p.set_defaults(func=cmd_new_wp)

    p = sub.add_parser('set', parents=[common], help='edit one cell of a WP row')
    p.add_argument('wp')
    p.add_argument('column', help=', '.join(SETTABLE))
    p.add_argument('text')
    p.add_argument('--evidence', help='journal evidence for a status change')
    p.set_defaults(func=cmd_set)

    p = sub.add_parser('model', parents=[common], help='set the implementer model, effort and reason of a package')
    p.add_argument('wp')
    p.add_argument('model', help='sonnet | opus | fable | haiku | opusplan | claude-...')
    p.add_argument('--effort', help='low | medium | high | xhigh | max')
    p.add_argument('--reason', required=True, help='one line: why this model')
    p.set_defaults(func=cmd_model)

    p = sub.add_parser('cloud-env', parents=[common], help='record the owner\'s cloud environment name')
    p.add_argument('name')
    p.add_argument('--module', help='only for this module')
    p.set_defaults(func=cmd_cloud_env)

    p = sub.add_parser('journal', parents=[common], help='add a journal line on top')
    p.add_argument('event')
    p.add_argument('--wp')
    p.add_argument('--evidence')
    p.set_defaults(func=cmd_journal)

    p = sub.add_parser('owner', parents=[common], help='owner queue: add, close, drop')
    p.add_argument('action', choices=('add', 'close', 'drop', 'carry'))
    p.add_argument('target', help='R|P for add; item id for close/drop/carry')
    p.add_argument('text')
    p.add_argument('--where', help='where the item is described')
    p.set_defaults(func=cmd_owner)

    p = sub.add_parser('queue', parents=[common], help='open owner items')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser('decide', parents=[common], help='append D-n, A-n or Q-n to decisions.md')
    p.add_argument('kind', help='D, A or Q')
    p.add_argument('text')
    p.add_argument('--source')
    p.add_argument('--closes', help='owner question P-n answered by this decision')
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser('lint', parents=[common], help='workspace integrity checks')
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser('commit', parents=[common], help='lint, commit the workspace, push if configured')
    p.add_argument('message')
    p.add_argument('--no-push', action='store_true')
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser('dispatch', parents=[common], help='check, take locks, print the start command')
    p.add_argument('wp')
    p.add_argument('--live', action='store_true', help='print a TASK line for a live session')
    p.add_argument('--dry-run', action='store_true', help='only check; change nothing')
    p.add_argument('--inline', action='store_true',
                   help='cloud module: append the whole package text to the prompt')
    p.add_argument('--no-settings', action='store_true',
                   help='local module: start command without --settings (the pre-0.6.0 form)')
    p.set_defaults(func=cmd_dispatch)

    p = sub.add_parser('verify', parents=[common], help='verify a package on test or prod by facts')
    p.add_argument('wp', nargs='?')
    p.add_argument('--env', choices=verification.ENVS)
    p.add_argument('--sha', help='expected deployed SHA (default: the merge commit of the package PR, through gh)')
    p.add_argument('--expect-version', help='package version the version_url may serve instead of the SHA')
    p.add_argument('--dry-run', action='store_true', help='print the plan; run nothing, write nothing')
    p.add_argument('--list', action='store_true', help='packages waiting for verification')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('report', parents=[common], help='anonymized report of a plugin defect; Issue on confirmation')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='collect facts, anonymize, write bugs/PLUGIN-BUG-n.md')
    mode.add_argument('--apply', action='store_true', help='search duplicates, then comment or create the Issue')
    mode.add_argument('--status', action='store_true', help='recorded plugin defects and a newer plugin version')
    mode.add_argument('--security', action='store_true', help='a security problem: never a public Issue')
    p.add_argument('--command', help='the command that failed')
    p.add_argument('--log', help='file with its output (first 30 lines are used)')
    p.add_argument('--title', help='short title (default: the first error line)')
    p.add_argument('--expected-actual', help='expected and actual behaviour, one or two sentences')
    p.add_argument('--workaround', help='the workaround used, if any')
    p.add_argument('--id', help='record to send (default: the latest not sent)')
    p.add_argument('--confirmed', action='store_true', help='the owner explicitly said yes to publishing')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('settings', parents=[common],
                       help='write orchestration/settings/<name>.json for session start commands')
    p.add_argument('target', help='module id, all, or orchestrator')
    p.set_defaults(func=cmd_settings)

    p = sub.add_parser('ready', parents=[common], help='pushed branches of dispatched packages (READY by branch)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_ready)

    p = sub.add_parser('overlap', parents=[common], help='path overlaps and repository checks (read-only)')
    p.add_argument('--planned', action='store_true', help='declared paths only, no git')
    p.add_argument('--no-checks', action='store_true', help='skip repository checks')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_overlap)

    p = sub.add_parser('lock', parents=[common], help='locks on shared paths and resources')
    p.add_argument('action', choices=('acquire', 'release', 'list'))
    p.add_argument('name', nargs='?', help='resource or shared path (repo:name or name)')
    p.add_argument('--wp', help='holder work package')
    p.add_argument('--repo', help='repository id when --wp does not identify it')
    p.add_argument('--note')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_lock)

    p = sub.add_parser('merge', parents=[common], help='merge queue: add, done, drop, list')
    p.add_argument('action', choices=('add', 'done', 'drop', 'list'))
    p.add_argument('wp', nargs='?')
    p.add_argument('--pr')
    p.add_argument('--evidence')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser('worktrees', parents=[common], help='worktrees of every repository (read-only)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_worktrees)

    p = sub.add_parser('review-start', parents=[common],
                       help='automatic findings, report skeleton and clone command for a review round')
    p.add_argument('wp')
    p.add_argument('--ref', help='branch or SHA to review (default: the package branch)')
    p.add_argument('--pr', help='PR URL, recorded in the WP row')
    p.add_argument('--since', help='previous reviewed SHA: prints the revision diff command')
    p.add_argument('--round', type=int, help='resubmission number (report file suffix -rN)')
    p.add_argument('--no-fetch', action='store_true',
                   help='do not fetch origin (by default review-start updates remote-tracking refs)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_review_start)

    p = sub.add_parser('close', parents=[common], help='program completion: --check or --apply')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='list blockers only')
    mode.add_argument('--apply', action='store_true', help='closeout report, state: closed, commit')
    p.add_argument('--summary', help='result against the completion condition (for the closeout report)')
    p.add_argument('--prs-verified', metavar='EVIDENCE',
                   help='PRs of branches still on origin were verified closed without gh (how)')
    p.add_argument('--no-commit', action='store_true', help='do not commit or archive')
    p.add_argument('--goal-confirmed', metavar='EVIDENCE',
                   help='close although PLAN.md has no written completion condition (how the goal was verified)')
    p.set_defaults(func=cmd_close)

    p = sub.add_parser('reopen', parents=[common], help='make a closed program active again')
    p.add_argument('reason')
    p.set_defaults(func=cmd_reopen)

    p = sub.add_parser('upgrade', parents=[common], help='add 0.2.0 tables to a 0.1.0 status.md')
    p.set_defaults(func=cmd_upgrade)
    runtime_commands.add_parsers(sub, common)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return runtime_commands.invoke(args)
    except (OrchError, safe_edit.EditError, streams.StreamError, state_io.StateError,
            id_allocator.AllocationError, project_instructions.InstructionError,
            codex_transport.TransportError) as error:
        print(f'orch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
