"""StreamingResponse: chunked transfer encoding on the wire, joined text in TestClient."""
from __future__ import annotations

from serp_fastapi import (FastAPI, LazyStreamingResponse, Response, StreamingResponse, TestClient,
                          listen, listen_port, serve_async)
from serp_socket import create_connection, socket
from serpentine import Ref, move, spawn
from _serp_socket import close as _close

app = FastAPI()


@app.get("/stream")
def stream() -> Response:
    parts: list[str] = []
    for i in range(3):
        parts.append("line " + str(i) + "\n")
    parts.append("")
    parts.append("héllo\n")
    return StreamingResponse(move(parts), media_type="text/plain")


def row_at(rows: Ref[list[str]], i: int, n: int) -> str | None:
    """The i-th chunk of a lazy stream of n lines, None when done."""
    if i >= n:
        return None
    return rows[i % len(rows)] + ":" + str(i) + "\n"


@app.get("/lazy/{n}")
def lazy(n: int) -> Response:
    rows: list[str] = ["alpha", "beta", "gamma"]
    return LazyStreamingResponse(lambda i: row_at(rows, i, n))


def read_all(conn: Ref[socket]) -> bytes:
    """Read until the peer closes."""
    out: bytearray = bytearray(b"")
    reading: bool = True
    while reading:
        chunk: bytes = b""
        try:
            chunk = conn.recv(4096)
        except OSError as e:
            reading = False
        if len(chunk) == 0:
            reading = False
        out.extend(chunk)
    return bytes(out)


def client(port: int) -> bytes:
    """Two raw HTTP/1.1 requests; returns both responses' bytes after their heads."""
    out: bytearray = bytearray(b"")
    for path in ["/stream", "/lazy/5"]:
        c: socket = create_connection(("127.0.0.1", port), 3.0)
        n: int = c.send(("GET " + path + " HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n").encode("utf-8"))
        raw: bytes = read_all(c)
        c.close()
        sep: int = raw.find(b"\r\n\r\n")
        head: str = raw[0:sep].decode("utf-8").lower()
        out.extend(("chunked=" + str(head.find("transfer-encoding: chunked") >= 0) + " ").encode("utf-8"))
        out.extend(raw[sep + 4:len(raw)])
        out.extend(b"|")
    return bytes(out)


def main() -> None:
    tc = TestClient(app)
    r = tc.get("/stream")
    print(r.status_code, r.headers.get("content-type"))
    print(r.text)
    print(tc.get("/lazy/4").text)
    print(len(tc.get("/lazy/0").text))
    fd: int = listen("127.0.0.1", 0)
    port: int = listen_port(fd)
    h = spawn(client, port)
    serve_async(app, fd, 2)
    raw: bytes = h.join()
    _close(fd)
    print(raw)


if __name__ == "__main__":
    main()
