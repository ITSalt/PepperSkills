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
RESOURCE_MODES = ('package', 'on-demand')
# Statuses with a live, unmerged branch: they compete for paths and locks.
ACTIVE = ('DISPATCHING', 'IN_PROGRESS', 'REVIEW', 'REVISE', 'ACCEPTED')
# Statuses that satisfy a dependency.
SATISFIED = ('MERGED', 'TEST-APPLIED', 'DEPLOYED_TEST', 'VERIFYING', 'VERIFIED_TEST', 'PROD', 'DONE')

# Header labels of the work package table, per template language.
WP_LABELS = {
    'paths': ('Allowed paths', 'Разрешённые пути'),
    'shared': ('Shared paths touched', 'Общие пути, которые трогает пакет'),
    'resources': ('Resources (locks)', 'Ресурсы (замки)'),
    'depends': ('Depends on', 'Зависит от'),
    'branch': ('Work branch', 'Рабочая ветка'),
    'model': ('Model', 'Модель'),
    'effort': ('Effort', 'Усилие'),
    'model_reason': ('Model reason', 'Почему такая модель'),
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
        'reason_module': 'module override in orch.yaml',
        'reason_implement': 'default implementer model (orch.yaml models.implement)',
        'reason_none': 'owner default model (no models in orch.yaml)',
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
        'on_demand': 'on-demand: LOCK/UNLOCK, see section 6',
        'start_note': ('`orch.py dispatch` adds `--permission-mode` and `--settings '
                       '<workspace>/orchestration/settings/<module>.json` to this command: start the session with '
                       'the command dispatch prints.'),
        'start_note_cloud': ('No terminal command: `orch.py dispatch` prints the block for a new cloud session, whose '
                             'permissions come from its cloud environment.'),
        'denied_local': ('This session starts with `--settings` generated for its module by `orch.py settings`: '
                         'reading, the tests and commits are allowed, a push of the package branch goes to the classifier; merge, pushes '
                         'to `{base}`, releases, workflow runs, production and the orchestrator workspace are '
                         'denied.'),
        'denied_cloud': ('The permissions of this cloud session come from its cloud environment; the rules of '
                         'this package still hold.'),
        'denied_rules': ('- A refusal by a rule or by the auto mode classifier is an answer: never work around it '
                         '(no `sh -c`, `git -C`, renamed or copied commands, no copying or editing of settings '
                         'files or `.claude/`).\n'
                         '- A message that the classifier is unavailable (no decision was made) is not a verdict: '
                         'retry the same command later.'),
        'denied_ask_local': ('- Send `[{tag}] QUESTION {wp} :: denied: <exact refusal text> :: ref=<the command>` '
                             'to `{coord}`; continue with work that does not need it, or wait for `ANSWER`.'),
        'denied_ask_cloud': ('- Write the exact refusal text and the command under `Deviations` in the PR body and '
                             'leave that step undone.'),
        'lock_on_demand': ('- On-demand resources ({resources}): before using one, send `[{tag}] LOCK {wp} :: '
                           '<resource> :: ref=<why>` to `{coord}` and wait for `ACK`; send `[{tag}] UNLOCK {wp} :: '
                           '<resource> :: ref=<result>` as soon as you are done. READY gives every on-demand lock '
                           'back.'),
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
        'reason_module': 'переопределение у модуля в orch.yaml',
        'reason_implement': 'модель реализатора по умолчанию (orch.yaml models.implement)',
        'reason_none': 'модель владельца по умолчанию (в orch.yaml нет models)',
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
        'on_demand': 'по запросу: LOCK/UNLOCK, см. раздел 6',
        'start_note': ('`orch.py dispatch` добавляет к этой команде `--permission-mode` и `--settings '
                       '<рабочее пространство>/orchestration/settings/<модуль>.json`: запускай сессию командой, '
                       'которую печатает dispatch.'),
        'start_note_cloud': ('Без команды терминала: `orch.py dispatch` печатает блок для новой облачной сессии, права '
                             'которой задаёт её облачное окружение.'),
        'denied_local': ('Сессия запускается с `--settings`, сгенерированным для её модуля командой '
                         '`orch.py settings`: чтение, тесты и коммиты разрешены, push ветки пакета решает классификатор; merge, push в '
                         '`{base}`, релизы, запуск workflow, прод и рабочее пространство оркестратора запрещены.'),
        'denied_cloud': ('Права облачной сессии задаёт её облачное окружение; правила этого пакета действуют '
                         'всё равно.'),
        'denied_rules': ('- Отказ правила или классификатора auto mode — это ответ: не обходить его (никаких '
                         '`sh -c`, `git -C`, переименованных или скопированных команд, никакого копирования или '
                         'правки файлов настроек и `.claude/`).\n'
                         '- Сообщение о недоступности классификатора (решение не принято) — не вердикт: повтори ту '
                         'же команду позже.'),
        'denied_ask_local': ('- Пришли `{coord}`: `[{tag}] QUESTION {wp} :: отказ: <точный текст отказа> :: '
                             'ref=<команда>`; продолжай работу, которой это не нужно, или жди `ANSWER`.'),
        'denied_ask_cloud': ('- Запиши точный текст отказа и команду в раздел `Deviations` тела PR и оставь этот шаг '
                             'невыполненным.'),
        'lock_on_demand': ('- Ресурсы по запросу ({resources}): перед использованием пришли `{coord}`: '
                           '`[{tag}] LOCK {wp} :: <ресурс> :: ref=<зачем>` и жди `ACK`; как только закончишь — '
                           '`[{tag}] UNLOCK {wp} :: <ресурс> :: ref=<результат>`. READY возвращает все замки по '
                           'запросу.'),
    },
}


