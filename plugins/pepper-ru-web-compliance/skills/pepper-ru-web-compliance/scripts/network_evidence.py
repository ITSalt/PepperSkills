"""Describe network evidence without inferring storage geography or retaining values."""
import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


def safe_url(value):
    """Public endpoint only: credentials, query values and fragments are not evidence."""
    try:
        p = urlsplit(value or '')
        if p.scheme not in ('http', 'https'):
            return ''
        host = p.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if p.port:
            host += ':' + str(p.port)
        # Common personal values sometimes appear in REST paths as well.
        path = re.sub(r'[^/]*@[^/]*|(?<!\w)\+?\d{10,}(?!\w)', '[redacted]', p.path)
        return urlunsplit((p.scheme, host, path, '', ''))
    except (ValueError, TypeError):
        return ''


def payload_shape(url, content_type='', body=None):
    """Only conventional field names; never values, nested objects or arbitrary keys."""
    known = {'email', 'phone', 'tel', 'telephone', 'name', 'first_name', 'last_name',
             'fullname', 'address', 'message', 'company', 'city', 'file', 'files',
             'client_id', 'userid', 'user_id', 'event', 'csp-report'}
    keys = set(parse_qs(urlsplit(url).query))
    inspected = body is not None and len(body) <= 65536
    if inspected:
        try:
            if 'json' in content_type or 'csp-report' in content_type:
                obj = json.loads(body)
                if isinstance(obj, dict):
                    keys.update(obj)
            elif 'x-www-form-urlencoded' in content_type:
                keys.update(parse_qs(body))
            elif 'multipart/form-data' in content_type:
                keys.update(re.findall(r'\bname="([^"]{1,64})"', body))
        except (ValueError, TypeError):
            inspected = False
    return {'known_fields': sorted(k for k in keys if k in known),
            'body_inspected': inspected, 'values_retained': False}


def classify_request(req):
    relation = req.get('form_relation') or {}
    if relation.get('confirmed') and relation.get('source') == 'cdp:Page.frameRequestedNavigation':
        return 'form_submission', 'Браузер подтвердил навигацию при отправке формы'
    content_type = (req.get('content_type') or '').lower()
    if content_type.split(';')[0] == 'application/csp-report' or req.get('resource_type') == 'cspviolationreport':
        return 'security_report', 'Тип запроса подтверждает отчёт безопасности CSP'
    p = urlsplit(req.get('url') or '')
    host = (p.hostname or '').lower()
    if host == 'csp.withgoogle.com' and p.path.startswith('/csp/'):
        return 'security_report_candidate', 'Адрес похож на приёмник CSP; содержимое не подтверждено'
    if (host in {'mc.yandex.ru', 'mc.yandex.com', 'mc.webvisor.com'}
            and p.path.startswith(('/webvisor/', '/watch/'))):
        return 'analytics_candidate', 'Адрес соответствует аналитике; состав данных не подтверждён'
    return 'unknown', 'Назначение запроса не установлено'


def request_context(req):
    category, basis = classify_request(req)
    return {key: value for key, value in {
        'request_id': req.get('request_id'), 'page': safe_url(req.get('page')),
        'phase': req.get('phase'), 'frame': safe_url(req.get('frame')),
        'method': req.get('method'), 'content_type': req.get('content_type'),
        'initiator': req.get('initiator'), 'payload_shape': req.get('payload_shape'),
        'form_relation': req.get('form_relation'), 'category': category,
        'classification_basis': basis,
        'observation_version': req.get('observation_version', 1),
        'metadata_complete': (req.get('observation_version') == 2 and bool(req.get('frame'))
                              and (req.get('initiator') or {}).get('type') not in (None, 'unavailable')
                              and 'content_type' in req),
    }.items() if value is not None}
