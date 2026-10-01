#!/usr/bin/env python3
"""Production release by the orchestrator: facts for the release gates P1-P7 (release window, defects,
migrations), the promote of the SHA that passed the stand (a PR integration -> prod, or a fast-forward
push from a clean clone) and the checks of the promote PR.

Only with delivery.prod: orchestrator (an owner decision D-n). The orchestrator never rolls back a
database. Standard library + git + gh. Imported by orch.py.
"""
import datetime as dt
import json
import os
import re
import subprocess
import time

import delivery
import streams

POLICIES = ('batch', 'per_package')
PROMOTES = ('pr', 'ff')
DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
DAYS_RU = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')
HIGH = ('blocker', 'critical', 'high')
CLOSED = re.compile(r'^(fixed|cancel|closed|resolved|done|исправлен|отмен|закрыт|решён|решен)', re.I)
MIGRATIONS_LINE = re.compile(r'^.*\b(migrations|миграции)\s*:.*$', re.I | re.M)
SAFE = re.compile(r'(?<![a-z])(?<!not )safe\b|(?<!не)(?<!не )безопасн', re.I)
REVERSIBLE = re.compile(r'(?<![a-z])(?<!not )reversib|(?<!не)(?<!не )обратим', re.I)
NO_VALUE = re.compile(r'^\s*(<.*>|—|-|no|none|нет|n/a)?\s*$', re.I)


class WindowError(ValueError):
    pass


# ---------------------------------------------------------------- release window and daily limit

def _day(token):
    token = token.strip().lower()
    if token in DAYS_RU:
        return DAYS_RU.index(token)
    for i, name in enumerate(DAYS):
        if len(token) >= 3 and name.startswith(token):
            return i
    raise WindowError(f'{token!r} is not a day of the week (Mon..Sun or Пн..Вс)')


def zone(name):
    """A time zone: UTC, an offset (+03:00, UTC+3) or an IANA name (Europe/Berlin)."""
    if name.upper() in ('UTC', 'GMT', 'Z'):
        return dt.timezone.utc
    offset = re.fullmatch(r'(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?', name, re.I)
    if offset:
        sign = -1 if offset.group(1) == '-' else 1
        hours, minutes = int(offset.group(2)), int(offset.group(3) or 0)
        if hours > 14 or minutes > 59:
            raise WindowError(f'{name!r} is not a valid UTC offset')
        return dt.timezone(sign * dt.timedelta(hours=hours, minutes=minutes), name)
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # unknown name, no tz database (Windows without tzdata), Python before 3.9
        raise WindowError(f'time zone {name!r} is unknown on this machine (on Windows: pip install tzdata; or give '
                          'an offset such as +03:00)')


def parse_window(text):
    """(days, start minute, end minute, zone) of "Mon-Fri 10:00-18:00 Europe/Berlin"; an end before the
    start runs past midnight (the window belongs to the day it starts)."""
    parts = str(text).split()
    if len(parts) != 3:
        raise WindowError(f'release_window {text!r}: expected "<days> <HH:MM-HH:MM> <zone>", for example '
                          '"Mon-Fri 10:00-18:00 Europe/Berlin"')
    days = set()
    for chunk in parts[0].split(','):
        ends = chunk.split('-')
        if len(ends) > 2 or not all(ends):
            raise WindowError(f'release_window days {parts[0]!r}: a day, a range (Mon-Fri) or a list (Mon,Wed)')
        first, last = _day(ends[0]), _day(ends[-1])
        i = first
        while True:
            days.add(i)
            if i == last:
                break
            i = (i + 1) % 7
    hours = re.fullmatch(r'(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})', parts[1])
    if not hours:
        raise WindowError(f'release_window hours {parts[1]!r}: HH:MM-HH:MM')
    h1, m1, h2, m2 = (int(x) for x in hours.groups())
    if h1 > 23 or h2 > 24 or m1 > 59 or m2 > 59 or (h2 == 24 and m2):
        raise WindowError(f'release_window hours {parts[1]!r}: not a valid time')
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if start == end:
        raise WindowError(f'release_window hours {parts[1]!r}: an empty window (leave release_window out for none)')
    return days, start, end, zone(parts[2])


