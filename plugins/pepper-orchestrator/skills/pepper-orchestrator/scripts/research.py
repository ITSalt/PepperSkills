"""Finite research rounds shared by foreground coordinators and the scheduler."""
import json
import time
from pathlib import Path

import runtime_commands as runtime
import state_io
import streams

MAX_CRITERIA = 8  # A research question that needs more is several packages.


def action(record):
    if not record:
        return 'define_research'
    return {'ready': 'continue_research', 'collecting': None, 'review': 'review_research',
            'revise': 'continue_research', 'partial': 'finalize_research', 'blocked': None,
            'accepted': 'finalize_research'}[record['phase']]


def evidence(ws, value):
    path = (ws.root / value).resolve()
    if not path.is_relative_to(ws.root.resolve()) or not path.is_file():
        raise streams.StreamError('research evidence must be an existing file inside the program workspace')
    return str(path.relative_to(ws.root.resolve()))


def remainder(ws, wp, verdict, remaining, payload):
    """Every unresolved criterion of a submitted result names its owner and the condition that resolves it."""
    owners = payload.get('remainder') or {}
    if set(owners) != set(remaining):
        raise streams.StreamError('name the owner of every unresolved criterion in remainder')
    rows = ws.wp_rows()
    for key, item in owners.items():
        if not isinstance(item, dict) or not item.get('condition'):
            raise streams.StreamError('remainder ' + key + ' needs the condition that resolves it')
        target = item.get('owner_wp')
        if verdict == 'partial' and (target not in rows or target == wp):
            raise streams.StreamError('partial result moves remainder ' + key + ' to another existing WP')
        if target and target not in rows:
            raise streams.StreamError('remainder owner ' + target + ' is not a WP of this program')


