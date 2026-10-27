"""serp-url — urllib.parse-compatible URL handling in the Serpentine subset.

Pure Serpentine ([P]): the same source runs under CPython and compiles
natively. Function names, signatures and observable behavior mirror
CPython's urllib.parse (urlparse, urlsplit, urljoin, quote, unquote,
urlencode, parse_qs, ...) with positional arguments only. Userinfo in
netloc is stripped for hostname but not otherwise interpreted.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, dataclass, move

_HEX_UPPER: str = "0123456789ABCDEF"
_HEX_LOWER: str = "0123456789abcdef"
_ASCII: str = (" !\"#$%&'()*+,-./0123456789:;<=>?"
               "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
               "`abcdefghijklmnopqrstuvwxyz{|}~")
_SCHEME_CHARS: str = ("abcdefghijklmnopqrstuvwxyz"
                      "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.")


@dataclass
class SplitResult:
    scheme: str
    netloc: str
    path: str
    query: str
    fragment: str
    hostname: str | None
    port: int | None


@dataclass
class ParseResult:
    scheme: str
    netloc: str
    path: str
    params: str
    query: str
    fragment: str
    hostname: str | None
    port: int | None


def _scheme_ok(s: str) -> bool:
    if s == "":
        return False
    first: str = s[0]
    alpha: bool = (first >= "a" and first <= "z") or (first >= "A" and first <= "Z")
    if not alpha:
        return False
    for ch in s:
        if _SCHEME_CHARS.find(ch) < 0:
            return False
    return True


def _parse_port(ps: str) -> int:
    v: int = 0
    for ch in ps:
        if ch < "0" or ch > "9":
            raise ValueError("Port could not be cast to integer value")
        v = v * 10 + int(ch)
    if v > 65535:
        raise ValueError("Port out of range 0-65535")
    return v


def _hostinfo(netloc: str) -> tuple[str, int]:
    hp: str = netloc
    at: int = -1
    i: int = len(netloc) - 1
    while i >= 0:
        if netloc[i] == "@":
            at = i
            break
        i -= 1
    if at >= 0:
        hp = netloc[at + 1:len(netloc)]
    host: str = hp
    port: int = -1
    if hp.startswith("["):
        rb: int = hp.find("]")
        if rb >= 0:
            host = hp[1:rb]
            tail: str = hp[rb + 1:len(hp)]
            if tail.startswith(":"):
                ps0: str = tail[1:len(tail)]
                if ps0 != "":
                    port = _parse_port(ps0)
    else:
        c: int = -1
        j: int = len(hp) - 1
        while j >= 0:
            if hp[j] == ":":
                c = j
                break
            j -= 1
        if c >= 0:
            host = hp[0:c]
            ps: str = hp[c + 1:len(hp)]
            if ps != "":
                port = _parse_port(ps)
    return (host.lower(), port)


def urlsplit(url: str) -> SplitResult:
    u: str = url.replace("\t", "")
    u = u.replace("\r", "")
    u = u.replace("\n", "")
    scheme: str = ""
    rest: str = u
    c: int = rest.find(":")
    if c > 0 and _scheme_ok(rest[0:c]):
        scheme = rest[0:c].lower()
        rest = rest[c + 1:len(rest)]
    netloc: str = ""
    if rest.startswith("//"):
        end: int = len(rest)
        i: int = 2
        while i < len(rest):
            ch: str = rest[i]
            if ch == "/" or ch == "?" or ch == "#":
                end = i
                break
            i += 1
        netloc = rest[2:end]
        rest = rest[end:len(rest)]
    fragment: str = ""
    f: int = rest.find("#")
    if f >= 0:
        fragment = rest[f + 1:len(rest)]
        rest = rest[0:f]
    query: str = ""
    q: int = rest.find("?")
    if q >= 0:
        query = rest[q + 1:len(rest)]
        rest = rest[0:q]
    hi: tuple[str, int] = _hostinfo(netloc)
    hostname: str | None = None
    if hi[0] != "":
        hostname = hi[0]
    port: int | None = None
    if hi[1] >= 0:
        port = hi[1]
    return SplitResult(scheme, netloc, rest, query, fragment, hostname, port)


def _splitparams(p: str) -> tuple[str, str]:
    start: int = 0
    i: int = len(p) - 1
    while i >= 0:
        if p[i] == "/":
            start = i
            break
        i -= 1
    semi: int = -1
    j: int = start
    while j < len(p):
        if p[j] == ";":
            semi = j
            break
        j += 1
    if semi < 0:
        return (p, "")
    return (p[0:semi], p[semi + 1:len(p)])


def urlparse(url: str) -> ParseResult:
    s: SplitResult = urlsplit(url)
    path: str = s.path
    params: str = ""
    if path.find(";") >= 0:
        pp: tuple[str, str] = _splitparams(path)
        path = pp[0]
        params = pp[1]
    return ParseResult(s.scheme, s.netloc, path, params, s.query, s.fragment,
                       s.hostname, s.port)


def _unsplit(scheme: str, netloc: str, path: str, query: str,
             fragment: str) -> str:
    url: str = path
    if netloc != "" or path.startswith("//"):
        if path != "" and not path.startswith("/"):
            url = "/" + path
        url = "//" + netloc + url
    if scheme != "":
        url = scheme + ":" + url
    if query != "":
        url = url + "?" + query
    if fragment != "":
        url = url + "#" + fragment
    return url


def urlunsplit(components: Ref[SplitResult]) -> str:
    return _unsplit(components.scheme, components.netloc, components.path,
                    components.query, components.fragment)


def urlunparse(components: Ref[ParseResult]) -> str:
    path: str = components.path
    if components.params != "":
        path = path + ";" + components.params
    return _unsplit(components.scheme, components.netloc, path,
                    components.query, components.fragment)


def _merge(bnetloc: str, bpath: str, rpath: str) -> str:
    if bnetloc != "" and bpath == "":
        return "/" + rpath
    sl: int = -1
    i: int = len(bpath) - 1
    while i >= 0:
        if bpath[i] == "/":
            sl = i
            break
        i -= 1
    if sl < 0:
        return rpath
    return bpath[0:sl + 1] + rpath


def _remove_dots(path: str) -> str:
    if path == "":
        return ""
    segs: list[str] = path.split("/")
    out: list[str] = []
    for seg in segs:
        if seg == ".":
            continue
        if seg == "..":
            if len(out) > 1:
                dropped: str = out.pop()
            elif len(out) == 1:
                if out[0] != "":
                    dropped2: str = out.pop()
        else:
            out.append(seg)
    last: str = segs[len(segs) - 1]
    if last == "." or last == "..":
        out.append("")
    return "/".join(out)


def urljoin(base: str, url: str) -> str:
    if base == "":
        return url
    if url == "":
        return base
    b: SplitResult = urlsplit(base)
    r: SplitResult = urlsplit(url)
    if r.scheme != "" and r.scheme != b.scheme:
        return url
    scheme: str = r.scheme
    if scheme == "":
        scheme = b.scheme
    if r.netloc != "":
        return _unsplit(scheme, r.netloc, _remove_dots(r.path), r.query,
                        r.fragment)
    netloc: str = b.netloc
    path: str = ""
    query: str = r.query
    if r.path == "":
        path = b.path
        if query == "":
            query = b.query
    elif r.path.startswith("/"):
        path = _remove_dots(r.path)
    else:
        path = _remove_dots(_merge(b.netloc, b.path, r.path))
    return _unsplit(scheme, netloc, path, query, r.fragment)


def urldefrag(url: str) -> tuple[str, str]:
    h: int = url.find("#")
    if h < 0:
        return (url, "")
    return (url[0:h], url[h + 1:len(url)])


def _quote_byte(b: int) -> str:
    return "%" + _HEX_UPPER[b // 16] + _HEX_UPPER[b % 16]


def _is_unreserved(b: int) -> bool:
    if b >= 48 and b <= 57:
        return True
    if b >= 65 and b <= 90:
        return True
    if b >= 97 and b <= 122:
        return True
    return b == 45 or b == 46 or b == 95 or b == 126


def quote(s: str, safe: str = "/") -> str:
    data: bytes = s.encode("utf-8")
    safeb: bytes = safe.encode("utf-8")
    out: list[str] = []
    for b in data:
        keep: bool = _is_unreserved(b)
        if not keep:
            for sb in safeb:
                if sb == b:
                    keep = True
                    break
        if keep and b >= 32 and b <= 126:
            out.append(_ASCII[b - 32])
        else:
            out.append(_quote_byte(b))
    return "".join(out)


def quote_plus(s: str, safe: str = "") -> str:
    q: str = quote(s, safe + " ")
    return q.replace(" ", "+")


def _utf8_seq(b: Ref[bytes], i: int) -> int:
    """Length of the well-formed UTF-8 sequence at i, or -k for a k-byte maximal invalid subpart."""
    n: int = len(b)
    c: int = b[i]
    if c < 128:
        return 1
    need: int = 0
    lo: int = 128
    hi: int = 191
    if c >= 0xC2 and c <= 0xDF:
        need = 1
    elif c == 0xE0:
        need = 2
        lo = 0xA0
    elif (c >= 0xE1 and c <= 0xEC) or c == 0xEE or c == 0xEF:
        need = 2
    elif c == 0xED:
        need = 2
        hi = 0x9F
    elif c == 0xF0:
        need = 3
        lo = 0x90
    elif c >= 0xF1 and c <= 0xF3:
        need = 3
    elif c == 0xF4:
        need = 3
        hi = 0x8F
    else:
        return -1
    j: int = 1
    while j <= need:
        if i + j >= n:
            return -j
        x: int = b[i + j]
        if j == 1:
            if x < lo or x > hi:
                return -j
        elif x < 128 or x > 191:
            return -j
        j += 1
    return need + 1


def _decode_replace(b: bytes) -> str:
    """UTF-8 decode with errors='replace' (one U+FFFD per maximal invalid subpart, as CPython)."""
    parts: list[str] = []
    i: int = 0
    start: int = 0
    n: int = len(b)
    while i < n:
        k: int = _utf8_seq(b, i)
        if k > 0:
            i += k
        else:
            if i > start:
                parts.append(b[start:i].decode("utf-8"))
            parts.append("\ufffd")
            i += -k
            start = i
    if start < n:
        parts.append(b[start:n].decode("utf-8"))
    return "".join(parts)


def unquote(s: str) -> str:
    out: bytearray = bytearray(b"")
    i: int = 0
    n: int = len(s)
    while i < n:
        ch: str = s[i]
        if ch == "%" and i + 2 <= n - 1:
            h1: int = _HEX_LOWER.find(s[i + 1].lower())
            h2: int = _HEX_LOWER.find(s[i + 2].lower())
            if h1 >= 0 and h2 >= 0:
                vals: list[int] = [h1 * 16 + h2]
                out.extend(bytes(vals))
                i += 3
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return _decode_replace(bytes(out))


def unquote_plus(s: str) -> str:
    return unquote(s.replace("+", " "))


def urlencode(query: Ref[dict[str, str]]) -> str:
    parts: list[str] = []
    for k, v in query.items():
        parts.append(quote_plus(k, "") + "=" + quote_plus(v, ""))
    return "&".join(parts)


def parse_qsl(qs: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if qs == "":
        return out
    for pair in qs.split("&"):
        if pair == "":
            continue
        eq: int = pair.find("=")
        if eq < 0:
            continue
        value: str = unquote_plus(pair[eq + 1:len(pair)])
        if value == "":
            continue
        name: str = unquote_plus(pair[0:eq])
        out.append((name, value))
    return out


def parse_qs(qs: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if qs == "":
        return out
    for pair in qs.split("&"):
        if pair == "":
            continue
        eq: int = pair.find("=")
        if eq < 0:
            continue
        value: str = unquote_plus(pair[eq + 1:len(pair)])
        if value == "":
            continue
        name: str = unquote_plus(pair[0:eq])
        if name in out:
            out[name].append(value)
        else:
            vals: list[str] = [value]
            out[name] = move(vals)
    return out
