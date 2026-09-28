"""serp-fang (Fang) — an httpx-style sync HTTP/1.1 client in the Serpentine subset.

Pure Serpentine ([P]) façade over a native transport core: serp-socket
(std::net + schannel/OpenSSL TLS) and serp-url, with the same source
dual-running under CPython. Supports http:// and https:// (system trust
roots, verify=False opt-out), redirects, cookies, basic auth, query
params, forms, JSON, multipart uploads, gzip/deflate decoding, streamed
downloads and wire-chunked file uploads.

httpx parity notes: properties are methods (r.text() not r.text), kwargs
that take lists/dicts/bytes are explicit parameters or Client fields,
one connection per request (connection: close), sync only.
"""
from __future__ import annotations
from serpentine import Mut, Owned, PyVal, Ref, dataclass, move
from serp_base64 import b64encode
from serp_io import append_bytes, read_bytes, write_bytes
from serp_json import dumps, loads
from _serp_socket import close, connect, recv, send, set_async, set_timeout, tls_connect
from serp_time import monotonic
from serp_url import SplitResult, urlencode, urljoin, urlsplit
from serp_uuid_core import u4_str
from serp_zlib import decompress, gzip_decompress, inflate

USER_AGENT: str = "fang/0.2"


class HTTPStatusError(Exception):
    pass


class TooManyRedirects(Exception):
    pass


def header_value(headers: Ref[list[str]], name: str, default: str = "") -> str:
    """Return the value of the first header matching name (case-insensitive)."""
    want: str = name.lower() + ": "
    for h in headers:
        if h.startswith(want):
            return h[len(want):len(h)]
    return default


def _norm_header(line: str) -> str:
    """Normalize a header line to 'lowercase-name: value'."""
    c: int = line.find(":")
    if c <= 0:
        return line.strip().lower()
    return line[0:c].strip().lower() + ": " + line[c + 1:len(line)].strip()


def _has_header(headers: Ref[list[str]], name: str) -> bool:
    """True when a header with the given name is present."""
    want: str = name.lower() + ":"
    for h in headers:
        if h.startswith(want):
            return True
    return False


def _digits_ok(s: str) -> bool:
    """True when s is a non-empty run of ASCII digits."""
    if s == "":
        return False
    for ch in s:
        if ch < "0" or ch > "9":
            return False
    return True


def _hex_val(s: str) -> int:
    """Parse a hex string to int, or -1 when invalid."""
    v: int = 0
    digits: str = "0123456789abcdef"
    for ch in s.lower():
        d: int = digits.find(ch)
        if d < 0:
            return -1
        v = v * 16 + d
    if s == "":
        return -1
    return v


def decode_chunked(data: bytes) -> bytes:
    """Decode a complete chunked transfer-encoded body."""
    out: bytearray = bytearray(b"")
    i: int = 0
    n: int = len(data)
    while i < n:
        nl: int = data[i:n].find(b"\r\n")
        if nl < 0:
            break
        sizeline: str = data[i:i + nl].decode("utf-8")
        semi: int = sizeline.find(";")
        if semi >= 0:
            sizeline = sizeline[0:semi]
        size: int = _hex_val(sizeline.strip())
        if size < 0:
            break
        if size == 0:
            break
        start: int = i + nl + 2
        out.extend(data[start:start + size])
        i = start + size + 2
    return bytes(out)


def basic_auth(username: str, password: str) -> str:
    """Build an 'authorization: Basic ...' header line."""
    cred: str = username + ":" + password
    return "authorization: Basic " + b64encode(cred.encode()).decode()


def with_params(url: str, params: Ref[dict[str, str]]) -> str:
    """Append URL-encoded query params to a URL (httpx params=...)."""
    q: str = urlencode(params)
    if q == "":
        return url
    if url.find("?") >= 0:
        return url + "&" + q
    return url + "?" + q


@dataclass
class FilePart:
    name: str
    filename: str
    content_type: str
    data: bytes


def multipart_content_type(boundary: str) -> str:
    """The content-type header value for a multipart body."""
    return "multipart/form-data; boundary=" + boundary


