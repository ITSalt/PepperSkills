#!/usr/bin/env python3
"""Streams in one repository: repos/modules schema, paths, locks, merge queue, dispatch.

A module is either a whole repository (kind: repo, the 0.1.0 form) or a logical block
inside a shared repository (kind: area | domain) with its own paths. Each parallel session
of a shared repository works in its own worktree and branch; shared paths and resources
are held by locks in status.md; merges into one repository go through a queue.
Standard library + git only. Imported by orch.py.
"""
import os
from pathlib import Path
import re
import subprocess

KINDS = ('area', 'domain', 'repo')
MERGE_POLICIES = ('sequential', 'free')
# Statuses with a live, unmerged branch: they compete for paths and locks.
ACTIVE = ('DISPATCHING', 'IN_PROGRESS', 'REVIEW', 'REVISE', 'ACCEPTED')
# Statuses that satisfy a dependency.
SATISFIED = ('MERGED', 'TEST-APPLIED', 'DEPLOYED_TEST', 'VERIFYING', 'PROD', 'DONE')

# Header labels of the work package table, per template language.
WP_LABELS = {
    'paths': ('Allowed paths', 'Разрешённые пути'),
    'shared': ('Shared paths touched', 'Общие пути, которые трогает пакет'),
    'resources': ('Resources (locks)', 'Ресурсы (замки)'),
    'depends': ('Depends on', 'Зависит от'),
    'branch': ('Work branch', 'Рабочая ветка'),
}

TEXT = {
    'en': {
        'none': 'none',
        'kind_repo_worktree': 'none: the session works in the repository checkout',
        'kind_worktree': '`{root}/{name}` (created by `claude -w {name}`)',
        'prep_repo': ('Not needed: the module is the whole repository. Create branch `{branch}` '
                      'from `{base_ref}` in the repository checkout.'),
        'prep_branch': 'Switch the worktree to the package branch: `{fetch}git switch -c {branch} {base_ref}`.',
        'prep_setup': 'Prepare the worktree (commands from `orch.yaml`, run inside the worktree):',
        'prep_none': 'No worktree setup commands are configured in `orch.yaml`; ask the orchestrator before installing anything.',
        'prep_env': 'Use test database `{test_db}` and ports {ports}; never the shared defaults.',
        'prep_paths': 'Edit only the allowed paths; shared paths only as declared in the header, after the lock is held.',
        'delivery_pr': ('- PR from `{branch}` to `{base}`; do not merge.\n'
                        '- PR body = development report + `Deviations` (what differs from this package and why).\n'
                        '- Then send `[{tag}] READY {wp} :: <sha> :: ref=<PR URL>` to `{coord}`.'),
        'delivery_local': ('- The repository has no remote: commit on `{branch}` only, no push, no PR; do not merge.\n'
                           '- Put the development report + `Deviations` in `{wp}-report.md` at the branch root.\n'
                           '- Then send `[{tag}] READY {wp} :: <sha> :: ref=branch {branch}` to `{coord}`.'),
        'prompt_repo': ('Read {wp_path} and implement it. Branch {branch} from {base_ref}, {finish}, do not merge. '
                        'When done, send to {coord}: [{tag}] READY {wp} :: <sha> :: ref={ref}'),
        'prompt_worktree': ('Read {wp_path} and implement it. First do section 0 (worktree preparation). '
                            'Branch {branch} from {base_ref}, {finish}, do not merge. '
                            'When done, send to {coord}: [{tag}] READY {wp} :: <sha> :: ref={ref}'),
        'finish_pr': 'PR to {base}',
        'finish_local': 'commits only, no push',
        'ref_pr': '<PR URL>',
        'ref_local': 'branch {branch}',
        'methodology_any': 'any, within this package',
        'shared_hint': 'Shared paths of this repository (declare the ones this package touches): {shared}.',
        'resources_hint': 'Resources of this repository that need a lock: {resources}.',
    },
    'ru': {
        'none': 'нет',
        'kind_repo_worktree': 'нет: сессия работает в checkout репозитория',
        'kind_worktree': '`{root}/{name}` (создаёт `claude -w {name}`)',
        'prep_repo': ('Не нужна: модуль — весь репозиторий. Создай ветку `{branch}` от `{base_ref}` '
                      'в checkout репозитория.'),
        'prep_branch': 'Переключи worktree на ветку пакета: `{fetch}git switch -c {branch} {base_ref}`.',
        'prep_setup': 'Подготовь worktree (команды из `orch.yaml`, выполнять внутри worktree):',
        'prep_none': 'Команд подготовки worktree в `orch.yaml` нет; перед установкой чего-либо спроси оркестратора.',
        'prep_env': 'Тестовая БД `{test_db}` и порты {ports}; общие значения по умолчанию не использовать.',
        'prep_paths': 'Правь только разрешённые пути; общие пути — только объявленные в шапке и после получения замка.',
        'delivery_pr': ('- PR из `{branch}` в `{base}`; не мержить.\n'
                        '- Тело PR = отчёт разработки + `Deviations` (чем результат отличается от пакета и почему).\n'
                        '- Затем сообщение `{coord}`: `[{tag}] READY {wp} :: <sha> :: ref=<PR URL>`.'),
        'delivery_local': ('- У репозитория нет remote: только коммиты в `{branch}`, без push и PR; не мержить.\n'
                           '- Отчёт разработки + `Deviations` — в файле `{wp}-report.md` в корне ветки.\n'
                           '- Затем сообщение `{coord}`: `[{tag}] READY {wp} :: <sha> :: ref=branch {branch}`.'),
        'prompt_repo': ('Прочитай {wp_path} и выполни. Ветка {branch} от {base_ref}, {finish}, не мержить. '
                        'По готовности — сообщение {coord}: [{tag}] READY {wp} :: <sha> :: ref={ref}'),
        'prompt_worktree': ('Прочитай {wp_path} и выполни. Сначала раздел 0 (подготовка worktree). '
                            'Ветка {branch} от {base_ref}, {finish}, не мержить. '
                            'По готовности — сообщение {coord}: [{tag}] READY {wp} :: <sha> :: ref={ref}'),
        'finish_pr': 'PR в {base}',
        'finish_local': 'только коммиты, без push',
        'ref_pr': '<PR URL>',
        'ref_local': 'branch {branch}',
        'methodology_any': 'любые, в рамках пакета',
        'shared_hint': 'Общие пути этого репозитория (объяви те, что трогает пакет): {shared}.',
        'resources_hint': 'Ресурсы этого репозитория, требующие замка: {resources}.',
    },
}


