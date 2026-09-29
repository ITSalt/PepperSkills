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
        'kind_cloud': 'none: a cloud session works in its own clone',
        'prep_cloud_branch': 'In the cloud session\'s clone, create the package branch: `git fetch origin && git switch -c {branch} origin/{base}`.',
        'prep_cloud_setup': 'Prepare the clone if the environment\'s setup script has not done it already:',
        'delivery_cloud': ('- Push `{branch}` and open a PR to `{base}`; its body starts with `{wp}` and holds the '
                           'development report + `Deviations`. Do not merge.\n'
                           '- No message back is needed: the orchestrator finds the PR by branch and package id.'),
        'prompt_cloud': ('Cloud session for work package {wp} in repository {repo_name}, starting from branch {base}. '
                         '{read} Do section 0, then implement the package on branch {branch} from origin/{base}. '
                         '{push_rule}Deliver: push {branch} and open a PR to {base} whose body starts with {wp} and '
                         'holds the development report and Deviations. Never merge (no merge tool such as '
                         'mcp__github__merge_pull_request, no gh pr merge), never push to {base}, never edit .claude/. '
                         'No message back: the orchestrator finds your PR by branch and package id.'),
        'read_branch': 'Read the package: git fetch origin {wbranch} && git show origin/{wbranch}:{wp_rel} .',
        'read_inline': 'The package text follows this prompt.',
        'push_rule_cloud': ('A push of any branch of this repository deploys the stand; this package holds the stand '
                            'slot while it runs: push only once, when the work is complete. '),
        'command_cloud': '# no terminal command: open a new cloud session on {repo_name}, branch {base}, and paste the prompt above',
        'push_slot': ('- Pushing any branch of this repository deploys the stand: commit locally and do not push '
                      'until the orchestrator gives you the stand slot (the `staging` lock); push once, then '
                      'report.'),
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
        'kind_cloud': 'нет: облачная сессия работает в своём клоне',
        'prep_cloud_branch': 'В клоне облачной сессии создай ветку пакета: `git fetch origin && git switch -c {branch} origin/{base}`.',
        'prep_cloud_setup': 'Подготовь клон, если setup-скрипт окружения ещё не сделал этого:',
        'delivery_cloud': ('- Запушь `{branch}` и открой PR в `{base}`; тело PR начинается с `{wp}` и содержит отчёт '
                           'разработки + `Deviations`. Не мержить.\n'
                           '- Сообщение назад не нужно: оркестратор найдёт PR по ветке и ID пакета.'),
        'prompt_cloud': ('Облачная сессия для пакета {wp} в репозитории {repo_name}, стартовая ветка {base}. '
                         '{read} Выполни раздел 0, затем пакет в ветке {branch} от origin/{base}. '
                         '{push_rule}Сдача: запушь {branch} и открой PR в {base}; тело PR начинается с {wp} и содержит '
                         'отчёт разработки и Deviations. Никогда не мержить (никаких инструментов merge вроде '
                         'mcp__github__merge_pull_request, никакого gh pr merge), не пушить в {base}, не править .claude/. '
                         'Сообщение назад не нужно: оркестратор найдёт PR по ветке и ID пакета.'),
        'read_branch': 'Прочитай пакет: git fetch origin {wbranch} && git show origin/{wbranch}:{wp_rel} .',
        'read_inline': 'Текст пакета — после этого промпта.',
        'push_rule_cloud': ('Push любой ветки этого репозитория выкатывает стенд; пакет держит слот стенда, пока '
                            'идёт работа: пушь один раз, когда работа готова. '),
        'command_cloud': '# без команды терминала: открой новую облачную сессию на {repo_name}, ветка {base}, и вставь промпт выше',
        'push_slot': ('- Push любой ветки этого репозитория выкатывает стенд: коммить локально и не пушь, пока '
                      'оркестратор не выдаст слот стенда (замок `staging`); запушь один раз и сообщи.'),
        'shared_hint': 'Общие пути этого репозитория (объяви те, что трогает пакет): {shared}.',
        'resources_hint': 'Ресурсы этого репозитория, требующие замка: {resources}.',
    },
}


class StreamError(Exception):
    pass


