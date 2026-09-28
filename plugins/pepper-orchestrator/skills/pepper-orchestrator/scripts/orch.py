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

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / 'templates'
LANGUAGES = ('en', 'ru')

STATUSES = ('DRAFT', 'READY', 'DISPATCHING', 'IN_PROGRESS', 'REVIEW', 'REVISE', 'ACCEPTED',
            'MERGED', 'TEST-APPLIED', 'DEPLOYED_TEST', 'VERIFYING', 'PROD', 'DONE')
REASON_STATUSES = ('BLOCKED', 'CANCELLED')

# Machine markers: tables are located by these comments, never by localized headings.
TABLES = {
    'wp': ('<!-- orch:wp -->', ('wp', 'module', 'title', 'status', 'session', 'pr', 'updated')),
    'owner': ('<!-- orch:owner -->', ('id', 'text', 'where', 'opened', 'closed')),
    'journal': ('<!-- orch:journal -->', ('date', 'wp', 'event', 'evidence')),
    'decisions': ('<!-- orch:decisions -->', ('id', 'date', 'text', 'source')),
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
    re.compile(r'(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*'
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
    return dt.date.today().isoformat()


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%MZ')


def cell(text):
    return ' '.join(str(text).split()).replace('|', '\\|') or '—'


def row(values):
    return '| ' + ' | '.join(cell(v) for v in values) + ' |'


def split_row(line):
    parts = re.split(r'(?<!\\)\|', line.strip())
    if len(parts) < 3 or parts[0].strip() or parts[-1].strip():
        return None
    return [p.strip() for p in parts[1:-1]]


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
    candidates = sorted(cwd.glob('features/*/orch.yaml'))
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


def cmd_init(args):
    program = args.program
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', program):
        raise OrchError('program must match [a-z0-9][a-z0-9-]*')
    lang = args.lang
    root = Path(args.dir or Path('features') / program).expanduser()
    if root.exists() and any(root.iterdir()):
        raise OrchError(f'{root} exists and is not empty')
    tag = (args.tag or program.split('-')[0]).upper()
    title = args.title or program
    base = {'PROGRAM': program, 'PROGRAM_TITLE': title, 'TAG': tag, 'LANG': lang,
            'COORDINATOR': f'{program}-coord', 'DATE': today()}
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
    }
    module_rows = '\n'.join(row([m['id'], m['repo'], m['base'], m['session']]) for m in modules)
    for rel, template in files.items():
        text = template.read_text(encoding='utf-8')
        text = text.replace('{{MODULE_ROWS}}\n', module_rows + '\n' if module_rows else '')
        text = fill(text, base)
        safe_edit.create(root / rel, text)
    safe_edit.create(root / 'orch.yaml', render_config(base, modules))
    safe_edit.create(root / '.gitignore', safe_edit.BACKUP_DIR_NAME + '/\n')
    ws = Workspace(root)
    ws.journal(f'workspace created ({lang})', evidence='orch.py init')
    print(f'workspace: {root}')
    return 0


def render_config(base, modules):
    title = json.dumps(base['PROGRAM_TITLE'], ensure_ascii=False)
    text = fill((TEMPLATES / 'orch.yaml').read_text(encoding='utf-8'),
                {**base, 'PROGRAM_TITLE_YAML': title})
    if modules:
        blocks = []
        for m in modules:
            blocks.append('\n'.join([
                f'  - id: {m["id"]}',
                f'    repo: {m["repo"]}',
                f'    base: {m["base"]}',
                f'    session: {m["session"]}',
                '    tests: []',
            ]))
        text = text.replace('modules: []\n', 'modules:\n' + '\n'.join(blocks) + '\n')
    return text


def cmd_new_wp(args):
    ws = Workspace(find_workspace(args.workspace))
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
    wp = f'{prefix}{max(numbers, default=0) + 1:02d}'
    path = ws.wp_dir / f'{wp}-{args.slug}.md'
    title = args.title or args.slug.replace('-', ' ')
    program = ws.config.get('program', 'program')
    branch = f'{program}/{wp.lower()}-{args.slug}'
    session = module.get('session') or f'{program}-{mod}'
    mapping = {'WP': wp, 'WP_TITLE': title, 'MODULE': mod, 'REPO': module.get('repo', ''),
               'BASE': module.get('base', 'main'), 'BRANCH': branch, 'SESSION': session,
               'TAG': ws.tag, 'WP_PATH': str(path.resolve()), 'DATE': today(),
               'COORDINATOR': ws.config.get('coordinator_session') or f'{program}-coord'}
    template = ws.wp_dir / '_TEMPLATE.md'
    safe_edit.create(path, fill(template.read_text(encoding='utf-8'), mapping))
    link = f'[{wp}](work-packages/{path.name})'
    line = row([link, mod, title, 'DRAFT', session, '—', today()])
    ws.rewrite_table(ws.status, 'wp', lambda body: body + [line])
    ws.journal(f'{wp} created (DRAFT)', wp=wp, evidence=f'work-packages/{path.name}')
    print(f'{wp} {path}')
    return 0


def cmd_set(args):
    ws = Workspace(find_workspace(args.workspace))
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
    print(f'{args.wp} {column} = {value}')
    return 0


def _has_wp(ws, wp):
    _, _, rows = ws.table(ws.status, 'wp')
    count = sum(1 for r in rows if plain_id(r['wp']) == wp)
    if count != 1:
        raise OrchError(f'{wp}: expected exactly one row in the WP table, found {count}')
    return True


def cmd_journal(args):
    ws = Workspace(find_workspace(args.workspace))
    ws.journal(args.event, wp=args.wp or '—', evidence=args.evidence or '—')
    print('journal: ok')
    return 0


def next_id(ids, prefix):
    numbers = [int(m.group(1)) for i in ids if (m := re.fullmatch(prefix + r'-(\d+)', i))]
    return f'{prefix}-{max(numbers, default=0) + 1}'


def cmd_owner(args):
    ws = Workspace(find_workspace(args.workspace))
    _, _, rows = ws.table(ws.status, 'owner')
    if args.action == 'add':
        kind = args.target.upper()
        if kind not in ('R', 'P'):
            raise OrchError('owner add takes R (action) or P (question)')
        new = next_id([plain_id(r['id']) for r in rows], kind)
        cells = [new, cell(args.text), cell(args.where or '—'), today(), '']
        line = '| ' + ' | '.join(cells) + ' |'
        ws.rewrite_table(ws.status, 'owner', lambda body: body + [line])
        ws.journal(f'{new} opened for owner', evidence=args.where or '—')
        print(new)
        return 0
    target = args.target.upper()
    matches = [r for r in rows if plain_id(r['id']) == target]
    if len(matches) != 1:
        raise OrchError(f'{target}: expected exactly one owner row, found {len(matches)}')
    if matches[0]['closed']:
        raise OrchError(f'{target} is already closed: {matches[0]["closed"]}')
    note = f'{today()}: {args.text}' if args.action == 'close' else f'{today()} dropped: {args.text}'

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
    verb = 'closed' if args.action == 'close' else 'dropped'
    ws.journal(f'{target} {verb}', evidence=args.text)
    print(f'{target} {verb}')
    return 0


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
    kind = args.kind.upper()
    if kind not in ('D', 'A', 'Q'):
        raise OrchError('decide takes D (decision), A (assumption) or Q (question)')
    _, _, rows = ws.table(ws.decisions, 'decisions')
    new = next_id([plain_id(r['id']) for r in rows], kind)
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
    ids = [str(m.get('id')) for m in config.get('modules') or [] if isinstance(m, dict)]
    for module in config.get('modules') or []:
        if not isinstance(module, dict) or not module.get('id') or not module.get('repo'):
            errors.append(f'orch.yaml: module needs id and repo: {module}')
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f'orch.yaml: duplicate module id {dup}')

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
    dec_ids = [plain_id(r['id']) for r in tables.get('decisions', [])]
    for dup in sorted({i for i in dec_ids if dec_ids.count(i) > 1}):
        errors.append(f'decisions.md: duplicate {dup}')

    for path in sorted(ws.root.rglob('*')):
        rel = path.relative_to(ws.root)
        if safe_edit.BACKUP_DIR_NAME in rel.parts or '.git' in rel.parts or not path.is_file():
            continue
        if path.stat().st_size == 0:
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
        if path.name != '_TEMPLATE.md' and re.search(r'\{\{[A-Z_]+\}\}', text):
            errors.append(f'{rel}: unresolved template placeholder')
    return errors


