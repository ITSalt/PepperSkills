"""Regression fixtures for the 2026-09-21 audit; no network required."""
import json
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
            f.semantic_review = None
            detect.attach_semantic_reviews(ctx, [f])
            self.assertIsNone(f.semantic_review)

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
