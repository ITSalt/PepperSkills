"""Opt-in local HTTPS relay acceptance, including an authenticated outer proxy."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import socket
import ssl
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

import audit_transport as net
from test_gateway_network import Origin, serve


class Relay(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    plain_port = tls_port = 0
    tunnels = {}
    seen = []
    def log_message(self, *_): pass
    def reply(self, status, value=None, headers=None):
        body = json.dumps(value).encode() if value is not None else b''
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', 'application/json')
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        if body: self.wfile.write(body)
    def binary(self, status, body=b'', headers=None):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        if body: self.wfile.write(body)
    def do_GET(self):
        path = urlsplit(self.path).path
        self.seen.append(self.path)
        if path == '/ru-audit/v2/capabilities':
            return self.reply(200, {'service':'pepper-ru-audit-gateway','protocol':2})
        if path == '/ru-audit/v2/diagnostic':
            return self.reply(200, {'service':'pepper-ru-audit-gateway','protocol':2,'relay':'trusted'})
        if path == '/ru-audit/v2/sessions/current': return self.reply(200, {'reason':''})
        if path.endswith('/read'):
            tid = path.split('/')[4]
            tunnel = self.tunnels[tid]
            offset = int(parse_qs(urlsplit(self.path).query)['offset'][0])
            with tunnel['rlock']:
                if offset == tunnel['read_offset'] - len(tunnel['last_read']) and tunnel['last_read']:
                    return self.binary(200, tunnel['last_read'])
                assert offset == tunnel['read_offset']
                tunnel['socket'].settimeout(.3)
                try: body = tunnel['socket'].recv(65536)
                except socket.timeout: return self.binary(204)
                except OSError: return self.binary(204, headers={'X-Relay-EOF':'1'})
                if not body: return self.binary(204, headers={'X-Relay-EOF':'1'})
                tunnel['last_read'] = body
                tunnel['read_offset'] += len(body)
                return self.binary(200, body)
        return self.reply(404, {'error':'not_found'})
    def do_POST(self):
        path = urlsplit(self.path).path
        self.seen.append(self.path)
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if path == '/ru-audit/v2/sessions':
            assert self.headers['Idempotency-Key']
            return self.reply(201, {'credential':'session:credential', 'session_id':'session'})
        assert self.headers.get('Authorization') == 'Bearer session:credential'
        if path == '/ru-audit/v2/sessions/current': return self.reply(200, {'reason':'session_closed'})
        if path == '/ru-audit/v2/tunnels':
            address = json.loads(body)['address']
            host, port = address.rsplit(':', 1)
            assert host in ('audit.test', 'third.test') and port in ('80', '443')
            sock = socket.create_connection(('127.0.0.1', self.tls_port if port == '443' else self.plain_port))
            tid = f'{len(self.tunnels)+1:048d}'
            self.tunnels[tid] = {'socket':sock, 'write_offset':0, 'read_offset':0,
                                 'last_write':b'', 'last_read':b'', 'rlock':threading.Lock(), 'wlock':threading.Lock()}
            return self.reply(201, {'tunnel_id':tid})
        tid, operation = path.split('/')[4:6]
        tunnel = self.tunnels[tid]
        if operation == 'write':
            offset = int(parse_qs(urlsplit(self.path).query)['offset'][0])
            with tunnel['wlock']:
                if offset == tunnel['write_offset'] - len(tunnel['last_write']) and body == tunnel['last_write']:
                    return self.reply(200, {'offset':tunnel['write_offset']})
                assert offset == tunnel['write_offset'] and len(body) <= 65536
                tunnel['socket'].sendall(body)
                tunnel['last_write'] = body
                tunnel['write_offset'] += len(body)
                return self.reply(200, {'offset':tunnel['write_offset']})
        if operation == 'close':
            tunnel['socket'].close()
            return self.reply(200, {'closed':True})
        return self.reply(404, {'error':'not_found'})


class OuterProxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    upstream_port = 0
    seen = []
    def log_message(self, *_): pass
    def do_CONNECT(self):
        self.seen.append(self.path)
        assert self.headers.get('Proxy-Authorization') == 'Basic ' + base64.b64encode(b'alice:secret').decode()
        upstream = socket.create_connection(('127.0.0.1', self.upstream_port))
        self.send_response(200); self.end_headers(); self.wfile.flush()
        try:
            while True:
                ready, _, _ = select.select([self.connection, upstream], [], [], 5)
                if not ready: return
                for source in ready:
                    block = source.recv(65536)
                    if not block: return
                    (upstream if source is self.connection else self.connection).sendall(block)
        finally:
            upstream.close(); self.close_connection = True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--browser', action='store_true'); args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = Path(tmp)/'cert.pem', Path(tmp)/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=gateway.test',
                        '-addext','subjectAltName=DNS:gateway.test,DNS:audit.test,DNS:third.test'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert,key)
        plain = serve(ThreadingHTTPServer(('127.0.0.1',0), Origin))
        secure = ThreadingHTTPServer(('127.0.0.1',0), Origin); secure.socket = tls.wrap_socket(secure.socket,server_side=True); serve(secure)
        Relay.plain_port, Relay.tls_port = plain.server_port, secure.server_port
        api = ThreadingHTTPServer(('127.0.0.1',0), Relay); api.socket = tls.wrap_socket(api.socket,server_side=True); serve(api)
        OuterProxy.upstream_port = api.server_port
        outer = serve(ThreadingHTTPServer(('127.0.0.1',0), OuterProxy))
        old = {name:os.environ.get(name) for name in ('HTTPS_PROXY','NO_PROXY','PEPPER_RU_GATEWAY_CA_FILE')}
        os.environ.update(HTTPS_PROXY=f'http://alice:secret@127.0.0.1:{outer.server_port}',
                          NO_PROXY='gateway.test,audit.test,third.test', PEPPER_RU_GATEWAY_CA_FILE=str(cert))
        bridge = None
        try:
            client = net.GatewayClient('https://gateway.test/ru-audit')
            client.capabilities()
            client.create('https://audit.test')
            bridge = net.RelayBridge(client).start()
            trust = ssl.create_default_context(cafile=str(cert))
            requester = net.opener(bridge.proxy_url, trust)
            with requester.open('http://audit.test/plain', timeout=15) as response: assert response.read() == b'ok'
            with requester.open('https://audit.test/secure', timeout=15) as response: assert response.read() == b'ok'
            if args.browser:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(proxy={'server':bridge.server_url,'username':bridge.user,'password':bridge.password},
                                                 args=net.chromium_args(bridge.proxy_url)+['--ignore-certificate-errors'])
                    context = browser.new_context(ignore_https_errors=True)
                    page = context.new_page()
                    page.goto('https://audit.test/', wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_function("document.title==='ready' && document.body.dataset.ws==='ok'", timeout=20000)
                    assert page.evaluate('window.thirdPartyLoaded')
                    assert ('POST','/api') in Origin.seen
                    browser.close()
            assert OuterProxy.seen and all(x == 'gateway.test:443' for x in OuterProxy.seen)
            assert any('/v2/tunnels/' in x for x in Relay.seen)
            print('PASS relay over authenticated HTTPS environment proxy', len(OuterProxy.seen), 'outer CONNECTs')
        finally:
            if bridge: bridge.close()
            for name, value in old.items():
                if value is None: os.environ.pop(name, None)
                else: os.environ[name] = value
            for server in (outer,api,secure,plain): server.shutdown(); server.server_close()


if __name__ == '__main__': main()
