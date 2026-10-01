#!/usr/bin/env python3
"""Claude Code settings files for the sessions of a program (orchestration/settings/*.json).

A module session gets narrow allow rules for what its package needs (reading, its tests, its
own branch), deny rules for what only the owner does (merge, push to the base, releases,
workflow runs, production, the orchestrator workspace) and `crossSessionInbound: accept` so that
its messages reach the orchestrator whatever permission mode either side runs in. Rules are
guard rails for the usual command forms, not a security boundary: branch protection and hooks
are. Standard library only. Imported by orch.py.
"""
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex

import streams

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates' / 'settings'
PERMISSION_MODES = ('auto', 'acceptEdits', 'default', 'dontAsk', 'bypassPermissions')
CHECKPOINTS = ('push', 'pr', 'deploy_test', 'rollback')
DEFAULT_CHECKPOINTS = ('deploy_test',)
SETTINGS_DIR = 'orchestration/settings'
ORCHESTRATOR = 'orchestrator'
# First words that make a module's deploy_test / deploy_prod value a command (else it is prose).
RUNNERS = ('make', 'npm', 'pnpm', 'yarn', 'npx', 'bash', 'sh', 'python', 'python3', 'node', 'docker',
           'kubectl', 'supabase', 'gh', 'fly', 'vercel', 'terraform', 'ansible-playbook')
SAMPLE_ENV = re.compile(r'\.(example|sample|template|dist)$')
RULE = re.compile(r'^(Bash|Read|Edit|Skill|WebFetch)\((.+)\)$', re.S)
MCP_RULE = re.compile(r'^mcp__[A-Za-z0-9_-]+(__[A-Za-z0-9_*-]+)?$')
WORKTREEINCLUDE_HINT = ('move it to `.worktreeinclude` in the repository root (gitignore syntax: Claude Code copies '
                        'the listed gitignored files into every new worktree); never copy `.claude/`: on macOS and '
                        'Linux worktrees read `.claude/settings.local.json` from the main checkout, on Windows they '
                        'do not, and session rules come from the generated --settings file on every system')


class PathError(ValueError):
    """A path that cannot become a permission rule (relative, or a Windows network path)."""


SHELLS = ('bash', 'powershell')


def is_windows():
    """The host kind; tests replace this function to generate Windows rules on any machine."""
    return os.name == 'nt'


def real_path(path):
    """The absolute real path of a local directory. On a simulated Windows host (tests) the string is
    taken as a Windows path as it is."""
    if is_windows() and os.name != 'nt':
        return PureWindowsPath(str(path))
    return Path(path).resolve()


def abs_rule_path(path):
    """The absolute form of a path in Read/Edit rules: //<path> on macOS and Linux; on Windows the
    documented POSIX form //<drive letter in lower case>/<path with forward slashes>
    (C:\\projects\\x -> //c/projects/x). Network (UNC) paths and relative paths are refused."""
    text = str(path)
    if is_windows():
        win = PureWindowsPath(text)
        if text.startswith(('\\\\', '//')) or win.drive.startswith('\\\\'):
            raise PathError(f'{text}: network (UNC) paths cannot be used in permission rules; map the share to a '
                            'drive letter or work from a local clone')
        if not win.drive or not win.root:
            raise PathError(f'{text}: not an absolute path with a drive letter')
        rest = '/'.join(win.parts[1:])
        return f'//{win.drive[0].lower()}/{rest}'.rstrip('/')
    if not text.startswith('/'):
        raise PathError(f'{text}: not an absolute path')
    return '/' + text.rstrip('/')


def command_path(path):
    """A path as it appears in a command a rule must match: forward slashes on Windows."""
    text = str(path)
    return PureWindowsPath(text).as_posix() if is_windows() else text


def settings_path(root, name):
    return Path(root) / SETTINGS_DIR / f'{name}.json'


# ---------------------------------------------------------------- commands and rules

