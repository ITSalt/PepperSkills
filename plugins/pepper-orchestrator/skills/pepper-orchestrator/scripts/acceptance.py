"""File-backed automatic verification and explicit live acceptance, shared by clients.

These records are evidence pointers, not a security boundary against a malicious
workspace writer. Only the coordinator may write them. All callers hold the short
workspace transaction when recording results.
"""
import hashlib
import json
from pathlib import Path
import re

import safe_edit

LIVE = '<!-- orch:live -->'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def criteria(text):
    section = re.search(r'(?ms)^## 3\.[^\n]*\n(.*?)(?=^## |\Z)', text)
    if not section:
        return []
    return [m.group(1).strip() for m in re.finditer(r'(?m)^\s*\d+\.\s+(.+)', section.group(1))]


def concrete(value):
    value = value.strip().strip('`')
    return bool(value) and not re.search(r'<|\b(TODO|TBD|pending|placeholder)\b|^[-—]+$', value, re.I)


def live_table(items):
    rows = [LIVE, '', '| # | Criterion | Expected | Actual | Evidence | Verdict |',
            '|---|-----------|----------|--------|----------|---------|']
    for n, item in enumerate(items, 1):
        rows.append(f'| {n} | {item.replace(chr(124), chr(92) + chr(124))} | TODO | TODO | TODO | WAIT |')
    return '\n'.join(rows) + '\n'


def record(root, report, wp, env, sha, verdict, items, rows):
    text = report.read_text(encoding='utf-8')
    safe_edit.create(Path(str(report) + '.checks.json'), json.dumps({
        'wp': wp, 'env': env, 'sha': sha, 'automatic': verdict,
        'report': report.relative_to(root).as_posix(), 'criteria': items,
        'automatic_digest': digest(text.split(LIVE)[0]), 'checks': rows,
    }, ensure_ascii=False, indent=2) + '\n')


def load(root, report, wp, env, sha):
    root, report = Path(root).resolve(), Path(report).resolve()
    report.relative_to(root / 'reports')  # never attest a foreign report
    latest = sorted((root / 'reports').glob(f'verify-{wp}-{env}-*.md.checks.json'),
                    key=lambda p: (p.stat().st_mtime_ns, str(p)))
    if not latest or latest[-1].resolve() != Path(str(report) + '.checks.json').resolve():
        raise ValueError('a newer automatic verification exists; finalize its report')
    data = json.loads(Path(str(report) + '.checks.json').read_text(encoding='utf-8'))
    if (data['wp'], data['env'], data['sha'], data['report']) != (wp, env, sha, report.relative_to(root).as_posix()):
        raise ValueError('verification report belongs to a different WP, environment or SHA')
    text = report.read_text(encoding='utf-8')
    if digest(text.split(LIVE)[0]) != data['automatic_digest']:
        raise ValueError('automatic verification section changed; run verify again')
    return data, text


def validate_live(data, text, verdict='PASS'):
    items = data['criteria']
    if not items or not all(concrete(x) for x in items):
        raise ValueError('WP needs concrete numbered acceptance criteria in section 3; run verify again')
    if LIVE not in text:
        raise ValueError('report has no live acceptance table')
    rows = []
    for line in text.split(LIVE, 1)[1].splitlines():
        cells = [x.strip().replace('\\|', '|') for x in re.split(r'(?<!\\)\|', line.strip())[1:-1]]
        if cells and cells[0].isdigit():
            rows.append(cells)
    if len(rows) != len(items):
        raise ValueError('record every acceptance criterion exactly once')
    for n, (item, cells) in enumerate(zip(items, rows), 1):
        if len(cells) != 6 or cells[0] != str(n) or cells[1] != item or cells[5] not in ('PASS', 'FAIL', 'WAIT'):
            raise ValueError(f'live criterion {n} needs matching text and a verdict')
        if verdict == 'PASS' and (cells[5] != 'PASS' or not all(concrete(x) for x in cells[2:5])):
            raise ValueError(f'live criterion {n} needs matching text, expected/actual/evidence and PASS')
    if verdict == 'FAIL' and not any(c[5] == 'FAIL' and all(concrete(x) for x in c[2:5]) for c in rows):
        raise ValueError('FAIL needs an observed failed criterion with concrete evidence; use WAIT for unavailable tools')


def finalized(root, wp, env, sha):
    """Latest automatic record for this exact revision must have an intact PASS attestation."""
    candidates = []
    for path in (Path(root) / 'reports').glob('*.checks.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if (data['wp'], data['env']) == (wp, env):
                candidates.append((path.stat().st_mtime_ns, path, data))
        except (OSError, ValueError, KeyError):
            if path.name.startswith(f'verify-{wp}-{env}-'):
                return False  # never fall back to an older PASS after corrupt evidence
            continue
    if not candidates:
        return False
    _, path, data = max(candidates, key=lambda x: (x[0], str(x[1])))
    try:
        report = Path(root) / data['report']
        data, text = load(root, report, wp, env, sha)
        final = json.loads(Path(str(report) + '.final.json').read_text(encoding='utf-8'))
        return data['automatic'] == 'PASS' and final == {
            'wp': wp, 'env': env, 'sha': sha, 'verdict': 'PASS', 'report_digest': digest(text)}
    except (OSError, ValueError, KeyError):
        return False
