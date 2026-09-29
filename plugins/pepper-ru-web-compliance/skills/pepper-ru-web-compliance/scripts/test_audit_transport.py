"""Offline transport policy checks. Real sockets/browser live in test_gateway_network.py."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

import audit
import audit_transport as net
import collect
import detect
import registries


class PolicyTests(unittest.TestCase):
    def test_cyrillic_host_and_path_are_normalized_before_issuance(self):
        self.assertEqual(collect.normalize_target("https://пример.рф/тест#anchor"),
                         "https://xn--e1afmkfd.xn--p1ai/%D1%82%D0%B5%D1%81%D1%82")
        with self.assertRaises(ValueError):
            collect.normalize_target("https://user:secret@example.com")

    def test_explicit_proxy_ignores_bypass(self):
        handler = net.ForcedProxy({})
        request = urllib.request.Request('https://example.com/path')
        with patch('urllib.request.proxy_bypass', return_value=True):
            handler.proxy_open(request, 'http://alice:secret@127.0.0.1:3128', 'https')
        self.assertEqual(request.host, '127.0.0.1:3128')
        self.assertEqual(request._tunnel_host, 'example.com')
        self.assertNotIn('Proxy-authorization', request.headers)
        self.assertIn('Proxy-authorization', request.unredirected_hdrs)

    def test_missing_session_cannot_fetch(self):
        with patch.object(net, 'ACTIVE', None), patch.object(registries, '_proxy_url', None):
            with self.assertRaises(net.NetworkError):
                net.urlopen('https://example.com')
            with self.assertRaises(net.NetworkError):
                registries.http_get('https://minjust.gov.ru')

    def test_api_redirect_forbidden(self):
        with self.assertRaises(net.NetworkError):
            net.NoGatewayRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.com')

    def test_retry_reuses_key_and_never_retries_denial(self):
        client = net.GatewayClient('https://gateway.example')
        with patch.object(client, 'request', side_effect=[net.NetworkError('gateway_unreachable'), {'credential':'secret'}]) as call:
            client.create('https://example.com')
            self.assertEqual(call.call_args_list[0].args[3], call.call_args_list[1].args[3])
        with patch.object(client, 'request', side_effect=net.NetworkError('daily_quota')) as call:
            with self.assertRaises(net.NetworkError):
                client.create('https://example.com')
            self.assertEqual(call.call_count, 1)

    def test_tunnel_retry_keeps_offset_and_body(self):
        client = net.GatewayClient('https://gateway.example')
        tid = 'a' * 48
        with patch.object(client, 'request', side_effect=[net.NetworkError('gateway_unreachable'), {'offset':3}]) as call:
            self.assertEqual(client.write_tunnel(tid, 0, b'abc'), 3)
            self.assertEqual(call.call_args_list[0].args, call.call_args_list[1].args)
        with patch.object(client, 'raw', side_effect=[net.NetworkError('gateway_unreachable'), (200,b'abc',{})]) as call:
            self.assertEqual(client.read_tunnel(tid, 0), (b'abc', False))
            self.assertEqual(call.call_args_list[0].args, call.call_args_list[1].args)
        with patch.object(client, 'request', side_effect=net.NetworkError('daily_quota')) as call:
            with self.assertRaises(net.NetworkError): client.write_tunnel(tid, 0, b'abc')
            self.assertEqual(call.call_count, 1)

    def test_registry_variable_does_not_change_site(self):
        with patch.dict('os.environ', {'PEPPER_RU_REGISTRY_PROXY':'http://registry.example:80'}, clear=True):
            s = net.NetworkSession('https://example.com')
            self.assertEqual(s.mode, 'managed')
            self.assertIsNone(s.custom)

    def test_default_gateway_failure_does_not_fallback(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(net, 'GatewayClient') as client, patch.object(net, 'opener') as direct:
            client.return_value.credential = None
            client.return_value.create.side_effect = net.NetworkError('gateway_unreachable')
            with self.assertRaisesRegex(net.NetworkError, 'gateway_unreachable'):
                with net.NetworkSession('https://example.com'):
                    self.fail('entered')
            client.assert_called_once_with('https://lts.itsalt.ru/ru-audit')
            client.return_value.capabilities.assert_called_once_with()
            client.return_value.create.assert_called_once_with('https://example.com')
            direct.assert_not_called()
        with patch.dict('os.environ', {'PEPPER_RU_GATEWAY_URL': 'https://override.example'}, clear=True):
            self.assertEqual(net.NetworkSession('https://example.com').gateway_url, 'https://override.example')
            self.assertEqual(net.NetworkSession('https://example.com', gateway='https://explicit.example').gateway_url, 'https://explicit.example')

    def test_no_local_dns_in_custom_probe(self):
        s = net.NetworkSession('https://example.com', proxy='http://127.0.0.1:1')
        s.proxy = s.custom
        with patch('http.client.HTTPSConnection.connect', side_effect=OSError()), patch('socket.getaddrinfo') as dns:
            result = s.probe('example.com')
            self.assertEqual(result['ips'], [])
            self.assertEqual(result['dns_status'], 'UNKNOWN')
            dns.assert_not_called()

    def test_partial_report_cannot_be_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'manifest.json').write_text(json.dumps({'target':'https://example.com','pages':[], 'network':{'complete':False}}))
            with patch.object(registries, '_proxy_url', None), patch.object(registries, 'http_get', side_effect=AssertionError('network in offline detector')):
                report = detect.run(detect.Context(root))
            self.assertFalse(any(f['status'] in ('PASS','NA') for f in report['findings']))
            self.assertFalse(report['network']['complete'])

    def test_offline_audit_never_issues_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'manifest.json').write_text(json.dumps({'target':'https://example.com','pages':[]}))
            with patch.object(net, 'NetworkSession') as session, patch.object(net, 'preflight') as preflight:
                result = audit.main(['--offline', '--out', str(root), '--findings', str(root/'findings.json')])
                self.assertEqual(result, 0)
                session.assert_not_called()
                preflight.assert_not_called()

    def test_missing_browser_does_not_spend_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(net, 'preflight', side_effect=ImportError()), patch.object(net, 'NetworkSession') as session:
                self.assertEqual(audit.main(['https://example.com','--out',tmp]), 2)
                session.assert_not_called()

    def test_partial_manifest_survives_keyboard_interrupt(self):
        import argparse
        with tempfile.TemporaryDirectory() as tmp:
            active = net.NetworkSession('https://example.com')
            args = argparse.Namespace(target='https://example.com',out=tmp,source_dir=None)
            with patch.object(net, 'ACTIVE', active), patch.object(collect, 'collect_infra', side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    collect.collect(args)
            saved = json.loads((Path(tmp)/'manifest.json').read_text())
            self.assertFalse(saved['network']['complete'])


if __name__ == '__main__':
    unittest.main()
