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
import streams  # noqa: E402

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
    'locks': ('<!-- orch:locks -->', ('lock', 'repo', 'holder', 'since', 'waiting', 'note')),
    'merge': ('<!-- orch:merge -->', ('n', 'repo', 'wp', 'pr', 'rebase_after', 'status')),
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
    in_repo = in_repo_setup(args, program) if args.in_repo else None
    root = in_repo['root'] if in_repo else Path(args.dir or Path('features') / program).expanduser()
    if root.exists() and any(root.iterdir()):
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
            'WORKSPACE': str(root.resolve())}
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
    for rel, template in files.items():
        text = template.read_text(encoding='utf-8')
        text = text.replace('{{MODULE_ROWS}}\n', module_rows + '\n' if module_rows else '')
        text = fill(text, base)
        safe_edit.create(root / rel, text)
    safe_edit.create(root / 'orch.yaml', render_config(base, modules, repos, areas, in_repo))
    safe_edit.create(root / '.gitignore', safe_edit.BACKUP_DIR_NAME + '/\n')
    ws = Workspace(root)
    ws.journal(f'workspace created ({lang})', evidence='orch.py init')
    print(f'workspace: {root}')
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
        raise OrchError('the deploy check cannot tell whether workspace commits would start a workflow: '
                        + '; '.join(refusals) + f'. {streams.DEPLOY_FORMS}. Ask the owner; after a '
                        'recorded decision pass --deploy-override D-n')
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
            raise OrchError('no non-hidden directory is ignored by every push workflow '
                            f'({"; ".join(notes)}); ask the owner where the workspace may live, then pass --dir')
        if not any_dir and not candidates[0].startswith('docs/'):
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
            'detected': prefix is not None, 'sessions': 'cloud'}
    return {'root': target, 'dir': rel, 'branch': branch, 'repo': repo, 'notes': notes,
            'override': override if (refusals or args.dir and not streams.dir_is_safe(rel, candidates, any_dir)) else None}


def yaml_list(values):
    return '[' + ', '.join(json.dumps(v, ensure_ascii=False) for v in values) + ']'


def render_config(base, modules, repos=(), areas=(), in_repo=None):
    title = json.dumps(base['PROGRAM_TITLE'], ensure_ascii=False)
    text = fill((TEMPLATES / 'orch.yaml').read_text(encoding='utf-8'),
                {**base, 'PROGRAM_TITLE_YAML': title})
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
            ] + ([f'    sessions: {r["sessions"]}'] if r.get('sessions') else [])))
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
                                     ws.coordinator, workspace))
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
    if not getattr(args, 'quiet', False):
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
    local = [m for m in modules.values() if not m.cloud]
    warning = streams.main_checkout_warning(ws.root, local)
    if warning:
        warnings.append(warning)
    return warnings


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