def split_commands(command):
    """Simple commands of a shell line: split on && || ; | & and newlines outside quotes."""
    parts, current, quote, i = [], '', None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            current += ch
            if ch == quote:
                quote = None
            elif ch == '\\' and quote == '"' and i + 1 < len(command):
                current += command[i + 1]
                i += 1
        elif ch in '\'"':
            quote = ch
            current += ch
        elif command.startswith(('&&', '||'), i):
            parts.append(current)
            current = ''
            i += 1
        elif ch in ';|&\n':
            parts.append(current)
            current = ''
        else:
            current += ch
        i += 1
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def words(command):
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def is_command(text):
    """A deploy_test / deploy_prod value that is a command, not prose like 'owner-confirmed'."""
    text = str(text or '').strip()
    first = text.split(' ', 1)[0] if text else ''
    return bool(first) and (first.startswith(('./', '/', '~/')) or first in RUNNERS)


def secret_copies(commands):
    """worktree_setup commands that copy or link secrets or session settings into a worktree."""
    found = []
    for command in commands:
        for part in split_commands(command):
            argv = words(part)
            if not argv or argv[0] not in ('cp', 'rsync', 'ln'):
                continue
            operands = [a for a in argv[1:] if not a.startswith('-')]
            for arg in operands[:-1] if len(operands) > 1 else operands:  # the sources, not the target
                segments = [s for s in arg.strip('/').split('/') if s not in ('', '.', '..')]
                last = segments[-1] if segments else ''
                env = re.fullmatch(r'\.env(\..+)?', last) and not SAMPLE_ENV.search(last)
                claude = '.claude' in segments
                secret = any(re.search(r'secret|key|cert', s, re.I) for s in segments[:-1]) or \
                    (not re.search(r'\.[a-z]+$', last) and re.search(r'secret|key|cert', last, re.I))
                if env or claude or secret:
                    found.append(command)
                    break
            else:
                continue
            break
    return found


def bash_rules(commands):
    """One exact allow rule per simple command (a rule must match each part of a compound line);
    `cd` parts are skipped: changing directory is read-only."""
    rules = []
    for command in commands:
        for part in split_commands(command):
            if part == 'cd' or part.startswith('cd '):
                continue
            rules.append(f'Bash({part})')
    return rules


def prefix_rules(command):
    return [f'Bash({command})', f'Bash({command} *)']


def mcp_server(name):
    """MCP tool prefix of a configured server: other characters than letters, digits, _ and - become _."""
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(name))


def path_rule(tool, path, glob='**'):
    """Read(//abs/path/**): a double slash anchors at the filesystem root (see abs_rule_path)."""
    return f'{tool}({abs_rule_path(path)}/{glob})'


def bash_rule_matches(rule, command):
    """Whether a Bash(...) rule matches a simple command: `*` is any text, and a single trailing ` *`
    also matches the bare command (the documented matching, without wrapper stripping)."""
    match = RULE.fullmatch(rule)
    if not match or match.group(1) != 'Bash':
        return False
    spec = match.group(2)
    if spec.endswith(':*') and spec.count('*') == 1:
        spec = spec[:-2] + ' *'
    pattern = '.*'.join(re.escape(part) for part in spec.split('*'))
    if re.fullmatch(pattern, command, re.S):
        return True
    return spec.endswith(' *') and spec.count('*') == 1 and command == spec[:-2]


def rule_errors(rule):
    """Syntax problems of one permission rule (the forms Claude Code documents)."""
    if not isinstance(rule, str) or not rule.strip():
        return [f'empty rule: {rule!r}']
    if rule.startswith('mcp__'):
        return [] if MCP_RULE.fullmatch(rule) else [f'{rule}: MCP rules take no parentheses: mcp__<server>__*']
    match = RULE.fullmatch(rule)
    if not match:
        return [f'{rule}: expected Tool(specifier) with Bash, Read, Edit, Skill or WebFetch']
    tool, spec = match.groups()
    if spec != spec.strip():
        return [f'{rule}: specifier has surrounding spaces']
    if tool in ('Read', 'Edit') and spec.startswith('/') and not spec.startswith('//'):
        return [f'{rule}: an absolute path needs a double slash (//path)']
    if tool == 'Skill' and not re.fullmatch(r'[A-Za-z0-9_.:/-]+( \*)?', spec):
        return [f'{rule}: Skill(name) or Skill(name *)']
    return []