def in_window(spec, now):
    """(inside, local time) of now (an aware datetime) in a parsed window."""
    days, start, end, tz = spec
    local = now.astimezone(tz)
    minute, weekday = local.hour * 60 + local.minute, local.weekday()
    if start < end:
        return weekday in days and start <= minute < end, local
    if minute >= start:
        return weekday in days, local
    if minute < end:
        return (weekday - 1) % 7 in days, local
    return False, local


def local_date(stamp, tz):
    """The calendar date in tz of a journal time stamp 'YYYY-MM-DD HH:MMZ' (UTC)."""
    try:
        moment = dt.datetime.strptime(stamp.strip(), '%Y-%m-%d %H:%MZ').replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return moment.astimezone(tz).date()


# ---------------------------------------------------------------- packages and defects

def migrations(header):
    """The Migrations row of a package header when it declares migrations, else None."""
    value = header.get('Migrations', header.get('Миграции', '')) or ''
    return None if NO_VALUE.match(value) else value.strip()


def migrations_reviewed(text):
    """True when a review report has a line "migrations: safe, reversible" (or "миграции: безопасны, обратимы")."""
    return any(SAFE.search(m.group(0)) and REVERSIBLE.search(m.group(0)) for m in MIGRATIONS_LINE.finditer(text))


def open_high_defects(root):
    """[(file, severity, environment, status)] of open defects of severity blocker, critical or high in bugs/."""
    found = []
    folder = root / 'bugs'
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob('*.md')):
        if path.name.startswith('_'):
            continue
        header = streams.wp_header(path.read_text(encoding='utf-8', errors='replace'))
        severity = (header.get('Severity') or header.get('Серьёзность') or '').strip()
        status = (header.get('Status') or header.get('Статус') or '').strip()
        environment = (header.get('Environment') or header.get('Окружение') or '').strip()
        words = severity.lower().replace('/', ' ').split()
        if severity.startswith('<') or not words or words[0] not in HIGH or CLOSED.match(status):
            continue
        found.append((path.name, words[0], environment or '?', status or '?'))
    return found


# ---------------------------------------------------------------- git facts

def fetch(repo, *branches):
    """Fetch branches from origin without ever prompting; (ok, detail)."""
    try:
        result = subprocess.run(['git', '-C', str(repo.local), 'fetch', '-q', 'origin', *branches],
                                capture_output=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}, timeout=300)
    except subprocess.TimeoutExpired:
        return False, 'timed out after 300 s'
    return result.returncode == 0, (result.stderr or '').strip().split('\n')[0]


def resolve(repo, ref):
    result = streams.git(repo.local, 'rev-parse', '--verify', '-q', f'{ref}^{{commit}}')
    return result.stdout.strip() if result.returncode == 0 else None


def is_ancestor(repo, older, newer):
    return streams.git(repo.local, 'merge-base', '--is-ancestor', older, newer).returncode == 0


def tree(repo, ref):
    result = streams.git(repo.local, 'rev-parse', '--verify', '-q', f'{ref}^{{tree}}')
    return result.stdout.strip() if result.returncode == 0 else None


def same_content(repo, a, b):
    """True when commits a and b have the same tree (the same code, whatever the history)."""
    first, second = tree(repo, a), tree(repo, b)
    return bool(first) and first == second


def prod_content(repo, prod_tip, sha):
    """(ok, base): the prod tip carries exactly the code of a commit the stand passed: base, the
    merge base of the prod tip and sha (the stand SHA of the last promote, or the initial commit). A
    hand-resolved promote merge, a revert or a hotfix on prod makes the trees differ."""
    result = streams.git(repo.local, 'merge-base', prod_tip, sha)
    base = result.stdout.strip() if result.returncode == 0 else None
    return bool(base) and same_content(repo, prod_tip, base), base


def own_commits(repo, prod_tip, sha):
    """Commits of the prod branch that sha lacks, merge commits of earlier promotes aside: code that
    never passed the stand."""
    result = streams.git(repo.local, 'rev-list', '--no-merges', prod_tip, f'^{sha}')
    return [line for line in result.stdout.split() if line] if result.returncode == 0 else ['rev-list failed']


