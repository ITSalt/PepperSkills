"""Documented Codex CLI / JSON-RPC transport. Never parse the TUI or Codex state DB."""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import struct
import subprocess
import threading
import time
from urllib.parse import urlsplit


class TransportError(RuntimeError):
    pass


class LocalWebSocket:
    """Small RFC6455 client for local App Server endpoints; no third-party runtime.

    Only local Unix sockets and loopback TCP are accepted. No authentication data
    or remote endpoints are inferred from Codex's internal state files.
    """
    def __init__(self, endpoint):
        u = urlsplit(endpoint)
        if u.scheme == 'unix' and not u.netloc and u.path.startswith('/'):
            self.sock = socket.socket(socket.AF_UNIX)
            self.sock.settimeout(10)
            self.sock.connect(u.path)
            host, path = 'localhost', '/'
        elif u.scheme == 'ws' and u.hostname in ('localhost', '127.0.0.1', '::1') and not u.username and not u.password:
            self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
            host, path = u.netloc, u.path or '/'
        else:
            raise TransportError('Codex endpoint must be unix:///absolute/socket or loopback ws://host:port')
        self.lock = threading.Lock()
        self.buffer = b''
        key = base64.b64encode(os.urandom(16)).decode()
        try:
            self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n'
                               f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                               'Sec-WebSocket-Version: 13\r\n\r\n').encode())
            header = b''
            while b'\r\n\r\n' not in header:
                part = self.sock.recv(4096)
                if not part or len(header) > 16384:
                    raise TransportError('Invalid App Server websocket handshake')
                header += part
            header, self.buffer = header.split(b'\r\n\r\n', 1)
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            lines = header.decode('ascii').split('\r\n')
            headers = {k.lower(): v for k, v in (x.split(':', 1) for x in lines[1:] if ':' in x)}
            if lines[0].split()[1] != '101' or headers.get('sec-websocket-accept', '').strip() != expected:
                raise TransportError('App Server rejected websocket handshake')
            self.sock.settimeout(None)
        except BaseException:
            self.sock.close()
            raise

    def exact(self, size):
        while len(self.buffer) < size:
            part = self.sock.recv(max(4096, size - len(self.buffer)))
            if not part:
                raise TransportError('App Server websocket closed')
            self.buffer += part
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def frame(self, payload, opcode=1):
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | opcode, 0x80 | (size if size < 126 else 126 if size < 65536 else 127)])
        if size >= 126:
            header += struct.pack('!H' if size < 65536 else '!Q', size)
        masked = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
        with self.lock:
            self.sock.sendall(header + mask + masked)

    def write(self, value):
        self.frame(json.dumps(value).encode('utf-8'))

    def read(self):
        fragments = []
        while True:
            first, second = self.exact(2)
            opcode, size = first & 15, second & 127
            if first & 0x70 or second & 0x80:
                raise TransportError('Unsupported websocket frame')
            if size in (126, 127):
                size = struct.unpack('!H' if size == 126 else '!Q', self.exact(2 if size == 126 else 8))[0]
            if size > 32 * 1024 * 1024:
                raise TransportError('App Server websocket frame too large')
            payload = self.exact(size)
            if opcode == 8:
                raise TransportError('App Server websocket closed')
            if opcode == 9:
                self.frame(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise TransportError('Unsupported websocket message')
            fragments.append(payload)
            if sum(map(len, fragments)) > 32 * 1024 * 1024:
                raise TransportError('App Server websocket message too large')
            if first & 0x80:
                return json.loads(b''.join(fragments).decode('utf-8'))

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def command():
    """Resolve the native CLI; Python does not resolve npm's .cmd via PATHEXT.

    Avoid cmd.exe shell parsing of messages and keep App Server's lifetime tied
    to the actual native process rather than a detached node/shim parent.
    """
    executable = shutil.which('codex')
    if not executable:
        raise TransportError('Codex CLI unavailable')
    path = Path(executable)
    resolved = path.resolve()
    if os.name != 'nt' and resolved.name == 'codex.js' and resolved.parent.name == 'bin':
        package = resolved.parent.parent
        candidates = [*package.glob('vendor/*/bin/codex'),
                      *package.parent.glob('codex-*/vendor/*/bin/codex'),
                      *package.glob('node_modules/@openai/codex-*/vendor/*/bin/codex')]
        candidates = list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))
        if len(candidates) != 1:
            raise TransportError('Cannot resolve one native Codex binary from npm; put the native binary on PATH')
        path = candidates[0]
    if os.name == 'nt' and path.suffix.lower() in ('.cmd', '.bat'):
        package = path.parent / 'node_modules/@openai/codex'
        candidates = []
        # Official npm 0.154 uses bin/; older packages used codex/.
        for directory in ('bin', 'codex'):
            candidates += [*package.glob(f'vendor/*/{directory}/codex.exe'),
                           *package.parent.glob(f'codex-win32-*/vendor/*/{directory}/codex.exe'),
                           *package.glob(f'node_modules/@openai/codex-win32-*/vendor/*/{directory}/codex.exe')]
        candidates = list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))
        if len(candidates) != 1:
            raise TransportError('Cannot resolve native codex.exe from npm shim; install the official CLI '
                                 'for this architecture or put native codex.exe on PATH')
        path = candidates[0]
    return [str(path)]


