"""serp-socket CPython delegate: native builds use runtime primitives instead.

The compiler intercepts `from serp_socket import ...` (rtlib.py); natively the
runtime uses std::net. This file emulates the same handle-based API over the
stdlib socket module for CPython runs.

Handles are opaque ints. Error messages are normalized identically in both
worlds: OSError("connection refused" / "timed out" / "connection reset" /
"address in use" / "not connected" / "address resolution failed" /
"socket error"), ValueError for misuse (bad handle, wrong socket kind,
port out of range).
"""

import errno as _errno
import select as _select
import socket as _socket
import ssl as _ssl
import time as _time

__all__ = ["connect", "tls_connect", "listen", "accept", "send", "send_all",
           "recv", "shutdown_write", "set_timeout", "local_port", "close",
           "udp_bind", "udp_send_to", "udp_recv_from", "udp_peer_host",
           "udp_peer_port", "set_nonblocking", "set_async", "accept_nb", "poll_ready"]

_socks: dict[int, list] = {}
_next_h: list[int] = [0]


def set_async(h: int) -> None:
    """Async mode (D45) is a native-runtime feature; under CPython the socket stays
    blocking, so tasks doing network I/O serialize instead of interleaving."""
    _get(h)


def _socket_of(h: int):
    """The underlying socket object (used by the _serp_asyncio reactor delegate)."""
    return _get(h)[0]

_ADDRINUSE = {getattr(_errno, n) for n in ("EADDRINUSE", "WSAEADDRINUSE")
              if hasattr(_errno, n)}


def _norm(e: BaseException) -> OSError:
    """Map a socket exception to the normalized cross-world OSError."""
    if isinstance(e, BlockingIOError):
        return OSError("timed out")
    if isinstance(e, _socket.timeout):
        return OSError("timed out")
    if isinstance(e, ConnectionRefusedError):
        return OSError("connection refused")
    if isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return OSError("connection reset")
    if isinstance(e, _socket.gaierror):
        return OSError("address resolution failed")
    if isinstance(e, OSError):
        if e.errno in _ADDRINUSE:
            return OSError("address in use")
        if getattr(e, "winerror", None) == 10057 or e.errno == getattr(_errno, "ENOTCONN", -1):
            return OSError("not connected")
    return OSError("socket error")


def _push(sock, kind: str) -> int:
    """Register a socket and return its handle."""
    _next_h[0] += 1
    _socks[_next_h[0]] = [sock, kind, None]
    return _next_h[0]


def set_nonblocking(h: int) -> None:
    """Switch a socket (or listener) to non-blocking mode."""
    rec = _get(h)
    rec[0].setblocking(False)


def accept_nb(h: int) -> int:
    """Non-blocking accept: a new connection handle, or 0 when none is pending."""
    rec = _get(h)
    if rec[1] != "listener":
        raise ValueError("accept_nb() needs a listener")
    try:
        c, _addr = rec[0].accept()
        c.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
        return _push(c, "tcp")
    except BlockingIOError:
        return 0
    except OSError as e:
        raise _norm(e)


def poll_ready(packed: bytes, timeout_ms: int) -> bytes:
    """Readiness poll over packed i64-LE handles; returns the ready subset (input order)."""
    hs = []
    i = 0
    while i + 8 <= len(packed):
        hs.append(int.from_bytes(packed[i:i + 8], "little"))
        i += 8
    if not hs:
        _time.sleep(max(timeout_ms, 0) / 1000.0)
        return b""
    ready_now = set()
    waitable = []
    for h in hs:
        rec = _socks.get(h)
        if rec is None:
            ready_now.add(h)
            continue
        if getattr(rec[0], "pending", None) is not None and rec[0].pending() > 0:
            ready_now.add(h)
            continue
        waitable.append((rec[0], h))
    if not ready_now and waitable:
        r, _w, _x = _select.select([s for s, _h in waitable], [], [],
                                   max(timeout_ms, 0) / 1000.0)
        ready_set = set(id(s) for s in r)
        for s, h in waitable:
            if id(s) in ready_set:
                ready_now.add(h)
    out = b""
    for h in hs:
        if h in ready_now:
            out += int(h).to_bytes(8, "little")
    return out


def _get(h: int) -> list:
    """Look up a socket record or raise the normalized handle error."""
    rec = _socks.get(h)
    if rec is None:
        raise ValueError("invalid socket handle")
    return rec


def _port_ok(port: int) -> int:
    """Reject ports outside 0..65535."""
    if port < 0 or port > 65535:
        raise ValueError("port out of range")
    return port


def connect(host: str, port: int, timeout_ms: int) -> int:
    """Open a TCP connection; timeout_ms > 0 bounds the connect."""
    _port_ok(port)
    try:
        if timeout_ms > 0:
            s = _socket.create_connection((host, port), timeout_ms / 1000.0)
            s.settimeout(None)
        else:
            s = _socket.create_connection((host, port))
        return _push(s, "tcp")
    except (OSError, _socket.timeout) as e:
        raise _norm(e)