class StreamError(Exception):
    pass


# ---------------------------------------------------------------- globs

def glob_regex(pattern):
    """Translate a path glob (`**`, `*`, `?`) into an anchored regex."""
    out, i = '', 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif pattern.startswith('**', i):
            out += '.*'
            i += 2
        elif pattern[i] == '*':
            out += '[^/]*'
            i += 1
        elif pattern[i] == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r'\Z')


def glob_match(path, pattern):
    return bool(glob_regex(pattern).match(path))


def matches_any(path, patterns):
    return any(glob_match(path, p) for p in patterns)


def static_prefix(pattern):
    """Literal part of a glob before its first wildcard."""
    match = re.search(r'[*?\[]', pattern)
    return pattern if match is None else pattern[:match.start()]


def patterns_overlap(a, b):
    """Conservative check whether two globs can match a common path."""
    if a == b:
        return True
    pa, pb = static_prefix(a), static_prefix(b)
    if pa == a and pb == b:
        return False  # two different literal paths
    if pa == a:
        return glob_match(a, b)
    if pb == b:
        return glob_match(b, a)
    return pa.startswith(pb) or pb.startswith(pa)


def covered(pattern, shared):
    """True when every path the pattern can match lies inside the shared patterns."""
    for s in shared:
        if pattern == s:
            return True
        if static_prefix(pattern) == pattern and glob_match(pattern, s):
            return True
        if s.endswith('/**') and static_prefix(pattern).startswith(s[:-2]):
            return True
    return False