def build_multipart(fields: Ref[dict[str, str]], files: Ref[list[FilePart]],
                    boundary: str) -> bytes:
    """Encode form fields and file parts as a multipart/form-data body."""
    out: bytearray = bytearray(b"")
    for k, v in fields.items():
        part: str = ("--" + boundary + '\r\ncontent-disposition: form-data; name="'
                     + k + '"\r\n\r\n' + v + "\r\n")
        out.extend(part.encode("utf-8"))
    for f in files:
        head: str = ("--" + boundary + '\r\ncontent-disposition: form-data; name="'
                     + f.name + '"; filename="' + f.filename
                     + '"\r\ncontent-type: ' + f.content_type + "\r\n\r\n")
        out.extend(head.encode("utf-8"))
        out.extend(f.data)
        out.extend(b"\r\n")
    out.extend(("--" + boundary + "--\r\n").encode("utf-8"))
    return bytes(out)


def _cookie_pairs(headers: Ref[list[str]]) -> list[str]:
    """Extract 'name=value' pairs from set-cookie response headers."""
    out: list[str] = []
    for h in headers:
        if h.startswith("set-cookie: "):
            v: str = h[12:len(h)]
            semi: int = v.find(";")
            if semi >= 0:
                v = v[0:semi]
            v = v.strip()
            if v.find("=") > 0:
                out.append(v)
    return out


def _jar_set(jar: Mut[list[str]], pair: str) -> None:
    """Insert or replace one 'name=value' cookie in a jar."""
    eq: int = pair.find("=")
    if eq <= 0:
        return
    name: str = pair[0:eq]
    i: int = 0
    while i < len(jar):
        if jar[i].startswith(name + "="):
            jar[i] = pair
            return
        i += 1
    jar.append(pair)
    return


def _store_cookies(headers: Ref[list[str]], jar: Mut[list[str]]) -> None:
    """Merge set-cookie headers from a response into a cookie jar."""
    pairs: list[str] = _cookie_pairs(headers)
    for p in pairs:
        _jar_set(jar, p)
    return


def _redirect_status(status: int) -> bool:
    """True for redirect status codes a client may follow."""
    return (status == 301 or status == 302 or status == 303
            or status == 307 or status == 308)


@dataclass
class Response:
    status_code: int
    reason_phrase: str
    http_version: str
    url: str
    headers: list[str]
    content: bytes
    history: list[str]
    elapsed: float

    def header(self: Ref[Response], name: str, default: str = "") -> str:
        return header_value(self.headers, name, default)

    def text(self: Ref[Response]) -> str:
        return self.content.decode("utf-8")

    def json(self: Ref[Response]) -> PyVal:
        return loads(self.content.decode("utf-8"))

    def cookies(self: Ref[Response]) -> list[str]:
        return _cookie_pairs(self.headers)

    def is_informational(self: Ref[Response]) -> bool:
        return self.status_code >= 100 and self.status_code <= 199

    def is_success(self: Ref[Response]) -> bool:
        return self.status_code >= 200 and self.status_code <= 299

    def is_redirect(self: Ref[Response]) -> bool:
        return _redirect_status(self.status_code)

    def is_client_error(self: Ref[Response]) -> bool:
        return self.status_code >= 400 and self.status_code <= 499

    def is_server_error(self: Ref[Response]) -> bool:
        return self.status_code >= 500 and self.status_code <= 599

    def is_error(self: Ref[Response]) -> bool:
        return self.status_code >= 400 and self.status_code <= 599

    def has_redirect_location(self: Ref[Response]) -> bool:
        return _redirect_status(self.status_code) and header_value(self.headers, "location") != ""

    def raise_for_status(self: Ref[Response]) -> None:
        if self.is_success():
            return
        kind: str = "Informational response"
        if self.status_code >= 300 and self.status_code <= 399:
            kind = "Redirect response"
        if self.is_client_error():
            kind = "Client error"
        if self.is_server_error():
            kind = "Server error"
        raise HTTPStatusError(kind + " '" + str(self.status_code) + " "
                              + self.reason_phrase + "' for url '" + self.url + "'")


