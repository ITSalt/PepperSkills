#!/usr/bin/env python3
"""Reports of defects in the plugin itself: facts, anonymization, duplicate search, Issue.

A report never carries a name of the program, its modules, sessions, repositories or origins, a
home path, an e-mail, a token, or a term from `.private-terms.local`: everything is replaced by
placeholders and the result is scanned again before anything is written or sent. Standard library
+ git (and gh for Issues). Imported by orch.py.
"""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

import streams

REPOSITORY = 'ITSalt/PepperSkills'
LABELS = ('bug', 'from-agent', 'needs-triage')
TERMS_FILE = '.private-terms.local'
OUTPUT_LINES = 30
# Home directories on macOS, Linux and Windows; built from pieces so this file does not match itself.
HOME_PATHS = re.compile('(' + '|'.join([
    '/' + 'Users/[^/\\s]+',
    '/' + 'home/[a-z_][^/\\s]*',
    '[A-Za-z]:' + r'[\\/]{1,2}' + 'Users' + r'[\\/]{1,2}[^\\/\s]+',
]) + ')')
EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
ERROR_HINT = re.compile(r'(error|refused|failed|traceback|exception|cannot|denied)', re.I)


class ReportError(Exception):
    pass


# ---------------------------------------------------------------- facts

def plugin_version(skill_dir):
    """(plugin name, version) of the installed copy, from SKILL.md frontmatter."""
    text = (Path(skill_dir) / 'SKILL.md').read_text(encoding='utf-8')
    name = re.search(r'^name:\s*(\S+)', text, re.M)
    version = re.search(r'^\s+version:\s*(\S+)', text, re.M)
    return (name.group(1) if name else 'pepper-orchestrator'), (version.group(1) if version else 'unknown')