# Work package ids: module ids may contain hyphens (WP-ADMIN-UI-01).
WP_ID = r'\bWP-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+\b'


# ---------------------------------------------------------------- globs

GLOB_SYNTAX = ('path globs: `*` (within one directory), `**` (any depth), `?` (one character), '
               '`{a,b}` (alternatives, may nest); `[` and `]` are literal characters')


def split_top(text, sep=','):
    """Split on sep outside braces: 'a/{x,y}/**,b' -> ['a/{x,y}/**', 'b']."""
    parts, depth, current = [], 0, ''
    for ch in text:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(current)
            current = ''
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def expand_braces(pattern):
    """Expand `{a,b}` alternatives (nested allowed); unbalanced braces raise StreamError."""
    if pattern.count('{') != pattern.count('}'):
        raise StreamError(f'unbalanced braces in glob: {pattern}')
    start = pattern.find('{')
    if start < 0:
        return [pattern]
    depth = 0
    for end in range(start, len(pattern)):
        depth += {'{': 1, '}': -1}.get(pattern[end], 0)
        if depth == 0:
            break
    else:
        raise StreamError(f'unbalanced braces in glob: {pattern}')
    head, body, tail = pattern[:start], pattern[start + 1:end], pattern[end + 1:]
    options = split_top(body) if body else ['']
    result = []
    for option in options:
        result.extend(expand_braces(head + option + tail))
    return result


def glob_regex(pattern):
    """Translate one brace-free path glob (`**`, `*`, `?`) into an anchored regex."""
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
    return any(glob_regex(p).match(path) for p in expand_braces(pattern))


def matches_any(path, patterns):
    return any(glob_match(path, p) for p in patterns)


def static_prefix(pattern):
    """Literal part of a brace-free glob before its first wildcard (`[` is literal)."""
    match = re.search(r'[*?]', pattern)
    return pattern if match is None else pattern[:match.start()]


def patterns_overlap(a, b):
    """Conservative check whether two globs can match a common path."""
    return any(_overlap_one(x, y) for x in expand_braces(a) for y in expand_braces(b))


def _overlap_one(a, b):
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
    expanded = [s2 for s in shared for s2 in expand_braces(s)]
    return all(_covered_one(p, expanded) for p in expand_braces(pattern))


def _covered_one(pattern, shared):
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


def local_path(path, base_dir=None):
    """Expand ~; a relative path (`.` for the repository holding an in-repo workspace) is taken
    from base_dir, the git toplevel of the workspace."""
    expanded = Path(os.path.expanduser(path or '.'))
    if not expanded.is_absolute() and base_dir is not None:
        expanded = Path(base_dir) / expanded
    return Path(os.path.normpath(str(expanded)))


class Repo:
    def __init__(self, data, implicit=False, program='program', base_dir=None):
        self.base_dir = base_dir
        self.id = str(data.get('id'))
        self.path = str(data.get('path') or '')
        self.base = str(data.get('base') or 'main')
        self.branch_prefix = str(data.get('branch_prefix') or f'{program}/')
        self.worktree_root = str(data.get('worktree_root') or '.claude/worktrees')
        self.worktree_setup = as_list(data.get('worktree_setup'))
        # Setup for review clones (run in the clone root, ORCH_MAIN_CHECKOUT = the main checkout);
        # worktree_setup is written for session worktrees and is never reused for clones.
        self.review_setup = as_list(data.get('review_setup'))
        self.merge_policy = str(data.get('merge_policy') or 'free')
        self.shared_paths = as_list(data.get('shared_paths'))
        self.resources = as_list(data.get('resources'))
        self.checks = as_list(data.get('checks'))
        self.deploy_workflows = as_list(data.get('deploy_workflows'))
        self.base_deploys = str(data.get('base_deploys') or 'none')
        self.push_deploys = bool(data.get('push_deploys'))
        self.sessions = str(data.get('sessions') or 'local')
        self.implicit = implicit

    @property
    def key(self):
        """Same checkout on disk: modules of one key never write at the same time unless streams."""
        return str(self.local)

    @property
    def local(self):
        return local_path(self.path, self.base_dir)


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
        self.sessions = str(data.get('sessions') or repo.sessions or 'local')
        methodology = data.get('methodology') if isinstance(data.get('methodology'), dict) else {}
        self.methodology = {'name': methodology.get('name'),
                            'allowed': as_list(methodology.get('allowed')),
                            'forbidden': as_list(methodology.get('forbidden'))}
        self.raw = data

    @property
    def worktree_mode(self):
        return self.kind != 'repo'

    @property
    def cloud(self):
        """Started as a cloud session (its own clone): no local worktree, no messages back."""
        return self.sessions == 'cloud'


