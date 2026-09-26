"""Regression fixtures for the 2026-09-21 audit; no network required."""
import json
import copy
import re
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict

import detect
import render
from selftest import artifacts_fixture
from processing_basis import classify_activities


class AuditRegression(unittest.TestCase):
    def classify(self, text, observed=None):
        return classify_activities([('https://example.ru/privacy', text)], observed or [
            {'service': 'Метрика', 'purpose': 'analytics', 'requests': []}])

    def test_bases(self):
        fixtures = [
            ('Аналитика обрабатывается на основании согласия пользователя', 'consent_declared'),
            ('Пункт 7. Срок действия договора', 'UNKNOWN'),
            ('Мы не используем законный интерес как основание аналитики', 'UNKNOWN'),
            ('Законный интерес для защиты от мошенничества; аналитика по согласию', 'consent_declared'),
            ('Аналитика и реклама на основании законного интереса и согласия', 'UNKNOWN'),
            ('Аналитика на основании п. 7 ч. 1 ст. 6 ФЗ-152', 'legitimate_interest_declared'),
            ('Аналитика без согласия пользователя', 'UNKNOWN'),
            ('Метрика используется для защиты от мошенничества на основании законного интереса', 'UNKNOWN'),
            ('Аналитика по согласию. Аналитика на основании законного интереса.', 'UNKNOWN'),
        ]
        for text, expected in fixtures:
            with self.subTest(text=text):
                activity = self.classify(text)[0]
                self.assertEqual(activity['declared_basis'], expected)
                self.assertIsNone(activity['verified_basis'])

    def test_service_scope(self):
        observed = [{'service': s, 'purpose': 'analytics', 'requests': []} for s in ('Метрика', 'Google Analytics')]
        result = self.classify('Метрика: аналитика по согласию', observed)
        self.assertEqual([a['declared_basis'] for a in result], ['consent_declared', 'UNKNOWN'])

    def context(self, path):
        art = artifacts_fixture(path, text='Аналитика по согласию. BASIS_PROOF_913',
                                dom='<html></html>', url='https://example.ru/privacy')
        return detect.Context(art)

    def test_banner_and_degraded(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            ctx.banner = {'found': True, 'candidates': [{'text': 'Используем только необходимые cookie. Понятно',
                          'buttons': [{'text': 'Понятно'}]}]}
            self.assertEqual([f.status for f in detect.detect_banner(ctx)], ['NA', 'NA'])
            ctx.banner['candidates'][0] = {'text': 'Cookie согласие', 'buttons': [{'text': 'Принять'}]}
            self.assertEqual(detect.detect_banner(ctx)[1].status, 'WARN')
            ctx.degraded = True
            self.assertEqual(detect.detect_legitimate_interest(ctx)[0].status, 'UNKNOWN')

    def test_evidence_and_acceptance(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            ctx.net['before_consent'] = [{'url': 'https://mc.yandex.ru/watch/1'}]
            f = asdict(detect.detect_legitimate_interest(ctx)[0])
            f['basis_evidence'][0]['snippet'] += ' BASIS_PROOF_913'
            data = {'target': ctx.target, 'generated_at': '2026-09-21', 'findings': [f], 'pages_analysed': 1}
            for report in (render.report_md(data), render.report_html(data), render.plan_md(data), render.plan_html(data)):
                self.assertIn('https://example.ru/privacy', report)
            for report in (render.report_md(data), render.report_html(data)):
                self.assertIn('BASIS_PROOF_913', report)
                self.assertIn('UNVERIFIED', report)
            self.assertNotIn('возвращает статус PASS', render.acceptance(f))
            f['status'] = 'UNKNOWN'
            self.assertIn('BASIS_PROOF_913', render.report_html(data))

    def test_review_bound_to_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            ctx.net['before_consent'] = [{'url': 'https://mc.yandex.ru/watch/1'}]
            f = detect.detect_legitimate_interest(ctx)[0]
            activity = f.processing_activities[0]
            item = {'status': 'PASS', 'reviewer': 'Fixture reviewer', 'reviewed_at': '2026-09-21',
                    'evidence': ['Fixture evidence'], 'activities': [{
                        'service': activity['service'], 'purpose': activity['purpose'],
                        'verified_basis': 'consent', 'evidence': ['Fixture policy']}]}
            path = ctx.dir / 'semantic-review.json'
            path.write_text(json.dumps({'target': ctx.target, 'artifacts_sha256': detect.artifact_fingerprint(ctx),
                                        'rules': {'LI-001': item}}))
            detect.attach_semantic_reviews(ctx, [f])
            self.assertEqual(f.semantic_review['status'], 'PASS')
            self.assertEqual(f.status, 'WARN')
            (ctx.dir / 'pages/index/text.txt').write_text('changed')
            detect.attach_semantic_reviews(ctx, [f])
            self.assertIsNone(f.semantic_review)

    def test_review_drives_report_without_changing_machine_observation(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            ctx.net['before_consent'] = [{'url': 'https://mc.yandex.ru/watch/1'}]
            f = detect.detect_legitimate_interest(ctx)[0]
            activity = f.processing_activities[0]
            path = ctx.dir / 'semantic-review.json'
            for status in ('PASS', 'FAIL', 'UNKNOWN', 'NA'):
                with self.subTest(status=status):
                    item = {'status': status, 'reviewer': 'Fixture reviewer',
                            'reviewed_at': '2026-09-26', 'evidence': ['BASIS_PROOF_913'],
                            'activities': [{'service': activity['service'],
                                            'purpose': activity['purpose'],
                                            'verified_basis': 'consent',
                                            'evidence': ['Fixture policy']}]}
                    path.write_text(json.dumps({'target': ctx.target,
                        'artifacts_sha256': detect.artifact_fingerprint(ctx),
                        'rules': {'LI-001': item}}))
                    detect.attach_semantic_reviews(ctx, [f])
                    row = asdict(f)
                    data = {'target': ctx.target, 'generated_at': '2026-09-26',
                            'pages_analysed': 1, 'findings': [row]}
                    unchanged = copy.deepcopy(data)
                    summary = render.summarise(data)
                    bucket = {'PASS': 'passes', 'FAIL': 'fails', 'UNKNOWN': 'unknowns', 'NA': 'nas'}[status]
                    self.assertEqual(len(summary[bucket]), 1)
                    self.assertEqual(len(summary['warns']), 0)
                    for layout in ('stacked', 'twoline', 'classic'):
                        report = render.report_html(data, layout)
                        self.assertIn('BASIS_PROOF_913', report)
                        self.assertIn('Машинное наблюдение: WARN', report)
                        self.assertIn(f"badge {status}", report)
                        ids = re.findall(r'''id=['"]([^'"]+)['"]''', report)
                        self.assertEqual(len(ids), len(set(ids)))
                        for target in re.findall(r'''href=['"]#([^'"]+)['"]''', report):
                            self.assertIn(target, ids)
                    md = render.report_md(data)
                    self.assertIn('Машинное наблюдение: WARN', md)
                    self.assertIn('проверенное основание: consent', md)
                    self.assertNotIn('проверенное основание: UNKNOWN', md)
                    self.assertIn('Fixture policy', md)
                    self.assertIn('id="rule-li-001"', md)
                    if status in ('PASS', 'NA', 'UNKNOWN'):
                        self.assertIn('**Задач:** 0', render.plan_md(data))
                        self.assertNotIn('Уточнить основания и режим работы аналитики', render.plan_html(data))
                    else:
                        self.assertIn('**Задач:** 1', render.plan_md(data))
                    self.assertEqual(data, unchanged)
                    self.assertEqual(f.status, 'WARN')

            # Review of LI-001 cannot silently close another rule in its group.
            item['status'] = 'PASS'
            path.write_text(json.dumps({'target': ctx.target,
                'artifacts_sha256': detect.artifact_fingerprint(ctx), 'rules': {'LI-001': item}}))
            detect.attach_semantic_reviews(ctx, [f])
            data['findings'] = [asdict(f), asdict(detect.mk(ctx, 'CK-003', 'WARN', 'Unreviewed tracker'))]
            plan = render.plan_md(data)
            self.assertIn('**Правила:** CK-003', plan)
            self.assertNotIn('LI-001', plan)

            # Incomplete service coverage cannot close the rule.
            item['activities'] = []
            path.write_text(json.dumps({'target': ctx.target,
                'artifacts_sha256': detect.artifact_fingerprint(ctx), 'rules': {'LI-001': item}}))
            detect.attach_semantic_reviews(ctx, [f])
            self.assertIsNone(f.semantic_review)
            self.assertEqual(render.report_status(asdict(f)), 'WARN')

    def test_quote_keeps_qualifying_condition_after_300_characters(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            quote = 'Полное описание обработки. ' * 16 + 'Исключение: при отказе аналитика отключается.'
            f = asdict(detect.mk(ctx, 'CK-003', 'WARN', 'Нужно проверить условие',
                [detect.Evidence(kind='text', detail='Цитата с условием', snippet=quote,
                                 url='https://example.ru/privacy')]))
            data = {'target': ctx.target, 'generated_at': '2026-09-26',
                    'findings': [f], 'pages_analysed': 1}
            for report in (render.report_md(data), render.report_html(data)):
                self.assertIn(quote, report)

    def test_shared_remediation(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            findings = [asdict(detect.mk(ctx, r, 'WARN', r)) for r in ('CK-001', 'CK-003', 'LI-001')]
            grouped = render.grouped_actions(findings)
            self.assertEqual(len(grouped), 1)
            self.assertEqual(len(grouped[0]['members']), 3)
            for rid in ('CK-001', 'CK-003', 'LI-001'):
                self.assertIn(rid, render.acceptance(grouped[0]))


if __name__ == '__main__':
    unittest.main()
