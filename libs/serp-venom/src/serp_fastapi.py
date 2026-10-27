"""serp-venom (Venom) — FastAPI drop-in for Serpentine.

FastAPI's everyday surface with FastAPI's spellings: a module-level `app = FastAPI()`,
`@app.get("/items/{item_id}")` decorators with parameter injection by name and type
(path/query scalars, `T | None` optionals, serp_molt models as JSON bodies), returned
dicts/lists/scalars/models serialized as JSON, `status_code=` on the decorator,
`HTTPException(status_code=404, detail=...)`, FastAPI's 422 validation envelope,
`JSONResponse`/`PlainTextResponse`/`HTMLResponse`/`RedirectResponse`, and
`TestClient(app)` with get/post/put/delete/patch and .status_code/.text/.json()/.headers.
Decorators and the module-level app lower at build time (docs/DECISIONS.md D41) and run
as ordinary Python under CPython (the `registrar` shim builds the same endpoint).

Divergences: response helpers are factory functions returning `Response` (annotate
handlers `-> Response`); `HTTPException` carries its status/detail in the message only;
`request.json()` is synchronous; no `Depends`, middleware, `APIRouter` or streaming.
"""
from __future__ import annotations

from serpentine import Callable, Mut, Owned, PyVal, Ref, block_on, dataclass, move, registrar
from serp_http_server import (BaseHTTPRequestHandler, HTTPServer, MAX_BODY, REQUEST_DEADLINE,
                              _Headers, _digits_ok, _parse_clen, _read_head, _read_body)
from _serp_socket import accept as _accept
from _serp_socket import accept_nb as _accept_nb
from _serp_socket import close as _close
from _serp_socket import listen as _listen
from _serp_socket import local_port as _local_port
from _serp_socket import poll_ready as _poll_ready
from _serp_socket import recv as _recv
from _serp_socket import send_all as _send_all
from _serp_socket import set_async as _set_async
from _serp_socket import set_nonblocking as _set_nonblocking
from _serp_socket import set_timeout as _set_timeout
from _serp_socket import shutdown_install as _shutdown_install
from _serp_socket import shutdown_requested as _shutdown_requested
from _serp_socket import shutdown_request as _shutdown_request
from serp_time import monotonic as _monotonic
from serp_json import dumps, loads
from serp_url import unquote, unquote_plus


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(status_code) + ": " + detail)


def _serp_exattr_HTTPException_status_code(msg: str) -> int:
    """`exc.status_code` — the status encoded at the front of the message (D42 getter)."""
    c: int = msg.find(":")
    if c > 0 and _digits(msg[0:c]):
        return int(msg[0:c])
    return 500


def _serp_exattr_HTTPException_detail(msg: str) -> str:
    """`exc.detail` — the text after the status code (D42 getter)."""
    c: int = msg.find(":")
    if c > 0 and _digits(msg[0:c]):
        return msg[c + 1:len(msg)].strip()
    return msg


class RequestValidationError(Exception):
    def __init__(self, errors: str) -> None:
        self.errors = errors
        super().__init__(errors)


def _serp_exattr_RequestValidationError_errors(msg: str) -> str:
    """`exc.errors` — the JSON-encoded pydantic-style error list (D42 getter)."""
    return msg


def _err_json(kind: str, loc: str, name: str, msg: str, value: PyVal) -> str:
    """One pydantic-shaped request error, serialized (the RequestValidationError message)."""
    e: dict[str, PyVal] = {"type": kind, "loc": [loc, name], "msg": msg, "input": value}
    errs: list[PyVal] = [e]
    return dumps(errs, False, False, True)


def _missing(loc: str, name: str) -> str:
    return _err_json("missing", loc, name, "Field required", None)


def _to_int(s: str, loc: str, name: str) -> int:
    ok: bool = True
    t: str = s
    if t.startswith("-") or t.startswith("+"):
        t = t[1:len(t)]
    if not _digits(t):
        ok = False
    if not ok:
        raise RequestValidationError(_err_json(
            "int_parsing", loc, name,
            "Input should be a valid integer, unable to parse string as an integer", s))
    return int(s)


def _to_float(s: str, loc: str, name: str) -> float:
    try:
        return float(s)
    except ValueError as e:
        raise RequestValidationError(_err_json(
            "float_parsing", loc, name,
            "Input should be a valid number, unable to parse string as a number", s))


def _to_bool(s: str, loc: str, name: str) -> bool:
    low: str = s.lower()
    if low == "1" or low == "true" or low == "t" or low == "yes" or low == "y" or low == "on":
        return True
    if low == "0" or low == "false" or low == "f" or low == "no" or low == "n" or low == "off":
        return False
    raise RequestValidationError(_err_json(
        "bool_parsing", loc, name, "Input should be a valid boolean, unable to interpret input",
        s))


@dataclass
class Request:
    method: str
    url: str
    path_params: dict[str, str]
    query_params: dict[str, str]
    headers: dict[str, str]
    body: str
    _status: int = 200
    _chain: list[Callable[[Request, Callable[[Request], Response]], Response]] = []
    _handlers: list[Callable[[Request], Response]] = []
    _async: bool = False

    def json(self: Ref[Request]) -> PyVal:
        return loads(self.body)

    def _serp_body(self: Ref[Request]) -> str:
        return self.body

    def _serp_path_str(self: Ref[Request], name: str) -> str:
        return self.path_params[name]

    def _serp_path_int(self: Ref[Request], name: str) -> int:
        return _to_int(self.path_params[name], "path", name)

    def _serp_path_float(self: Ref[Request], name: str) -> float:
        return _to_float(self.path_params[name], "path", name)

    def _serp_path_bool(self: Ref[Request], name: str) -> bool:
        return _to_bool(self.path_params[name], "path", name)

    def _serp_query_str(self: Ref[Request], name: str, default: str, has_default: bool) -> str:
        v: str | None = self.query_params.get(name)
        if v is None:
            if not has_default:
                raise RequestValidationError(_missing("query", name))
            return default
        return v

    def _serp_query_int(self: Ref[Request], name: str, default: int, has_default: bool) -> int:
        v: str | None = self.query_params.get(name)
        if v is None:
            if not has_default:
                raise RequestValidationError(_missing("query", name))
            return default
        return _to_int(v, "query", name)

    def _serp_query_float(self: Ref[Request], name: str, default: float,
                          has_default: bool) -> float:
        v: str | None = self.query_params.get(name)
        if v is None:
            if not has_default:
                raise RequestValidationError(_missing("query", name))
            return default
        return _to_float(v, "query", name)

    def _serp_query_bool(self: Ref[Request], name: str, default: bool,
                         has_default: bool) -> bool:
        v: str | None = self.query_params.get(name)
        if v is None:
            if not has_default:
                raise RequestValidationError(_missing("query", name))
            return default
        return _to_bool(v, "query", name)

    def _serp_query_opt_str(self: Ref[Request], name: str) -> str | None:
        return self.query_params.get(name)

    def _serp_query_opt_int(self: Ref[Request], name: str) -> int | None:
        v: str | None = self.query_params.get(name)
        if v is None:
            return None
        return _to_int(v, "query", name)

    def _serp_query_opt_float(self: Ref[Request], name: str) -> float | None:
        v: str | None = self.query_params.get(name)
        if v is None:
            return None
        return _to_float(v, "query", name)

    def _serp_query_opt_bool(self: Ref[Request], name: str) -> bool | None:
        v: str | None = self.query_params.get(name)
        if v is None:
            return None
        return _to_bool(v, "query", name)

    def _serp_validation_error(self: Ref[Request], errs: Owned[list[PyVal]]) -> Response:
        """FastAPI's 422 envelope for a failed body model, loc prefixed with 'body'."""
        out: list[PyVal] = []
        for e in errs:
            loc: list[PyVal] = ["body"]
            for part in e["loc"]:
                loc.append(part)
            item: dict[str, PyVal] = {"type": e["type"], "loc": loc, "msg": e["msg"]}
            if "input" in e:
                item["input"] = e["input"]
            out.append(item)
        return JSONResponse({"detail": out}, 422)

    def _serp_respond_json(self: Ref[Request], value: PyVal) -> Response:
        """Serialize a handler's return value with the route's declared status code."""
        if self._status == 204:
            return Response("", 204, {}, "application/json")
        return JSONResponse(value, self._status)