@dataclass
class ResponseStream:
    conn: int
    status_code: int
    reason_phrase: str
    http_version: str
    url: str
    headers: list[str]
    history: list[str]
    mode: int
    remaining: int
    chunk_left: int
    need_crlf: bool
    buf: bytes
    closed: bool
    started: float

    def header(self: Ref[ResponseStream], name: str, default: str = "") -> str:
        return header_value(self.headers, name, default)

    def _fill(self: Mut[ResponseStream]) -> bool:
        chunk: bytes = recv(self.conn, 65536)
        if len(chunk) == 0:
            return False
        self.buf = self.buf + chunk
        return True

    def _take(self: Mut[ResponseStream], max_bytes: int) -> bytes:
        n: int = max_bytes
        if len(self.buf) < n:
            n = len(self.buf)
        out: bytes = self.buf[0:n]
        self.buf = self.buf[n:len(self.buf)]
        return out

    def read(self: Mut[ResponseStream], max_bytes: int = 65536) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.closed or self.mode == 0:
            return b""
        if self.mode == 1:
            if self.remaining <= 0:
                return b""
            if len(self.buf) == 0:
                if not self._fill():
                    self.remaining = 0
                    return b""
            n: int = max_bytes
            if self.remaining < n:
                n = self.remaining
            out: bytes = self._take(n)
            self.remaining -= len(out)
            return out
        if self.mode == 3:
            if len(self.buf) == 0:
                if not self._fill():
                    self.mode = 0
                    return b""
            return self._take(max_bytes)
        while True:
            if self.chunk_left > 0:
                if len(self.buf) == 0:
                    if not self._fill():
                        self.mode = 0
                        return b""
                n2: int = max_bytes
                if self.chunk_left < n2:
                    n2 = self.chunk_left
                out2: bytes = self._take(n2)
                self.chunk_left -= len(out2)
                if self.chunk_left == 0:
                    self.need_crlf = True
                return out2
            if self.need_crlf:
                while len(self.buf) < 2:
                    if not self._fill():
                        self.mode = 0
                        return b""
                self.buf = self.buf[2:len(self.buf)]
                self.need_crlf = False
            nl: int = self.buf.find(b"\r\n")
            if nl < 0:
                if not self._fill():
                    self.mode = 0
                    return b""
                continue
            sizeline: str = self.buf[0:nl].decode("utf-8")
            self.buf = self.buf[nl + 2:len(self.buf)]
            semi: int = sizeline.find(";")
            if semi >= 0:
                sizeline = sizeline[0:semi]
            size: int = _hex_val(sizeline.strip())
            if size < 0:
                raise ValueError("malformed chunked encoding")
            if size == 0:
                self.mode = 0
                return b""
            self.chunk_left = size
        raise OSError("unreachable")

    def read_all(self: Mut[ResponseStream]) -> bytes:
        out: bytearray = bytearray(b"")
        while True:
            chunk: bytes = self.read(65536)
            if len(chunk) == 0:
                break
            out.extend(chunk)
        return bytes(out)

    def close(self: Mut[ResponseStream]) -> None:
        if not self.closed:
            close(self.conn)
            self.closed = True
        return


def _parse_head(conn: int, url_str: str, method: str, started: float) -> ResponseStream:
    """Read and parse the status line + headers, returning a framed stream."""
    raw: bytes = b""
    sep: int = -1
    while True:
        sep = raw.find(b"\r\n\r\n")
        if sep >= 0:
            break
        if len(raw) > 1048576:
            close(conn)
            raise OSError("malformed HTTP response")
        chunk: bytes = recv(conn, 65536)
        if len(chunk) == 0:
            break
        raw = raw + chunk
    if sep < 0:
        close(conn)
        raise OSError("malformed HTTP response")
    head: bytes = raw[0:sep]
    leftover: bytes = raw[sep + 4:len(raw)]
    lines: list[bytes] = head.split(b"\r\n")
    statusline: str = ""
    bad: bool = False
    try:
        statusline = lines[0].decode("utf-8")
    except ValueError as e:
        bad = True
    parts: list[str] = statusline.split(" ")
    if bad or len(parts) < 2 or not parts[0].startswith("HTTP/") or not _digits_ok(parts[1]):
        close(conn)
        raise OSError("malformed HTTP response")
    version: str = parts[0][5:len(parts[0])]
    status: int = int(parts[1])
    reason: str = ""
    if len(parts) > 2:
        reason = statusline[len(parts[0]) + 1 + len(parts[1]) + 1:len(statusline)]
    rhs: list[str] = []
    i: int = 1
    while i < len(lines):
        hline: str = ""
        bad_line: bool = False
        try:
            hline = lines[i].decode("utf-8")
        except ValueError as e:
            bad_line = True
        if not bad_line:
            c: int = hline.find(":")
            if c > 0:
                rhs.append(hline[0:c].strip().lower() + ": " + hline[c + 1:len(hline)].strip())
        i += 1
    mode: int = 3
    remaining: int = 0
    te: str = header_value(rhs, "transfer-encoding").lower()
    cl: str = header_value(rhs, "content-length")
    if method == "HEAD" or status == 204 or status == 304:
        mode = 0
    elif te.find("chunked") >= 0:
        mode = 2
    elif _digits_ok(cl):
        mode = 1
        remaining = int(cl)
    hist: list[str] = []
    return ResponseStream(conn, status, reason, version, url_str, move(rhs), move(hist),
                          mode, remaining, 0, False, leftover, False, started)