def cmd_commit(args):
    ws = Workspace(find_workspace(args.workspace))
    errors = lint(ws)
    if errors:
        for error in errors:
            print(f'lint: {error}', file=sys.stderr)
        raise OrchError('lint failed; nothing committed')
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
        branch = streams.current_branch(ws.root)
        if branch != ws.workspace_branch:
            raise OrchError(f'in-repo workspace: commits go only to {ws.workspace_branch}, the checkout is on '
                            f'{branch}; nothing committed')
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
        # Always push the current branch to the same-named branch of its remote: an upstream that
        # points elsewhere (for example a branch created from origin/main) is never used.
        remote = git(ws.root, 'config', f'branch.{branch}.remote', check=False).stdout.strip() or 'origin'
        upstream = git(ws.root, 'rev-parse', '--abbrev-ref', '@{u}', check=False)
        push = ['push', remote, f'HEAD:refs/heads/{branch}']
        if upstream.returncode:
            push.insert(1, '-u')
        elif upstream.stdout.strip() != f'{remote}/{branch}':
            print(f'note: upstream {upstream.stdout.strip()} left as is; pushed to {remote}/{branch}',
                  file=sys.stderr)
        result = git(ws.root, *push, check=False)
        if result.returncode:
            print(f'push failed: {result.stderr.strip()}', file=sys.stderr)
            return 1
        print('push: ok')
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
    require_table(ws, 'locks')
    if args.action == 'list':
        rows = locks(ws)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif not rows:
            print('locks: none')
        for r in [] if args.json else rows:
            holder = 'free' if r['holder'] == FREE else f'holder {r["holder"]}'
            print(f'{r["lock"]} | {holder} | since {r["since"]} | waiting {r["waiting"]}')
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
    for name in meta['shared'] + meta['resources']:
        try:
            conflicts = lock_conflicts(ws, module.repo, name, wp)
        except OrchError as error:
            problems.append(str(error))
            continue
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
    wp = args.wp
    problems, wanted, busy, r, module = dispatch_problems(ws, wp)
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
    if args.dry_run:  # never writes anything, for any kind of module
        print(f'dispatch {wp}: ok (dry run); locks to take: {", ".join(wanted) or "none"}')
        return 0
    if module.cloud:
        prompt = re.search(r'## 5\.[^\n]*\n+```text\n(.*?)\n```', text, re.S)
        for name in wanted:
            if acquire(ws, module.repo, name, wp, 'dispatch'):
                raise OrchError(f'lock {name} became busy during dispatch; nothing handed over')
        cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='DISPATCHING',
                                   quiet=True, evidence='cloud session prompt handed to the owner'))
        print(prompt.group(1).strip() if prompt else f'{wp}: no start prompt in section 5')
        if args.inline or not ws.in_repo:
            print('\n---\n' + text.strip())
        return 0
    blocks = [b.strip() for b in re.findall(r'```bash\n(.*?)\n\s*```', text, re.S)]
    commands = [b for b in blocks if b.startswith('cd ') and ' claude ' in b]
    command = commands[-1] if commands else None
    for name in wanted:
        if acquire(ws, module.repo, name, wp, 'dispatch'):
            raise OrchError(f'lock {name} became busy during dispatch; nothing handed over')
    wanted = [lock_key(module.repo, n) for n in wanted]
    evidence = 'TASK message to live session' if args.live else 'start command handed to the owner'
    cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='DISPATCHING', quiet=True,
                               evidence=evidence + (f'; locks {", ".join(wanted)}' if wanted else '')))
    if args.live:
        rel = path.relative_to(ws.root) if path else wp
        print(f'[{ws.tag}] TASK {wp} :: {r["title"]} :: ref={ws.root / rel}')
    elif command:
        print(command)
    else:
        print(f'{wp}: no start command in the work package; use its Start prompt section')
    return 0


