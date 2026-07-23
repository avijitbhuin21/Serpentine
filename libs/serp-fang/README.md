# serp-fang (Fang)

Fang is Serpentine's synchronous HTTP(S) client — the httpx equivalent.
It is layered like the Rust HTTP stacks: a native transport core
(serp-socket: std::net + system TLS — schannel on Windows, OpenSSL on
Linux/macOS) with a thin pure-Serpentine façade that mirrors httpx names
and behavior. The same source dual-runs under CPython (ssl module).

```python
from serp_fang import Client, Response, client, get, post

r: Response = get("https://example.com/")
print(r.status_code, r.header("content-type"))
print(r.text())
r.raise_for_status()

p: Response = post("https://api.example/items", b'{"name": "fang"}',
                   content_type="application/json")
j = p.json()

c: Client = client("https://api.example", timeout=10.0, follow_redirects=True)
c.set_basic_auth("user", "secret")
r2: Response = c.get("/items")
```

## httpx-equivalent API

Top-level verbs (each takes `timeout=5.0, follow_redirects=False, verify=True`
keywords, matching httpx defaults):

- `get / head / options / delete (url, ...)` — `get` also takes `auth_user` / `auth_pass`
- `post / put / patch (url, content, content_type=...)` — raw-body variants
- `post_form(url, form)` — httpx `data=...`
- `post_json(url, payload)` — httpx `json=...` (payload is a dynamic PyVal)
- `post_multipart(url, fields, files, boundary="")` — httpx `files=...` with `FilePart`
- `request(method, url, ...)` — bodyless generic request
- `stream(method, url, ...) -> ResponseStream` — httpx `stream`: `read()` chunks, `close()`
- `download(url, path, ...)` — streams a body straight to disk (constant memory)
- `upload_file(method, url, path, content_type=...)` — file body, wire-chunked sends
- helpers: `with_params(url, params)` (httpx `params=...`), `basic_auth(user, pw)`,
  `build_multipart`, `multipart_content_type`, `header_value`, `parse_response`,
  `decode_chunked`

`Client` (httpx.Client): `base_url`, default `headers`, persistent `cookies`
jar, `timeout`, `follow_redirects`, `max_redirects`, `verify`, basic auth;
methods mirror the verbs plus `stream/download/upload_file/set_header/`
`set_cookie/set_basic_auth/close`. Create with `client(...)` (kwargs like
httpx.Client).

`Response` (httpx.Response): `status_code`, `reason_phrase`, `http_version`,
`url` (final URL after redirects), `headers`, `content`, `history`
(pre-redirect URLs), `elapsed`; methods `text()`, `json()`, `header(name)`,
`cookies()`, `is_success()/is_redirect()/is_client_error()/is_server_error()/`
`is_error()/is_informational()`, `has_redirect_location()`,
`raise_for_status()` (raises `HTTPStatusError`).

Behavior parity with httpx:

- **https** with SNI + system trust roots; `verify=False` opt-out;
  cert failures raise `OSError("certificate verify failed")`.
- Redirects (when `follow_redirects=True`): 301/302/303 convert to GET and
  drop the body (307/308 preserve), Location is resolved with `urljoin`,
  authorization is stripped on cross-host hops, `TooManyRedirects` past
  `max_redirects`.
- Cookies: `set-cookie` responses populate the client jar and are replayed.
- `accept-encoding: gzip` is sent and gzip/deflate bodies decode
  transparently (streams request `identity` instead).
- Content-Length and chunked framing, incremental in `ResponseStream`.

## Divergences from httpx (language subset)

- Properties are methods: `r.text()`, not `r.text`.
- kwargs that take lists/dicts/bytes in httpx are explicit parameters or
  `Client` fields (defaults may only be scalar literals).
- One connection per request (`connection: close`) — no pooling/keep-alive,
  no HTTP/2, no async, no proxies.
- `text()` decodes UTF-8 (no charset sniffing).
- Transport errors are the normalized serp-socket `OSError`s
  ("connection refused", "timed out", "tls handshake failed", ...).
