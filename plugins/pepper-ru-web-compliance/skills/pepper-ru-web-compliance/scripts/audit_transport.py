"""Explicit, fail-closed audit transport. No API credentials enter artifacts.

The deployed managed gateway is the default; an environment override supports
other deployments. A local authenticated HTTP adapter uses verified TLS.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ACTIVE = None
DEFAULT_GATEWAY_URL = 'https://lts.itsalt.ru/ru-audit'
EGRESS_URL = 'https://ipinfo.io/json'


class NetworkError(RuntimeError):
    def __init__(self, code, retry_after=None):
        self.code, self.retry_after = code, retry_after
        super().__init__(code + (f'; retry_after={retry_after}' if retry_after else ''))


def tls_context():
    ctx = ssl.create_default_context()
    extra = os.environ.get('PEPPER_RU_GATEWAY_CA_FILE')
    if extra:
        ctx.load_verify_locations(extra)
    return ctx


def proxy_parts(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.path not in ('', '/') or p.query or p.fragment:
        raise NetworkError('invalid_proxy_url')
    try:
        port = p.port or (443 if p.scheme == 'https' else 80)
    except ValueError:
        raise NetworkError('invalid_proxy_url') from None
    host = f'[{p.hostname}]' if ':' in p.hostname else p.hostname
    server = f'{p.scheme}://{host}:{port}'
    return p, server, urllib.parse.unquote(p.username or ''), urllib.parse.unquote(p.password or '')


class ForcedProxy(urllib.request.ProxyHandler):
    """Explicit proxy: never let NO_PROXY or OS bypass lists cause direct traffic."""
    def proxy_open(self, req, proxy, type):
        p, _, user, password = proxy_parts(proxy)
        if p.scheme not in ('http', 'https'):
            raise NetworkError('unsupported_environment_proxy')
        if user or password:
            auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
            req.add_unredirected_header('Proxy-Authorization', 'Basic ' + auth)
        host = f'[{p.hostname}]' if ':' in p.hostname else p.hostname
        req.set_proxy(f'{host}:{p.port or (443 if p.scheme == "https" else 80)}', p.scheme)
        return None


def opener(proxy, context=None):
    return urllib.request.build_opener(ForcedProxy({'http': proxy, 'https': proxy}),
                                      urllib.request.HTTPSHandler(context=context or ssl.create_default_context()))


class NoGatewayRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NetworkError('gateway_redirect_forbidden')


def preflight(browser=True):
    """Run before issuance: even a missing browser must not consume a launch."""
    import h11
    if browser:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(proxy={'server':'http://127.0.0.1:9'}, args=chromium_args('http://127.0.0.1:9'))
            b.close()


def chromium_args(proxy_url):
    host = proxy_parts(proxy_url)[0].hostname
    return ['--disable-quic', '--disable-background-networking',
            '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE ' + host]


class GatewayClient:
    def __init__(self, url):
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/', '/ru-audit', '/ru-audit/'):
            raise NetworkError('gateway_requires_https')
        self.url = url.rstrip('/')
        self.credential = None

    def transport(self):
        proxy = urllib.request.getproxies().get('https') or urllib.request.getproxies().get('all')
        handler = ForcedProxy({'https': proxy}) if proxy else urllib.request.ProxyHandler({})
        return urllib.request.build_opener(NoGatewayRedirect(), handler,
                                           urllib.request.HTTPSHandler(context=tls_context()))

    def raw(self, method, path, data=None, headers=None):
        hdr = {'Content-Type': 'application/octet-stream' if isinstance(data, bytes) else 'application/json', **(headers or {})}
        if self.credential:
            hdr['Authorization'] = 'Bearer ' + self.credential
        req = urllib.request.Request(self.url + path, method=method, headers=hdr,
                                     data=data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None)
        try:
            with self.transport().open(req, timeout=45) as r:
                raw = r.read((32 << 20) + 1)
                if len(raw) > 32 << 20:
                    raise NetworkError('gateway_response_too_large')
                return r.status, raw, r.headers
        except urllib.error.HTTPError as e:
            try:
                code = json.loads(e.read(8192)).get('error', 'gateway_error')
            except Exception:
                code = 'gateway_http_' + str(e.code)
            raise NetworkError(code, e.headers.get('Retry-After')) from None
        except urllib.error.URLError as e:
            reason = str(e.reason).lower()
            if 'certificate' in reason or 'ssl' in reason:
                raise NetworkError('gateway_tls_failed') from None
            raise NetworkError('gateway_unreachable') from None
        except (OSError, ValueError):
            raise NetworkError('gateway_unreachable') from None

    def request(self, method, path, data=None, headers=None):
        _, raw, _ = self.raw(method, path, data, headers)
        try:
            return json.loads(raw)
        except ValueError:
            raise NetworkError('gateway_invalid_response') from None

    def capabilities(self):
        try:
            info = self.request('GET', '/v2/capabilities')
        except NetworkError as e:
            if e.code in ('gateway_http_404', 'gateway_invalid_response'):
                raise NetworkError('gateway_wrong_endpoint') from None
            raise
        if info.get('service') != 'pepper-ru-audit-gateway' or info.get('protocol') != 2:
            raise NetworkError('gateway_wrong_endpoint')
        diagnostic = self.request('GET', '/v2/diagnostic')
        if (diagnostic.get('service') != 'pepper-ru-audit-gateway' or
                diagnostic.get('protocol') != 2 or diagnostic.get('relay') != 'trusted'):
            raise NetworkError('gateway_wrong_endpoint')
        return info

    def create(self, target):
        key = secrets.token_hex(24)
        # A lost response may be retried once with the SAME key, never a new lease.
        for attempt in range(2):
            try:
                result = self.request('POST', '/v2/sessions', {'target': target}, {'Idempotency-Key': key})
                self.credential = result.pop('credential')
                return result
            except NetworkError as e:
                if e.code != 'gateway_unreachable' or attempt:
                    raise

    def open_tunnel(self, address):
        return self.request('POST', '/v2/tunnels', {'address': address})['tunnel_id']

    def write_tunnel(self, tid, offset, body):
        path = f'/v2/tunnels/{tid}/write?offset={offset}'
        for attempt in range(2):
            try:
                return self.request('POST', path, body)['offset']
            except NetworkError as e:
                if e.code != 'gateway_unreachable' or attempt:
                    raise

    def read_tunnel(self, tid, offset):
        path = f'/v2/tunnels/{tid}/read?offset={offset}'
        for attempt in range(2):
            try:
                status, body, headers = self.raw('GET', path)
                return body, status == 204 and headers.get('X-Relay-EOF') == '1'
            except NetworkError as e:
                if e.code != 'gateway_unreachable' or attempt:
                    raise

    def close_tunnel(self, tid):
        try:
            self.request('POST', f'/v2/tunnels/{tid}/close')
        except NetworkError:
            pass


class ProxyBridge:
    """Loopback-only h11 HTTP proxy -> TLS forward proxy; bounded streaming."""
    def __init__(self, upstream, credential, context=None):
        import h11
        self.h11 = h11
        self.upstream = urllib.parse.urlsplit(upstream)
        self.credential = credential
        self.context = context or tls_context()
        self.user, self.password = 'audit', secrets.token_urlsafe(32)
        self.auth = 'Basic ' + base64.b64encode(f'{self.user}:{self.password}'.encode()).decode()
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.tasks = set()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise NetworkError('adapter_start_failed')
        if hasattr(self, 'error'):
            raise NetworkError('adapter_start_failed')
        self.server_url = f'http://127.0.0.1:{self.port}'
        self.proxy_url = f'http://{self.user}:{self.password}@127.0.0.1:{self.port}'
        return self

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.slots = asyncio.Semaphore(32)
            self.server = self.loop.run_until_complete(asyncio.start_server(self._handle, '127.0.0.1', 0, limit=32768))
            self.port = self.server.sockets[0].getsockname()[1]
        except Exception as e:
            self.error = type(e).__name__
            self.ready.set()
            self.loop.close()
            return
        self.ready.set()
        self.loop.run_forever()
        self.loop.close()

    async def _event(self, conn, reader):
        while True:
            event = conn.next_event()
            if event is not self.h11.NEED_DATA:
                return event
            data = await asyncio.wait_for(reader.read(16384), 60)
            conn.receive_data(data)

    async def _pipe(self, reader, writer):
        while True:
            data = await asyncio.wait_for(reader.read(32768), 60)
            if not data:
                return
            writer.write(data)
            await asyncio.wait_for(writer.drain(), 60)

    async def _duplex(self, a, aw, b, bw):
        tasks = [asyncio.create_task(self._pipe(a, bw)), asyncio.create_task(self._pipe(b, aw))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        if len(self.tasks) > 64:
            writer.close()
            self.tasks.discard(task)
            return
        remote = None
        started = False
        try:
            async with self.slots:
                h = self.h11
                conn = h.Connection(h.SERVER, max_incomplete_event_size=16384)
                req = await self._event(conn, reader)
                if not isinstance(req, h.Request):
                    return
                headers = [(k.lower(), v) for k, v in req.headers]
                auth = next((v.decode() for k, v in headers if k == b'proxy-authorization'), '')
                if not hmac.compare_digest(auth, self.auth):
                    writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="local-audit"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                    return
                upstream_reader, remote = await asyncio.wait_for(asyncio.open_connection(
                    self.upstream.hostname, self.upstream.port or 443, ssl=self.context,
                    server_hostname=self.upstream.hostname, limit=32768), 10)
                clean = [(k, v) for k, v in headers if k not in (b'proxy-authorization', b'proxy-connection', b'connection', b'expect')]
                clean.append((b'proxy-authorization', b'Basic ' + base64.b64encode(self.credential.encode())))
                upgrade = next((v for k, v in headers if k == b'upgrade'), None)
                if req.method != b'CONNECT':
                    clean.append((b'connection', b'Upgrade' if upgrade else b'close'))
                sender = h.Connection(h.CLIENT)
                remote.write(sender.send(h.Request(method=req.method, target=req.target, headers=clean)))
                if any(k == b'expect' for k, _ in headers):
                    writer.write(b'HTTP/1.1 100 Continue\r\n\r\n')
                    await writer.drain()
                while True:
                    event = await self._event(conn, reader)
                    if isinstance(event, h.EndOfMessage):
                        remote.write(sender.send(h.EndOfMessage()))
                        break
                    if not isinstance(event, h.Data):
                        raise NetworkError('invalid_proxy_body')
                    remote.write(sender.send(event))
                    await asyncio.wait_for(remote.drain(), 60)
                await remote.drain()
                # Forward interim responses, preserving WebSocket and CONNECT switches.
                while True:
                    head = await asyncio.wait_for(upstream_reader.readuntil(b'\r\n\r\n'), 60)
                    code = int(head.split(b' ', 2)[1])
                    writer.write(head)
                    await writer.drain()
                    if code >= 200 or code == 101:
                        break
                started = True
                if (req.method == b'CONNECT' and code == 200) or code == 101:
                    pending = conn.trailing_data[0]
                    if pending:
                        remote.write(pending)
                        await remote.drain()
                    await self._duplex(reader, writer, upstream_reader, remote)
                else:
                    await self._pipe(upstream_reader, writer)
        except (Exception, asyncio.CancelledError):
            if not started and not writer.is_closing():
                writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            if remote:
                remote.close()
            writer.close()
            self.tasks.discard(task)

    def close(self):
        if not self.thread.is_alive():
            return
        async def shutdown():
            self.server.close()
            await self.server.wait_closed()
            tasks = list(self.tasks)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)


class RelayBridge(ProxyBridge):
    """Local HTTP proxy carried only by ordinary HTTPS gateway requests."""
    def __init__(self, gateway):
        super().__init__(gateway.url, gateway.credential)
        self.gateway = gateway

    def _run(self):
        self.loop.set_default_executor(ThreadPoolExecutor(max_workers=72, thread_name_prefix='ru-relay'))
        super()._run()

    async def _send(self, tid, offset, body):
        for start in range(0, len(body), 65536):
            offset = await asyncio.to_thread(self.gateway.write_tunnel, tid, offset, body[start:start + 65536])
        return offset

    async def _receive(self, tid, offset):
        while True:
            data, eof = await asyncio.to_thread(self.gateway.read_tunnel, tid, offset)
            if data or eof:
                return data, eof

    async def _duplex_relay(self, tid, reader, writer, read_offset, write_offset):
        async def upload():
            offset = write_offset
            while data := await reader.read(32768):
                offset = await self._send(tid, offset, data)
        async def download():
            offset = read_offset
            while True:
                data, eof = await self._receive(tid, offset)
                if data:
                    offset += len(data)
                    writer.write(data)
                    await writer.drain()
                if eof:
                    return
        tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for item in tasks:
                item.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        tid = None
        started = False
        try:
            async with self.slots:
                h = self.h11
                conn = h.Connection(h.SERVER, max_incomplete_event_size=16384)
                req = await self._event(conn, reader)
                if not isinstance(req, h.Request):
                    return
                headers = [(k.lower(), v) for k, v in req.headers]
                auth = next((v.decode() for k, v in headers if k == b'proxy-authorization'), '')
                if not hmac.compare_digest(auth, self.auth):
                    writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="local-audit"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                    return
                if req.method == b'CONNECT':
                    address = req.target.decode('ascii')
                else:
                    target = urllib.parse.urlsplit(req.target.decode('ascii'))
                    if target.scheme != 'http' or not target.hostname:
                        raise NetworkError('invalid_proxy_target')
                    address = f'{target.hostname}:{target.port or 80}'
                tid = await asyncio.to_thread(self.gateway.open_tunnel, address)
                offset = 0
                if req.method == b'CONNECT':
                    writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    await writer.drain()
                    started = True
                    pending = conn.trailing_data[0]
                    if pending:
                        offset = await self._send(tid, offset, pending)
                    await self._duplex_relay(tid, reader, writer, 0, offset)
                    return
                upgrade = next((v for k, v in headers if k == b'upgrade'), None)
                clean = [(k, v) for k, v in headers if k not in (b'proxy-authorization', b'proxy-connection', b'connection', b'expect')]
                clean.append((b'connection', b'Upgrade' if upgrade else b'close'))
                path = urllib.parse.urlunsplit(('', '', target.path or '/', target.query, ''))
                sender = h.Connection(h.CLIENT)
                offset = await self._send(tid, offset, sender.send(h.Request(method=req.method, target=path.encode(), headers=clean)))
                if any(k == b'expect' for k, _ in headers):
                    writer.write(b'HTTP/1.1 100 Continue\r\n\r\n')
                    await writer.drain()
                while True:
                    event = await self._event(conn, reader)
                    if isinstance(event, h.EndOfMessage):
                        end = sender.send(h.EndOfMessage())
                        if end:
                            offset = await self._send(tid, offset, end)
                        break
                    if not isinstance(event, h.Data):
                        raise NetworkError('invalid_proxy_body')
                    offset = await self._send(tid, offset, sender.send(event))
                read_offset = 0
                head = bytearray()
                while b'\r\n\r\n' not in head:
                    data, eof = await self._receive(tid, read_offset)
                    if eof:
                        raise NetworkError('upstream_closed_before_headers')
                    read_offset += len(data)
                    head.extend(data)
                    if len(head) > 65536:
                        raise NetworkError('upstream_headers_too_large')
                code = int(head.split(b' ', 2)[1])
                writer.write(head)
                await writer.drain()
                started = True
                if code == 101:
                    await self._duplex_relay(tid, reader, writer, read_offset, offset)
                else:
                    while True:
                        data, eof = await self._receive(tid, read_offset)
                        if data:
                            read_offset += len(data)
                            writer.write(data)
                            await writer.drain()
                        if eof:
                            break
        except (Exception, asyncio.CancelledError):
            if not started and not writer.is_closing():
                writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        finally:
            if tid:
                await asyncio.to_thread(self.gateway.close_tunnel, tid)
            writer.close()
            self.tasks.discard(task)


class NetworkSession:
    def __init__(self, target, mode=None, proxy=None, gateway=None):
        self.target = target
        self.custom = proxy or os.environ.get('PEPPER_RU_AUDIT_PROXY')
        self.mode = mode or ('custom' if self.custom else 'managed')
        self.gateway_url = gateway or os.environ.get('PEPPER_RU_GATEWAY_URL') or DEFAULT_GATEWAY_URL
        self.gateway = self.bridge = None
        self.metadata = {'mode': self.mode, 'complete': False,
                         'started_at': datetime.now(timezone.utc).isoformat(),
                         'limitations': ['QUIC and non-proxied WebRTC disabled']}

    def __enter__(self):
        global ACTIVE
        if ACTIVE is not None:
            raise NetworkError('nested_network_session')
        try:
            if self.mode == 'managed':
                # Import before quota is spent.
                import h11
                self.gateway = GatewayClient(self.gateway_url)
                self.gateway.capabilities()
                info = self.gateway.create(self.target)
                self.metadata.update({k: info[k] for k in ('session_id', 'expires_at', 'launches_remaining', 'next_launch_at') if k in info})
                self.bridge = RelayBridge(self.gateway).start()
                self.proxy = self.bridge.proxy_url
            elif self.mode == 'custom' and self.custom:
                p, server, user, password = proxy_parts(self.custom)
                if p.scheme == 'https':
                    self.bridge = ProxyBridge(server, f'{user}:{password}').start()
                    self.proxy = self.bridge.proxy_url
                else:
                    self.proxy = self.custom
            else:
                raise NetworkError('custom_proxy_required')
            self.http = opener(self.proxy)
            with self.http.open(EGRESS_URL, timeout=15) as r:
                data = json.loads(r.read(65536))
            if data.get('country') != 'RU' or not data.get('ip'):
                raise NetworkError('ru_egress_not_confirmed')
            self.metadata['egress'] = {k: data.get(k) for k in ('ip', 'country', 'org')}
            ACTIVE = self
            return self
        except Exception:
            self.close()
            raise

    def browser_proxy(self):
        _, server, user, password = proxy_parts(self.proxy)
        return {'server': server, 'username': user, 'password': password, 'bypass': '<-loopback>'}

    def urlopen(self, req, timeout=20, context=None):
        try:
            return (opener(self.proxy, context) if context else self.http).open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (407, 502, 503, 504):
                self.metadata.update(complete=False, transport_error='proxy_http_' + str(exc.code))
            raise
        except OSError:
            self.metadata['complete'] = False
            self.metadata['transport_error'] = 'proxy_request_failed'
            raise NetworkError('proxy_request_failed') from None

    def status(self):
        if self.gateway:
            state = self.gateway.request('GET', '/v2/sessions/current')
            if state.get('reason'):
                raise NetworkError(state['reason'])
        return self.metadata

    def registry(self, key, inn=None):
        if not self.gateway:
            return None
        path = '/v2/registries/' + key
        if inn is not None:
            path += '?inn=' + urllib.parse.quote(inn)
        data = self.gateway.request('GET', path)
        raw = base64.b64decode(data.pop('body_base64'), validate=True)
        if hashlib.sha256(raw).hexdigest() != data['source_sha256']:
            raise NetworkError('registry_hash_mismatch')
        return raw, data

    def probe(self, host):
        if self.gateway:
            return self.gateway.request('POST', '/v2/probe', {'host': host})
        # HTTPS CONNECT sends the hostname to the proxy; never resolve the target locally.
        import http.client
        p, _, user, password = proxy_parts(self.proxy)
        result = {'host': host, 'ips': [], 'dns_status': 'UNKNOWN', 'tls': {}}
        conn = http.client.HTTPSConnection(p.hostname, p.port or 80, timeout=15,
                                           context=ssl.create_default_context())
        auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
        conn.set_tunnel(host, 443, headers={'Proxy-Authorization': 'Basic ' + auth} if user or password else {})
        try:
            conn.connect()
            cert = conn.sock.getpeercert()
            result['tls'] = {'protocol': conn.sock.version(), 'not_after': cert.get('notAfter'),
                             'issuer': dict(x[0] for x in cert.get('issuer', ())),
                             'subject': dict(x[0] for x in cert.get('subject', ()))}
        except Exception:
            result['tls'] = {'error': 'proxy_tls_probe_failed'}
        finally:
            conn.close()
        return result

    def close(self):
        global ACTIVE
        if ACTIVE is self:
            ACTIVE = None
        try:
            if self.gateway and self.gateway.credential:
                try:
                    self.gateway.request('POST', '/v2/sessions/current')
                except NetworkError:
                    pass
                self.gateway.credential = None
        finally:
            if self.bridge:
                self.bridge.close()
            self.metadata['finished_at'] = datetime.now(timezone.utc).isoformat()

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.metadata['transport_error'] = exc.code if isinstance(exc, NetworkError) else type(exc).__name__
            self.metadata['complete'] = False
        self.close()


def current():
    if ACTIVE is None:
        raise NetworkError('network_session_required')
    return ACTIVE


def urlopen(req, timeout=20):
    return current().urlopen(req, timeout)