def resolve(config, base_dir=None):
    """Return (repos, modules, errors, warnings); the 0.1.0 form maps to implicit repos."""
    program = str(config.get('program') or 'program')
    errors, warnings, repos, modules = [], [], {}, {}
    for data in config.get('repos') or []:
        if not isinstance(data, dict) or not data.get('id') or not data.get('path'):
            errors.append(f'orch.yaml: repo needs id and path: {data}')
            continue
        repo = Repo(data, program=program, base_dir=base_dir)
        if repo.id in repos:
            errors.append(f'orch.yaml: duplicate repo id {repo.id}')
        if repo.merge_policy not in MERGE_POLICIES:
            errors.append(f'orch.yaml: repo {repo.id}: merge_policy must be sequential or free')
        for pattern in repo.shared_paths:
            try:
                expand_braces(pattern)
            except StreamError as error:
                errors.append(f'orch.yaml: repo {repo.id}: {error}')
        repos[repo.id] = repo
    implicit = {}
    for data in config.get('modules') or []:
        if not isinstance(data, dict) or not data.get('id') or not data.get('repo'):
            continue  # reported by the core lint
        ref = str(data['repo'])
        if ref in repos:
            repo = repos[ref]
        else:
            # 0.1.0 form: one implicit repository per (path, base), so each module keeps its base.
            key = (str(local_path(ref, base_dir)), str(data.get('base') or 'main'))
            if key not in implicit:
                implicit[key] = Repo({'id': str(data['id']), 'path': ref, 'base': data.get('base')},
                                     implicit=True, program=program, base_dir=base_dir)
            repo = implicit[key]
        module = Module(data, repo, program)
        if module.kind not in KINDS:
            errors.append(f'orch.yaml: module {module.id}: kind must be area, domain or repo')
        if module.kind != 'repo' and (repo.implicit or not data.get('paths')):
            errors.append(f'orch.yaml: module {module.id}: kind {module.kind} needs `repo: <repos id>` '
                          'and explicit paths')
        for pattern in module.paths:
            try:
                expand_braces(pattern)
            except StreamError as error:
                errors.append(f'orch.yaml: module {module.id}: {error}')
        if module.sessions not in ('local', 'cloud'):
            errors.append(f'orch.yaml: module {module.id}: sessions must be local or cloud')
        modules[module.id] = module
    by_key = {}
    for module in modules.values():
        by_key.setdefault(module.repo.key, []).append(module)
    for group in by_key.values():
        if len(group) < 2:
            continue
        names = ', '.join(m.id for m in group)
        whole = [m.id for m in group if m.kind == 'repo']
        if whole and all(m.repo.implicit for m in group):
            warnings.append(f'orch.yaml: modules {names} (0.1.0 form) share repository {group[0].repo.path}: '
                            'they are dispatched one at a time. To run them in parallel, add a `repos` '
                            'entry and give each module kind area|domain, `repo: <repos id>` and paths')
            continue
        if whole:
            errors.append(f'orch.yaml: modules {names} share repository {group[0].repo.path}; '
                          f'{", ".join(whole)} must become kind area|domain with paths '
                          '(one writing session per worktree and branch)')
            continue
        shared = [p for m in group for p in m.repo.shared_paths]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                try:
                    pairs = overlap_outside_shared(a.paths, b.paths, shared)
                except StreamError:
                    continue  # reported above
                for pa, pb in pairs:
                    errors.append(f'orch.yaml: modules {a.id} and {b.id} overlap outside shared_paths: '
                                  f'{pa} ~ {pb}')
    return repos, modules, errors, warnings


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
    depends = re.findall(WP_ID, field('depends') or '')
    return {'paths': paths, 'shared': ticks(field('shared')), 'resources': ticks(field('resources')),
            'depends': depends, 'branch': branch}


