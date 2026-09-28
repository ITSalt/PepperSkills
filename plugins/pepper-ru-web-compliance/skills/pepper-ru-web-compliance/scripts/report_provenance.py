"""Identify the installed skill and reject silently reused, incompatible findings."""
import hashlib
import json
from pathlib import Path
import re
from review_contract import valid_action_review

ROOT = Path(__file__).resolve().parent.parent


def current_producer():
    skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
    version = re.search(r'^  version: (.+)$', skill, re.M).group(1).strip()
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
    return ('Скилл / детектор: ' + producer.get('skill_version', 'не указан') +
            ' / ' + producer.get('detector_version', 'не указан') +
            '; правила SHA-256: ' + producer.get('rules_sha256', 'не указан') +
            '; генератор: ' + current_producer()['skill_version'] + '.')


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
    for rule in ('PDN-011', 'INF-003'):
        if status(rule) == 'PASS' and not rows[rule].get('semantic_review'):
            issues.append(rule + ': география не подтверждается машинным PASS; приложите документированную смысловую оценку.')
    return issues