class StreamError(Exception):
    pass


# Implementer models: aliases of the latest model of a family, or a full model id.
MODEL_ALIASES = ('sonnet', 'opus', 'fable', 'haiku', 'opusplan')
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
MODEL_ID = re.compile(r'^claude-[a-z0-9][a-z0-9.-]*(\[1m\])?$')
PREFILL_URL_LIMIT = 2000  # longer prefill links are cut to repositories + environment; the prompt goes apart


def valid_model(value):
    return value in MODEL_ALIASES or bool(MODEL_ID.match(value or ''))


def valid_effort(value):
    return value in EFFORTS


def model_errors(where, model, effort):
    errors = []
    if model is not None and not valid_model(str(model)):
        errors.append(f'{where}: model {model!r} is not one of {", ".join(MODEL_ALIASES)} or a claude-... id')
    if effort is not None and not valid_effort(str(effort)):
        errors.append(f'{where}: effort {effort!r} is not one of {", ".join(EFFORTS)}')
    return errors


def choose_model(models, module):
    """(model, effort, reason) for a new package: module override, then program models.implement."""
    models = models if isinstance(models, dict) else {}
    if module.model:
        return module.model, module.effort, 'module'
    if models.get('implement'):
        return str(models['implement']), module.effort or models.get('implement_effort'), 'implement'
    return None, None, 'none'


