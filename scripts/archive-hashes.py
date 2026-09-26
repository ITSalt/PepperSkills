#!/usr/bin/env python3
"""Print stable path=digest pairs for built archives."""
import hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for path in sorted((ROOT / 'dist').glob('pepper-*/*/*.zip')):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f'{path.relative_to(ROOT / "dist").as_posix()}={digest}')