def _perform(method: str, url_str: str, headers: Ref[list[str]], content: bytes,
             timeout_ms: int, verify: bool, started: float, aio: bool) -> ResponseStream:
    """Open one connection (TLS for https), send the request, parse the head."""
    u: SplitResult = urlsplit(url_str)
    if u.scheme != "http" and u.scheme != "https":
        raise ValueError("unsupported URL scheme: " + u.scheme)
    hn: str | None = u.hostname
    host: str = ""
    if hn is not None:
        host = hn
    if host == "":
        raise ValueError("URL has no host")
    default: int = 80
    if u.scheme == "https":
        default = 443
    pt: int | None = u.port
    port: int = default
    explicit: bool = False
    if pt is not None:
        port = pt
        explicit = True
    conn: int = 0
    if u.scheme == "https":
        conn = tls_connect(host, port, timeout_ms, 0 if verify else 1)
    else:
        conn = connect(host, port, timeout_ms)
    set_timeout(conn, timeout_ms)
    if aio:
        set_async(conn)
    host_header: str = host
    if explicit and port != default:
        host_header = host + ":" + str(port)
    path_q: str = u.path
    if path_q == "":
        path_q = "/"
    if u.query != "":
        path_q = path_q + "?" + u.query
    head: str = method + " " + path_q + " HTTP/1.1\r\nhost: " + host_header + "\r\n"
    for h in headers:
        head += h + "\r\n"
    has_body_method: bool = method == "POST" or method == "PUT" or method == "PATCH"
    if len(content) > 0 or has_body_method:
        head += "content-length: " + str(len(content)) + "\r\n"
    head += "connection: close\r\n\r\n"
    x: int = send(conn, head.encode("utf-8"))
    off: int = 0
    while off < len(content):
        end: int = off + 65536
        if end > len(content):
            end = len(content)
        y: int = send(conn, content[off:end])
        off = end
    return _parse_head(conn, url_str, method, started)


def _prepare_headers(user_headers: Ref[list[str]], client_headers: Ref[list[str]],
                     cookies: Ref[list[str]], auth_user: str, auth_pass: str,
                     send_auth: bool, want_stream: bool, drop_ct: bool) -> list[str]:
    """Assemble the final header list for one request attempt."""
    hs: list[str] = []
    for h in user_headers:
        nh: str = _norm_header(h)
        if drop_ct and nh.startswith("content-type:"):
            continue
        hs.append(nh)
    for h2 in client_headers:
        nh2: str = _norm_header(h2)
        c: int = nh2.find(":")
        nm: str = nh2
        if c > 0:
            nm = nh2[0:c]
        if not _has_header(hs, nm):
            hs.append(nh2)
    if not _has_header(hs, "user-agent"):
        hs.append("user-agent: " + USER_AGENT)
    if not _has_header(hs, "accept"):
        hs.append("accept: */*")
    if not _has_header(hs, "accept-encoding"):
        if want_stream:
            hs.append("accept-encoding: identity")
        else:
            hs.append("accept-encoding: gzip")
    if len(cookies) > 0 and not _has_header(hs, "cookie"):
        cline: str = ""
        first: bool = True
        for cv in cookies:
            if first:
                cline = cv
                first = False
            else:
                cline = cline + "; " + cv
        hs.append("cookie: " + cline)
    if send_auth and auth_user != "" and not _has_header(hs, "authorization"):
        hs.append(basic_auth(auth_user, auth_pass))
    return hs


def _merge_url(base_url: str, url: str) -> str:
    """Join a client base_url with a request URL (absolute URLs win)."""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if base_url == "":
        return url
    b: str = base_url
    if b.endswith("/"):
        b = b[0:len(b) - 1]
    if not url.startswith("/"):
        return b + "/" + url
    return b + url


