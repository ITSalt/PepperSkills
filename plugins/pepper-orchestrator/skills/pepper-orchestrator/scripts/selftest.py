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
    'GIT_CONFIG_COUNT': '3', 'GIT_CONFIG_KEY_0': 'commit.gpgsign', 'GIT_CONFIG_VALUE_0': 'false',
    'GIT_CONFIG_KEY_1': 'core.hooksPath', 'GIT_CONFIG_VALUE_1': '/dev/null',
    # Like CI runners: a default branch other than main must not break any fixture.
    'GIT_CONFIG_KEY_2': 'init.defaultBranch', 'GIT_CONFIG_VALUE_2': 'master',
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
    tmp.mkdir(parents=True, exist_ok=True)
    remote = tmp / 'mono.git'
    repo = tmp / 'mono'
    git(tmp, 'init', '-q', '--bare', str(remote))
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')  # explicit initial branch on any git
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
    git(repo, 'init', '-q')
    git(repo, 'symbolic-ref', 'HEAD', 'refs/heads/main')
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


def test_p4_identity(tmp):
    """P4 by git common dir and origin: worktree on orch/ allowed, base in worktree or clone refused."""
    mono = make_monorepo(tmp / 'p4')
    wt_ok = tmp / 'p4/wt-orch'
    git(mono, 'worktree', 'add', '-q', '-b', 'orch/shop', str(wt_ok), 'main')
    assert run(wt_ok, 'init', 'shop', '--lang', 'en', '--repo', f'mono={mono}').returncode == 0
    wt_base = tmp / 'p4/wt-base'
    git(mono, 'switch', '-q', '-c', 'side')  # free main for a linked worktree
    git(mono, 'worktree', 'add', '-q', str(wt_base), 'main')
    refused = run(wt_base, 'init', 'shop', '--lang', 'en', '--repo', f'mono={mono}', ok=False)
    assert 'linked worktree of module repository' in refused.stderr, refused.stderr
    clone = tmp / 'p4/clone'
    git(tmp, 'clone', '-q', str(tmp / 'p4/mono.git'), str(clone))
    refused = run(clone, 'init', 'shop', '--lang', 'en', '--repo', f'mono={mono}', ok=False)
    assert 'checkout or clone of module repository' in refused.stderr, refused.stderr
    # commit is refused the same way when a workspace was copied onto a base worktree.
    shutil.copytree(wt_ok / 'features/shop', wt_base / 'features/shop',
                    ignore=shutil.ignore_patterns('.orch-backup'))
    assert 'linked worktree' in run(wt_base, 'commit', 'x', ok=False).stderr
    # L7: orch/ in the main checkout while a whole-repository module works there: warning.
    solo = make_monorepo(tmp / 'p4solo')
    git(solo, 'switch', '-q', '-c', 'orch/solo')
    out = run(solo, 'init', 'solo', '--lang', 'en', '--module', f'core={solo}')
    assert 'warning' in out.stdout and 'main checkout' in out.stdout, out.stdout
    assert 'main checkout' in run(solo, 'lint').stderr
    # git older than 2.31 echoes the unknown --path-format option and prints a relative path.
    import streams
    real = streams.git

    def old_git(root, *args):
        if '--path-format=absolute' in args:
            rest = [a for a in args if a != '--path-format=absolute']
            result = real(root, *rest)
            relative = os.path.relpath(result.stdout.strip(), root)
            return subprocess.CompletedProcess(args, 0, '--path-format=absolute\n' + relative + '\n', '')
        return real(root, *args)
    streams.git = old_git
    try:
        assert streams.common_dir(wt_base) == Path(real(mono, 'rev-parse', '--path-format=absolute',
                                                        '--git-common-dir').stdout.strip()).resolve()
    finally:
        streams.git = real
    print('PASS P4: common dir + origin (worktree on orch/ ok, base worktree and clone refused), L7 warning')


