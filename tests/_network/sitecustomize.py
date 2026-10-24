"""Test-process guard: allow loopback/Unix sockets, reject external DNS and connects.

Imported by test modules, or by Python startup for CLI subprocesses via PYTHONPATH.
This is a regression safety net for Python sockets, not an operating-system sandbox.
"""
import ipaddress
import socket


def _require_loopback(address):
    if not isinstance(address, tuple):
        return  # Unix-domain sockets do not leave the host.
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii")
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise AssertionError("External networking is disabled in tests")


def _install():
    if getattr(socket, "_inha_loopback_only", False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo

    def connect(sock, address):
        _require_loopback(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        _require_loopback(address)
        return original_connect_ex(sock, address)

    def sendto(sock, data, *args):
        _require_loopback(args[-1])
        return original_sendto(sock, data, *args)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host == "localhost":
            host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        if host is not None:
            _require_loopback((host, port))
        return original_getaddrinfo(host, port, family, type, proto, flags)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket._inha_loopback_only = True


_install()