def cmd_merge(args):
    ws = Workspace(find_workspace(args.workspace))
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
        number = max([int(q['n']) for q in rows if q['n'].isdigit()], default=0) + 1
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
    wp = args.wp
    r, module, meta = wp_context(ws, wp)
    if not module.repo.local.is_dir():
        raise OrchError(f'{module.repo.path} is not available locally: clone it (read-only) or pass --workspace '
                        'from a place where it is')
    ref = args.ref or meta['branch']
    if not ref:
        raise OrchError(f'{wp}: no work branch in the package; pass --ref <branch or sha>')
    streams.git(module.repo.local, 'fetch', '-q', 'origin')
    sha, files, findings = review_auto(ws, wp, module, meta, ref)
    base = streams.base_ref(module.repo)
    text = REPORT_TEXT[ws.lang]
    auto = '\n'.join(f'- **{text["kinds"][k]}**: {t}' for k, t in findings) or f'- {text["none"]}'
    stat = streams.git(module.repo.local, 'diff', '--shortstat', f'{base}...{sha}').stdout.strip()
    revision = ''
    if args.since:
        old = streams.resolve_ref(module.repo, args.since)
        if old is None:
            raise OrchError(f'--since {args.since} not found')
        revision = (f'git -C {module.repo.path} range-diff {base}...{old} {base}...{sha}'
                    if streams.git(module.repo.local, 'merge-base', '--is-ancestor', old, sha).returncode
                    else f'git -C {module.repo.path} diff {old} {sha}')
    date = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
    reports = ws.root / 'reports'
    name = f'{wp.lower()}-review-{date}' + (f'-r{args.round}' if args.round else '') + '.md'
    path = reports / name
    template = (TEMPLATES / ws.lang / 'review-report.md').read_text(encoding='utf-8')
    body = fill(template, {'WP': wp, 'PR': args.pr or r['pr'], 'SHA': sha[:10], 'BASE': base, 'DATE': today(),
                           'ROUND': str(args.round or 1), 'FILES': str(len(files)), 'STAT': stat or '—',
                           'AUTO': auto, 'REVISION': revision or '—'})
    safe_edit.create(path, body)
    if args.pr:
        cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='pr', text=args.pr, quiet=True,
                                   evidence=None))
    if r['status'] in ('DISPATCHING', 'IN_PROGRESS', 'REVISE'):
        cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status', text='REVIEW', quiet=True,
                                   evidence=f'{sha[:10]}; report reports/{name}'))
    else:
        ws.journal(f'{wp}: review round {args.round or 1} started at {sha[:10]}', wp=wp,
                   evidence=f'reports/{name}')
    origin = streams.git(module.repo.local, 'config', '--get', 'remote.origin.url').stdout.strip()
    tests = module.tests if isinstance(module.tests, dict) else {'full': module.tests or []}
    commands = [c for c in streams.as_list(tests.get('scoped')) + streams.as_list(tests.get('full'))]
    clone = ['bash', str(SKILL_DIR / 'scripts' / 'review_clone.sh'), '--repo', origin or str(module.repo.local),
             '--sha', sha]
    for c in module.repo.worktree_setup:
        clone += ['--setup', c]
    for c in commands:
        clone += ['--test', c]
    result = {'wp': wp, 'sha': sha, 'base': base, 'files': files, 'stat': stat, 'report': str(path),
              'findings': [{'kind': k, 'finding': t} for k, t in findings],
              'clone_command': ' '.join(shlex_quote(c) for c in clone), 'revision_diff': revision or None}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f'review {wp} at {sha[:10]} against {base}: {stat or "no changes"}')
    print(f'report: {path}')
    for k, t in findings:
        print(f'[{k}] {t}')
    if not findings:
        print('automatic findings: none')
    print(f'clone and tests: {result["clone_command"]}')
    if revision:
        print(f'revision diff: {revision}')
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
    import shutil
    return shutil.which(name)


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
                        'directory; modules run as cloud sessions')
    p.add_argument('--base', help='base branch of the --in-repo repository (default: origin HEAD)')
    p.add_argument('--deploy-override', metavar='D-n',
                   help='owner decision that accepts an unverifiable deploy check or an unsafe --dir')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('new-wp', parents=[common], help='create a work package')
    p.add_argument('module')
    p.add_argument('slug')
    p.add_argument('--title')
    p.set_defaults(func=cmd_new_wp)

    p = sub.add_parser('set', parents=[common], help='edit one cell of a WP row')
    p.add_argument('wp')
    p.add_argument('column', help=', '.join(SETTABLE))
    p.add_argument('text')
    p.add_argument('--evidence', help='journal evidence for a status change')
    p.set_defaults(func=cmd_set)

    p = sub.add_parser('journal', parents=[common], help='add a journal line on top')
    p.add_argument('event')
    p.add_argument('--wp')
    p.add_argument('--evidence')
    p.set_defaults(func=cmd_journal)

    p = sub.add_parser('owner', parents=[common], help='owner queue: add, close, drop')
    p.add_argument('action', choices=('add', 'close', 'drop'))
    p.add_argument('target', help='R|P for add; item id for close/drop')
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
    p.set_defaults(func=cmd_dispatch)

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
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_review_start)

    p = sub.add_parser('upgrade', parents=[common], help='add 0.2.0 tables to a 0.1.0 status.md')
    p.set_defaults(func=cmd_upgrade)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OrchError, safe_edit.EditError, streams.StreamError) as error:
        print(f'orch: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