def apply_model_flags(command, model, effort):
    """Put --model/--effort into a `claude ...` start command, right before --name (idempotent)."""
    command = re.sub(r' --model \S+', '', command)
    command = re.sub(r' --effort \S+', '', command)
    flags = (f' --model {model}' if model else '') + (f' --effort {effort}' if model and effort else '')
    if not flags or ' --name ' not in command:
        return command
    return command.replace(' --name ', flags + ' --name ', 1)


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
    def __init__(self, data, implicit=False, program='program', base_dir=None, defaults=None):
        defaults = defaults or {}
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
        # Resources: a name (mode package: held from dispatch to merge or verification) or
        # {name, mode: on-demand} (taken on a LOCK message, given back on UNLOCK or READY).
        self.resources, self.resource_modes, self.resource_errors = [], {}, []
        raw = data.get('resources')
        for item in raw if isinstance(raw, list) else as_list(raw):
            if isinstance(item, dict):
                name, mode = item.get('name'), str(item.get('mode') or 'package')
                if not name:
                    self.resource_errors.append(f'resource needs a name: {item}')
                    continue
            elif item is None:
                continue
            else:
                name, mode = item, 'package'
            if mode not in RESOURCE_MODES:
                self.resource_errors.append(f'resource {name}: mode must be package or on-demand')
            self.resources.append(str(name))
            self.resource_modes[str(name)] = mode
        self.checks = as_list(data.get('checks'))
        self.deploy_workflows = as_list(data.get('deploy_workflows'))
        self.base_deploys = str(data.get('base_deploys') or 'none')
        self.push_deploys = bool(data.get('push_deploys'))
        self.sessions = str(data.get('sessions') or defaults.get('sessions') or 'local')
        self.cloud_environment = data.get('cloud_environment') or defaults.get('cloud_environment')
        self.implicit = implicit
        self.raw = data

    def on_demand(self, name):
        return self.resource_modes.get(name) == 'on-demand'

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
        self.model = data.get('model')
        self.effort = data.get('effort')
        self.cloud_environment = data.get('cloud_environment') or repo.cloud_environment
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
    # Program-level session kind and cloud environment, chosen by the owner at init; repositories
    # and modules inherit them unless they set their own.
    defaults = {'sessions': config.get('sessions'), 'cloud_environment': config.get('cloud_environment')}
    errors, warnings, repos, modules = [], [], {}, {}
    for data in config.get('repos') or []:
        if not isinstance(data, dict) or not data.get('id') or not data.get('path'):
            errors.append(f'orch.yaml: repo needs id and path: {data}')
            continue
        repo = Repo(data, program=program, base_dir=base_dir, defaults=defaults)
        if repo.id in repos:
            errors.append(f'orch.yaml: duplicate repo id {repo.id}')
        if repo.merge_policy not in MERGE_POLICIES:
            errors.append(f'orch.yaml: repo {repo.id}: merge_policy must be sequential or free')
        for pattern in repo.shared_paths:
            try:
                expand_braces(pattern)
            except StreamError as error:
                errors.append(f'orch.yaml: repo {repo.id}: {error}')
        errors.extend(f'orch.yaml: repo {repo.id}: {e}' for e in repo.resource_errors)
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
                                     implicit=True, program=program, base_dir=base_dir, defaults=defaults)
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
        errors.extend(model_errors(f'orch.yaml: module {module.id}', module.model, module.effort))
        if module.cloud and not module.cloud_environment:
            warnings.append(f'orch.yaml: module {module.id} runs cloud sessions but has no cloud_environment '
                            '(name of the owner\'s cloud environment)')
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
    if config.get('sessions') not in (None, 'local', 'cloud'):
        errors.append('orch.yaml: sessions must be local or cloud')
    models = config.get('models')
    if models is not None and not isinstance(models, dict):
        errors.append('orch.yaml: models must be a mapping (implement, implement_effort, escalate, escalate_effort)')
    elif models:
        unknown = set(models) - {'implement', 'implement_effort', 'escalate', 'escalate_effort'}
        if unknown:
            errors.append(f'orch.yaml: models has unknown keys: {", ".join(sorted(unknown))}')
        errors.extend(model_errors('orch.yaml: models.implement', models.get('implement'), models.get('implement_effort')))
        errors.extend(model_errors('orch.yaml: models.escalate', models.get('escalate'), models.get('escalate_effort')))
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

    def plain(key):
        value = (ticks(field(key)) or [(field(key) or '').strip()])[0]
        return value if value and value not in ('—', '-', 'none', 'нет') else None

    return {'paths': paths, 'shared': ticks(field('shared')), 'resources': ticks(field('resources')),
            'depends': depends, 'branch': branch, 'model': plain('model'), 'effort': plain('effort')}


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
    'mapping with plain keys; under `push:` only `branches`, `branches-ignore`, `paths-ignore` and '
    '`paths` (the last only when a branch filter already excludes the workspace branch), '
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
    """(runs_on_push, branches, branches_ignore, paths_ignore, paths) or DeployFormError.

    A positive `paths` filter is returned as given (a list, or the DeployFormError of an unsupported
    list): it only matters when the push runs on the workspace branch at all."""
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
            return head == 'push', None, None, None, None
        if re.fullmatch(r'\[\s*[A-Za-z_]+(\s*,\s*[A-Za-z_]+)*\s*\]', head):
            events = [e.strip() for e in head[1:-1].split(',')]
            return 'push' in events, None, None, None, None
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
        return False, None, None, None, None
    push_indent = _indent(block[push_at])
    body = []
    for line in block[push_at + 1:]:
        if line.strip() and _indent(line) <= push_indent:
            break
        body.append(line)
    found = {'branches': None, 'branches-ignore': None, 'paths-ignore': None, 'paths': None}
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
            if m.group(1) == 'paths':
                try:
                    found['paths'] = _pattern_list('paths', m.group(2), following)
                except DeployFormError as error:
                    found['paths'] = error
                continue
            found[m.group(1)] = _pattern_list(m.group(1), m.group(2), following)
    return True, found['branches'], found['branches-ignore'], found['paths-ignore'], found['paths']


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
            on_push, branches, branches_ignore, paths_ignore, paths = parse_push_trigger(text, name)
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
        if paths is not None:
            refusals.append(f'{name}: runs on push to {branch} with a positive `paths` filter; the check cannot '
                            'prove that workspace commits stay outside it (a branch filter that excludes '
                            f'{branch} would make it safe)')
            continue
        relevant.append(name)
        dirs = [p[:-3] for p in (paths_ignore or []) if p.endswith('/**') and '*' not in p[:-3]
                and not any(part.startswith('.') for part in p[:-3].split('/'))]
        notes.append(f'{name}: runs on push to {branch}; ignored directories: {", ".join(dirs) or "none"}')
        candidates = dirs if candidates is None else [d for d in candidates if d in dirs]
    if refusals:
        # Candidates from the workflows that could be read: used only after an owner decision (D-n).
        if not relevant:
            return [f'docs/orchestration/{program}'], notes, refusals, False
        ordered = sorted(candidates or [], key=lambda d: (d != 'docs', d))
        return [f'{d}/orchestration/{program}' for d in ordered], notes, refusals, False
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