def cmd_lint(args):
    ws = Workspace(find_workspace(args.workspace))
    errors = lint(ws)
    for error in errors:
        print(f'lint: {error}', file=sys.stderr)
    if not errors:
        print(f'lint: clean ({ws.root})')
    return 1 if errors else 0


def git(root, *args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check, text=True,
                          capture_output=True)


def cmd_commit(args):
    ws = Workspace(find_workspace(args.workspace))
    errors = lint(ws)
    if errors:
        for error in errors:
            print(f'lint: {error}', file=sys.stderr)
        raise OrchError('lint failed; nothing committed')
    if git(ws.root, 'rev-parse', '--is-inside-work-tree', check=False).returncode:
        raise OrchError(f'{ws.root} is not inside a git repository')
    git(ws.root, 'add', '-A', '--', '.')
    if not git(ws.root, 'diff', '--cached', '--name-only', '--', '.').stdout.strip():
        print('commit: nothing to commit')
        return 0
    git(ws.root, 'commit', '-q', '-m', args.message, '--', '.')
    sha = git(ws.root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    print(f'commit: {sha}')
    if ws.config.get('push_after_milestone') and not args.no_push:
        upstream = git(ws.root, 'rev-parse', '--abbrev-ref', '@{u}', check=False)
        push = ['push'] if upstream.returncode == 0 else ['push', '-u', 'origin', 'HEAD']
        result = git(ws.root, *push, check=False)
        if result.returncode:
            print(f'push failed: {result.stderr.strip()}', file=sys.stderr)
            return 1
        print('push: ok')
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog='orch.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--workspace', help='workspace directory (contains orch.yaml)')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('init', help='create a program workspace')
    p.add_argument('program')
    p.add_argument('--dir', help='workspace directory (default: features/<program>)')
    p.add_argument('--title')
    p.add_argument('--tag')
    p.add_argument('--lang', choices=LANGUAGES, default='en')
    p.add_argument('--module', action='append', metavar='ID=REPO[@BASE]')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('new-wp', help='create a work package')
    p.add_argument('module')
    p.add_argument('slug')
    p.add_argument('--title')
    p.set_defaults(func=cmd_new_wp)

    p = sub.add_parser('set', help='edit one cell of a WP row')
    p.add_argument('wp')
    p.add_argument('column', help=', '.join(SETTABLE))
    p.add_argument('text')
    p.add_argument('--evidence', help='journal evidence for a status change')
    p.set_defaults(func=cmd_set)

    p = sub.add_parser('journal', help='add a journal line on top')
    p.add_argument('event')
    p.add_argument('--wp')
    p.add_argument('--evidence')
    p.set_defaults(func=cmd_journal)

    p = sub.add_parser('owner', help='owner queue: add, close, drop')
    p.add_argument('action', choices=('add', 'close', 'drop'))
    p.add_argument('target', help='R|P for add; item id for close/drop')
    p.add_argument('text')
    p.add_argument('--where', help='where the item is described')
    p.set_defaults(func=cmd_owner)

    p = sub.add_parser('queue', help='open owner items')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser('decide', help='append D-n, A-n or Q-n to decisions.md')
    p.add_argument('kind', help='D, A or Q')
    p.add_argument('text')
    p.add_argument('--source')
    p.add_argument('--closes', help='owner question P-n answered by this decision')
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser('lint', help='workspace integrity checks')
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser('commit', help='lint, commit the workspace, push if configured')
    p.add_argument('message')
    p.add_argument('--no-push', action='store_true')
    p.set_defaults(func=cmd_commit)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OrchError, safe_edit.EditError) as error:
        print(f'orch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