# ---------------------------------------------------------------- git helpers

def git(root, *args):
    # --no-optional-locks: never race a session's own git for index.lock in its worktree.
    return subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args], text=True,
                          capture_output=True)


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


def resolve_ref(repo, ref):
    """A commit-ish of the module repository: local ref, origin/<ref> or a SHA (fetched if needed)."""
    for candidate in (ref, f'origin/{ref}'):
        if ref_exists(repo.local, candidate):
            return candidate
    if re.fullmatch(r'[0-9a-f]{7,40}', ref or ''):
        git(repo.local, 'fetch', '-q', 'origin', ref)
        if ref_exists(repo.local, ref):
            return ref
    return None


def merge_base_report(repo, ref, files):
    """(merge_base, behind, overlapping) of ref against the base: commits the base gained since the
    branch point and which of the branch's files the base changed meanwhile."""
    base = base_ref(repo)
    mb = git(repo.local, 'merge-base', base, ref).stdout.strip()
    if not mb:
        return None, None, []
    behind = int(git(repo.local, 'rev-list', '--count', f'{mb}..{base}').stdout.strip() or 0)
    changed = [f for f in git(repo.local, 'diff', '--name-only', mb, base).stdout.split('\n') if f]
    return mb, behind, sorted(set(changed) & set(files))


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
    """Branch name (also for a branch without commits yet), 'HEAD' when detached, None outside git."""
    result = git(path, 'symbolic-ref', '--short', '-q', 'HEAD')
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return 'HEAD' if git(path, 'rev-parse', '--git-dir').returncode == 0 else None


def _abs_git_path(path, flag):
    """Absolute --git-common-dir / --git-dir, also on git older than 2.31."""
    result = git(path, 'rev-parse', '--path-format=absolute', flag)
    value = result.stdout.strip()
    if result.returncode or not value or value.startswith('--'):
        result = git(path, 'rev-parse', flag)
        value = result.stdout.strip()
        if result.returncode or not value:
            return None
    found = Path(value)
    if not found.is_absolute():
        found = Path(path) / found
    return found.resolve()


def common_dir(path):
    return _abs_git_path(path, '--git-common-dir')


def is_linked_worktree(path):
    git_dir, common = _abs_git_path(path, '--git-dir'), common_dir(path)
    return git_dir is not None and common is not None and git_dir != common


def normalize_url(url, base=None):
    """A remote URL as host/owner/name (lowercase, no scheme, user, port or .git).

    Handles https and scp-style GitHub URLs and the cloud git proxy form
    http://<user>@127.0.0.1:<port>/git/<owner>/<repo>. Local paths are resolved against base."""
    if not url:
        return None
    if url.startswith(('/', '.', '~', 'file:')):
        local = url[len('file://'):] if url.startswith('file://') else url
        return str((Path(base or '.') / os.path.expanduser(local)).resolve())
    match = re.match(r'^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)(?::(\d+))?[:/](.+?)(?:\.git)?/?$', url)
    if not match:
        return url.lower()
    host, path = match.group(1).lower(), match.group(3).lower()
    proxy = re.match(r'^(?:.*/)?git/([^/]+/[^/]+)$', path)
    if proxy:  # cloud git proxy: /git/<owner>/<repo>
        path = proxy.group(1)
    return f'{host}/{path}'


def normalized_origin(path):
    """remote.origin.url of the checkout at path, normalized by normalize_url."""
    result = git(path, 'config', '--get', 'remote.origin.url')
    url = result.stdout.strip()
    if result.returncode or not url:
        return None
    return normalize_url(url, path)


def same_repository(path, repo):
    """True when path is the module repository: shared git common dir, or the same origin (a clone)."""
    if not repo.local.is_dir():
        return False
    mine, theirs = common_dir(path), common_dir(repo.local)
    if mine is not None and mine == theirs:
        return True
    origin = normalized_origin(path)
    return origin is not None and origin == normalized_origin(repo.local)