def overlap_outside_shared(paths_a, paths_b, shared):
    """Pairs of patterns from two path sets that overlap outside the shared paths."""
    pairs = []
    for a in paths_a:
        for b in paths_b:
            if patterns_overlap(a, b) and not (covered(a, shared) or covered(b, shared)):
                pairs.append((a, b))
    return pairs


# ---------------------------------------------------------------- schema

def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]


class Repo:
    def __init__(self, data, implicit=False, program='program'):
        self.id = str(data.get('id'))
        self.path = str(data.get('path') or '')
        self.base = str(data.get('base') or 'main')
        self.branch_prefix = str(data.get('branch_prefix') or f'{program}/')
        self.worktree_root = str(data.get('worktree_root') or '.claude/worktrees')
        self.worktree_setup = as_list(data.get('worktree_setup'))
        self.merge_policy = str(data.get('merge_policy') or 'free')
        self.shared_paths = as_list(data.get('shared_paths'))
        self.resources = as_list(data.get('resources'))
        self.checks = as_list(data.get('checks'))
        self.deploy_workflows = as_list(data.get('deploy_workflows'))
        self.base_deploys = str(data.get('base_deploys') or 'none')
        self.implicit = implicit

    @property
    def local(self):
        return Path(os.path.expanduser(self.path))


class Module:
    def __init__(self, data, repo, program):
        self.id = str(data.get('id')).lower()
        self.repo = repo
        self.kind = str(data.get('kind') or ('repo' if not data.get('paths') else 'area'))
        self.paths = as_list(data.get('paths')) or ['**']
        self.session = str(data.get('session') or f'{program}-{self.id}')
        self.test_db = data.get('test_db')
        self.ports = data.get('ports') if isinstance(data.get('ports'), dict) else {}
        self.tests = data.get('tests')
        methodology = data.get('methodology') if isinstance(data.get('methodology'), dict) else {}
        self.methodology = {'name': methodology.get('name'),
                            'allowed': as_list(methodology.get('allowed')),
                            'forbidden': as_list(methodology.get('forbidden'))}
        self.raw = data

    @property
    def worktree_mode(self):
        return self.kind != 'repo'


def resolve(config):
    """Return (repos, modules, errors); the 0.1.0 form maps to implicit repos."""
    program = str(config.get('program') or 'program')
    errors, repos, modules = [], {}, {}
    for data in config.get('repos') or []:
        if not isinstance(data, dict) or not data.get('id') or not data.get('path'):
            errors.append(f'orch.yaml: repo needs id and path: {data}')
            continue
        repo = Repo(data, program=program)
        if repo.id in repos:
            errors.append(f'orch.yaml: duplicate repo id {repo.id}')
        if repo.merge_policy not in MERGE_POLICIES:
            errors.append(f'orch.yaml: repo {repo.id}: merge_policy must be sequential or free')
        repos[repo.id] = repo
    implicit = {}
    for data in config.get('modules') or []:
        if not isinstance(data, dict) or not data.get('id') or not data.get('repo'):
            continue  # reported by the core lint
        ref = str(data['repo'])
        if ref in repos:
            repo = repos[ref]
        else:
            key = os.path.normpath(os.path.expanduser(ref))
            if key not in implicit:
                implicit[key] = Repo({'id': str(data['id']), 'path': ref, 'base': data.get('base')},
                                     implicit=True, program=program)
            repo = implicit[key]
        module = Module(data, repo, program)
        if module.kind not in KINDS:
            errors.append(f'orch.yaml: module {module.id}: kind must be area, domain or repo')
        if module.kind != 'repo' and (repo.implicit or not data.get('paths')):
            errors.append(f'orch.yaml: module {module.id}: kind {module.kind} needs `repo: <repos id>` '
                          'and explicit paths')
        modules[module.id] = module
    by_repo = {}
    for module in modules.values():
        by_repo.setdefault(id(module.repo), []).append(module)
    for group in by_repo.values():
        if len(group) < 2:
            continue
        repo = group[0].repo
        whole = [m.id for m in group if m.kind == 'repo']
        if whole:
            errors.append(f'orch.yaml: modules {", ".join(m.id for m in group)} share repository '
                          f'{repo.path}; {", ".join(whole)} must become kind area|domain with paths '
                          '(one writing session per worktree and branch)')
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                for pa, pb in overlap_outside_shared(a.paths, b.paths, repo.shared_paths):
                    errors.append(f'orch.yaml: modules {a.id} and {b.id} overlap outside shared_paths: '
                                  f'{pa} ~ {pb}')
    return repos, modules, errors


