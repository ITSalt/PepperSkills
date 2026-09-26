#!/usr/bin/env python3
"""Prove DNS is denied and recorded, including in a child Python process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / 'scripts/offline_guard'
CODE = "import socket;\ntry: socket.getaddrinfo('example.invalid', 443)\nexcept PermissionError: pass\nelse: raise SystemExit('DNS unexpectedly allowed')"

with tempfile.TemporaryDirectory(prefix='pepperskills-guard-') as raw:
    log = Path(raw) / 'attempts.log'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(GUARD)
    env['PEPPERSKILLS_NETWORK_AUDIT_LOG'] = str(log)
    subprocess.run([sys.executable, '-c', CODE], env=env, check=True)
    assert log.read_text(encoding='ascii').strip() == 'socket.getaddrinfo'
print('PASS offline guard denies and records DNS attempts in child Python processes')
