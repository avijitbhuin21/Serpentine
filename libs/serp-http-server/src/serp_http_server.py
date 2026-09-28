"""serp-http-server — http.server-compatible blocking HTTP/1.1 server.

Class, field and method names mirror CPython's http.server
(HTTPServer, BaseHTTPRequestHandler, send_response, send_header,
end_headers, rfile/wfile, ...). Dispatch differs by necessity: instead
of subclassing a handler, call server.handle_request() in a loop and
answer on the returned request object, then finish() to close the
connection. Single-threaded, one request per connection, no TLS, no
chunked request bodies, no automatic Date/Server headers (deterministic
dual-run output). Malformed requests are answered 400 automatically and
returned with command == "".
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, dataclass, move
from _serp_socket import accept as _accept
from _serp_socket import close as _close
from _serp_socket import listen as _listen
from _serp_socket import local_port as _local_port
from _serp_socket import recv as _recv
from _serp_socket import send_all as _send_all
from _serp_socket import set_timeout as _set_timeout

MAX_HEAD: int = 65536


def _send(conn: int, data: bytes) -> int:
    """Write every byte of data to a connection, blocking until it all lands."""
    return _send_all(conn, data, 0)


def _status_text(code: int) -> str:
    if code == 200:
        return "OK"
    if code == 201:
        return "Created"
    if code == 204:
        return "No Content"
    if code == 301:
        return "Moved Permanently"
    if code == 302:
        return "Found"
    if code == 304:
        return "Not Modified"
    if code == 400:
        return "Bad Request"
    if code == 401:
        return "Unauthorized"
    if code == 403:
        return "Forbidden"
    if code == 404:
        return "Not Found"
    if code == 405:
        return "Method Not Allowed"
    if code == 500:
        return "Internal Server Error"
    if code == 501:
        return "Not Implemented"
    if code == 503:
        return "Service Unavailable"
    return "Unknown"


def _digits_ok(s: str) -> bool:
    if s == "":
        return False
    for ch in s:
        if ch < "0" or ch > "9":
            return False
    return True


def _read_head(conn: int) -> bytes:
    buf: bytearray = bytearray(b"")
    while len(buf) < MAX_HEAD:
        chunk: bytes = _recv(conn, 4096)
        if len(chunk) == 0:
            break
        buf.extend(chunk)
        if bytes(buf).find(b"\r\n\r\n") >= 0:
            break
    return bytes(buf)


@dataclass
class _Headers:
    lines: list[str]

    def get(self: Ref[_Headers], name: str, default: str = "") -> str:
        want: str = name.lower() + ": "
        for h in self.lines:
            if h.lower().startswith(want):
                return h[len(want):len(h)]
        return default


@dataclass
class _RFile:
    data: bytes
    pos: int = 0

    def read(self: Mut[_RFile], n: int = -1) -> bytes:
        if n < 0:
            rest: bytes = self.data[self.pos:len(self.data)]
            self.pos = len(self.data)
            return rest
        end: int = self.pos + n
        if end > len(self.data):
            end = len(self.data)
        part: bytes = self.data[self.pos:end]
        self.pos = end
        return part


@dataclass
class _WFile:
    conn: int

    def write(self: Ref[_WFile], data: bytes) -> int:
        return _send(self.conn, data)


@dataclass
class BaseHTTPRequestHandler:
    conn: int
    command: str
    path: str
    request_version: str
    headers: _Headers
    rfile: _RFile
    wfile: _WFile

    def send_response(self: Ref[BaseHTTPRequestHandler], code: int,
                      message: str = "") -> None:
        msg: str = message
        if msg == "":
            msg = _status_text(code)
        line: str = "HTTP/1.1 " + str(code) + " " + msg + "\r\n"
        x: int = _send(self.conn, line.encode("utf-8"))

    def send_response_only(self: Ref[BaseHTTPRequestHandler], code: int,
                           message: str = "") -> None:
        msg: str = message
        if msg == "":
            msg = _status_text(code)
        line: str = "HTTP/1.1 " + str(code) + " " + msg + "\r\n"
        x: int = _send(self.conn, line.encode("utf-8"))

    def send_header(self: Ref[BaseHTTPRequestHandler], keyword: str,
                    value: str) -> None:
        x: int = _send(self.conn, (keyword + ": " + value + "\r\n").encode("utf-8"))

    def end_headers(self: Ref[BaseHTTPRequestHandler]) -> None:
        x: int = _send(self.conn, b"\r\n")

    def send_error(self: Mut[BaseHTTPRequestHandler], code: int,
                   message: str = "") -> None:
        msg: str = message
        if msg == "":
            msg = _status_text(code)
        body: bytes = msg.encode("utf-8")
        head: str = "HTTP/1.1 " + str(code) + " " + _status_text(code) + "\r\n"
        head += "content-type: text/plain\r\n"
        head += "content-length: " + str(len(body)) + "\r\n"
        head += "connection: close\r\n\r\n"
        x: int = _send(self.conn, head.encode("utf-8"))
        x = _send(self.conn, body)
        _close(self.conn)
        self.conn = -1

    def finish(self: Mut[BaseHTTPRequestHandler]) -> None:
        if self.conn >= 0:
            _close(self.conn)
            self.conn = -1


def _bad_request(conn: int) -> BaseHTTPRequestHandler:
    try:
        x: int = _send(conn, b"HTTP/1.1 400 Bad Request\r\ncontent-length: 0\r\n"
                             b"connection: close\r\n\r\n")
    except OSError as e:
        pass
    _close(conn)
    empty: list[str] = []
    hdrs: _Headers = _Headers(move(empty))
    rf: _RFile = _RFile(b"")
    wf: _WFile = _WFile(-1)
    return BaseHTTPRequestHandler(-1, "", "", "", move(hdrs), move(rf), move(wf))


@dataclass
class HTTPServer:
    server_address: tuple[str, int]
    fd: int = -1
    server_name: str = ""
    server_port: int = 0

    def server_bind(self: Mut[HTTPServer]) -> None:
        self.fd = _listen(self.server_address[0], self.server_address[1])
        self.server_name = self.server_address[0]
        self.server_port = _local_port(self.fd)

    def handle_request(self: Mut[HTTPServer]) -> BaseHTTPRequestHandler:
        if self.fd < 0:
            self.server_bind()
        conn: int = _accept(self.fd)
        _set_timeout(conn, 10000)
        raw: bytes = _read_head(conn)
        sep: int = raw.find(b"\r\n\r\n")
        if sep < 0:
            return _bad_request(conn)
        head: bytes = raw[0:sep]
        rest: bytes = raw[sep + 4:len(raw)]
        lines: list[bytes] = head.split(b"\r\n")
        reqline: str = ""
        try:
            reqline = lines[0].decode("utf-8")
        except ValueError as e:
            return _bad_request(conn)
        parts: list[str] = reqline.split(" ")
        if len(parts) != 3:
            return _bad_request(conn)
        hlines: list[str] = []
        clen: int = 0
        i: int = 1
        while i < len(lines):
            hline: str = ""
            try:
                hline = lines[i].decode("utf-8")
            except ValueError as e:
                return _bad_request(conn)
            c: int = hline.find(":")
            if c > 0:
                hname: str = hline[0:c].strip()
                hval: str = hline[c + 1:len(hline)].strip()
                hlines.append(hname + ": " + hval)
                if hname.lower() == "content-length" and _digits_ok(hval):
                    clen = int(hval)
            i += 1
        body: bytearray = bytearray(rest)
        while len(body) < clen:
            chunk: bytes = _recv(conn, 4096)
            if len(chunk) == 0:
                break
            body.extend(chunk)
        full: bytes = bytes(body)
        hdrs: _Headers = _Headers(move(hlines))
        rf: _RFile = _RFile(full[0:clen])
        wf: _WFile = _WFile(conn)
        return BaseHTTPRequestHandler(conn, parts[0], parts[1], parts[2],
                                      move(hdrs), move(rf), move(wf))

    def server_close(self: Mut[HTTPServer]) -> None:
        if self.fd >= 0:
            _close(self.fd)
            self.fd = -1