# ---------------------------------------------------------------- work package metadata

def wp_header(text):
    """Rows of the first Markdown table of a work package: {label: value}."""
    rows, started = {}, False
    for line in text.split('\n'):
        if line.startswith('|'):
            started = True
            cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip())[1:-1]]
            if len(cells) >= 2 and not set(cells[0]) <= set('-: '):
                rows[cells[0]] = cells[1]
        elif started:
            break
    return rows


def wp_meta(path, module):
    """Declared metadata of a work package, with module defaults for 0.1.0 files."""
    header = wp_header(Path(path).read_text(encoding='utf-8'))

    def field(key):
        for label in WP_LABELS[key]:
            if label in header:
                return header[label]
        return None

    def ticks(value):
        return re.findall(r'`([^`]+)`', value or '')

    paths = ticks(field('paths')) or (module.paths if module else ['**'])
    branch = (ticks(field('branch')) or [None])[0]
    depends = re.findall(r'\bWP-[A-Z0-9]+-\d+\b', field('depends') or '')
    return {'paths': paths, 'shared': ticks(field('shared')), 'resources': ticks(field('resources')),
            'depends': depends, 'branch': branch}


# ---------------------------------------------------------------- git helpers

def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True)


def has_remote(repo):
    if not repo.local.is_dir():
        return True  # not checked out here: assume the usual PR flow
    result = git(repo.local, 'remote')
    return result.returncode != 0 or bool(result.stdout.strip())


def ref_exists(root, ref):
    return git(root, 'rev-parse', '--verify', '--quiet', ref + '^{commit}').returncode == 0


def base_ref(repo):
    remote = f'origin/{repo.base}'
    return remote if repo.local.is_dir() and ref_exists(repo.local, remote) else repo.base


def branch_files(repo, branch):
    """Files changed on branch relative to its merge base with the repository base."""
    base = base_ref(repo)
    for ref in (branch, f'origin/{branch}'):
        if ref_exists(repo.local, ref):
            result = git(repo.local, 'diff', '--name-only', f'{base}...{ref}')
            if result.returncode == 0:
                return [f for f in result.stdout.split('\n') if f]
    return None


def worktrees(repo):
    """Entries of `git worktree list --porcelain` with dirty state and lag behind base."""
    result = git(repo.local, 'worktree', 'list', '--porcelain')
    if result.returncode:
        return []
    entries, current = [], {}
    for line in result.stdout.split('\n') + ['']:
        if not line:
            if current:
                entries.append(current)
            current = {}
            continue
        key, _, value = line.partition(' ')
        if key == 'worktree':
            current['path'] = value
        elif key == 'branch':
            current['branch'] = value.removeprefix('refs/heads/')
        elif key == 'detached':
            current['branch'] = '(detached)'
    base = base_ref(repo)
    for entry in entries:
        status = git(entry['path'], 'status', '--porcelain')
        entry['dirty'] = bool(status.stdout.strip()) if status.returncode == 0 else None
        count = git(entry['path'], 'rev-list', '--left-right', '--count', f'HEAD...{base}')
        if count.returncode == 0 and count.stdout.split():
            ahead, behind = count.stdout.split()
            entry['ahead'], entry['behind'] = int(ahead), int(behind)
    return entries


def detect_branch_prefix(path):
    """Branch prefix from the repository's own convention (config.yaml git.branch_prefix)."""
    config = Path(os.path.expanduser(path)) / 'config.yaml'
    if not config.is_file():
        return None
    match = re.search(r'(?m)^\s*branch_prefix:\s*["\']?([^"\'\s#]+)', config.read_text(encoding='utf-8'))
    return match.group(1) if match else None