def module_repo_conflict(home, repos):
    """P4: the workspace never lives in a checkout of a module repository, except on orch/<program>."""
    if common_dir(home) is None:
        return None
    for repo in repos:
        if same_repository(home, repo):
            branch = current_branch(home)
            if not (branch or '').startswith('orch/'):
                where = 'a linked worktree' if is_linked_worktree(home) else 'a checkout or clone'
                return (f'the workspace would live in {where} of module repository {repo.path} on branch '
                        f'{branch}; use a separate home repository, or branch orch/<program> in its own '
                        'worktree or clone')
    return None


def main_checkout_warning(home, modules):
    """P4/L7: orch/<program> in the main checkout while a whole-repository module uses that checkout."""
    if common_dir(home) is None or is_linked_worktree(home):
        return None
    for module in modules:
        if module.kind == 'repo' and module.repo.local.is_dir() and \
                common_dir(home) == common_dir(module.repo.local) and \
                git_toplevel(home) == git_toplevel(module.repo.local):
            return (f'the workspace is on {current_branch(home)} in the main checkout of {module.repo.path}, '
                    f'where the session of module {module.id} (kind repo) works and switches branches; '
                    'move the workspace to its own worktree or clone')
    return None


def origin_name(repo):
    """owner/name of the repository's origin when it is a hosted remote (also behind the cloud proxy)."""
    if not repo.local.is_dir():
        return None
    origin = normalized_origin(repo.local)
    if not origin or origin.startswith('/'):
        return None
    return '/'.join(origin.split('/')[-2:])


# ---------------------------------------------------------------- deploy check (in-repo workspaces)

DEPLOY_FORMS = (
    'supported workflow trigger forms: `on: push`; `on: [push, ...]` on one line; `on:` as a block '
    'mapping with plain keys; under `push:` only `branches`, `branches-ignore` and `paths-ignore`, '
    'each a one-line flow list or a block list of plain or quoted patterns made of letters, digits, '
    '`.`, `_`, `-`, `/` and `*`; no anchors, aliases, negations (`!`), character classes or other keys')
PATTERN_OK = re.compile(r'^[A-Za-z0-9._/*-]+$')


class DeployFormError(Exception):
    """A workflow trigger in a form the check does not understand: never treated as safe."""


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _pattern_list(key, value, following):
    """Values of a list key: one-line flow list or block list of plain/quoted patterns."""
    value = value.split(' #')[0].strip()
    items = []
    if value:
        if not (value.startswith('[') and value.endswith(']')):
            raise DeployFormError(f'`{key}` must be a list, got `{value}`')
        items = [v.strip() for v in value[1:-1].split(',') if v.strip()]
    else:
        for line in following:
            if not line.strip() or line.strip().startswith('#'):
                continue
            m = re.match(r'^\s*-\s*(.+?)\s*(?:#.*)?$', line)
            if not m:
                raise DeployFormError(f'`{key}`: unsupported list item `{line.strip()}`')
            items.append(m.group(1))
        if not items:
            raise DeployFormError(f'`{key}` is empty or not a block list')
    patterns = []
    for item in items:
        if len(item) >= 2 and item[0] == item[-1] and item[0] in '\'"':
            item = item[1:-1]
        if not PATTERN_OK.match(item):
            raise DeployFormError(f'`{key}`: pattern `{item}` uses unsupported syntax')
        patterns.append(item)
    return patterns