def _host_of(url: str) -> str:
    """The lowercase hostname of a URL, or '' when absent."""
    u: SplitResult = urlsplit(url)
    hn: str | None = u.hostname
    if hn is None:
        return ""
    return hn


def _request_core(method: str, url: str, user_headers: Ref[list[str]], content: bytes,
                  timeout: float, verify: bool, follow: bool, max_redirects: int,
                  auth_user: str, auth_pass: str, client_headers: Ref[list[str]],
                  cookies: Mut[list[str]], base_url: str,
                  want_stream: bool, aio: bool = False) -> ResponseStream:
    """The redirect-following request engine shared by every verb."""
    started: float = monotonic()
    cur_url: str = _merge_url(base_url, url)
    cur_method: str = method.upper()
    body: bytes = content
    timeout_ms: int = int(timeout * 1000.0)
    origin_host: str = _host_of(cur_url)
    history: list[str] = []
    hops: int = 0
    send_auth: bool = True
    dropped: bool = False
    while True:
        hs: list[str] = _prepare_headers(user_headers, client_headers, cookies,
                                         auth_user, auth_pass, send_auth,
                                         want_stream, dropped)
        rs: ResponseStream = _perform(cur_method, cur_url, hs, body, timeout_ms,
                                      verify, started, aio)
        _store_cookies(rs.headers, cookies)
        loc: str = header_value(rs.headers, "location")
        if follow and _redirect_status(rs.status_code) and loc != "":
            if hops >= max_redirects:
                rs.close()
                raise TooManyRedirects("exceeded maximum allowed redirects ("
                                       + str(max_redirects) + ")")
            rs.close()
            history.append(cur_url)
            nxt: str = urljoin(cur_url, loc)
            change_to_get: bool = rs.status_code == 303 or (
                (rs.status_code == 301 or rs.status_code == 302)
                and cur_method != "GET" and cur_method != "HEAD")
            if change_to_get:
                cur_method = "GET"
                body = b""
                dropped = True
            if _host_of(nxt) != origin_host:
                send_auth = False
            cur_url = nxt
            hops += 1
            continue
        rs.url = cur_url
        rs.history = move(history)
        return rs
    raise OSError("unreachable")


def _finish(rs: Owned[ResponseStream]) -> Response:
    """Drain a stream into a Response, decoding gzip/deflate bodies."""
    body: bytes = rs.read_all()
    rs.close()
    enc: str = header_value(rs.headers, "content-encoding").lower()
    if len(body) > 0 and enc.find("gzip") >= 0:
        body = gzip_decompress(body)
    elif len(body) > 0 and enc.find("deflate") >= 0:
        try:
            body = decompress(body)
        except ValueError as e:
            body = inflate(body)
    elapsed: float = monotonic() - rs.started
    return Response(rs.status_code, rs.reason_phrase, rs.http_version, rs.url,
                    move(rs.headers), body, move(rs.history), elapsed)


def parse_response(raw: bytes) -> Response:
    """Parse a complete raw HTTP response (offline helper, no socket)."""
    empty: list[str] = []
    ehist: list[str] = []
    sep: int = raw.find(b"\r\n\r\n")
    if sep < 0:
        return Response(0, "", "", "", move(empty), b"", move(ehist), 0.0)
    head: bytes = raw[0:sep]
    rest: bytes = raw[sep + 4:len(raw)]
    lines: list[bytes] = head.split(b"\r\n")
    statusline: str = ""
    bad: bool = False
    try:
        statusline = lines[0].decode("utf-8")
    except ValueError as e:
        bad = True
    parts: list[str] = statusline.split(" ")
    if bad or len(parts) < 2 or not parts[0].startswith("HTTP/") or not _digits_ok(parts[1]):
        return Response(0, "", "", "", move(empty), b"", move(ehist), 0.0)
    version: str = parts[0][5:len(parts[0])]
    status: int = int(parts[1])
    reason: str = ""
    if len(parts) > 2:
        reason = statusline[len(parts[0]) + 1 + len(parts[1]) + 1:len(statusline)]
    headers: list[str] = []
    i: int = 1
    while i < len(lines):
        hline: str = ""
        bad_line: bool = False
        try:
            hline = lines[i].decode("utf-8")
        except ValueError as e:
            bad_line = True
        if not bad_line:
            c: int = hline.find(":")
            if c > 0:
                headers.append(hline[0:c].strip().lower() + ": "
                               + hline[c + 1:len(hline)].strip())
        i += 1
    body: bytes = rest
    te: str = header_value(headers, "transfer-encoding").lower()
    cl: str = header_value(headers, "content-length")
    if te.find("chunked") >= 0:
        body = decode_chunked(rest)
    elif _digits_ok(cl):
        body = rest[0:int(cl)]
    enc: str = header_value(headers, "content-encoding").lower()
    if len(body) > 0 and enc.find("gzip") >= 0:
        body = gzip_decompress(body)
    elif len(body) > 0 and enc.find("deflate") >= 0:
        try:
            body = decompress(body)
        except ValueError as e:
            body = inflate(body)
    return Response(status, reason, version, "", move(headers), body, move(ehist), 0.0)


