# serp-http-server

A minimal, blocking HTTP/1.1 server for Serpentine. Pure Serpentine ([P])
over serp-socket — the same source dual-runs under CPython. Single-threaded,
connection-close model: one request per connection, handled inline in your
accept loop (the threaded model waits for Wave-6 concurrency, docs/decisions.md D9).

```python
from serp_http_server import (http_listen, http_accept, http_respond,
                              header_of, HttpRequest)

lst: int = http_listen("127.0.0.1", 8080)
while True:
    req: HttpRequest = http_accept(lst)
    if req.ok and req.path == "/hello":
        http_respond(req, 200, "text/plain", b"hi there")
    else:
        http_respond(req, 404, "text/plain", b"not found")
```

## API

- `http_listen(host, port) -> int` (port 0 = pick free), `http_port(listener) -> int`
- `http_accept(listener) -> HttpRequest` — blocks; parses request line, headers
  (lowercased names), query string and a Content-Length body (10s socket timeout)
- `HttpRequest` — `conn, ok, method, target, path, query, headers: list[str], body: bytes`;
  `ok == False` means the request was malformed (answer with 400)
- `header_of(req, name) -> str` — case-insensitive header lookup ("" if absent)
- `http_respond(req, status, content_type, body)` — writes the response with
  content-length + connection: close, then closes the connection
- `status_text(code) -> str`

## Limits

No TLS, no keep-alive, no chunked request bodies, no concurrent connections.
Deterministic output (no Date/Server headers).
