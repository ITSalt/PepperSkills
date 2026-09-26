"""Live Chromium acceptance of independent refusal contexts, locally hosted.
Run: uv run --no-project --with playwright scripts/test_browser_scenarios.py --out /tmp/pepper-browser-qa
"""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import shutil

import collect
import detect
import render

HTML = '''<!doctype html><meta charset="utf-8"><title>Audit fixture</title>
<style>#cookie-banner {width:600px;padding:30px;background:#eee}button{padding:15px}</style>
<h1>Local consent fixture</h1><a href="/privacy">Privacy</a>
<div id="cookie-banner">Cookie: согласие на аналитику
<button onclick="choose('yes')">Принять</button><button DISABLED onclick="choose('no')">Отказаться</button></div>
<script>
const broken = BROKEN;
function track() { fetch('/track'); document.cookie='analytics=1; path=/'; }
function choose(v) { localStorage.setItem('choice',v); document.cookie='choice='+v+'; path=/';
document.getElementById('cookie-banner').style.display='none'; if(v==='yes'||broken) track(); }
if(localStorage.choice) { document.getElementById('cookie-banner').style.display='none';
if(localStorage.choice==='yes'||broken) track(); }
</script>'''


class Handler(BaseHTTPRequestHandler):
    mode = 'good'
    def log_message(self, *_):
        pass
    def do_GET(self):
        if self.path == '/track':
            body = b'ok'
        elif self.path == '/privacy':
            body = '<meta charset="utf-8">Аналитика по согласию пользователя BASIS_PROOF_913'.encode()
        else:
            body = HTML.replace('BROKEN', 'true' if self.mode == 'broken' else 'false').replace(
                'DISABLED', 'disabled' if self.mode == 'disabled' else '').encode()
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = f'http://127.0.0.1:{server.server_port}'
    results = []
    try:
        for mode in ('good', 'broken', 'disabled'):
            Handler.mode = mode
            out = args.out / mode
            out.mkdir(parents=True, exist_ok=True)
            if mode == 'disabled':
                shutil.copytree(args.out/'broken', out, dirs_exist_ok=True)
            manifest = collect.RunManifest(target=target, started_at=collect.now_iso())
            collect.browser_collect(target, [target+'/', target+'/privacy'], out, manifest, 10000)
            (out / 'manifest.json').write_text(json.dumps(asdict(manifest), ensure_ascii=False))
            ctx = detect.Context(out)
            # Local /track endpoint substitutes for a known analytics vendor.
            ctx.sig['trackers']['russian'].append({'vendor':'Fixture analytics','kind':'analytics',
                                                   'host':'127.0.0.1','paths':['/track'],'country':'RU'})
            tracked = lambda phase: any('/track' in r['url'] for r in ctx.net[phase])
            assert not tracked('before_consent'), 'accept requests leaked into before_consent'
            assert tracked('after_consent'), 'accept click request not captured'
            assert not tracked('before_reject'), 'refusal inherited acceptance'
            if mode == 'disabled':
                assert manifest.refusal['click_status'] == 'failed'
                assert not manifest.refusal['revisit_completed']
                assert not (out/'network/revisit_reject.jsonl').exists(), 'stale revisit evidence'
                assert not (out/'refusal-storage-state.json').exists(), 'stale refusal state'
            else:
                assert manifest.refusal['click_status'] == 'clicked'
                assert manifest.refusal['revisit_completed']
                for phase in ('after_reject', 'revisit_reject'):
                    assert tracked(phase) == (mode == 'broken'), (mode, phase)
                    cookie = any(c['name'] == 'analytics' for c in ctx.cookies[phase])
                    assert cookie == (mode == 'broken'), (mode, phase, 'cookie')
            finding = detect.detect_legitimate_interest(ctx)[0]
            if mode == 'broken':
                assert 'эффективность отказа не подтверждена' in finding.summary
                data = {'target':target, 'generated_at':'2026-09-21', 'findings':[asdict(finding)],
                        'pages_analysed':2}
                (args.out / 'findings.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
            results.append({'scenario':mode,'refusal':manifest.refusal,'status':'PASS',
                            'browser':manifest.browser})
            print(f'PASS {mode}', flush=True)
    finally:
        server.shutdown()
        server.server_close()
    (args.out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