CLOUD_BLOCK = {
    'en': {
        'title': 'New cloud session for {wp}:',
        'env': '- Environment: {env}',
        'env_missing': '- Environment: not set in orch.yaml (cloud_environment); choose the project environment in the form',
        'repo': '- Repository: {repo}, starting branch: {base} (choose the branch in the form if it is not the default)',
        'model': ('- Model: {model}, effort: {effort} - choose them in the lists next to the send button; in a browser '
                  'without the lists send `/model {model}` and `/effort {effort}` as the first messages'),
        'model_only': ('- Model: {model} - choose it in the list next to the send button; in a browser without the '
                       'list send `/model {model}` as the first message'),
        'model_none': '- Model: the owner default (no model in the package)',
        'link': '- Prefilled form: {url}',
        'link_short': '- Prefilled form (without the prompt, it is too long for a link; paste the prompt below): {url}',
        'no_link': '- No prefill link: the repository is not a hosted remote',
        'prompt': 'Prompt:',
    },
    'ru': {
        'title': 'Новая облачная сессия для {wp}:',
        'env': '- Окружение: {env}',
        'env_missing': '- Окружение: в orch.yaml не задано (cloud_environment); выберите окружение проекта в форме',
        'repo': '- Репозиторий: {repo}, стартовая ветка: {base} (выберите ветку в форме, если она не по умолчанию)',
        'model': ('- Модель: {model}, усилие: {effort} — выберите в списках рядом с кнопкой отправки; в браузере без '
                  'списков первыми сообщениями отправьте `/model {model}` и `/effort {effort}`'),
        'model_only': ('- Модель: {model} — выберите в списке рядом с кнопкой отправки; в браузере без списка первым '
                       'сообщением отправьте `/model {model}`'),
        'model_none': '- Модель: по умолчанию владельца (в пакете модель не задана)',
        'link': '- Предзаполненная форма: {url}',
        'link_short': '- Предзаполненная форма (без промпта: для ссылки он слишком длинный; вставьте промпт ниже): {url}',
        'no_link': '- Ссылки предзаполнения нет: репозиторий не на хостинге',
        'prompt': 'Промпт:',
    },
}