def settings_errors(data):
    errors = []
    if not isinstance(data, dict):
        return ['settings must be a JSON object']
    permissions = data.get('permissions') or {}
    for kind in ('allow', 'ask', 'deny'):
        for rule in permissions.get(kind) or []:
            errors.extend(f'{kind}: {e}' for e in rule_errors(rule))
    auto = data.get('autoMode') or {}
    env = auto.get('environment') or []
    if env and env[0] != '$defaults':
        errors.append('autoMode.environment must start with "$defaults" (keeps the built-in entries)')
    if data.get('crossSessionInbound') != 'accept':
        errors.append('crossSessionInbound must be "accept"')
    return errors


# ---------------------------------------------------------------- building

def _template(name, mapping):
    def fill(value):
        if isinstance(value, str):
            for key, text in mapping.items():
                value = value.replace('{{' + key + '}}', text)
            return value
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value
    return fill(json.loads((TEMPLATES / f'{name}.json').read_text(encoding='utf-8')))


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def environment(repos):
    lines = ['$defaults']
    for repo in repos:
        local = real_path(repo.local)
        origin = streams.normalized_origin(repo.local) if os.path.isdir(str(local)) else None
        if origin and not origin.startswith('/'):
            lines.append(f'Trusted repo: {origin}')
            lines.append(f'Source control: {"/".join(origin.split("/")[:2])}')
        else:
            lines.append(f'Trusted repo: local git repository {local}')
    return _unique(lines)


def _prod_servers(config):
    envs = config.get('environments') if isinstance(config.get('environments'), dict) else {}
    prod = envs.get('prod') if isinstance(envs.get('prod'), dict) else {}
    servers = []
    for key, value in prod.items():
        if 'mcp' in str(key).lower():
            servers.extend(streams.as_list(value))
    return [f'mcp__{mcp_server(s)}__*' for s in servers]


def _base_push_rules(base):
    """Pushes to the base branch in the usual forms, with any tail (a `*` in a rule matches any text)."""
    return [f'Bash(git push origin {base})', f'Bash(git push origin {base} *)', f'Bash(git push * {base})',
            f'Bash(git push * {base} *)', f'Bash(git push origin HEAD:{base})', f'Bash(git push *:{base})',
            f'Bash(git push *:{base} *)', f'Bash(git push *:refs/heads/{base})',
            f'Bash(git push *:refs/heads/{base} *)', f'Bash(git push * refs/heads/{base})',
            f'Bash(git push * refs/heads/{base} *)']


def delivery_branches(config, raws, base):
    """The integration and prod branches of a repository other than its base, when orch.yaml has a
    delivery block: pushes to them are denied like pushes to the base (release promotes happen only
    inside orch.py release --apply)."""
    if not isinstance(config.get('delivery'), dict):
        return []
    found = []
    for raw in raws:
        for key in ('integration_branch', 'prod_branch'):
            value = str(raw.get(key) or '').strip()
            if value and value != base and value not in found:
                found.append(value)
    return found


def checkpoints(config, module=None):
    raw = (module.raw.get('checkpoints') if module is not None else None)
    if raw is None:
        raw = config.get('checkpoints')
    return list(DEFAULT_CHECKPOINTS) if raw is None else streams.as_list(raw)


def module_tests(module):
    tests = module.tests
    if isinstance(tests, dict):
        return streams.as_list(tests.get('scoped')) + streams.as_list(tests.get('full'))
    return streams.as_list(tests)


