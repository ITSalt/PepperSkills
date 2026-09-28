#!/usr/bin/env python3
"""Offline self-test for orch.py and safe_edit.py (standard library + git only)."""
import json
import os
from pathlib import Path
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
    run(repo, 'init', 'demo', ok=False)  # never over an existing workspace
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
    (ws / 'reports/empty.md').write_text('token = ghp_' + 'a' * 36 + '\n', encoding='utf-8')
    expect('looks like a secret')
    (ws / 'reports/empty.md').write_text('db: postgres://user:pa55word@host/db\n', encoding='utf-8')
    expect('looks like a secret')
    (ws / 'reports/empty.md').write_text('left {{WP}} unresolved\n', encoding='utf-8')
    expect('unresolved template placeholder')
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
    run(repo, 'init', 'one')
    assert run(repo, 'queue').returncode == 0  # single features/*/orch.yaml is found
    run(repo, 'init', 'two')
    assert 'several workspaces' in run(repo, 'queue', ok=False).stderr
    assert run(repo, '--workspace', 'features/two', 'queue').returncode == 0
    assert run(repo / 'features/one/work-packages', 'lint').returncode == 0
    print('PASS workspace discovery: upward search, features/*, ambiguity, --workspace')


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
    print('PASS pepper-orchestrator selftest')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