def newest(repo, shas):
    """The SHA among shas that contains all the others, or None when they diverge."""
    for sha in shas:
        if all(is_ancestor(repo, other, sha) for other in shas):
            return sha
    return None


# ---------------------------------------------------------------- promote

def open_promote_pr(repo_name, base, head):
    prs = delivery.gh_json(['pr', 'list', '--repo', repo_name, '--base', base, '--head', head, '--state', 'open',
                            '--json', 'number,url,headRefOid,title']) or []
    return prs[0] if prs else None


def create_promote_pr(repo_name, base, head, title, body_file):
    result = subprocess.run(['gh', 'pr', 'create', '--repo', repo_name, '--base', base, '--head', head, '--title',
                             title, '--body-file', str(body_file)], encoding='utf-8', errors='replace',
                            capture_output=True)
    if result.returncode:
        raise delivery.DeliveryError((result.stderr or result.stdout).strip().split('\n')[0] or 'gh pr create failed')
    url = re.search(r'https?://\S+/pull/\d+', result.stdout)
    if not url:
        raise delivery.DeliveryError(f'gh pr create printed no PR URL: {result.stdout.strip()[:200]}')
    return url.group(0)


def wait_checks(repo_name, number, timeout, interval):
    """(ok, detail): the checks of a PR, waited for while any is pending; a failed check ends the wait."""
    deadline = time.monotonic() + timeout
    while True:
        result = subprocess.run(['gh', 'pr', 'checks', str(number), '--repo', repo_name, '--json', 'name,bucket'],
                                encoding='utf-8', errors='replace', capture_output=True)
        if result.returncode and 'no checks' in (result.stderr + result.stdout).lower():
            return True, 'no checks reported'
        try:
            checks = json.loads(result.stdout or '[]')
        except ValueError:
            return False, (result.stderr or 'gh pr checks failed').strip().split('\n')[0]
        buckets = [str(c.get('bucket', '')).lower() for c in checks]
        bad = [c for c, b in zip(checks, buckets) if b not in delivery.PASSING and b != 'pending']
        if bad:
            return False, ', '.join(f'{c.get("name")}: {c.get("bucket")}' for c in bad[:5])
        if 'pending' not in buckets:
            return True, f'{len(checks)} checks passed' if checks else 'no checks reported'
        if time.monotonic() >= deadline:
            return False, f'checks still pending after {timeout} s'
        time.sleep(interval)


def clone_problem(clone, repo):
    """Why release_clone cannot push the promote, or None: it must be a clean clone of the same origin."""
    if not clone or not clone.is_dir():
        return f'release_clone {clone or "(not set)"} is not a directory: promote: ff pushes from a clean clone'
    if streams.normalized_origin(clone) != streams.normalized_origin(repo.local):
        return f'release_clone {clone} is not a clone of the repository\'s origin'
    status = streams.git(clone, 'status', '--porcelain')
    if status.returncode or status.stdout.strip():
        return f'release_clone {clone} is not clean (git status --porcelain)'
    return None


def ff_push(clone, sha, prod_branch):
    """git push origin <sha>:refs/heads/<prod_branch> from the clean clone; never forced, so git itself
    refuses anything but a fast-forward."""
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    args = ['git', '-C', str(clone), 'push', 'origin', f'{sha}:refs/heads/{prod_branch}']
    try:
        fetched = subprocess.run(['git', '-C', str(clone), 'fetch', '-q', 'origin'], capture_output=True,
                                 encoding='utf-8', errors='replace', env=env, timeout=300)
        if fetched.returncode:
            raise delivery.DeliveryError(f'git fetch in {clone}: {(fetched.stderr.strip().splitlines() or [""])[0]}')
        pushed = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', env=env, timeout=300)
    except subprocess.TimeoutExpired as error:
        raise delivery.DeliveryError(f'{" ".join(error.cmd[3:])} timed out after 300 s')
    if pushed.returncode:
        raise delivery.DeliveryError((pushed.stderr or pushed.stdout).strip().split('\n')[-1] or 'git push failed')
    return ' '.join(args[3:])
