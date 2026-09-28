"""Shared contract for evidence-backed reviewer conclusions and actions."""


def valid_action_review(item):
    # Older reviews remain readable, but cannot supply an executable action.
    if 'summary' not in item and 'action' not in item:
        return True
    if not isinstance(item.get('summary'), str) or not item['summary'].strip():
        return False
    action = item.get('action')
    if item.get('status') in {'PASS', 'NA'}:
        return action is None
    if not isinstance(action, dict) or action.get('kind') not in {'verify', 'fix'}:
        return False
    if action['kind'] == 'fix' and item.get('status') != 'FAIL':
        return False
    if not all(isinstance(action.get(k), str) and action[k].strip() for k in ('text', 'acceptance')):
        return False
    sources = action.get('evidence')
    if not isinstance(sources, list) or not sources or not all(
            isinstance(x, str) and x in item.get('evidence', []) for x in sources):
        return False
    locations = action.get('locations', [])
    if not isinstance(locations, list) or not all(isinstance(x, str) and x.strip() for x in locations):
        return False
    return action['kind'] != 'fix' or bool(locations)
