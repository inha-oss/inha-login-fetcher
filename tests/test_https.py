"""Actual requests/urllib3/ssl integration, served entirely on numeric loopback.

Ephemeral synthetic PKI and accounts only. The transport changes the TCP destination,
not the request URL, TLS SNI, certificate hostname, Host header or cookie origin.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import gzip
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
import ssl
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from _network import sitecustomize as _network_guard
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.util.connection import create_connection

from inha_cloud import InhaCloud, LoginStatus
from inha_cloud.inha_cloud import _MAX_BODY_BYTES, _Session

HOST = "cloud.inha.ac.kr"
BASE = "https://" + HOST
ACCOUNT = "tls-synthetic-account"
PASSWORD = "tls-synthetic-password"
FORM = b'''<form action="/auth/login" method="POST">
<input type="hidden" name="_csrf" value="synthetic-csrf">
<input type="hidden" name="loginDomain" value="inha.ac.kr">
<input name="userid"><input type="password" name="password"></form>'''
IDENTITY = f'<div class="loginHeader" data-userid="{ACCOUNT}">Synthetic display</div>'.encode()


def _authority():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic local test CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .sign(key, hashes.SHA256()))
    return key, cert


def _leaf(authority, hostname=HOST, *, expired=False):
    ca_key, ca_cert = authority
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


@dataclass
class Reply:
    body: bytes = b""
    status: int = 200
    headers: dict = field(default_factory=dict)
    raw: bytes | None = None
    stall: str | None = None


class Site:
    """Small stateful origin: POST and account access require preceding cookies."""

    def __init__(self, *, fault_stage=None, fault=None, cookie_domain=HOST, landing=FORM, gzip_landing=False):
        self.fault_stage = fault_stage
        self.fault = fault
        self.cookie_domain = cookie_domain
        self.landing = landing
        self.gzip_landing = gzip_landing
        self.authenticated = False
        self.requests = []
        self.forms = []

    def respond(self, method, path, headers, body):
        self.requests.append((method, path, dict(headers), body))
        cookies = SimpleCookie(headers.get("Cookie", ""))
        auth = cookies.get("SYNTHAUTH")
        stage = "login" if method == "POST" else "account" if auth else "landing"
        if stage == self.fault_stage:
            return self.fault
        if method == "POST" and path == "/auth/login":
            fields = parse_qs(body.decode("utf-8"))
            self.forms.append(fields)
            pre = cookies.get("SYNTHPRE")
            if (pre is not None and pre.value == "synthetic-preauth"
                    and fields == {"_csrf": ["synthetic-csrf"], "loginDomain": ["inha.ac.kr"],
                                   "userid": [ACCOUNT], "password": [PASSWORD]}):
                self.authenticated = True
                return Reply(status=303, headers={"Location": "/", "Set-Cookie":
                    f"SYNTHAUTH=synthetic-session; Domain={self.cookie_domain}; Path=/; Secure; HttpOnly"})
            return Reply(FORM)
        if method == "GET" and path == "/":
            if auth and auth.value == "synthetic-session" and self.authenticated:
                return Reply(IDENTITY)
            headers = {"Set-Cookie": "SYNTHPRE=synthetic-preauth; Path=/; Secure; HttpOnly"}
            if self.gzip_landing:
                headers["Content-Encoding"] = "gzip"
            return Reply(gzip.compress(self.landing, mtime=0) if self.gzip_landing else self.landing,
                         headers=headers)
        return Reply(status=404)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, context, site):
        self.context = context
        self.site = site
        self.release = threading.Event()
        self.stalled = threading.Event()
        self.condition = threading.Condition()
        self.active = 0
        self.finished = 0
        self.sni = []
        self.tls = []
        self.errors = []
        self.workers = []
        context.set_servername_callback(lambda sock, name, ctx: self.sni.append(name))
        super().__init__(("127.0.0.1", 0), Handler)

    def server_bind(self):
        # HTTPServer.server_bind would call getfqdn, including reverse DNS.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.socket.getsockname()[1]

    def get_request(self):
        sock, address = super().get_request()
        try:
            return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), address
        except BaseException:
            sock.close()
            raise

    def process_request(self, request, address):
        with self.condition:
            self.active += 1
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        self.workers.append(threading.current_thread())
        super().process_request_thread(request, address)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            with self.condition:
                self.active -= 1
                self.finished += 1
                self.condition.notify_all()

    def handle_error(self, request, address):
        self.errors.append(sys.exc_info()[1])

    def wait_finished(self, count):
        with self.condition:
            return self.condition.wait_for(lambda: self.finished >= count, timeout=5)

    def wait_idle(self):
        with self.condition:
            return self.condition.wait_for(lambda: self.active == 0, timeout=5)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 5

    def handle(self):
        try:
            self.connection.do_handshake()
        except (ssl.SSLError, OSError):
            return  # Expected certificate rejection; no HTTP request was read.
        self.server.tls.append(self.connection.version())
        super().handle()

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        self.close_connection = True
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        reply = self.server.site.respond(self.command, self.path, self.headers, body)
        try:
            if reply.raw is not None:
                self.connection.sendall(reply.raw)
                return
            if reply.stall == "headers":
                self.server.stalled.set()
                self.server.release.wait(15)
                return
            self.send_response(reply.status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(reply.body) + (1 if reply.stall == "body" else 0)))
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(reply.body)
            self.wfile.flush()
            if reply.stall == "body":
                self.server.stalled.set()
                self.server.release.wait(15)
        except (ConnectionError, ssl.SSLError):
            pass  # Oversize-response and timeout tests deliberately close early.


class LoopbackAdapter(HTTPAdapter):
    """Only TCP dialing is rerouted; TLS still validates the logical hostname."""

    def __init__(self, port, ca_pem):
        self.calls = []
        self.dials = []
        self.tls_errors = []
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cadata=ca_pem.decode("ascii"))
        dials = self.dials

        class Connection(HTTPSConnection):
            def _new_conn(self):
                dials.append((self.host, self.port, "127.0.0.1", port))
                return create_connection(("127.0.0.1", port), self.timeout,
                                         source_address=self.source_address,
                                         socket_options=self.socket_options)

        class Pool(HTTPSConnectionPool):
            ConnectionCls = Connection

        self.pool_class = Pool
        super().__init__(max_retries=0)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = dict(self.poolmanager.pool_classes_by_scheme,
                                                       https=self.pool_class)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        hosts, options = super().build_connection_pool_key_attributes(request, verify, cert)
        options["ssl_context"] = self.context
        return hosts, options

    def send(self, request, **kwargs):
        if not request.url.startswith(BASE + "/"):
            raise AssertionError("Unexpected logical origin in local TLS fixture")
        if kwargs.get("verify") is not True or not self.context.check_hostname:
            raise AssertionError("TLS verification must remain enabled")
        self.calls.append((request.method, request.url, kwargs["timeout"]))
        try:
            return super().send(request, **kwargs)
        except requests.exceptions.SSLError as error:
            self.tls_errors.append(error)
            raise


class LoopbackSession(_Session):
    def __init__(self, adapter):
        super().__init__()
        self.mount("https://", adapter)
        self.closed = False

    def close(self):
        self.closed = True
        super().close()


class LocalHttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = _authority()
        cls.ca_pem = cls.authority[1].public_bytes(serialization.Encoding.PEM)
        cls.leaves = {"valid": _leaf(cls.authority),
                      "wrong_hostname": _leaf(cls.authority, "localhost"),
                      "untrusted": _leaf(_authority()),
                      "expired": _leaf(cls.authority, expired=True)}

    @contextmanager
    def local(self, site=None, *, certificate="valid"):
        site = site if site is not None else Site()
        key, cert = self.leaves[certificate]
        with TemporaryDirectory(prefix="inha-local-tls-") as directory:
            key_path = Path(directory) / "leaf.key"
            cert_path = Path(directory) / "leaf.pem"
            # Exclusive creation with owner-only permissions; no committed keys.
            with key_path.open("xb") as stream:
                key_path.chmod(0o600)
                stream.write(key.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(cert_path), str(key_path))
            server = LocalServer(context, site)
            adapter = session = thread = None
            try:
                adapter = LoopbackAdapter(server.server_port, self.ca_pem)
                session = LoopbackSession(adapter)
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02},
                                          name="synthetic-tls-listener", daemon=True)
                thread.start()
                with patch("inha_cloud.inha_cloud._Session", return_value=session):
                    yield server, site, session, adapter
            finally:
                if session is not None:
                    session.close()
                elif adapter is not None:
                    adapter.close()
                server.release.set()
                if thread is not None and thread.ident is not None:
                    server.shutdown()
                server.server_close()
                if thread is not None and thread.ident is not None:
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive(), "TLS listener failed to terminate")
                self.assertTrue(server.wait_idle(), "TLS connection handler failed to terminate")
                for worker in server.workers:
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive(), "TLS worker failed to terminate")
            self.assertEqual(server.errors, [], "Unexpected server-side handler error")

    def assert_requests(self, site, stages):
        self.assertEqual([(method, path) for method, path, _, _ in site.requests], stages)

    def test_verified_tls_login_303_cookie_session_and_expiry(self):
        with self.local() as (server, site, session, adapter):
            with InhaCloud(timeout=3) as client:
                result = client.login(ACCOUNT, PASSWORD)
                self.assertEqual(result.status, LoginStatus.SUCCESS)
                self.assertEqual(result.identity.account_id, ACCOUNT)
                self.assertEqual(result.identity.display_name, "Synthetic display")
                self.assertEqual(result.http_status, 200)
                self.assert_requests(site, [("GET", "/"), ("POST", "/auth/login"), ("GET", "/")])
                self.assertIn("SYNTHPRE=synthetic-preauth", site.requests[1][2]["Cookie"])
                self.assertIn("SYNTHAUTH=synthetic-session", site.requests[2][2]["Cookie"])
                self.assertEqual(client.fetch_login_info().status, LoginStatus.SUCCESS)
                site.authenticated = False
                self.assertEqual(client.fetch_login_info().status, LoginStatus.REJECTED)
                count = len(site.requests)
                self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                self.assertEqual(len(site.requests), count)
                self.assertTrue(session.closed)
                self.assertEqual(len(session.cookies), 0)
            self.assertTrue(server.wait_finished(len(site.requests)))
            self.assertEqual(server.sni, [HOST] * len(site.requests))
            self.assertTrue(all(version in {"TLSv1.2", "TLSv1.3"} for version in server.tls))
            self.assertTrue(all(headers["Host"] == HOST for _, _, headers, _ in site.requests))
            self.assertTrue(all(call[1].startswith(BASE) and call[2] == (3.0, 3.0) for call in adapter.calls))
            self.assertEqual(adapter.dials, [(HOST, 443, "127.0.0.1", server.server_port)] * len(site.requests))

    def test_account_requires_cookie_accepted_for_logical_origin(self):
        # A cookie for another domain must not authorize the subsequent account GET.
        with self.local(Site(cookie_domain="unrelated.invalid")) as (_, site, session, _):
            with InhaCloud(timeout=3) as client:
                self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.REJECTED)
            self.assert_requests(site, [("GET", "/"), ("POST", "/auth/login"), ("GET", "/")])
            self.assertNotIn("SYNTHAUTH", site.requests[2][2].get("Cookie", ""))
            self.assertTrue(session.closed)

    def test_certificate_failures_precede_all_http_and_credentials(self):
        for certificate in ("wrong_hostname", "untrusted", "expired"):
            with self.subTest(certificate=certificate), self.local(certificate=certificate) as (server, site, session, adapter):
                with InhaCloud(timeout=3) as client:
                    self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.NETWORK_ERROR)
                    self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                self.assertTrue(server.wait_finished(1))
                self.assertEqual(site.requests, [])
                self.assertEqual(len(adapter.calls), 1)
                self.assertEqual(len(adapter.tls_errors), 1)
                self.assertTrue(session.closed)

    def test_real_read_timeouts_before_headers_and_during_body_never_retry(self):
        for stage in ("landing", "login", "account"):
            for stall in ("headers", "body"):
                site = Site(fault_stage=stage, fault=Reply(body=b"partial", stall=stall))
                with self.subTest(stage=stage, stall=stall), self.local(site) as (server, _, session, adapter):
                    with InhaCloud(timeout=1) as client:
                        self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.NETWORK_ERROR)
                        self.assertTrue(server.stalled.is_set(), "Server never reached the read stall")
                        self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                    expected = [("GET", "/")]
                    if stage != "landing":
                        expected.append(("POST", "/auth/login"))
                    if stage == "account":
                        expected.append(("GET", "/"))
                    self.assert_requests(site, expected)
                    self.assertEqual(len(adapter.calls), len(expected))
                    self.assertTrue(session.closed)

    def test_malformed_wire_responses_never_retry_credentials(self):
        faults = {
            "bad_status": Reply(raw=b"HTTP/1.1 invalid status\r\n\r\n"),
            "truncated_chunk": Reply(raw=b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                                          b"Content-Type: text/html\r\nConnection: close\r\n\r\n8\r\nshort"),
            "bad_chunk_length": Reply(raw=b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                                           b"Connection: close\r\n\r\nnot-hex\r\n"),
            "bad_gzip": Reply(body=b"not a gzip stream", headers={"Content-Encoding": "gzip"}),
            "disconnect": Reply(raw=b""),
        }
        for stage in ("landing", "login", "account"):
            for fault_name, fault in faults.items():
                with self.subTest(stage=stage, fault=fault_name), self.local(Site(fault_stage=stage, fault=fault)) as (_, site, session, adapter):
                    with InhaCloud(timeout=3) as client:
                        self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.NETWORK_ERROR)
                        self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                    expected = [("GET", "/")]
                    if stage != "landing":
                        expected.append(("POST", "/auth/login"))
                    if stage == "account":
                        expected.append(("GET", "/"))
                    self.assert_requests(site, expected)
                    self.assertEqual(len(adapter.calls), len(expected))
                    self.assertTrue(session.closed)

    def test_nonstandard_status_codes_invalidate_real_cookie_session(self):
        for stage in ("landing", "login", "account"):
            for status in (600, 999):
                site = Site(fault_stage=stage, fault=Reply(status=status))
                with self.subTest(stage=stage, status=status), self.local(site) as (_, _, session, adapter):
                    with InhaCloud(timeout=3) as client:
                        result = client.login(ACCOUNT, PASSWORD)
                        self.assertEqual(result.status, LoginStatus.HTTP_ERROR)
                        self.assertIsNone(result.http_status)
                        self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                    expected = [("GET", "/")]
                    if stage != "landing":
                        expected.append(("POST", "/auth/login"))
                    if stage == "account":
                        expected.append(("GET", "/"))
                    self.assert_requests(site, expected)
                    self.assertEqual(len(adapter.calls), len(expected))
                    self.assertTrue(session.closed)

    def test_decoded_size_limit_accepts_exact_boundary_and_rejects_one_byte_over(self):
        for compressed in (False, True):
            for extra in (0, 1):
                size = _MAX_BODY_BYTES + extra
                body = FORM + b"<!--" + b"x" * (size - len(FORM) - 7) + b"-->"
                self.assertEqual(len(body), size)
                site = Site(landing=body, gzip_landing=compressed)
                with self.subTest(gzip=compressed, extra=extra), self.local(site) as (_, _, session, _):
                    with InhaCloud(timeout=3) as client:
                        self.assertEqual(client.login(ACCOUNT, PASSWORD).status,
                                         LoginStatus.PAGE_CHANGED if extra else LoginStatus.SUCCESS)
                    self.assertEqual(sum(method == "POST" for method, _, _, _ in site.requests),
                                     0 if extra else 1)
                    self.assertTrue(session.closed)

    def test_redirect_policies_apply_before_any_tls_followup(self):
        cases = [("/auth/mfa", 303, LoginStatus.ADDITIONAL_AUTH),
                 ("/auth/%6dfa/pin", 303, LoginStatus.ADDITIONAL_AUTH),
                 ("/auth/./mfa/pin", 303, LoginStatus.ADDITIONAL_AUTH),
                 ("https://unrelated.invalid/", 303, LoginStatus.UNSAFE_DESTINATION),
                 ("http://cloud.inha.ac.kr/", 303, LoginStatus.UNSAFE_DESTINATION),
                 ("/auth/login", 307, LoginStatus.UNSAFE_DESTINATION),
                 ("/auth/login", 308, LoginStatus.UNSAFE_DESTINATION)]
        for target, status, expected in cases:
            site = Site(fault_stage="login", fault=Reply(status=status, headers={"Location": target}))
            with self.subTest(target=target, status=status), self.local(site) as (_, _, _, adapter):
                with InhaCloud(timeout=3) as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, expected)
                self.assert_requests(site, [("GET", "/"), ("POST", "/auth/login")])
                self.assertEqual(len(adapter.calls), 2)


if __name__ == "__main__":
    unittest.main()
