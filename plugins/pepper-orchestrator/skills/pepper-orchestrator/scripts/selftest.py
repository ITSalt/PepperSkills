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
    'ORCH_NO_GH': '1',  # no network: gh paths are not exercised by the offline self-test
    'ORCH_NO_CLAUDE': '1',  # plugin reports do not start the claude CLI for its version
}


def run(cwd, *args, ok=True, extra_env=None):
    env = {**os.environ, **GIT_ENV, 'PYTHONDONTWRITEBYTECODE': '1', **(extra_env or {})}
    env.pop('ORCH_WORKSPACE', None)
    result = subprocess.run([*ORCH, *args], cwd=cwd, env=env, encoding='utf-8', errors='replace', capture_output=True)
    if ok and result.returncode:
        raise AssertionError(f'orch {args} failed: {result.stderr}')
    if not ok and not result.returncode:
        raise AssertionError(f'orch {args} should have failed')
    return result


def git(cwd, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(['git', *args], cwd=cwd, env=env, encoding='utf-8', errors='replace', capture_output=True,
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
                          '--old', 'gamma', '--new', 'delta'], capture_output=True, encoding='utf-8', errors='replace')
    assert cli.returncode == 0 and target.read_text(encoding='utf-8').startswith('delta')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target),
                          '--old', 'beta', '--new', 'x'], capture_output=True, encoding='utf-8', errors='replace')
    assert cli.returncode == 1 and 'found 2' in cli.stderr
    print('PASS safe_edit: single match, backup, refusal, create-only, CLI')


