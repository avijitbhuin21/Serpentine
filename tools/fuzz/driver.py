"""Fuzz driver: reads `kind hex` lines and prints one verdict per case (same source under CPython and natively)."""
import sys

from serpentine import PyVal
from serp_base64 import b64decode
from serp_csv import reader
from serp_json import loads
from serp_re import compile
from serp_tomllib import loads as toml_loads
from serp_url import parse_qs, unquote, urlsplit
from serp_zlib import decompress, gzip_decompress, inflate


def clip(s: str) -> str:
    """At most 60 characters of s."""
    if len(s) > 60:
        return s[0:60]
    return s


def run_bytes(kind: str, data: bytes) -> str:
    """Parsers that take raw bytes."""
    try:
        if kind == "zlib":
            return "ok " + str(len(inflate(data)))
        if kind == "zlibw":
            return "ok " + str(len(decompress(data)))
        if kind == "gzip":
            return "ok " + str(len(gzip_decompress(data)))
        return "ok " + str(len(b64decode(data)))
    except Exception as e:
        return "err " + clip(str(e))


def run_text(kind: str, text: str) -> str:
    """Parsers that take str."""
    try:
        if kind == "json":
            v: PyVal = loads(text)
            return "ok " + clip(str(v))
        if kind == "toml":
            t: PyVal = toml_loads(text)
            return "ok " + clip(str(t))
        if kind == "url":
            u = urlsplit(text)
            q: dict[str, list[str]] = parse_qs(u.query)
            return "ok " + clip(u.scheme + "|" + u.netloc + "|" + unquote(u.path) + "|" + str(len(q)))
        if kind == "re":
            p = compile(text)
            m = p.search("aab-xyz 123 aaaa_bbbb cc\nzz")
            if m is None:
                return "ok nomatch"
            return "ok " + str(m.start()) + ":" + str(m.end())
        lines: list[str] = text.split("\n")
        rows: list[list[str]] = reader(lines)
        return "ok " + str(len(rows))
    except Exception as e:
        return "err " + clip(str(e))


def main() -> None:
    """Run cases [lo, hi) from the file in argv[1]."""
    f = open(sys.argv[1], "r")
    body: str = f.read()
    f.close()
    lines: list[str] = body.split("\n")
    lo: int = int(sys.argv[2])
    hi: int = int(sys.argv[3])
    i: int = lo
    while i < hi and i < len(lines):
        line: str = lines[i]
        sp: int = line.find(" ")
        if sp > 0:
            kind: str = line[0:sp]
            data: bytes = bytes.fromhex(line[sp + 1:len(line)])
            verdict: str = ""
            if kind == "zlib" or kind == "zlibw" or kind == "gzip" or kind == "b64":
                verdict = run_bytes(kind, data)
            else:
                try:
                    verdict = run_text(kind, data.decode("utf-8"))
                except ValueError as e:
                    verdict = "nodecode"
            print(str(i) + " " + verdict)
        i += 1


if __name__ == "__main__":
    main()