def parse_push_trigger(text, name):
    """(runs_on_push, branches, branches_ignore, paths_ignore) or DeployFormError."""
    lines = text.split('\n')
    for line in lines:
        code = '' if line.lstrip().startswith('#') else line.split(' #')[0]
        if re.search(r'(^|[\s:\[,])[&*][A-Za-z_*]', code):
            raise DeployFormError(f'{name}: YAML anchor, alias or unquoted `*` pattern: `{code.strip()}`')
    tops = [i for i, l in enumerate(lines) if l and not l.startswith((' ', '#')) and ':' in l]
    on_lines = [i for i in tops if re.match(r'^on:(\s|$)', lines[i])]
    if any(re.match(r'^["\']on["\']\s*:|^true\s*:', lines[i]) for i in tops):
        raise DeployFormError(f'{name}: quoted or boolean `on` key')
    if len(on_lines) != 1:
        raise DeployFormError(f'{name}: no single top-level `on:` key')
    start = on_lines[0]
    head = lines[start].split(':', 1)[1].split(' #')[0].strip()
    if head:
        if re.fullmatch(r'[A-Za-z_]+', head):
            return head == 'push', None, None, None
        if re.fullmatch(r'\[\s*[A-Za-z_]+(\s*,\s*[A-Za-z_]+)*\s*\]', head):
            events = [e.strip() for e in head[1:-1].split(',')]
            return 'push' in events, None, None, None
        raise DeployFormError(f'{name}: `on: {head}`')
    end = next((k for k in tops if k > start), len(lines))
    block = [l for l in lines[start + 1:end]]
    keys = [(k, l) for k, l in enumerate(block) if l.strip() and not l.lstrip().startswith('#')]
    if not keys:
        raise DeployFormError(f'{name}: empty `on:` block')
    level = _indent(keys[0][1])
    push_at = None
    for k, line in keys:
        if _indent(line) != level:
            continue
        m = re.match(r'^\s*([A-Za-z_]+):\s*(.*)$', line)
        if not m:
            raise DeployFormError(f'{name}: unsupported `on:` entry `{line.strip()}`')
        if m.group(1) == 'push':
            if m.group(2).split(' #')[0].strip() not in ('', '{}', 'null', '~'):
                raise DeployFormError(f'{name}: `push: {m.group(2).strip()}`')
            push_at = k
    if push_at is None:
        return False, None, None, None
    push_indent = _indent(block[push_at])
    body = []
    for line in block[push_at + 1:]:
        if line.strip() and _indent(line) <= push_indent:
            break
        body.append(line)
    found = {'branches': None, 'branches-ignore': None, 'paths-ignore': None}
    entries = [(k, l) for k, l in enumerate(body) if l.strip() and not l.lstrip().startswith('#')]
    if entries:
        inner = _indent(entries[0][1])
        for pos, (k, line) in enumerate(entries):
            if _indent(line) != inner:
                continue
            m = re.match(r'^\s*([A-Za-z_-]+):\s*(.*)$', line)
            if not m or m.group(1) not in found:
                raise DeployFormError(f'{name}: unsupported push filter `{line.strip()}`')
            following = []
            for line2 in body[k + 1:]:
                if line2.strip() and _indent(line2) <= inner:
                    break
                following.append(line2)
            found[m.group(1)] = _pattern_list(m.group(1), m.group(2), following)
    return True, found['branches'], found['branches-ignore'], found['paths-ignore']


def workflow_texts(repo_root, ref):
    """{name: text} of .github/workflows/*.y*ml in the tree of ref (never the working tree)."""
    listing = git(repo_root, 'ls-tree', '--name-only', f'{ref}:.github/workflows')
    if listing.returncode:
        if git(repo_root, 'cat-file', '-e', f'{ref}^{{commit}}').returncode:
            raise DeployFormError(f'ref {ref} not found')
        return {}  # the ref has no workflows directory
    texts = {}
    for name in listing.stdout.split():
        if name.endswith(('.yml', '.yaml')):
            texts[name] = git(repo_root, 'show', f'{ref}:.github/workflows/{name}').stdout
    return texts