def prefill_url(repo_name, environment, prompt):
    """claude.ai/code link that prefills repositories, environment and prompt (no model or branch)."""
    from urllib.parse import quote
    params = [('repositories', quote(repo_name, safe='/'))]
    if environment:
        params.append(('environment', quote(str(environment), safe='')))
    base = 'https://claude.ai/code?' + '&'.join(f'{k}={v}' for k, v in params)
    full = base + '&prompt=' + quote(prompt, safe='')
    return (full, True) if len(full) <= PREFILL_URL_LIMIT else (base, False)


def cloud_block(lang, wp, module, prompt, model, effort):
    """What the owner needs to start a cloud session for a package: environment, repository and base,
    model and effort, a prefill link, then the prompt."""
    t = CLOUD_BLOCK[lang]
    repo = module.repo
    lines = [t['title'].format(wp=wp)]
    env = module.cloud_environment
    lines.append(t['env'].format(env=env) if env else t['env_missing'])
    name = origin_name(repo)
    lines.append(t['repo'].format(repo=name or repo.path, base=repo.base))
    if model and effort:
        lines.append(t['model'].format(model=model, effort=effort))
    elif model:
        lines.append(t['model_only'].format(model=model))
    else:
        lines.append(t['model_none'])
    if name:
        url, with_prompt = prefill_url(name, env, prompt)
        lines.append((t['link'] if with_prompt else t['link_short']).format(url=url))
    else:
        lines.append(t['no_link'])
    lines += ['', t['prompt'], prompt]
    return '\n'.join(lines)


# ---------------------------------------------------------------- work package fields

def wp_fields(lang, module, wp, slug, wp_path, tag, coord, workspace=None, models=None):
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
    where = repo.path if repo.path.startswith(('/', '~')) else str(repo.local)  # `path: .` -> absolute
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
        command = f'cd {where} && claude -w {name} --name {module.session} "{prompt}"'
        worktree = t['kind_worktree'].format(root=repo.worktree_root, name=name)
    else:
        prep = t['prep_repo'].format(**fmt)
        prompt = t['prompt_repo'].format(finish=finish, ref=ref, **fmt)
        command = f'cd {where} && claude --name {module.session} "{prompt}"'
        worktree = t['kind_repo_worktree']
    model, effort, reason = choose_model(models, module)
    if not module.cloud:
        command = apply_model_flags(command, model, effort)
    method = module.methodology
    allowed = ', '.join(f'`{c}`' for c in method['allowed']) or t['methodology_any']
    forbidden = ', '.join(f'`{c}`' for c in method['forbidden']) or t['none']
    if method['name']:
        allowed = f'{method["name"]}: {allowed}'
    hints = []
    if repo.shared_paths:
        hints.append(t['shared_hint'].format(shared=', '.join(f'`{p}`' for p in repo.shared_paths)))
    if repo.resources:
        hints.append(t['resources_hint'].format(resources=', '.join(
            f'`{r}`' + (f' ({t["on_demand"]})' if repo.on_demand(r) else '') for r in repo.resources)))
    denied = [t['denied_cloud' if module.cloud else 'denied_local'].format(**fmt), '',
              t['denied_rules'], t['denied_ask_cloud' if module.cloud else 'denied_ask_local'].format(**fmt)]
    on_demand = [r for r in repo.resources if repo.on_demand(r)]
    if on_demand and not module.cloud:
        denied.append(t['lock_on_demand'].format(resources=', '.join(f'`{r}`' for r in on_demand), **fmt))
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
        'MODEL': f'`{model}`' if model else '—', 'EFFORT': f'`{effort}`' if effort else '—',
        'MODEL_REASON': t['reason_' + reason],
        'IF_DENIED': '\n'.join(denied),
        'START_NOTE': t['start_note_cloud' if module.cloud else 'start_note'],
    }
