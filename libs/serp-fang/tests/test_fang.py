from serp_fang import (Client, FilePart, HTTPStatusError, Response, basic_auth,
                       build_multipart, client, decode_chunked, get,
                       header_value, multipart_content_type, parse_response,
                       with_params)
from serpentine import PyVal
from serp_json import dumps
from serp_zlib import gzip_compress


def main() -> None:
    r1: Response = parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 11\r\n\r\nhello worldTRAILING")
    print(r1.status_code, r1.reason_phrase, r1.http_version)
    print(r1.header("content-type"), r1.header("Content-Type"), r1.header("missing", "n/a"))
    print(r1.content)
    print(r1.text())
    print(r1.is_success(), r1.is_error(), r1.is_redirect())
    r1.raise_for_status()
    print("no raise")

    chunked: bytes = b"4\r\nWiki\r\n7\r\npedia i\r\nB\r\nn\r\nchunks.\r\n0\r\n\r\n"
    print(decode_chunked(chunked))
    r2: Response = parse_response(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + chunked)
    print(r2.content)

    gz: bytes = gzip_compress(b"gzip bodies decode transparently in fang", 6)
    raw3: bytes = (b"HTTP/1.1 200 OK\r\ncontent-encoding: gzip\r\ncontent-length: "
                   + str(len(gz)).encode("utf-8") + b"\r\n\r\n" + gz)
    r3: Response = parse_response(raw3)
    print(r3.text())

    r4: Response = parse_response(b"HTTP/1.1 404 Not Found\r\ncontent-length: 2\r\n\r\nno")
    print(r4.is_client_error(), r4.is_server_error(), r4.is_error())
    try:
        r4.raise_for_status()
        print("unreachable")
    except HTTPStatusError as e:
        print("status:", e)

    rj: Response = parse_response(
        b'HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: 20\r\n\r\n{"ok": true, "n": 7}')
    j: PyVal = rj.json()
    print(dumps(j))

    r5: Response = parse_response(
        b"HTTP/1.1 302 Found\r\nlocation: /next\r\ncontent-length: 0\r\n\r\n")
    print(r5.is_redirect(), r5.has_redirect_location(), r5.header("location"))
    try:
        r5.raise_for_status()
        print("unreachable")
    except HTTPStatusError as e:
        print("redir:", e)

    r6: Response = parse_response(
        b"HTTP/1.1 200 OK\r\nset-cookie: a=1; Path=/\r\nset-cookie: b=2\r\ncontent-length: 0\r\n\r\n")
    print(r6.cookies())
    print(r6.history)

    params: dict[str, str] = {"q": "snake bite", "page": "2"}
    print(with_params("http://h.example/s", params))
    print(with_params("http://h.example/s?x=1", params))
    print(basic_auth("user", "pass"))
    print(multipart_content_type("BOUND"))
    fields: dict[str, str] = {"name": "fang", "kind": "snake"}
    files: list[FilePart] = [FilePart("data", "bite.bin", "application/octet-stream", b"\x00\x01VENOM")]
    print(build_multipart(fields, files, "BOUND"))

    hs: list[str] = ["content-type: text/plain", "x-a: 1"]
    print(header_value(hs, "X-A"), header_value(hs, "nope", "-"))

    c: Client = client("http://api.example", 3.5, True, 5, False, "u", "p")
    print(c.base_url, c.timeout, c.follow_redirects, c.max_redirects, c.verify, c.auth_user)
    c.set_header("X-Trace: on")
    c.set_cookie("sid", "abc")
    c.set_cookie("sid", "xyz")
    c.set_cookie("t", "1")
    print(c.headers)
    print(c.cookies)
    d: Client = client()
    print(d.timeout, d.follow_redirects, d.max_redirects, d.verify)
    d.close()

    try:
        rf: Response = get("ftp://example.com/")
        print(rf.status_code)
    except ValueError as e:
        print("scheme:", e)
    try:
        rh: Response = get("http:///nohost")
        print(rh.status_code)
    except ValueError as e:
        print("host:", e)
    try:
        rr: Response = get("http://127.0.0.1:1/", timeout=1.5)
        print(rr.status_code)
    except OSError as e:
        print("refused:", e)
    try:
        rs: Response = get("https://127.0.0.1:1/", timeout=1.5)
        print(rs.status_code)
    except OSError as e:
        print("tls refused:", e)

    print("done")


if __name__ == "__main__":
    main()