def claude_version():
    if os.environ.get('ORCH_NO_CLAUDE') == '1' or not shutil.which('claude'):
        return 'unknown (not queried)'
    try:
        result = subprocess.run(['claude', '--version'], text=True, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    return (result.stdout.strip().split('\n') or ['unknown'])[0] or 'unknown'


def shell_name(config):
    if config.get('shell'):
        return str(config['shell'])
    for key in ('SHELL', 'ComSpec'):
        if os.environ.get(key):
            return re.split(r'[\\/]', os.environ[key])[-1]
    return 'unknown'


def environment_facts(skill_dir, config):
    plugin, version = plugin_version(skill_dir)
    return {'plugin': plugin, 'version': version, 'claude': claude_version(),
            'os': f'{platform.system()} {platform.release()} ({platform.machine()})',
            'python': sys.version.split()[0], 'shell': shell_name(config)}


def workspace_shape(config, repos, modules):
    kinds = [m.kind for m in modules.values()]
    return (f'workspace {config.get("workspace_mode") or "separate"}, sessions {config.get("sessions") or "local"}, '
            f'{len(modules)} modules ({kinds.count("repo")} whole repositories, '
            f'{len(kinds) - kinds.count("repo")} streams), {len(repos) or len({m.repo.key for m in modules.values()})} '
            f'repositories, permission mode {config.get("permission_mode") or "unset"}, '
            f'shell {config.get("shell") or "bash"}')


def first_error_line(lines):
    for line in lines:
        if ERROR_HINT.search(line):
            return line.strip()
    return next((line.strip() for line in lines if line.strip()), '')


# ---------------------------------------------------------------- anonymization

def load_terms(*roots):
    terms = []
    for root in roots:
        if root is None:
            continue
        path = Path(root) / TERMS_FILE
        if path.is_file():
            for line in path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and line.lower() not in terms:
                    terms.append(line.lower())
    return terms


def private_names(config, repos, modules, workspace_root):
    """[(value, placeholder)] from orch.yaml and the local paths behind it, longest first."""
    pairs = []

    def add(value, placeholder):
        value = str(value or '').strip()
        if len(value) >= 2 and value.lower() not in {'main', 'master', 'local', 'cloud', 'auto', 'none', 'repo'}:
            pairs.append((value, placeholder))

    root = Path(workspace_root)
    for form in {str(root), str(root.resolve())}:
        add(form, '<workspace>')
    all_repos = list({m.repo.key: m.repo for m in modules.values()}.values())
    all_repos += [r for r in repos.values() if r.key not in {x.key for x in all_repos}]
    for n, repo in enumerate(all_repos, 1):
        for form in {repo.path, str(repo.local), str(repo.local.resolve())}:
            if form not in ('.', ''):
                add(form, f'<repo-{n}>')
        add(repo.id, f'<repo-{n}>')
        if repo.local.is_dir():
            url = streams.git(repo.local, 'config', '--get', 'remote.origin.url').stdout.strip()
            normalized = streams.normalize_url(url, repo.local) if url else None
            add(url, f'<origin-{n}>')
            add(normalized, f'<origin-{n}>')
            if normalized and not normalized.startswith('/'):
                add('/'.join(normalized.split('/')[-2:]), f'<origin-{n}>')
    for n, module in enumerate(modules.values(), 1):
        add(module.id, f'<module-{n}>')
        add(module.session, f'<session-{n}>')
        add(module.cloud_environment, f'<environment-{n}>')
        urls = module.raw.get('web_urls')
        for env, url in (urls.items() if isinstance(urls, dict) else []):
            host = re.sub(r'^[a-z]+://', '', str(url)).split('/')[0]
            add(url, f'<url-{env}>')
            add(host, f'<host-{env}>')
    add(config.get('coordinator_session'), '<coordinator>')
    add(config.get('title'), '<title>')
    add(config.get('workspace_branch'), '<workspace-branch>')
    add(config.get('cloud_environment'), '<environment>')
    add(config.get('program'), '<program>')
    add(config.get('tag'), '<tag>')
    unique, seen = [], set()
    for value, placeholder in sorted(pairs, key=lambda p: -len(p[0])):
        if value.lower() not in seen:
            seen.add(value.lower())
            unique.append((value, placeholder))
    return unique


def _pattern(value):
    return re.compile(r'(?<![A-Za-z0-9_])' + re.escape(value) + r'(?![A-Za-z0-9_])', re.I)


def anonymize(text, names, terms, secret_patterns):
    home = str(Path.home())
    for value, placeholder in names:
        text = _pattern(value).sub(placeholder, text)
    if len(home) > 1:
        text = text.replace(home, '~')
    text = HOME_PATHS.sub('<home>', text)
    text = EMAIL.sub('[redacted]', text)
    for pattern in secret_patterns:
        text = pattern.sub('[redacted]', text)
    for term in terms:
        text = re.compile(re.escape(term), re.I).sub('[redacted]', text)
    return text


def leaks(text, names, terms, secret_patterns):
    """What still looks private in text: the same checks that anonymize applies."""
    found = []
    for value, _ in names:
        if _pattern(value).search(text):
            found.append(f'name from orch.yaml ({len(value)} characters)')
    if HOME_PATHS.search(text):
        found.append('home-directory path')
    if EMAIL.search(text):
        found.append('e-mail address')
    if any(p.search(text) for p in secret_patterns):
        found.append('secret-looking string')
    lower = text.lower()
    found += [f'term from {TERMS_FILE}' for term in terms if term in lower]
    return found


# ---------------------------------------------------------------- Issue

def fingerprint(plugin, version, error_line):
    text = re.sub(r'<[^>\s]+>|\[redacted\]', ' ', error_line)  # placeholders differ between reporters
    words = ' '.join(re.sub(r'[^\w\s.:-]', ' ', text).split())[:80]
    return f'{plugin} {version} {words}'.strip()


def gh(args):
    result = subprocess.run(['gh', *args], text=True, capture_output=True)
    if result.returncode:
        raise ReportError((result.stderr or result.stdout).strip().split('\n')[0] or f'gh exited {result.returncode}')
    return result.stdout


def find_duplicates(query):
    out = gh(['issue', 'list', '--repo', REPOSITORY, '--search', query, '--state', 'all',
              '--json', 'number,title,url,state'])
    try:
        return json.loads(out or '[]')
    except ValueError:
        return []


def create_issue(title, body_file):
    """URL of the new Issue; without the triage labels when the repository lacks them."""
    base = ['issue', 'create', '--repo', REPOSITORY, '--title', title, '--body-file', str(body_file)]
    try:
        out = gh(base + [a for label in LABELS for a in ('--label', label)])
        missing = False
    except ReportError as error:
        if 'label' not in str(error).lower():
            raise
        out, missing = gh(base + ['--label', 'bug']), True
    urls = re.findall(r'https://\S+/issues/\d+', out)
    return (urls[-1] if urls else out.strip()), missing


def comment_issue(number, body_file):
    out = gh(['issue', 'comment', str(number), '--repo', REPOSITORY, '--body-file', str(body_file)])
    urls = re.findall(r'https://\S+', out)
    return urls[-1] if urls else f'#{number}'


def latest_version():
    """The version of pepper-orchestrator on main of the marketplace repository, through gh."""
    out = gh(['api', f'repos/{REPOSITORY}/contents/plugins/pepper-orchestrator/plugin.json',
              '--jq', '.content'])
    import base64
    data = json.loads(base64.b64decode(out.strip() or 'e30=').decode('utf-8'))
    return str(data.get('version') or '')


def version_key(version):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r'[.-]', version))