def git_toplevel(path):
    result = git(path, 'rev-parse', '--show-toplevel')
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def current_branch(path):
    result = git(path, 'rev-parse', '--abbrev-ref', 'HEAD')
    return result.stdout.strip() if result.returncode == 0 else None


def module_repo_conflict(home, repos):
    """P4: the workspace must never live in a checkout of a module's base branch."""
    top = git_toplevel(home)
    if top is None:
        return None
    for repo in repos:
        if repo.local.is_dir() and git_toplevel(repo.local) == top:
            branch = current_branch(home)
            if not (branch or '').startswith('orch/'):
                return (f'the workspace would live in module repository {repo.path} on branch {branch}; '
                        'use a separate home repository, or branch orch/<program> in its own worktree')
    return None


# ---------------------------------------------------------------- work package fields

def wp_fields(lang, module, wp, slug, wp_path, tag, coord):
    """Placeholder values for the 0.2.0 work package template."""
    t = TEXT[lang]
    repo = module.repo
    branch = f'{repo.branch_prefix}{wp.lower()}-{slug}'
    remote = has_remote(repo)
    bref = f'origin/{repo.base}' if remote else repo.base
    name = f'{wp.lower()}-{slug}'
    fmt = dict(branch=branch, base=repo.base, base_ref=bref, wp=wp, tag=tag, coord=coord,
               wp_path=wp_path)
    finish = (t['finish_pr'] if remote else t['finish_local']).format(**fmt)
    ref = (t['ref_pr'] if remote else t['ref_local']).format(**fmt)
    ports = ', '.join(f'{k}={v}' for k, v in module.ports.items()) or t['none']
    if module.worktree_mode:
        steps = [t['prep_branch'].format(fetch='git fetch origin && ' if remote else '', **fmt)]
        if repo.worktree_setup:
            steps.append(t['prep_setup'] + '\n\n   ```bash\n' +
                         '\n'.join(f'   {c}' for c in repo.worktree_setup) + '\n   ```')
        else:
            steps.append(t['prep_none'])
        if module.test_db or module.ports:
            steps.append(t['prep_env'].format(test_db=module.test_db or t['none'], ports=ports))
        steps.append(t['prep_paths'])
        prep = '\n'.join(f'{i}. {s}' for i, s in enumerate(steps, 1))
        prompt = t['prompt_worktree'].format(finish=finish, ref=ref, **fmt)
        command = f'cd {repo.path} && claude -w {name} --name {module.session} "{prompt}"'
        worktree = t['kind_worktree'].format(root=repo.worktree_root, name=name)
    else:
        prep = t['prep_repo'].format(**fmt)
        prompt = t['prompt_repo'].format(finish=finish, ref=ref, **fmt)
        command = f'cd {repo.path} && claude --name {module.session} "{prompt}"'
        worktree = t['kind_repo_worktree']
    method = module.methodology
    allowed = ', '.join(f'`{c}`' for c in method['allowed']) or t['methodology_any']
    forbidden = ', '.join(f'`{c}`' for c in method['forbidden']) or t['none']
    if method['name']:
        allowed = f'{method["name"]}: {allowed}'
    hints = []
    if repo.shared_paths:
        hints.append(t['shared_hint'].format(shared=', '.join(f'`{p}`' for p in repo.shared_paths)))
    if repo.resources:
        hints.append(t['resources_hint'].format(resources=', '.join(f'`{r}`' for r in repo.resources)))
    delivery = (t['delivery_pr'] if remote else t['delivery_local']).format(**fmt)
    return {
        'BRANCH': branch, 'KIND': module.kind, 'LINE': repo.base, 'WORKTREE': worktree,
        'PATHS': ', '.join(f'`{p}`' for p in module.paths),
        'TEST_ENV': f'{module.test_db or t["none"]}; {ports}',
        'METHOD_ALLOWED': allowed, 'METHOD_FORBIDDEN': forbidden,
        'REPO_HINTS': '\n'.join(hints) or '—',
        'WORKTREE_SETUP': prep, 'DELIVERY': delivery,
        'START_PROMPT': prompt, 'START_COMMAND': command,
    }
