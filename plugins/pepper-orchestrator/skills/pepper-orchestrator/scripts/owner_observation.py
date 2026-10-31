"""Pinned read-only Git observations for the explicit private owner adapter.

Never use a model-writable gitfile/commondir to select the host's repository.
Registration is an owner bootstrap operation, before any model/grant starts.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


class ObservationError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class GitObserver:
    READS = {'status', 'rev-parse', 'show-ref', 'for-each-ref', 'diff', 'ls-files', 'merge-base', 'rev-list',
             'ls-tree', 'log', 'show', 'cat-file', 'symbolic-ref', 'branch', 'remote'}

    def __init__(self, storage):
        self.storage = Path(storage).resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.git_binary = str(Path(shutil.which('git')).resolve(strict=True))
        self.registrations = {}
        self.toplevels = {}

    def register(self, worktree):
        worktree = Path(worktree).resolve(strict=True)
        def git(*args):
            p = subprocess.run([self.git_binary, '-C', str(worktree), *args], text=True,
                encoding='utf-8', capture_output=True, timeout=15,
                env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
            if p.returncode:
                raise ObservationError('cannot register Git observation: ' + p.stderr.strip())
            return p.stdout.strip()
        private = Path(git('rev-parse', '--absolute-git-dir')).resolve(strict=True)
        common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir')).resolve(strict=True)
        config = common / 'config'
        # --file deliberately does not follow include directives. Reject them;
        # otherwise writable included config could add an unobserved filter driver.
        p = subprocess.run([self.git_binary, 'config', '--file', str(config), '--null', '--list'],
            text=True, capture_output=True, encoding='utf-8', timeout=15)
        if p.returncode:
            raise ObservationError('cannot inspect common Git config')
        entries = [v.split('\n', 1) for v in p.stdout.split('\0') if v]
        keys = {e[0].lower(): e[1] if len(e) > 1 else '' for e in entries}
        if any(k.startswith(('include.', 'includeif.')) for k in keys):
            raise ObservationError('owner observation requires no included Git config')
        if keys.get('extensions.worktreeconfig', 'false').lower() not in ('false', 'no', '0'):
            raise ObservationError('mutable per-worktree Git config is unsupported')
        if 'extensions.partialclone' in keys or any(k.endswith('.promisor') and v.lower() in ('true', '1', 'yes') for k, v in keys.items()):
            raise ObservationError('owner observation cannot perform implicit promisor fetch')
        drivers = {m.group(1) for k in keys for m in [re.fullmatch(r'filter\.([a-z0-9_-]+)\.(?:clean|smudge|process|required)', k)] if m}
        # Unknown filter driver spellings are rejected rather than interpolated.
        if any(k.startswith('filter.') and not re.fullmatch(r'filter\.[a-z0-9_-]+\.(?:clean|smudge|process|required)', k) for k in keys):
            raise ObservationError('unsupported Git filter configuration')
        row = {'worktree': worktree, 'private': private, 'common': common,
               'config': config, 'config_sha256': digest(config), 'drivers': sorted(drivers),
               'object_format': git('rev-parse', '--show-object-format')}
        self.registrations[str(worktree)] = row
        return row

    def __call__(self, worktree, *args):
        key = str(Path(worktree).absolute())
        if args == ('rev-parse', '--show-toplevel') and key in self.toplevels:
            return subprocess.CompletedProcess(args, 0, self.toplevels[key] + '\n', '')
        row = self.registrations.get(key)
        if not row or Path(worktree).resolve() != row['worktree']:
            raise ObservationError('unregistered or replaced Git worktree')
        if digest(row['config']) != row['config_sha256']:
            raise ObservationError('common Git config changed; owner reconfirmation required')
        if not args or args[0] not in self.READS:
            raise ObservationError('host Git writes/network commands are forbidden')
        if args[0] == 'branch' and args[1:] != ('--show-current',):
            raise ObservationError('host branch mutation is forbidden')
        if args[0] == 'remote' and args[1:] not in ((), ('-v',)):
            raise ObservationError('host remote mutation is forbidden')
        if args[0] == 'symbolic-ref' and args[1:] not in (('--short', '-q', 'HEAD'), ('--short', 'HEAD')):
            raise ObservationError('only read-only symbolic-ref observations are supported')
        if args in (('rev-parse', '--git-dir'), ('rev-parse', '--absolute-git-dir'),
                    ('rev-parse', '--git-common-dir'), ('rev-parse', '--path-format=absolute', '--git-common-dir'),
                    ('rev-parse', '--path-format=absolute', '--git-dir')):
            value = row['common'] if args[-1] == '--git-common-dir' else row['private']
            return subprocess.CompletedProcess(args, 0, str(value) + '\n', '')
        # No arbitrary caller-selected config, execution helper, output path or
        # option file. The owner adapter calls this only with fixed core reads.
        if any(a.startswith(('--output', '--exec', '--config', '--git-dir', '--work-tree')) for a in args):
            raise ObservationError('unsafe host Git option: ' + repr(args))
        options = ['-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
            '-c', 'core.pager=cat', '-c', 'diff.external=', '-c', 'core.attributesFile=' + os.devnull]
        for driver in row['drivers']:
            for kind, value in (('clean', ''), ('smudge', ''), ('process', ''), ('required', 'false')):
                options += ['-c', 'filter.' + driver + '.' + kind + '=' + value]
        flags = list(args)
        if flags[0] in ('diff', 'show', 'log'):
            flags[1:1] = ['--no-ext-diff', '--no-textconv']
        # A linked gitdir may follow its writable gitdir/commondir pointers even
        # with explicit command options. Build an owner-held observation view:
        # copy only HEAD/index as bounded regular files; expose pinned refs/objects.
        # The view has no project config or info/attributes, and is never a write
        # target for the module. It does not fetch, prepare or change its index.
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ATTR_NOSYSTEM='1', GIT_NO_REPLACE_OBJECTS='1',
            GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', GIT_PAGER='cat', GIT_CONFIG_COUNT='0')
        if flags[0] in ('status', 'diff'):
            flags.insert(1, '--ignore-submodules=all')
        with tempfile.TemporaryDirectory(prefix='git-view-', dir=self.storage) as tmp:
            view = Path(tmp)
            for name in ('HEAD', 'index'):
                try:
                    fd = os.open(row['private'] / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                except FileNotFoundError:
                    if name == 'index':
                        continue
                    raise ObservationError('missing registered HEAD')
                with os.fdopen(fd, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
                        raise ObservationError('Git observation metadata must be bounded regular files')
                    with (view / name).open('wb') as dest:
                        shutil.copyfileobj(source, dest)
                    # Preserve the index timestamp: Git's racy-clean detection
                    # compares worktree mtimes to it. A freshly stamped copy can
                    # incorrectly hide a same-size edit made in that window.
                    os.utime(view / name, ns=(info.st_atime_ns, info.st_mtime_ns))
            config = '[core]\nrepositoryformatversion = 0\nbare = false\n'
            if row['object_format'] == 'sha256':
                config = '[core]\nrepositoryformatversion = 1\nbare = false\n[extensions]\nobjectFormat = sha256\n'
            (view / 'config').write_text(config)
            if (row['common'] / 'info/exclude').is_file():
                (view / 'info').mkdir()
                (view / 'info/exclude').symlink_to(row['common'] / 'info/exclude')
            for name in ('objects', 'refs', 'packed-refs', 'shallow'):
                if (row['common'] / name).exists():
                    (view / name).symlink_to(row['common'] / name)
            return subprocess.run([self.git_binary, '--no-optional-locks', '--git-dir=' + str(view),
                '--work-tree=' + str(row['worktree']), *options, *flags], env=env,
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
