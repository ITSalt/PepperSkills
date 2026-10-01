"""Documented Codex CLI / JSON-RPC transport. Never parse the TUI or Codex state DB."""
from contextlib import contextmanager
import json
import queue
import shutil
import subprocess
import threading
import time


class TransportError(RuntimeError):
    pass


def capabilities():
    if not shutil.which('codex'):
        return {'available': False, 'queue': False, 'app_server': False, 'version': None}
    def run(args):
        r = subprocess.run(['codex', *args], capture_output=True, text=True, encoding='utf-8', timeout=15)
        return r.returncode == 0, r.stdout
    _, version = run(['--version'])
    sending, _ = run(['queue', '--help'])
    reading, _ = run(['app-server', '--help'])
    return {'available': True, 'queue': sending, 'app_server': reading, 'version': version.strip()}


class Server:
    def __init__(self):
        self.proc = subprocess.Popen(['codex', 'app-server', '--stdio'], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1)
        self.responses = queue.Queue()
        self.next_id = 0
        def read():
            for line in self.proc.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError:
                    continue
            self.responses.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'pepper_orchestrator', 'version': '0.11.0'}})
            self.send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def send(self, data):
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
            if value.get('id') == ident:
                if 'error' in value:
                    raise TransportError(f'{method}: {value["error"].get("message", "request failed")}')
                return value.get('result')
            if time.monotonic() >= deadline:
                raise TransportError('App Server timeout: ' + method)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        self.proc.stdin.close(); self.proc.stdout.close()


@contextmanager
def server():
    instance = Server()
    try:
        yield instance
    finally:
        instance.close()


def read_thread(thread_id, include_turns=False):
    with server() as api:
        return api.call('thread/read', {'threadId': thread_id, 'includeTurns': include_turns})


def list_threads(cwd):
    with server() as api:
        return api.call('thread/list', {'cwd': cwd, 'limit': 100})


def send(thread_id, message):
    try:
        caps = capabilities()
    except (OSError, subprocess.TimeoutExpired):
        caps = {'queue': False}
    if not caps['queue']:
        return {'delivered': False, 'fallback': message, 'reason': 'codex queue unavailable'}
    try:
        r = subprocess.run(['codex', 'queue', '--thread', thread_id, '--message', message],
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {'delivered': False, 'outcome_unknown': True, 'fallback': message, 'reason': 'queue outcome unknown; read thread before retry'}
    return {'delivered': r.returncode == 0, 'queued': r.returncode == 0, 'fallback': None if r.returncode == 0 else message,
            'reason': None if r.returncode == 0 else 'codex queue failed; inspect the destination session'}
