"""Browser acceptance on intercepted synthetic pages only; no live-site requests.

PYTHONPATH=<playwright packages> python scripts/test_network_browser.py --out /tmp/evidence-qa
Kept separate from the offline release suite, which prohibits browser processes.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import sync_playwright
import collect
import detect
import render
from report_provenance import current_producer
from selftest import artifacts_fixture
from test_network_evidence import SYNTHETIC_URLS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--browser-executable', help='Optional existing Chromium executable for local QA')
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser_executable)
        context = browser.new_context()
        def fulfill(route):
            url = route.request.url
            if '/form' in url:
                method = 'POST' if 'post' in url else 'GET'
                body = f'''<form method="{method}" action="/receive"><input name="email" value="PRIVATE_EMAIL"><button>Send</button></form>
                <script>fetch('/fields.php', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{email:'PRIVATE_EMAIL'}})}})</script>'''
            elif '/frame' in url:
                body = '<iframe src="/form-get"></iframe>'
            else:
                body = '<p>Synthetic response</p>'
            route.fulfill(status=200, content_type='text/html', body=body)
        context.route('**/*', fulfill)
        recorder = collect.NetworkRecorder()
        for method in ('get', 'post'):
            page = context.new_page()
            recorder.attach(page, 'walk', 'https://fixture.test/form-' + method)
            page.goto('https://fixture.test/form-' + method)
            page.get_by_role('button', name='Send').click()
            page.wait_for_url('**/receive*')
            page.wait_for_timeout(100)
            recorder.detach()
            page.close()
        confirmed = [r for r in recorder.requests if r.get('form_relation')]
        assert {r['method'] for r in confirmed} == {'GET', 'POST'}, recorder.requests
        ajax = [r for r in recorder.requests if '/fields.php' in r['url']]
        assert len(ajax) == 2 and all(not r.get('form_relation') for r in ajax)
        assert all(r['initiator']['type'] == 'script' for r in ajax), ajax
        assert all(r['payload_shape']['known_fields'] == ['email'] for r in ajax)
        assert all('PRIVATE' not in json.dumps(r['payload_shape']) for r in ajax)
        # Frame attribution and repeated attach/detach must work independently.
        page = context.new_page()
        recorder.attach(page, 'frame_fixture', 'https://fixture.test/frame')
        page.goto('https://fixture.test/frame')
        page.frame_locator('iframe').get_by_role('button', name='Send').click()
        page.wait_for_timeout(150)
        recorder.detach()
        page.close()
        frame_ajax = [r for r in recorder.requests if r['phase'] == 'frame_fixture' and '/fields.php' in r['url']]
        assert frame_ajax and all(r['frame'].endswith('/form-get') for r in frame_ajax), frame_ajax
        # Foreign iframe sessions may not expose CDP navigation attribution. Never infer it.
        assert len({r['request_id'] for r in recorder.requests}) == len(recorder.requests)
        context.close()

        with tempfile.TemporaryDirectory() as raw:
            ctx = detect.Context(artifacts_fixture(Path(raw), text='Synthetic QA, not a site audit',
                                  dom='<html></html>', url='https://synthetic.example.test'))
            ctx.pages[0]['forms'] = []
            ctx.net['walk'] = [{'url': u, 'method': 'POST', 'resource_type': 'xhr'} for u in SYNTHETIC_URLS]
            rows = {rid: detect.mk(ctx, rid, 'NA', 'Вне синтетического сценария; сайт не проверялся') for rid in ctx.rules}
            for f in detect.detect_endpoints(ctx): rows[f.rule_id] = f
            f = rows['PDN-004']
            f.status = 'PASS'
            f.summary = 'Во всех формах есть чекбокс'
            f.semantic_review = {'status': 'FAIL', 'summary': 'Синтетический дефект: чекбокс не связан с формой.',
                'reviewer': 'Synthetic QA', 'reviewed_at': '2026-09-28', 'evidence': ['fixture DOM: #lead'],
                'action': {'kind': 'fix', 'text': 'Связать чекбокс с формой #lead.',
                    'acceptance': 'Отправка формы учитывает состояние связанного чекбокса.',
                    'evidence': ['fixture DOM: #lead'], 'locations': ['Тестовый компонент #lead']}}
            data = {'target': ctx.target, 'generated_at': '2026-09-28', 'pages_analysed': 1,
                    'producer': current_producer(), 'findings': [asdict(f) for f in rows.values()]}
            assert not render.provenance_issues(data)
            assert not render.consistency_issues(data)
            (out/'synthetic-findings.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
            md = render.combined_md(data)
            html = render.report_html(data)
            (out/'synthetic-report.md').write_text(md)
            (out/'synthetic-report.html').write_text(html)
            assert 'PRIVATE_TEST_ID' not in md + html
            assert 'Подключение ресурса' not in md + html
            assert 'P0-01' not in md + html
            assert 'V-01' in md and 'V-01' in html
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.goto((out/'synthetic-report.html').resolve().as_uri())
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            ids = page.locator('[id]').evaluate_all('(nodes) => nodes.map(n => n.id)')
            assert len(ids) == len(set(ids))
            for href in page.locator('a[href^="#"]').evaluate_all('(nodes) => nodes.map(n => n.getAttribute("href").slice(1))'):
                assert href in ids, href
            page.get_by_role('heading', name='Часть II. План проверки и исправлений', exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(out/'plan.png'))
            page.get_by_role('heading', name=re.compile(r'V-01\.')).locator('..').screenshot(path=str(out/'localization.png'))
            page.pdf(path=str(out/'synthetic-report.pdf'), format='A4', print_background=True,
                     margin={'top':'15mm', 'bottom':'15mm', 'left':'14mm', 'right':'14mm'})
            page.close()
        browser.close()
    result = {'native_form_methods': sorted(r['method'] for r in confirmed), 'ajax_requests': len(ajax),
              'frame_attribution': True, 'unknown_localization': True, 'md_html': True,
              'html_anchors': True, 'html_no_overflow': True, 'pdf_generated': True,
              'scope': 'Synthetic intercepted pages only; no metallik or external services audited'}
    (out/'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
