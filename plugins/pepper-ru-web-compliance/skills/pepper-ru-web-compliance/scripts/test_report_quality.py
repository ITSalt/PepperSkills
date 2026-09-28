"""Regressions from the metallik/omnidata reports; synthetic evidence, no network."""
from dataclasses import asdict
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import detect
import render
from report_provenance import consistency_issues, current_producer, provenance_issues
from selftest import artifacts_fixture


class ReportQuality(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ctx = detect.Context(artifacts_fixture(self.base, text='Fixture',
            dom='<a href="/login">Войти</a>', url='https://example.ru'))

    def finding(self, rule, summary='Наблюдаемый факт', **kwargs):
        row = asdict(detect.mk(self.ctx, rule, 'WARN', summary))
        row.update(kwargs)
        return row

    def data(self, *rows):
        return {'target': 'https://example.ru', 'generated_at': '2026-09-28',
                'pages_analysed': 1, 'producer': current_producer(), 'findings': list(rows)}

    def test_no_total_or_repeat_offence_in_summary(self):
        rows = [self.finding(r, status='FAIL',
                    fine_legal='до 6 000 000 ₽, при повторе до 18 000 000 ₽',
                    liability='до 6 000 000 ₽, при повторе до 18 000 000 ₽')
                for r in ('CK-005', 'PDN-009')]
        data = self.data(*rows)
        before = copy.deepcopy(data)
        self.assertNotIn('exposure', render.summarise(data))
        self.assertEqual(render.fine_display(rows[0]), 'до 6\u00a0000\u00a0000\u00a0₽')
        for output in (render.combined_md(data), render.report_html(data)):
            self.assertNotIn('верхняя граница санкций', output.lower())
            self.assertNotIn('36\u00a0000\u00a0000', output)
            self.assertIn('Суммы по правилам не складываются', output)
        self.assertEqual(data, before)

    def test_group_preserves_both_actions_without_repeated_evidence(self):
        evidence = [{'kind': 'request', 'detail': 'Обнаруженный запрос',
                     'url': 'https://tracker.example/collect?client=PRIVATE_TEST_ID'}]
        data = self.data(
            self.finding('CK-005', fix_hint='Уточнить необходимость сервиса.', evidence=evidence),
            self.finding('PDN-009', fix_hint='Уточнить страну получателя.', evidence=evidence))
        for plan in (render.plan_md(data), render.plan_html(data)):
            self.assertEqual(plan.count('Уточнить необходимость сервиса.'), 1)
            self.assertEqual(plan.count('Уточнить страну получателя.'), 1)
            self.assertNotIn('PRIVATE_TEST_ID', plan)
            self.assertIn('CK-005', plan)
            self.assertIn('PDN-009', plan)
        for report in (render.report_md(data), render.report_html(data)):
            self.assertEqual(report.count('PRIVATE_TEST_ID'), 1)
            self.assertIn('Доказательство: см.', report)

    def test_every_task_has_action_even_without_fix_hint(self):
        data = self.data(self.finding('PDN-013', fix_hint=None, manual_check='Уточнить цель заявки.'))
        self.assertIn('**Что сделать.** Уточнить цель заявки.', render.plan_md(data))
        self.assertIn('<b>Что сделать.</b> Уточнить цель заявки.', render.plan_html(data))
        self.assertNotIn('Задача требует юридического', render.plan_html(data))

    def test_same_basis_is_shown_once_with_all_rule_ids(self):
        data = self.data(*(self.finding(r, processing_basis='UNKNOWN')
                          for r in ('CK-001', 'CK-003', 'LI-001')))
        for report in (render.report_md(data), render.report_html(data)):
            self.assertEqual(report.count('Автоматически распознанное основание:'), 1)
            self.assertIn('CK-001, CK-003, LI-001', report)

    def test_login_link_and_login_form_do_not_hide_subscription(self):
        self.ctx.pages[0]['forms'] = [
            {'selector': '#login', 'fields': [{'name': 'email', 'type': 'email'},
                                            {'name': 'password', 'type': 'password'}]},
            {'selector': '#subscribe', 'fields': [{'name': 'email', 'type': 'email'}]}]
        rows = {f.rule_id: f for f in detect.detect_forms(self.ctx)}
        self.assertEqual(rows['PDN-004'].status, 'FAIL')
        self.assertIn('#subscribe', rows['PDN-004'].evidence[0]['selector'])
        self.assertNotIn('#login', rows['PDN-004'].evidence[0]['selector'])

    def test_foreign_policy_is_not_operator_policy(self):
        self.ctx.pages.append({'slug': 'google', 'status': 200,
            'final_url': 'https://policies.google.com/privacy', 'forms': []})
        self.ctx._texts = {'google': 'Аналитика на основании согласия', 'index': 'Fixture'}
        self.assertEqual(detect.privacy_pages(self.ctx), [])
        self.assertEqual(detect.policy_texts(self.ctx), {})
        self.assertEqual(detect.detect_documents(self.ctx)[0].status, 'UNKNOWN')
        self.ctx.documents = [{'url': 'https://example.ru/policy/', 'status': 200,
                               'content_type': 'application/pdf'}]
        self.assertEqual(detect.detect_documents(self.ctx)[0].status, 'PASS')

    def test_own_domain_does_not_prove_database_location(self):
        self.ctx.pages[0]['forms'] = [{'action': '/submit', 'fields': [{'type': 'email'}]}]
        self.ctx.net['walk'] = [{'url': 'https://example.ru/submit', 'method': 'POST'}]
        rows = {f.rule_id: f for f in detect.detect_endpoints(self.ctx)}
        self.assertEqual(rows['PDN-011'].status, 'UNKNOWN')
        self.assertEqual(rows['INF-003'].status, 'UNKNOWN')
        self.ctx.net['walk'].append({'url': 'https://external.example/telemetry', 'method': 'POST'})
        rows = detect.detect_endpoints(self.ctx)
        self.assertEqual([r.status for r in rows], ['WARN', 'WARN'])

    def test_current_complete_findings_and_missing_li(self):
        data = self.data(*(self.finding(r, status='NA') for r in self.ctx.rules))
        self.assertEqual(provenance_issues(data), [])
        data['findings'] = [f for f in data['findings'] if f['rule_id'] != 'LI-001']
        self.assertIn('LI-001', ' '.join(provenance_issues(data)))
        data['producer']['skill_version'] = '1.0.1'
        self.assertGreater(len(provenance_issues(data)), 1)

    def test_cli_rejects_legacy_before_writing_and_labels_opt_in(self):
        data = self.data(self.finding('CK-005'))
        data.pop('producer')
        source = self.base / 'findings.json'
        source.write_text(json.dumps(data))
        dest = self.base / 'report'
        cmd = [sys.executable, str(Path(render.__file__)), '--findings', str(source),
               '--out-dir', str(dest), '--format', 'md,html']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(dest.exists())
        result = subprocess.run(cmd + ['--allow-legacy'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for ext in ('md', 'html'):
            report = (dest / ('compliance-report.' + ext)).read_text()
            self.assertIn('Несовместимые входные данные', report)
            self.assertIn('генератор: ' + current_producer()['skill_version'], report)

    def test_conflicting_consent_and_unsupported_geography_are_flagged(self):
        data = self.data(self.finding('PDN-013', 'Основание — согласие', status='PASS'),
                         self.finding('PDN-008', status='FAIL'),
                         self.finding('PDN-011', status='PASS'))
        original = copy.deepcopy(data)
        self.assertEqual(len(consistency_issues(data)), 2)
        self.assertIn('Противоречивые выводы', render.report_html(data))
        self.assertEqual(original, data)


if __name__ == '__main__':
    unittest.main()
