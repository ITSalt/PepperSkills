#!/usr/bin/env python3
"""Run the eight review fixtures and emit JSON results and individual reports."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'skills/pepper-ru-web-compliance/scripts'))
import detect
import registries
import render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    suite = json.loads((ROOT/'submission-tests.json').read_text())
    results = []
    # Review fixtures are deterministic and never fetch public registries.
    detect.Context.registry = lambda self, key: registries.RegistryData(registry=key,error='offline fixture')
    for scenario in suite['positive']+suite['negative']:
        fixture = json.loads((ROOT/scenario['fixture']).read_text())
        with tempfile.TemporaryDirectory() as raw:
            art = Path(raw)
            (art/'pages/privacy').mkdir(parents=True)
            (art/'network').mkdir()
            (art/'pages/privacy/text.txt').write_text(fixture['policy'])
            (art/'pages/privacy/dom.html').write_text('<html></html>')
            (art/'manifest.json').write_text(json.dumps({
                'target':'https://example.ru','degraded':fixture.get('degraded',False),
                'banner':fixture.get('banner',{'found':False}), 'refusal':fixture.get('refusal',{}),
                'pages':[{'url':'https://example.ru/privacy','final_url':'https://example.ru/privacy',
                          'slug':'privacy','status':200,'forms':[]}]}))
            for phase in ('before_consent','after_consent','after_reject','revisit_reject'):
                urls = fixture['requests'] if phase in ('before_consent','after_consent') else []
                (art/f'network/{phase}.jsonl').write_text(''.join(json.dumps({'url':u})+'\n' for u in urls))
            data = detect.run(detect.Context(art))
            findings = {f['rule_id']:f for f in data['findings']}
            checks = {rid:findings[rid]['status'] in statuses for rid,statuses in fixture['expected'].items()}
            if 'basis' in fixture:
                checks['processing_basis'] = findings['LI-001']['processing_basis'] == fixture['basis']
            checks['no_detector_errors'] = not any('завершился ошибкой' in f['summary'] for f in findings.values())
            directory = args.out/scenario['id']
            directory.mkdir(exist_ok=True)
            (directory/'findings.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
            (directory/'report.md').write_text(render.combined_md(data))
            results.append({'scenario':scenario['id'],'status':'PASS' if all(checks.values()) else 'FAIL',
                            'observed_statuses':{rid:findings[rid]['status'] for rid in fixture['expected']},'checks':checks})
            print(results[-1]['status'], scenario['id'])
    (args.out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return 0 if all(r['status']=='PASS' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