SAMPLE_YAML = '''\
program: example-program         # prefix
title: "Example program: part B"
tag: EXAMPLE
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
    assert parsed['title'] == 'Example program: part B'
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
    run(repo, 'init', 'demo', '--lang', lang, '--sessions', 'local', '--permission-mode', 'auto', '--title', 'Demo: "quoted" | program',
        '--module', 'db=~/projects/demo-db', '--module', 'web=~/projects/demo-web@develop')
    ws = repo / 'features/demo'
    config = orch.parse_yaml((ws / 'orch.yaml').read_text(encoding='utf-8'))
    assert config['title'] == 'Demo: "quoted" | program' and config['tag'] == 'DEMO'
    assert [m['base'] for m in config['modules']] == ['main', 'develop']
    run(repo, 'init', 'demo', '--lang', lang, '--sessions', 'local', '--permission-mode', 'auto', ok=False)  # never over an existing workspace
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
    run(repo, 'set', 'WP-WEB-01', 'title', 'Orders page | draft')
    run(repo, 'set', 'WP-WEB-01', 'pr', 'https://example.com/pull/7')
    run(repo, 'set', 'WP-WEB-01', 'pr', 'draft PR', ok=False)  # 0.9.1: only a URL or a number
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
    assert 'Orders page \\| draft' in status and '| https://example.com/pull/7 |' in status
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
    run(repo, 'init', 'one', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto')
    assert run(repo, 'queue').returncode == 0  # single features/*/orch.yaml is found
    run(repo, 'init', 'two', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto')
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
                         input=block, capture_output=True, encoding='utf-8', errors='replace')
    assert cli.returncode == 0, cli.stderr
    assert target.read_text(encoding='utf-8') == 'alpha\ngamma\ndelta\n'
    two = ('<<<<<<< OLD\nalpha\n=======\nALPHA\n>>>>>>> NEW\n'
           '<<<<<<< OLD\ndelta\n=======\nDELTA\n>>>>>>> NEW\n')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input=two, capture_output=True, encoding='utf-8', errors='replace')
    assert cli.returncode == 0, cli.stderr
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n'
    atomic = ('<<<<<<< OLD\nALPHA\n=======\nx\n>>>>>>> NEW\n'
              '<<<<<<< OLD\nmissing\n=======\ny\n>>>>>>> NEW\n')
    cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input=atomic, capture_output=True, encoding='utf-8', errors='replace')
    assert cli.returncode == 1 and 'block 2' in cli.stderr
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n', 'partial multi-block edit'
    for broken in ('<<<<<<< OLD\nALPHA\n=======\n<<<<<<< OLD\n>>>>>>> NEW\n',
                   '<<<<<<< OLD\nALPHA\n=======\nx\n', 'stray\n<<<<<<< OLD\nALPHA\n=======\nx\n>>>>>>> NEW\n'):
        cli = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                             input=broken, capture_output=True, encoding='utf-8', errors='replace')
        assert cli.returncode == 1, broken
    assert target.read_text(encoding='utf-8') == 'ALPHA\ngamma\nDELTA\n'
    target.write_text('alpha\ngamma\ndelta\n', encoding='utf-8')
    bad = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target), '--stdin'],
                         input='no markers', capture_output=True, encoding='utf-8', errors='replace')
    assert bad.returncode == 1 and 'OLD' in bad.stderr
    created = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(tmp / 'c.md'),
                              '--create', '--stdin'], input='new file\n', capture_output=True, encoding='utf-8', errors='replace')
    assert created.returncode == 0 and (tmp / 'c.md').read_text(encoding='utf-8') == 'new file\n'
    blocker = tmp / 'not-a-dir'
    blocker.write_text('x\n', encoding='utf-8')
    env = {**os.environ, 'ORCH_BACKUP_DIR': str(blocker / 'sub')}
    fallback = subprocess.run([sys.executable, str(HERE / 'safe_edit.py'), str(target),
                               '--old', 'alpha', '--new', 'omega'], env=env, capture_output=True, encoding='utf-8', errors='replace')
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
    legacy_lint = run(home, 'lint')
    assert legacy_lint.returncode == 0 and 'no permission_mode' in legacy_lint.stderr, legacy_lint.stderr
    assert 'P-1' not in run(home, 'queue').stdout and 'R-1' in run(home, 'queue').stdout
    assert 'overlap: none' in run(home, 'overlap', '--planned').stdout
    assert run(home, 'worktrees').returncode == 0
    refused = run(home, 'dispatch', 'WP-API-01', '--dry-run', ok=False).stderr
    assert 'orch.py settings api' in refused and '--no-settings' in refused, refused
    assert 'dry run' in run(home, 'dispatch', 'WP-API-01', '--dry-run', '--no-settings').stdout
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file()}
    assert before == after, 'read-only commands changed a 0.1.0 workspace'
    run(home, 'new-wp', 'api', 'orders-import', '--title', 'Orders import')
    text = (ws / 'work-packages/WP-API-02-orders-import.md').read_text(encoding='utf-8')
    assert 'legacy/wp-api-02-orders-import' in text and 'cd ~/projects/example-api && claude --name' in text
    assert '-w ' not in text and '{{' not in text, 'old template must keep the 0.1.0 form'
    assert 'No `--settings` in this version' not in text and '`orch.py dispatch` adds `--permission-mode`' in text
    assert 'predates 0.6.0' in run(home, 'lint').stderr
    run(home, 'set', 'WP-API-02', 'status', 'READY')
    command = run(home, 'dispatch', 'WP-API-01', '--no-settings').stdout
    assert command.startswith('cd ~/projects/example-api && claude --name legacy-api "'), command
    assert 'dispatch refused' in run(home, 'dispatch', 'WP-API-02', '--no-settings', ok=False).stderr  # same repo
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
    refused = run(mono, 'init', 'inside', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}', ok=False)
    assert 'module repository' in refused.stderr, 'P4: workspace in a module checkout must be refused'
    run(home, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}',
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
    run(home, 'settings', 'all')
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
    settings = (ws / 'orchestration/settings/app.json').resolve()
    assert out.startswith(f'cd {mono} && claude -w wp-app-01-checkout --permission-mode auto --settings {settings} '
                          '--name shop-app "'), out
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
    assert run(wt_ok, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}').returncode == 0
    wt_base = tmp / 'p4/wt-base'
    git(mono, 'switch', '-q', '-c', 'side')  # free main for a linked worktree
    git(mono, 'worktree', 'add', '-q', str(wt_base), 'main')
    refused = run(wt_base, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}', ok=False)
    assert 'linked worktree of module repository' in refused.stderr, refused.stderr
    clone = tmp / 'p4/clone'
    git(tmp, 'clone', '-q', str(tmp / 'p4/mono.git'), str(clone))
    refused = run(clone, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}', ok=False)
    assert 'checkout or clone of module repository' in refused.stderr, refused.stderr
    # commit is refused the same way when a workspace was copied onto a base worktree.
    shutil.copytree(wt_ok / 'features/shop', wt_base / 'features/shop',
                    ignore=shutil.ignore_patterns('.orch-backup'))
    assert 'linked worktree' in run(wt_base, 'commit', 'x', ok=False).stderr
    # L7: orch/ in the main checkout while a whole-repository module works there: warning.
    solo = make_monorepo(tmp / 'p4solo')
    git(solo, 'switch', '-q', '-c', 'orch/solo')
    out = run(solo, 'init', 'solo', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'core={solo}')
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
    run(home, 'init', 'edge', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}',
        '--area', 'web=mono:apps/{admin,app}/**', '--domain', 'admin-ui=mono:backend/src/billing/**')
    ws = home / 'features/edge'
    config = ws / 'orch.yaml'
    assert 'paths: ["apps/{admin,app}/**"]' in config.read_text(encoding='utf-8'), 'braces kept by init'
    assert run(home, 'init', 'bad', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}',
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
    run(home, 'init', 'two', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', 'api=~/projects/example-api',
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
    out = run(orch_clone, 'init', 'demo', '--lang', 'en', '--sessions', 'cloud', '--permission-mode', 'auto', '--cloud-environment', 'Project env', '--in-repo', 'app', '--cloud-env', 'Project env',
              '--area', 'admin=app:apps/admin/**', '--area', 'web=app:apps/app/**').stdout
    assert 'in-repo workspace on branch orch/demo, directory docs/orchestration/demo' in out, out
    assert 'deploy.yml: runs on push to orch/demo; ignored directories: docs' in out, out
    assert git(orch_clone, 'rev-parse', '--abbrev-ref', 'HEAD').strip() == 'orch/demo'
    ws = orch_clone / 'docs/orchestration/demo'
    config = orch.parse_yaml((ws / 'orch.yaml').read_text(encoding='utf-8'))
    assert config['workspace_mode'] == 'in-repo' and config['workspace_branch'] == 'orch/demo'
    assert config['workspace_dir'] == 'docs/orchestration/demo' and config['push_after_milestone'] is True
    assert config['repos'][0]['path'] == '.' and config['sessions'] == 'cloud'
    assert config['cloud_environment'] == 'Project env'
    assert 'session kind: cloud, environment Project env, confirmed by the owner' in \
        (orch_clone / 'docs/orchestration/demo/status.md').read_text(encoding='utf-8')
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
    handover = run(orch_clone, 'dispatch', 'WP-ADMIN-01').stdout
    assert handover.startswith('New cloud session for WP-ADMIN-01:') and '- Environment: Project env' in handover
    prompt = handover.split('Prompt:\n', 1)[1]
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
    run(home, 'init', 'sep', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'app={mono}', '--area', 'admin=app:apps/admin/**')
    sep_config = home / 'features/sep/orch.yaml'
    safe_edit.replace_once(sep_config, '    checks: []\n', '    checks: []\n    sessions: cloud\n')
    run(home, 'new-wp', 'admin', 'list')
    sep_text = (home / 'features/sep/work-packages/WP-ADMIN-01-list.md').read_text(encoding='utf-8')
    assert 'The package text follows this prompt.' in sep_text
    run(home, 'set', 'WP-ADMIN-01', 'status', 'READY')
    refusal = run(home, 'dispatch', 'WP-ADMIN-01', '--dry-run', ok=False).stderr
    assert 'no cloud environment is set' in refusal and 'orch.py cloud-env' in refusal, refusal
    run(home, 'cloud-env', 'Project env')
    assert 'cloud environment Project env' in (home / 'features/sep/status.md').read_text(encoding='utf-8')
    inline = run(home, 'dispatch', 'WP-ADMIN-01').stdout.split('Prompt:\n', 1)[1]
    assert inline.startswith('Cloud session for work package WP-ADMIN-01') and '\n---\n# WP-ADMIN-01' in inline
    print('PASS cloud in-repo: init on orch/ under paths-ignore, cloud prompt, push to orch/, READY by branch, base refused')


def test_cloud_deploy_scan(tmp):
    """Deploy check reads the pushed ref, refuses unknown forms and hidden or unsafe directories."""
    import streams
    mono = make_monorepo(tmp / 'scan')
    with_workflow(mono, 'name: Deploy\non:\n  push:\njobs: {}\n')
    clone = tmp / 'scan/clone'
    git(tmp, 'clone', '-q', str(tmp / 'scan/mono.git'), str(clone))
    refused = run(clone, 'init', 'x', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', ok=False).stderr
    assert 'no non-hidden directory is ignored by every push workflow' in refused, refused
    assert git(clone, 'rev-parse', '--abbrev-ref', 'HEAD').strip() == 'main', 'refusal must not switch branches'
    # H2: the working tree is not what gets pushed; deleting workflows locally changes nothing.
    shutil.rmtree(clone / '.github')
    refused = run(clone, 'init', 'x', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', ok=False).stderr
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
    # 3a defect a: a positive `paths` filter is fine when the branch filter already excludes orch/<p>.
    safe, notes, refusals, any_dir = verdict(
        "on:\n  push:\n    branches: [main, 'release/**']\n    paths: ['src/**', 'package.json']\njobs: {}\n")
    assert any_dir and not refusals and 'branches filter' in notes[0], (refusals, notes)
    safe, notes, refusals, any_dir = verdict(
        "on:\n  push:\n    branches-ignore: ['orch/**']\n    paths:\n      - '!docs/**'\njobs: {}\n")
    assert any_dir and not refusals, refusals
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
        safe, _, refusals, any_dir = verdict(text)  # candidates only serve an owner decision (D-n)
        assert refusals and not any_dir, (label, refusals)
    git(clone, 'push', '-q', 'origin', 'HEAD:main')  # origin/main now has the negation-free "no on key" form
    refused = run(clone, 'init', 'x', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', ok=False).stderr
    assert 'cannot tell' in refused and '--deploy-override D-n' in refused, refused
    assert run(clone, 'init', 'x', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', '--deploy-override', 'owner',
               ok=False).returncode == 1
    out = run(clone, 'init', 'x', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', '--dir', 'notes/orch-x',
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
    refused = run(clone2, 'init', 'y', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', ok=False).stderr
    assert 'no docs/ directory is ignored' in refused and 'notes/orchestration/y' in refused, refused
    refused = run(clone2, 'init', 'y', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', '--dir', 'src/orch', ok=False).stderr
    assert 'not a non-hidden directory that every push workflow ignores' in refused, refused
    assert run(clone2, 'init', 'y', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app', '--dir', 'notes/orchestration/y').returncode == 0
    tracking = subprocess.run(['git', 'config', '--get', 'branch.orch/y.merge'], cwd=clone2,
                              capture_output=True, encoding='utf-8', errors='replace')
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
    run(orch_clone, 'init', 'demo', '--lang', 'en', '--sessions', 'cloud', '--permission-mode', 'auto', '--cloud-environment', 'Project env', '--in-repo', 'app', '--area', 'admin=app:apps/admin/**')
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
    refused = run(second, 'init', 'demo', '--lang', 'en', '--sessions', 'cloud', '--permission-mode', 'auto', '--cloud-environment', 'Project env', '--in-repo', 'app', ok=False).stderr
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
    run(home, 'init', 'rv', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}',
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
                             capture_output=True, encoding='utf-8', errors='replace')
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
    esc = [w for w in third['warnings'] if w.startswith('round 3:')]
    assert esc and f'cd {mono} && claude --resume rv-app --model opus' in esc[0], third['warnings']
    assert 'if the same REVISE items are still open' in esc[0], esc  # 0.9.1 (#21): conditional before reading

    def escalations():
        return [q for q in json.loads(run(home, 'queue', '--json').stdout) if 'restart the module session' in q['text']]
    assert escalations() == [], 'no owner item before the round is reviewed'
    assert 'if the same REVISE items are still open' in Path(third['report']).read_text(encoding='utf-8')
    run(home, 'set', 'WP-APP-01', 'status', 'REVISE', '--evidence', 'round 3: items 2 and 3 again')
    assert len(escalations()) == 1 and 'round 3: the same REVISE items are still open' in escalations()[0]['text']
    again = json.loads(run(home, 'review-start', 'WP-APP-01', '--since', third['sha'], '--round', '4', '--json').stdout)
    assert any(w.startswith('round 4:') for w in again['warnings']), 'the hint is printed every round'
    run(home, 'set', 'WP-APP-01', 'status', 'REVISE')
    assert len(escalations()) == 1, escalations()
    command = third['revision_diff']
    assert f'range-diff origin/main..{second["sha"]} origin/main..{third["sha"]}' in command, command
    rd = subprocess.run(command.split()[:1] + command.split()[1:], capture_output=True, encoding='utf-8', errors='replace')
    assert rd.returncode == 0 and 'resubmission 1' in rd.stdout, rd.stdout
    assert 'base moves on' not in rd.stdout, 'base commits must not show up in the revision diff'
    sym = subprocess.run(command.replace('..', '...').split(), capture_output=True, encoding='utf-8', errors='replace')
    assert 'base moves on' in sym.stdout, 'control: the symmetric form would show the base commit'
    # The disposable clone: tests pass at the new head, fail at the old one, cleanup is guarded.
    clone = [sys.executable, '-c', 'import sys, subprocess; sys.exit(subprocess.call(sys.argv[1:]))',
             'bash', str(HERE / 'review_clone.sh'), '--repo', str(tmp / 'review/mono.git')]
    ok = subprocess.run(clone + ['--sha', second['sha'], '--test', 'test -f apps/app/src/page.tsx',
                                 '--test', 'grep -q fixed apps/app/src/page.tsx'], capture_output=True, encoding='utf-8', errors='replace')
    assert ok.returncode == 0 and 'test: grep -q fixed apps/app/src/page.tsx -> exit 0' in ok.stdout, ok.stdout
    bad = subprocess.run(clone + ['--sha', old_sha, '--test', 'grep -q fixed apps/app/src/page.tsx'],
                         capture_output=True, encoding='utf-8', errors='replace')
    assert bad.returncode == 1 and '-> exit 1' in bad.stdout, bad.stdout
    kept = subprocess.run(clone + ['--sha', old_sha, '--keep'], capture_output=True, encoding='utf-8', errors='replace')
    kept_dir = kept.stdout.split('--cleanup ')[1].split('\n')[0].strip()
    assert Path(kept_dir, 'repo/apps/app/src/page.tsx').is_file()
    refused = subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--cleanup', str(tmp)], capture_output=True,
                             encoding='utf-8', errors='replace')
    assert refused.returncode == 2 and Path(tmp).is_dir(), 'cleanup only removes marked clone directories'
    subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--cleanup', kept_dir], check=True, capture_output=True)
    assert not Path(kept_dir).exists()
    missing = subprocess.run(clone + ['--sha', 'deadbeef'], capture_output=True, encoding='utf-8', errors='replace')
    assert missing.returncode == 2
    dangling = subprocess.run(['bash', str(HERE / 'review_clone.sh'), '--repo', 'x', '--sha'], capture_output=True,
                              encoding='utf-8', errors='replace', timeout=10)
    assert dangling.returncode == 2 and 'needs a value' in dangling.stderr
    print('PASS review: automatic findings (outside paths, unlocked/undeclared shared, stale merge-base), '
          'report, rounds, disposable clone')


def test_close(tmp):
    """2d: completion check by facts, carry to backlog, atomic closeout, archive, refusals, reopen."""
    mono = make_monorepo(tmp / 'close')
    home = tmp / 'close/home'
    home.mkdir()
    git(home, 'init', '-q')
    git(tmp, 'init', '-q', '--bare', str(tmp / 'close/home.git'))
    git(home, 'remote', 'add', 'origin', str(tmp / 'close/home.git'))
    run(home, 'init', 'goal', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--title', 'One goal', '--module', f'core={mono}')
    ws = home / 'features/goal'
    safe_edit.replace_once(ws / 'orch.yaml', 'push_after_milestone: false', 'push_after_milestone: true')
    plan = ws / 'PLAN.md'
    run(home, 'new-wp', 'core', 'export')
    run(home, 'new-wp', 'core', 'import')
    run(home, 'decide', 'D', 'CSV only')
    run(home, 'owner', 'add', 'R', 'Rotate the export token : see vault ; expected: rotated')
    run(home, 'set', 'WP-CORE-01', 'status', 'DONE', '--evidence', 'verified on PROD')
    run(home, 'set', 'WP-CORE-01', 'pr', 'https://example.invalid/pull/7')
    run(home, 'set', 'WP-CORE-02', 'status', 'CANCELLED (superseded by D-1)')
    # L4: an unwritten completion condition blocks closing unless the goal is confirmed explicitly.
    assert 'no filled completion condition' in run(home, 'close', '--check', ok=False).stderr
    text = plan.read_text(encoding='utf-8')
    goal_block = text[text.index('<The one goal'):text.index('## Scope')].rstrip()
    safe_edit.replace_once(plan, goal_block, 'Ship orders export.\n\nCompletion condition: WP-CORE-01 DONE.')
    git(mono, 'switch', '-q', '-c', 'goal/wp-core-01-export')
    git(mono, 'push', '-q', 'origin', 'goal/wp-core-01-export')
    git(mono, 'switch', '-q', 'main')
    blocked = run(home, 'close', '--check', ok=False).stderr
    assert 'R-1 is open' in blocked and 'owner carry R-1' in blocked, blocked
    assert 'goal/wp-core-01-export is still on origin' in blocked, blocked
    assert 'recorded PR https://example.invalid/pull/7 cannot be checked here' in blocked, blocked  # M2
    run(home, 'owner', 'carry', 'R-1', 'token rotation belongs to the next program')
    backlog = (ws / 'backlog.md').read_text(encoding='utf-8')
    assert '| B-1 |' in backlog and 'Rotate the export token' in backlog and '| R-1 |' in backlog
    # M1: evidence must be concrete.
    assert 'concrete evidence' in run(home, 'close', '--check', '--prs-verified', 'looks fine', ok=False).stderr
    evidence = 'https://example.invalid/pull/7 merged; list_pull_requests head=goal/wp-core-01-export state=open: []'
    check = run(home, 'close', '--check', '--prs-verified', evidence)
    assert 'no blockers' in check.stdout and 'module sessions to close: goal-core' in check.stdout, check.stdout
    # M4: commit conditions are checked before anything changes.
    run(home, 'commit', 'goal: ready to close')
    git(home, 'checkout', '-q', '--detach')
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    refused = run(home, 'close', '--apply', '--prs-verified', evidence, ok=False).stderr
    assert 'detached HEAD' in refused, refused
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    assert before == after and 'state: closed' not in (ws / 'orch.yaml').read_text(encoding='utf-8')
    git(home, 'switch', '-q', '-')
    # M4: a close without commit is finished by a second --apply.
    run(home, 'close', '--apply', '--prs-verified', evidence, '--no-commit', '--summary', 'Export shipped.')
    assert 'state: closed' in (ws / 'orch.yaml').read_text(encoding='utf-8') and git(home, 'status', '--porcelain')
    out = run(home, 'close', '--apply').stdout
    assert 'finishing the commit and the archive' in out, out
    archived = (home / 'features/_archive/goal').resolve()
    assert f'archived: {archived}' in out.replace(str(home), str(home.resolve())) or 'archived: ' in out, out
    assert not ws.exists() and (archived / 'orch.yaml').is_file()
    assert not git(home, 'status', '--porcelain').strip(), 'closeout and archive are committed'
    remote_log = git(tmp / 'close/home.git', 'log', '--format=%s', '-3')
    assert 'goal: archive workspace' in remote_log and 'goal: close program' in remote_log, 'L1: archive pushed'
    report = next((archived / 'reports').glob('closeout-*.md')).read_text(encoding='utf-8')
    for expected in ('Ship orders export.', 'Completion condition: WP-CORE-01 DONE.', 'Export shipped',
                     '| WP-CORE-01 | core |', '<release or merge commit>', 'D-1', 'B-1: Rotate the export token',
                     'goal-core', 'PRs without gh:', 'list_pull_requests head=goal/wp-core-01-export'):
        assert expected in report, (expected, report)
    status = (archived / 'status.md').read_text(encoding='utf-8')
    assert '> **Closed ' in status and 'PRs verified without gh' in status and evidence in status
    # After closing: refusals, read-only lint, closed workspaces are not picked among several.
    wsarg = ['--workspace', str(archived)]
    for command in (['dispatch', 'WP-CORE-01'], ['new-wp', 'core', 'more'], ['lock', 'acquire', 'x', '--wp', 'WP-CORE-01'],
                    ['merge', 'add', 'WP-CORE-01'], ['set', 'WP-CORE-01', 'pr', 'x'], ['decide', 'D', 'x'],
                    ['owner', 'add', 'R', 'x'], ['review-start', 'WP-CORE-01']):
        refused = run(home, *wsarg, *command, ok=False).stderr
        assert 'is closed' in refused and 'new program (init)' in refused, (command, refused)
    assert run(home, *wsarg, 'lint').returncode == 0
    assert 'already closed' in run(home, *wsarg, 'close', '--check').stdout
    closed_cfg = archived / 'orch.yaml'
    status_file = archived / 'status.md'
    original = status_file.read_text(encoding='utf-8')
    status_file.write_text(original.replace('| DONE |', '| MERGED |', 1), encoding='utf-8')
    closed_lint = subprocess.run([*ORCH, '--workspace', str(archived), 'lint'], capture_output=True, encoding='utf-8', errors='replace')
    assert 'program is closed but WP-CORE-01 is MERGED' in closed_lint.stderr, closed_lint.stderr
    status_file.write_text(original, encoding='utf-8')
    run(home, 'init', 'next', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'core={mono}')
    found = subprocess.run([*ORCH, 'queue'], cwd=home, capture_output=True, encoding='utf-8', errors='replace', env={**os.environ, **GIT_ENV})
    assert found.returncode == 0, 'only the active workspace is picked automatically'
    reopened = run(home, *wsarg, 'reopen', 'import is needed after all').stdout
    assert 'reopened' in reopened and 'git mv' in reopened
    assert orch.parse_yaml(closed_cfg.read_text(encoding='utf-8'))['state'] == 'active'
    assert 'Reopened ' in status_file.read_text(encoding='utf-8')
    assert run(home, *wsarg, 'new-wp', 'core', 'import-again').returncode == 0
    # L2: a workspace that is the root of its own repository is closed but not moved.
    solo = tmp / 'close/solo'
    run(tmp / 'close', 'init', 'solo', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--dir', 'solo', '--module', f'core={mono}')
    git(solo, 'init', '-q')
    text = (solo / 'PLAN.md').read_text(encoding='utf-8')
    block = text[text.index('<The one goal'):text.index('## Scope')].rstrip()
    safe_edit.replace_once(solo / 'PLAN.md', block, 'Goal.\n\nCompletion condition: nothing to do.')
    out = run(solo, 'close', '--apply').stdout
    assert 'root of its repository' in out and not (solo / '_archive').exists() and not (tmp / 'close/_archive').exists()
    print('PASS close: facts and evidence, carry, atomic apply and finish, archive pushed, refusals, reopen, root')


def test_close_in_repo(tmp):
    """2d in-repo: archive commands tied to the closeout commit, printed not run; no re-push after archive."""
    mono = make_monorepo(tmp / 'closecloud')
    with_workflow(mono, DEPLOY_WORKFLOW)
    remote = tmp / 'closecloud/mono.git'
    clone = tmp / 'closecloud/orch'
    git(tmp, 'clone', '-q', str(remote), str(clone))
    run(clone, 'init', 'demo', '--lang', 'en', '--sessions', 'cloud', '--permission-mode', 'auto', '--cloud-environment', 'Project env', '--in-repo', 'app', '--area', 'admin=app:apps/admin/**')
    run(clone, 'new-wp', 'admin', 'orders')
    run(clone, 'set', 'WP-ADMIN-01', 'status', 'DONE', '--evidence', 'verified')
    run(clone, 'commit', 'demo: done')
    assert 'no filled completion condition' in run(clone, 'close', '--apply', ok=False).stderr
    out = run(clone, 'close', '--apply', '--goal-confirmed', 'owner confirmed on PROD', '--summary', 'Goal reached.').stdout
    assert 'closeout:' in out and 'archived' not in out, out
    ws = clone / 'docs/orchestration/demo'
    status = (ws / 'status.md').read_text(encoding='utf-8')
    closeout_sha = git(remote, 'log', '--format=%H %s', 'orch/demo').split('\n')
    closeout_sha = next(l.split()[0] for l in closeout_sha if 'demo: close program' in l)
    assert f'git push origin {closeout_sha}:refs/tags/orch-demo-closed-' in status, status
    assert 'git push origin --delete orch/demo' in status and '/private' not in status.split('Archive')[1][:200]
    assert 'Keep the workspace as history in docs/' in status
    assert 'owner confirmed on PROD' in next((ws / 'reports').glob('closeout-*.md')).read_text(encoding='utf-8')
    assert not git(remote, 'tag', '-l').strip(), 'the plugin never creates tags'
    assert git(remote, 'branch', '--list', 'orch/demo').strip(), 'the plugin never deletes branches'
    assert 'archive steps for the owner' in git(remote, 'log', '-1', '--format=%s', 'orch/demo')
    assert not git(remote, 'log', '--oneline', 'main', '--', 'docs').strip(), 'nothing on the base'
    # M3: the owner runs the archive commands; closing R-1 afterwards never re-creates the branch.
    owner_clone = tmp / 'closecloud/owner'
    git(tmp, 'clone', '-q', str(remote), str(owner_clone))
    start = status.index('git push origin ' + closeout_sha)
    command = status[start:status.index(' ; expected', start)]
    ran = subprocess.run(command, shell=True, cwd=owner_clone, capture_output=True, encoding='utf-8', errors='replace',
                         env={**os.environ, **GIT_ENV})
    assert ran.returncode == 0, (command, ran.stdout, ran.stderr)
    assert git(remote, 'tag', '-l').strip().startswith('orch-demo-closed-')
    assert not git(remote, 'branch', '--list', 'orch/demo').strip()
    run(clone, 'owner', 'close', 'R-1', 'git ls-remote --tags origin: tag present; branch gone')
    committed = run(clone, 'commit', 'demo: archive verified').stdout
    assert 'no longer on origin (archived): committed locally, not pushed' in committed, committed
    assert not git(remote, 'branch', '--list', 'orch/demo').strip(), 'the archived branch must not come back'
    print('PASS close in-repo: archive commands tied to the closeout commit, printed not run; no re-push')


def test_models(tmp):
    """2e: implementer model and effort per package, start-command flags, lint, cloud prefill."""
    import streams
    from urllib.parse import urlparse, parse_qs
    mono = make_monorepo(tmp / 'models')
    home = tmp / 'models/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'mdl', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}',
        '--area', 'app=mono:apps/app/**', '--area', 'admin=mono:apps/admin/**')
    ws = home / 'features/mdl'
    config = ws / 'orch.yaml'
    safe_edit.replace_once(config, 'repos:\n', 'models:\n  implement: sonnet\n  escalate: opus\n'
                                               '  escalate_effort: high\nrepos:\n')
    safe_edit.replace_once(config, '    paths: ["apps/admin/**"]\n    session: mdl-admin\n',
                           '    paths: ["apps/admin/**"]\n    session: mdl-admin\n    model: opus\n    effort: high\n')
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    run(home, 'new-wp', 'app', 'list')
    run(home, 'new-wp', 'admin', 'roles')
    app = (ws / 'work-packages/WP-APP-01-list.md').read_text(encoding='utf-8')
    admin = (ws / 'work-packages/WP-ADMIN-01-roles.md').read_text(encoding='utf-8')
    assert '| Model | `sonnet` |' in app and '| Effort | — |' in app and 'models.implement' in app
    assert f'cd {mono} && claude -w wp-app-01-list --model sonnet --name mdl-app "' in app, app
    assert '| Model | `opus` |' in admin and '| Effort | `high` |' in admin and 'module override' in admin
    assert '--model opus --effort high --name mdl-admin' in admin
    for wp in ('WP-APP-01', 'WP-ADMIN-01'):
        run(home, 'set', wp, 'status', 'READY')
    before = (ws / 'status.md').read_text(encoding='utf-8')
    dry = run(home, 'dispatch', 'WP-APP-01', '--dry-run').stdout
    assert 'model sonnet' in dry and 'claude -w wp-app-01-list --permission-mode auto --settings ' in dry, dry
    assert ' --model sonnet --name mdl-app' in dry, dry
    assert (ws / 'status.md').read_text(encoding='utf-8') == before, 'dry-run writes nothing'
    assert '--model opus --effort high' in run(home, 'dispatch', 'WP-ADMIN-01', '--dry-run').stdout
    # orch.py model: header rows, the start command and the journal change together.
    run(home, 'model', 'WP-APP-01', 'gpt-4', '--reason', 'x', ok=False)
    run(home, 'model', 'WP-APP-01', 'opus', '--effort', 'extreme', '--reason', 'x', ok=False)
    run(home, 'model', 'WP-APP-01', 'opus', '--effort', 'high', '--reason', 'cross-module contract change')
    app = (ws / 'work-packages/WP-APP-01-list.md').read_text(encoding='utf-8')
    assert '| Model | `opus` |' in app and '| Model reason | cross-module contract change |' in app
    assert '--model opus --effort high --name mdl-app' in app and '--model sonnet' not in app
    out = run(home, 'dispatch', 'WP-APP-01').stdout
    assert '--model opus --effort high' in out
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'model opus, effort high' in status and 'WP-APP-01: model opus, effort high (cross-module' in status
    # L2: model and effort in a package header are checked too.
    app_path = ws / 'work-packages/WP-APP-01-list.md'
    app_original = app_path.read_text(encoding='utf-8')
    app_path.write_text(app_original.replace('| Model | `opus` |', '| Model | `gpt-4` |', 1), encoding='utf-8')
    assert "header: model 'gpt-4' is not one of" in lint_errors(home)
    run(home, 'set', 'WP-ADMIN-01', 'status', 'READY')
    admin_path = ws / 'work-packages/WP-ADMIN-01-roles.md'
    admin_original = admin_path.read_text(encoding='utf-8')
    admin_path.write_text(admin_original.replace('| Model | `opus` |', '| Model | `gpt-4` |', 1), encoding='utf-8')
    refusal = run(home, 'dispatch', 'WP-ADMIN-01', '--dry-run', ok=False).stderr
    assert "WP-ADMIN-01 header: model 'gpt-4'" in refusal, refusal
    admin_path.write_text(admin_original.replace('| Model | `opus` |', '| Model | — |', 1), encoding='utf-8')
    app_path.write_text(app_original, encoding='utf-8')
    assert 'Effort without Model' in run(home, 'lint').stderr
    admin_path.write_text(admin_original, encoding='utf-8')
    # lint: invalid aliases and efforts are errors.
    original = config.read_text(encoding='utf-8')
    for bad, expected in (('models:\n  implement: sonnet', 'models:\n  implement: sonet'),
                          ('mdl-admin\n    model: opus\n    effort: high', 'mdl-admin\n    model: opus\n    effort: extreme'),
                          ('mdl-admin\n    model: opus', 'mdl-admin\n    model: gpt-4')):
        config.write_text(original.replace(bad, expected, 1), encoding='utf-8')
        assert 'is not one of' in lint_errors(home), expected
    config.write_text(original, encoding='utf-8')
    # Without models: no flags (the 0.4.0 behaviour is also pinned by the legacy fixture test).
    assert streams.apply_model_flags('cd x && claude -w s --name n "p"', None, None) == 'cd x && claude -w s --name n "p"'
    assert streams.apply_model_flags('cd x && claude --model a --effort b --name n "p"', 'opus', None) == \
        'cd x && claude --model opus --name n "p"'
    # Cloud block and prefill link (a hosted-looking origin; nothing is fetched).
    hosted = tmp / 'models/hosted'
    git(tmp, 'clone', '-q', str(tmp / 'models/mono.git'), str(hosted))
    git(hosted, 'remote', 'set-url', 'origin', 'https://github.com/Owner/Repo.git')
    repo = streams.Repo({'id': 'r', 'path': str(hosted), 'base': 'main', 'sessions': 'cloud',
                         'cloud_environment': 'Project env'})
    module = streams.Module({'id': 'web', 'repo': 'r', 'kind': 'area', 'paths': ['apps/**']}, repo, 'mdl')
    prompt = 'Cloud session for work package WP-WEB-01: read the package & deliver a PR = done?'
    block = streams.cloud_block('en', 'WP-WEB-01', module, prompt, 'opus', 'high')
    assert '- Environment: Project env' in block and '- Repository: owner/repo, starting branch: main' in block
    assert '`/model opus` and `/effort high`' in block and block.endswith('Prompt:\n' + prompt)
    url = next(l for l in block.split('\n') if 'claude.ai/code?' in l).split(': ', 1)[1]
    query = parse_qs(urlparse(url).query)
    assert query == {'repositories': ['owner/repo'], 'environment': ['Project env'], 'prompt': [prompt]}, query
    long_prompt = 'x' * (streams.PREFILL_URL_LIMIT + 10)
    long_block = streams.cloud_block('ru', 'WP-WEB-01', module, long_prompt, None, None)
    long_url = next(l for l in long_block.split('\n') if 'claude.ai/code?' in l).split(': ', 1)[1]
    assert 'prompt=' not in long_url and 'без промпта' in long_block and long_block.endswith(long_prompt)
    assert 'по умолчанию владельца' in long_block
    # lint warns about a cloud module without an environment.
    safe_edit.replace_once(config, '    checks: []\n', '    checks: []\n    sessions: cloud\n')
    warned = run(home, 'lint')
    assert 'runs cloud sessions but has no cloud_environment' in warned.stderr, warned.stderr
    print('PASS models: per-package model and effort, flags, orch.py model, lint, cloud block and prefill link')


def test_local_cloud_matrix(tmp):
    """2e bis: five fixtures, each with and without models; local output never has cloud parts and
    cloud output never has terminal commands or model flags."""
    local_bad = ('/model ', 'environment=', 'claude.ai/code')
    cloud_bad = ('claude -w', '&& claude', '--model')
    for with_models in (False, True):
        tag = 'm' if with_models else 'n'
        base = tmp / f'matrix-{tag}'
        mono = make_monorepo(base)
        with_workflow(mono, DEPLOY_WORKFLOW)
        remote = base / 'mono.git'
        cases = []
        # A: separate workspace, local module that is a whole repository.
        home_a = base / 'a'
        home_a.mkdir()
        git(home_a, 'init', '-q')
        run(home_a, 'init', 'pa', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'core={mono}')
        cases.append(('A', home_a, home_a / 'features/pa', 'core', 'local'))
        # B: separate workspace, local stream.
        home_b = base / 'b'
        home_b.mkdir()
        git(home_b, 'init', '-q')
        run(home_b, 'init', 'pb', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}', '--area', 'app=mono:apps/app/**')
        cases.append(('B', home_b, home_b / 'features/pb', 'app', 'local'))
        # C: in-repo workspace, local stream.
        clone_c = base / 'c'
        git(base, 'clone', '-q', str(remote), str(clone_c))
        run(clone_c, 'init', 'pc', '--lang', 'en', '--in-repo', 'app', '--sessions', 'local', '--permission-mode', 'auto',
            '--area', 'web=app:apps/app/**')
        cases.append(('C', clone_c, clone_c / 'docs/orchestration/pc', 'web', 'local'))
        # D: in-repo workspace, cloud module.
        clone_d = base / 'd'
        git(base, 'clone', '-q', str(remote), str(clone_d))
        run(clone_d, 'init', 'pd', '--lang', 'en', '--in-repo', 'app', '--sessions', 'cloud', '--permission-mode', 'auto',
            '--cloud-env', 'Project env', '--area', 'web=app:apps/app/**')
        cases.append(('D', clone_d, clone_d / 'docs/orchestration/pd', 'web', 'cloud'))
        # E: separate workspace, cloud module (the package travels as text).
        home_e = base / 'e'
        home_e.mkdir()
        git(home_e, 'init', '-q')
        run(home_e, 'init', 'pe', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--repo', f'mono={mono}', '--area', 'app=mono:apps/app/**')
        safe_edit.replace_once(home_e / 'features/pe/orch.yaml', '    checks: []\n',
                               '    checks: []\n    sessions: cloud\n    cloud_environment: "Project env"\n')
        cases.append(('E', home_e, home_e / 'features/pe', 'app', 'cloud'))
        for label, cwd, ws, module, kind in cases:
            config = ws / 'orch.yaml'
            if with_models:
                text = config.read_text(encoding='utf-8')
                anchor = '\nrepos:' if '\nrepos:' in text else '\nmodules:'
                safe_edit.replace_once(config, anchor, '\nmodels:\n  implement: sonnet' + anchor)
            run(cwd, 'new-wp', module, 'task')
            wp = f'WP-{module.upper()}-01'
            run(cwd, 'set', wp, 'status', 'READY')
            if label in ('C', 'D'):
                run(cwd, 'commit', f'{label}: package')
            out = run(cwd, 'dispatch', wp, '--dry-run').stdout
            wp_text = next((ws / 'work-packages').glob(f'{wp}-*.md')).read_text(encoding='utf-8')
            lint = run(cwd, 'lint')
            if kind == 'local':
                for bad in local_bad:
                    assert bad not in out, (label, tag, bad, out)
                assert ('--model sonnet' in out) == with_models, (label, tag, out)
                assert 'environment' not in lint.stderr, (label, tag, lint.stderr)
                if label in ('B', 'C'):
                    assert 'claude -w wp-' in out, (label, out)
                if label == 'C':
                    assert f'cd {clone_c.resolve()} && claude -w' in out or f'cd {clone_c} && claude -w' in out, out
            else:
                prompt_part = out.split('Prompt:\n', 1)[1]
                for bad in cloud_bad:
                    assert bad not in out, (label, tag, bad, out)
                assert 'New cloud session for' in out and '- Environment: Project env' in out, (label, out)
                assert ('- Model: sonnet' in out) == with_models, (label, tag, out)
                assert ('owner default' in out) == (not with_models), (label, tag, out)
                assert ('\n---\n# WP-' in prompt_part) == (label == 'E'), (label, prompt_part[:200])
            assert ('| Model | `sonnet` |' in wp_text) == with_models, (label, tag)
        # In-repo with local sessions: a whole-repository module shares the main checkout on orch/<p>.
        if not with_models:
            clone_f = base / 'f'
            git(base, 'clone', '-q', str(remote), str(clone_f))
            out = run(clone_f, 'init', 'pf', '--lang', 'en', '--in-repo', 'app', '--sessions', 'local', '--permission-mode', 'auto').stdout
            config = clone_f / 'docs/orchestration/pf/orch.yaml'
            safe_edit.replace_once(config, 'modules: []\n', 'modules:\n  - id: core\n    repo: app\n')
            warned = run(clone_f, 'lint').stderr
            assert 'main checkout' in warned and 'orch/pf' in warned, warned
            hint = run(base / 'd', '--workspace', str(base / 'd/docs/orchestration/pd'), 'lint').stderr
            assert 'environment' not in hint
        if not with_models:
            # The owner chooses the session kind at init; cloud needs an environment; a cloud
            # orchestrator works only with cloud sessions.
            fresh = base / 'fresh'
            fresh.mkdir()
            git(fresh, 'init', '-q')
            asked = run(fresh, 'init', 'q', '--lang', 'en', '--module', f'core={mono}', ok=False).stderr
            assert 'the owner chooses the session kind' in asked and 'locally' in asked and 'recommended' in asked
            assert 'needs --cloud-environment' in run(fresh, 'init', 'q', '--lang', 'en', '--sessions', 'cloud', '--permission-mode', 'auto',
                                                      '--module', f'core={mono}', ok=False).stderr
            assert 'only for --sessions cloud' in run(fresh, 'init', 'q', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
                                                      '--cloud-environment', 'X', '--module', f'core={mono}',
                                                      ok=False).stderr
            remote_env = {'CLAUDE_CODE_REMOTE': 'true'}
            refused = run(fresh, 'init', 'q', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'core={mono}',
                          ok=False, extra_env=remote_env).stderr
            assert 'local module sessions need a local orchestrator' in refused, refused
            assert run(fresh, 'init', 'q', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'core={mono}').returncode == 0
            journal = (fresh / 'features/q/status.md').read_text(encoding='utf-8')
            assert 'session kind: local, confirmed by the owner' in journal
            run(fresh, 'new-wp', 'core', 'x')
            run(fresh, 'set', 'WP-CORE-01', 'status', 'READY')
            refused = run(fresh, 'dispatch', 'WP-CORE-01', '--dry-run', ok=False, extra_env=remote_env).stderr
            assert 'local module sessions need a local orchestrator' in refused, refused
    print('PASS local/cloud matrix: 5 fixtures x with/without models, outputs separated')

def test_settings(tmp):
    """3a: settings files, dispatch flags, permission mode, worktrees without secrets, on-demand locks."""
    import session_settings
    mono = make_monorepo(tmp / 'settings')
    (mono / '.gitignore').write_text('.env\n', encoding='utf-8')
    (mono / '.env').write_text('TOKEN=placeholder\n', encoding='utf-8')
    single = make_monorepo(tmp / 'settings-db')
    home = tmp / 'settings/home'
    home.mkdir()
    git(home, 'init', '-q')
    args = ['init', 'shop', '--lang', 'en', '--sessions', 'local', '--repo', f'mono={mono}',
            '--area', 'admin=mono:apps/admin/**', '--area', 'app=mono:apps/app/**', '--module', f'db={single}']
    asked = run(home, *args, ok=False).stderr
    assert 'Which permission mode' in asked and '--permission-mode' in asked, asked
    out = run(home, *args, '--permission-mode', 'auto').stdout
    ws = home / 'features/shop'
    config = ws / 'orch.yaml'
    assert orch.parse_yaml(config.read_text(encoding='utf-8'))['permission_mode'] == 'auto'
    assert '--name shop-coord --permission-mode auto --settings orchestration/settings/orchestrator.json' in out, out
    assert '"Messages from your other sessions" -> accept' in out, out
    assert 'owner question: Repository mono: add `.worktreeinclude`' in out and ': .env (' in out, out
    assert 'P-1' in run(home, 'queue').stdout
    assert 'Repository db' not in out, 'a whole-repository module has no worktrees'
    for old, new in (
        ('    worktree_setup: []', '    worktree_setup: ["pnpm install --frozen-lockfile", '
                                   '"cp ../../../.env .env", "cp -R ../../../.claude .claude"]'),
        ('    shared_paths: []', '    shared_paths: [pnpm-lock.yaml, "backend/migrations/**"]'),
        ('    resources: []', '    resources: [staging, {name: ci-gate, mode: on-demand}]'),
        ('    checks: []', '    checks: ["./scripts/check-order.sh && echo ok"]'),
        ('    session: shop-app\n', '    session: shop-app\n    tests: {scoped: ["pnpm --filter app test"], '
                                   'full: ["pnpm -r test"]}\n    methodology: {name: m, forbidden: [m-release]}\n'),
        ('    tests: []\n', '    tests: ["./scripts/test.sh"]\n    deploy_test: ./scripts/deploy.sh --target test\n'
                          '    deploy_prod: ./scripts/deploy.sh --target prod\n'),
        ('environments: {}', 'environments:\n  prod: {db_mcp: example-prod}'),
        ('guards: {}', 'guards:\n  sql_select_only: [example-prod]'),
    ):
        safe_edit.replace_once(config, old, new)
    warned = run(home, 'lint').stderr
    assert 'worktree_setup `cp ../../../.env .env`' in warned and '.worktreeinclude' in warned, warned
    assert 'worktree_setup `cp -R ../../../.claude .claude`' in warned, warned
    assert 'older than orch.yaml' in warned, warned
    (ws / 'orchestration/settings/admin.local.json').write_text('{"permissions": {"allow": ["Bash(make x)"]}}\n',
                                                               encoding='utf-8')
    out = run(home, 'settings', 'all').stdout
    assert 'settings db: written' in out and 'settings orchestrator: written' in out, out
    assert 'cp ../../../.env .env` is not allowed' in out, out
    files = sorted(p.name for p in (ws / 'orchestration/settings').glob('*.json'))
    assert files == ['admin.json', 'admin.local.json', 'app.json', 'db.json', 'orchestrator.json'], files
    data = {n: json.loads((ws / f'orchestration/settings/{n}.json').read_text(encoding='utf-8'))
            for n in ('admin', 'app', 'db', 'orchestrator')}
    for name, item in data.items():
        assert not session_settings.settings_errors(item), (name, session_settings.settings_errors(item))
        assert item['crossSessionInbound'] == 'accept' and item['autoMode']['environment'][0] == '$defaults'
    app = data['app']['permissions']
    wsabs, monoabs = ws.resolve(), mono.resolve()
    for rule in (f'Read(/{monoabs}/apps/app/**)', f'Read(/{monoabs}/**)', 'Bash(pnpm --filter app test)',
                 'Bash(pnpm -r test)', 'Bash(./scripts/check-order.sh)', 'Bash(echo ok)',
                 'Bash(pnpm install --frozen-lockfile)', 'Bash(sed -n *)', 'Bash(gh pr create *)'):
        assert rule in app['allow'], (rule, app['allow'])
    assert not any(r.startswith('Bash(git push') for r in app['allow'] + app['ask']), app
    # M1 (rev.2): pushes to the base and force pushes in tail forms are never allowed and always denied.
    risky = ['git push origin feature/x:main --no-verify', 'git push origin feature/x:refs/heads/main',
             'git push origin HEAD:refs/heads/main --no-verify', 'git push origin feature/x refs/heads/main',
             'git push origin feature/x --force', 'git push origin feature/x --force --no-verify',
             'git push origin feature/x -f', 'git push origin feature/x -f -u',
             'git push origin feature/x --force-with-lease', 'git push --force-with-lease origin feature/x',
             'git push origin +feature/x', 'git push -u origin main', 'git push origin main --no-verify',
             'git push --force origin feature/x', 'git push origin HEAD:main']
    for name in ('app', 'db', 'orchestrator'):
        perms = data[name]['permissions']
        for command in risky:
            allowed = [r for r in perms['allow'] + perms['ask'] if session_settings.bash_rule_matches(r, command)]
            assert not [r for r in allowed if r in perms['allow']], (name, command, allowed)
            assert any(session_settings.bash_rule_matches(r, command) for r in perms['deny']), (name, command)
    assert session_settings.bash_rule_matches('Bash(ls *)', 'ls') and not session_settings.bash_rule_matches(
        'Bash(ls *)', 'lsof') and session_settings.bash_rule_matches('Bash(git push * -f *)', 'git push o x -f -u')
    assert not any('.env' in r or '.claude' in r for r in app['allow']), app['allow']
    for rule in ('Bash(gh pr merge *)', 'Bash(git push origin main)', 'Bash(git push origin HEAD:main)',
                 'Bash(git push --force *)', 'Bash(gh workflow run *)', f'Edit(/{wsabs}/**)',
                 'mcp__example-prod__*', 'Bash(ssh *)', 'Skill(m-release)'):
        assert rule in app['deny'], (rule, app['deny'])
    db = data['db']['permissions']
    assert 'Bash(./scripts/deploy.sh --target test *)' in db['ask'], db['ask']
    assert 'Bash(git push *)' not in db['ask'], 'push is a checkpoint only when asked for'
    assert 'Bash(./scripts/deploy.sh --target prod)' in db['deny'] and 'Bash(./scripts/test.sh)' in db['allow']
    orch_rules = data['orchestrator']['permissions']
    assert f'Bash(python3 {HERE}/orch.py *)' in orch_rules['allow'] and 'Bash(gh pr merge *)' in orch_rules['deny']
    assert not any('merge' in r for r in orch_rules['allow'])
    assert any(line.startswith('Trusted repo: ') for line in data['app']['autoMode']['environment'])
    for bad in ('Read(/abs/path/**)', 'mcp__server__x(y)', 'Bash()', 'Skill(a b c)', 'Write'):
        assert session_settings.rule_errors(bad), bad
    assert session_settings.split_commands('a && b "c && d" | e; f') == ['a', 'b "c && d"', 'e', 'f']
    assert session_settings.secret_copies(['cp .env.example .env', 'cp -r ../x/certs certs']) == \
        ['cp -r ../x/certs certs']
    again = run(home, 'settings', 'all').stdout
    assert 'settings app: unchanged' in again and 'written' not in again, again
    # L4: checkpoints [push] asks for every git push (the documented recipe).
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, 'checkpoints: [deploy_test]', 'checkpoints: [push, deploy_test]')
    run(home, 'settings', 'app')
    pushed = json.loads((ws / 'orchestration/settings/app.json').read_text(encoding='utf-8'))['permissions']
    assert 'Bash(git push *)' in pushed['ask'] and 'Bash(git push origin main)' in pushed['deny'], pushed['ask']
    config.write_text(original, encoding='utf-8')
    run(home, 'settings', 'app')
    assert 'make x' in (ws / 'orchestration/settings/admin.local.json').read_text(encoding='utf-8')
    assert 'older than' not in run(home, 'lint').stderr
    # Work packages, dispatch flags and refusal without the file.
    for mod, slug in (('app', 'checkout'), ('admin', 'orders'), ('db', 'schema')):
        run(home, 'new-wp', mod, slug)
    wps = ws / 'work-packages'
    app_wp = wps / 'WP-APP-01-checkout.md'
    text = app_wp.read_text(encoding='utf-8')
    assert '## 6. If a permission is denied' in text and 'QUESTION WP-APP-01 :: denied:' in text, text
    assert 'LOCK WP-APP-01 :: <resource>' in text and '`ci-gate` (on-demand' in text, text
    fill_header(app_wp, 'Resources (locks)', '`ci-gate`')
    fill_header(app_wp, 'Shared paths touched', '`some.test.mjs`')
    fill_header(wps / 'WP-ADMIN-01-orders.md', 'Resources (locks)', '`ci-gate`')
    for wp in ('WP-APP-01', 'WP-ADMIN-01', 'WP-DB-01'):
        run(home, 'set', wp, 'status', 'READY')
    warned = run(home, 'lint').stderr
    assert '`some.test.mjs` in the Shared paths or Resources row is not a lock of repo mono' in warned, warned
    dry = run(home, 'dispatch', 'WP-APP-01', '--dry-run')
    assert 'locks to take: none' in dry.stdout and 'on-demand locks, taken when the session sends LOCK: ci-gate' \
        in dry.stderr and 'some.test.mjs' in dry.stderr, (dry.stdout, dry.stderr)
    assert f'--permission-mode auto --settings {wsabs}/orchestration/settings/app.json --name shop-app' in dry.stdout
    db_dry = run(home, 'dispatch', 'WP-DB-01', '--dry-run').stdout
    assert f'cd {single} && claude --permission-mode auto --settings {wsabs}/orchestration/settings/db.json ' \
        '--name shop-db' in db_dry, db_dry
    moved = ws / 'orchestration/settings/db.json'
    moved.rename(moved.with_suffix('.bak'))
    refused = run(home, 'dispatch', 'WP-DB-01', '--dry-run', ok=False).stderr
    assert 'orchestration/settings/db.json is missing: run orch.py settings db' in refused, refused
    assert '--settings' not in run(home, 'dispatch', 'WP-DB-01', '--dry-run', '--no-settings').stdout
    moved.with_suffix('.bak').rename(moved)
    # On-demand locks: not taken at dispatch; LOCK -> acquire, queue, READY releases, stale warning.
    run(home, 'dispatch', 'WP-APP-01')
    run(home, 'dispatch', 'WP-ADMIN-01')
    assert 'locks: none' in run(home, 'lock', 'list').stdout
    assert 'held by WP-APP-01' in run(home, 'lock', 'acquire', 'ci-gate', '--wp', 'WP-APP-01').stdout
    assert 'queued' in run(home, 'lock', 'acquire', 'ci-gate', '--wp', 'WP-ADMIN-01', ok=False).stderr
    assert '(on-demand)' in run(home, 'lock', 'list').stdout
    released = run(home, 'set', 'WP-APP-01', 'status', 'REVIEW').stderr
    assert 'lock mono:ci-gate: released; next in queue: WP-ADMIN-01' in released, released
    run(home, 'lock', 'acquire', 'ci-gate', '--wp', 'WP-ADMIN-01')
    since = json.loads(run(home, 'lock', 'list', '--json').stdout)[0]['since']
    later = (orch.dt.datetime.strptime(since, '%Y-%m-%d %H:%MZ') + orch.dt.timedelta(hours=5)).strftime('%Y-%m-%d %H:%MZ')
    assert 'on-demand lock' not in run(home, 'lint').stderr
    stale = run(home, 'lint', extra_env={'ORCH_NOW': later}).stderr
    assert 'on-demand lock mono:ci-gate held by WP-ADMIN-01 for 5 h (limit 4 h)' in stale, stale
    run(home, 'lock', 'release', 'ci-gate', '--wp', 'WP-ADMIN-01')
    # A cloud module keeps its block without --settings.
    safe_edit.replace_once(config, '\n  - id: admin\n',  # the commented example starts with '#'
                           '\n  - id: admin\n    sessions: cloud\n    cloud_environment: "Env"\n')
    assert 'settings admin: skipped' in run(home, 'settings', 'all').stdout
    run(home, 'new-wp', 'admin', 'report')
    run(home, 'set', 'WP-ADMIN-02', 'status', 'READY')
    run(home, 'set', 'WP-ADMIN-01', 'status', 'CANCELLED (selftest)')
    cloud = run(home, 'dispatch', 'WP-ADMIN-02', '--dry-run').stdout
    assert 'New cloud session for WP-ADMIN-02' in cloud and '--settings' not in cloud, cloud
    # d) the session name is checked against coordinator_session in modes and the bootstrap prompt.
    modes = HERE.parent / 'references/modes'
    for name in ('dispatch.md', 'resume.md'):
        assert '/rename <coordinator_session>' in (modes / name).read_text(encoding='utf-8'), name
    bootstrap = (ws / 'orchestration/bootstrap-prompt.md').read_text(encoding='utf-8')
    assert '/rename shop-coord' in bootstrap and '--permission-mode\nauto --settings' in bootstrap, bootstrap
    print('PASS settings: files per session, rules, dispatch flags and refusal, permission mode, '
          '.worktreeinclude, on-demand locks, cloud unchanged')


def test_deploy_override_first_candidate(tmp):
    """3a defect a: a positive paths filter behind a branch filter passes; an override without --dir
    takes the first readable candidate; no candidate at all asks for --dir."""
    mono = make_monorepo(tmp / 'field')
    with_workflow(mono, "on:\n  push:\n    branches: [main, 'release/**']\n    paths: ['src/**']\njobs: {}\n")
    clone = tmp / 'field/clone'
    git(tmp, 'clone', '-q', str(tmp / 'field/mono.git'), str(clone))
    out = run(clone, 'init', 'p', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
              '--in-repo', 'app').stdout
    assert 'directory docs/orchestration/p' in out, out
    mono2 = make_monorepo(tmp / 'field2')
    with_workflow(mono2, "on:\n  push:\n    paths-ignore: ['docs/**']\njobs: {}\n")
    with_workflow(mono2, 'on:\n  - push\n', 'odd.yml')
    clone2 = tmp / 'field2/clone'
    git(tmp, 'clone', '-q', str(tmp / 'field2/mono.git'), str(clone2))
    refused = run(clone2, 'init', 'q', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
                  '--in-repo', 'app', ok=False).stderr
    assert 'odd.yml' in refused and 'docs/orchestration/q' in refused and '--dir <directory>' in refused, refused
    out = run(clone2, 'init', 'q', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
              '--in-repo', 'app', '--deploy-override', 'D-1').stdout
    assert 'directory docs/orchestration/q' in out and 'overridden by owner decision D-1' in out, out
    mono3 = make_monorepo(tmp / 'field3')
    with_workflow(mono3, 'on: [push]\njobs: {}\n')
    with_workflow(mono3, 'on:\n  - push\n', 'odd.yml')
    clone3 = tmp / 'field3/clone'
    git(tmp, 'clone', '-q', str(tmp / 'field3/mono.git'), str(clone3))
    refused = run(clone3, 'init', 'r', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
                  '--in-repo', 'app', '--deploy-override', 'D-1', ok=False).stderr
    assert 'cannot verify' in refused and 'no non-hidden directory' in refused and '--dir <directory>' in refused, \
        refused
    print('PASS deploy override: positive paths behind a branch filter, first candidate, --dir only without one')


GH_STUB = """#!/usr/bin/env python3
import os, sys
root = os.environ['GH_STUB_DIR']
with open(os.path.join(root, 'calls.log'), 'a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
kind = {('run', 'list'): 'runs.json', ('pr', 'view'): 'pr.json'}.get(tuple(sys.argv[1:3]))
if not kind:
    sys.exit(1)
print(open(os.path.join(root, kind)).read())
"""


def test_verify(tmp):
    """3b: verify by facts with a stub gh and stub verify commands (no real gh, no network)."""
    mono = make_monorepo(tmp / 'verify')
    stub = tmp / 'verify/stub'
    (stub / 'bin').mkdir(parents=True)
    (stub / 'bin/gh').write_text(GH_STUB, encoding='utf-8')
    (stub / 'bin/gh').chmod(0o755)
    sha = git(mono, 'rev-parse', 'HEAD').strip()
    (stub / 'pr.json').write_text(json.dumps({'state': 'MERGED', 'mergeCommit': {'oid': sha}}), encoding='utf-8')
    runs = [{'databaseId': 7, 'status': 'completed', 'conclusion': 'success', 'headBranch': 'main',
             'url': 'https://example.invalid/runs/7', 'createdAt': '2026-09-30T10:00:00Z'}]
    (stub / 'runs.json').write_text(json.dumps(runs), encoding='utf-8')
    version = tmp / 'verify/version.json'
    version.write_text(json.dumps({'sha': sha}), encoding='utf-8')
    flag = tmp / 'verify/fail.flag'
    gh_env = {'ORCH_NO_GH': '', 'GH_STUB_DIR': str(stub), 'PATH': f'{stub / "bin"}{os.pathsep}{os.environ["PATH"]}'}
    home = tmp / 'verify/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
        '--repo', f'mono={mono}', '--area', 'app=mono:apps/app/**')
    ws = home / 'features/shop'
    config = ws / 'orch.yaml'
    for old, new in (
        ('    checks: []\n', '    checks: []\n    deploy_workflows: [deploy.yml]\n'
                           f'    version_url: "file://{version}"\n'
                           '    version_pattern: \'"sha": "([0-9a-f]+)"\'\n'
                           '    verify_test: ["test \\"$ORCH_ENV\\" = test && echo checked $ORCH_WP $ORCH_BASE_URL", '
                           f'"test ! -f {flag} || (echo broken build; exit 2)", '
                           '"printf \'pass%s=abcdefgh12345\\\\n\' word"]\n'
                           '    verify_prod: ["sleep 3"]\n'),
        ('    session: shop-app\n', '    session: shop-app\n    web_urls: {test: https://test.example.com}\n'),
        ('push_after_milestone: false', 'push_after_milestone: false\nverify_timeout: 1'),
    ):
        safe_edit.replace_once(config, old, new)
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    git(mono, 'remote', 'set-url', 'origin', 'https://github.com/example/mono.git')
    for slug in ('orders', 'cart', 'fees', 'tax'):
        run(home, 'new-wp', 'app', slug)
    for wp in ('WP-APP-01', 'WP-APP-02', 'WP-APP-03', 'WP-APP-04'):
        run(home, 'set', wp, 'pr', 'https://github.com/example/mono/pull/5')
        run(home, 'set', wp, 'status', 'MERGED' if wp != 'WP-APP-04' else 'ACCEPTED')
    listed = run(home, 'verify', '--list').stdout
    assert 'WP-APP-01 (MERGED): orch.py verify WP-APP-01 --env test' in listed, listed
    # Dry run: the plan, nothing written, gh never called.
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    plan = run(home, 'verify', 'WP-APP-01', '--env', 'test', '--dry-run', extra_env=gh_env).stdout
    assert '1. deploy: deploy.yml' in plan and '2. version: file://' in plan and 'PASS -> status VERIFIED_TEST' in plan
    assert 'merge commit of https://github.com/example/mono/pull/5 (gh)' in plan, plan
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and '.orch-backup' not in p.parts}
    assert before == after and not (stub / 'calls.log').exists(), 'dry run must not write or call gh'
    refused = run(home, 'verify', 'WP-APP-01', '--env', 'test', ok=False).stderr
    assert 'verify needs gh' in refused, refused
    # PASS: merge commit from the PR, deploy run for that SHA, served version, commands -> VERIFIED_TEST.
    out = run(home, 'verify', 'WP-APP-01', '--env', 'test', extra_env=gh_env).stdout
    assert f'PASS at {sha[:10]}' in out and 'status VERIFIED_TEST' in out, out
    calls = (stub / 'calls.log').read_text(encoding='utf-8')
    assert 'pr view https://github.com/example/mono/pull/5 --repo example/mono' in calls, calls
    assert f'run list --repo example/mono --workflow deploy.yml --commit {sha}' in calls, calls
    report = next((ws / 'reports').glob('verify-WP-APP-01-test-*.md')).read_text(encoding='utf-8')
    assert '| # | Check | Command or target | Exit | Output (first lines) | Verdict |' in report, report
    assert 'checked WP-APP-01 https://test.example.com' in report and '[redacted]' in report, report
    assert 'password=abcdefgh12345' not in report and '## Live scenario' in report and '**Verdict: PASS**' in report
    assert '| VERIFIED_TEST |' in (ws / 'status.md').read_text(encoding='utf-8')
    # FAIL: a failing command -> status kept, defect, journal; no owner item (the deploy run is fine).
    flag.write_text('x', encoding='utf-8')
    failed = run(home, 'verify', 'WP-APP-02', '--env', 'test', extra_env=gh_env, ok=False).stderr
    assert 'FAIL at' in failed and 'status stays MERGED' in failed and 'owner item' not in failed, failed
    bug = ws / 'bugs/BUG-1-verify-wp-app-02-test.md'
    assert bug.is_file() and 'broken build' in bug.read_text(encoding='utf-8')
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'WP-APP-02: verification on test failed' in status, status
    flag.unlink()
    # --sha that the environment does not serve -> FAIL.
    other = '0123456789abcdef0123456789abcdef01234567'
    mismatch = run(home, 'verify', 'WP-APP-02', '--env', 'test', '--sha', other, extra_env=gh_env, ok=False).stderr
    assert 'served version `file://' in mismatch and 'bugs/BUG-2-verify-wp-app-02-test.md' in mismatch, mismatch
    text = (ws / 'bugs/BUG-2-verify-wp-app-02-test.md').read_text(encoding='utf-8')
    assert f'serves {sha}, expected {other[:10]}' in text, text
    # No deploy run for the SHA -> FAIL and an owner item (a deploy needs the owner's rights).
    (stub / 'runs.json').write_text('[]', encoding='utf-8')
    nodeploy = run(home, 'verify', 'WP-APP-03', '--env', 'test', extra_env=gh_env, ok=False).stderr
    assert 'owner item: WP-APP-03: no successful deploy run on test' in nodeploy, nodeploy
    assert 'R-1' in run(home, 'queue').stdout
    # WAIT (rev.2 M1): a queued or running deploy run -> exit 2, journal, no defect, no owner item.
    running = [dict(runs[0], status='in_progress', conclusion=None)]
    (stub / 'runs.json').write_text(json.dumps(running), encoding='utf-8')
    bugs_before = sorted(p.name for p in (ws / 'bugs').glob('BUG-*.md'))
    owner_before = run(home, 'queue').stdout
    waited = run(home, 'verify', 'WP-APP-03', '--env', 'test', extra_env=gh_env, ok=False)
    assert waited.returncode == 2 and 'WAIT at' in waited.stderr and 'no defect' in waited.stderr, waited.stderr
    assert sorted(p.name for p in (ws / 'bugs').glob('BUG-*.md')) == bugs_before
    assert run(home, 'queue').stdout == owner_before
    assert 'WP-APP-03: verify on test waits for the deploy run' in (ws / 'status.md').read_text(encoding='utf-8')
    (stub / 'runs.json').write_text(json.dumps(runs), encoding='utf-8')
    # L4: ACCEPTED -> gh confirms the merge, MERGED, then PASS; an open PR or no gh refuses.
    assert 'verify needs gh' in run(home, 'verify', 'WP-APP-04', '--env', 'test', ok=False).stderr
    (stub / 'pr.json').write_text(json.dumps({'state': 'OPEN', 'mergeCommit': None}), encoding='utf-8')
    assert 'is OPEN, not merged' in run(home, 'verify', 'WP-APP-04', '--env', 'test', extra_env=gh_env, ok=False).stderr
    (stub / 'pr.json').write_text(json.dumps({'state': 'MERGED', 'mergeCommit': {'oid': sha}}), encoding='utf-8')
    run(home, 'verify', 'WP-APP-04', '--env', 'test', extra_env=gh_env)
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'WP-APP-04: ACCEPTED -> MERGED' in status and 'WP-APP-04: MERGED -> VERIFIED_TEST' in status, status
    run(home, 'new-wp', 'app', 'draft')
    assert 'needs one of MERGED' in run(home, 'verify', 'WP-APP-05', '--env', 'test', extra_env=gh_env, ok=False).stderr
    # Timeout of a verify command -> FAIL with a note; the status stays VERIFIED_TEST.
    slow = run(home, 'verify', 'WP-APP-01', '--env', 'prod', extra_env=gh_env, ok=False).stderr
    assert 'status stays VERIFIED_TEST' in slow, slow
    prod_report = next((ws / 'reports').glob('verify-WP-APP-01-prod-*.md')).read_text(encoding='utf-8')
    assert 'timed out after 1 s' in prod_report and '| timeout |' in prod_report, prod_report
    assert 'WP-APP-01 (VERIFIED_TEST): orch.py verify WP-APP-01 --env prod' in run(home, 'verify', '--list').stdout
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    # A secret-looking string in a verify command is a lint error.
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, '    verify_prod: ["sleep 3"]', '    verify_prod: ["curl -H api_key=abcdefgh12345678 x"]')
    assert 'orch.yaml: looks like a secret' in lint_errors(home)
    config.write_text(original, encoding='utf-8')
    # L2: an invalid version_pattern and verify_timeout are lint errors; a bad pattern is a FAIL, not a crash.
    safe_edit.replace_once(config, 'verify_timeout: 1', 'verify_timeout: soon')
    safe_edit.replace_once(config, '\n    version_pattern: \'"sha"', '\n    version_pattern: "([0-9" # \'"sha"')
    errors = lint_errors(home)
    assert 'verify_timeout must be a positive whole number' in errors and 'version_pattern is not a valid' in errors
    config.write_text(original, encoding='utf-8')
    import verification
    assert verification.served_version(f'file://{version}', '([0-9', sha)[0] == 'FAIL'
    # L3: Russian table head, summary texts and defect headings.
    assert '| # | Проверка | Команда или цель | Код |' in verification.table([], 'ru')
    ru_home = tmp / 'verify/ru-home'
    ru_home.mkdir()
    git(ru_home, 'init', '-q')
    run(ru_home, 'init', 'ru', '--lang', 'ru', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'db={mono}')
    ru_ws = orch.Workspace(ru_home / 'features/ru')
    rel = orch.write_bug(ru_ws, 'WP-DB-01', ru_ws.streams()[1]['db'], 'test', sha, 'reports/x.md',
                         [{'kind': 'команда проверки', 'target': 'false', 'exit': '1', 'output': []}])
    bug_ru = (ru_ws.root / rel).read_text(encoding='utf-8')
    assert '## Подтверждение' in bug_ru and '| Статус | открыт (WP-DB-01) |' in bug_ru and 'Field' not in bug_ru, bug_ru
    # L5: prod with its own branch: the tip of origin/<prod_branch> containing the merge commit.
    prod_repo = make_monorepo(tmp / 'verify-prod')
    merge = git(prod_repo, 'rev-parse', 'HEAD').strip()
    git(prod_repo, 'commit', '-q', '--allow-empty', '-m', 'release')
    git(prod_repo, 'push', '-q', 'origin', 'HEAD:refs/heads/prod')
    tip = git(prod_repo, 'rev-parse', 'HEAD').strip()
    repo_obj = orch.streams.Repo({'id': 'p', 'path': str(prod_repo), 'base': 'main'})
    assert verification.prod_tip(repo_obj, 'prod', merge) == tip
    git(prod_repo, 'switch', '-q', '-c', 'side', 'main~0')
    git(prod_repo, 'commit', '-q', '--allow-empty', '-m', 'not released')
    stray = git(prod_repo, 'rev-parse', 'HEAD').strip()
    try:
        verification.prod_tip(repo_obj, 'prod', stray)
    except RuntimeError as error:
        assert 'does not contain the merge commit' in str(error)
    else:
        raise AssertionError('a merge commit outside the prod branch must be refused')
    print('PASS verify: stub gh, merge commit, deploy run, WAIT, ACCEPTED->MERGED, served version, commands, report, '
          'VERIFIED_TEST, defect, owner item, timeout, dry run, redaction, lint, RU texts, prod tip')


def settings_fixture(root, workspace, skill):
    """The fixed module and orchestrator settings of fixtures/settings-0.7.0 for given paths."""
    import session_settings
    repo = orch.streams.Repo({'id': 'mono', 'path': root, 'base': 'main', 'branch_prefix': 'feature/',
                              'worktree_setup': ['pnpm install --frozen-lockfile'], 'checks': ['./scripts/check.sh']})
    mod = orch.streams.Module({'id': 'app', 'kind': 'area', 'repo': 'mono', 'paths': ['apps/app/**'],
                               'tests': {'scoped': ['pnpm --filter app test']},
                               'methodology': {'name': 'm', 'forbidden': ['m-release']}}, repo, 'shop')
    config = {'environments': {'prod': {'db_mcp': 'example-prod'}}, 'guards': {'x': [1]},
              'checkpoints': ['push', 'deploy_test']}
    data, _ = session_settings.module_settings(config, workspace, mod)
    return data, session_settings.orchestrator_settings(config, workspace, {'app': mod}, {'mono': repo}, skill)


def test_windows_paths(tmp):
    """0.7.1: rule paths in the documented Windows form, shell of start commands; POSIX output as in 0.7.0."""
    import session_settings as ss
    fixtures = HERE / 'fixtures/settings-0.7.0'
    data, orch_data = settings_fixture('/nonexistent-fixture/mono', '/nonexistent-fixture/orch/ws',
                                       '/nonexistent-fixture/skill')
    assert ss.render(data) == (fixtures / 'module.json').read_text(encoding='utf-8'), 'POSIX module output changed'
    assert ss.render(orch_data) == (fixtures / 'orchestrator.json').read_text(encoding='utf-8'), 'orchestrator changed'
    real = ss.is_windows
    ss.is_windows = lambda: True
    try:
        assert ss.abs_rule_path('C:\\a\\b') == '//c/a/b' and ss.abs_rule_path('D:/x') == '//d/x'
        for bad in ('\\\\server\\share\\x', '//server/share', 'relative\\x', 'C:x'):
            try:
                ss.abs_rule_path(bad)
            except ss.PathError:
                pass
            else:
                raise AssertionError(f'{bad} must be refused')
        win, win_orch = settings_fixture('C:\\projects\\mono', 'C:\\projects\\home-orch\\ws',
                                         'C:\\tools\\skill')
        for item in (win, win_orch):
            assert not ss.settings_errors(item), ss.settings_errors(item)
        perms = win['permissions']
        for rule in ('Read(//c/projects/mono/**)', 'Read(//c/projects/mono/apps/app/**)',
                     'Read(//c/projects/home-orch/ws/**)'):
            assert rule in perms['allow'], (rule, perms['allow'])
        assert 'Edit(//c/projects/home-orch/ws/**)' in perms['deny'], perms['deny']
        assert not any('\\' in r for r in perms['allow'] + perms['deny']), 'no backslashes in rules'
        allow = win_orch['permissions']['allow']
        for rule in ('Bash(python3 C:/tools/skill/scripts/orch.py *)', 'Bash(python C:/tools/skill/scripts/orch.py *)',
                     'Bash(py -3 C:/tools/skill/scripts/orch.py *)', 'Bash(py -3 C:/tools/skill/scripts/safe_edit.py *)'):
            assert rule in allow, (rule, allow)
        try:
            settings_fixture('C:\\projects\\mono', '\\\\server\\share\\ws', 'C:\\s')
        except ss.PathError as error:
            assert 'network (UNC) paths' in str(error)
        else:
            raise AssertionError('a UNC workspace must be refused')
        assert ss.apply_flags('cd C:\\r && claude --name s "p"', 'C:\\ws\\s.json', 'auto') == \
            'cd C:\\r && claude --permission-mode auto --settings C:/ws/s.json --name s "p"'
        refused = None
        try:
            orch.cmd_init(orch.build_parser().parse_args(['init', 'w', '--lang', 'en', '--sessions', 'local',
                                                          '--permission-mode', 'auto']))
        except orch.OrchError as error:
            refused = str(error)
        assert refused and '--shell powershell|bash' in refused, refused
    finally:
        ss.is_windows = real
    assert ss.shell_command('cd C:\\p\\m && claude -w a --name s "x && y"', 'powershell') == \
        'cd "C:/p/m"; claude -w a --name s "x && y"'
    assert ss.shell_command('cd /r && claude --name s "p"', 'bash') == 'cd /r && claude --name s "p"'
    # PowerShell start commands end to end (on any host).
    mono = make_monorepo(tmp / 'pwsh')
    home = tmp / 'pwsh/home'
    home.mkdir()
    git(home, 'init', '-q')
    out = run(home, 'init', 'win', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
              '--shell', 'powershell', '--module', f'db={mono}').stdout
    assert '"; claude --name win-coord --permission-mode auto --settings orchestration/settings/orchestrator.json' \
        in out, out
    ws = home / 'features/win'
    assert orch.parse_yaml((ws / 'orch.yaml').read_text(encoding='utf-8'))['shell'] == 'powershell'
    run(home, 'new-wp', 'db', 'schema')
    run(home, 'set', 'WP-DB-01', 'status', 'READY')
    dry = run(home, 'dispatch', 'WP-DB-01', '--dry-run').stdout
    assert f'cd "{mono}"; claude --permission-mode auto --settings ' in dry, dry
    safe_edit.replace_once(ws / 'orch.yaml', '\nshell: powershell\n', '\nshell: cmd\n')
    assert 'shell must be one of bash, powershell' in lint_errors(home)
    print('PASS windows paths: //c/... rules, UNC refused, python/py forms, PowerShell commands, POSIX as in 0.7.0')


REPORT_GH_STUB = """#!/usr/bin/env python3
import base64, json, os, sys
root = os.environ['GH_STUB_DIR']
args = sys.argv[1:]
with open(os.path.join(root, 'calls.log'), 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['issue', 'list']:
    print(open(os.path.join(root, 'issues.json')).read())
elif args[:2] == ['issue', 'create']:
    print('https://github.com/ITSalt/PepperSkills/issues/101')
elif args[:2] == ['issue', 'comment']:
    if os.path.exists(os.path.join(root, 'fail_comment')):
        sys.stderr.write('HTTP 502: bad gateway\\n')
        sys.exit(1)
    print('https://github.com/ITSalt/PepperSkills/issues/42#issuecomment-1')
elif args[:1] == ['api']:
    print(base64.b64encode(json.dumps({'version': '9.9.9'}).encode()).decode())
else:
    sys.exit(1)
"""


def test_report(tmp):
    """3e: anonymized plugin defect reports; Issue only after the owner's yes; duplicates get a comment."""
    import plugin_report
    mono = make_monorepo(tmp / 'report')
    git(mono, 'remote', 'set-url', 'origin', 'https://github.com/acme-hidden/quietmono.git')
    stub = tmp / 'report/stub'
    (stub / 'bin').mkdir(parents=True)
    (stub / 'bin/gh').write_text(REPORT_GH_STUB, encoding='utf-8')
    (stub / 'bin/gh').chmod(0o755)
    (stub / 'issues.json').write_text('[]', encoding='utf-8')
    gh_env = {'ORCH_NO_GH': '', 'GH_STUB_DIR': str(stub), 'PATH': f'{stub / "bin"}{os.pathsep}{os.environ["PATH"]}'}
    home = tmp / 'report/home'
    home.mkdir()
    git(home, 'init', '-q')
    git(home, 'remote', 'add', 'origin', 'https://git.hushcorp.example/hushowner/homerepo.git')
    (home / '.private-terms.local').write_text('# private\nhushterm\n', encoding='utf-8')
    run(home, 'init', 'quietprog', '--lang', 'ru', '--sessions', 'local', '--permission-mode', 'auto', '--tag', 'QPX',
        '--repo', f'quietrepo={mono}', '--area', 'billzone=quietrepo:apps/app/**')
    ws = home / 'features/quietprog'
    safe_edit.replace_once(ws / 'orch.yaml', '    session: quietprog-billzone\n',
                           '    session: quietprog-billzone\n    web_urls: {test: https://stage.hidden-shop.example}\n')
    token = 'gh' + 'p_' + 'A' * 36
    log = tmp / 'report/out.log'
    log.write_text('\n'.join([
        f'$ python3 orch.py settings all   (in {ws.resolve()})',
        f'Traceback: orch: settings billzone: error in {mono}/apps/app for quietprog-billzone',
        f'origin https://github.com/acme-hidden/quietmono.git, QPX, quietprog, {Path.home()}/notes, hushterm',
        f'contact owner@hidden-shop.example token {token} host stage.hidden-shop.example',
        'DB_PASSWORD=plainvalue123 STRIPE_KEY: sk_live_abcdef123456 url acme-hidden%2Fquietmono',
        'home origin https://git.hushcorp.example/hushowner/homerepo.git by hushowner',
    ] + [f'line {i}' for i in range(40)]), encoding='utf-8')
    out = run(home, 'report', '--check', '--command', f'python3 orch.py settings all --workspace {ws}', '--log', str(log),
              '--expected-actual', 'Expected settings for billzone; got an error.', '--workaround=dispatch with --no-settings').stdout
    record = (ws / 'bugs/PLUGIN-BUG-1.md').read_text(encoding='utf-8')
    issue = (ws / 'bugs/PLUGIN-BUG-1.issue.md').read_text(encoding='utf-8')
    body = record + issue + out
    for secret in ('quietprog', 'QPX', 'billzone', 'quietrepo', 'acme-hidden', 'quietmono', 'hidden-shop', 'hushterm',
                   str(Path.home()), str(mono), str(ws), token, 'owner@', 'plainvalue123', 'sk_live_abcdef',
                   'hushowner', 'hushcorp', 'homerepo'):
        assert secret.lower() not in body.lower(), (secret, body)
    assert '<module-1>' in issue and '<repo-1>' in issue and '<workspace>' in issue and '[redacted]' in issue, issue
    assert 'line 23' in record and 'line 26' not in record, 'first 30 lines only'
    assert '## Вывод (первые строки, обезличен)' in record and '### Plugin and version' in issue
    assert 'Publish this anonymized report' in out and 'fingerprint: pepper-orchestrator' in out, out
    traces = next((p / 'scripts/check-private-traces.py' for p in HERE.parents
                   if (p / 'scripts/check-private-traces.py').is_file()), None)
    if traces:  # inside the PepperSkills repository (not in an unpacked package): the repository guard
        import importlib.util
        spec = importlib.util.spec_from_file_location('traces', traces)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        scan = tmp / 'report/scan'
        scan.mkdir()
        git(scan, 'init', '-q')
        (scan / 'issue.md').write_text(issue, encoding='utf-8')
        git(scan, 'add', '-A')
        assert guard.findings(scan, terms=['hushterm']) == [], guard.findings(scan, terms=['hushterm'])
    refused = run(home, 'report', '--apply', ok=False).stderr
    assert 'Publish PLUGIN-BUG-1' in refused and '--confirmed' in refused, refused
    manual = run(home, 'report', '--apply', '--confirmed').stdout
    assert 'No gh here' in manual and 'create_issue owner=ITSalt repo=PepperSkills' in manual, manual
    assert '| Issue | — |' in (ws / 'bugs/PLUGIN-BUG-1.md').read_text(encoding='utf-8')
    sent = run(home, 'report', '--apply', '--confirmed', extra_env=gh_env).stdout
    assert 'new Issue: https://github.com/ITSalt/PepperSkills/issues/101' in sent, sent
    calls = [json.loads(line) for line in (stub / 'calls.log').read_text(encoding='utf-8').splitlines()]
    assert calls[0][:4] == ['issue', 'list', '--repo', 'ITSalt/PepperSkills'] and '--state' in calls[0], calls
    create = calls[1]
    assert create[:4] == ['issue', 'create', '--repo', 'ITSalt/PepperSkills'], create
    assert create[create.index('--title') + 1].startswith('[pepper-orchestrator '), create
    assert [create[i + 1] for i, a in enumerate(create) if a == '--label'] == ['bug', 'from-agent', 'needs-triage']
    assert '| Issue | https://github.com/ITSalt/PepperSkills/issues/101 |' in \
        (ws / 'bugs/PLUGIN-BUG-1.md').read_text(encoding='utf-8')
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'PLUGIN-BUG-1 sent to ITSalt/PepperSkills' in status and 'FYI, no action needed' in status
    assert 'already sent' in run(home, 'report', '--apply', '--confirmed', '--id', 'PLUGIN-BUG-1', ok=False).stderr
    # A duplicate: a comment with the environment facts, no new Issue.
    run(home, 'report', '--check', '--log', str(log), '--title', 'settings fail again')
    (stub / 'issues.json').write_text(json.dumps([{'number': 42, 'title': 'x', 'url': 'u', 'state': 'OPEN'}]),
                                      encoding='utf-8')
    dup = run(home, 'report', '--apply', '--confirmed', extra_env=gh_env).stdout
    assert 'comment on #42' in dup, dup
    calls = [json.loads(line) for line in (stub / 'calls.log').read_text(encoding='utf-8').splitlines()]
    assert calls[-1][:3] == ['issue', 'comment', '42'] and not any(c[:2] == ['issue', 'create'] for c in calls[2:])
    # bug_reports: auto needs a recorded decision; with it, --apply needs no --confirmed.
    config = ws / 'orch.yaml'
    safe_edit.replace_once(config, 'push_after_milestone: false', 'push_after_milestone: false\nbug_reports: auto')
    assert 'bug_reports: auto needs bug_reports_decision' in lint_errors(home)
    run(home, 'decide', 'D', 'Plugin defect reports are published without asking')
    safe_edit.replace_once(config, 'bug_reports: auto', 'bug_reports: auto\nbug_reports_decision: D-1')
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    run(home, 'report', '--check', '--log', str(log), '--title', 'third')
    (stub / 'issues.json').write_text('[]', encoding='utf-8')
    assert 'new Issue' in run(home, 'report', '--apply', extra_env=gh_env).stdout
    status_out = run(home, 'report', '--status', extra_env=gh_env).stdout
    assert 'PLUGIN-BUG-1: Issue https://' in status_out and 'update available: pepper-orchestrator' in status_out
    assert 'SECURITY.md' in run(home, 'report', '--security').stdout
    assert plugin_report.fingerprint('p', '1.0', 'orch: <module-1> error [redacted]') == 'p 1.0 orch: error'
    # M1: the exception line of a traceback, not its header; volatile parts removed.
    first = ['Traceback (most recent call last):', '  File "orch.py", line 10, in main', "KeyError: 'shell'"]
    second = ['Traceback (most recent call last):', '  File "orch.py", line 99, in run', 'ValueError: bad sha']
    fps = {plugin_report.fingerprint('p', '1', plugin_report.first_error_line(x)) for x in (first, second)}
    assert len(fps) == 2 and "p 1 KeyError: shell" in fps, fps
    assert plugin_report.fingerprint('p', '1', '2026-09-30 10:22Z WP-APP-01 dispatch refused at abc1234def') == \
        plugin_report.fingerprint('p', '1', '2026-10-01 08:00Z WP-DB-07 dispatch refused at 9876543fed'), 'volatile parts'
    assert plugin_report.first_error_line(['all good', 'still fine']) == ''
    assert plugin_report.search_query('p 1.0 -x orch: error') == '"p 1.0 x orch error"'
    # L4 d: environment, settings, key files and KEY=value files are never attached.
    for name, content in (('.env.local', 'A=1\n'), ('orch.yaml', 'x: 1\n'), ('settings.local.json', '{}'),
                          ('id.pem', 'x'), ('vars.txt', 'A=1\nB=2\nnote\n')):
        bad = tmp / 'report-logs' / name  # outside the workspace tree: a stray orch.yaml would be found as one
        bad.parent.mkdir(exist_ok=True)
        bad.write_text(content, encoding='utf-8')
        assert '--log refused' in run(home, 'report', '--check', '--log', str(bad), ok=False).stderr, name
    # L3: a failed comment leaves no file behind; the retry works. L7: an open duplicate is preferred.
    (stub / 'issues.json').write_text(json.dumps([{'number': 7, 'title': 'old', 'url': 'u7', 'state': 'CLOSED'},
                                                  {'number': 42, 'title': 'x', 'url': 'u42', 'state': 'OPEN'}]),
                                      encoding='utf-8')
    run(home, 'report', '--check', '--log', str(log), '--title', 'fourth')
    (stub / 'fail_comment').write_text('x', encoding='utf-8')
    assert 'gh failed: HTTP 502' in run(home, 'report', '--apply', extra_env=gh_env, ok=False).stderr
    (stub / 'fail_comment').unlink()
    again = run(home, 'report', '--apply', extra_env=gh_env).stdout
    assert 'comment on #42 (open, u42)' in again, again
    assert 'comment on #42 (open' in (ws / 'status.md').read_text(encoding='utf-8')
    calls = [json.loads(line) for line in (stub / 'calls.log').read_text(encoding='utf-8').splitlines()]
    searches = [c[c.index('--search') + 1] for c in calls if c[:2] == ['issue', 'list']]
    assert all(s.startswith('"') and s.endswith('"') for s in searches), searches
    print('PASS report: anonymized record and Issue text, guard clean, owner yes required, stub gh create/comment, '
          'auto by decision, no-gh instructions, update line')


DELIVER_GH_STUB = """#!/usr/bin/env python3
import json, os, sys
root = os.environ['GH_STUB_DIR']
args = sys.argv[1:]
with open(os.path.join(root, 'calls.log'), 'a') as log:
    log.write(json.dumps(args) + '\\n')
def load(name):
    return open(os.path.join(root, name)).read()
if args[:2] == ['pr', 'view']:
    print(load('pr.json'))
elif args[:2] == ['pr', 'checks']:
    print(load('checks.json'))
elif args[:2] == ['pr', 'merge']:
    if os.path.exists(os.path.join(root, 'no_merge_commit')):
        print('Merged pull request')
        sys.exit(0)
    if os.path.exists(os.path.join(root, 'fail_merge')):
        sys.stderr.write('GraphQL: At least 1 approving review is required\\n')
        sys.exit(1)
    pr = json.loads(load('pr.json'))
    pr['state'] = 'MERGED'
    pr['mergeCommit'] = {'oid': load('merge_sha.txt').strip()}
    open(os.path.join(root, 'pr.json'), 'w').write(json.dumps(pr))
    print('Merged pull request #%s' % pr['number'])
elif args[:2] == ['run', 'list']:
    print(load('runs.json'))
elif args[:2] == ['run', 'watch']:
    sys.exit(int(load('watch_rc.txt').strip() or 0))
else:
    sys.exit(3)
"""


def test_deliver(tmp):
    """3c: trusted delivery with a stub gh (view, checks, merge, run) and stub commands."""
    mono = make_monorepo(tmp / 'deliver')
    stub = tmp / 'deliver/stub'
    (stub / 'bin').mkdir(parents=True)
    (stub / 'bin/gh').write_text(DELIVER_GH_STUB, encoding='utf-8')
    (stub / 'bin/gh').chmod(0o755)
    head = git(mono, 'rev-parse', 'HEAD').strip()
    merge_sha = 'ab' * 20

    def pr(wp, number):
        (stub / 'pr.json').write_text(json.dumps({
            'number': number, 'url': f'https://github.com/example/mono/pull/{number}', 'state': 'OPEN',
            'headRefOid': head, 'mergeable': 'MERGEABLE', 'baseRefName': 'main',
            'title': f'[SHOP] {wp}: work', 'mergeCommit': None}), encoding='utf-8')
    pr('WP-APP-01', 5)
    (stub / 'checks.json').write_text(json.dumps([{'name': 'ubuntu', 'bucket': 'pass'}]), encoding='utf-8')
    (stub / 'merge_sha.txt').write_text(merge_sha, encoding='utf-8')
    (stub / 'runs.json').write_text(json.dumps([{'databaseId': 9, 'status': 'completed', 'conclusion': 'success',
                                                 'headBranch': 'main', 'url': 'https://example.invalid/runs/9'}]),
                                    encoding='utf-8')
    (stub / 'watch_rc.txt').write_text('0', encoding='utf-8')
    env = {'ORCH_NO_GH': '', 'GH_STUB_DIR': str(stub), 'ORCH_POLL_INTERVAL': '0',
           'PATH': f'{stub / "bin"}{os.pathsep}{os.environ["PATH"]}'}
    home = tmp / 'deliver/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'shop', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto',
        '--repo', f'mono={mono}', '--area', 'app=mono:apps/app/**')
    ws = home / 'features/shop'
    config = ws / 'orch.yaml'
    safe_edit.replace_once(config, '    checks: []\n', '    checks: []\n    merge_method: squash\n'
                           '    deploy_workflows: [deploy.yml]\n    verify_test: ["echo stand ok"]\n'
                           '    rollback_test: "echo rollback {previous_sha}"\n')
    git(mono, 'remote', 'set-url', 'origin', 'https://github.com/example/mono.git')
    # The hosted URL resolves to the local bare remote: no fetch ever reaches the network.
    git(mono, 'config', f'url.{tmp / "deliver/mono.git"}.insteadOf', 'https://github.com/example/mono.git')
    for slug in ('orders', 'cart', 'fees', 'tax', 'ship'):
        run(home, 'new-wp', 'app', slug)
    for n, wp in enumerate(('WP-APP-01', 'WP-APP-02', 'WP-APP-03', 'WP-APP-04', 'WP-APP-05'), 5):
        run(home, 'set', wp, 'pr', f'https://github.com/example/mono/pull/{n}')
        run(home, 'set', wp, 'status', 'REVIEW')
    # Default (and every workspace before 0.9.0): the owner delivers.
    owner = run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env, ok=False).stderr
    assert 'delivery is done by the owner' in owner and \
        'gh pr merge https://github.com/example/mono/pull/5 --squash --delete-branch' in owner, owner
    assert 'decision' in run(home, 'delivery', 'set', 'merge', 'orchestrator', ok=False).stderr
    run(home, 'decide', 'D', 'The orchestrator merges accepted packages and runs the stand')
    run(home, 'delivery', 'set', 'merge', 'orchestrator', '--decision', 'D-1')
    run(home, 'delivery', 'set', 'stand', 'orchestrator', '--decision', 'D-1')
    parsed = orch.parse_yaml(config.read_text(encoding='utf-8'))['delivery']
    assert parsed == {'enabled_by': 'D-1', 'merge': 'orchestrator', 'stand': 'orchestrator'}, parsed
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, '  enabled_by: D-1\n', '')
    assert 'orchestrator needs enabled_by: D-n' in lint_errors(home)
    invalid = run(home, 'deliver', '--apply', 'WP-APP-01', extra_env=env, ok=False).stderr
    assert 'delivery configuration is invalid' in invalid, invalid  # M1: never delivers on a lint error
    config.write_text(original, encoding='utf-8')
    safe_edit.replace_once(config, '    merge_method: squash\n', '    merge_method: admin\n')
    admin = run(home, 'deliver', '--apply', 'WP-APP-01', extra_env=env, ok=False).stderr
    assert 'merge_method must be merge, squash or rebase' in admin, admin
    config.write_text(original, encoding='utf-8')
    assert run(home, 'lint').returncode == 0, lint_errors(home)
    # G1: not accepted; G2: accepted at another SHA; then every gate green.
    g1 = run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env, ok=False).stdout
    assert '| G1 | RED |' in g1, g1
    review = ws / 'reports/wp-app-01-review.md'
    review.parent.mkdir(exist_ok=True)
    review.write_text('# Review\n\n**Decision: ACCEPTED**\n', encoding='utf-8')
    run(home, 'accept', 'WP-APP-01', 'c' * 40, '--report', 'reports/wp-app-01-review.md')
    g2 = run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env, ok=False).stdout
    assert '| G2 | RED |' in g2 and 'new commits need a new review' in g2, g2
    run(home, 'accept', 'WP-APP-01', head, '--report', 'reports/wp-app-01-review.md')
    assert f'pull/5 (accepted {head[:10]})' in (ws / 'status.md').read_text(encoding='utf-8')
    status_text = (ws / 'status.md').read_text(encoding='utf-8')  # L1: sequential without the queue table
    (ws / 'status.md').write_text(status_text.replace('<!-- orch:merge -->', '<!-- no merge table -->'), encoding='utf-8')
    assert 'run orch.py upgrade' in run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env, ok=False).stdout
    (ws / 'status.md').write_text(status_text, encoding='utf-8')
    g5 = run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env, ok=False).stdout
    assert '| G5 | RED |' in g5 and 'merge queue' in g5, g5  # sequential policy: the queue first
    run(home, 'merge', 'add', 'WP-APP-01', '--pr', 'https://github.com/example/mono/pull/5')
    green = run(home, 'deliver', '--check', 'WP-APP-01', extra_env=env).stdout
    assert 'RED' not in green and '| G10 | green |' in green, green
    applied = run(home, 'deliver', '--apply', 'WP-APP-01', extra_env=env).stdout
    assert f'merged (squash) at {merge_sha[:10]}' in applied and 'VERIFIED_TEST' in applied, applied
    calls = [json.loads(line) for line in (stub / 'calls.log').read_text(encoding='utf-8').splitlines()]
    assert ['pr', 'merge', '5', '--repo', 'example/mono', '--squash', '--delete-branch'] in calls, calls
    assert any(c[:2] == ['run', 'watch'] for c in calls) and not any('--admin' in c for c in calls)
    assert all(tuple(c[:2]) in {('pr', 'view'), ('pr', 'checks'), ('pr', 'merge'), ('run', 'list'), ('run', 'watch')}
               for c in calls), 'no command outside the delivery commands'
    status = (ws / 'status.md').read_text(encoding='utf-8')
    assert 'WP-APP-01: MERGED -> VERIFIED_TEST' in status, status
    ledger = (ws / 'release/deliveries.md').read_text(encoding='utf-8')
    assert f'| WP-APP-01 | https://github.com/example/mono/pull/5 | {merge_sha[:12]} |' in ledger and '| PASS |' in ledger
    # A failed stand run: hold, defect, rollback, the queue stops.
    pr('WP-APP-02', 6)
    review2 = ws / 'reports/wp-app-02-review.md'
    review2.write_text('# Review\n', encoding='utf-8')
    run(home, 'accept', 'WP-APP-02', head, '--report', 'reports/wp-app-02-review.md')
    run(home, 'merge', 'add', 'WP-APP-02')
    (stub / 'watch_rc.txt').write_text('1', encoding='utf-8')
    failed = run(home, 'deliver', '--apply', 'WP-APP-02', extra_env=env, ok=False).stderr
    assert 'delivery is on hold' in failed and 'REVISE text for the module session' in failed, failed
    assert 'WP-APP-02' in orch.parse_yaml(config.read_text(encoding='utf-8'))['delivery']['hold']
    assert list((ws / 'bugs').glob('BUG-*-verify-wp-app-02-test.md')), 'defect written'
    assert 'hold; ' in (ws / 'release/deliveries.md').read_text(encoding='utf-8')
    pr('WP-APP-03', 7)
    review3 = ws / 'reports/wp-app-03-review.md'
    review3.write_text('# Review\n', encoding='utf-8')
    run(home, 'accept', 'WP-APP-03', head, '--report', 'reports/wp-app-03-review.md')
    run(home, 'merge', 'add', 'WP-APP-03')
    stopped = run(home, 'deliver', '--apply', 'WP-APP-03', extra_env=env, ok=False)
    assert '| G10 | RED |' in stopped.stdout and 'hold' in stopped.stdout, stopped.stdout
    assert '| G5 | RED |' in stopped.stdout and 'not VERIFIED_TEST' in stopped.stdout
    assert 'WP-APP-03: delivery refused' in (ws / 'status.md').read_text(encoding='utf-8')
    run(home, 'unhold', 'analysed: flaky runner, rerun is green')
    assert 'hold' not in orch.parse_yaml(config.read_text(encoding='utf-8'))['delivery']
    # GitHub refuses the merge: an owner item, never a bypass.
    (stub / 'watch_rc.txt').write_text('0', encoding='utf-8')
    (stub / 'fail_merge').write_text('x', encoding='utf-8')
    bad = run(home, 'deliver', '--apply', 'WP-APP-03', '--after-failure', 'yes', extra_env=env, ok=False).stderr
    assert '--after-failure takes the owner decision' in bad, bad  # M2
    refused = run(home, 'deliver', '--apply', 'WP-APP-03', '--after-failure', 'D-1', extra_env=env, ok=False).stderr
    assert 'GitHub refused the merge' in refused and 'owner item opened' in refused, refused
    assert 'R-1' in run(home, 'queue').stdout
    (stub / 'fail_merge').unlink()
    # G9: a package with a specification reference needs "graph: checked" in its review report.
    fill_header(ws / 'work-packages/WP-APP-03-fees.md', 'Specification', 'UC-12, FR-4')
    g9 = run(home, 'deliver', '--check', 'WP-APP-03', '--after-failure', 'D-1', extra_env=env, ok=False).stdout
    assert '| G9 | RED |' in g9 and 'graph: checked' in g9, g9
    review3.write_text('# Review\n\ngraph: checked (status command output in the PR report)\n', encoding='utf-8')
    assert '| G9 | green |' in run(home, 'deliver', '--check', 'WP-APP-03', '--after-failure', 'D-1', extra_env=env).stdout
    # M3: a deploy run still in progress at verification: exit 2, MERGED, no hold, no rollback.
    run(home, 'deliver', '--apply', 'WP-APP-03', '--after-failure', 'D-1', extra_env=env)  # green again
    pr('WP-APP-04', 8)
    (ws / 'reports/wp-app-04-review.md').write_text('# Review\n', encoding='utf-8')
    run(home, 'accept', 'WP-APP-04', head, '--report', 'reports/wp-app-04-review.md')
    run(home, 'merge', 'add', 'WP-APP-04')
    (stub / 'runs.json').write_text(json.dumps([{'databaseId': 10, 'status': 'in_progress', 'conclusion': None,
                                                 'headBranch': 'main', 'url': 'u10'}]), encoding='utf-8')
    waiting = run(home, 'deliver', '--apply', 'WP-APP-04', '--after-failure', 'D-1', extra_env=env, ok=False)
    assert waiting.returncode == 2 and 'waits for the deploy run' in waiting.stderr, waiting.stderr
    assert 'hold' not in orch.parse_yaml(config.read_text(encoding='utf-8'))['delivery']
    assert '| MERGED |' in next(l for l in (ws / 'status.md').read_text(encoding='utf-8').split('\n')
                                if l.startswith('| [WP-APP-04]'))
    assert 'after failure by D-1' in (ws / 'release/deliveries.md').read_text(encoding='utf-8')
    (stub / 'runs.json').write_text(json.dumps([{'databaseId': 9, 'status': 'completed', 'conclusion': 'success',
                                                 'headBranch': 'main', 'url': 'u9'}]), encoding='utf-8')
    # L4: GitHub has not reported the merge commit: stop before the stand, one ledger row.
    pr('WP-APP-05', 9)
    (ws / 'reports/wp-app-05-review.md').write_text('# Review\n', encoding='utf-8')
    run(home, 'accept', 'WP-APP-05', head, '--report', 'reports/wp-app-05-review.md')
    run(home, 'merge', 'add', 'WP-APP-05')
    (stub / 'no_merge_commit').write_text('x', encoding='utf-8')
    unknown = run(home, 'deliver', '--apply', 'WP-APP-05', '--after-failure', 'D-1', extra_env={**env, 'ORCH_MERGE_POLLS': '2'},
                  ok=False).stderr
    assert 'merge commit is unknown yet' in unknown, unknown
    assert 'merge SHA unknown: stand not started' in (ws / 'release/deliveries.md').read_text(encoding='utf-8')
    (stub / 'no_merge_commit').unlink()
    # lint: prod by the orchestrator needs merge by the orchestrator; a hold is the first warning.
    original = config.read_text(encoding='utf-8')
    safe_edit.replace_once(config, '  merge: orchestrator\n', '  merge: owner\n  prod: orchestrator\n')
    assert 'delivery.prod: orchestrator needs delivery.merge: orchestrator' in lint_errors(home)
    config.write_text(original, encoding='utf-8')
    run(home, 'hold', 'owner stop')
    assert 'delivery is on hold: owner stop' in run(home, 'lint').stderr
    run(home, 'unhold', 'owner resumed')
    # The orchestrator's settings follow the delivery levels.
    run(home, 'settings', 'orchestrator')
    rules = json.loads((ws / 'orchestration/settings/orchestrator.json').read_text(encoding='utf-8'))['permissions']
    assert 'Bash(gh pr merge *)' in rules['deny'] and not any('pr merge' in r for r in rules['allow']), rules
    assert 'Bash(echo rollback *)' in rules['allow'] and 'Bash(echo stand ok)' in rules['allow'], rules['allow']
    print('PASS deliver: owner default, delivery set by D-n, lint, gates G1/G2/G5/G10, merge with the configured '
          'method, ledger, run watch, verify, hold on failure, unhold, GitHub refusal -> owner item, settings')


def test_encoding_and_pr_cell(tmp):
    """0.9.1: UTF-8 output through a pipe under a non-UTF-8 locale, unreadable workflows refused, PR cells."""
    import io
    import threading
    import streams
    # Illustration of CPython behaviour, not a guard of the fix (the fix is guarded by the pipe checks
    # below): on Windows subprocess reads pipes in a reader thread; a decoding error kills only that
    # thread and communicate() returns None (#20).
    raw = io.TextIOWrapper(io.BytesIO('Проверка деплоя'.encode('utf-8')), encoding='cp1252')
    buffer = []
    thread = threading.Thread(target=lambda: buffer.append(raw.read()))
    hook, threading.excepthook = threading.excepthook, lambda args: None
    thread.start()
    thread.join()
    threading.excepthook = hook
    assert buffer == [], 'the reader thread dies; communicate() would return stdout=None'
    try:
        streams.parse_push_trigger(None, 'ci.yml')
    except streams.DeployFormError as error:
        assert 'could not be read' in str(error)
    else:
        raise AssertionError('None must be a refusal')
    real = streams.workflow_texts
    streams.workflow_texts = lambda root, ref: {'ci.yml': None, 'other.yml': 'on: [pull_request]\n'}
    try:
        candidates, _, refusals, any_dir = streams.deploy_safe_dirs(tmp, 'orch/x', 'x', 'HEAD')
    finally:
        streams.workflow_texts = real
    assert refusals and candidates == [] and not any_dir, (candidates, refusals)
    # A repository with Russian text in a workflow and in a commit message, a Russian workspace.
    mono = make_monorepo(tmp / 'enc')
    with_workflow(mono, "# Выкладка стенда\non:\n  push:\n    paths-ignore: ['docs/**']\njobs: {}\n")
    (mono / 'apps/app/src/page.tsx').write_text('// страница\n', encoding='utf-8')
    git(mono, 'commit', '-qam', 'Правка страницы: кириллица в сообщении')
    git(mono, 'push', '-q', 'origin', 'main')
    clone = tmp / 'enc/clone'
    git(tmp, 'clone', '-q', str(tmp / 'enc/mono.git'), str(clone))
    git(clone, 'config', f'url.{tmp / "enc/mono.git"}.insteadOf', 'https://github.com/example/mono.git')
    git(clone, 'remote', 'set-url', 'origin', 'https://github.com/example/mono.git')
    run(clone, 'init', 'enc', '--lang', 'ru', '--sessions', 'local', '--permission-mode', 'auto', '--in-repo', 'app',
        '--area', 'shop=app:apps/app/**')
    run(clone, 'owner', 'add', 'P', 'Нужен ли экспорт заказов? (а) да (б) нет; рекомендую (б)')
    run(clone, 'new-wp', 'shop', 'orders', '--title', 'Заказы')
    wt = branch_with(clone, 'feature/wp-shop-01-orders', ['apps/app/src/page.tsx'])
    git(wt, 'commit', '-q', '--allow-empty', '-m', 'Пакет: заказы — готово')
    git(wt, 'push', '-q', 'origin', 'feature/wp-shop-01-orders')
    env = {**os.environ, **GIT_ENV, 'PYTHONIOENCODING': 'cp1252', 'LC_ALL': 'C', 'LANG': 'C', 'PYTHONUTF8': '0'}
    env.pop('ORCH_WORKSPACE', None)
    for args in (['queue'], ['lint'], ['ready'], ['overlap', '--planned'], ['review-start', 'WP-SHOP-01', '--no-fetch']):
        result = subprocess.run([*ORCH, *args], cwd=clone, env=env, capture_output=True)
        assert result.returncode == 0, (args, result.stderr.decode('utf-8', 'replace'))
        out = (result.stdout + result.stderr).decode('utf-8')  # strict: valid UTF-8
        if args == ['queue']:
            assert 'Нужен ли экспорт заказов' in out, out
    # PR cells (#24): a URL or a number expanded by origin; anything else refused.
    ws = clone / 'docs/orchestration/enc'
    run(clone, 'set', 'WP-SHOP-01', 'pr', '#87')
    assert '| https://github.com/example/mono/pull/87 |' in (ws / 'status.md').read_text(encoding='utf-8')
    assert 'takes a pull request URL or number' in run(clone, 'set', 'WP-SHOP-01', 'pr', 'мусор', ok=False).stderr
    run(clone, 'new-wp', 'shop', 'cart')
    run(clone, 'merge', 'add', 'WP-SHOP-02', '--pr', 'https://github.com/example/mono/pull/88')
    assert '| https://github.com/example/mono/pull/88 |' in (ws / 'status.md').read_text(encoding='utf-8')
    # A cell written before 0.9.1 ("#87") still resolves for verify.
    status = (ws / 'status.md').read_text(encoding='utf-8')
    (ws / 'status.md').write_text(status.replace('| https://github.com/example/mono/pull/87 |', '| #87 |'),
                                  encoding='utf-8')
    orch_ws = orch.Workspace(ws)
    _, module, _ = orch.wp_context(orch_ws, 'WP-SHOP-01')
    assert orch.pr_url('#87', module.repo) == 'https://github.com/example/mono/pull/87'
    assert orch.pr_url('#87 (accepted abcdef1)', module.repo) == 'https://github.com/example/mono/pull/87'
    assert orch.pr_url('3 commits behind', module.repo) is None, 'a number must be the whole cell (L1)'
    # M1/I3: a URL with a tail is normalized before anything is written; a bad value writes nothing.
    reports_before = sorted(p.name for p in (ws / 'reports').iterdir())
    bad = run(clone, 'review-start', 'WP-SHOP-01', '--no-fetch', '--round', '2', '--pr', 'see the PR', ok=False)
    assert 'takes a pull request URL or number' in bad.stderr and \
        sorted(p.name for p in (ws / 'reports').iterdir()) == reports_before, 'no partial state'
    run(clone, 'review-start', 'WP-SHOP-01', '--no-fetch', '--round', '2',
        '--pr', 'https://github.com/example/mono/pull/87/files?w=1')
    status_now = (ws / 'status.md').read_text(encoding='utf-8')
    assert '| https://github.com/example/mono/pull/87 |' in status_now and '/files' not in status_now
    report2 = next((ws / 'reports').glob('wp-shop-01-review-*-r2.md')).read_text(encoding='utf-8')
    assert 'https://github.com/example/mono/pull/87' in report2 and '/files' not in report2
    # L2: merge add validates first.
    run(clone, 'new-wp', 'shop', 'tax')
    rows_before = (ws / 'status.md').read_text(encoding='utf-8').count('| queued |')
    assert 'takes a pull request URL' in run(clone, 'merge', 'add', 'WP-SHOP-03', '--pr', 'draft', ok=False).stderr
    assert (ws / 'status.md').read_text(encoding='utf-8').count('| queued |') == rows_before
    # M2: accept never refuses because of an older free-text cell; the journal line is written.
    head = git(clone, 'rev-parse', 'origin/main').strip()
    text = (ws / 'status.md').read_text(encoding='utf-8')
    row = next(l for l in text.split('\n') if l.startswith('| [WP-SHOP-03]'))
    cells = row.split(' | ')
    cells[5] = 'PR https://github.com/example/mono/pull/90 \\| draft'
    (ws / 'status.md').write_text(text.replace(row, ' | '.join(cells)), encoding='utf-8')
    run(clone, 'set', 'WP-SHOP-03', 'status', 'REVIEW')
    (ws / 'reports/wp-shop-03-review.md').write_text('# Review\n', encoding='utf-8')
    run(clone, 'accept', 'WP-SHOP-03', head, '--report', 'reports/wp-shop-03-review.md')
    after = (ws / 'status.md').read_text(encoding='utf-8')
    assert f'WP-SHOP-03: accepted at {head}' in after, 'journal line written'
    assert f'| https://github.com/example/mono/pull/90 (accepted {head[:10]}) |' in after
    assert orch.accepted_revision(orch.Workspace(ws), 'WP-SHOP-03')[0] == head
    stub = tmp / 'enc/stub'
    (stub / 'bin').mkdir(parents=True)
    (stub / 'bin/gh').write_text(GH_STUB, encoding='utf-8')
    (stub / 'bin/gh').chmod(0o755)
    head = git(clone, 'rev-parse', 'origin/main').strip()
    (stub / 'pr.json').write_text(json.dumps({'state': 'MERGED', 'mergeCommit': {'oid': head}}), encoding='utf-8')
    (stub / 'runs.json').write_text('[]', encoding='utf-8')
    safe_edit.replace_once(ws / 'orch.yaml', '    checks: []\n', '    checks: []\n    verify_test: ["true"]\n')
    run(clone, 'set', 'WP-SHOP-01', 'status', 'MERGED')
    gh_env = {'ORCH_NO_GH': '', 'GH_STUB_DIR': str(stub), 'PATH': f'{stub / "bin"}{os.pathsep}{os.environ["PATH"]}'}
    assert 'PASS' in run(clone, 'verify', 'WP-SHOP-01', '--env', 'test', extra_env=gh_env).stdout
    assert 'pr view https://github.com/example/mono/pull/87' in (stub / 'calls.log').read_text(encoding='utf-8')
    local = make_monorepo(tmp / 'enc-local')
    home = tmp / 'enc-local/home'
    home.mkdir()
    git(home, 'init', '-q')
    run(home, 'init', 'loc', '--lang', 'en', '--sessions', 'local', '--permission-mode', 'auto', '--module', f'db={local}')
    run(home, 'new-wp', 'db', 'schema')
    assert 'cannot be expanded' in run(home, 'set', 'WP-DB-01', 'pr', '#5', ok=False).stderr
    # M3: the loopback git proxy of a cloud session is not a forge: no plausible wrong URL.
    git(local, 'remote', 'set-url', 'origin', 'http://proxy@127.0.0.1:43123/git/example/mono')
    assert orch.pr_from_number(orch.streams.Repo({'id': 'r', 'path': str(local)}), 5) is None
    assert 'cannot be expanded' in run(home, 'set', 'WP-DB-01', 'pr', '#5', ok=False).stderr
    assert not orch.forge_host('10.0.0.5') and orch.forge_host('github.com') and orch.forge_host('git.example.org')
    # L4: a workflow that is not UTF-8 is unreadable: refused, no candidate with a replaced character.
    bad_repo = make_monorepo(tmp / 'enc-latin')
    wf = bad_repo / '.github/workflows/deploy.yml'
    wf.parent.mkdir(parents=True)
    wf.write_bytes("# d\xe9ploiement\non:\n  push:\n    paths-ignore: ['caf\xe9/**']\njobs: {}\n".encode('latin-1'))
    git(bad_repo, 'add', '-A')
    git(bad_repo, 'commit', '-qm', 'latin-1 workflow')
    candidates, _, refusals, _ = streams.deploy_safe_dirs(bad_repo, 'orch/x', 'x', 'HEAD')
    assert refusals and 'not valid UTF-8' in refusals[0] and candidates == [], (candidates, refusals)
    # L3: the self-test reads child output as UTF-8 itself (it runs the install checks on Windows too).
    assert ('text' + '=True') not in Path(__file__).read_text(encoding='utf-8')
    print('PASS encoding and PR cell: UTF-8 through a pipe under cp1252/C, unreadable workflow refused, #87 expanded')


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
        test_models(tmp)
        test_local_cloud_matrix(tmp)
        test_settings(tmp)
        test_deploy_override_first_candidate(tmp)
        test_verify(tmp)
        test_windows_paths(tmp)
        test_report(tmp)
        test_deliver(tmp)
        test_encoding_and_pr_cell(tmp)
    print('PASS pepper-orchestrator selftest')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
