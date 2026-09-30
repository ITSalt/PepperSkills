#!/usr/bin/env python3
"""Verification of a deployment by facts: the deploy run for the SHA, the served version, and the
repository's read-only verify commands. Used by `orch.py verify`; standard library + git (and gh
for workflow runs and merge commits). Imported by orch.py.
"""
import json
import os
import re
import subprocess
import urllib.request

import streams

ENVS = ('test', 'prod')
DEFAULT_TIMEOUT = 300
OUTPUT_LINES = 5
# Statuses a package may be verified from, per environment.
VERIFIABLE = {'test': ('ACCEPTED',) + streams.SATISFIED, 'prod': streams.SATISFIED}
TARGET = {'test': 'VERIFIED_TEST', 'prod': 'PROD'}
# A package already past the target keeps its status on PASS (never a downgrade).
LATER = {'test': ('PROD', 'DONE'), 'prod': ('DONE',)}

TEXT = {
    'en': {
        'deploy': 'deploy run', 'version': 'served version', 'command': 'verify command',
        'none': 'none', 'skipped': 'skipped',
        'bug_title': '{wp}: verification on {env} failed',
        'bug_found': '{date}, orch.py verify --env {env} (report {report})',
        'bug_symptom': 'Failed checks:', 'bug_repro': 'Run `orch.py verify {wp} --env {env} --sha {sha}`.',
        'bug_expected': 'Every check passes for `{sha}`.', 'bug_cause': 'Not established yet.',
        'bug_status': 'open', 'bug_severity': 'high',
    },
    'ru': {
        'deploy': 'run деплоя', 'version': 'отдаваемая версия', 'command': 'команда проверки',
        'none': 'нет', 'skipped': 'пропущено',
        'bug_title': '{wp}: проверка на {env} не пройдена',
        'bug_found': '{date}, orch.py verify --env {env} (отчёт {report})',
        'bug_symptom': 'Проваленные проверки:', 'bug_repro': 'Запусти `orch.py verify {wp} --env {env} --sha {sha}`.',
        'bug_expected': 'Все проверки проходят для `{sha}`.', 'bug_cause': 'Пока не установлена.',
        'bug_status': 'open', 'bug_severity': 'high',
    },
}


def conf(module, key):
    """A verify setting of the module, else of its repository (0.1.0 modules keep them on the module)."""
    if key in module.raw:
        return module.raw.get(key)
    return module.repo.raw.get(key)


def per_env(value, env):
    """A setting given once or as {test: ..., prod: ...}."""
    if isinstance(value, dict):
        return value.get(env)
    return value


def commands(module, env):
    return streams.as_list(conf(module, f'verify_{env}'))


def workflows(module, env):
    return streams.as_list(per_env(conf(module, 'deploy_workflows'), env))


def branch(module, env):
    key = 'prod_branch' if env == 'prod' else 'integration_branch'
    return str(conf(module, key) or module.repo.base)


def base_url(module, env):
    urls = conf(module, 'web_urls')
    return str(urls.get(env) or '') if isinstance(urls, dict) else ''


def version_source(module, env):
    url = per_env(conf(module, 'version_url'), env)
    pattern = per_env(conf(module, 'version_pattern'), env)
    if not url:
        return None, None
    url = str(url).replace('{base_url}', base_url(module, env).rstrip('/')).replace('{env}', env)
    return url, (str(pattern) if pattern else None)


def timeout(config):
    value = config.get('verify_timeout')
    return value if isinstance(value, int) and value > 0 else DEFAULT_TIMEOUT


def first_lines(text, redact):
    lines = [redact(line.rstrip()) for line in (text or '').strip().split('\n') if line.strip()]
    return lines[:OUTPUT_LINES]