@dataclass
class Response:
    content: str = ""
    status_code: int = 200
    headers: dict[str, str] = {}
    media_type: str = "text/plain"
    background: list[Callable[[], None]] = []
    chunks: list[str] = []
    streaming: bool = False
    producers: list[Callable[[int], str | None]] = []


def StreamingResponse(content: Owned[list[str]], status_code: int = 200,
                      headers: Owned[dict[str, str]] = {},
                      media_type: str = "text/plain; charset=utf-8") -> Response:
    """Chunked response: each element goes out as its own HTTP/1.1 chunk (Transfer-Encoding:
    chunked). For chunks computed while sending, use LazyStreamingResponse."""
    return Response("", status_code, _fresh(headers), media_type, [], move(content), True)


def LazyStreamingResponse(producer: Callable[[int], str | None], status_code: int = 200,
                          headers: Owned[dict[str, str]] = {},
                          media_type: str = "text/plain; charset=utf-8") -> Response:
    """Chunked response produced lazily: `producer(i)` is called while the response is being
    written, for i = 0, 1, 2, ..., until it returns None (the generator-free form of
    FastAPI's StreamingResponse over a generator)."""
    ps: list[Callable[[int], str | None]] = []
    ps.append(producer)
    return Response("", status_code, _fresh(headers), media_type, [], [], True, move(ps))


def _collect_stream(resp: Ref[Response]) -> str:
    """The whole streamed body (TestClient): list chunks, then producer output."""
    out: list[str] = []
    for c in resp.chunks:
        out.append(c)
    for p in resp.producers:
        i: int = 0
        going: bool = True
        while going:
            part: str | None = p(i)
            if part is None:
                going = False
            else:
                out.append(part)
                i += 1
    return "".join(out)


def _chunk(text: str) -> bytes:
    """One HTTP/1.1 chunk frame."""
    data: bytes = text.encode("utf-8")
    return (_hex(len(data)) + "\r\n").encode("utf-8") + data + b"\r\n"


def _hex(n: int) -> str:
    """Lowercase hex digits of a non-negative int."""
    if n == 0:
        return "0"
    digits: str = "0123456789abcdef"
    out: str = ""
    v: int = n
    while v > 0:
        out = digits[v % 16] + out
        v = v // 16
    return out


def _send_stream(conn: int, resp: Ref[Response]) -> None:
    """Send every chunk with its own write (calling producers as it goes), then the
    terminating zero chunk."""
    for c in resp.chunks:
        if c != "":
            n: int = _send_all(conn, _chunk(c), 0)
    for p in resp.producers:
        i: int = 0
        going: bool = True
        while going:
            part: str | None = p(i)
            if part is None:
                going = False
            else:
                if part != "":
                    n1: int = _send_all(conn, _chunk(part), 0)
                i += 1
    n2: int = _send_all(conn, b"0\r\n\r\n", 0)


@dataclass
class BackgroundTasks:
    """Work to run after the response is sent (FastAPI's `BackgroundTasks` parameter).

    `add_task` takes a zero-argument callable — `background_tasks.add_task(lambda: f(x))` —
    because the subset has no `*args`; tasks run in order once the response is written."""
    tasks: list[Callable[[], None]] = []

    def add_task(self: Mut[BackgroundTasks], func: Callable[[], None]) -> None:
        self.tasks.append(func)


def _run_background(resp: Ref[Response]) -> None:
    """Run a response's background tasks; a failing task never affects the client."""
    for t in resp.background:
        try:
            t()
        except Exception as e:
            pass


def _fresh(headers: Ref[dict[str, str]]) -> dict[str, str]:
    """An independent copy of a headers mapping (CPython shares mutable default arguments)."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        out[k] = v
    return out


def JSONResponse(content: PyVal, status_code: int = 200, headers: Owned[dict[str, str]] = {},
                 media_type: str = "application/json") -> Response:
    """Factory mirroring fastapi.responses.JSONResponse."""
    return Response(dumps(content, False, False, True), status_code, _fresh(headers), media_type)


def PlainTextResponse(content: str, status_code: int = 200, headers: Owned[dict[str, str]] = {},
                      media_type: str = "text/plain; charset=utf-8") -> Response:
    """Factory mirroring fastapi.responses.PlainTextResponse."""
    return Response(content, status_code, _fresh(headers), media_type)


def HTMLResponse(content: str, status_code: int = 200, headers: Owned[dict[str, str]] = {},
                 media_type: str = "text/html; charset=utf-8") -> Response:
    """Factory mirroring fastapi.responses.HTMLResponse."""
    return Response(content, status_code, _fresh(headers), media_type)


def RedirectResponse(url: str, status_code: int = 307, headers: Owned[dict[str, str]] = {}) -> Response:
    """Factory mirroring fastapi.responses.RedirectResponse."""
    hs: dict[str, str] = _fresh(headers)
    hs["location"] = url
    return Response("", status_code, move(hs), "text/plain; charset=utf-8")


@dataclass
class Route:
    path: str
    methods: list[str]
    handler: Callable[[Request], Response]
    segs: list[str] = []
    nparam: int = 0
    status_code: int = 200
    is_async: bool = False


def _segs_match(ps: Ref[list[str]], xs: Ref[list[str]]) -> bool:
    """Match a route's pre-split pattern against the pre-split request path."""
    if len(ps) != len(xs):
        return False
    i: int = 0
    while i < len(ps):
        p: str = ps[i]
        if not _is_param(p):
            if p != xs[i]:
                return False
        i += 1
    return True


