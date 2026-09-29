"""One safe, stable evidence index shared by all report formats."""
import hashlib
import html
import json
import re
from collections import defaultdict
from urllib.parse import quote

from network_evidence import safe_url


def clean(item):
    item = json.loads(json.dumps(item, ensure_ascii=False))
    if item.get('url'):
        item['url'] = safe_url(item['url'])
    for field in ('detail', 'snippet'):
        if item.get(field):
            value = re.sub(r'https?://[^\s<>`]+', lambda m: safe_url(m[0]), item[field])
            value = re.sub(r'(?i)\b(bearer\s+)\S+', r'\1[redacted]', value)
            value = re.sub(r'(?i)\b((?:api[_-]?key|token|secret|password|authorization|cookie)\s*[:=]\s*)[^\s;,&]+',
                           r'\1[redacted]', value)
            item[field] = value
    context = item.get('context') or {}
    context = {k: context[k] for k in ('request_id', 'page', 'phase', 'frame', 'method',
                                      'content_type', 'resource_type', 'is_navigation',
                                      'category', 'classification_basis',
                                      'observation_version', 'metadata_complete') if k in context}
    original = item.get('context') or {}
    if isinstance(original.get('initiator'), dict):
        context['initiator_type'] = original['initiator'].get('type')
        context['initiator_script'] = safe_url(original['initiator'].get('script_url'))
    if isinstance(original.get('payload_shape'), dict):
        context['payload_shape'] = {k: original['payload_shape'].get(k) for k in ('known_fields', 'body_inspected', 'values_retained')}
    if isinstance(original.get('form_relation'), dict):
        context['form_relation'] = {k: original['form_relation'].get(k) for k in ('confirmed', 'source', 'reason')}
        context['form_relation']['action'] = safe_url(original['form_relation'].get('action'))
    item['context'] = context
    if context.get('page'):
        context['page'] = safe_url(context['page'])
    # Request bodies, cookies and credentials are never report evidence.
    for field in ('headers', 'body', 'post_data', 'cookie', 'authorization'):
        item.pop(field, None)
    phase = context.get('phase')
    if phase in ('before_consent', 'after_consent', 'before_reject', 'after_reject', 'revisit_reject', 'walk'):
        item['source_artifact'] = f'artifacts/network/{phase}.jsonl'
    return item