def update(ws, record, event, payload, wp=None):
    """Validate before replacing the caller's transactional registry record."""
    item = json.loads(json.dumps(record)) if record else None
    if event == 'contract':
        if item:
            raise streams.StreamError('research contract already exists; scope changes require a separately decided package')
        for field in ('question', 'decision', 'artifact', 'criteria'):
            if not payload.get(field):
                raise streams.StreamError('research contract requires ' + field)
        criteria = payload['criteria']
        if not isinstance(criteria, dict) or not all(isinstance(v, dict) and v.get('evidence_standard') and
                type(v.get('unknown_allowed')) is bool for v in criteria.values()):
            raise streams.StreamError('each criterion needs evidence_standard and boolean unknown_allowed')
        if len(criteria) > MAX_CRITERIA:
            raise streams.StreamError(f'at most {MAX_CRITERIA} criteria; split the question into separate packages')
        artifact = (ws.root / payload['artifact']).resolve()
        if not artifact.is_relative_to(ws.root.resolve()):
            raise streams.StreamError('research artifact must belong to the program workspace')
        return {'contract': payload, 'round': 0, 'phase': 'ready', 'open': list(criteria),
                'results': {}, 'events': {}, 'verdicts': [], 'updated_at': int(time.time())}
    if not item:
        raise streams.StreamError('define a research contract first')
    event_id = payload.get('id')
    if not event_id:
        raise streams.StreamError('research events require a stable id')
    previous = item['events'].get(event_id)
    if previous:
        if previous != {'event': event, 'payload': payload}:
            raise streams.StreamError('research event id was reused with different contents')
        return item
    if event == 'start':
        if item['phase'] not in ('ready', 'revise') or item['round'] >= 2:
            raise streams.StreamError('research collection is closed; submit a verdict or blocked remainder')
        tasks = payload.get('tasks', [])
        if not tasks or len({t.get('id') for t in tasks}) != len(tasks):
            raise streams.StreamError('research start requires uniquely identified tasks')
        for task in tasks:
            if not task.get('id') or task.get('criterion') not in item['open'] or not task.get('missing_fact') or not task.get('decision'):
                raise streams.StreamError('each task needs id, open criterion, missing_fact and affected decision')
        item.update(phase='collecting', round=item['round'] + 1, tasks=tasks, results={})
    elif event == 'result':
        task = payload.get('task')
        if item['phase'] != 'collecting' or task not in {t['id'] for t in item['tasks']} or task in item['results']:
            raise streams.StreamError('result does not match an outstanding research task')
        item['results'][task] = evidence(ws, payload['evidence'])
        if len(item['results']) == len(item['tasks']):
            item['phase'] = 'review'
    elif event == 'verdict':
        if item['phase'] not in ('review', 'ready', 'revise'):
            raise streams.StreamError('research verdict requires returned results or an existing deliverable')
        evidence(ws, item['contract']['artifact'])
        assessment = payload.get('criteria', {})
        if set(assessment) != set(item['contract']['criteria']):
            raise streams.StreamError('assess every frozen criterion')
        remaining = []
        for key, finding in assessment.items():
            if finding.get('status') not in ('satisfied', 'unknown', 'blocked') or not finding.get('reason'):
                raise streams.StreamError('each assessment needs status and reason')
            evidence(ws, finding['evidence'])
            if finding['status'] != 'satisfied' and not (finding['status'] == 'unknown' and
                    item['contract']['criteria'][key]['unknown_allowed']):
                remaining.append(key)
        verdict = payload.get('verdict')
        if verdict not in ('accepted', 'revise', 'partial', 'blocked') or (verdict == 'accepted' and remaining):
            raise streams.StreamError('verdict contradicts criterion evidence')
        if verdict == 'revise' and (item['round'] >= 2 or not remaining):
            raise streams.StreamError('revision limit reached or no scoped correction remains; submit available result')
        if verdict in ('partial', 'blocked'):
            if not remaining:
                raise streams.StreamError('partial or blocked verdict requires an identified remainder')
            if verdict == 'partial' and len(remaining) == len(assessment):
                raise streams.StreamError('partial result needs at least one resolved criterion; otherwise blocked')
            remainder(ws, wp, verdict, remaining, payload)
        item.update(phase=verdict, open=remaining)
        item['verdicts'].append(payload)
    elif event == 'unblock':
        # A partial result is closed; its remainder lives in the WP that owns it.
        if item['phase'] != 'blocked' or payload.get('criterion') not in item['open']:
            raise streams.StreamError('unblock requires a blocked open criterion')
        evidence(ws, payload['evidence'])
        item['phase'] = 'review'  # New evidence requires a decision, never another unbounded collection.
    else:
        raise streams.StreamError('unknown research event')
    item['events'][event_id] = {'event': event, 'payload': payload}
    item['updated_at'] = int(time.time())  # Stall detection: a collection without new results.
    return item


def cmd_research(args):
    import autonomy
    ws = runtime.workspace(args)
    _, _, meta = runtime.api().wp_context(ws, args.wp)
    if meta.get('execution') != 'research':
        raise streams.StreamError('research events require Execution research')
    if args.event == 'status':
        print(json.dumps(autonomy.registry(ws)[1].get('research', {}).get(args.wp), ensure_ascii=False, indent=2))
        return 0
    ws.require_open('research event')
    if not args.file:
        raise streams.StreamError('research event requires --file JSON_PATH')
    payload = json.loads(Path(args.file).read_text(encoding='utf-8'))
    with state_io.transaction(ws.root):
        _, data = autonomy.registry(ws)
        records = data.setdefault('research', {})
        before = records.get(args.wp)
        after = update(ws, before, args.event, payload, wp=args.wp)
        if after != before:
            records[args.wp] = after
            autonomy.persist(ws, data)
            ws.journal('research ' + args.event + ': ' + after['phase'], wp=args.wp,
                       evidence=payload.get('id', after['contract']['artifact']))
    print(json.dumps(after, ensure_ascii=False, indent=2))
    return 0


def add_parser(sub, common):
    parser = sub.add_parser('research', parents=[common], help='bounded research contract, collection and acceptance')
    parser.add_argument('event', choices=('contract', 'start', 'result', 'verdict', 'unblock', 'status'))
    parser.add_argument('--wp', required=True)
    parser.add_argument('--file', help='JSON event payload; use stable event ids across retries')
    parser.set_defaults(func=cmd_research)
