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
import report_evidence
from report_provenance import collection_issues, collection_warnings, consistency_issues, current_producer, provenance_issues
from selftest import artifacts_fixture


class ReportQuality(unittest.TestCase):
    def test_producer_version_has_no_yaml_quotes(self):
        self.assertEqual(current_producer()['skill_version'], '2.4.0')

    def test_partial_network_summary_names_coverage_reason(self):
        summary = render.network_summary({
            'complete': False, 'mode': 'managed',
            'coverage_reason': '4 из 20 страниц вернули 403',
        })
        self.assertIn('Причина ограничения: 4 из 20 страниц вернули 403', summary)
        self.assertNotIn('Причина ограничения: нет', summary)

    def test_report_warns_about_unvisited_pages_and_unfinished_refusal(self):
        warnings = collection_warnings({
            'unvisited_links': 98,
            'collection': {'network': {'complete': True}, 'visual_complete': True,
                           'refusal': {'click_status': 'not_found', 'revisit_completed': False}},
        })
        self.assertEqual(len(warnings), 2)
        self.assertIn('98', warnings[0])
        self.assertIn('отказа', warnings[1])

    def test_shared_request_set_is_one_plan_reference_without_repeated_page_list(self):
        request = {'kind': 'request', 'detail': 'GET', 'url': 'https://receiver.example/a',
                   'context': {'method': 'GET', 'page': 'https://example.ru/'}}
        locations = [{'kind': 'dom', 'detail': 'адрес формы',
                      'url': f'https://example.ru/page-{i}'} for i in range(12)]
        first = {'evidence': [request] + locations}
        second = {'evidence': [request] + locations}
        shared = {}
        first_lines = render.describe_observations(first, shared, 'V-01')
        second_lines = render.describe_observations(second, shared, 'V-02')
        self.assertLessEqual(len(first_lines), 6)
        self.assertEqual(second_lines,
                         ['Общий набор сетевых доказательств: см. V-01; evidence.html / evidence.json.'])

    def test_repeated_direct_evidence_is_not_listed_twice(self):
        entries = [{'kind': 'dom', 'detail': 'адрес формы',
                    'url': f'https://example.ru/page-{i}'} for i in range(12)]
        owners = {}
        first, hidden = render.visible_nonrequest_evidence(
            {'rule_id': 'PDN-011', 'evidence': entries}, owners)
        repeated, repeated_hidden = render.visible_nonrequest_evidence(
            {'rule_id': 'INF-003', 'evidence': entries}, owners)
        self.assertEqual(len(first), 5)
        self.assertEqual(hidden, 7)
        self.assertEqual((repeated, repeated_hidden), ([], 0))

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
                'pages_analysed': 1, 'producer': current_producer(), 'findings': list(rows),
                'collection': {'collector': {'name': 'pepper-ru-web-compliance', 'version': '2.4.0', 'observation_version': 2},
                               'schema_version': 1, 'started_at': '2026-09-28', 'finished_at': '2026-09-28',
                               'network': {'mode': 'managed', 'complete': True, 'egress': {'ip': '203.0.113.1', 'country': 'RU'}},
                               'network_observations': {'count': 1, 'versions': ['2']}}}

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
            self.finding('CK-005', manual_check='Уточнить необходимость сервиса.', evidence=evidence),
            self.finding('PDN-009', manual_check='Уточнить страну получателя.', evidence=evidence))
        for plan in (render.plan_md(data), render.plan_html(data)):
            self.assertEqual(plan.count('Уточнить необходимость сервиса.'), 1)
            self.assertEqual(plan.count('Уточнить страну получателя.'), 1)
            self.assertNotIn('PRIVATE_TEST_ID', plan)
            self.assertIn('CK-005', plan)
            self.assertIn('PDN-009', plan)
        for report in (render.report_md(data), render.report_html(data)):
            self.assertNotIn('PRIVATE_TEST_ID', report)
            self.assertIn('evidence.html', report)

    def test_large_network_evidence_stays_out_of_main_report(self):
        for size in (400, 2000):
            rows = [{'kind': 'request', 'detail': 'POST: назначение не установлено',
                     'url': 'https://receiver.example/collect?secret=private',
                     'context': {'method': 'POST', 'page': f'https://example.ru/p{i}',
                                 'phase': 'before_consent', 'category': 'unknown'}}
                    for i in range(size)]
            data = self.data(self.finding('PDN-011', evidence=rows),
                             self.finding('INF-003', evidence=rows))
            registry = report_evidence.index(data)
            self.assertEqual(len(registry['evidence']), size)
            self.assertNotIn('private', json.dumps(registry))
            for output in (render.report_md(data), render.report_html(data),
                           render.plan_md(data), render.plan_html(data)):
                self.assertLess(output.count('receiver.example'), 12)
                self.assertLess(output.count('Доказательство: см.'), 2)
            self.assertLessEqual(render.plan_md(data).count('receiver.example'), 1)
            self.assertIn('Общий набор сетевых доказательств', render.plan_md(data))

    def test_identical_repeated_requests_remain_distinct_in_registry(self):
        request = {'kind': 'request', 'detail': 'GET: назначение не установлено',
                   'url': 'https://receiver.example/collect?secret=private',
                   'context': {'phase': 'before_consent', 'page': 'https://example.ru/'}}
        data = self.data(self.finding('PDN-011', evidence=[request] * 3),
                         self.finding('INF-003', evidence=[request] * 3))
        registry = report_evidence.index(data)
        self.assertEqual(len(registry['evidence']), 3)
        self.assertEqual(registry['groups'][0]['count'], 3)
        page = report_evidence.html_page(registry, data['target'])
        self.assertIn('../artifacts/network/before_consent.jsonl', page)
        self.assertNotIn('private', page)

    def test_grouping_preserves_consent_phase_and_context_conflicts(self):
        rows = [{'kind': 'request', 'detail': 'POST: candidate', 'url': 'https://receiver.example/collect',
                 'context': {'method': 'POST', 'category': 'unknown', 'phase': phase,
                             'metadata_complete': complete, 'observation_version': 2}}
                for phase, complete in [('before_consent', True), ('after_consent', True),
                                        ('after_reject', True), ('after_reject', False)]]
        registry = report_evidence.index(self.data(self.finding('PDN-011', evidence=rows)))
        self.assertEqual(len(registry['groups']), 4)
        self.assertEqual(len(registry['evidence']), 4)

    def test_missing_collection_provenance_downgrades_report(self):
        data = self.data(self.finding('PDN-011', status='PASS'))
        data.pop('collection')
        for output in (render.report_md(data), render.report_html(data)):
            self.assertIn('Ограниченный снимок', output)
            self.assertIn('НЕ УДАЛОСЬ ПРОВЕРИТЬ', output)

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
        self.assertEqual([r.status for r in rows], ['UNKNOWN', 'UNKNOWN'])

    def test_current_complete_findings_and_missing_li(self):
        data = self.data(*(self.finding(r, status='NA') for r in self.ctx.rules))
        self.assertEqual(provenance_issues(data), [])
        data['findings'] = [f for f in data['findings'] if f['rule_id'] != 'LI-001']
        self.assertIn('LI-001', ' '.join(provenance_issues(data)))

    def test_mixed_raw_observation_versions_limit_report(self):
        data = self.data(self.finding('PDN-004', status='FAIL'))
        self.assertEqual(collection_issues(data), [])
        data['collection']['network_observations']['versions'] = ['1', '2']
        self.assertTrue(collection_issues(data))
        self.assertEqual(render.public_data(data)['findings'][0]['status'], 'UNKNOWN')

    def test_partial_network_warns_without_erasing_direct_findings(self):
        data = self.data(self.finding('PDN-004', status='FAIL'))
        data['collection']['network']['complete'] = False
        self.assertEqual(collection_issues(data), [])
        self.assertTrue(collection_warnings(data))
        self.assertEqual(render.public_data(data)['findings'][0]['status'], 'FAIL')
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
