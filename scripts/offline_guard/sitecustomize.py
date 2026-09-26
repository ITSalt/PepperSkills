"""Audit-hook network denial loaded by every Python process in the offline check."""
import os
from pathlib import Path
import sys

# Preserve the host interpreter's sitecustomize (for example Homebrew's site paths).
_self = Path(__file__).resolve()
for _entry in sys.path:
    _candidate = Path(_entry or '.') / 'sitecustomize.py'
    if _candidate.is_file() and _candidate.resolve() != _self:
        exec(compile(_candidate.read_bytes(), str(_candidate), 'exec'), globals(), globals())
        break

_LOG = os.environ.get('PEPPERSKILLS_NETWORK_AUDIT_LOG')
_BLOCKED = {
    'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex',
    'socket.gethostbyaddr', 'socket.connect', 'socket.connect_ex',
    'socket.sendto', 'socket.sendmsg',
}


def _deny_network(event, args):
    if event not in _BLOCKED:
        return
    if _LOG:
        fd = os.open(_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (event + '\n').encode('ascii', 'replace'))
        finally:
            os.close(fd)
    raise PermissionError(f'offline test blocked network operation: {event}')


sys.addaudithook(_deny_network)