def gh_json(args):
    result = subprocess.run(['gh', *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip().split('\n')[0] or f'gh exited {result.returncode}')
    try:
        return json.loads(result.stdout or 'null')
    except ValueError as error:
        raise RuntimeError(f'gh returned no JSON: {error}')


def merge_commit(repo_name, pr):
    """The merge commit SHA of a merged PR, through gh."""
    data = gh_json(['pr', 'view', pr, '--repo', repo_name, '--json', 'state,mergeCommit'])
    if not data or data.get('state') != 'MERGED' or not (data.get('mergeCommit') or {}).get('oid'):
        raise RuntimeError(f'PR {pr} is not merged ({(data or {}).get("state", "unknown")})')
    return data['mergeCommit']['oid']


def deploy_run(repo_name, workflow, sha, branch_name):
    """(verdict, detail): the runs of workflow for sha on branch; any success passes."""
    runs = gh_json(['run', 'list', '--repo', repo_name, '--workflow', workflow, '--commit', sha, '--json',
                    'databaseId,status,conclusion,headBranch,url,createdAt', '--limit', '20']) or []
    runs = [r for r in runs if not r.get('headBranch') or r.get('headBranch') == branch_name]
    ok = [r for r in runs if r.get('conclusion') == 'success']
    if ok:
        return 'PASS', f'{workflow}: success {ok[0].get("url") or ok[0].get("databaseId")}'
    running = [r for r in runs if r.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested')]
    if running:
        return 'FAIL', f'{workflow}: still {running[0].get("status")} for {sha[:10]} on {branch_name}; verify again later'
    if runs:
        return 'FAIL', f'{workflow}: {runs[0].get("conclusion") or runs[0].get("status")} for {sha[:10]} on {branch_name}'
    return 'FAIL', f'{workflow}: no run for {sha[:10]} on {branch_name}'


def served_version(url, pattern, sha, expect_version=None):
    """(verdict, detail): the version the environment serves against the expected SHA or version."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read(1_000_000).decode('utf-8', errors='replace')
    except Exception as error:  # network, HTTP or URL errors are a failed check, never a crash
        return 'FAIL', f'{url}: {type(error).__name__}: {error}'
    if pattern:
        match = re.search(pattern, body)
        if not match:
            return 'FAIL', f'{url}: version_pattern not found'
        found = (match.group(1) if match.groups() else match.group(0)).strip()
    else:
        found = sha[:12] if sha and sha[:7].lower() in body.lower() else ''
        if not found:
            return 'FAIL', f'{url}: {sha[:10]} not found in the response'
    low, want = found.lower(), (sha or '').lower()
    if want and len(low) >= 7 and (want.startswith(low) or low.startswith(want)):
        return 'PASS', f'{url}: serves {found}'
    if expect_version and found == expect_version:
        return 'PASS', f'{url}: serves version {found}'
    return 'FAIL', f'{url}: serves {found}, expected {sha[:10] if sha else ""}' + \
        (f' or version {expect_version}' if expect_version else '')


def run_command(command, cwd, env, limit, redact):
    """(verdict, exit, output lines) of one read-only verify command."""
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, env=env, text=True, capture_output=True,
                                timeout=limit)
    except subprocess.TimeoutExpired as error:
        out = error.stdout.decode(errors='replace') if isinstance(error.stdout, bytes) else (error.stdout or '')
        return 'FAIL', 'timeout', [f'timed out after {limit} s'] + first_lines(out, redact)
    return ('PASS' if result.returncode == 0 else 'FAIL'), str(result.returncode), \
        first_lines(result.stdout + result.stderr, redact)


def command_env(env, sha, wp, url):
    return {**os.environ, 'ORCH_ENV': env, 'ORCH_SHA': sha or '', 'ORCH_WP': wp, 'ORCH_BASE_URL': url}


def cell(text):
    text = ' '.join(str(text).split()).replace('|', '\\|').replace('<!--', '&lt;!--')
    return text or '—'


def table(rows):
    """Markdown table of check rows {kind, target, exit, output, verdict}."""
    lines = ['| # | Check | Command or target | Exit | Output (first lines) | Verdict |',
             '|---|-------|-------------------|------|----------------------|---------|']
    for i, r in enumerate(rows, 1):
        lines.append('| ' + ' | '.join([str(i), cell(r['kind']), cell(f'`{r["target"]}`'), cell(r['exit']),
                                        cell(' / '.join(r['output']) or '—'), cell(r['verdict'])]) + ' |')
    return '\n'.join(lines)