def deploy_safe_dirs(repo_root, branch, program, ref):
    """(candidates, notes, refusals, any_dir) for commits on branch, from the workflows in the tree of ref.

    any_dir: no push workflow runs on branch at all, so any non-hidden directory is safe.

    Candidates are non-hidden directories every push workflow running on branch ignores,
    `docs` first. Any workflow in an unknown form is a refusal, never 'safe'."""
    notes, refusals, candidates, relevant = [], [], None, []
    try:
        texts = workflow_texts(repo_root, ref)
    except DeployFormError as error:
        return [], notes, [str(error)], False
    if not texts:
        notes.append(f'{ref} has no .github/workflows: no push workflow runs')
    for name, text in sorted(texts.items()):
        try:
            on_push, branches, branches_ignore, paths_ignore = parse_push_trigger(text, name)
        except DeployFormError as error:
            refusals.append(str(error) if str(error).startswith(name) else f'{name}: {error}')
            continue
        if not on_push:
            notes.append(f'{name}: does not run on push')
            continue
        if branches is not None and not any(glob_match(branch, b) for b in branches):
            notes.append(f'{name}: push on {branch} does not run it (branches filter)')
            continue
        if branches_ignore and any(glob_match(branch, b) for b in branches_ignore):
            notes.append(f'{name}: {branch} is in branches-ignore')
            continue
        relevant.append(name)
        dirs = [p[:-3] for p in (paths_ignore or []) if p.endswith('/**') and '*' not in p[:-3]
                and not any(part.startswith('.') for part in p[:-3].split('/'))]
        notes.append(f'{name}: runs on push to {branch}; ignored directories: {", ".join(dirs) or "none"}')
        candidates = dirs if candidates is None else [d for d in candidates if d in dirs]
    if refusals:
        return [], notes, refusals, False
    if not relevant:
        return [f'docs/orchestration/{program}'], notes, [], True
    ordered = sorted(candidates or [], key=lambda d: (d != 'docs', d))
    return [f'{d}/orchestration/{program}' for d in ordered], notes, [], False


def dir_is_safe(rel, candidates, any_dir=False):
    """rel is a non-hidden directory inside one of the ignored directories behind the candidates."""
    if any(part.startswith('.') for part in Path(rel).parts):
        return False
    if any_dir:
        return True
    roots = [c.rsplit('/orchestration/', 1)[0] for c in candidates]
    return any(rel == r or rel.startswith(r + '/') for r in roots)


# ---------------------------------------------------------------- work package fields

def wp_fields(lang, module, wp, slug, wp_path, tag, coord, workspace=None):
    """Placeholder values for the 0.2.0 work package template.

    workspace: {'mode', 'branch', 'wp_rel'} for an in-repo workspace (cloud sessions read the
    package from its branch)."""
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
    if module.cloud:
        steps = [t['prep_cloud_branch'].format(**fmt)]
        if repo.worktree_setup:
            steps.append(t['prep_cloud_setup'] + '\n\n   ```bash\n' +
                         '\n'.join(f'   {c}' for c in repo.worktree_setup) + '\n   ```')
        if module.test_db or module.ports:
            steps.append(t['prep_env'].format(test_db=module.test_db or t['none'], ports=ports))
        steps.append(t['prep_paths'])
        prep = '\n'.join(f'{i}. {s}' for i, s in enumerate(steps, 1))
        repo_name = origin_name(repo) or (normalized_origin(repo.local) if repo.local.is_dir() else None) \
            or repo.local.name or repo.path
        ws = workspace or {}
        if ws.get('mode') == 'in-repo' and ws.get('wp_rel'):
            read = t['read_branch'].format(wbranch=ws['branch'], wp_rel=ws['wp_rel'])
        else:
            read = t['read_inline']
        push_rule = t['push_rule_cloud'] if repo.push_deploys else ''
        prompt = t['prompt_cloud'].format(repo_name=repo_name, read=read, push_rule=push_rule, **fmt)
        command = t['command_cloud'].format(repo_name=repo_name, base=repo.base)
        worktree = t['kind_cloud']
    elif module.worktree_mode:
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
    if module.cloud:
        delivery = t['delivery_cloud'].format(**fmt)
        if repo.push_deploys:
            delivery = '- ' + t['push_rule_cloud'].strip() + '\n' + delivery
    elif remote and repo.push_deploys:
        delivery = t['push_slot'] + '\n' + delivery
    return {
        'BRANCH': branch, 'KIND': module.kind, 'LINE': repo.base, 'WORKTREE': worktree,
        'PATHS': ', '.join(f'`{p}`' for p in module.paths),
        'TEST_ENV': f'{module.test_db or t["none"]}; {ports}',
        'METHOD_ALLOWED': allowed, 'METHOD_FORBIDDEN': forbidden,
        'REPO_HINTS': '\n'.join(hints) or '—',
        'WORKTREE_SETUP': prep, 'DELIVERY': delivery,
        'START_PROMPT': prompt, 'START_COMMAND': command,
    }
