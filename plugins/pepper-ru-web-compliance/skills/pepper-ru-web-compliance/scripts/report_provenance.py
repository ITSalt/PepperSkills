"""Identify the installed skill and reject silently reused, incompatible findings."""
import hashlib
import json
from pathlib import Path
import re
from review_contract import valid_action_review

ROOT = Path(__file__).resolve().parent.parent


def current_producer():
    skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    version = re.search(r'^  version: (.+)$', skill, re.M).group(1).strip().strip("\"'")
    return {
        'skill_version': version,
        'detector_version': version,
        'rules_sha256': hashlib.sha256((ROOT / 'scripts/rules.yaml').read_bytes()).hexdigest(),
    }


def provenance_issues(data):
    issues = []
    expected = current_producer()
    producer = data.get('producer') or {}
    if producer != expected:
        issues.append('Версия или набор правил findings.json не совпадает с установленным скиллом; повторите detect.')
    rules = json.loads((ROOT / 'scripts/rules.json').read_text(encoding='utf-8'))['rules']
    required = {r['id'] for r in rules}
    present = {f['rule_id'] for f in data.get('findings', [])}
    missing = sorted(required - present)
    if missing:
        issues.append('Отсутствуют правила: ' + ', '.join(missing) + '.')
    return issues


def provenance_line(data):
    producer = data.get('producer') or {}
    collection = data.get('collection') or {}
    collector = collection.get('collector') or {}
    network = collection.get('network') or {}
    egress = network.get('egress') or {}
    return ('Скилл / детектор: ' + producer.get('skill_version', 'не указан') +
            ' / ' + producer.get('detector_version', 'не указан') +
            '; правила SHA-256: ' + producer.get('rules_sha256', 'не указан') +
            '; генератор: ' + current_producer()['skill_version'] +
            '; сборщик: ' + collector.get('version', 'не установлен') +
            '; формат наблюдений: ' + str(collector.get('observation_version', 'не установлен')) +
            '; транспорт: ' + str(network.get('mode', 'не установлен')) +
            '; выход: ' + str(egress.get('ip', 'не установлен')) +
            '; сетевой сбор выбранных страниц: ' + ({True: 'да', False: 'нет'}.get(network.get('complete'), 'не установлен')) +
            '; вне выборки внутренних ссылок: ' + str(data.get('unvisited_links', 'не установлено')) +
            '; снимки страниц: ' + ('неполны' if collection.get('visual_complete') is False
                                     else 'сохранены' if collection.get('visual_complete') is True
                                     else 'не установлено') + '.')


def collection_issues(data):
    collection = data.get('collection') or {}
    collector = collection.get('collector') or {}
    network = collection.get('network') or {}
    observations = collection.get('network_observations') or {}
    missing_origin = (collector.get('name') != 'pepper-ru-web-compliance' or
            collector.get('observation_version') != 2 or
            not collection.get('started_at') or not collection.get('finished_at') or
            not network.get('mode') or
            not (network.get('egress') or {}).get('ip') or
            not observations.get('count'))
    # Evidence objects are summaries and may omit request metadata. The raw
    # phase journals, counted by detect, are the authoritative format check.
    legacy = bool(observations.get('count')) and observations.get('versions') != ['2']
    if missing_origin or legacy:
        label = 'старый журнал сетевых наблюдений; ' if legacy else ''
        return [label + 'происхождение или полнота сетевого сбора не подтверждены; выводы по сайту предварительные.']
    return []


def collection_warnings(data):
    collection = data.get('collection') or {}
    warnings = []
    if (collection.get('network') or {}).get('complete') is not True:
        warnings.append('Сетевой обход неполон: выводы об отсутствии признаков ограничены доступными страницами.')
    if collection.get('visual_complete') is False:
        warnings.append('Часть снимков страниц не сохранена; визуальные признаки требуют ручной проверки.')
    unvisited = data.get('unvisited_links')
    if isinstance(unvisited, int) and unvisited > 0:
        warnings.append(f'Внутренних ссылок вне выборки: {unvisited}; '
                        'выводы об отсутствии признаков относятся только к посещённым страницам.')
    refusal = collection.get('refusal') or {}
    # Без баннера отказываться не от чего: незавершённый сценарий отказа тогда
    # ничего не ограничивает и только засоряет шапку отчёта.
    if refusal and collection.get('banner_found') is not False and (
            refusal.get('click_status') != 'clicked' or not refusal.get('revisit_completed')):
        warnings.append('Сценарий отказа от cookie не завершён; результат отказа и повторного визита не подтверждён.')
    return warnings


def consistency_issues(data):
    """Flag conflicting conclusions without rewriting detector or reviewer statuses."""
    rows = {f['rule_id']: f for f in data.get('findings', [])}
    def status(rule):
        f = rows.get(rule, {})
        return (f.get('semantic_review') or {}).get('status', f.get('status'))
    issues = []
    for row in rows.values():
        if row.get('semantic_review') and not valid_action_review(row['semantic_review']):
            issues.append(row['rule_id'] + ': неполное или несогласованное действие смысловой оценки.')
    basis = rows.get('PDN-013', {})
    review = basis.get('semantic_review') or {}
    consent_claimed = ('соглас' in basis.get('summary', '').lower() or
        any(a.get('verified_basis') == 'consent' for a in review.get('activities', [])))
    if status('PDN-013') == 'PASS' and status('PDN-008') == 'FAIL' and consent_claimed:
        issues.append('PDN-013 подтверждает согласие, но PDN-008 отмечает дефект согласия; согласуйте цели, формы и доказательства.')
    # Геолокация получателей (INF-003) наблюдается по IP и ASN; размещение баз
    # (PDN-011) снаружи не видно, и машинный PASS по нему невозможен.
    if status('PDN-011') == 'PASS' and not rows.get('PDN-011', {}).get('semantic_review'):
        issues.append('PDN-011: размещение баз не подтверждается машинным PASS; нужен ответ владельца в смысловой оценке.')
    return issues
