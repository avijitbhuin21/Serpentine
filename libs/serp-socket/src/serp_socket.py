"""serp-socket — socket-module-compatible networking in the Serpentine subset.

The `socket` class, constants and exception types mirror CPython's socket
module. The transport core is the intercepted _serp_socket runtime module:
std::net natively, a stdlib delegate under CPython. IPv4 TCP/UDP only;
SHUT_WR is the only supported shutdown mode; non-blocking mode is not
available (settimeout(0) raises ValueError).
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, dataclass, move
from _serp_socket import accept as _accept
from _serp_socket import close as _close
from _serp_socket import connect as _connect
from _serp_socket import listen as _listen
from _serp_socket import local_port as _local_port
from _serp_socket import recv as _recv
from _serp_socket import send as _send
from _serp_socket import set_timeout as _set_timeout
from _serp_socket import shutdown_write as _shutdown_write
from _serp_socket import udp_bind as _udp_bind
from _serp_socket import udp_peer_host as _udp_peer_host
from _serp_socket import udp_peer_port as _udp_peer_port
from _serp_socket import udp_recv_from as _udp_recv_from
from _serp_socket import udp_send_to as _udp_send_to

AF_INET: int = 2
SOCK_STREAM: int = 1
SOCK_DGRAM: int = 2
SHUT_RD: int = 0
SHUT_WR: int = 1
SHUT_RDWR: int = 2


class ConnectionError(OSError):
    pass


class ConnectionRefusedError(ConnectionError):
    pass


class ConnectionResetError(ConnectionError):
    pass


class ConnectionAbortedError(ConnectionError):
    pass


class BrokenPipeError(ConnectionError):
    pass


class TimeoutError(OSError):
    pass


class timeout(TimeoutError):
    pass


class gaierror(OSError):
    pass


class herror(OSError):
    pass


def _mapped(msg: str) -> None:
    if msg == "connection refused":
        raise ConnectionRefusedError(msg)
    if msg == "connection reset":
        raise ConnectionResetError(msg)
    if msg == "timed out":
        raise timeout(msg)
    if msg == "address resolution failed":
        raise gaierror(msg)
    raise OSError(msg)


@dataclass
class socket:
    family: int = 2
    type: int = 1
    proto: int = 0
    fd: int = -1
    timeout_ms: int = 0
    laddr: str = ""
    listening: bool = False

    def connect(self: Mut[socket], address: tuple[str, int]) -> None:
        if self.type != 1:
            raise OSError("connect() needs a SOCK_STREAM socket")
        try:
            self.fd = _connect(address[0], address[1], self.timeout_ms)
        except OSError as e:
            _mapped(str(e))
        if self.timeout_ms > 0:
            _set_timeout(self.fd, self.timeout_ms)

    def bind(self: Mut[socket], address: tuple[str, int]) -> None:
        try:
            if self.type == 2:
                self.fd = _udp_bind(address[0], address[1])
            else:
                self.fd = _listen(address[0], address[1])
                self.listening = True
        except OSError as e:
            _mapped(str(e))
        self.laddr = address[0]
        if self.type == 2 and self.timeout_ms > 0:
            _set_timeout(self.fd, self.timeout_ms)

    def listen(self: Ref[socket], backlog: int = 128) -> None:
        if self.fd < 0 or not self.listening:
            raise OSError("bind() must be called before listen()")

    def accept(self: Ref[socket]) -> socket:
        try:
            fd: int = _accept(self.fd)
            return socket(self.family, self.type, self.proto, fd)
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def send(self: Ref[socket], data: bytes) -> int:
        try:
            return _send(self.fd, data)
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def sendall(self: Ref[socket], data: bytes) -> None:
        try:
            n: int = _send(self.fd, data)
        except OSError as e:
            _mapped(str(e))

    def recv(self: Ref[socket], bufsize: int) -> bytes:
        try:
            return _recv(self.fd, bufsize)
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def sendto(self: Mut[socket], data: bytes, address: tuple[str, int]) -> int:
        if self.type != 2:
            raise OSError("sendto() needs a SOCK_DGRAM socket")
        if self.fd < 0:
            self.fd = _udp_bind("0.0.0.0", 0)
            if self.timeout_ms > 0:
                _set_timeout(self.fd, self.timeout_ms)
        try:
            return _udp_send_to(self.fd, data, address[0], address[1])
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def recvfrom(self: Ref[socket], bufsize: int) -> tuple[bytes, tuple[str, int]]:
        try:
            data: bytes = _udp_recv_from(self.fd, bufsize)
            return (data, (_udp_peer_host(self.fd), _udp_peer_port(self.fd)))
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def settimeout(self: Mut[socket], value: float | None) -> None:
        if value is None:
            self.timeout_ms = 0
        else:
            if value <= 0.0:
                raise ValueError("non-blocking and negative timeouts are not supported")
            self.timeout_ms = int(value * 1000.0)
        if self.fd >= 0 and not self.listening:
            _set_timeout(self.fd, self.timeout_ms)

    def gettimeout(self: Ref[socket]) -> float | None:
        if self.timeout_ms == 0:
            return None
        return self.timeout_ms / 1000.0

    def getsockname(self: Ref[socket]) -> tuple[str, int]:
        host: str = self.laddr
        if host == "":
            host = "0.0.0.0"
        if self.fd < 0:
            return (host, 0)
        try:
            return (host, _local_port(self.fd))
        except OSError as e:
            _mapped(str(e))
        raise OSError("unreachable")

    def shutdown(self: Ref[socket], how: int) -> None:
        if how != 1:
            raise ValueError("only SHUT_WR is supported")
        try:
            _shutdown_write(self.fd)
        except OSError as e:
            _mapped(str(e))

    def fileno(self: Ref[socket]) -> int:
        return self.fd

    def close(self: Mut[socket]) -> None:
        if self.fd >= 0:
            _close(self.fd)
            self.fd = -1


def create_connection(address: tuple[str, int], timeout: float = -1.0) -> socket:
    s: socket = socket(2, 1)
    if timeout >= 0.0:
        s.settimeout(timeout)
    s.connect(address)
    return s