def module_settings(config, workspace_root, module, in_repo=False):
    """(settings dict, notes) for a local module session."""
    repo = module.repo
    notes = []
    points = checkpoints(config, module)
    local = real_path(repo.local)  # rules match real paths (a symlinked /var is /private/var)
    data = _template('module', {'REPO': abs_rule_path(local), 'WORKSPACE': abs_rule_path(real_path(workspace_root))})
    perms = data['permissions']
    allow, ask, deny = perms['allow'], perms['ask'], perms['deny']
    for pattern in module.paths:
        for expanded in streams.expand_braces(pattern):
            allow.append(path_rule('Read', local, expanded) if expanded != '**' else path_rule('Read', local))
    remote = streams.has_remote(repo)
    if remote:
        # No allow rule for git push: a `*` tail would also match `<branch>:<base>` refspecs and force
        # flags. Pushes of the package branch are left to the classifier, or to the owner at a checkpoint.
        if 'push' in points or ('deploy_test' in points and repo.push_deploys):
            ask.append('Bash(git push *)')
        (ask if 'pr' in points else allow).append('Bash(gh pr create *)')
        deny.extend(_base_push_rules(repo.base))
        for branch in delivery_branches(config, [repo.raw, module.raw], repo.base):
            deny.extend(_base_push_rules(branch))
    setup = repo.worktree_setup
    copies = secret_copies(setup)
    for command in copies:
        notes.append(f'worktree_setup `{command}` is not allowed: {WORKTREEINCLUDE_HINT}')
    allow.extend(bash_rules(module_tests(module) + repo.checks + [c for c in setup if c not in copies]))
    deploy_test = module.raw.get('deploy_test')
    if 'deploy_test' in points and is_command(deploy_test):
        ask.extend(prefix_rules(deploy_test))
    deploy_prod = module.raw.get('deploy_prod')
    if is_command(deploy_prod):
        deny.extend(prefix_rules(deploy_prod))
    deny.extend(_prod_servers(config))
    if config.get('guards'):
        deny.extend(['Bash(ssh *)', 'Bash(psql *)', 'Bash(mysql *)'])
    for name in module.methodology['forbidden']:
        deny.extend([f'Skill({name})', f'Skill({name} *)'])
    if in_repo:
        notes.append('in-repo workspace: edits of the workspace directory are denied in the main checkout')
    for kind in ('allow', 'ask', 'deny'):
        perms[kind] = _unique(perms[kind])
    # A rule in deny or ask wins over allow; keep allow free of what the others hold.
    perms['allow'] = [r for r in perms['allow'] if r not in perms['ask'] and r not in perms['deny']]
    data['autoMode'] = {'environment': environment([repo])}
    data['crossSessionInbound'] = 'accept'
    return data, notes


def orchestrator_settings(config, workspace_root, modules, repos, skill_dir, workspace_branch=None):
    """Settings for the orchestrator session: reading everything it reconciles, its own scripts,
    no merge, no deploy, no push to any base."""
    root = real_path(workspace_root)
    scripts = command_path(real_path(skill_dir))
    data = _template('orchestrator', {'WORKSPACE': abs_rule_path(root), 'SKILL_DIR': scripts})
    perms = data['permissions']
    if is_windows():  # `python3` may be missing on Windows: the forms the py launcher and python accept
        for script in ('orch.py', 'safe_edit.py'):
            perms['allow'] += [f'Bash(python {scripts}/scripts/{script} *)', f'Bash(py -3 {scripts}/scripts/{script} *)']
    all_repos = list({m.repo.key: m.repo for m in modules.values()}.values())
    all_repos += [r for r in repos.values() if r.key not in {x.key for x in all_repos}]
    for repo in all_repos:
        perms['allow'].append(path_rule('Read', real_path(repo.local)))
        if streams.has_remote(repo):
            perms['deny'].extend(_base_push_rules(repo.base))
            raws = [repo.raw] + [m.raw for m in modules.values() if m.repo.key == repo.key]
            for branch in delivery_branches(config, raws, repo.base):
                perms['deny'].extend(_base_push_rules(branch))
    for module in modules.values():
        if is_command(module.raw.get('deploy_prod')):
            perms['deny'].extend(prefix_rules(module.raw['deploy_prod']))
    if workspace_branch:
        perms['allow'].append(f'Bash(git push origin {workspace_branch})')
    delivery_rules(config, modules, perms)
    perms['deny'].extend(_prod_servers(config))
    for kind in ('allow', 'ask', 'deny'):
        perms[kind] = _unique(perms[kind])
    perms['allow'] = [r for r in perms['allow'] if r not in perms['deny']]
    data['autoMode'] = {'environment': environment(all_repos)}
    data['crossSessionInbound'] = 'accept'
    return data


