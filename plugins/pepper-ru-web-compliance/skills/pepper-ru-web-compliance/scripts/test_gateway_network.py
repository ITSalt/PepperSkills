"""Opt-in local socket/TLS/browser acceptance. No external sites or RU claim.
python test_gateway_network.py [--browser]
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import select
import socket
import ssl
import subprocess
import tempfile
import threading
import urllib.request

import audit_transport as net

class Origin(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen = []
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.do_GET()
    def do_GET(self):
        assert 'Proxy-Authorization' not in self.headers
        self.seen.append((self.command,self.path))
        if self.path == '/ws':
            self.send_response(101);self.send_header('Connection','Upgrade');self.send_header('Upgrade','websocket')
            # Browser handshake (also accepts raw echo test with no key).
            if self.headers.get('Sec-WebSocket-Key'):
                import hashlib
                key=self.headers['Sec-WebSocket-Key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
                self.send_header('Sec-WebSocket-Accept',base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
            self.end_headers()
            if self.headers.get('Sec-WebSocket-Key'):
                self.wfile.write(b'\x81\x02ok');self.wfile.flush()
            else:
                self.wfile.write(self.rfile.read(4));self.wfile.flush()
            self.close_connection=True;return
        body=b'ok';content='text/plain'
        if self.path == '/':
            content='text/html';body=b'''<script src="https://third.test/code.js"></script><iframe src="https://third.test/frame"></iframe>
<script>document.cookie='audit=1; SameSite=Lax; Secure';fetch('/api',{method:'POST',body:'evidence'});
navigator.serviceWorker.register('/sw.js').then(()=>navigator.serviceWorker.ready).then(()=>document.title='ready');
let w=new WebSocket('wss://third.test/ws');w.onmessage=()=>document.body.dataset.ws='ok';</script>'''
        elif self.path=='/code.js':content='text/javascript';body=b"window.thirdPartyLoaded=true;"
        elif self.path=='/sw.js':content='text/javascript';body=b"self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(clients.claim()));"
        self.send_response(200);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

class Gateway(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    expected='Basic '+base64.b64encode(b'session:credential').decode()
    seen=[]
    tls_port=0
    plain_port=0
    def log_message(self,*_):pass
    def do_CONNECT(self):
        self.seen.append(('CONNECT',self.path))
        assert self.headers['Proxy-Authorization']==self.expected
        upstream=socket.create_connection(('127.0.0.1',self.tls_port))
        self.send_response(200);self.end_headers();self.wfile.flush()
        self.relay(upstream)
    def relay(self,upstream):
        try:
            for _ in range(10000):
                ready,_,_=select.select([self.connection,upstream],[],[],5)
                if not ready:return
                for src in ready:
                    data=src.recv(32768)
                    if not data:return
                    (upstream if src is self.connection else self.connection).sendall(data)
        except (OSError,ssl.SSLError):pass
        finally:upstream.close();self.close_connection=True
    def do_GET(self):
        from urllib.parse import urlsplit
        assert self.headers['Proxy-Authorization']==self.expected
        self.seen.append(('GET',self.path))
        upstream=socket.create_connection(('127.0.0.1',self.plain_port))
        p=urlsplit(self.path)
        headers=''.join(f'{k}: {v}\r\n' for k,v in self.headers.items() if k.lower()!='proxy-authorization')
        upstream.sendall(f'GET {p.path or "/"} HTTP/1.1\r\n{headers}\r\n'.encode())
        self.relay(upstream)


def serve(server):
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--browser',action='store_true');args=ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        cert,key=Path(tmp)/'cert.pem',Path(tmp)/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,DNS:audit.test,DNS:third.test,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
        plain=serve(ThreadingHTTPServer(('127.0.0.1',0),Origin))
        secure=ThreadingHTTPServer(('127.0.0.1',0),Origin);secure.socket=tls.wrap_socket(secure.socket,server_side=True);serve(secure)
        Gateway.plain_port,Gateway.tls_port=plain.server_port,secure.server_port
        gateway=ThreadingHTTPServer(('127.0.0.1',0),Gateway);gateway.socket=tls.wrap_socket(gateway.socket,server_side=True);serve(gateway)
        trust=ssl.create_default_context(cafile=str(cert))
        bridge=net.ProxyBridge(f'https://localhost:{gateway.server_port}','session:credential',context=trust).start()
        try:
            client=net.opener(bridge.proxy_url,trust)
            with client.open('http://audit.test/plain',timeout=5) as r:assert r.read()==b'ok'
            with client.open('https://audit.test/secure',timeout=5) as r:assert r.read()==b'ok'
            # Unauthenticated bridge requests never reach the gateway.
            before=len(Gateway.seen)
            s=socket.create_connection(('127.0.0.1',bridge.port));s.sendall(b'CONNECT audit.test:443 HTTP/1.1\r\nHost: audit.test:443\r\n\r\n');assert b'407' in s.recv(1024);s.close();assert len(Gateway.seen)==before
            s=socket.create_connection(('127.0.0.1',bridge.port));s.settimeout(5)
            s.sendall(f'GET http://audit.test/ws HTTP/1.1\r\nHost: audit.test\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nProxy-Authorization: {bridge.auth}\r\n\r\n'.encode())
            f=s.makefile('rb');assert b'101' in f.readline()
            while f.readline()!=b'\r\n':pass
            s.sendall(b'echo');assert f.read(4)==b'echo';f.close();s.close()
            if args.browser:
                from playwright.sync_api import sync_playwright
                session=net.NetworkSession('https://audit.test');session.proxy=bridge.proxy_url
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(proxy=session.browser_proxy(),args=net.chromium_args(session.proxy)+['--ignore-certificate-errors'])
                    # Test-only self-signed origin certificate. Production never disables certificate validation.
                    context=browser.new_context(ignore_https_errors=True)
                    page=context.new_page();page.on('pageerror',lambda e: print('fixture page error:',e));page.on('requestfailed',lambda r: print('fixture failed:',r.url,r.failure));page.goto('https://audit.test/');page.wait_for_function("document.title==='ready' && document.body.dataset.ws==='ok'")
                    assert page.evaluate('window.thirdPartyLoaded')
                    assert any(c['name']=='audit' for c in context.cookies())
                    assert any(path=='/frame' for _,path in Origin.seen)
                    assert ('POST','/api') in Origin.seen
                    assert any('third.test' in path for _,path in Gateway.seen)
                    bridge.close()
                    try:page.goto('https://audit.test/unreachable',timeout=3000)
                    except Exception:pass
                    else:raise AssertionError('direct fallback after adapter stop')
                    browser.close()
            print(json.dumps({'TLS_CONNECT':True,'HTTP_stream':True,'WebSocket_upgrade':True,'local_auth':True,'proxy_credentials_stripped':True,'browser':args.browser,'external_RU_acceptance':False}))
        finally:
            bridge.close()
            for s in (gateway,secure,plain):s.shutdown();s.server_close()

if __name__=='__main__':main()