def tls_connect(host: str, port: int, timeout_ms: int, insecure: int) -> int:
    """Open a TCP connection wrapped in TLS (SNI + system trust; insecure=1 skips verify)."""
    _port_ok(port)
    try:
        if timeout_ms > 0:
            s = _socket.create_connection((host, port), timeout_ms / 1000.0)
        else:
            s = _socket.create_connection((host, port))
    except (OSError, _socket.timeout) as e:
        raise _norm(e)
    try:
        ctx = _ssl.create_default_context()
        if insecure != 0:
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        w = ctx.wrap_socket(s, server_hostname=host)
        w.settimeout(None)
        return _push(w, "tcp")
    except _ssl.SSLCertVerificationError:
        s.close()
        raise OSError("certificate verify failed")
    except _socket.timeout:
        s.close()
        raise OSError("timed out")
    except (_ssl.SSLError, OSError):
        s.close()
        raise OSError("tls handshake failed")


def listen(host: str, port: int) -> int:
    """Bind a TCP listener (port 0 picks a free port)."""
    _port_ok(port)
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.bind((host, port))
        s.listen(16)
        return _push(s, "listener")
    except OSError as e:
        raise _norm(e)


def accept(h: int) -> int:
    """Accept one connection from a listener, returning a stream handle."""
    rec = _get(h)
    if rec[1] != "listener":
        raise ValueError("accept() needs a listener")
    try:
        conn, _addr = rec[0].accept()
        conn.settimeout(None)
        conn.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
        return _push(conn, "tcp")
    except (OSError, _socket.timeout) as e:
        raise _norm(e)


def send(h: int, data: bytes) -> int:
    """Send what the socket accepts right now; returns bytes actually written."""
    rec = _get(h)
    if rec[1] != "tcp":
        raise ValueError("send() needs a TCP stream")
    sent = 0
    while sent < len(data):
        try:
            n = rec[0].send(data[sent:])
        except BlockingIOError:
            break
        except (OSError, _socket.timeout) as e:
            if sent > 0:
                break
            raise _norm(e)
        if n <= 0:
            break
        sent += n
    return sent


def send_all(h: int, data: bytes, timeout_ms: int) -> int:
    """Send every byte, parking on writability when the send buffer is full."""
    rec = _get(h)
    if rec[1] != "tcp":
        raise ValueError("sendall() needs a TCP stream")
    s = rec[0]
    sent = 0
    while sent < len(data):
        try:
            n = s.send(data[sent:])
        except BlockingIOError:
            wait = timeout_ms / 1000.0 if timeout_ms > 0 else 1.0
            _r, w, _x = _select.select([], [s], [], wait)
            if not w and timeout_ms > 0:
                raise OSError("timed out")
            continue
        except (OSError, _socket.timeout) as e:
            raise _norm(e)
        if n <= 0:
            raise OSError("connection reset")
        sent += n
    return sent


def recv(h: int, maxlen: int) -> bytes:
    """Receive up to maxlen bytes; empty bytes means the peer closed."""
    if maxlen <= 0:
        raise ValueError("maxlen must be positive")
    rec = _get(h)
    if rec[1] != "tcp":
        raise ValueError("recv() needs a TCP stream")
    try:
        return rec[0].recv(maxlen)
    except (OSError, _socket.timeout) as e:
        raise _norm(e)


def shutdown_write(h: int) -> None:
    """Half-close the write side of a TCP stream (peer sees EOF)."""
    rec = _get(h)
    if rec[1] != "tcp":
        raise ValueError("shutdown_write() needs a TCP stream")
    try:
        rec[0].shutdown(_socket.SHUT_WR)
    except OSError as e:
        raise _norm(e)


def set_timeout(h: int, ms: int) -> None:
    """Set the read/write timeout in ms (0 = blocking) on a stream or UDP socket."""
    rec = _get(h)
    if rec[1] == "listener":
        raise ValueError("cannot set timeout on a listener")
    rec[0].settimeout(ms / 1000.0 if ms > 0 else None)


def local_port(h: int) -> int:
    """The locally bound port of any socket handle."""
    rec = _get(h)
    try:
        return rec[0].getsockname()[1]
    except OSError as e:
        raise _norm(e)


def close(h: int) -> None:
    """Close and invalidate a socket handle."""
    rec = _get(h)
    rec[0].close()
    del _socks[h]


def udp_bind(host: str, port: int) -> int:
    """Bind a UDP socket (port 0 picks a free port)."""
    _port_ok(port)
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.bind((host, port))
        return _push(s, "udp")
    except OSError as e:
        raise _norm(e)


def udp_send_to(h: int, data: bytes, host: str, port: int) -> int:
    """Send one datagram; returns the number of bytes sent."""
    _port_ok(port)
    rec = _get(h)
    if rec[1] != "udp":
        raise ValueError("udp_send_to() needs a UDP socket")
    try:
        return rec[0].sendto(data, (host, port))
    except (OSError, _socket.timeout) as e:
        raise _norm(e)


def udp_recv_from(h: int, maxlen: int) -> bytes:
    """Receive one datagram; the sender is remembered for udp_peer_host/port."""
    if maxlen <= 0:
        raise ValueError("maxlen must be positive")
    rec = _get(h)
    if rec[1] != "udp":
        raise ValueError("udp_recv_from() needs a UDP socket")
    try:
        data, addr = rec[0].recvfrom(maxlen)
        rec[2] = (addr[0], addr[1])
        return data
    except (OSError, _socket.timeout) as e:
        raise _norm(e)


def udp_peer_host(h: int) -> str:
    """Sender address of the last received datagram."""
    rec = _get(h)
    if rec[2] is None:
        raise ValueError("no datagram received yet")
    return rec[2][0]


def udp_peer_port(h: int) -> int:
    """Sender port of the last received datagram."""
    rec = _get(h)
    if rec[2] is None:
        raise ValueError("no datagram received yet")
    return rec[2][1]