def test_streams_edges(tmp):
    mono = make_monorepo(tmp / 'edges')
    home = tmp / 'edges/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'edge', '--lang', 'en', '--repo', f'mono={mono}',
        '--area', 'web=mono:apps/{admin,app}/**', '--domain', 'admin-ui=mono:backend/src/billing/**')
    ws = home / 'features/edge'
    config = ws / 'orch.yaml'
    assert 'paths: ["apps/{admin,app}/**"]' in config.read_text(encoding='utf-8'), 'braces kept by init'
    assert run(home, 'init', 'bad', '--lang', 'en', '--repo', f'mono={mono}',
               '--area', 'x=mono:apps/{admin/**', ok=False).returncode == 1
    for old, new in (
        ('    merge_policy: sequential\n    shared_paths',
         '    merge_policy: sequential\n    push_deploys: true\n    shared_paths'),
        ('    shared_paths: []', '    shared_paths: [pnpm-lock.yaml, "backend/migrations/**", "src/*.{ts,tsx}"]'),
        ('    resources: []', '    resources: [staging, migrations]'),
    ):
        safe_edit.replace_once(config, old, new)
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, 'paths: ["backend/src/billing/**"]', 'paths: ["apps/app/**"]')
    assert 'modules web and admin-ui overlap' in lint_errors(home), 'braces must expand for overlap'
    config.write_text(original, encoding='utf-8')
    # M3: a dependency on a module id with a hyphen is honoured.
    run(home, 'new-wp', 'admin-ui', 'fees')
    run(home, 'new-wp', 'web', 'fees-view')
    view = ws / 'work-packages/WP-WEB-01-fees-view.md'
    fill_header(view, 'Depends on', 'WP-ADMIN-UI-01')
    run(home, 'set', 'WP-WEB-01', 'status', 'READY')
    refusal = run(home, 'dispatch', 'WP-WEB-01', '--dry-run', ok=False).stderr
    assert 'depends on WP-ADMIN-UI-01 (DRAFT)' in refusal, refusal
    # Push = deploy: delivery tells the stream to wait for the stand slot.
    assert 'do not push until the orchestrator gives you the stand slot' in view.read_text(encoding='utf-8')
    # L1: path locks collide by glob; unknown resources are refused.
    fees = ws / 'work-packages/WP-ADMIN-UI-01-fees.md'
    fill_header(fees, 'Shared paths touched', '`backend/migrations/**`')
    run(home, 'set', 'WP-ADMIN-UI-01', 'status', 'READY')
    assert run(home, 'dispatch', 'WP-ADMIN-UI-01').returncode == 0
    fill_header(view, 'Depends on', 'none')
    fill_header(view, 'Shared paths touched', '`backend/migrations/0002_fees.sql`')
    refusal = run(home, 'dispatch', 'WP-WEB-01', ok=False).stderr
    assert 'mono:backend/migrations/** is held by WP-ADMIN-UI-01' in refusal, refusal
    assert 'unknown lock' in run(home, 'lock', 'acquire', 'stagin', '--wp', 'WP-WEB-01', ok=False).stderr
    assert 'unknown lock' in run(home, 'lock', 'acquire', 'docs/readme.md', '--wp', 'WP-WEB-01',
                                 ok=False).stderr
    # L2: merge done keeps the queue on a free row and names who waits; the queue is respected.
    run(home, 'merge', 'add', 'WP-ADMIN-UI-01')
    done = run(home, 'merge', 'done', 'WP-ADMIN-UI-01').stdout
    assert 'WP-WEB-01 (waits for mono:backend/migrations/**)' in done, done
    lock = json.loads(run(home, 'lock', 'list', '--json').stdout)[0]
    assert lock['holder'] == '—' and lock['waiting'] == 'WP-WEB-01', lock
    run(home, 'set', 'WP-ADMIN-UI-01', 'status', 'MERGED', '--evidence', 'merge verified')
    run(home, 'new-wp', 'admin-ui', 'refunds')
    refunds = ws / 'work-packages/WP-ADMIN-UI-02-refunds.md'
    fill_header(refunds, 'Shared paths touched', '`backend/migrations/**`')
    run(home, 'set', 'WP-ADMIN-UI-02', 'status', 'READY')
    assert 'WP-WEB-01 is first in its queue' in run(home, 'dispatch', 'WP-ADMIN-UI-02', ok=False).stderr
    assert run(home, 'dispatch', 'WP-WEB-01').returncode == 0
    held = {l['lock']: (l['holder'], l['waiting']) for l in json.loads(run(home, 'lock', 'list', '--json').stdout)}
    assert held == {'mono:backend/migrations/**': ('—', 'WP-ADMIN-UI-02'),
                    'mono:backend/migrations/0002_fees.sql': ('WP-WEB-01', '—')}, held
    # WP-WEB-01 left the queue when it got its lock; after its release WP-ADMIN-UI-02 goes next.
    run(home, 'lock', 'release', 'backend/migrations/0002_fees.sql', '--wp', 'WP-WEB-01')
    assert run(home, 'dispatch', 'WP-ADMIN-UI-02').returncode == 0
    held = {l['lock']: (l['holder'], l['waiting']) for l in json.loads(run(home, 'lock', 'list', '--json').stdout)}
    assert held == {'mono:backend/migrations/**': ('WP-ADMIN-UI-02', '—')}, held
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    print('PASS streams edges: braces, hyphen ids, push=deploy slot, glob locks, unknown lock, queue after merge')


def test_legacy_shared_path(tmp):
    """M4: 0.1.0 modules on one path: lint warns (commit works), each module keeps its base."""
    home = tmp / 'legacy2'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'two', '--lang', 'en', '--module', 'api=~/projects/example-api',
        '--module', 'lts=~/projects/example-api@release/1.x')
    out = run(home, 'lint')
    assert out.returncode == 0 and 'dispatched one at a time' in out.stderr, out.stderr
    run(home, 'new-wp', 'lts', 'backport')
    text = (home / 'features/two/work-packages/WP-LTS-01-backport.md').read_text(encoding='utf-8')
    assert 'from release/1.x' in text or 'от release/1.x' in text or 'origin/release/1.x' in text, text
    assert 'PR to release/1.x' in text
    run(home, 'new-wp', 'api', 'fix')
    run(home, 'set', 'WP-API-01', 'status', 'READY')
    run(home, 'set', 'WP-LTS-01', 'status', 'READY')
    assert run(home, 'dispatch', 'WP-API-01').returncode == 0
    assert 'same repository' in run(home, 'dispatch', 'WP-LTS-01', '--dry-run', ok=False).stderr
    assert 'commit:' in run(home, 'commit', 'two modules on one path').stdout
    print('PASS 0.1.0 modules sharing a path: warning not error, own base, serialized dispatch')


DEPLOY_WORKFLOW = """name: Deploy
on:
  push:
    branches: ["**"]
    paths-ignore:
      - 'docs/**'
      - '**.md'
  workflow_dispatch:
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: echo deploy
"""


