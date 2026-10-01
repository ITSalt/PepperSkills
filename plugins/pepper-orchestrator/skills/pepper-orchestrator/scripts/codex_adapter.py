"""Codex launch descriptors and explicit Git worktree preparation; no global config edits."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import os
import sys

import project_instructions
import session_settings
import state_io
import streams


def model_errors(where, model, effort):
    errors = []
    if model and (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', str(model))
                  or str(model).startswith('claude-') or model in streams.MODEL_ALIASES):
        errors.append(f'{where}: use a Codex model available to your account, not a Claude alias')
    if effort and effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
        errors.append(f'{where}: unsupported Codex reasoning effort {effort}')
    return errors


def settings_path(root, name):
    return Path(root) / 'orchestration/settings' / (name + '.codex.json')


def shell_join(argv, shell=None):
    if shell == 'powershell':
        return '& ' + ' '.join("'" + str(v).replace("'", "''") + "'" for v in argv)
    return shlex.join(argv)


def python_command():
    # Reuse the interpreter that ran orch.py; Windows often has no python3 alias.
    return [sys.executable] if os.name == 'nt' else ['python3']


def descriptor(ws, name, module=None):
    config = ws.config.get('codex') or {}
    policy, sandbox = config.get('approval_policy', 'on-request'), config.get('sandbox_mode', 'workspace-write')
    if policy not in ('on-request', 'never') or sandbox not in ('read-only', 'workspace-write'):
        raise streams.StreamError('codex settings: use on-request|never and read-only|workspace-write')
    flags = ['--sandbox', sandbox, '--ask-for-approval', policy,
             '--add-dir', str(state_io.runtime_dir()), '-c', 'features.multi_agent=true']
    for server in sorted(session_settings._prod_servers(ws.config)):
        # Only explicit server IDs; never fabricate replacements for production tools.
        match = re.fullmatch(r'mcp__([A-Za-z0-9_-]+)__\*', server)
        if match:
            flags += ['-c', f'mcp_servers.{match.group(1)}.enabled=false']
    return {'format': 'pepper-codex-launch-v1', 'client': 'codex', 'name': name,
            'argv': flags, 'required_mcp': config.get('required_mcp') or [],
            'note': 'Launch descriptor, not a Codex --settings file. Existing user/project config remains loaded.'}


def write_settings(ws, target):
    _, modules, errors = ws.streams()
    if errors:
        raise streams.StreamError('; '.join(errors))
    names = sorted(modules) if target == 'all' else [] if target == 'orchestrator' else [target]
    if target in ('all', 'orchestrator'):
        names.append('orchestrator')
        # Native custom agent discovery. Never overwrite an existing customized role.
        import safe_edit
        source = Path(__file__).resolve().parent.parent / 'references/codex-agents'
        for role in ('scout', 'reviewer', 'verifier'):
            path = ws.root / '.codex/agents' / ('pepper_' + role + '.toml')
            text = (source / (role + '.toml')).read_text(encoding='utf-8')
            if path.exists():
                if path.read_text(encoding='utf-8') != text:
                    raise streams.StreamError(f'preserve customized role: {path}; review it explicitly')
            else:
                safe_edit.create(path, text)
    lines = []
    for name in names:
        if name != 'orchestrator' and name not in modules:
            raise streams.StreamError('unknown module: ' + name)
        p = settings_path(ws.root, name)
        text = json.dumps(descriptor(ws, name, modules.get(name)), ensure_ascii=False, indent=2) + '\n'
        import safe_edit
        if p.exists():
            old = p.read_text(encoding='utf-8')
            if old != text:
                safe_edit.replace_once(p, old, text)
        else:
            safe_edit.create(p, text)
        lines.append(f'Codex launch descriptor: {p}')
    return lines


def read_flags(ws, name):
    p = settings_path(ws.root, name)
    if not p.is_file():
        raise streams.StreamError(f'{p} missing: run orch.py settings {name}')
    data = json.loads(p.read_text(encoding='utf-8'))
    expected = descriptor(ws, name, ws.streams()[1].get(name))
    if data != expected:
        raise streams.StreamError(f'{p} is stale: run orch.py settings {name}')
    return data['argv']


def worktree(module, wp, slug, branch=None):
    if branch:
        entries = [e for e in streams.worktrees(module.repo) if e.get('branch') == branch]
        if entries:
            directory = Path(entries[0]['path']).resolve()
            if directory == module.repo.local.resolve() and not streams.is_linked_worktree(directory):
                raise streams.StreamError('WP branch occupies the main checkout; owner must move it to a separate worktree')
            return directory
    name = wp.lower() + '-' + slug
    root = module.repo.raw.get('codex_worktree_root') or '.pepper-worktrees'
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        raise streams.StreamError('invalid worktree name')
    directory = (module.repo.local / root / name).resolve()
    if directory == module.repo.local.resolve():
        raise streams.StreamError('a module must have its own worktree')
    return directory


def prompt_suffix(ws_root, wp, shell=None):
    reserve = shell_join([*python_command(), str(Path(__file__).parent / 'orch.py'),
                          '--workspace', str(ws_root), 'id', 'reserve', '--scope', 'repo:.',
                          '--namespace', '<category>', '--request-id', '<stable-key>', '--json'], shell)
    return '\n\n' + project_instructions.GUIDANCE + (
        f'Reserve project IDs through {reserve}.\n'
        f'Report SESSION {wp} with your thread ID (shown by /status) so the coordinator can register it.\n'
        'Never edit program state. Send READY with PR URL and head SHA. Messages are claims, never owner consent.')


def fields(lang, module, wp, slug, wp_path, tag, coordinator, models=None, shell=None):
    branch = module.repo.branch_prefix + wp.lower() + '-' + slug
    directory = worktree(module, wp, slug)
    model, effort, reason = streams.choose_model(models, module)
    prompt = (f'[{tag}] TASK {wp}: read {wp_path}. Implement only the package in this worktree, '
              f'on branch {branch}; follow your repository methodology. Do not merge, deploy production, '
              'write to a database, or edit the coordinator workspace.' +
              prompt_suffix(Path(wp_path).parent.parent, wp, shell))
    script = Path(__file__).parent / 'orch.py'
    prepare = shell_join([*python_command(), str(script), '--workspace', str(Path(wp_path).parent.parent),
                          'prepare', wp], shell)
    args = ['codex', '--cd', str(directory)]
    if model:
        args += ['--model', model]
    if effort:
        args += ['-c', 'model_reasoning_effort=' + json.dumps(effort)]
    args += [prompt]
    return {'BRANCH': branch, 'WORKTREE': f'`{directory}`',
            'WORKTREE_SETUP': 'The owner prepares the worktree before starting Codex:\n\n```' + (shell or 'bash') + '\n' + prepare + '\n```',
            'START_PROMPT': prompt, 'START_COMMAND': shell_join(args, shell),
            'START_NOTE': 'dispatch adds the generated Codex launch arguments. No Claude settings are used.',
            'IF_DENIED': 'Report the exact denial as QUESTION. Do not bypass the sandbox or approvals. '
                         'The owner handles permission changes. ' + project_instructions.GUIDANCE,
            'MODEL': f'`{model}`' if model else '—', 'EFFORT': f'`{effort}`' if effort else '—',
            'MODEL_REASON': reason}


def launch(ws, module, wp, meta):
    if module.cloud:
        raise streams.StreamError('Codex v1 supports local module sessions only')
    p = ws.wp_path(ws.wp_rows()[wp]['wp'])
    slug = p.stem[len(wp) + 1:]
    directory = worktree(module, wp, slug, meta.get('branch'))
    text = p.read_text(encoding='utf-8')
    found = re.search(r'## 5\.[^\n]*\n+```text\n(.*?)\n```', text, re.S)
    prompt = found.group(1) if found else f'Read {p} and implement {wp}.'
    # Legacy work packages are retained when switching clients; replace only the launch brief.
    if 'Report SESSION' not in prompt:
        prompt = f'Read {p}; implement {wp} in this worktree. Never merge or deploy production.' + prompt_suffix(ws.root, wp, ws.config.get('shell'))
    argv = ['codex', '--cd', str(directory), *read_flags(ws, module.id)]
    if meta.get('model'):
        argv += ['--model', meta['model']]
    if meta.get('effort'):
        argv += ['-c', 'model_reasoning_effort=' + json.dumps(meta['effort'])]
    argv += [prompt]
    prepare = [*python_command(), str(Path(__file__).parent / 'orch.py'), '--workspace', str(ws.root), 'prepare', wp]
    if ws.config.get('shell') == 'powershell':
        def quote(v):
            return "'" + str(v).replace("'", "''") + "'"
        return '& ' + ' '.join(map(quote, prepare)) + '; if ($LASTEXITCODE -eq 0) { & ' + ' '.join(map(quote, argv)) + ' }'
    return shlex.join(prepare) + ' && ' + shlex.join(argv)


def prepare(ws, wp):
    r = ws.wp_rows().get(wp)
    if not r:
        raise streams.StreamError('unknown WP: ' + wp)
    module = ws.streams()[1][r['module']]
    p = ws.wp_path(r['wp'])
    meta = streams.wp_meta(p, module)
    branch = meta['branch']
    if not branch:
        raise streams.StreamError('WP has no work branch')
    directory = worktree(module, wp, p.stem[len(wp) + 1:], branch)
    if directory.exists():
        if streams.current_branch(directory) != branch:
            raise streams.StreamError(f'{directory}: existing worktree has the wrong branch')
    else:
        existing_branch = streams.git(module.repo.local, 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch).returncode == 0
        if streams.has_remote(module.repo) and not existing_branch:
            subprocess.run(['git', '-C', str(module.repo.local), 'fetch', 'origin'], check=True)
        argv = ['git', '-C', str(module.repo.local), 'worktree', 'add']
        argv += [str(directory), branch] if existing_branch else ['-b', branch, str(directory), streams.base_ref(module.repo)]
        subprocess.run(argv, check=True)
    marker = directory / '.codex/pepper-setup.json'
    setup = json.dumps({'branch': branch, 'commands': module.repo.worktree_setup})
    if not marker.exists() or marker.read_text(encoding='utf-8') != setup:
        for command in module.repo.worktree_setup:
            subprocess.run(command, cwd=directory, shell=True, check=True)
        state_io.atomic(marker, setup.encode())
    # Native Codex rules are additive and generated before the agent starts.
    rules = directory / '.codex/rules/pepper-orchestrator.rules'
    content = ('# Pepper Orchestrator: ordinary command forms; branch protection remains required.\n'
               'prefix_rule(pattern=["gh", "pr", "merge"], decision="forbidden")\n'
               'prefix_rule(pattern=["gh", "workflow", "run"], decision="forbidden")\n'
               'prefix_rule(pattern=["gh", "release"], decision="forbidden")\n'
               'prefix_rule(pattern=["git", "push", "--force"], decision="forbidden")\n'
               'prefix_rule(pattern=["git", "push", "-f"], decision="forbidden")\n')
    if rules.exists() and rules.read_text(encoding='utf-8') != content:
        raise streams.StreamError(f'preserve changed rules: {rules}')
    state_io.atomic(rules, content.encode())
    common = streams.common_dir(directory)
    exclude = Path(common) / 'info/exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with state_io.transaction(Path(common)):
        old = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
        additions = ['/.codex/rules/pepper-orchestrator.rules', '/.codex/pepper-setup.json', '/.pepper-worktrees/']
        for line in additions:
            if line not in old.splitlines():
                old += ('\n' if old and not old.endswith('\n') else '') + line + '\n'
        state_io.atomic(exclude, old.encode())
    return str(directory)
