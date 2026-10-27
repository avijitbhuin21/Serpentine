"""Graceful shutdown + slowloris guard for the event-loop server (serve_async).

A client thread drives the scenario against the server running on the main thread:
a request that trickles in slower than the read deadline is dropped; after
shutdown_request() the listener stops being served, an idle keep-alive connection
is closed, and a request that was already in flight still completes before
serve_async returns.
"""
from __future__ import annotations

from serp_fastapi import FastAPI, listen, listen_port, serve_async, shutdown_request, shutdown_requested
from serp_socket import create_connection, socket
from serp_time import sleep
from serpentine import Ref, spawn
from _serp_socket import close as _close

app = FastAPI()


@app.get("/ping")
def ping() -> dict[str, bool]:
    return {"pong": True}


def read_all(conn: Ref[socket]) -> bytes:
    """Read until the peer closes (a reset counts as closed)."""
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


def client(port: int) -> str:
    """Run the slowloris, drain and idle-close checks; return a summary line."""
    report: list[str] = []
    slow: socket = create_connection(("127.0.0.1", port), 3.0)
    n: int = slow.send(b"GET /ping HTTP/1.1\r\nHost: x\r\n")
    sleep(1.5)
    report.append("slowloris-dropped=" + str(len(read_all(slow)) == 0))
    slow.close()

    a: socket = create_connection(("127.0.0.1", port), 3.0)
    n = a.send(b"GET /ping HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    ra: bytes = read_all(a)
    report.append("normal=" + str(ra.startswith(b"HTTP/1.1 200") and ra.endswith(b'{"pong":true}')))
    a.close()

    idle: socket = create_connection(("127.0.0.1", port), 3.0)
    inflight: socket = create_connection(("127.0.0.1", port), 3.0)
    n = inflight.send(b"GET /ping HTTP/1.1\r\nHost: x\r\nConnection: close\r\n")
    sleep(0.2)
    shutdown_request()
    sleep(0.3)
    report.append("idle-closed=" + str(len(read_all(idle)) == 0))
    idle.close()
    n = inflight.send(b"\r\n")
    rb: bytes = read_all(inflight)
    report.append("inflight-drained=" + str(rb.startswith(b"HTTP/1.1 200")))
    inflight.close()
    return " ".join(report)


def main() -> None:
    fd: int = listen("127.0.0.1", 0)
    port: int = listen_port(fd)
    print("requested before:", shutdown_requested())
    h = spawn(client, port)
    serve_async(app, fd, -1, 0.8)
    _close(fd)
    print("serve_async returned; requested:", shutdown_requested())
    print(h.join())


if __name__ == "__main__":
    main()