def capabilities():
    try:
        argv = command()
    except TransportError as error:
        return {'available': False, 'queue': False, 'app_server': False, 'version': None, 'reason': str(error)}
    def run(args):
        r = subprocess.run([*argv, *args], capture_output=True, text=True, encoding='utf-8', timeout=15)
        return r.returncode == 0, r.stdout
    _, version = run(['--version'])
    sending, _ = run(['queue', '--help'])
    reading, _ = run(['app-server', '--help'])
    return {'available': True, 'queue': sending, 'app_server': reading, 'version': version.strip()}


class Server:
    def __init__(self, shared=False, remote=None):
        self.ws = LocalWebSocket(remote) if remote else None
        self.proc = None if self.ws else subprocess.Popen(
            [*command(), 'app-server', 'proxy' if shared else '--stdio'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1)
        self.responses = queue.Queue()
        self.events = []
        self.next_id = 0
        def read():
            try:
                if self.ws:
                    while True:
                        self.responses.put(self.ws.read())
                else:
                    for line in self.proc.stdout:
                        try:
                            self.responses.put(json.loads(line))
                        except ValueError:
                            continue
            except (OSError, ValueError, TransportError):
                pass
            finally:
                self.responses.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'pepper_orchestrator', 'version': '0.13.1'}})
            self.send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def send(self, data):
        if self.ws:
            self.ws.write(data)
        else:
            self.proc.stdin.write(json.dumps(data) + '\n')
            self.proc.stdin.flush()

    def call(self, method, params, timeout=20):
        self.next_id += 1
        ident = self.next_id
        self.send({'id': ident, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = self.responses.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise TransportError('App Server timeout: ' + method)
            if value is None:
                raise TransportError('App Server closed before answering: ' + method)
            if 'method' not in value and value.get('id') == ident:
                if 'error' in value:
                    raise TransportError(f'{method}: {value["error"].get("message", "request failed")}')
                return value.get('result')
            self.events.append(value)
            self.events = self.events[-1000:]
            if time.monotonic() >= deadline:
                raise TransportError('App Server timeout: ' + method)

    def close(self):
        if self.ws:
            self.ws.close()
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        self.proc.stdin.close(); self.proc.stdout.close()


@contextmanager
def server(shared=False, remote=None):
    instance = Server(shared=shared, remote=remote)
    try:
        yield instance
    finally:
        instance.close()


def read_thread(thread_id, include_turns=False, shared=False, remote=None):
    with server(shared=shared, remote=remote) as api:
        result = api.call('thread/read', {'threadId': thread_id})
        if include_turns:
            result['thread']['turns'] = turns(api, thread_id)
        return result


def turns(api, thread_id):
    try:
        return api.call('thread/turns/list', {
            'threadId': thread_id, 'limit': 100, 'itemsView': 'full'})['data']
    except TransportError as error:
        if 'not supported' not in str(error) and 'unknown method' not in str(error).lower():
            raise
        return api.call('thread/read', {'threadId': thread_id, 'includeTurns': True})['thread']['turns']


def compact(thread_id, remote=None, timeout=60):
    """Compact only an already-loaded idle thread on its owning server.

    An RPC acknowledgement is not completion. A lost completion is unknown and
    must be reconciled, never replaced by sending literal slash-command text.
    """
    with server(shared=True, remote=remote) as api:
        thread = api.call('thread/read', {'threadId': thread_id})['thread']
        if thread.get('status', {}).get('type') != 'idle':
            raise TransportError('compaction requires a loaded idle thread')
        # Subscribe to the already-loaded runtime on this exact server. No model,
        # permissions or configuration overrides; never resume a notLoaded thread.
        api.call('thread/resume', {'threadId': thread_id, 'excludeTurns': True})
        api.call('thread/compact/start', {'threadId': thread_id})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            thread = api.call('thread/read', {'threadId': thread_id})['thread']
            complete = any(e.get('method') == 'item/completed' and
                           e.get('params', {}).get('threadId') == thread_id and
                           e.get('params', {}).get('item', {}).get('type') == 'contextCompaction'
                           for e in api.events)
            if complete and thread.get('status', {}).get('type') == 'idle':
                return {'completed': True}
            time.sleep(.2)
        return {'completed': False, 'outcome_unknown': True}


def list_threads(cwd):
    with server() as api:
        return api.call('thread/list', {'cwd': cwd, 'limit': 100})


def send(thread_id, message, remote=None):
    try:
        caps = capabilities()
    except (OSError, subprocess.TimeoutExpired):
        caps = {'queue': False}
    if not caps['queue']:
        return {'delivered': False, 'fallback': message, 'reason': 'codex queue unavailable'}
    try:
        r = subprocess.run([*command(), 'queue', '--thread', thread_id, '--message', message,
                            *(['--remote', remote] if remote else [])],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {'delivered': False, 'outcome_unknown': True, 'fallback': None, 'reason': 'queue outcome unknown; read thread before retry'}
    return {'delivered': r.returncode == 0, 'queued': r.returncode == 0, 'outcome_unknown': r.returncode != 0, 'fallback': None,
            'reason': None if r.returncode == 0 else 'codex queue failed; inspect the destination session'}
