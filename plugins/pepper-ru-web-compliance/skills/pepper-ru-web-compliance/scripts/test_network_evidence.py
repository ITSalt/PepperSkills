"""Synthetic regression from the supplied metallik report; never a live site audit."""
from dataclasses import asdict
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

import collect
import detect
import render
from network_evidence import classify_request, payload_shape, safe_url
from report_provenance import current_producer
from review_contract import valid_action_review
from selftest import artifacts_fixture

SYNTHETIC_URLS = [
    'https://privacy-cs.mail.ru/fp/?id=PRIVATE_TEST_ID',
    'https://mod.calltouch.ru/set_external_data.php',
    'https://ab-ct.ru/fields.php',
    'https://mc.yandex.com/webvisor/17596246?email=PRIVATE_TEST_ID',
    'https://csp.withgoogle.com/csp/frame-ancestors/38fac9d5b82543fc4729580d18ff2d3d',
    'https://ogads-pa.clients6.google.com/$rpc/google.internal.onegoogle.asyncdata.v1.AsyncDataService/GetAsyncData',
]


class NetworkEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = detect.Context(artifacts_fixture(Path(self.tmp.name), text='Synthetic fixture',
                                  dom='<html></html>', url='https://example.ru'))
        self.ctx.pages[0]['forms'] = []

    def data(self, *rows):
        return {'target': self.ctx.target, 'generated_at': '2026-09-28', 'pages_analysed': 1,
                'producer': current_producer(), 'findings': [asdict(x) for x in rows],
                'collection': {'collector': {'name': 'pepper-ru-web-compliance', 'version': '2.4.0',
                                              'observation_version': 2},
                               'started_at': '2026-09-28', 'finished_at': '2026-09-28',
                               'network': {'mode': 'managed', 'complete': True,
                                           'egress': {'ip': '203.0.113.1', 'country': 'RU'}},
                               'network_observations': {'count': 1, 'versions': ['2']}}}

    def test_six_report_urls_and_csp_alone_never_prescribe_database_move(self):
        for urls in (SYNTHETIC_URLS, [SYNTHETIC_URLS[4]]):
            self.ctx.net['walk'] = [{'url': u, 'method': 'POST', 'resource_type': 'xhr'} for u in urls]
            rows = detect.detect_endpoints(self.ctx)
            # Без подтверждённой отправки формы за рубеж перенос базы не предписывается.
            self.assertNotEqual(rows[0].status, 'FAIL')
            self.assertIn(rows[0].status, ('EXTERNAL', 'WARN'))
            data = self.data(*rows)
            data['collection']['network_observations'] = {'count': len(urls), 'versions': ['1']}
            original = copy.deepcopy(data)
            for plan in (render.plan_md(data), render.plan_html(data)):
                self.assertNotIn('Первичную запись данных вести', plan)
                self.assertNotIn('PRIVATE_TEST_ID', plan)
                self.assertNotIn('semantic_review', plan)
            for report in (render.combined_md(data), render.report_html(data)):
                self.assertNotIn('PRIVATE_TEST_ID', report)
                self.assertIn('Ограниченный снимок', report)
            ids = re.findall(r'''id=['"]([^'"]+)['"]''', render.report_html(data))
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(data, original)

    def test_names_and_post_fields_do_not_prove_form_submission(self):
        for url in SYNTHETIC_URLS[:3]:
            req = {'url': url, 'method': 'POST', 'payload_shape': {'known_fields': ['email']}}
            self.assertEqual(classify_request(req)[0], 'unknown')
        self.assertEqual(classify_request({'url': SYNTHETIC_URLS[4]})[0], 'security_report_candidate')
        self.assertEqual(classify_request({'url': SYNTHETIC_URLS[4],
                         'content_type': 'application/csp-report'})[0], 'security_report')

    def test_confirmed_form_flows_survive_host_and_method_changes(self):
        for host in ('example.ru', 'mc.yandex.com', 'www.google-analytics.com', 'outside.test'):
            for method in ('GET', 'POST'):
                req = {'url': f'https://{host}/collect', 'method': method,
                       'resource_type': 'document', 'observation_version': 2,
                       'form_relation': {'confirmed': True, 'source': 'cdp:Page.frameRequestedNavigation'}}
                self.ctx.net['walk'] = [req]
                row = detect.detect_endpoints(self.ctx)[0]
                self.assertEqual(row.evidence[0]['context']['category'], 'form_submission')
                # Форма уходит на сервер с установленной иностранной страной — нарушение;
                # на свой, российский или неизвестный — вывод не выше вопроса владельцу.
                expected = 'FAIL' if host == 'www.google-analytics.com' else 'EXTERNAL'
                self.assertEqual(row.status, expected, host)

    def test_empty_and_russian_brand_do_not_prove_localization(self):
        for requests in ([], [{'url': 'https://mc.yandex.ru/watch/1', 'method': 'GET'}]):
            self.ctx.net['walk'] = requests
            self.assertEqual(detect.detect_endpoints(self.ctx)[0].status, 'EXTERNAL')

    def test_safe_payload_shape_never_retains_personal_values(self):
        body = json.dumps({'email': 'PRIVATE_EMAIL', 'phone': 'PRIVATE_PHONE',
                           'PRIVATE_DYNAMIC_KEY': 'SECRET', 'nested': {'message': 'PRIVATE_MESSAGE'}})
        shape = payload_shape('https://example.ru/a?name=PRIVATE_NAME', 'application/json', body)
        encoded = json.dumps(shape)
        self.assertNotIn('PRIVATE', encoded)
        self.assertNotIn('SECRET', encoded)
        self.assertEqual(shape['known_fields'], ['email', 'name', 'phone'])
        for content_type, body in [('application/x-www-form-urlencoded', 'email=PRIVATE_EMAIL'),
                                   ('multipart/form-data; boundary=secret', 'name="email"\r\nPRIVATE_EMAIL')]:
            self.assertNotIn('PRIVATE', json.dumps(payload_shape('https://e.test', content_type, body)))
        self.assertFalse(payload_shape('https://e.test', 'application/json', 'x' * 65537)['body_inspected'])
        self.assertNotIn('secret', safe_url('https://user:secret@example.ru/p?email=secret#secret'))

    def reviewed(self, status='FAIL', kind='fix'):
        f = detect.mk(self.ctx, 'PDN-004', 'PASS', 'Во всех формах есть чекбокс')
        f.semantic_review = {'status': status, 'summary': 'Чекбокс найден, но не относится к отправляемой форме.',
                             'reviewer': 'Synthetic reviewer', 'reviewed_at': '2026-09-28',
                             'evidence': ['dom.html: форма #lead и отдельный чекбокс #other'],
                             'action': {'kind': kind, 'text': 'Связать согласие с формой #lead.',
                                        'evidence': ['dom.html: форма #lead и отдельный чекбокс #other'],
                                        'acceptance': 'В сценарии отправки проверяется состояние связанного согласия.',
                                        'locations': ['Компонент формы #lead на /contact']}}
        return f

    def test_accepted_summary_action_and_acceptance_are_consistent(self):
        f = self.reviewed()
        data = self.data(f)
        for output in (render.combined_md(data), render.report_html(data)):
            self.assertIn(f.semantic_review['summary'], output)
            self.assertIn('Машинное наблюдение: PASS', output)
            self.assertIn('Во всех формах есть чекбокс', output)
            self.assertIn(f.semantic_review['action']['text'], output)
            self.assertIn(f.semantic_review['action']['acceptance'], output)
        for plan in (render.plan_md(data), render.plan_html(data)):
            self.assertNotIn('Во всех формах есть чекбокс', plan)
            self.assertIn('Компонент формы #lead на /contact', plan)
            self.assertNotIn('V-01', plan)
        self.assertEqual(f.status, 'PASS')

    def test_unknown_is_not_a_task_warn_carries_its_fix(self):
        f = detect.mk(self.ctx, 'PDN-011', 'UNKNOWN', 'Сбор не состоялся')
        f.fix_hint = 'UNSUPPORTED_REBUILD'
        for output in (render.plan_md(self.data(f)), render.plan_html(self.data(f))):
            self.assertNotIn('UNSUPPORTED_REBUILD', output)
        f = detect.mk(self.ctx, 'PDN-011', 'WARN', 'Иностранный получатель')
        f.fix_hint = 'Убрать иностранный сервис.'
        for output in (render.plan_md(self.data(f)), render.plan_html(self.data(f))):
            self.assertIn('Убрать иностранный сервис.', output)
            self.assertNotIn('V-01', output)

    def test_review_validation_and_artifact_binding(self):
        f = self.reviewed()
        item = f.semantic_review
        path = self.ctx.dir / 'semantic-review.json'
        def attach(review):
            path.write_text(json.dumps({'target': self.ctx.target,
                'artifacts_sha256': detect.artifact_fingerprint(self.ctx), 'rules': {f.rule_id: review}}))
            detect.attach_semantic_reviews(self.ctx, [f])
        attach(item)
        self.assertIsNotNone(f.semantic_review)
        for change in ('status', 'location', 'source', 'summary', 'acceptance'):
            broken = copy.deepcopy(item)
            if change == 'status': broken['status'] = 'UNKNOWN'
            elif change == 'location': broken['action']['locations'] = []
            elif change == 'source': broken['action']['evidence'] = ['invented source']
            elif change == 'summary': broken['summary'] = ''
            else: broken['action']['acceptance'] = ''
            attach(broken)
            self.assertIsNone(f.semantic_review, change)
        attach(item)
        (self.ctx.dir/'pages/index/text.txt').write_text('changed')
        detect.attach_semantic_reviews(self.ctx, [f])
        self.assertIsNone(f.semantic_review)

    def test_legacy_review_does_not_reuse_contradictory_machine_summary(self):
        f = self.reviewed()
        del f.semantic_review['summary']
        del f.semantic_review['action']
        for plan in (render.plan_md(self.data(f)), render.plan_html(self.data(f))):
            self.assertNotIn('Во всех формах есть чекбокс', plan)
            self.assertIn('P0-01', plan)

    def test_grouped_task_keeps_each_rule_acceptance(self):
        fixed = self.reviewed()
        fixed.rule_id = 'CK-003'
        pending = detect.mk(self.ctx, 'LI-001', 'WARN', 'Основание неизвестно')
        sections = render.plan_sections(self.data(fixed, pending))
        self.assertEqual(sum(len(rows) for _, _, rows in sections), 1)
        task = sections[0][2][0]
        self.assertIn(fixed.semantic_review['action']['acceptance'], render.acceptance(task))
        self.assertIn('LI-001', render.acceptance(task))

    def test_recorder_retains_requests_when_metadata_unavailable(self):
        class Page:
            url = 'https://example.ru'
            def on(self, name, handler): self.handler = handler
            def remove_listener(self, *args): pass
        class Request:
            url = 'https://example.ru/a?email=PRIVATE_EMAIL'
            method = 'GET'
            resource_type = 'fetch'
            def is_navigation_request(self): return False
        recorder = collect.NetworkRecorder()
        page = Page()
        recorder.attach(page, 'walk', page.url)
        page.handler(Request())
        recorder.detach()
        self.assertEqual(len(recorder.requests), 1)
        self.assertEqual(recorder.requests[0]['initiator']['type'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