def delivery_rules(config, modules, perms):
    """Trusted delivery (orch.yaml delivery levels set to orchestrator by a decision D-n): the commands
    the orchestrator may run itself (runs, PR facts, the stand and prod commands). The merge, the promote
    PR and the promote push happen only inside `orch.py deliver --apply` / `orch.py release --apply` (a
    subprocess, not a Bash call), so `gh pr merge`, `gh pr create` by hand and pushes to a prod branch
    stay without allow rules (`gh pr merge` and pushes to the base stay denied)."""
    block = config.get('delivery') if isinstance(config.get('delivery'), dict) else {}
    if not block.get('enabled_by'):
        return
    merge_level = block.get('merge') == 'orchestrator'
    stand_level = block.get('stand') == 'orchestrator'
    prod_level = block.get('prod') == 'orchestrator'
    if not (merge_level or stand_level or prod_level):
        return
    ask_rollback = 'rollback' in checkpoints(config)
    for module in modules.values():
        perms['allow'] += ['Bash(gh run watch *)', 'Bash(gh run list *)', 'Bash(gh pr view *)', 'Bash(gh pr checks *)']
        raw = {**module.repo.raw, **module.raw}
        if stand_level:
            if is_command(raw.get('deploy_test')):
                perms['allow'].append(f'Bash({raw["deploy_test"]})')
            perms['allow'] += bash_rules(streams.as_list(raw.get('verify_test')))
            if raw.get('rollback_test'):
                rule = f'Bash({str(raw["rollback_test"]).replace("{previous_sha}", "*")})'  # the SHA varies
                (perms['ask'] if ask_rollback else perms['allow']).append(rule)
        if prod_level:
            perms['allow'] += bash_rules(streams.as_list(raw.get('verify_prod')))
            perms['allow'] += bash_rules(streams.as_list(raw.get('backup_prod')))
            if raw.get('rollback_prod'):
                rule = f'Bash({str(raw["rollback_prod"]).replace("{previous_sha}", "*")})'
                (perms['ask'] if ask_rollback else perms['allow']).append(rule)


def apply_flags(command, settings, mode):
    """Put --permission-mode/--settings into a `claude ...` start command before the model flags and
    --name (idempotent)."""
    command = re.sub(r" --settings ('[^']*'|\S+)", '', command)
    command = re.sub(r' --permission-mode \S+', '', command)
    if ' --name ' not in command:
        return command
    head = command.split(' "', 1)[0]
    anchor = min((head.find(a) for a in (' --model ', ' --effort ', ' --name ') if head.find(a) >= 0))
    flags = (f' --permission-mode {mode}' if mode else '') + f' --settings {shlex.quote(command_path(settings))}'
    return command[:anchor] + flags + command[anchor:]


def shell_command(command, shell):
    """A start command `cd <dir> && claude ...` in the owner's shell: PowerShell gets
    `cd "<dir with forward slashes>"; claude ...` (idempotent; bash is unchanged)."""
    if shell != 'powershell':
        return command
    match = re.match(r'^cd (.+?) && (claude .*)$', command, re.S)
    if not match:
        return command
    where = match.group(1).strip()
    if len(where) >= 2 and where[0] == where[-1] and where[0] in '\'"':
        where = where[1:-1]
    return f'cd "{PureWindowsPath(where).as_posix() if re.match(r"^[A-Za-z]:", where) else where}"; {match.group(2)}'


def render(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'