def stable_id(prefix, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return prefix + '-' + hashlib.sha256(raw).hexdigest()[:12]


def indexed_items(finding):
    """Distinguish identical repeated observations, while sharing IDs across rules."""
    occurrences = defaultdict(int)
    for raw in finding.get('evidence', []) + finding.get('basis_evidence', []):
        item = clean(raw)
        fingerprint = stable_id('F', item)
        ordinal = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        yield stable_id('E', [item, ordinal]), item


def group_key(item):
    context = item.get('context') or {}
    detail = item.get('detail') or ''
    method = context.get('method') or (detail.split(':', 1)[0] if ':' in detail else '?')
    return (method, item.get('url') or '', context.get('category') or 'unknown',
            context.get('phase') or 'unknown', context.get('metadata_complete'),
            context.get('observation_version'), context.get('classification_basis'))


def index(data):
    evidence = {}
    groups = defaultdict(lambda: {'ids': [], 'pages': set(), 'rules': set()})
    for finding in data.get('findings', []):
        for eid, item in indexed_items(finding):
            evidence[eid] = item
            if item.get('kind') == 'request':
                key = group_key(item)
                group = groups[key]
                if eid not in group['ids']:
                    group['ids'].append(eid)
                if (item.get('context') or {}).get('page'):
                    group['pages'].add(item['context']['page'])
                group['rules'].add(finding['rule_id'])
    result = []
    for key, value in groups.items():
        result.append({'id': stable_id('G', key), 'method': key[0], 'url': key[1],
                       'category': key[2], 'phase': key[3], 'metadata_complete': key[4],
                       'observation_version': key[5], 'classification_basis': key[6],
                       'count': len(value['ids']),
                       'pages': sorted(value['pages']), 'rules': sorted(value['rules']),
                       'evidence_ids': value['ids']})
    return {'schema_version': 1, 'groups': sorted(result, key=lambda g: g['id']),
            'evidence': evidence}


def request_groups(finding):
    groups = defaultdict(lambda: {'ids': set(), 'pages': set()})
    for eid, item in indexed_items(finding):
        if item.get('kind') != 'request':
            continue
        key = group_key(item)
        group = groups[key]
        group['ids'].add(eid)
        if (item.get('context') or {}).get('page'):
            group['pages'].add(item['context']['page'])
    return sorted(({'id': stable_id('G', key), 'method': key[0], 'url': key[1],
                    'category': key[2], 'phase': key[3], 'metadata_complete': key[4],
                    'observation_version': key[5], 'classification_basis': key[6],
                    'count': len(value['ids']),
                    'pages': len(value['pages']), 'page_examples': sorted(value['pages'])[:2]}
                   for key, value in groups.items()),
                  key=lambda row: (-row['count'], row['id']))


def summary_lines(finding, limit=5):
    groups = request_groups(finding)
    categories = {'unknown': 'назначение не установлено', 'form_submission': 'отправка формы подтверждена',
                  'analytics_candidate': 'предположительно аналитика', 'security_report': 'отчёт CSP',
                  'security_report_candidate': 'предположительно отчёт CSP'}
    phases = {'before_consent': 'до согласия', 'after_consent': 'после согласия',
              'before_reject': 'до отказа', 'after_reject': 'после отказа',
              'revisit_reject': 'повторный визит после отказа', 'walk': 'обход'}
    fullness = {True: 'полный', False: 'частичный', None: 'не установлена'}
    lines = [f"{g['id']}: {g['method']} {g['url']} — "
             f"{categories.get(g['category'], g['category'])}, {phases.get(g['phase'], g['phase'])}; "
             f"наблюдений: {g['count']}, страниц: {g['pages']}; контекст: {fullness[g['metadata_complete']]}" +
             (f"; примеры: {', '.join(g['page_examples'])}" if g['page_examples'] else '')
             for g in groups[:limit]]
    if len(groups) > limit:
        lines.append(f"Ещё {len(groups) - limit} групп: evidence.html / evidence.json.")
    if groups:
        lines.append("Полный реестр: evidence.html / evidence.json; ID групп сохранены при печати.")
    return lines


def html_page(registry, target, artifact_href='../artifacts'):
    out = ['<!doctype html><html lang="ru"><meta charset="utf-8">',
           '<title>Реестр доказательств</title>',
           '<style>body{font:16px/1.5 system-ui;max-width:72rem;margin:3rem auto;padding:0 1rem}'
           'section{border-top:1px solid #ccc;padding:1rem 0}li{overflow-wrap:anywhere}'
           'code{background:#eee;padding:.1rem .3rem}</style>',
           '<h1>Реестр доказательств</h1>', f'<p>{html.escape(target)}</p>']
    for group in registry['groups']:
        out.append(f'<section id="{group["id"]}"><h2>{group["id"]}: '
                   f'{html.escape(group["method"])} {html.escape(group["url"])}</h2>')
        out.append(f'<p>{html.escape(group["category"])} · {html.escape(group["phase"])} · '
                   f'контекст: {html.escape(str(group["metadata_complete"]))} · '
                   f'{group["count"]} наблюдений · правила {html.escape(", ".join(group["rules"]))}</p><ol>')
        for eid in group['evidence_ids']:
            item = registry['evidence'][eid]
            source = item.get('source_artifact') or ''
            source_link = (f'<a href="{html.escape(quote(artifact_href, safe="/.-_") + "/" + quote(source.removeprefix("artifacts/"), safe="/.-_"))}">'
                           f'{html.escape(source)}</a>' if source else 'источник не установлен')
            out.append(f'<li id="{eid}"><code>{eid}</code> '
                       f'{html.escape(item.get("detail") or "")} · '
                       f'{html.escape(json.dumps(item.get("context") or {}, ensure_ascii=False, sort_keys=True))} · '
                       f'{source_link}</li>')
        out.append('</ol></section>')
    other = [(eid, item) for eid, item in registry['evidence'].items() if item.get('kind') != 'request']
    if other:
        out.append('<section><h2>Другие доказательства</h2><ol>')
        for eid, item in sorted(other):
            out.append(f'<li id="{eid}"><code>{eid}</code> '
                       f'{html.escape(json.dumps(item, ensure_ascii=False, sort_keys=True))}</li>')
        out.append('</ol></section>')
    out.append('</html>')
    return ''.join(out)