def _params_from(ps: Ref[list[str]], xs: Ref[list[str]]) -> dict[str, str]:
    """Pull `{name}` segments out of an already-split path."""
    out: dict[str, str] = {}
    i: int = 0
    while i < len(ps):
        p: str = ps[i]
        if _is_param(p):
            out[p[1:len(p) - 1]] = unquote(xs[i])
        i += 1
    return out


def _split_path(p: str) -> list[str]:
    parts: list[str] = p.split("/")
    out: list[str] = []
    for s in parts:
        if s != "":
            out.append(s)
    return out


def _is_param(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def _pattern_matches(pattern: str, path: str) -> bool:
    ps: list[str] = _split_path(pattern)
    xs: list[str] = _split_path(path)
    if len(ps) != len(xs):
        return False
    i: int = 0
    while i < len(ps):
        pseg: str = ps[i]
        if not _is_param(pseg):
            if pseg != xs[i]:
                return False
        i += 1
    return True


def _extract_params(pattern: str, path: str) -> dict[str, str]:
    ps: list[str] = _split_path(pattern)
    xs: list[str] = _split_path(path)
    out: dict[str, str] = {}
    i: int = 0
    while i < len(ps):
        pseg: str = ps[i]
        if _is_param(pseg):
            out[pseg[1:len(pseg) - 1]] = unquote(xs[i])
        i += 1
    return out


def _parse_query(qs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if qs == "":
        return out
    pairs: list[str] = qs.split("&")
    for pair in pairs:
        if pair == "":
            continue
        eq: int = pair.find("=")
        if eq < 0:
            out[unquote_plus(pair)] = ""
        else:
            out[unquote_plus(pair[0:eq])] = unquote_plus(pair[eq + 1:len(pair)])
    return out


def _digits(s: str) -> bool:
    if s == "":
        return False
    for ch in s:
        if ch < "0" or ch > "9":
            return False
    return True


def _http_exc_response(msg: str) -> Response:
    """Turn an HTTPException message ('404: detail') into FastAPI's error shape."""
    c: int = msg.find(":")
    code: int = 500
    detail: str = msg
    if c > 0 and _digits(msg[0:c]):
        code = int(msg[0:c])
        detail = msg[c + 1:len(msg)].strip()
    if detail == "":
        line: str = _status_line(code)
        detail = line[4:len(line)]
    return JSONResponse({"detail": detail}, code)


def _fallback(req: Owned[Request]) -> Response:
    return Response("", 500, {}, "text/plain")


def _not_found(req: Owned[Request]) -> Response:
    """Router 404 as a handler, so middleware wraps it too (Starlette semantics)."""
    return JSONResponse({"detail": "Not Found"}, 404)


def _method_not_allowed(req: Owned[Request]) -> Response:
    """Router 405 as a handler, so middleware wraps it too."""
    return JSONResponse({"detail": "Method Not Allowed"}, 405)


def _call_next(request: Owned[Request]) -> Response:
    """FastAPI's `call_next`: run the next middleware (outermost = most recently added), or
    the route handler at the end with its exceptions turned into responses."""
    req: Request = move(request)
    if len(req._chain) > 0:
        mw: Callable[[Request, Callable[[Request], Response]], Response] = req._chain.pop()
        return mw(move(req), _call_next)
    h: Callable[[Request], Response] = req._handlers.pop()
    try:
        if req._async:
            return block_on(h(move(req)))
        return h(move(req))
    except HTTPException as e:
        return _http_exc_response(str(e))
    except RequestValidationError as e2:
        return JSONResponse({"detail": loads(str(e2))}, 422)
    except Exception as e3:
        return PlainTextResponse("Internal Server Error", 500)


CORSMiddleware: str = "CORSMiddleware"
_CORS_SAFE: str = "Accept, Accept-Language, Content-Language, Content-Type"
_CORS_ALL_METHODS: str = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"


def _has(xs: Ref[list[str]], x: str) -> bool:
    """Case-sensitive list membership."""
    for v in xs:
        if v == x:
            return True
    return False


def _has_ci(xs: Ref[list[str]], x: str) -> bool:
    """Case-insensitive list membership."""
    low: str = x.lower()
    for v in xs:
        if v.lower() == low:
            return True
    return False


@dataclass
class _Match:
    found: bool
    matched_other: bool
    pattern: str
    nparam: int
    status: int
    handler: Callable[[Request], Response]
    is_async: bool


@dataclass
class Depends:
    """`param: T = Depends(fn)` — the compiler (D41) and the shim inject fn's result; the
    stored callable is only read under CPython."""
    dependency: str = ""


@dataclass
class APIRouter:
    prefix: str = ""
    routes: list[Route] = []

    def add_api_route(self: Mut[APIRouter], path: str,
                      endpoint: Callable[[Request], Response],
                      methods: Owned[list[str]], status_code: int = 200,
                      is_async: bool = False) -> None:
        full: str = self.prefix + path
        segs: list[str] = _split_path(full)
        np: int = 0
        for s in segs:
            if _is_param(s):
                np += 1
        self.routes.append(Route(full, move(methods), endpoint, move(segs), np, status_code,
                                 is_async))

    @registrar
    def get(self: Mut[APIRouter], path: str, endpoint: Callable[[Request], Response],
            status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["GET"], status_code, is_async)

    @registrar
    def post(self: Mut[APIRouter], path: str, endpoint: Callable[[Request], Response],
             status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["POST"], status_code, is_async)

    @registrar
    def put(self: Mut[APIRouter], path: str, endpoint: Callable[[Request], Response],
            status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["PUT"], status_code, is_async)

    @registrar
    def delete(self: Mut[APIRouter], path: str, endpoint: Callable[[Request], Response],
               status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["DELETE"], status_code, is_async)

    @registrar
    def patch(self: Mut[APIRouter], path: str, endpoint: Callable[[Request], Response],
              status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["PATCH"], status_code, is_async)


@dataclass
class FastAPI:
    title: str = "FastAPI"
    version: str = "0.1.0"
    routes: list[Route] = []
    middlewares: list[Callable[[Request, Callable[[Request], Response]], Response]] = []
    cors_on: bool = False
    cors_origins: list[str] = []
    cors_methods: list[str] = []
    cors_headers: list[str] = []
    cors_expose: list[str] = []
    cors_credentials: bool = False
    cors_max_age: int = 600

    @registrar
    def middleware(self: Mut[FastAPI], middleware_type: str,
                   endpoint: Callable[[Request, Callable[[Request], Response]], Response]) -> None:
        """`@app.middleware("http")`: wrap every request; the latest-added runs outermost."""
        if middleware_type != "http":
            raise ValueError(f"unsupported middleware type {middleware_type!r}")
        self.middlewares.append(endpoint)

    def add_middleware(self: Mut[FastAPI], middleware_class: str,
                       allow_origins: Owned[list[str]] = [], allow_methods: Owned[list[str]] = [],
                       allow_headers: Owned[list[str]] = [], allow_credentials: bool = False,
                       expose_headers: Owned[list[str]] = [], max_age: int = 600) -> None:
        """`app.add_middleware(CORSMiddleware, allow_origins=[...], ...)` (Starlette semantics)."""
        if middleware_class != CORSMiddleware:
            raise ValueError(f"unsupported middleware {middleware_class!r}")
        self.cors_on = True
        self.cors_origins = move(allow_origins)
        self.cors_methods = move(allow_methods)
        if len(self.cors_methods) == 0:
            self.cors_methods.append("GET")
        self.cors_headers = move(allow_headers)
        self.cors_expose = move(expose_headers)
        self.cors_credentials = allow_credentials
        self.cors_max_age = max_age

    def _cors_origin_ok(self: Ref[FastAPI], origin: str) -> bool:
        return _has(self.cors_origins, "*") or _has(self.cors_origins, origin)

    def _cors_preflight(self: Ref[FastAPI], origin: str, req_method: str,
                        req_headers: str) -> Response:
        """Answer an OPTIONS preflight the way Starlette's CORSMiddleware does."""
        failures: list[str] = []
        if not self._cors_origin_ok(origin):
            failures.append("origin")
        if not (_has(self.cors_methods, "*") or _has(self.cors_methods, req_method)):
            failures.append("method")
        allowed_headers: str = _CORS_SAFE
        if _has(self.cors_headers, "*"):
            allowed_headers = req_headers
        else:
            if len(self.cors_headers) > 0:
                allowed_headers = _CORS_SAFE + ", " + ", ".join(self.cors_headers)
            if req_headers.strip() != "":
                for h in req_headers.split(","):
                    name: str = h.strip()
                    if name != "" and not _has_ci(self.cors_headers, name) \
                            and _CORS_SAFE.lower().find(name.lower()) < 0:
                        if not _has(failures, "headers"):
                            failures.append("headers")
        hs: dict[str, str] = {}
        if _has(self.cors_origins, "*") and not self.cors_credentials:
            hs["access-control-allow-origin"] = "*"
        else:
            hs["access-control-allow-origin"] = origin
            hs["vary"] = "Origin"
        hs["access-control-allow-methods"] = _CORS_ALL_METHODS if _has(self.cors_methods, "*") \
            else ", ".join(self.cors_methods)
        hs["access-control-max-age"] = str(self.cors_max_age)
        if allowed_headers != "":
            hs["access-control-allow-headers"] = allowed_headers
        if self.cors_credentials:
            hs["access-control-allow-credentials"] = "true"
        if len(failures) > 0:
            return Response("Disallowed CORS " + ", ".join(failures), 400, move(hs),
                            "text/plain; charset=utf-8")
        return Response("OK", 200, move(hs), "text/plain; charset=utf-8")

    def _cors_decorate(self: Ref[FastAPI], resp: Mut[Response], origin: str) -> None:
        """Add CORS headers to a normal response for an allowed origin."""
        if not self._cors_origin_ok(origin):
            return
        if _has(self.cors_origins, "*") and not self.cors_credentials:
            resp.headers["access-control-allow-origin"] = "*"
        else:
            resp.headers["access-control-allow-origin"] = origin
            resp.headers["vary"] = "Origin"
        if self.cors_credentials:
            resp.headers["access-control-allow-credentials"] = "true"
        if len(self.cors_expose) > 0:
            resp.headers["access-control-expose-headers"] = ", ".join(self.cors_expose)

    def add_api_route(self: Mut[FastAPI], path: str,
                      endpoint: Callable[[Request], Response],
                      methods: Owned[list[str]], status_code: int = 200,
                      is_async: bool = False) -> None:
        segs: list[str] = _split_path(path)
        np: int = 0
        for s in segs:
            if _is_param(s):
                np += 1
        self.routes.append(Route(path, move(methods), endpoint, move(segs), np, status_code,
                                 is_async))

    def include_router(self: Mut[FastAPI], router: Owned[APIRouter], prefix: str = "") -> None:
        """Mount every route of `router` (its own prefix already applied) under `prefix`."""
        for r in router.routes:
            ms: list[str] = [m for m in r.methods]
            self.add_api_route(prefix + r.path, r.handler, move(ms), r.status_code, r.is_async)

    @registrar
    def get(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
            status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["GET"], status_code, is_async)

    @registrar
    def post(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
             status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["POST"], status_code, is_async)

    @registrar
    def put(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
            status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["PUT"], status_code, is_async)

    @registrar
    def delete(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
               status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["DELETE"], status_code, is_async)

    @registrar
    def patch(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
              status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["PATCH"], status_code, is_async)

    @registrar
    def head(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
             status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["HEAD"], status_code, is_async)

    @registrar
    def options(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
                status_code: int = 200, is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, ["OPTIONS"], status_code, is_async)

    @registrar
    def api_route(self: Mut[FastAPI], path: str, endpoint: Callable[[Request], Response],
                  methods: Owned[list[str]], status_code: int = 200,
                  is_async: bool = False) -> None:
        self.add_api_route(path, endpoint, move(methods), status_code, is_async)

    def _match(self: Ref[FastAPI], method: str, path: str) -> _Match:
        """Order-based route lookup for one request (405 when only the method differs)."""
        m: _Match = _Match(False, False, "", 0, 200, _fallback, False)
        xs: list[str] = _split_path(path)
        for r in self.routes:
            if m.found:
                continue
            if not _segs_match(r.segs, xs):
                continue
            allowed: bool = False
            for mm in r.methods:
                if mm == method:
                    allowed = True
            if not allowed:
                m.matched_other = True
                continue
            m.found = True
            m.pattern = r.path
            m.nparam = r.nparam
            m.status = r.status_code
            m.handler = r.handler
            m.is_async = r.is_async
        return m

    def _handle(self: Ref[FastAPI], method: str, target: str,
                headers: Owned[dict[str, str]], body: str) -> Response:
        """Dispatch one request: CORS preflight/decoration around the middleware chain."""
        origin: str = ""
        if self.cors_on:
            o: str | None = headers.get("origin")
            if o is not None:
                origin = o
            rm: str | None = headers.get("access-control-request-method")
            if origin != "" and method == "OPTIONS":
                if rm is not None:
                    rh: str | None = headers.get("access-control-request-headers")
                    hdrs: str = ""
                    if rh is not None:
                        hdrs = rh
                    return self._cors_preflight(origin, rm, hdrs)
        resp: Response = self._dispatch(method, target, move(headers), body)
        if origin != "":
            self._cors_decorate(resp, origin)
        return resp

    def _dispatch(self: Ref[FastAPI], method: str, target: str,
                  headers: Owned[dict[str, str]], body: str) -> Response:
        q: int = target.find("?")
        path: str = target
        query: str = ""
        if q >= 0:
            path = target[0:q]
            query = target[q + 1:len(target)]
        m: _Match = self._match(method, path)
        if not m.found:
            if len(self.middlewares) > 0:
                miss: Request = Request(method, path, {}, _parse_query(query), move(headers),
                                        body, 404)
                if m.matched_other:
                    miss._handlers.append(_method_not_allowed)
                else:
                    miss._handlers.append(_not_found)
                for mw0 in self.middlewares:
                    miss._chain.append(mw0)
                try:
                    return _call_next(move(miss))
                except Exception as e0:
                    return PlainTextResponse("Internal Server Error", 500)
            if m.matched_other:
                return JSONResponse({"detail": "Method Not Allowed"}, 405)
            return JSONResponse({"detail": "Not Found"}, 404)
        params: Owned[dict[str, str]] = {}
        if m.nparam > 0:
            params = _params_from(_split_path(m.pattern), _split_path(path))
        handler: Callable[[Request], Response] = m.handler
        try:
            req: Request = Request(method, path, move(params), _parse_query(query),
                                   move(headers), body, m.status)
            if len(self.middlewares) > 0:
                req._handlers.append(handler)
                req._async = m.is_async
                for mw in self.middlewares:
                    req._chain.append(mw)
                return _call_next(move(req))
            if m.is_async:
                return block_on(handler(move(req)))
            return handler(move(req))
        except HTTPException as e:
            return _http_exc_response(str(e))
        except RequestValidationError as e:
            return JSONResponse({"detail": loads(str(e))}, 422)
        except Exception as e:
            return PlainTextResponse("Internal Server Error", 500)

    async def _handle_async(self: Ref[FastAPI], method: str, target: str,
                            headers: Owned[dict[str, str]], body: str) -> Response:
        """Task-context dispatch: `async def` handlers are awaited, so their awaits
        suspend only this connection's task (D45). With CORS or middleware configured the
        request goes through the synchronous chain instead (handlers then run to completion)."""
        if self.cors_on or len(self.middlewares) > 0:
            return self._handle(method, target, move(headers), body)
        q: int = target.find("?")
        path: str = target
        query: str = ""
        if q >= 0:
            path = target[0:q]
            query = target[q + 1:len(target)]
        m: _Match = self._match(method, path)
        if not m.found:
            if m.matched_other:
                return JSONResponse({"detail": "Method Not Allowed"}, 405)
            return JSONResponse({"detail": "Not Found"}, 404)
        params: Owned[dict[str, str]] = {}
        if m.nparam > 0:
            params = _params_from(_split_path(m.pattern), _split_path(path))
        handler: Callable[[Request], Response] = m.handler
        try:
            req: Request = Request(method, path, move(params), _parse_query(query),
                                   move(headers), body, m.status)
            if m.is_async:
                return await handler(move(req))
            return handler(move(req))
        except HTTPException as e:
            return _http_exc_response(str(e))
        except RequestValidationError as e:
            return JSONResponse({"detail": loads(str(e))}, 422)
        except Exception as e:
            return PlainTextResponse("Internal Server Error", 500)


@dataclass
class ClientResponse:
    status_code: int
    text: str
    headers: dict[str, str]

    def json(self: Ref[ClientResponse]) -> PyVal:
        return loads(self.text)


def _with_query(url: str, params: Ref[dict[str, str]]) -> str:
    """Append `params` to a URL as a query string (after any existing one)."""
    if len(params) == 0:
        return url
    out: str = url
    sep: str = "&" if url.find("?") >= 0 else "?"
    for k, v in params.items():
        out += sep + k + "=" + v
        sep = "&"
    return out


@dataclass
class TestClient:
    app: FastAPI

    def request(self: Ref[TestClient], method: str, url: str, content: str = "",
                params: Owned[dict[str, str]] = {}, headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        hs: dict[str, str] = {"host": "testserver"}
        for k, v in headers.items():
            hs[k.lower()] = v
        if content != "":
            if "content-type" not in hs:
                hs["content-type"] = "application/json"
            hs["content-length"] = str(len(content.encode("utf-8")))
        resp: Response = self.app._handle(method, _with_query(url, params), move(hs), content)
        _run_background(resp)
        if resp.streaming:
            resp.content = _collect_stream(resp)
        out: dict[str, str] = {"content-type": resp.media_type,
                               "content-length": str(len(resp.content.encode("utf-8")))}
        for k2, v2 in resp.headers.items():
            out[k2] = v2
        return ClientResponse(resp.status_code, resp.content, move(out))

    def get(self: Ref[TestClient], url: str, params: Owned[dict[str, str]] = {},
            headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("GET", url, "", move(params), move(headers))

    def delete(self: Ref[TestClient], url: str, params: Owned[dict[str, str]] = {},
               headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("DELETE", url, "", move(params), move(headers))

    def head(self: Ref[TestClient], url: str, params: Owned[dict[str, str]] = {},
             headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("HEAD", url, "", move(params), move(headers))

    def options(self: Ref[TestClient], url: str, params: Owned[dict[str, str]] = {},
                headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("OPTIONS", url, "", move(params), move(headers))

    def post(self: Ref[TestClient], url: str, json: PyVal = None, params: Owned[dict[str, str]] = {},
             headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("POST", url, _body(json), move(params), move(headers))

    def put(self: Ref[TestClient], url: str, json: PyVal = None, params: Owned[dict[str, str]] = {},
            headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("PUT", url, _body(json), move(params), move(headers))

    def patch(self: Ref[TestClient], url: str, json: PyVal = None, params: Owned[dict[str, str]] = {},
              headers: Owned[dict[str, str]] = {}) -> ClientResponse:
        return self.request("PATCH", url, _body(json), move(params), move(headers))


def _body(json: PyVal) -> str:
    """The request body for a `json=` argument (omitted json sends no body)."""
    if json is None:
        return ""
    return dumps(json, False)


def _headers_dict(h: Ref[_Headers]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in h.lines:
        c: int = line.find(":")
        if c > 0:
            out[line[0:c].strip().lower()] = line[c + 1:len(line)].strip()
    return out


def handle_once(app: Ref[FastAPI], srv: Mut[HTTPServer]) -> None:
    """Accept and answer exactly one HTTP request on srv with app's routes."""
    req: BaseHTTPRequestHandler = srv.handle_request()
    if req.command == "":
        return
    hs: dict[str, str] = _headers_dict(req.headers)
    raw: bytes = req.rfile.read()
    body: str = ""
    try:
        body = raw.decode("utf-8")
    except ValueError as e:
        body = ""
    resp: Response = app._handle(req.command, req.path, move(hs), body)
    req.send_response(resp.status_code)
    req.send_header("content-type", resp.media_type)
    payload: bytes = resp.content.encode("utf-8")
    req.send_header("content-length", str(len(payload)))
    for k, v in resp.headers.items():
        req.send_header(k, v)
    req.send_header("connection", "close")
    req.end_headers()
    n: int = req.wfile.write(payload)
    req.finish()
    _run_background(resp)


def _status_line(code: int) -> str:
    if code == 200:
        return "200 OK"
    if code == 201:
        return "201 Created"
    if code == 204:
        return "204 No Content"
    if code == 301:
        return "301 Moved Permanently"
    if code == 307:
        return "307 Temporary Redirect"
    if code == 400:
        return "400 Bad Request"
    if code == 404:
        return "404 Not Found"
    if code == 405:
        return "405 Method Not Allowed"
    if code == 500:
        return "500 Internal Server Error"
    return str(code) + " Unknown"


def _status_head(code: int) -> bytes:
    """The full 'HTTP/1.1 <status>' line plus the content-type header name, precomposed."""
    if code == 200:
        return b"HTTP/1.1 200 OK\r\ncontent-type: "
    if code == 201:
        return b"HTTP/1.1 201 Created\r\ncontent-type: "
    if code == 204:
        return b"HTTP/1.1 204 No Content\r\ncontent-type: "
    if code == 301:
        return b"HTTP/1.1 301 Moved Permanently\r\ncontent-type: "
    if code == 307:
        return b"HTTP/1.1 307 Temporary Redirect\r\ncontent-type: "
    if code == 400:
        return b"HTTP/1.1 400 Bad Request\r\ncontent-type: "
    if code == 404:
        return b"HTTP/1.1 404 Not Found\r\ncontent-type: "
    if code == 405:
        return b"HTTP/1.1 405 Method Not Allowed\r\ncontent-type: "
    if code == 422:
        return b"HTTP/1.1 422 Unprocessable Entity\r\ncontent-type: "
    if code == 500:
        return b"HTTP/1.1 500 Internal Server Error\r\ncontent-type: "
    return ("HTTP/1.1 " + _status_line(code) + "\r\ncontent-type: ").encode("utf-8")


def _fast_head(code: int, media_type: str) -> bytes:
    """Status line + content-type + the 'content-length: ' label as ONE literal, or b"".

    Empty means "no precomposed form" — the caller builds the head field by field.
    """
    if code == 200:
        if media_type == "application/json":
            return b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: "
        if media_type == "text/plain; charset=utf-8":
            return (b"HTTP/1.1 200 OK\r\ncontent-type: text/plain; charset=utf-8"
                    b"\r\ncontent-length: ")
        if media_type == "text/html; charset=utf-8":
            return (b"HTTP/1.1 200 OK\r\ncontent-type: text/html; charset=utf-8"
                    b"\r\ncontent-length: ")
    return b""


def listen(host: str, port: int) -> int:
    """Bind a listening TCP socket; the returned fd is Send (workers may share it)."""
    return _listen(host, port)


def shutdown_install() -> None:
    """Route SIGTERM/SIGINT (Ctrl-C/Ctrl-Break on Windows) to a graceful stop of every serve loop."""
    _shutdown_install()


def shutdown_requested() -> bool:
    """True once a shutdown signal arrived or shutdown_request() was called."""
    return _shutdown_requested()


def shutdown_request() -> None:
    """Ask every serve loop in the process to stop accepting, drain in-flight requests and return."""
    _shutdown_request()


def listen_port(fd: int) -> int:
    """The local port of a listening socket (useful after binding port 0)."""
    return _local_port(fd)


@dataclass
class _Parsed:
    ok: bool
    method: str
    target: str
    headers: dict[str, str]
    body: str
    keep: bool


def _parse_request(conn: int) -> _Parsed:
    """Read one HTTP/1.1 request (head + content-length body) off a connection."""
    bad: _Parsed = _Parsed(False, "", "", {}, "", False)
    raw: bytes = _read_head(conn)
    sep: int = raw.find(b"\r\n\r\n")
    if sep < 0:
        return bad
    head: bytes = raw[0:sep]
    rest: bytes = raw[sep + 4:len(raw)]
    lines: list[bytes] = head.split(b"\r\n")
    reqline: str = ""
    try:
        reqline = lines[0].decode("utf-8")
    except ValueError as e:
        return bad
    parts: list[str] = reqline.split(" ")
    if len(parts) != 3:
        return bad
    hs: dict[str, str] = {}
    clen: int = 0
    i: int = 1
    while i < len(lines):
        hline: str = ""
        try:
            hline = lines[i].decode("utf-8")
        except ValueError as e:
            return bad
        c: int = hline.find(":")
        if c > 0:
            hname: str = hline[0:c].strip().lower()
            hval: str = hline[c + 1:len(hline)].strip()
            hs[hname] = hval
            if hname == "content-length" and _digits_ok(hval):
                clen = _parse_clen(hval)
        i += 1
    if clen > MAX_BODY:
        return _Parsed(False, "413", "", {}, "", False)
    full: bytes = _read_body(conn, rest, clen)
    if len(full) < clen:
        return bad
    body: str = ""
    try:
        body = full[0:clen].decode("utf-8")
    except ValueError as e:
        body = ""
    conn_hdr: str = ""
    v: str | None = hs.get("connection")
    if v is not None:
        conn_hdr = v.lower()
    keep: bool = parts[2] == "HTTP/1.1" and conn_hdr != "close"
    return _Parsed(True, parts[0], parts[1], move(hs), body, keep)


def _write_response(conn: int, resp: Ref[Response], keep: bool) -> None:
    """Serialize and send one response; closes the connection unless keep-alive."""
    payload: bytes = resp.content.encode("utf-8")
    out: str = "HTTP/1.1 " + _status_line(resp.status_code) + "\r\n"
    out += "content-type: " + resp.media_type + "\r\n"
    if resp.streaming:
        out += "transfer-encoding: chunked\r\n"
    else:
        out += "content-length: " + str(len(payload)) + "\r\n"
    for k, hv in resp.headers.items():
        out += k + ": " + hv + "\r\n"
    if keep:
        out += "connection: keep-alive\r\n\r\n"
    else:
        out += "connection: close\r\n\r\n"
    if resp.streaming:
        n0: int = _send_all(conn, out.encode("utf-8"), 0)
        _send_stream(conn, resp)
    else:
        n: int = _send_all(conn, out.encode("utf-8") + payload, 0)
    if not keep:
        _close(conn)
    _run_background(resp)


def _reject(conn: int, why: str) -> None:
    """Close a connection whose request failed to parse, replying 413 when the body was oversize."""
    if why == "413":
        try:
            n: int = _send_all(conn, b"HTTP/1.1 413 Payload Too Large\r\ncontent-length: 0\r\n"
                                     b"connection: close\r\n\r\n", 0)
        except OSError as e:
            pass
    _close(conn)


def _handle_conn(app: Ref[FastAPI], conn: int) -> bool:
    """Serve one request on an open connection; True if it should be kept alive."""
    p: _Parsed = _parse_request(conn)
    if not p.ok:
        _reject(conn, p.method)
        return False
    resp: Response = app._handle(p.method, p.target, move(p.headers), p.body)
    _write_response(conn, resp, p.keep)
    return p.keep


async def _handle_conn_async(app: Ref[FastAPI], conn: int) -> int:
    """Task-context twin of _handle_conn: socket waits and async handlers suspend.
    Returns -1 (peer gone, nothing served), 0 (served, connection closed) or 1 (served, keep)."""
    p: _Parsed = _parse_request(conn)
    if not p.ok:
        _reject(conn, p.method)
        return -1
    resp: Response = await app._handle_async(p.method, p.target, move(p.headers), p.body)
    _write_response(conn, resp, p.keep)
    if p.keep:
        return 1
    return 0


async def accept_async(fd: int) -> int:
    """Accept one connection cooperatively (the listener and the new connection are put
    in async mode, D45); pair with `asyncio.create_task(handler(conn))` + `serve_conn`."""
    _set_async(fd)
    conn: int = _accept(fd)
    _set_async(conn)
    _set_timeout(conn, 10000)
    return conn


async def serve_conn(app: Ref[FastAPI], conn: int, max_requests: int = -1) -> int:
    """Serve HTTP/1.1 keep-alive requests on one async-mode connection inside a task;
    `async def` handlers are awaited so other connections' tasks keep running.
    Returns the number of requests served."""
    served: int = 0
    alive: bool = True
    while alive and (max_requests < 0 or served < max_requests):
        code: int = await _handle_conn_async(app, conn)
        if code >= 0:
            served += 1
        alive = code == 1
    if alive:
        _close(conn)
    return served


def serve_on(app: Ref[FastAPI], fd: int, max_requests: int = -1) -> None:
    """Accept-and-serve loop (HTTP/1.1 keep-alive) on a shared listening socket.

    Run one call per worker thread: `spawn(worker, fd)` where the worker builds
    its own app and calls serve_on(app, fd). max_requests bounds the total
    requests served by THIS worker (-1 = forever). The loop returns after a
    shutdown request (SIGTERM/Ctrl-C once `shutdown_install()` ran, or
    `shutdown_request()`): the request in flight finishes, then its connection closes.
    """
    _set_nonblocking(fd)
    served: int = 0
    while (max_requests < 0 or served < max_requests) and not shutdown_requested():
        ready: bytes = _poll_ready(_pack1(fd), 100)
        if len(ready) == 0:
            continue
        conn: int = _accept_nb(fd)
        if conn <= 0:
            continue
        _set_timeout(conn, 10000)
        alive: bool = True
        while alive and (max_requests < 0 or served < max_requests):
            try:
                alive = _handle_conn(app, conn)
            except Exception as e:
                alive = False
                try:
                    _close(conn)
                except Exception as e2:
                    pass
            served += 1
            if alive and shutdown_requested():
                break
        if alive:
            _close(conn)


SHUTDOWN_GRACE: float = 10.0


def run(app: Owned[FastAPI], host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve app on this thread until SIGTERM/Ctrl-C (uvicorn.run equivalent, event-loop I/O).

    The first signal stops accepting, lets in-flight requests finish (up to
    SHUTDOWN_GRACE seconds), closes idle keep-alive connections and returns; a
    second signal terminates immediately."""
    shutdown_install()
    fd: int = listen(host, port)
    serve_async(app, fd)
    _close(fd)


def _pack(hs: Ref[list[int]]) -> bytes:
    out: bytearray = bytearray(b"")
    for h in hs:
        v: int = h
        j: int = 0
        while j < 8:
            out.append(v % 256)
            v = v // 256
            j += 1
    return bytes(out)


def _unpack(data: bytes) -> list[int]:
    out: list[int] = []
    i: int = 0
    while i + 8 <= len(data):
        v: int = 0
        mult: int = 1
        j: int = 0
        while j < 8:
            v += data[i + j] * mult
            j += 1
            if j < 8:
                mult *= 256
        out.append(v)
        i += 8
    return out


def _index_of(xs: Ref[list[int]], x: int) -> int:
    i: int = 0
    while i < len(xs):
        if xs[i] == x:
            return i
        i += 1
    return -1


def _pack1(h: int) -> bytes:
    """The 8-byte little-endian encoding of a single socket handle."""
    out: bytearray = bytearray(b"")
    v: int = h
    j: int = 0
    while j < 8:
        out.append(v % 256)
        v = v // 256
        j += 1
    return bytes(out)


def _parse_reqline(line: str) -> list[str]:
    parts: list[str] = line.split(" ")
    if len(parts) != 3:
        return []
    return parts


def _parse_headers(lines: Ref[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    i: int = 1
    while i < len(lines):
        hline: str = lines[i]
        c: int = hline.find(":")
        if c > 0:
            out[hline[0:c].strip().lower()] = hline[c + 1:len(hline)].strip()
        i += 1
    return out


def _serve_buffered(app: Ref[FastAPI], conn: int, raw: Ref[bytes]) -> tuple[int, bool]:
    """Serve at most one complete buffered request; returns (consumed bytes, keep-alive).

    consumed 0 = incomplete (need more data), -1 = malformed/oversized (drop conn).
    """
    sep: int = raw.find(b"\r\n\r\n")
    if sep < 0:
        if len(raw) > 65536:
            return (-1, False)
        return (0, True)
    head: str = ""
    try:
        head = raw[0:sep].decode("utf-8")
    except ValueError as e:
        return (-1, False)
    lines: list[str] = head.split("\r\n")
    parts: list[str] = _parse_reqline(lines[0])
    if len(parts) == 0:
        return (-1, False)
    hs: dict[str, str] = _parse_headers(lines)
    clen: int = 0
    v: str | None = hs.get("content-length")
    if v is not None:
        if _digits_ok(v):
            clen = _parse_clen(v)
    if clen > MAX_BODY:
        return (-1, False)
    total: int = sep + 4 + clen
    if len(raw) < total:
        return (0, True)
    body: str = ""
    if clen > 0:
        try:
            body = raw[sep + 4:total].decode("utf-8")
        except ValueError as e:
            body = ""
    conn_hdr: str = ""
    v2: str | None = hs.get("connection")
    if v2 is not None:
        conn_hdr = v2.lower()
    keep: bool = parts[2] == "HTTP/1.1" and conn_hdr != "close"
    resp: Response = app._handle(parts[0], parts[1], move(hs), body)
    if resp.streaming:
        sh: bytearray = bytearray(_status_head(resp.status_code))
        sh.extend(resp.media_type.encode("utf-8"))
        sh.extend(b"\r\ntransfer-encoding: chunked\r\n")
        for k0, hv0 in resp.headers.items():
            sh.extend((k0 + ": " + hv0 + "\r\n").encode("utf-8"))
        if keep:
            sh.extend(b"connection: keep-alive\r\n\r\n")
        else:
            sh.extend(b"connection: close\r\n\r\n")
        ns: int = _send_all(conn, bytes(sh), 0)
        _send_stream(conn, resp)
        _run_background(resp)
        return (total, keep)
    payload: bytes = resp.content.encode("utf-8")
    fast: bytes = b""
    if len(resp.headers) == 0:
        fast = _fast_head(resp.status_code, resp.media_type)
    out: bytearray = bytearray(b"")
    if len(fast) > 0:
        out.extend(fast)
        out.extend(str(len(payload)).encode("utf-8"))
        if keep:
            out.extend(b"\r\nconnection: keep-alive\r\n\r\n")
        else:
            out.extend(b"\r\nconnection: close\r\n\r\n")
        out.extend(payload)
        n0: int = _send_all(conn, bytes(out), 0)
        _run_background(resp)
        return (total, keep)
    out.extend(_status_head(resp.status_code))
    out.extend(resp.media_type.encode("utf-8"))
    out.extend(b"\r\ncontent-length: ")
    out.extend(str(len(payload)).encode("utf-8"))
    out.extend(b"\r\n")
    for k, hv in resp.headers.items():
        out.extend((k + ": " + hv + "\r\n").encode("utf-8"))
    if keep:
        out.extend(b"connection: keep-alive\r\n\r\n")
    else:
        out.extend(b"connection: close\r\n\r\n")
    out.extend(payload)
    n: int = _send_all(conn, bytes(out), 0)
    _run_background(resp)
    return (total, keep)


def serve_async(app: Ref[FastAPI], fd: int, max_requests: int = -1,
                read_deadline: float = 30.0) -> None:
    """Event-loop serving: ONE thread multiplexes every connection (non-blocking I/O).

    This is the uvicorn-style model: readiness-polled sockets, no thread per
    connection. Run one loop per worker thread for multi-core scaling
    (spawn(worker, fd) with each worker calling serve_async on its own app).
    """
    _set_nonblocking(fd)
    conns: list[int] = []
    bufs: list[bytearray] = []
    since: list[float] = []
    slot: dict[int, int] = {}
    packed: bytearray = bytearray(_pack1(fd))
    dirty: bool = False
    served: int = 0
    draining: bool = False
    deadline: float = 0.0
    while max_requests < 0 or served < max_requests:
        now: float = _monotonic()
        if not draining and shutdown_requested():
            draining = True
            deadline = now + SHUTDOWN_GRACE
            dirty = True
        closed: list[int] = []
        for ci in range(len(conns)):
            if len(bufs[ci]) > 0:
                if now - since[ci] > read_deadline:
                    closed.append(conns[ci])
            elif draining:
                closed.append(conns[ci])
        if draining and (len(closed) == len(conns) or now >= deadline):
            break
        if dirty:
            if draining:
                packed = bytearray(b"")
            else:
                packed = bytearray(_pack1(fd))
            for cfd in conns:
                packed.extend(_pack1(cfd))
            dirty = False
        ready: list[int] = []
        if len(packed) > 0:
            ready = _unpack(_poll_ready(bytes(packed), 50))
        for h in ready:
            if h == fd and not draining:
                accepting: bool = True
                naccept: int = 0
                while accepting:
                    c: int = _accept_nb(fd)
                    if c > 0:
                        _set_nonblocking(c)
                        slot[c] = len(conns)
                        conns.append(c)
                        bufs.append(bytearray(b""))
                        since.append(now)
                        packed.extend(_pack1(c))
                        naccept += 1
                        if naccept >= 64:
                            accepting = False
                    else:
                        accepting = False
                continue
            si: int | None = slot.get(h)
            if si is None:
                continue
            idx: int = si
            hup: bool = False
            fresh: int = 0
            reading: bool = True
            while reading:
                data: bytes = b""
                got: bool = True
                try:
                    data = _recv(h, 65536)
                except OSError as e:
                    got = False
                if not got:
                    reading = False
                elif len(data) == 0:
                    hup = True
                    reading = False
                else:
                    fresh += len(data)
                    if len(data) < 65536:
                        reading = False
                    if len(bufs[idx]) == 0:
                        since[idx] = now
                    bufs[idx].extend(data)
            if fresh == 0:
                if hup:
                    closed.append(h)
                continue
            raw: bytes = bytes(bufs[idx])
            pumping: bool = True
            while pumping:
                res: tuple[int, bool] = (-1, False)
                try:
                    res = _serve_buffered(app, h, raw)
                except Exception as e_io:
                    res = (-1, False)
                if res[0] < 0:
                    closed.append(h)
                    pumping = False
                elif res[0] == 0:
                    pumping = False
                else:
                    served += 1
                    if res[0] >= len(raw):
                        raw = b""
                        pumping = False
                    else:
                        raw = raw[res[0]:len(raw)]
                    if not res[1]:
                        closed.append(h)
                        pumping = False
                    elif max_requests >= 0 and served >= max_requests:
                        pumping = False
            bufs[idx] = bytearray(b"")
            if len(raw) > 0:
                bufs[idx].extend(raw)
                since[idx] = now
            if hup:
                closed.append(h)
        for h2 in closed:
            si2: int | None = slot.get(h2)
            if si2 is not None:
                idx2: int = si2
                _close(h2)
                slot.pop(h2)
                last: int = len(conns) - 1
                if idx2 != last:
                    moved: int = conns[last]
                    tail: bytearray = bufs.pop()
                    conns[idx2] = moved
                    bufs[idx2] = move(tail)
                    since[idx2] = since[last]
                    slot[moved] = idx2
                else:
                    buf_gone: bytearray = bufs.pop()
                t_gone: float = since.pop()
                gone: int = conns.pop()
                dirty = True
    for h3 in conns:
        _close(h3)
