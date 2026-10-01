#!/usr/bin/env python3
"""Real-process local runtime regressions; no paid providers or external writes."""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import codex_adapter
import id_allocator
import orch
import project_instructions as instructions
import runtime_commands
import safe_edit
import state_io
import streams

HERE = Path(__file__).resolve().parent


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pepper-runtime-test-')
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {'ORCH_RUNTIME_DIR': str(self.root / 'runtime'),
                                           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONPATH': str(HERE)})
        self.env.start()
        self.children = []

    def tearDown(self):
        for p in self.children:
            if p.poll() is None:
                p.kill()
            p.communicate()
        self.env.stop()
        self.temp.cleanup()

    def child(self, code, *args):
        process = subprocess.Popen([sys.executable, '-c', code, *map(str, args)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.children.append(process)
        return process

    def cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, str(HERE / 'orch.py'), *map(str, args)],
                           capture_output=True, text=True, encoding='utf-8', cwd=self.root)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout)
        return p

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *map(str, args)], check=True,
                              capture_output=True, text=True, encoding='utf-8').stdout.strip()

    def fixture(self, client='codex'):
        repo = self.root / 'app'
        repo.mkdir()
        self.git(repo, 'init', '-b', 'main')
        self.git(repo, 'config', 'user.name', 'Fixture')
        self.git(repo, 'config', 'user.email', 'fixture@example.invalid')
        (repo / 'a').mkdir(); (repo / 'b').mkdir()
        (repo / 'a/readme.md').write_text('a\n'); (repo / 'b/readme.md').write_text('b\n')
        (repo / 'CLAUDE.md').write_text('Claude custom\n')
        self.git(repo, 'add', '.'); self.git(repo, 'commit', '-m', 'fixture')
        home = self.root / 'home'
        home.mkdir(); self.git(home, 'init', '-b', 'main')
        ws = home / 'features/test'
        flags = ['--permission-mode', 'default'] if client == 'claude' else []
        self.cli('init', 'test', '--client', client, '--sessions', 'local', '--lang', 'en',
                 '--dir', ws, '--shell', 'bash', '--repo', 'app=' + str(repo), '--area', 'a=app:a/**',
                 '--area', 'b=app:b/**', *flags)
        return repo, ws

    def test_reservations_processes_replay_loss_and_corruption(self):
        scope = id_allocator.new_scope()
        id_allocator.register(scope, {'FR': 41})
        code = '''import id_allocator,json,sys,time
s=sys.argv[1]; i=sys.argv[2]
def reserve(n):
 for retry in range(8):
  try:return id_allocator.reserve(s,'FR',i+':'+str(n))['first']
  except id_allocator.AllocationError as e:
   if 'locked' not in str(e) or retry==7:raise
   time.sleep(.05*(retry+1))
a=[reserve(n) for n in range(100)]
assert [reserve(n) for n in range(100)]==a
print(json.dumps(a))'''
        procs = [self.child(code, scope, n) for n in range(16)]
        values = []
        for p in procs:
            out, err = p.communicate(timeout=180)
            self.assertEqual(p.returncode, 0, err)
            values.extend(json.loads(out))
        self.assertEqual(len(set(values)), 1600)
        self.assertEqual((min(values), max(values)), (42, 1641))
        with self.assertRaises(id_allocator.AllocationError):
            id_allocator.reserve(scope, 'OTHER', '0:0')
        with self.assertRaises(id_allocator.AllocationError):
            id_allocator.reserve(scope, 'FR', '0:0', 2)
        db, _ = id_allocator.scope_paths(scope)
        db.unlink()
        with self.assertRaises(id_allocator.AllocationError):
            id_allocator.register(scope, {})
        db.write_bytes(b'not sqlite')
        with self.assertRaises(id_allocator.AllocationError):
            id_allocator.reserve(scope, 'FR', 'new')

    def test_allocator_crash_and_busy(self):
        scope = id_allocator.new_scope(); id_allocator.register(scope, {})
        p = self.child("import id_allocator,os,sys; c=id_allocator.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); c.execute(\"INSERT INTO counters VALUES ('X',999)\"); os._exit(9)", scope)
        p.communicate(timeout=5)
        self.assertEqual(id_allocator.reserve(scope, 'X', 'after-rollback')['first'], 1)
        p = self.child("import id_allocator,os,sys; id_allocator.reserve(sys.argv[1],'X','commit-crash'); os._exit(9)", scope)
        p.communicate(timeout=5)
        self.assertEqual(id_allocator.reserve(scope, 'X', 'commit-crash')['first'], 2)
        c = id_allocator.connect(scope)
        self.assertEqual(c.execute('PRAGMA busy_timeout').fetchone()[0], 10000)
        c.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        try:
            with self.assertRaises(id_allocator.AllocationError):
                id_allocator.reserve(scope, 'X', 'busy')
        finally:
            c.close()
        self.assertGreater(time.monotonic() - started, 9)
        self.assertLess(time.monotonic() - started, 30)  # CI scheduling can delay return.
        self.assertEqual(id_allocator.reserve(scope, 'X', 'busy')['first'], 3)

    def test_parallel_state_and_exclusive_create(self):
        repo, ws = self.fixture('claude')
        code = "import orch,sys; raise SystemExit(orch.main(['--workspace',sys.argv[1],'owner','add','R',sys.argv[2]]))"
        procs = [self.child(code, ws, 'item-' + str(n)) for n in range(12)]
        for p in procs:
            out, err = p.communicate(timeout=180); self.assertEqual(p.returncode, 0, err)
        rows = orch.Workspace(ws).table(ws / 'status.md', 'owner')[2]
        self.assertEqual(len([r for r in rows if r['text'].startswith('item-')]), 12)
        path = ws / 'notes.md'; path.write_text('anchor\n')
        code = "import safe_edit,sys; safe_edit.replace_once(sys.argv[1],'anchor\\n',sys.argv[2]+'\\nanchor\\n')"
        # Windows path spelling must not create a second lock for the same file.
        procs = [self.child(code, str(path).upper() if os.name == 'nt' and n % 2 else path,
                            'line-' + str(n)) for n in range(12)]
        for p in procs:
            _, err = p.communicate(timeout=20); self.assertEqual(p.returncode, 0, err)
        self.assertEqual(len(path.read_text().splitlines()), 13)
        code = "import safe_edit,sys; safe_edit.create(sys.argv[1],sys.argv[2])"
        procs = [self.child(code, ws / 'exclusive.md', str(n)) for n in range(8)]
        self.assertEqual(sum(p.communicate(timeout=20) is not None and p.returncode == 0 for p in procs), 1)

    def test_multi_file_recovery_and_foreign_conflict(self):
        ws = self.root / 'ws'; ws.mkdir(); (ws / 'orch.yaml').write_text('program: test\n')
        a, b = ws / 'a.md', ws / 'b.md'; a.write_text('old\n'); b.write_text('old\n')
        code = '''import state_io,safe_edit,sys,os
from pathlib import Path
r=Path(sys.argv[1])
with state_io.transaction(r):
 safe_edit.replace_once(r/'a.md','old','middle')
 safe_edit.replace_once(r/'a.md','middle','new')
 safe_edit.replace_once(r/'b.md','old','new')
 os._exit(9)'''
        p = self.child(code, ws); p.communicate(timeout=10)
        with state_io.transaction(ws):
            pass
        self.assertEqual(a.read_text(), 'old\n'); self.assertEqual(b.read_text(), 'old\n')
        p = self.child(code, ws); p.communicate(timeout=10); a.write_text('foreign\n')
        with self.assertRaises(state_io.StateError):
            with state_io.transaction(ws):
                pass
        self.assertEqual(a.read_text(), 'foreign\n'); self.assertEqual(b.read_text(), 'new\n')

    def test_crlf_point_edits_preserve_bytes_and_reject_ambiguity(self):
        path = self.root / 'state.md'
        path.write_bytes('Владелец\r\nanchor\r\ntail\r\n'.encode('utf-8'))
        safe_edit.replace_once(path, 'anchor\n', 'one\ntwo\n')
        safe_edit.replace_many(path, [('two\ntail', 'three\ntail')])
        self.assertEqual(path.read_bytes(), 'Владелец\r\none\r\nthree\r\ntail\r\n'.encode('utf-8'))
        path.write_bytes(b'anchor\r\nanchor\r\n')
        with self.assertRaises(safe_edit.EditError):
            safe_edit.replace_once(path, 'anchor\n', 'new\n')
        self.assertEqual(path.read_bytes(), b'anchor\r\nanchor\r\n')
        path.write_bytes(b'keep\nanchor\r\n')
        with self.assertRaises(safe_edit.EditError):
            safe_edit.replace_once(path, 'anchor\n', 'new\n')
        self.assertEqual(path.read_bytes(), b'keep\nanchor\r\n')

    def test_instruction_pairs_case_nested_cas_and_preservation(self):
        repo = self.root / 'repo'; repo.mkdir()
        p = repo / 'claude.md'; p.write_bytes(b'custom\r\n[link](docs/a.md)\r\n')
        first = instructions.status(repo)['files']
        preview = instructions.sync(repo, 'pytest -q\nPreserve owner copy', first[0]['sha256'], 'missing')
        self.assertFalse(preview['applied']); self.assertFalse((repo / 'AGENTS.md').exists())
        instructions.sync(repo, 'pytest -q\nPreserve owner copy', first[0]['sha256'], 'missing', True)
        self.assertTrue(p.read_bytes().startswith(b'custom\r\n[link](docs/a.md)\r\n'))
        self.assertNotIn('CLAUDE.md', [x.name for x in repo.iterdir()])
        self.assertTrue(instructions.status(repo)['synchronized'])
        with self.assertRaises(instructions.InstructionError):
            instructions.sync(repo, 'new', first[0]['sha256'], 'missing', True)
        child = repo / 'nested'; child.mkdir(); (child / 'AGENTS.md').write_text('nested custom')
        self.assertFalse(all(x['synchronized'] for x in instructions.check_tree(repo)))
        if not (repo / 'CLAUDE.md').exists():
            (repo / 'CLAUDE.md').write_text('ambiguous')
            with self.assertRaises(instructions.InstructionError): instructions.status(repo)
        target = repo / 'target'; target.write_text('outside')
        try:
            (child / 'CLAUDE.md').symlink_to(target)
        except OSError as error:
            if os.name != 'nt' or getattr(error, 'winerror', None) != 1314:
                raise
            return  # Native Windows symlinks require developer mode or privilege.
        h = instructions.status(child)['files']
        with self.assertRaises(instructions.InstructionError):
            instructions.sync(child, 'shared', h[0]['sha256'], h[1]['sha256'], True)

    def test_codex_worktrees_switch_models_and_scopes(self):
        repo, ws = self.fixture()
        for mod in ('a', 'b'):
            self.cli('--workspace', ws, 'new-wp', mod, 'work', '--request-id', mod + ':work')
            self.cli('--workspace', ws, 'new-wp', mod, 'work', '--request-id', mod + ':work')
            self.cli('--workspace', ws, 'prepare', 'WP-' + mod.upper() + '-01')
        w = orch.Workspace(ws)
        for mod in ('a', 'b'):
            module = w.streams()[1][mod]
            directory = codex_adapter.worktree(module, 'WP-' + mod.upper() + '-01', 'work')
            self.assertEqual(id_allocator.repo_scope(repo), id_allocator.repo_scope(directory))
        self.cli('--workspace', ws, 'model', 'WP-A-01', 'gpt-test', '--effort', 'high', '--reason', 'fixture')
        self.cli('--workspace', ws, 'set', 'WP-A-01', 'status', 'READY')
        with patch.object(runtime_commands, 'check_capabilities', return_value={'available': True}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(orch.main(['--workspace', str(ws), 'dispatch', 'WP-A-01', '--dry-run']), 0)
        dispatch = output.getvalue()
        self.assertIn('codex --cd', dispatch); self.assertNotIn('claude ', dispatch)
        self.cli('--workspace', ws, 'client', 'switch', '--target', 'claude', '--stopped-evidence', 'fixture: no writers')
        launch = self.cli('--workspace', ws, 'dispatch', 'WP-A-01', '--dry-run').stdout
        self.assertIn('.pepper-worktrees/wp-a-01-work', launch.replace('\\', '/'))
        self.assertNotIn('claude -w', launch)
        self.cli('--workspace', ws, 'model', 'WP-A-01', 'opus', '--reason', 'Claude fixture')
        self.cli('--workspace', ws, 'client', 'switch', '--target', 'codex', '--stopped-evidence', 'fixture: no writers')
        self.cli('--workspace', ws, 'prepare', 'WP-A-01')
        w = orch.Workspace(ws)
        self.assertEqual(streams.wp_meta(w.wp_path(w.wp_rows()['WP-A-01']['wp']), w.streams()[1]['a'])['model'], 'gpt-test')
        self.cli('--workspace', ws, 'new-wp', 'a', 'next')
        self.assertIn('WP-A-02', orch.Workspace(ws).wp_rows())
        self.cli('--workspace', ws, 'lint')

    def test_explicit_migration_and_numbering_lock(self):
        repo, ws = self.fixture('claude')
        p = ws / 'orch.yaml'; text = p.read_text(); text = re_remove_numbering(text); p.write_text(text)
        (ws / 'archives').mkdir(); (ws / 'archives/old.md').write_text('R-77 WP-A-42 BUG-19\n')
        self.cli('--workspace', ws, 'id', 'migrate', '--scope', 'program')
        self.assertNotIn('numbering:', p.read_text())
        self.cli('--workspace', ws, 'id', 'migrate', '--scope', 'program', '--apply')
        self.cli('--workspace', ws, 'id', 'migrate', '--scope', 'program', '--apply')
        out = self.cli('--workspace', ws, 'new-wp', 'a', 'migrated').stdout
        self.assertIn('WP-A-43', out)
        self.cli('id', 'migrate', '--scope', 'repo:' + str(repo), '--namespace', 'FR', '--seed', '100', '--apply')
        p.write_text(p.read_text().replace('    resources: []', '    resources:\n      - name: numbering\n        mode: sequence\n        namespace: FR\n        producers_migrated: true'))
        w = orch.Workspace(ws); runtime_commands.check_sequence(w, w.streams()[1]['a'].repo, 'numbering')
        self.assertNotIn('numbering', orch.dispatch_problems(w, 'WP-A-43')[1])

    def test_concrete_files_shared_file_and_stand_serialization(self):
        repo, ws = self.fixture('claude')
        config = ws / 'orch.yaml'
        config.write_text(config.read_text().replace('    shared_paths: []', '    shared_paths: [shared/**]')
                          .replace('    resources: []', '    resources: [{name: stand, mode: on-demand}]')
                          .replace('    paths: [a/**]', '    paths: [shared/**]')
                          .replace('    paths: [b/**]', '    paths: [shared/**]'))
        self.cli('--workspace', ws, 'settings', 'all')
        for mod, number in (('a', 101), ('b', 102)):
            self.cli('--workspace', ws, 'new-wp', mod, 'newfile')
            w = orch.Workspace(ws); wp = 'WP-' + mod.upper() + '-01'; p = w.wp_path(w.wp_rows()[wp]['wp'])
            original = p.read_text()
            line = next(x for x in original.splitlines() if x.startswith('| Shared paths touched |'))
            p.write_text(original.replace(line, '| Shared paths touched | `shared/FR-' + str(number) + '.md` |'))
            self.cli('--workspace', ws, 'set', wp, 'status', 'READY')
        self.cli('--workspace', ws, 'dispatch', 'WP-A-01')
        self.cli('--workspace', ws, 'dispatch', 'WP-B-01', '--dry-run')
        w = orch.Workspace(ws); p = w.wp_path(w.wp_rows()['WP-B-01']['wp'])
        p.write_text(p.read_text().replace('shared/FR-102.md', 'shared/FR-101.md'))
        self.cli('--workspace', ws, 'dispatch', 'WP-B-01', '--dry-run', ok=False)
        self.cli('--workspace', ws, 'lock', 'acquire', 'stand', '--wp', 'WP-A-01')
        self.cli('--workspace', ws, 'lock', 'acquire', 'stand', '--wp', 'WP-B-01', ok=False)

    def test_transport_fallback_and_switch_running_session(self):
        import codex_transport
        with patch.object(codex_transport, 'capabilities', return_value={'queue': False}):
            result = codex_transport.send('test-thread', 'TASK')
        self.assertFalse(result['delivered']); self.assertEqual(result['fallback'], 'TASK')
        repo, ws = self.fixture('claude')
        self.cli('--workspace', ws, 'new-wp', 'a', 'work')
        p = ws / 'orchestration/sessions.json'
        p.write_text(json.dumps({'version': 1, 'sessions': {'WP-A-01': {'state': 'running', 'client': 'claude',
                        'thread_id': 'fixture', 'worktree': str(repo), 'branch': 'test/wp-a-01-work'}}, 'outbox': {}}))
        self.cli('--workspace', ws, 'client', 'switch', '--target', 'codex', '--stopped-evidence', 'fixture', ok=False)
        self.cli('--workspace', ws, 'session', 'stopped', '--wp', 'WP-A-01', '--evidence', 'owner stopped fixture')
        self.cli('--workspace', ws, 'client', 'switch', '--target', 'codex', '--stopped-evidence', 'fixture')

    def test_interrupted_init_recovers_without_overwriting(self):
        root = self.root / 'new-program'
        code = '''import orch,safe_edit,sys,os
original=safe_edit.create
calls=0
def crash(*a,**k):
 global calls
 original(*a,**k);calls+=1
 if calls==3:os._exit(9)
safe_edit.create=crash
orch.main(['init','recovery','--client','codex','--sessions','local','--lang','en','--shell','bash','--dir',sys.argv[1]])'''
        p = self.child(code, root); p.communicate(timeout=10)
        self.assertEqual(p.returncode, 9)
        self.cli('init', 'recovery', '--client', 'codex', '--sessions', 'local', '--lang', 'en', '--shell', 'powershell', '--dir', root)
        self.assertEqual(orch.Workspace(root).config['shell'], 'powershell')
        self.assertTrue(orch.orchestrator_start(orch.Workspace(root)).splitlines()[1].startswith('& '))


def re_remove_numbering(text):
    import re
    return re.sub(r'\nnumbering:\n(?:  .*\n)+', '\n', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