@dataclass
class Client:
    base_url: str
    headers: list[str]
    cookies: list[str]
    timeout: float
    follow_redirects: bool
    max_redirects: int
    verify: bool
    auth_user: str
    auth_pass: str

    def set_header(self: Mut[Client], line: str) -> None:
        self.headers.append(_norm_header(line))
        return

    def set_basic_auth(self: Mut[Client], username: str, password: str) -> None:
        self.auth_user = username
        self.auth_pass = password
        return

    def set_cookie(self: Mut[Client], name: str, value: str) -> None:
        _jar_set(self.cookies, name + "=" + value)
        return

    def request(self: Mut[Client], method: str, url: str, headers: Ref[list[str]],
                content: bytes) -> Response:
        ch: list[str] = []
        for h in self.headers:
            ch.append(h)
        rs: ResponseStream = _request_core(method, url, headers, content,
                                           self.timeout, self.verify,
                                           self.follow_redirects, self.max_redirects,
                                           self.auth_user, self.auth_pass, ch,
                                           self.cookies, self.base_url, False)
        return _finish(move(rs))

    def get(self: Mut[Client], url: str) -> Response:
        hs: list[str] = []
        return self.request("GET", url, hs, b"")

    def head(self: Mut[Client], url: str) -> Response:
        hs: list[str] = []
        return self.request("HEAD", url, hs, b"")

    def options(self: Mut[Client], url: str) -> Response:
        hs: list[str] = []
        return self.request("OPTIONS", url, hs, b"")

    def delete(self: Mut[Client], url: str) -> Response:
        hs: list[str] = []
        return self.request("DELETE", url, hs, b"")

    def post(self: Mut[Client], url: str, content: bytes,
             content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return self.request("POST", url, hs, content)

    def put(self: Mut[Client], url: str, content: bytes,
            content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return self.request("PUT", url, hs, content)

    def patch(self: Mut[Client], url: str, content: bytes,
              content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return self.request("PATCH", url, hs, content)

    def post_form(self: Mut[Client], url: str, form: Ref[dict[str, str]]) -> Response:
        hs: list[str] = ["content-type: application/x-www-form-urlencoded"]
        return self.request("POST", url, hs, urlencode(form).encode("utf-8"))

    def post_json(self: Mut[Client], url: str, payload: PyVal) -> Response:
        hs: list[str] = ["content-type: application/json"]
        return self.request("POST", url, hs, dumps(payload).encode("utf-8"))

    def post_multipart(self: Mut[Client], url: str, fields: Ref[dict[str, str]],
                       files: Ref[list[FilePart]], boundary: str = "") -> Response:
        b: str = boundary
        if b == "":
            b = "fang" + u4_str().replace("-", "")
        hs: list[str] = ["content-type: " + multipart_content_type(b)]
        return self.request("POST", url, hs, build_multipart(fields, files, b))

    def stream(self: Mut[Client], method: str, url: str) -> ResponseStream:
        hs: list[str] = []
        ch: list[str] = []
        for h in self.headers:
            ch.append(h)
        return _request_core(method, url, hs, b"", self.timeout, self.verify,
                             self.follow_redirects, self.max_redirects,
                             self.auth_user, self.auth_pass, ch, self.cookies,
                             self.base_url, True)

    def download(self: Mut[Client], url: str, path: str) -> Response:
        rs: ResponseStream = self.stream("GET", url)
        n: int = write_bytes(path, b"")
        while True:
            chunk: bytes = rs.read(65536)
            if len(chunk) == 0:
                break
            n = append_bytes(path, chunk)
        rs.close()
        elapsed: float = monotonic() - rs.started
        return Response(rs.status_code, rs.reason_phrase, rs.http_version, rs.url,
                        move(rs.headers), b"", move(rs.history), elapsed)

    def upload_file(self: Mut[Client], method: str, url: str, path: str,
                    content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return self.request(method, url, hs, read_bytes(path))

    def close(self: Mut[Client]) -> None:
        """No-op: fang opens one connection per request (connection: close)."""
        return


@dataclass
class AsyncClient:
    """httpx.AsyncClient equivalent: the same engine over async-mode sockets, so a
    request suspends the calling task at every would-block instead of blocking the
    loop (D45). `async with AsyncClient() as c: r = await c.get(url)`."""
    base_url: str
    headers: list[str]
    cookies: list[str]
    timeout: float
    follow_redirects: bool
    max_redirects: int
    verify: bool
    auth_user: str
    auth_pass: str

    def __init__(self: Mut[AsyncClient], base_url: str = "", timeout: float = 5.0,
                 follow_redirects: bool = False, max_redirects: int = 20,
                 verify: bool = True, auth_user: str = "", auth_pass: str = "") -> None:
        self.base_url = base_url
        self.headers = []
        self.cookies = []
        self.timeout = timeout
        self.follow_redirects = follow_redirects
        self.max_redirects = max_redirects
        self.verify = verify
        self.auth_user = auth_user
        self.auth_pass = auth_pass

    def set_header(self: Mut[AsyncClient], line: str) -> None:
        self.headers.append(_norm_header(line))
        return

    def set_basic_auth(self: Mut[AsyncClient], username: str, password: str) -> None:
        self.auth_user = username
        self.auth_pass = password
        return

    def set_cookie(self: Mut[AsyncClient], name: str, value: str) -> None:
        _jar_set(self.cookies, name + "=" + value)
        return

    async def request(self: Mut[AsyncClient], method: str, url: str, headers: Ref[list[str]],
                      content: bytes) -> Response:
        ch: list[str] = []
        for h in self.headers:
            ch.append(h)
        rs: ResponseStream = _request_core(method, url, headers, content,
                                           self.timeout, self.verify,
                                           self.follow_redirects, self.max_redirects,
                                           self.auth_user, self.auth_pass, ch,
                                           self.cookies, self.base_url, False, True)
        return _finish(move(rs))

    async def get(self: Mut[AsyncClient], url: str) -> Response:
        hs: list[str] = []
        return await self.request("GET", url, hs, b"")

    async def head(self: Mut[AsyncClient], url: str) -> Response:
        hs: list[str] = []
        return await self.request("HEAD", url, hs, b"")

    async def options(self: Mut[AsyncClient], url: str) -> Response:
        hs: list[str] = []
        return await self.request("OPTIONS", url, hs, b"")

    async def delete(self: Mut[AsyncClient], url: str) -> Response:
        hs: list[str] = []
        return await self.request("DELETE", url, hs, b"")

    async def post(self: Mut[AsyncClient], url: str, content: bytes,
                   content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return await self.request("POST", url, hs, content)

    async def put(self: Mut[AsyncClient], url: str, content: bytes,
                  content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return await self.request("PUT", url, hs, content)

    async def patch(self: Mut[AsyncClient], url: str, content: bytes,
                    content_type: str = "application/octet-stream") -> Response:
        hs: list[str] = ["content-type: " + content_type]
        return await self.request("PATCH", url, hs, content)

    async def post_form(self: Mut[AsyncClient], url: str, form: Ref[dict[str, str]]) -> Response:
        hs: list[str] = ["content-type: application/x-www-form-urlencoded"]
        return await self.request("POST", url, hs, urlencode(form).encode("utf-8"))

    async def post_json(self: Mut[AsyncClient], url: str, payload: PyVal) -> Response:
        hs: list[str] = ["content-type: application/json"]
        return await self.request("POST", url, hs, dumps(payload).encode("utf-8"))

    async def stream(self: Mut[AsyncClient], method: str, url: str) -> ResponseStream:
        """Open a streaming response; `read()` on it suspends cooperatively."""
        hs: list[str] = []
        ch: list[str] = []
        for h in self.headers:
            ch.append(h)
        return _request_core(method, url, hs, b"", self.timeout, self.verify,
                             self.follow_redirects, self.max_redirects,
                             self.auth_user, self.auth_pass, ch, self.cookies,
                             self.base_url, True, True)

    async def aclose(self: Mut[AsyncClient]) -> None:
        """No-op: one connection per request (connection: close)."""
        return

    async def __aenter__(self: Ref[AsyncClient]) -> AsyncClient:
        return self

    async def __aexit__(self: Ref[AsyncClient], exc_type: None, exc: None, tb: None) -> None:
        return


def client(base_url: str = "", timeout: float = 5.0, follow_redirects: bool = False,
           max_redirects: int = 20, verify: bool = True, auth_user: str = "",
           auth_pass: str = "") -> Client:
    """Create a Client with httpx-equivalent defaults."""
    hs: list[str] = []
    cs: list[str] = []
    return Client(base_url, move(hs), move(cs), timeout, follow_redirects,
                  max_redirects, verify, auth_user, auth_pass)


def request(method: str, url: str, timeout: float = 5.0, follow_redirects: bool = False,
            verify: bool = True, auth_user: str = "", auth_pass: str = "") -> Response:
    """Send a bodyless request with an ad-hoc client (httpx.request)."""
    c: Client = client("", timeout, follow_redirects, 20, verify, auth_user, auth_pass)
    hs: list[str] = []
    return c.request(method, url, hs, b"")


def get(url: str, timeout: float = 5.0, follow_redirects: bool = False,
        verify: bool = True, auth_user: str = "", auth_pass: str = "") -> Response:
    """httpx.get equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, auth_user, auth_pass)
    return c.get(url)


def head(url: str, timeout: float = 5.0, follow_redirects: bool = False,
         verify: bool = True) -> Response:
    """httpx.head equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.head(url)


def options(url: str, timeout: float = 5.0, follow_redirects: bool = False,
            verify: bool = True) -> Response:
    """httpx.options equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.options(url)


def delete(url: str, timeout: float = 5.0, follow_redirects: bool = False,
           verify: bool = True) -> Response:
    """httpx.delete equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.delete(url)


def post(url: str, content: bytes, content_type: str = "application/octet-stream",
         timeout: float = 5.0, follow_redirects: bool = False,
         verify: bool = True) -> Response:
    """httpx.post equivalent (content is the raw request body)."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.post(url, content, content_type=content_type)


def put(url: str, content: bytes, content_type: str = "application/octet-stream",
        timeout: float = 5.0, follow_redirects: bool = False,
        verify: bool = True) -> Response:
    """httpx.put equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.put(url, content, content_type=content_type)


def patch(url: str, content: bytes, content_type: str = "application/octet-stream",
          timeout: float = 5.0, follow_redirects: bool = False,
          verify: bool = True) -> Response:
    """httpx.patch equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.patch(url, content, content_type=content_type)


def post_form(url: str, form: Ref[dict[str, str]], timeout: float = 5.0,
              follow_redirects: bool = False, verify: bool = True) -> Response:
    """httpx.post(data=...) equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.post_form(url, form)


def post_json(url: str, payload: PyVal, timeout: float = 5.0,
              follow_redirects: bool = False, verify: bool = True) -> Response:
    """httpx.post(json=...) equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.post_json(url, payload)


def post_multipart(url: str, fields: Ref[dict[str, str]], files: Ref[list[FilePart]],
                   boundary: str = "", timeout: float = 5.0,
                   follow_redirects: bool = False, verify: bool = True) -> Response:
    """httpx.post(files=...) equivalent."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.post_multipart(url, fields, files, boundary=boundary)


def stream(method: str, url: str, timeout: float = 5.0, follow_redirects: bool = False,
           verify: bool = True) -> ResponseStream:
    """httpx.stream equivalent: read() chunks, then close()."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.stream(method, url)


def download(url: str, path: str, timeout: float = 5.0, follow_redirects: bool = True,
             verify: bool = True) -> Response:
    """Stream a GET body straight to a file on disk."""
    c: Client = client("", timeout, follow_redirects, 20, verify, "", "")
    return c.download(url, path)


def upload_file(method: str, url: str, path: str,
                content_type: str = "application/octet-stream", timeout: float = 5.0,
                verify: bool = True) -> Response:
    """Send a file from disk as the request body (wire-chunked)."""
    c: Client = client("", timeout, False, 20, verify, "", "")
    return c.upload_file(method, url, path, content_type=content_type)
