#!/usr/bin/env python3
"""Regressions for delivery truth, explicit live acceptance and client boundaries.

No external writes or model calls. Temporary repositories and process-level CLI
calls exercise production commands; mock results cover unavailable GitHub states.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import acceptance
import delivery
import orch
import runtime_selftest
import session_settings


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.h = runtime_selftest.RuntimeTests()
        self.h.setUp()
        env = patch.dict(os.environ, {'ORCH_NO_CLAUDE': '1', 'ORCH_NO_GH': '1'})
        env.start(); self.addCleanup(env.stop)
        self.addCleanup(self.h.tearDown)

    def checks(self, code, out='', err='', **kwargs):
        with patch.object(delivery.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, out, err)):
            return delivery.pr_checks('example/repo', 1, **kwargs)

    def test_check_read_errors_are_never_absence(self):
        for code, out, err in [(1, '', 'network unavailable'), (1, '', 'token expired'), (1, '[]', ''),
                                (1, '[{"name":"ci","bucket":"pass"}]', 'incomplete GraphQL response'),
                                (1, '[{"name":"ci","bucket":"pass"}]', ''),
                                (0, '{', ''), (0, '{}', ''), (0, '[{"name":"ci"}]', ''),
                                (0, '[{"name":"ci","bucket":"unknown"}]', '')]:
            with self.subTest(code=code, out=out, err=err):
                self.assertFalse(self.checks(code, out, err)[0])
        self.assertTrue(self.checks(0, '[]')[0])
        self.assertTrue(self.checks(1, '', 'no checks reported on the main branch')[0])
        self.assertFalse(self.checks(1, '', 'no checks; token expired')[0])

    def test_strict_checks_and_explicit_provider_exception(self):
        checks = subprocess.CompletedProcess([], 1, '[{"name":"preview","bucket":"fail"}]', '')
        required = subprocess.CompletedProcess([], 0, '[]', '')
        rule = [{'name': 'preview', 'source': 'app:preview-provider', 'decision': 'D-1'}]
        def gh(args):
            if 'check-runs' in args[-1]:
                return {'check_runs': [{'name': 'preview', 'app': {'slug': 'preview-provider'}}]}
            return []
        with patch.object(delivery.subprocess, 'run', side_effect=[checks, required]), \
                patch.object(delivery, 'pr_facts', return_value={'headRefOid': 'a' * 40}), \
                patch.object(delivery, 'gh_json', side_effect=gh):
            ok, detail = delivery.pr_checks('example/repo', 1, rule, {'D-1'})
            self.assertTrue(ok, detail); self.assertIn('nonblocking by D-1', detail)
        with patch.object(delivery.subprocess, 'run', side_effect=[checks, checks]), \
                patch.object(delivery, 'pr_facts', return_value={'headRefOid': 'a' * 40}), \
                patch.object(delivery, 'gh_json', side_effect=gh):
            self.assertFalse(delivery.pr_checks('example/repo', 1, rule, {'D-1'})[0])
        self.assertFalse(self.checks(1, checks.stdout, exceptions=rule, decisions=set())[0])
        self.assertFalse(self.checks(1, checks.stdout, exceptions=[{**rule[0], 'decision': 'A-1'}], decisions={'A-1'})[0])
        with patch.object(delivery.subprocess, 'run', side_effect=[checks, subprocess.CompletedProcess([], 1, '', 'denied')]):
            self.assertFalse(delivery.pr_checks('example/repo', 1, rule, {'D-1'})[0])
        for code, response in [(1, '[]'), (8, '[]'),
                               (1, '[{"name":"ci","bucket":"pass"}]'),
                               (0, '[{"name":"ci","bucket":"unknown"}]')]:
            with patch.object(delivery.subprocess, 'run', side_effect=[
                    checks, subprocess.CompletedProcess([], code, response, '')]):
                ok, detail = delivery.pr_checks('example/repo', 1, rule, {'D-1'})
                self.assertFalse(ok, detail)

    def fixture(self, client='claude'):
        repo, ws = self.h.fixture(client)
        self.h.cli('--workspace', ws, 'new-wp', 'a', 'work')
        w = orch.Workspace(ws); wp = w.wp_path(w.wp_rows()['WP-A-01']['wp'])
        wp.write_text(wp.read_text().replace('<verifiable: test, measurement, live scenario, SELECT>',
                                           'Read the fixture output without changing application state'))
        config = ws / 'orch.yaml'
        config.write_text(config.read_text().replace('    checks: []', '    checks: []\n    verify_test: ["echo verified"]\n    verify_prod: ["echo verified"]'))
        self.h.cli('--workspace', ws, 'set', 'WP-A-01', 'status', 'MERGED')
        sha = self.h.git(repo, 'rev-parse', 'HEAD')
        return repo, ws, sha

    def verify(self, ws, sha, env='test'):
        self.h.cli('--workspace', ws, 'verify', 'WP-A-01', '--env', env, '--sha', sha)
        return max((ws / 'reports').glob(f'verify-WP-A-01-{env}-*.md'), key=lambda p: p.stat().st_mtime_ns)

    def finalize(self, ws, sha, report, verdict='PASS', env='test', ok=True):
        return self.h.cli('--workspace', ws, 'verify', 'finalize', 'WP-A-01', '--env', env,
                          '--sha', sha, '--report', report, '--verdict', verdict, ok=ok)

    def fill_live(self, report):
        report.write_text(report.read_text().replace('| TODO | TODO | TODO | WAIT |',
            '| verified | verified observed | fixture stdout: verified | PASS |'))

    def test_automatic_pass_does_not_unlock_release(self):
        repo, ws, sha = self.fixture('codex')
        report = self.verify(ws, sha[:8])
        self.assertEqual(orch.Workspace(ws).wp_rows()['WP-A-01']['status'], 'VERIFYING')
        self.assertFalse(acceptance.finalized(ws, 'WP-A-01', 'test', sha))
        result = self.h.cli('--workspace', ws, 'release', '--plan', ok=False)
        self.assertIn('no package', result.stderr)
        self.finalize(ws, sha, report, ok=False)
        self.fill_live(report); self.finalize(ws, sha, report)
        self.assertTrue(acceptance.finalized(ws, 'WP-A-01', 'test', sha))
        self.assertEqual(orch.Workspace(ws).wp_rows()['WP-A-01']['status'], 'VERIFIED_TEST')
        report.write_text(report.read_text() + '\nchanged after acceptance\n')
        self.assertFalse(acceptance.finalized(ws, 'WP-A-01', 'test', sha))

    def test_unknown_sha_refused_without_state_writes(self):
        repo, ws, sha = self.fixture()
        before = {str(p): p.read_bytes() for p in ws.rglob('*') if p.is_file()}
        result = self.h.cli('--workspace', ws, 'verify', 'WP-A-01', '--env', 'test', '--sha', 'e' * 40, ok=False)
        self.assertIn('unknown or ambiguous', result.stderr)
        self.assertEqual(before, {str(p): p.read_bytes() for p in ws.rglob('*') if p.is_file()})

    def test_wrong_report_revision_and_failed_tools_never_unlock(self):
        repo, ws, sha = self.fixture()
        report = self.verify(ws, sha)
        self.fill_live(report)
        self.h.git(repo, 'commit', '--allow-empty', '-m', 'another revision')
        other = self.h.git(repo, 'rev-parse', 'HEAD')
        self.finalize(ws, other, report, ok=False)
        self.finalize(ws, sha, report, verdict='WAIT', ok=False)
        self.assertFalse(acceptance.finalized(ws, 'WP-A-01', 'test', sha))
        self.assertFalse(list((ws / 'bugs').glob('BUG-*')))
        self.finalize(ws, sha, report)
        before, live = report.read_text().split(acceptance.LIVE, 1)
        report.write_text(before + acceptance.LIVE + live.replace('| PASS |', '| FAIL |'))
        self.finalize(ws, sha, report, verdict='FAIL', ok=False)
        self.assertTrue(delivery.settings(orch.Workspace(ws).config)['hold'])
        self.assertTrue(list((ws / 'bugs').glob('BUG-*')))
        self.assertEqual(orch.Workspace(ws).wp_rows()['WP-A-01']['status'], 'VERIFYING')
        self.assertFalse(acceptance.finalized(ws, 'WP-A-01', 'test', sha))

    def test_automatic_report_tampering_and_missing_criterion(self):
        repo, ws, sha = self.fixture()
        report = self.verify(ws, sha)
        self.fill_live(report)
        original = report.read_text()
        report.write_text(original.replace('**Verdict: PASS**', '**Verdict: FAIL**'))
        self.assertIn('section changed', self.finalize(ws, sha, report, ok=False).stderr)
        report.write_text(original.replace('fixture stdout: verified', 'TODO'))
        self.finalize(ws, sha, report, ok=False)

    def test_cancel_waiter_preserves_holder_and_terminal_cleanup(self):
        repo, ws, sha = self.fixture()
        config = ws / 'orch.yaml'
        config.write_text(config.read_text().replace('    resources: []', '    resources: [stand]'))
        self.h.cli('--workspace', ws, 'new-wp', 'b', 'work')
        for wp in ('WP-A-01', 'WP-B-01'):
            self.h.cli('--workspace', ws, 'lock', 'acquire', 'stand', '--wp', wp, ok=wp=='WP-A-01')
        self.h.cli('--workspace', ws, 'lock', 'cancel', 'stand', '--wp', 'WP-B-01')
        self.assertEqual(orch.locks(orch.Workspace(ws))[0]['holder'], 'WP-A-01')
        self.h.cli('--workspace', ws, 'lock', 'acquire', 'stand', '--wp', 'WP-B-01', ok=False)
        self.h.cli('--workspace', ws, 'set', 'WP-B-01', 'status', 'CANCELLED (not needed)')
        lock = orch.locks(orch.Workspace(ws))[0]
        self.assertEqual(lock['holder'], 'WP-A-01'); self.assertEqual(orch.waiting_of(lock), [])

    def test_instruction_prompts_are_read_only_by_default(self):
        import project_instructions
        self.assertNotIn('If one file is missing', project_instructions.GUIDANCE)
        repo, ws, sha = self.fixture()
        self.h.cli('instructions', 'check', '--repo', repo, ok=False)
        self.assertFalse((repo / 'AGENTS.md').exists())
        text = self.h.root / 'shared.txt'; text.write_text('Confirmed common rule')
        self.h.cli('--workspace', ws, 'instructions', 'sync', '--repo', repo, '--wp', 'WP-A-01',
                   '--text-file', text, '--expected-claude', 'missing', '--expected-agents', 'missing', '--apply', ok=False)
        self.assertFalse((repo / 'AGENTS.md').exists())
        config = ws / 'orch.yaml'
        config.write_text(config.read_text().replace('    shared_paths: []', '    shared_paths: [CLAUDE.md, AGENTS.md]'))
        w = orch.Workspace(ws); wpfile = w.wp_path(w.wp_rows()['WP-A-01']['wp'])
        text_ = wpfile.read_text(); old = next(x for x in text_.splitlines() if x.startswith('| Shared paths touched |'))
        wpfile.write_text(text_.replace(old, '| Shared paths touched | `CLAUDE.md`, `AGENTS.md` |'))
        for name in ('CLAUDE.md', 'AGENTS.md'):
            self.h.cli('--workspace', ws, 'lock', 'acquire', name, '--wp', 'WP-A-01')
        hashes = project_instructions.status(repo)['files']
        self.h.cli('--workspace', ws, 'instructions', 'sync', '--repo', repo, '--wp', 'WP-A-01',
                   '--text-file', text, '--expected-claude', hashes[0]['sha256'], '--expected-agents', 'missing', '--apply')
        self.assertIn('Claude custom', (repo / 'CLAUDE.md').read_text())
        self.h.cli('instructions', 'check', '--repo', repo)

    def test_report_template_does_not_leak_origin_owner(self):
        import plugin_report
        repo, ws, sha = self.fixture()
        self.h.git(repo, 'remote', 'add', 'origin', 'https://github.com/ITSalt/private-project.git')
        result = self.h.cli('--workspace', ws, 'report', '--check', '--command', 'echo ITSalt private-project',
                            '--title', 'test report', '--expected-actual', 'ITSalt fails without revealing details')
        issue = next((ws / 'bugs').glob('*.issue.md')).read_text()
        self.assertNotIn('ITSalt', issue); self.assertNotIn('private-project', issue)
        self.assertIn('<origin-', issue)
        self.assertIn('PLUGIN-BUG-', result.stdout)
        self.assertTrue(plugin_report.leaks('secret-team', [('secret-team','<team>')], [], []))

    def test_delivery_modes_before_side_effects(self):
        repo, ws, sha = self.fixture()
        w = orch.Workspace(ws); module = w.streams()[1]['a']
        with self.assertRaises(delivery.DeliveryError): delivery.stand_plan(module)
        module.repo.raw['deploy_test'] = 'git status --porcelain && echo deployed'
        with self.assertRaises(delivery.DeliveryError): delivery.stand_plan(module)
        module.repo.raw['deploy_test_mode'] = 'command'
        self.assertEqual(delivery.stand_plan(module)[0], 'command')
        module.repo.raw['deploy_test'] = 'owner-confirmed in module window'
        with self.assertRaises(delivery.DeliveryError): delivery.stand_plan(module)
        del module.repo.raw['deploy_test_mode']
        self.assertEqual(delivery.stand_plan(module)[0], 'owner')

    def test_claude_settings_deny_any_prod_command_and_follow_stand_mode(self):
        self.assertTrue(session_settings.denied_command('ssh prod ./deploy.sh'))
        self.assertFalse(session_settings.denied_command('owner-confirmed in module window'))
        self.assertIsNone(session_settings.stand_command({'deploy_test': 'git pull && make up'}))
        self.assertEqual(session_settings.stand_command({'deploy_test': 'git pull && make up',
                                                         'deploy_test_mode': 'command'}), 'git pull && make up')
        self.assertIsNone(session_settings.stand_command({'deploy_test': './up.sh', 'deploy_test_mode': 'owner'}))
        repo, ws, sha = self.fixture()
        w = orch.Workspace(ws); repos, modules = w.streams()[0], w.streams()[1]
        module = modules['a']
        module.raw['deploy_prod'] = 'ssh prod ./deploy.sh'
        data, _ = session_settings.module_settings(w.config, w.root, module)
        self.assertIn('Bash(ssh prod ./deploy.sh)', data['permissions']['deny'])
        data = session_settings.orchestrator_settings(w.config, w.root, modules, repos, orch.SKILL_DIR)
        self.assertIn('Bash(ssh prod ./deploy.sh *)', data['permissions']['deny'])

    def test_reconciliation_requires_authoritative_queue_absence(self):
        for data, expected in [({'data': {'repository': {'pullRequest': {'mergeQueueEntry': None}}}}, True),
                               ({'data': {'repository': {'pullRequest': {'mergeQueueEntry': {'id': 'queued'}}}}}, False),
                               ({'data': None, 'errors': [{'message': 'unavailable'}]}, False), ({}, False)]:
            with patch.object(delivery, 'gh_json', return_value=data):
                self.assertEqual(delivery.not_queued('example/repo', 1), expected)

    def test_merge_is_bound_to_reviewed_head(self):
        with patch.object(delivery.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            delivery.merge('a/b', 1, 'merge', False, 'a' * 40)
            self.assertIn('--match-head-commit', run.call_args.args[0])
        with self.assertRaises(delivery.DeliveryError): delivery.merge('a/b', 1, 'merge', False, 'abcd123')

    def test_queued_pr_never_becomes_merged_or_starts_deploy(self):
        repo, ws, sha = self.fixture('codex')
        self.h.cli('--workspace', ws, 'set', 'WP-A-01', 'status', 'ACCEPTED')
        delivery.set_key(ws / 'orch.yaml', 'merge', 'orchestrator')
        w = orch.Workspace(ws); row, module, _ = orch.wp_context(w, 'WP-A-01')
        args = argparse.Namespace(workspace=str(ws), wp='WP-A-01', apply=True, check=False, after_failure=None)
        context = {'row': row, 'module': module, 'facts': {'number': 1}, 'sha': sha,
                   'name': 'example/repo', 'pr': 'https://github.com/example/repo/pull/1'}
        with patch.object(delivery, 'errors', return_value=[]), \
                patch.object(orch, 'shutil_which', return_value=True), \
                patch.object(orch, 'delivery_gates', return_value=([('G1', True, 'fixture')], context)), \
                patch.object(delivery, 'merge', return_value=None), \
                patch.object(delivery, 'pr_facts', return_value={'state': 'OPEN', 'mergeCommit': {'oid': sha}}), \
                patch.object(delivery, 'run_command') as deploy, \
                patch.dict(os.environ, {'ORCH_MERGE_POLLS': '1', 'ORCH_POLL_INTERVAL': '0'}):
            self.assertEqual(orch.cmd_deliver(args), 1)
            deploy.assert_not_called()
        self.assertEqual(orch.Workspace(ws).wp_rows()['WP-A-01']['status'], 'ACCEPTED')
        self.assertEqual(orch.delivery_progress(w, 'WP-A-01')['phase'], 'unknown')

    def test_bash_command_and_unknown_outcome(self):
        ok, detail = delivery.run_command('printf done', self.h.root, 5, 'bash')
        self.assertTrue(ok, detail)
        self.assertIn('done', detail)
        ok, detail = delivery.run_command('sleep 2', self.h.root, .05, 'bash')
        self.assertFalse(ok); self.assertIn('timed out', detail)

    def test_review_clones_are_unique_and_checkout_drift_is_fatal(self):
        repo, ws, sha = self.fixture()
        self.h.git(repo, 'commit', '--allow-empty', '-m', 'second review revision')
        other = self.h.git(repo, 'rev-parse', 'HEAD')
        script = Path(__file__).with_name('review_clone.sh')
        env = dict(os.environ, TMPDIR=self.h.root.as_posix())
        bash = delivery.shell_program('bash')
        def clone(n):
            expected = sha if n % 2 else other
            result = subprocess.run([bash, script.as_posix(), '--repo', repo.as_posix(), '--sha', expected, '--keep',
                '--test', 'test "$(git rev-parse HEAD)" = "' + expected + '"'],
                env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return next(x for x in result.stdout.splitlines() if x.startswith('review-run:'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            runs = list(pool.map(clone, range(6)))
        self.assertEqual(len(set(runs)), 6)
        result = subprocess.run([bash, script.as_posix(), '--repo', repo.as_posix(), '--sha', sha,
            '--test', 'git -c advice.detachedHead=false checkout --detach ' + other], env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2); self.assertIn('HEAD mismatch', result.stderr)

    def test_delivery_mutex_does_not_block_hold_and_releases_after_crash(self):
        repo, ws, sha = self.fixture()
        with delivery.operation_lock(ws):
            child = self.h.child("import delivery,sys;\nwith delivery.operation_lock(sys.argv[1]): print('unsafe')", ws)
            out, err = child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0); self.assertIn('another delivery operation', err)
            self.h.cli('--workspace', ws, 'hold', 'stop remains available during a workflow')
        child = self.h.child("import delivery,sys,time;\nwith delivery.operation_lock(sys.argv[1]):\n print('locked',flush=True); time.sleep(30)", ws)
        self.assertEqual(child.stdout.readline().strip(), 'locked')
        child.kill(); child.communicate(timeout=10)
        with delivery.operation_lock(ws):
            pass

    def test_client_switch_revokes_delegation(self):
        repo, ws, sha = self.fixture()
        self.h.cli('--workspace', ws, 'decide', 'D', 'Delegate merge')
        self.h.cli('--workspace', ws, 'delivery', 'set', 'merge', 'orchestrator', '--decision', 'D-1')
        self.h.cli('--workspace', ws, 'client', 'switch', '--target', 'codex', '--stopped-evidence', 'owner stopped writers')
        d = delivery.settings(orch.Workspace(ws).config)
        self.assertTrue(all(d[x] == 'owner' for x in delivery.LEVELS)); self.assertIsNone(d['enabled_by'])
        self.assertIn('delegation reset', (ws / 'status.md').read_text())

    def test_new_merge_of_delivered_wp_is_refused_early(self):
        repo, ws, sha = self.fixture()
        w = orch.Workspace(ws)
        orch.ledger(w, 'WP-A-01', 'https://github.com/example/repo/pull/1', sha)
        result = self.h.cli('--workspace', ws, 'merge', 'add', 'WP-A-01', ok=False)
        self.assertIn('expand/contract', result.stderr)
        self.h.cli('--workspace', ws, 'set', 'WP-A-01', 'status', 'VERIFYING')


if __name__ == '__main__':
    unittest.main(verbosity=2)
