"""Regression fixtures for the 2026-09-21 audit; no network required."""
import json
import copy
import re
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict
from unittest.mock import patch

import detect
import collect
import render
import registries
from selftest import artifacts_fixture
from processing_basis import classify_activities


VERIFIED_COLLECTION = {
    'collector': {'name': 'pepper-ru-web-compliance', 'version': '2.4.0', 'observation_version': 2},
    'started_at': '2026-09-21', 'finished_at': '2026-09-21',
    'network': {'mode': 'managed', 'complete': True, 'egress': {'ip': '203.0.113.1', 'country': 'RU'}},
    'network_observations': {'count': 1, 'versions': ['2']},
}


class AuditRegression(unittest.TestCase):
    def test_sitemap_index_yields_pages_not_xml_files(self):
        docs = {
            'https://example.ru/sitemap.xml': '<sitemapindex><loc>https://example.ru/child.xml</loc></sitemapindex>',
            'https://example.ru/child.xml': '<urlset><loc>https://example.ru/privacy</loc><loc>https://example.ru/about</loc></urlset>',
        }
        with patch.object(collect, 'fetch_text', side_effect=lambda url: (200, docs.get(url, ''))):
            self.assertEqual(collect.discover_from_sitemap('https://example.ru'),
                             ['https://example.ru/privacy', 'https://example.ru/about'])

    def test_page_budget_uses_observed_links_not_guessed_paths(self):
        with patch.object(collect, 'discover_from_sitemap', return_value=[]):
            self.assertEqual(collect.build_page_list('https://example.ru', 20),
                             ['https://example.ru/'])

    def test_successful_registry_source_does_not_report_guidance_as_error(self):
        spec = registries.RegistrySpec('example', 'Example', [registries.Source(
            'https://example.ru/list', 'official',
            lambda _: [registries.Entry('1', 'org', 'Example')],
            note='Отвечает только с российских адресов')])
        with patch.object(registries, 'fetch_source_bytes', return_value=b'fixture'):
            result = registries.fetch_live(spec)
        self.assertEqual(len(result.entries), 1)
        self.assertIsNone(result.error)

    def test_generic_registry_alias_needs_name_context(self):
        data = registries.RegistryData(entries=[{
            'id': 'example', 'kind': 'org', 'name': 'Служба поддержки',
            'aliases': ['Служба поддержки']}])
        matcher = registries.RegistryMatcher(data)
        self.assertEqual(matcher.find('Обратитесь в службу поддержки по телефону'), [])
        quoted = matcher.find('Организация «Служба поддержки» упомянута в статье')
        self.assertEqual(len(quoted), 1)
        self.assertEqual(quoted[0].confidence, 'low')

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
            self.assertEqual([f.status for f in detect.detect_banner(ctx)], ['NA', 'NA', 'NA'])
            ctx.banner['candidates'][0] = {'text': 'Cookie согласие', 'buttons': [{'text': 'Принять'}]}
            rows = {f.rule_id: f.status for f in detect.detect_banner(ctx)}
            self.assertEqual((rows['CK-002'], rows['CK-007']), ('WARN', 'WARN'))
            ctx.degraded = True
            self.assertEqual(detect.detect_legitimate_interest(ctx)[0].status, 'UNKNOWN')

    def tracked(self, ctx):
        ctx.net['before_consent'] = [{'url': 'https://mc.yandex.ru/watch/1'}]
        return detect.detect_gating(ctx)[0]

    def test_evidence_and_acceptance(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            f = asdict(self.tracked(ctx))
            self.assertEqual(f['status'], 'FAIL')
            data = {'target': ctx.target, 'generated_at': '2026-09-21', 'findings': [f], 'pages_analysed': 1,
                    'pages': [{'slug': 'index', 'url': 'https://example.ru/privacy'}],
                    'collection': VERIFIED_COLLECTION}
            for report in (render.report_md(data), render.report_html(data), render.plan_md(data), render.plan_html(data)):
                self.assertIn('https://mc.yandex.ru/watch/1', report)
                self.assertIn('Загружать перечисленные теги только после согласия', report)
            self.assertIn('Журнал первого визита', render.acceptance(f))

    def review(self, f, status, activities=True):
        activity = f.processing_activities[0]
        return {'status': status, 'reviewer': 'Fixture reviewer', 'reviewed_at': '2026-09-26',
                'evidence': ['BASIS_PROOF_913'],
                'activities': [{'service': activity['service'], 'purpose': activity['purpose'],
                                'verified_basis': 'consent', 'evidence': ['Fixture policy']}] if activities else []}

    def attach(self, ctx, f, item):
        (ctx.dir / 'semantic-review.json').write_text(json.dumps({'target': ctx.target,
            'artifacts_sha256': detect.artifact_fingerprint(ctx), 'rules': {f.rule_id: item}}))
        detect.attach_semantic_reviews(ctx, [f])

    def test_review_bound_to_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            f = self.tracked(ctx)
            self.attach(ctx, f, self.review(f, 'PASS'))
            self.assertEqual(f.semantic_review['status'], 'PASS')
            self.assertEqual(f.status, 'FAIL')
            (ctx.dir / 'pages/index/text.txt').write_text('changed')
            detect.attach_semantic_reviews(ctx, [f])
            self.assertIsNone(f.semantic_review)

    def test_review_drives_report_without_changing_machine_observation(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            f = self.tracked(ctx)
            for status in ('PASS', 'FAIL', 'WARN', 'UNKNOWN', 'NA'):
                with self.subTest(status=status):
                    self.attach(ctx, f, self.review(f, status))
                    row = asdict(f)
                    data = {'target': ctx.target, 'generated_at': '2026-09-26',
                            'pages_analysed': 1, 'findings': [row], 'collection': VERIFIED_COLLECTION}
                    unchanged = copy.deepcopy(data)
                    summary = render.summarise(data)
                    bucket = {'PASS': 'passes', 'FAIL': 'fails', 'WARN': 'warns',
                              'UNKNOWN': 'unknowns', 'NA': 'nas'}[status]
                    self.assertEqual(len(summary[bucket]), 1)
                    for layout in ('stacked', 'twoline', 'classic'):
                        report = render.report_html(data, layout)
                        self.assertIn(f"badge {status}", report)
                        if status in ('FAIL', 'WARN'):
                            self.assertIn('Машинное наблюдение: FAIL', report)
                            self.assertIn('BASIS_PROOF_913', report)
                        ids = re.findall(r'''id=['"]([^'"]+)['"]''', report)
                        self.assertEqual(len(ids), len(set(ids)))
                        for target in re.findall(r'''href=['"]#([^'"]+)['"]''', report):
                            self.assertIn(target, ids)
                    tasks = 1 if status in ('FAIL', 'WARN') else 0
                    self.assertIn(f'**Задач:** {tasks}', render.plan_md(data))
                    self.assertEqual(data, unchanged)
                    self.assertEqual(f.status, 'FAIL')

            # Review of CK-003 cannot silently close another rule in its group.
            self.attach(ctx, f, self.review(f, 'PASS'))
            other = detect.mk(ctx, 'CK-001', 'FAIL', 'Unreviewed banner',
                              [detect.Evidence(kind='dom', detail='баннера нет')])
            data = {'target': ctx.target, 'generated_at': '2026-09-26', 'pages_analysed': 1,
                    'findings': [asdict(f), asdict(other)], 'collection': VERIFIED_COLLECTION}
            plan = render.plan_md(data)
            self.assertIn('**Правила:** CK-001', plan)
            self.assertNotIn('CK-003', plan)

            # Incomplete service coverage cannot close the rule.
            self.attach(ctx, f, self.review(f, 'PASS', activities=False))
            self.assertIsNone(f.semantic_review)
            self.assertEqual(render.report_status(asdict(f)), 'FAIL')

    def test_quote_keeps_qualifying_condition_after_300_characters(self):
        with tempfile.TemporaryDirectory() as raw:
            ctx = self.context(Path(raw))
            quote = 'Полное описание обработки. ' * 16 + 'Исключение: при отказе аналитика отключается.'
            f = asdict(detect.mk(ctx, 'CK-003', 'WARN', 'Трекеры до выбора при заявленном законном интересе',
                [detect.Evidence(kind='text', detail='Цитата с условием', snippet=quote,
                                 url='https://example.ru/privacy')]))
            data = {'target': ctx.target, 'generated_at': '2026-09-26',
                    'findings': [f], 'pages_analysed': 1, 'collection': VERIFIED_COLLECTION}
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