def with_workflow(repo, text, name='deploy.yml'):
    path = repo / '.github/workflows' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', f'add {name}')
    git(repo, 'push', '-q', 'origin', 'main')


def test_cloud_in_repo(tmp):
    """2c: in-repo workspace on orch/<program> under paths-ignore; cloud modules; READY by branch."""
    mono = make_monorepo(tmp / 'cloud')
    with_workflow(mono, DEPLOY_WORKFLOW)
    with_workflow(mono, 'name: CI\non: [pull_request]\njobs: {}\n', 'ci.yml')
    remote = tmp / 'cloud/mono.git'
    orch_clone = tmp / 'cloud/orchestrator'
    git(tmp, 'clone', '-q', str(remote), str(orch_clone))
    out = run(orch_clone, 'init', 'demo', '--lang', 'en', '--in-repo', 'app',
              '--area', 'admin=app:apps/admin/**', '--area', 'web=app:apps/app/**').stdout
    assert 'in-repo workspace on branch orch/demo, directory docs/orchestration/demo' in out, out
    assert 'deploy.yml: runs on push to orch/demo; ignored directories: docs' in out, out
    assert git(orch_clone, 'rev-parse', '--abbrev-ref', 'HEAD').strip() == 'orch/demo'
    ws = orch_clone / 'docs/orchestration/demo'
    config = orch.parse_yaml((ws / 'orch.yaml').read_text(encoding='utf-8'))
    assert config['workspace_mode'] == 'in-repo' and config['workspace_branch'] == 'orch/demo'
    assert config['workspace_dir'] == 'docs/orchestration/demo' and config['push_after_milestone'] is True
    assert config['repos'][0]['path'] == '.' and config['repos'][0]['sessions'] == 'cloud'
    lint = run(orch_clone, 'lint')  # found from the repository root (nested discovery)
    assert lint.returncode == 0 and 'warning' not in lint.stderr, lint.stderr
    run(orch_clone, 'new-wp', 'admin', 'orders')
    wp = ws / 'work-packages/WP-ADMIN-01-orders.md'
    text = wp.read_text(encoding='utf-8')
    rel = 'docs/orchestration/demo/work-packages/WP-ADMIN-01-orders.md'
    assert f'git fetch origin orch/demo && git show origin/orch/demo:{rel}' in text, text
    assert 'claude -w' not in text and 'mcp__github__merge_pull_request' in text
    assert 'No message back is needed' in text and 'feature/wp-admin-01-orders' in text
    assert 'commit:' in run(orch_clone, 'commit', 'demo: workspace and first package').stdout
    assert git(orch_clone, 'ls-remote', '--heads', 'origin', 'orch/demo').strip(), 'state pushed to orch/demo'
    assert not git(remote, 'log', '--oneline', 'main', '--', 'docs/orchestration').strip(), 'base untouched'
    # A module cloud session reads the package from the workspace branch, as the prompt says.
    module_clone = tmp / 'cloud/module'
    git(tmp, 'clone', '-q', str(remote), str(module_clone))
    git(module_clone, 'fetch', '-q', 'origin', 'orch/demo')
    assert '# WP-ADMIN-01' in git(module_clone, 'show', f'origin/orch/demo:{rel}')
    run(orch_clone, 'set', 'WP-ADMIN-01', 'status', 'READY')
    prompt = run(orch_clone, 'dispatch', 'WP-ADMIN-01').stdout
    assert prompt.startswith(f'Cloud session for work package WP-ADMIN-01 in repository {remote.resolve()},'), prompt
    assert f'{rel} . Do section 0' in prompt, prompt
    assert '---' not in prompt, 'in-repo workspace: the prompt points to the branch, no inline text'
    assert 'no pushed branch' in run(orch_clone, 'ready').stdout
    git(module_clone, 'switch', '-q', '-c', 'feature/wp-admin-01-orders', 'origin/main')
    (module_clone / 'apps/admin/src/page.tsx').write_text('export const Admin = () => 1;\n', encoding='utf-8')
    git(module_clone, 'commit', '-qam', 'WP-ADMIN-01: orders')
    git(module_clone, 'push', '-q', 'origin', 'feature/wp-admin-01-orders')
    ready = run(orch_clone, 'ready').stdout
    assert 'WP-ADMIN-01: branch feature/wp-admin-01-orders pushed at' in ready, ready
    # State commits never go to another branch, and never to the base.
    run(orch_clone, 'journal', 'READY found by branch')
    git(orch_clone, 'switch', '-q', '-c', 'orch/side')
    assert 'commits go only to orch/demo' in run(orch_clone, 'commit', 'x', ok=False).stderr
    saved = tmp / 'cloud/saved-ws'
    shutil.copytree(ws, saved, ignore=shutil.ignore_patterns('.orch-backup'))
    git(orch_clone, 'stash', '-q', '-u')
    git(orch_clone, 'switch', '-q', 'main')
    shutil.copytree(saved, ws, dirs_exist_ok=True)  # ignored .orch-backup survives the switch
    refused = run(orch_clone, 'commit', 'on base', ok=False).stderr
    assert 'nothing committed' in refused, refused
    # A separate-mode workspace with a cloud module appends the package text to the prompt.
    home = tmp / 'cloud/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'sep', '--lang', 'en', '--repo', f'app={mono}', '--area', 'admin=app:apps/admin/**')
    sep_config = home / 'features/sep/orch.yaml'
    safe_edit.replace_once(sep_config, '    checks: []\n', '    checks: []\n    sessions: cloud\n')
    run(home, 'new-wp', 'admin', 'list')
    sep_text = (home / 'features/sep/work-packages/WP-ADMIN-01-list.md').read_text(encoding='utf-8')
    assert 'The package text follows this prompt.' in sep_text
    run(home, 'set', 'WP-ADMIN-01', 'status', 'READY')
    inline = run(home, 'dispatch', 'WP-ADMIN-01').stdout
    assert inline.startswith('Cloud session for work package WP-ADMIN-01') and '\n---\n# WP-ADMIN-01' in inline
    print('PASS cloud in-repo: init on orch/ under paths-ignore, cloud prompt, push to orch/, READY by branch, base refused')


def test_cloud_deploy_scan(tmp):
    """Deploy check reads the pushed ref, refuses unknown forms and hidden or unsafe directories."""
    import streams
    mono = make_monorepo(tmp / 'scan')
    with_workflow(mono, 'name: Deploy\non:\n  push:\njobs: {}\n')
    clone = tmp / 'scan/clone'
    git(tmp, 'clone', '-q', str(tmp / 'scan/mono.git'), str(clone))
    refused = run(clone, 'init', 'x', '--lang', 'en', '--in-repo', 'app', ok=False).stderr
    assert 'no non-hidden directory is ignored by every push workflow' in refused, refused
    assert git(clone, 'rev-parse', '--abbrev-ref', 'HEAD').strip() == 'main', 'refusal must not switch branches'
    # H2: the working tree is not what gets pushed; deleting workflows locally changes nothing.
    shutil.rmtree(clone / '.github')
    refused = run(clone, 'init', 'x', '--lang', 'en', '--in-repo', 'app', ok=False).stderr
    assert 'ignored by every push workflow' in refused, 'judged from origin/main, not the working tree'
    git(clone, 'checkout', '-q', '--', '.github')

    def verdict(text, name='deploy.yml', extra=None):
        wf = clone / '.github/workflows'
        for f in wf.glob('*'):
            f.unlink()
        (wf / name).write_text(text, encoding='utf-8')
        for other, body in (extra or {}).items():
            (wf / other).write_text(body, encoding='utf-8')
        git(clone, 'add', '-A')
        git(clone, 'commit', '-qm', 'variant', '--allow-empty')
        return streams.deploy_safe_dirs(clone, 'orch/x', 'x', 'HEAD')

    safe, notes, refusals, any_dir = verdict('on:\n  push:\n    branches: [main, "release/**"]\njobs: {}\n')
    assert any_dir and not refusals and 'branches filter' in notes[0], notes
    safe, notes, refusals, any_dir = verdict("on:\n  push:\n    branches-ignore: ['orch/**']\njobs: {}\n")
    assert any_dir and 'branches-ignore' in notes[0], notes
    assert verdict('on: [push]\njobs: {}\n')[0] == []
    safe, _, refusals, any_dir = verdict(
        "on:\n  push:\n    paths-ignore: ['.tl/**', '.claude/**', docs/**, 'notes/**']\njobs: {}\n",
        extra={'other.yml': 'on:\n  push:\n    paths-ignore:\n      - notes/**\n      - docs/**\n      - .tl/**\n'})
    assert safe == ['docs/orchestration/x', 'notes/orchestration/x'] and not any_dir, safe  # docs first, no hidden
    safe, _, _, _ = verdict("on:\n  push:\n    paths-ignore: ['.tl/**', 'notes/**']\njobs: {}\n")
    assert safe == ['notes/orchestration/x']
    assert streams.dir_is_safe('notes/orch/x', safe) and not streams.dir_is_safe('.tl/x', safe)
    # H3: every unknown form is a refusal, never "safe".
    unknown = {
        'block list on': 'on:\n  - push\n',
        'quoted key': 'on:\n  "push":\n    branches: [main]\n',
        'multi-line flow': "on:\n  push:\n    branches: [\n      '**'\n    ]\n",
        'alias': "x: &all ['**']\non:\n  push:\n    branches: *all\n",
        'scalar branches': "on:\n  push:\n    branches: '**'\n",
        'character class': "on:\n  push:\n    branches: ['[oO]rch/**']\n",
        'negation': "on:\n  push:\n    paths-ignore: ['!docs/keep/**', 'docs/**']\n",
        'positive paths': "on:\n  push:\n    paths: ['src/**']\n",
        'no on key': 'name: x\njobs: {}\n',
    }
    for label, text in unknown.items():
        safe, _, refusals, _ = verdict(text)
        assert refusals and not safe, (label, refusals)
    git(clone, 'push', '-q', 'origin', 'HEAD:main')  # origin/main now has the negation-free "no on key" form
    refused = run(clone, 'init', 'x', '--lang', 'en', '--in-repo', 'app', ok=False).stderr
    assert 'cannot tell' in refused and '--deploy-override D-n' in refused, refused
    assert run(clone, 'init', 'x', '--lang', 'en', '--in-repo', 'app', '--deploy-override', 'owner',
               ok=False).returncode == 1
    out = run(clone, 'init', 'x', '--lang', 'en', '--in-repo', 'app', '--dir', 'notes/orch-x',
              '--deploy-override', 'D-1').stdout
    assert 'overridden by owner decision D-1' in out, out
    ws = clone / 'notes/orch-x'
    assert 'deploy_check_override: D-1' in (ws / 'orch.yaml').read_text(encoding='utf-8')
    assert 'deploy check overridden by D-1' in (ws / 'status.md').read_text(encoding='utf-8')
    # M2: an unsafe --dir without a decision is refused (origin/main: paths-ignore notes/** only).
    mono2 = make_monorepo(tmp / 'scan2')
    with_workflow(mono2, "on:\n  push:\n    paths-ignore: ['notes/**']\njobs: {}\n")
    clone2 = tmp / 'scan2/clone'
    git(tmp, 'clone', '-q', str(tmp / 'scan2/mono.git'), str(clone2))
    refused = run(clone2, 'init', 'y', '--lang', 'en', '--in-repo', 'app', ok=False).stderr
    assert 'no docs/ directory is ignored' in refused and 'notes/orchestration/y' in refused, refused
    refused = run(clone2, 'init', 'y', '--lang', 'en', '--in-repo', 'app', '--dir', 'src/orch', ok=False).stderr
    assert 'not a non-hidden directory that every push workflow ignores' in refused, refused
    assert run(clone2, 'init', 'y', '--lang', 'en', '--in-repo', 'app', '--dir', 'notes/orchestration/y').returncode == 0
    tracking = subprocess.run(['git', 'config', '--get', 'branch.orch/y.merge'], cwd=clone2,
                              capture_output=True, text=True)
    assert tracking.returncode != 0, 'orch/ must not track the base'
    # M5: repository names from GitHub URLs and the cloud git proxy.
    assert streams.normalize_url('https://github.com/Owner/Repo.git') == 'github.com/owner/repo'
    assert streams.normalize_url('git@github.com:Owner/Repo.git') == 'github.com/owner/repo'
    assert streams.normalize_url('http://local_proxy@127.0.0.1:43123/git/Owner/Repo') == '127.0.0.1/owner/repo'
    git(clone2, 'remote', 'set-url', 'origin', 'http://local_proxy@127.0.0.1:43123/git/Owner/Repo')
    assert streams.origin_name(streams.Repo({'id': 'r', 'path': str(clone2)})) == 'owner/repo'
    git(clone2, 'remote', 'set-url', 'origin', 'https://github.com/Owner/Repo')
    assert streams.origin_name(streams.Repo({'id': 'r', 'path': str(clone2)})) == 'owner/repo'
    print('PASS deploy check: pushed ref, unknown forms refused, hidden dirs skipped, docs first, D-n override, URLs')


def test_cloud_dispatch_safety(tmp):
    """H4 dry-run writes nothing, M4 package must be on origin first, M3 stand slot, L1, L4."""
    mono = make_monorepo(tmp / 'safety')
    with_workflow(mono, DEPLOY_WORKFLOW)
    remote = tmp / 'safety/mono.git'
    orch_clone = tmp / 'safety/orch'
    git(tmp, 'clone', '-q', str(remote), str(orch_clone))
    run(orch_clone, 'init', 'demo', '--lang', 'en', '--in-repo', 'app', '--area', 'admin=app:apps/admin/**')
    ws = orch_clone / 'docs/orchestration/demo'
    config = ws / 'orch.yaml'
    safe_edit.replace_once(config, '    resources: []', '    resources: [staging]\n    push_deploys: true')
    run(orch_clone, 'new-wp', 'admin', 'orders')
    wp_text = (ws / 'work-packages/WP-ADMIN-01-orders.md').read_text(encoding='utf-8')
    assert 'this package holds the stand slot while it runs: push only once' in wp_text
    run(orch_clone, 'set', 'WP-ADMIN-01', 'status', 'READY')
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    refused = run(orch_clone, 'dispatch', 'WP-ADMIN-01', '--dry-run', ok=False).stderr
    assert 'is not on origin/orch/demo yet' in refused, refused  # M4
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    assert before == after, 'dry-run must write nothing'
    run(orch_clone, 'commit', 'demo: package')
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    assert 'ok (dry run); locks to take: staging' in run(orch_clone, 'dispatch', 'WP-ADMIN-01', '--dry-run').stdout
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    assert before == after, 'dry-run of a cloud module must write nothing (H4)'
    prompt = run(orch_clone, 'dispatch', 'WP-ADMIN-01').stdout
    assert 'push only once' in prompt, prompt
    held = json.loads(run(orch_clone, 'lock', 'list', '--json').stdout)
    assert [(l['lock'], l['holder']) for l in held] == [('app:staging', 'WP-ADMIN-01')], held
    # L1: a fresh clone finds the existing orch/demo on origin and refuses a second workspace.
    second = tmp / 'safety/second'
    git(tmp, 'clone', '-q', str(remote), str(second))
    run(orch_clone, 'commit', 'demo: dispatched')
    refused = run(second, 'init', 'demo', '--lang', 'en', '--in-repo', 'app', ok=False).stderr
    assert 'already exists' in refused and 'resume' in refused, refused
    # L4: detached HEAD is refused before anything is committed.
    head = git(orch_clone, 'rev-parse', 'HEAD').strip()
    git(orch_clone, 'checkout', '-q', '--detach')
    run(orch_clone, 'journal', 'detached test')
    assert 'detached HEAD' in run(orch_clone, 'commit', 'x', ok=False).stderr
    assert git(orch_clone, 'rev-parse', 'HEAD').strip() == head
    print('PASS cloud dispatch safety: dry-run read-only, package on origin first, stand slot, existing branch, detached')


def test_review(tmp):
    """2b: automatic review findings on the demo monorepo, report skeleton, disposable clone."""
    mono = make_monorepo(tmp / 'review')
    home = tmp / 'review/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'rv', '--lang', 'en', '--repo', f'mono={mono}',
        '--area', 'admin=mono:apps/admin/**', '--area', 'app=mono:apps/app/**')
    ws = home / 'features/rv'
    config = ws / 'orch.yaml'
    for old, new in (('    shared_paths: []', '    shared_paths: [pnpm-lock.yaml, "backend/migrations/**"]'),
                     ('    resources: []', '    resources: [migrations]'),
                     ('    checks: []', '    checks: ["test -n \\"$ORCH_BRANCHES\\""]\n'
                                      '    review_setup: ["cp \\"$ORCH_MAIN_CHECKOUT/config.yaml\\" copied.yaml"]')):
        safe_edit.replace_once(config, old, new)
    safe_edit.replace_once(config, '    paths: ["apps/app/**"]\n',
                           '    paths: ["apps/app/**"]\n    tests: {scoped: ["test -f apps/app/src/page.tsx"], '
                           'full: ["grep -q change apps/app/src/page.tsx"]}\n')
    run(home, 'new-wp', 'app', 'checkout')
    wp = ws / 'work-packages/WP-APP-01-checkout.md'
    fill_header(wp, 'Shared paths touched', '`pnpm-lock.yaml`')
    run(home, 'set', 'WP-APP-01', 'status', 'READY')
    run(home, 'dispatch', 'WP-APP-01')
    run(home, 'lock', 'release', 'pnpm-lock.yaml', '--wp', 'WP-APP-01')  # the branch will change it unlocked
    wt = branch_with(mono, 'feature/wp-app-01-checkout',
                     ['apps/app/src/page.tsx', 'apps/admin/src/page.tsx', 'pnpm-lock.yaml',
                      'backend/migrations/0002_orders.sql'])
    git(wt, 'push', '-q', 'origin', 'feature/wp-app-01-checkout')
    # The base moves on and changes one of the branch's files: a stale merge-base.
    (mono / 'apps/app/src/page.tsx').write_text('export const App = () => 2;\n', encoding='utf-8')
    git(mono, 'commit', '-qam', 'base moves on')
    git(mono, 'push', '-q', 'origin', 'main')
    out = run(home, 'review-start', 'WP-APP-01', '--pr', 'https://example.invalid/pull/5', '--json').stdout
    result = json.loads(out)
    found = [f['finding'] for f in result['findings']]
    assert 'WP-APP-01: apps/admin/src/page.tsx is outside the allowed paths' in found, found
    assert 'WP-APP-01: shared path pnpm-lock.yaml changed without the lock' in found, found
    assert 'WP-APP-01: shared path backend/migrations/0002_orders.sql changed but not declared' in found
    stale = [f for f in found if 'commits behind origin/main' in f]
    assert stale and 'apps/app/src/page.tsx' in stale[0] and 'rebase' in stale[0], found
    assert not any(f.startswith('mono:') for f in found), 'passing repository check is not a finding'
    report = Path(result['report'])
    text = report.read_text(encoding='utf-8')
    assert report.name.startswith('wp-app-01-review-') and 'https://example.invalid/pull/5' in text
    assert 'outside the allowed paths' in text and '{{' not in text
    rows = orch.Workspace(ws).wp_rows()
    assert rows['WP-APP-01']['status'] == 'REVIEW' and rows['WP-APP-01']['pr'] == 'https://example.invalid/pull/5'
    assert "--test 'test -f apps/app/src/page.tsx'" in result['clone_command'], result['clone_command']
    assert result['clone_command'].startswith(f'ORCH_MAIN_CHECKOUT={mono} bash ')
    assert 'copied.yaml' in result['clone_command'] and 'pnpm install' not in result['clone_command']
    assert result['base'].startswith('main @ ') and 'main @ ' in text
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    # The review command runs the clone exactly as printed (review_setup with ORCH_MAIN_CHECKOUT).
    printed = subprocess.run(['bash', '-c', result['clone_command'].replace("'test -f apps/app/src/page.tsx'",
                                                                            "'test -f copied.yaml'", 1)],
                             capture_output=True, text=True)
    assert 'setup: cp' in printed.stdout and 'test: test -f copied.yaml -> exit 0' in printed.stdout, printed.stdout
    # M2: an unpushed local commit on the branch is not reviewed; the default is origin/<branch>.
    (wt / 'apps/app/src/local.tsx').write_text('local only\n', encoding='utf-8')
    git(wt, 'add', '-A')
    git(wt, 'commit', '-qm', 'not pushed')
    local = json.loads(run(home, 'review-start', 'WP-APP-01', '--round', '9', '--json').stdout)
    assert local['sha'] == result['sha'] and 'differs from origin/feature/wp-app-01-checkout' in local['warnings'][0]
    git(wt, 'reset', '-q', '--hard', 'HEAD~1')
    # L2: a failing fetch stops the review unless --no-fetch.
    git(mono, 'remote', 'set-url', 'origin', str(tmp / 'review/missing.git'))
    assert 'git fetch origin failed' in run(home, 'review-start', 'WP-APP-01', '--round', '8', ok=False).stderr
    assert run(home, 'review-start', 'WP-APP-01', '--round', '8', '--no-fetch').returncode == 0
    git(mono, 'remote', 'set-url', 'origin', str(tmp / 'review/mono.git'))
    # Resubmission: the revision diff command, a second report without clobbering the first.
    old_sha = result['sha']
    (wt / 'apps/app/src/page.tsx').write_text('fixed\n', encoding='utf-8')
    git(wt, 'commit', '-qam', 'resubmission 1')
    git(wt, 'push', '-q', 'origin', 'feature/wp-app-01-checkout')
    run(home, 'review-start', 'WP-APP-01', ok=False)  # same-day report exists: needs --round
    second = json.loads(run(home, 'review-start', 'WP-APP-01', '--since', old_sha, '--round', '2',
                            '--json').stdout)
    assert second['report'].endswith('-r2.md') and f'diff {old_sha}' in second['revision_diff']
    # L1: after a rebase the revision diff is a range-diff over base..old and base..new.
    git(wt, 'fetch', '-q', 'origin')
    git(wt, 'rebase', '-q', '-X', 'theirs', 'origin/main')
    git(wt, 'push', '-q', '-f', 'origin', 'feature/wp-app-01-checkout')
    third = json.loads(run(home, 'review-start', 'WP-APP-01', '--since', second['sha'], '--round', '3',
                           '--json').stdout)
    command = third['revision_diff']
    assert f'range-diff origin/main..{second["sha"]} origin/main..{third["sha"]}' in command, command
    rd = subprocess.run(command.split()[:1] + command.split()[1:], capture_output=True, text=True)
    assert rd.returncode == 0 and 'resubmission 1' in rd.stdout, rd.stdout
    assert 'base moves on' not in rd.stdout, 'base commits must not show up in the revision diff'
    sym = subprocess.run(command.replace('..', '...').split(), capture_output=True, text=True)
    assert 'base moves on' in sym.stdout, 'control: the symmetric form would show the base commit'
    # The disposable clone: tests pass at the new head, fail at the old one, cleanup is guarded.
    clone = [sys.executable, '-c', 'import sys, subprocess; sys.exit(subprocess.call(sys.argv[1:]))',
             'bash', str(HERE / 'review_clone.sh'), '--repo', str(tmp / 'review/mono.git')]
    ok = subprocess.run(clone + ['--sha', second['sha'], '--test', 'test -f apps/app/src/page.tsx',
                                 '--test', 'grep -q fixed apps/app/src/page.tsx'], capture_output=True, text=True)
    assert ok.returncode == 0 and 'test: grep -q fixed apps/app/src/page.tsx -> exit 0' in ok.stdout, ok.stdout
    bad = subprocess.run(clone + ['--sha', old_sha, '--test', 'grep -q fixed apps/app/src/page.tsx'],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and '-> exit 1' in bad.stdout, bad.stdout
    kept = subprocess.run(clone + ['--sha', old_sha, '--keep'], capture_output=True, text=True)
    kept_dir = kept.stdout.split('--cleanup ')[1].split('\n')[0].strip()
    assert Path(kept_dir, 'repo/apps/app/src/page.tsx').is_file()
    refused = subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--cleanup', str(tmp)], capture_output=True,
                             text=True)
    assert refused.returncode == 2 and Path(tmp).is_dir(), 'cleanup only removes marked clone directories'
    subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--cleanup', kept_dir], check=True, capture_output=True)
    assert not Path(kept_dir).exists()
    missing = subprocess.run(clone + ['--sha', 'deadbeef'], capture_output=True, text=True)
    assert missing.returncode == 2
    dangling = subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--repo', 'x', '--sha'], capture_output=True,
                              text=True, timeout=10)
    assert dangling.returncode == 2 and 'needs a value' in dangling.stderr
    print('PASS review: automatic findings (outside paths, unlocked/undeclared shared, stale merge-base), '
          'report, rounds, disposable clone')


def test_close(tmp):
    """2d: completion check, carry to backlog, closeout, archive, refusals, reopen, discovery."""
    mono = make_monorepo(tmp / 'close')
    home = tmp / 'close/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'goal', '--lang', 'en', '--title', 'One goal', '--module', f'core={mono}')
    ws = home / 'features/goal'
    plan = ws / 'PLAN.md'
    text = plan.read_text(encoding='utf-8')
    assert '## Goal and completion condition' in text and 'Completion condition:' in text
    goal_block = text[text.index('<The one goal'):text.index('## Scope')].rstrip()
    safe_edit.replace_once(plan, goal_block, 'Ship orders export.\n\nCompletion condition: WP-CORE-01 DONE.')
    run(home, 'new-wp', 'core', 'export')
    run(home, 'new-wp', 'core', 'import')
    run(home, 'decide', 'D', 'CSV only')
    run(home, 'owner', 'add', 'R', 'Rotate the export token : see vault ; expected: rotated')
    assert 'WP-CORE-01 is DRAFT' in run(home, 'close', '--check', ok=False).stderr
    run(home, 'set', 'WP-CORE-01', 'status', 'DONE', '--evidence', 'verified on PROD')
    run(home, 'set', 'WP-CORE-02', 'status', 'CANCELLED (superseded by D-1)')
    # A package branch still on origin: PRs cannot be listed here without gh -> blocker.
    git(mono, 'switch', '-q', '-c', 'goal/wp-core-01-export')
    git(mono, 'push', '-q', 'origin', 'goal/wp-core-01-export')
    git(mono, 'switch', '-q', 'main')
    blocked = run(home, 'close', '--check', ok=False).stderr
    assert 'R-1 is open' in blocked and 'owner carry R-1' in blocked, blocked
    assert 'goal/wp-core-01-export is still on origin' in blocked, blocked
    run(home, 'owner', 'carry', 'R-1', 'token rotation belongs to the next program')
    backlog = (ws / 'backlog.md').read_text(encoding='utf-8')
    assert '| B-1 |' in backlog and 'Rotate the export token' in backlog and '| R-1 |' in backlog
    assert 'carried to backlog.md' in (ws / 'status.md').read_text(encoding='utf-8')
    check = run(home, 'close', '--check', '--prs-verified', 'owner: PR merged and closed')
    assert 'no blockers' in check.stdout and 'module sessions to close: goal-core' in check.stdout, check.stdout
    assert run(home, 'dispatch', 'WP-CORE-01', '--dry-run', ok=False).returncode == 1  # still open, but not READY
    out = run(home, 'close', '--apply', '--prs-verified', 'owner: PR merged and closed',
              '--summary', 'Export shipped; import cancelled by D-1.').stdout
    archived = (home / 'features/_archive/goal').resolve()
    printed = {l.split(': ', 1)[0]: Path(l.split(': ', 1)[1]).resolve() for l in out.splitlines()
               if l.startswith(('archived: ', 'closeout: '))}
    assert printed.get('archived') == archived and printed['closeout'].parent == archived / 'reports', out
    assert not ws.exists() and (archived / 'orch.yaml').is_file()
    report = next((archived / 'reports').glob('closeout-*.md')).read_text(encoding='utf-8')
    for expected in ('Ship orders export.', 'Completion condition: WP-CORE-01 DONE.', 'Export shipped',
                     '| WP-CORE-01 | core |', 'D-1', 'B-1: Rotate the export token', 'goal-core'):
        assert expected in report, (expected, report)
    config = orch.parse_yaml((archived / 'orch.yaml').read_text(encoding='utf-8'))
    assert config['state'] == 'closed'
    assert '> **Closed ' in (archived / 'status.md').read_text(encoding='utf-8')
    assert not git(home, 'status', '--porcelain').strip(), 'closeout and archive are committed'
    assert 'archive workspace' in git(home, 'log', '-1', '--format=%s')
    # After closing: refusals, read-only lint, closed workspaces are not picked among several.
    wsarg = ['--workspace', str(archived)]
    for command in (['dispatch', 'WP-CORE-01'], ['new-wp', 'core', 'more'], ['lock', 'acquire', 'x', '--wp', 'WP-CORE-01'],
                    ['merge', 'add', 'WP-CORE-01']):
        refused = run(home, *wsarg, *command, ok=False).stderr
        assert 'is closed' in refused and 'new program (init)' in refused, (command, refused)
    assert run(home, *wsarg, 'lint').returncode == 0
    assert 'already closed' in run(home, *wsarg, 'close', '--check').stdout
    run(home, 'init', 'next', '--lang', 'en', '--module', f'core={mono}')
    found = subprocess.run([*ORCH, 'queue'], cwd=home, capture_output=True, text=True,
                           env={**os.environ, **GIT_ENV})
    assert found.returncode == 0, 'only the active workspace is picked automatically'
    reopened = run(home, *wsarg, 'reopen', 'import is needed after all').stdout
    assert 'reopened' in reopened and 'git mv' in reopened
    assert orch.parse_yaml((archived / 'orch.yaml').read_text(encoding='utf-8'))['state'] == 'active'
    assert 'Reopened ' in (archived / 'status.md').read_text(encoding='utf-8')
    assert run(home, *wsarg, 'new-wp', 'core', 'import-again').returncode == 0
    print('PASS close: blockers by fact, carry to backlog, closeout report, archive, refusals, reopen')


def test_close_in_repo(tmp):
    """2d in-repo: tag and branch deletion are printed to the owner, never run."""
    mono = make_monorepo(tmp / 'closecloud')
    with_workflow(mono, DEPLOY_WORKFLOW)
    remote = tmp / 'closecloud/mono.git'
    clone = tmp / 'closecloud/orch'
    git(tmp, 'clone', '-q', str(remote), str(clone))
    run(clone, 'init', 'demo', '--lang', 'en', '--in-repo', 'app', '--area', 'admin=app:apps/admin/**')
    run(clone, 'new-wp', 'admin', 'orders')
    run(clone, 'set', 'WP-ADMIN-01', 'status', 'DONE', '--evidence', 'verified')
    run(clone, 'commit', 'demo: done')
    out = run(clone, 'close', '--apply', '--summary', 'Goal reached.').stdout
    assert 'closeout:' in out and 'archived' not in out, out
    status = (clone / 'docs/orchestration/demo/status.md').read_text(encoding='utf-8')
    assert 'push origin --delete orch/demo' in status and 'tag orch-demo-closed-' in status, status
    assert 'Keep the workspace as history in docs/' in status
    assert not git(remote, 'tag', '-l').strip(), 'the plugin never creates tags'
    assert git(remote, 'branch', '--list', 'orch/demo').strip(), 'the plugin never deletes branches'
    assert 'state: closed' in git(remote, 'show', 'orch/demo:docs/orchestration/demo/orch.yaml')
    assert not git(remote, 'log', '--oneline', 'main', '--', 'docs').strip(), 'nothing on the base'
    print('PASS close in-repo: archive commands printed for the owner, not run; closeout pushed to orch/')

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
        test_p4_identity(tmp)
        test_streams_edges(tmp)
        test_legacy_shared_path(tmp)
        test_cloud_in_repo(tmp)
        test_cloud_deploy_scan(tmp)
        test_cloud_dispatch_safety(tmp)
        test_review(tmp)
        test_close(tmp)
        test_close_in_repo(tmp)
    print('PASS pepper-orchestrator selftest')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
