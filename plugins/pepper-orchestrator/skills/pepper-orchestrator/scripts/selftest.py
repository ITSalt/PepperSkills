#!/usr/bin/env python3
"""Offline self-test for orch.py and safe_edit.py (standard library + git only)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import orch  # noqa: E402
import safe_edit  # noqa: E402

ORCH = [sys.executable, str(HERE / 'orch.py')]
GIT_ENV = {
    'GIT_AUTHOR_NAME': 'Selftest', 'GIT_AUTHOR_EMAIL': 'selftest@example.invalid',
    'GIT_COMMITTER_NAME': 'Selftest', 'GIT_COMMITTER_EMAIL': 'selftest@example.invalid',
    'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'commit.gpgsign', 'GIT_CONFIG_VALUE_0': 'false',
    'GIT_CONFIG_KEY_1': 'core.hooksPath', 'GIT_CONFIG_VALUE_1': '/dev/null',
}


def run(cwd, *args, ok=True):
    env = {**os.environ, **GIT_ENV, 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('ORCH_WORKSPACE', None)
    result = subprocess.run([*ORCH, *args], cwd=cwd, env=env, text=True, capture_output=True)
    if ok and result.returncode:
        raise AssertionError(f'orch {args} failed: {result.stderr}')
    if not ok and not result.returncode:
        raise AssertionError(f'orch {args} should have failed')
    return result


def git(cwd, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(['git', *args], cwd=cwd, env=env, text=True, capture_output=True,
                          check=True).stdout


def lint_errors(cwd):
    result = run(cwd, 'lint', ok=False)
    return result.stderr


def test_safe_edit(tmp):
    path = tmp / 'orch.yaml'
    path.write_text('program: x\n', encoding='utf-8')
    target = tmp / 'status.md'
    target.write_text('alpha\nbeta\nbeta\n', encoding='utf-8')
    safe_edit.replace_once(target, 'alpha', 'gamma')
    assert target.read_text(encoding='utf-8') == 'gamma\nbeta\nbeta\n'
    backups = list((tmp / safe_edit.BACKUP_DIR_NAME).glob('status.md.*'))
    assert len(backups) == 1 and backups[0].read_text(encoding='utf-8') == 'alpha\nbeta\nbeta\n'
    for old in ('beta', 'missing', ''):
        try:
            safe_edit.replace_once(target, old, 'x')
        except safe_edit.EditError:
            pass
        else:
            raise AssertionError(f'ambiguous or missing fragment accepted: {old!r}')
    assert target.read_text(encoding='utf-8') == 'gamma\nbeta\nbeta\n', 'failed edit changed file'
    try:
        safe_edit.create(target, 'new')
    except safe_edit.EditError:
        pass
    else:
        raise AssertionError('create overwrote an existing file')
    for empty in ('', '\n', ' \n\t'):
        try:
            safe_edit.create(tmp / 'sub/empty.md', empty)
        except safe_edit.EditError:
            pass
        else:
            raise AssertionError(f'created an empty file from {empty!r}')
    whole = tmp / 'whole.md'
    whole.write_text('only\n', encoding='utf-8')
    try:
        safe_edit.replace_once(whole, 'only\n', '\n')
    except safe_edit.EditError:
        pass
    else:
        raise AssertionError('replace_once emptied a file')
    assert whole.read_text(encoding='utf-8') == 'only\n'
    safe_edit.create(tmp / 'sub/new.md', 'Юникод\n')
    assert (tmp / 'sub/new.md').read_text(encoding='utf-8') == 'Юникод\n'
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target),
                          '--old', 'gamma', '--new', 'delta'], capture_output=True, text=True)
    assert cli.returncode == 0 and target.read_text(encoding='utf-8').startswith('delta')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target),
                          '--old', 'beta', '--new', 'x'], capture_output=True, text=True)
    assert cli.returncode == 1 and 'found 2' in cli.stderr
    print('PASS safe_edit: single match, backup, refusal, create-only, CLI')


SAMPLE_YAML = '''\
program: corp-clients            # prefix
title: "Corporate clients: B2B"
tag: CORP
owner_language: ru
push_after_milestone: true
modules:
  - id: db
    repo: ~/projects/example_database
    base: main
    tests: ["./scripts/test.sh"]
    deploy_prod: ./scripts/deploy.sh --target prod --type migrations
  - id: dispatcher
    repo: ~/projects/dispatcher
    tests: ["npm --prefix frontend run type-check", "npm --prefix frontend test"]
    web_urls: {test: https://test.example.com, prod: https://example.com}
environments:
  test: {db_mcp: example-test}
  prod: {db_mcp: example-prod}
guards:
  sql_select_only: [example-test, example-prod]
empty_list: []
nothing:
spec_graph: none   # none | nacl
note: 'it''s # not a comment'
'''


def test_yaml():
    parsed = orch.parse_yaml(SAMPLE_YAML)
    assert parsed['modules'][1]['web_urls']['prod'] == 'https://example.com'
    assert parsed['modules'][0]['tests'] == ['./scripts/test.sh']
    assert parsed['push_after_milestone'] is True and parsed['nothing'] is None
    assert parsed['title'] == 'Corporate clients: B2B'
    assert parsed['note'] == "it's # not a comment"
    try:
        import yaml
    except ImportError:
        print('SKIP PyYAML cross-check (not installed)')
    else:
        assert parsed == yaml.safe_load(SAMPLE_YAML), 'subset parser disagrees with PyYAML'
        print('PASS orch.yaml subset parser matches PyYAML')
    for bad in ('a: 1\n  b: 2\n', '- x\n', 'a:\n\t- b\n'):
        try:
            orch.parse_yaml(bad)
        except orch.OrchError:
            pass
        else:
            raise AssertionError(f'invalid YAML accepted: {bad!r}')
    print('PASS orch.yaml subset parser')


def test_workflow(tmp, lang):
    repo = tmp / f'home-{lang}'
    repo.mkdir()
    git(repo, 'init', '-q')
    run(repo, 'init', 'demo', '--lang', lang, '--title', 'Demo: "quoted" | program',
        '--module', 'db=~/projects/demo-db', '--module', 'web=~/projects/demo-web@develop')
    ws = repo / 'features/demo'
    config = orch.parse_yaml((ws / 'orch.yaml').read_text(encoding='utf-8'))
    assert config['title'] == 'Demo: "quoted" | program' and config['tag'] == 'DEMO'
    assert [m['base'] for m in config['modules']] == ['main', 'develop']
    run(repo, 'init', 'demo', '--lang', lang, ok=False)  # never over an existing workspace
    assert run(repo, 'lint').returncode == 0
    run(repo, 'new-wp', 'db', 'orders-table', '--title', 'Orders table')
    run(repo, 'new-wp', 'web', 'orders-page')
    run(repo, 'new-wp', 'db', 'orders-index')
    run(repo, 'new-wp', 'api', 'x', ok=False)
    run(repo, 'new-wp', 'db', 'Bad Slug', ok=False)
    wp_file = ws / 'work-packages/WP-DB-01-orders-table.md'
    text = wp_file.read_text(encoding='utf-8')
    assert '# WP-DB-01 — Orders table' in text and 'demo/wp-db-01-orders-table' in text
    assert '[DEMO] READY WP-DB-01' in text and str(wp_file.resolve()) in text
    assert '{{' not in text
    start = text[text.index('### Start command'):]
    command = start[start.index('```bash\n') + 8:start.index('\n```', start.index('```bash'))]
    assert command.startswith('cd ~/projects/demo-db && claude --name demo-db "')
    assert '--settings' not in command
    bootstrap = (ws / 'orchestration/bootstrap-prompt.md').read_text(encoding='utf-8')
    assert str(ws.resolve()) in bootstrap and '{{' not in bootstrap
    utc_date = orch.dt.datetime.now(orch.dt.timezone.utc).date().isoformat()
    assert f'| DRAFT | demo-db | — | {utc_date} |' in (ws / 'status.md').read_text(encoding='utf-8')
    assert (ws / 'work-packages/WP-DB-02-orders-index.md').is_file()
    run(repo, 'set', 'WP-DB-01', 'status', 'READY', '--evidence', 'reviewed')
    run(repo, 'set', 'WP-DB-01', 'status', 'BLOCKED', ok=False)
    run(repo, 'set', 'WP-DB-02', 'status', 'CANCELLED (hypothesis refuted by measurement)')
    run(repo, 'set', 'WP-WEB-01', 'pr', 'https://example.com/pull/7 | draft')
    run(repo, 'set', 'WP-WEB-01', 'module', 'db', ok=False)
    run(repo, 'set', 'WP-NONE-01', 'status', 'READY', ok=False)
    run(repo, 'owner', 'add', 'P', 'Export needed? (a) yes (b) no; recommend (b)')
    run(repo, 'owner', 'add', 'R', 'Merge: gh pr merge 7 ; expected: merged', '--where', 'x.md')
    run(repo, 'owner', 'add', 'X', 'bad', ok=False)
    queue = json.loads(run(repo, 'queue', '--json').stdout)
    assert [q['id'] for q in queue] == ['P-1', 'R-1']
    run(repo, 'decide', 'D', 'No export', '--closes', 'P-1')
    run(repo, 'decide', 'D', 'again', '--closes', 'P-1', ok=False)
    run(repo, 'owner', 'close', 'R-1', 'gh pr view 7: MERGED')
    run(repo, 'owner', 'close', 'R-1', 'twice', ok=False)
    run(repo, 'owner', 'add', 'R', 'obsolete item')
    run(repo, 'owner', 'drop', 'R-2', 'superseded by D-1')
    run(repo, 'decide', 'A', 'Staging mirrors production schema')
    assert 'empty' in run(repo, 'queue').stdout
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'https://example.com/pull/7 \\| draft' in status
    assert '| ~~P-1~~ |' in status and 'answered by D-1' in status
    assert 'dropped: superseded by D-1' in status
    decisions = (ws / 'decisions.md').read_text(encoding='utf-8')
    assert '| D-1 |' in decisions and '| A-1 |' in decisions
    run(repo, 'journal', 'text with <!-- orch:wp --> and <!-- orch:journal -->', '--wp', 'WP-DB-01')
    run(repo, 'owner', 'add', 'R', 'marker <!-- orch:owner --> in text')
    run(repo, 'owner', 'close', 'R-3', 'verified <!-- orch:owner -->')
    assert run(repo, 'lint').returncode == 0, 'marker text in a cell broke the tables'
    run(repo, 'journal', 'reconciled with reality', '--evidence', 'gh pr list')
    _, _, journal = orch.Workspace(ws).table(ws / 'status.md', 'journal')
    assert journal[0]['event'] == 'reconciled with reality'
    assert journal[-1]['event'].startswith('workspace created')
    assert run(repo, 'lint').returncode == 0

    # Commit and push to a local bare remote when push_after_milestone is true.
    remote = tmp / f'remote-{lang}.git'
    git(tmp, 'init', '-q', '--bare', str(remote))
    git(repo, 'remote', 'add', 'origin', str(remote))
    safe_edit.replace_once(ws / 'orch.yaml', 'push_after_milestone: false',
                           'push_after_milestone: true')
    (repo / 'unrelated.txt').write_text('not part of the workspace\n', encoding='utf-8')
    out = run(repo, 'commit', 'demo: plan and work packages').stdout
    assert 'push: ok' in out, out
    committed = git(repo, 'show', '--name-only', '--format=', 'HEAD').split()
    assert 'features/demo/status.md' in committed
    assert 'unrelated.txt' not in committed and not any('.orch-backup' in c for c in committed)
    assert git(remote, 'log', '--oneline').strip()
    assert 'nothing to commit' in run(repo, 'commit', 'again').stdout
    print(f'PASS workflow ({lang}): init, new-wp, set, owner, decide, journal, commit, push')
    return repo, ws


def test_lint_failures(repo, ws):
    status = ws / 'status.md'
    original = status.read_text(encoding='utf-8')

    def expect(fragment):
        errors = lint_errors(repo)
        assert fragment in errors, (fragment, errors)

    (ws / 'work-packages/WP-DB-09-orphan.md').write_text('# orphan\n', encoding='utf-8')
    expect('no row in the status.md WP table')
    (ws / 'work-packages/WP-DB-09-orphan.md').unlink()
    (ws / 'reports').mkdir()
    (ws / 'reports/empty.md').write_text('', encoding='utf-8')
    expect('empty file')
    (ws / 'reports/empty.md').write_text('\n', encoding='utf-8')
    expect('empty file')
    (ws / 'reports/empty.md').write_text('token = ghp_' + 'a' * 36 + '\n', encoding='utf-8')
    expect('looks like a secret')
    (ws / 'reports/empty.md').write_text('db: postgres://user:pa55word@host/db\n', encoding='utf-8')
    expect('looks like a secret')
    (ws / 'reports/empty.md').write_text('left {{WP}} unresolved\n', encoding='utf-8')
    expect('unresolved template placeholder')
    (ws / 'reports/empty.md').write_text('text\n>>>>>>> NEW\n', encoding='utf-8')
    expect('leftover edit marker line')
    (ws / 'reports/empty.md').write_text('password: <stored in vault>\n', encoding='utf-8')
    assert run(repo, 'lint').returncode == 0, 'placeholder value flagged as secret'
    (ws / 'reports/empty.md').unlink()
    lines = original.split('\n')
    wp_rows = [i for i, line in enumerate(lines) if line.startswith('| [WP-DB-01]')]
    duplicate = lines[:wp_rows[0] + 1] + [lines[wp_rows[0]]] + lines[wp_rows[0] + 1:]
    status.write_text('\n'.join(duplicate), encoding='utf-8')
    expect('duplicate WP WP-DB-01')
    status.write_text(original.replace('| READY |', '| SHIPPED |', 1), encoding='utf-8')
    expect("invalid status 'SHIPPED'")
    journal = [i for i, line in enumerate(lines) if line.startswith('| 20')]
    stale = lines[:journal[0]] + ['| 2020-01-01 00:00Z | — | old event | — |'] + lines[journal[0]:]
    status.write_text('\n'.join(stale), encoding='utf-8')
    expect('journal must be newest first')
    status.write_text(original.replace('<!-- orch:owner -->', ''), encoding='utf-8')
    expect('expected exactly one <!-- orch:owner -->')
    status.write_text(original, encoding='utf-8')
    assert run(repo, 'lint').returncode == 0
    print('PASS lint catches orphans, empties, secrets, placeholders, duplicates, order')


def test_discovery(tmp):
    repo = tmp / 'multi'
    repo.mkdir()
    run(repo, 'init', 'one', '--lang', 'en')
    assert run(repo, 'queue').returncode == 0  # single features/*/orch.yaml is found
    run(repo, 'init', 'two', '--lang', 'en')
    assert 'several workspaces' in run(repo, 'queue', ok=False).stderr
    assert run(repo, '--workspace', 'features/two', 'queue').returncode == 0
    assert run(repo, 'queue', '--workspace', 'features/two').returncode == 0
    assert run(repo, 'lint', '--workspace', 'features/one').returncode == 0
    assert run(repo / 'features/one/work-packages', 'lint').returncode == 0
    print('PASS workspace discovery: upward search, features/*, ambiguity, --workspace')



def test_safe_edit_stdin(tmp):
    target = tmp / 'stdin.md'
    target.write_text('alpha\nbeta\n', encoding='utf-8')
    block = '<<<<<<< OLD\nbeta\n=======\ngamma\ndelta\n>>>>>>> NEW\n'
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input=block, capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert target.read_text(encoding='utf-8') == 'alpha\ngamma\ndelta\n'
    two = ('<<<<<<< OLD\nalpha\n=======\nALPHA\n>>>>>>> NEW\n'
           '<<<<<<< OLD\ndelta\n=======\nDELTA\n>>>>>>> NEW\n')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input=two, capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n'
    atomic = ('<<<<<<< OLD\nALPHA\n=======\nx\n>>>>>>> NEW\n'
              '<<<<<<< OLD\nmissing\n=======\ny\n>>>>>>> NEW\n')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input=atomic, capture_output=True, text=True)
    assert cli.returncode == 1 and 'block 2' in cli.stderr
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n', 'partial multi-block edit'
    for broken in ('<<<<<<< OLD\nALPHA\n=======\n<<<<<<< OLD\n>>>>>>> NEW\n',
                   '<<<<<<< OLD\nALPHA\n=======\nx\n', 'stray\n<<<<<<< OLD\nALPHA\n=======\nx\n>>>>>>> NEW\n'):
        cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                             input=broken, capture_output=True, text=True)
        assert cli.returncode == 1, broken
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n'
    target.write_text('alpha\ngamma\ndelta\n', encoding='utf-8')
    bad = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input='no markers', capture_output=True, text=True)
    assert bad.returncode == 1 and 'OLD' in bad.stderr
    created = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(tmp / 'c.md'),
                              '--create', '--stdin'], input='new file\n', capture_output=True, text=True)
    assert created.returncode == 0 and (tmp / 'c.md').read_text(encoding='utf-8') == 'new file\n'
    blocker = tmp / 'not-a-dir'
    blocker.write_text('x\n', encoding='utf-8')
    env = {**os.environ, 'ORCH_BACKUP_DIR': str(blocker / 'sub')}
    fallback = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target),
                               '--old', 'alpha', '--new', 'omega'], env=env, capture_output=True, text=True)
    assert fallback.returncode == 0, fallback.stderr
    print('PASS safe_edit: stdin block, create from stdin, backup fallback')


def test_legacy_fixture(tmp):
    """Criterion 1: a 0.1.0 workspace passes lint and every command without changes."""
    home = tmp / 'legacy-home'
    ws = home / 'features/legacy'
    shutil.copytree(HERE / 'fixtures/workspace-0.1.0', ws)
    git(home, 'init', '-q')
    git(home, 'add', '-A')
    git(home, 'commit', '-qm', 'fixture 0.1.0')
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file()}
    assert run(home, 'lint').returncode == 0
    assert 'P-1' not in run(home, 'queue').stdout and 'R-1' in run(home, 'queue').stdout
    assert 'overlap: none' in run(home, 'overlap', '--planned').stdout
    assert run(home, 'worktrees').returncode == 0
    assert 'dry run' in run(home, 'dispatch', 'WP-API-01', '--dry-run').stdout
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file()}
    assert before == after, 'read-only commands changed a 0.1.0 workspace'
    run(home, 'new-wp', 'api', 'orders-import', '--title', 'Orders import')
    text = (ws / 'work-packages/WP-API-02-orders-import.md').read_text(encoding='utf-8')
    assert 'legacy/wp-api-02-orders-import' in text and 'cd ~/projects/example-api && claude --name' in text
    assert '-w ' not in text and '{{' not in text, 'old template must keep the 0.1.0 form'
    run(home, 'set', 'WP-API-02', 'status', 'READY')
    command = run(home, 'dispatch', 'WP-API-01').stdout
    assert command.startswith('cd ~/projects/example-api && claude --name legacy-api "'), command
    assert 'dispatch refused' in run(home, 'dispatch', 'WP-API-02', ok=False).stderr  # same repo
    run(home, 'owner', 'close', 'R-1', 'gh pr view 7: MERGED')
    run(home, 'decide', 'A', 'Import runs nightly')
    run(home, 'journal', 'legacy workspace still works')
    assert 'upgrade' in run(home, 'lock', 'list', ok=False).stderr
    run(home, 'upgrade')
    assert 'none' in run(home, 'lock', 'list').stdout
    assert 'already' in run(home, 'upgrade').stdout
    assert run(home, 'lint').returncode == 0
    assert 'commit:' in run(home, 'commit', 'legacy: still works').stdout
    print('PASS 0.1.0 workspace: lint, read-only commands unchanged, all commands work, upgrade')


def make_monorepo(tmp):
    """Anonymous demo monorepo: apps/admin, apps/app, backend, shared lockfile and migrations."""
    remote = tmp / 'mono.git'
    repo = tmp / 'mono'
    git(tmp, 'init', '-q', '--bare', str(remote))
    for rel, content in {
        'apps/admin/src/page.tsx': 'export const Admin = () => null;\n',
        'apps/app/src/page.tsx': 'export const App = () => null;\n',
        'backend/src/billing/invoice.ts': 'export const invoice = 1;\n',
        'backend/src/app.ts': 'export const routes = [];\n',
        'backend/migrations/0001_init.sql': 'create table t (id int);\n',
        'pnpm-lock.yaml': 'lockfileVersion: 9\n',
        'config.yaml': 'git:\n  strategy: feature-branch\n  branch_prefix: feature/\n',
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding='utf-8')
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'init')
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    return repo


def branch_with(repo, branch, files):
    """Create a worktree branch from origin/main and commit the given files there."""
    wt = repo / '.claude/worktrees' / branch.replace('/', '-')
    git(repo, 'worktree', 'add', '-q', '-b', branch, str(wt), 'origin/main')
    for rel in files:
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        with open(wt / rel, 'a', encoding='utf-8') as handle:
            handle.write(f'change for {branch}\n')
    git(wt, 'add', '-A')
    git(wt, 'commit', '-qm', f'work on {branch}')
    return wt


def fill_header(path, label, value):
    text = path.read_text(encoding='utf-8')
    line = next(l for l in text.split('\n') if l.startswith(f'| {label} |'))
    safe_edit.replace_once(path, line, f'| {label} | {value} |')


def test_monorepo(tmp):
    mono = make_monorepo(tmp)
    home = tmp / 'mono-home'
    home.mkdir()
    git(home, 'init', '-q')
    refused = run(mono, 'init', 'inside', '--lang', 'en', '--repo', f'mono={mono}', ok=False)
    assert 'module repository' in refused.stderr, 'P4: workspace in a module checkout must be refused'
    run(home, 'init', 'shop', '--lang', 'en', '--repo', f'mono={mono}',
        '--area', 'admin=mono:apps/admin/**', '--area', 'app=mono:apps/app/**',
        '--domain', 'billing=mono:backend/src/billing/**')
    ws = home / 'features/shop'
    config = ws / 'orch.yaml'
    parsed = orch.parse_yaml(config.read_text(encoding='utf-8'))
    assert parsed['repos'][0]['branch_prefix'] == 'feature/', 'branch prefix from repo convention'
    assert [m['kind'] for m in parsed['modules']] == ['area', 'area', 'domain']
    for old, new in (
        ('    worktree_setup: []', '    worktree_setup: ["cp ../../../.env.example .env", "pnpm install"]'),
        ('    shared_paths: []', '    shared_paths: [pnpm-lock.yaml, "backend/migrations/**", backend/src/app.ts]'),
        ('    resources: []', '    resources: [migrations, staging]'),
        ('    checks: []', '    checks: ["test -n \\"$ORCH_BRANCHES\\"", "echo duplicate migration 0002 && exit 3"]'),
    ):
        safe_edit.replace_once(config, old, new)
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    for mod, slug in (('admin', 'orders-list'), ('app', 'checkout'), ('billing', 'invoices')):
        run(home, 'new-wp', mod, slug)
    wps = ws / 'work-packages'
    admin = wps / 'WP-ADMIN-01-orders-list.md'
    app = wps / 'WP-APP-01-checkout.md'
    billing = wps / 'WP-BILLING-01-invoices.md'
    text = admin.read_text(encoding='utf-8')
    assert f'cd {mono} && claude -w wp-admin-01-orders-list --name shop-admin "' in text
    assert 'git fetch origin && git switch -c feature/wp-admin-01-orders-list origin/main' in text
    assert 'pnpm install' in text and '`apps/admin/**`' in text and '{{' not in text
    assert 'ref=<PR URL>' in text
    fill_header(app, 'Shared paths touched', '`pnpm-lock.yaml`')
    fill_header(billing, 'Shared paths touched', '`pnpm-lock.yaml`, `backend/migrations/**`')
    fill_header(billing, 'Resources (locks)', '`migrations`')
    fill_header(billing, 'Depends on', 'none')
    for wp in ('WP-ADMIN-01', 'WP-APP-01', 'WP-BILLING-01'):
        run(home, 'set', wp, 'status', 'READY')
    planned = run(home, 'overlap', '--planned', ok=False).stdout
    assert 'WP-APP-01 and WP-BILLING-01 both declare shared path pnpm-lock.yaml' in planned, planned
    out = run(home, 'dispatch', 'WP-APP-01').stdout
    assert out.startswith(f'cd {mono} && claude -w wp-app-01-checkout --name shop-app "'), out
    assert 'mono:pnpm-lock.yaml' in run(home, 'lock', 'list').stdout
    refusal = run(home, 'dispatch', 'WP-BILLING-01', ok=False).stderr
    assert 'lock mono:pnpm-lock.yaml is held by WP-APP-01' in refusal and 'queued' in refusal, refusal
    locks = json.loads(run(home, 'lock', 'list', '--json').stdout)
    assert locks[0]['waiting'] == 'WP-BILLING-01' and len(locks) == 1, locks
    assert run(home, 'dispatch', 'WP-ADMIN-01').returncode == 0
    run(home, 'lock', 'release', 'pnpm-lock.yaml', '--wp', 'WP-ADMIN-01', ok=False)  # not the holder
    # Overlap without a lock: declared paths reaching into an active stream refuse dispatch.
    run(home, 'new-wp', 'billing', 'cart-fees')
    fees = wps / 'WP-BILLING-02-cart-fees.md'
    fill_header(fees, 'Allowed paths', '`backend/src/billing/**`, `apps/app/src/cart/**`')
    run(home, 'set', 'WP-BILLING-02', 'status', 'READY')
    refusal = run(home, 'dispatch', 'WP-BILLING-02', ok=False).stderr
    assert 'paths overlap with WP-APP-01 outside shared paths' in refusal, refusal
    run(home, 'new-wp', 'app', 'coupons')
    run(home, 'set', 'WP-APP-02', 'status', 'READY')
    assert 'already runs in stream app' in run(home, 'dispatch', 'WP-APP-02', ok=False).stderr
    for wp in ('WP-BILLING-02', 'WP-APP-02'):
        run(home, 'set', wp, 'status', 'CANCELLED (selftest case)')
    # Actual branches: app touches admin files and an undeclared migration; admin shares a file.
    branch_with(mono, 'feature/wp-app-01-checkout',
                ['apps/app/src/page.tsx', 'pnpm-lock.yaml', 'apps/admin/src/page.tsx',
                 'backend/migrations/0002_orders.sql'])
    branch_with(mono, 'feature/wp-admin-01-orders-list', ['apps/admin/src/page.tsx'])
    actual = run(home, 'overlap', ok=False).stdout
    for expected in ('WP-APP-01: apps/admin/src/page.tsx is outside the allowed paths',
                     'WP-APP-01: shared path backend/migrations/0002_orders.sql changed but not declared',
                     'WP-ADMIN-01 and WP-APP-01 both change apps/admin/src/page.tsx',
                     '[check] mono: `echo duplicate migration 0002 && exit 3` failed: duplicate migration 0002'):
        assert expected in actual, (expected, actual)
    assert 'pnpm-lock.yaml changed without the lock' not in actual, 'held lock must satisfy overlap'
    trees = json.loads(run(home, 'worktrees', '--json').stdout)
    assert {t['wp'] for t in trees} >= {'WP-APP-01', 'WP-ADMIN-01'}, trees
    released = run(home, 'lock', 'release', 'pnpm-lock.yaml', '--wp', 'WP-APP-01').stdout
    assert 'next in queue: WP-BILLING-01' in released
    assert run(home, 'dispatch', 'WP-BILLING-01').returncode == 0
    held = {l['lock']: l['holder'] for l in json.loads(run(home, 'lock', 'list', '--json').stdout)}
    assert held == {'mono:pnpm-lock.yaml': 'WP-BILLING-01', 'mono:backend/migrations/**': 'WP-BILLING-01',
                    'mono:migrations': 'WP-BILLING-01'}, held
    run(home, 'merge', 'add', 'WP-BILLING-01', '--pr', 'https://example.invalid/pull/1')
    queued = run(home, 'merge', 'add', 'WP-ADMIN-01').stdout
    assert 'rebase after WP-BILLING-01' in queued
    run(home, 'merge', 'add', 'WP-ADMIN-01', ok=False)
    done = run(home, 'merge', 'done', 'WP-BILLING-01', '--evidence', 'gh pr view 1: MERGED').stdout
    assert 'still held (release after verification): mono:migrations' in done
    assert 'next: rebase WP-ADMIN-01' in done
    assert {l['lock'] for l in json.loads(run(home, 'lock', 'list', '--json').stdout)} == {'mono:migrations'}
    assert 'WP-ADMIN-01' in run(home, 'merge', 'list').stdout
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    # Lint: overlapping module paths and whole-repository modules sharing a repository.
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, 'paths: ["backend/src/billing/**"]',
                           'paths: ["backend/src/billing/**", "apps/app/src/**"]')
    assert 'modules app and billing overlap outside shared_paths' in lint_errors(home)
    config.write_text(original, encoding='utf-8')
    safe_edit.replace_once(config, '    kind: domain\n', '    kind: repo\n')
    assert 'must become kind area|domain' in lint_errors(home)
    config.write_text(original, encoding='utf-8')
    # P4: committing a workspace that lives in a module checkout on the base branch is refused.
    inner = mono / 'orch-ws'
    shutil.copytree(ws, inner, ignore=shutil.ignore_patterns('.orch-backup'))
    assert 'module repository' in run(mono, '--workspace', str(inner), 'commit', 'x', ok=False).stderr
    shutil.rmtree(inner)
    assert run(home, 'commit', 'shop: streams demo').returncode == 0
    print('PASS monorepo: init areas/domain, worktree start commands, overlap, locks, dispatch, merge queue, P4')

def main():
    with tempfile.TemporaryDirectory(prefix='pepper-orchestrator-selftest-') as raw:
        tmp = Path(raw)
        (tmp / 'edit').mkdir()
        test_safe_edit(tmp / 'edit')
        test_yaml()
        for lang in orch.LANGUAGES:
            repo, ws = test_workflow(tmp, lang)
        test_lint_failures(repo, ws)
        test_discovery(tmp)
        test_safe_edit_stdin(tmp / 'edit')
        test_legacy_fixture(tmp)
        test_monorepo(tmp)
    print('PASS pepper-orchestrator selftest')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
