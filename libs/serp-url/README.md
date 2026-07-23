# serp-url

URL parsing and encoding for Serpentine. Pure Serpentine ([P]) — the same
source dual-runs under CPython.

```python
from serp_url import url_parse, quote, urlencode, parse_query

u = url_parse("https://example.com:8443/a/b?x=1&y=two#frag")
print(u.scheme, u.host, u.port, u.path, u.query, u.fragment)
print(quote("a b/c?"))                 # a%20b/c%3F
print(parse_query("x=1&name=J%C3%BCrgen"))
```

## API

- `Url` — dataclass: `scheme, host, port (-1 when absent), path, query, fragment`
- `url_parse(url) -> Url` — handles IPv6 bracket hosts; no userinfo support
- `default_port(scheme) -> int`, `effective_port(u) -> int`
- `quote(s)` / `unquote(s)` — RFC 3986 percent-encoding of UTF-8 ('/' kept safe in quote)
- `quote_plus(s)` / `unquote_plus(s)` — form encoding (space ↔ '+')
- `urlencode(params: dict[str, str]) -> str`
- `parse_query(q) -> dict[str, str]` — last value wins for duplicate keys
