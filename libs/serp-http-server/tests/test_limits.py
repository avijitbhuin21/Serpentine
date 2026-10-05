from serp_http_server import MAX_BODY, BaseHTTPRequestHandler, HTTPServer
from serp_socket import SHUT_WR, create_connection, socket
from serpentine import Ref


def read_all(conn: Ref[socket]) -> bytes:
    """Read until the peer closes."""
    out: bytearray = bytearray(b"")
    while True:
        chunk: bytes = conn.recv(4096)
        if len(chunk) == 0:
            break
        out.extend(chunk)
    return bytes(out)


def main() -> None:
    """A body larger than MAX_BODY is refused with 413 before it is read; normal requests still work."""
    srv: HTTPServer = HTTPServer(("127.0.0.1", 0))
    srv.server_bind()
    port: int = srv.server_port
    print("limit", MAX_BODY)

    big: socket = create_connection(("127.0.0.1", port), 2.0)
    n: int = big.send(b"POST /upload HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999\r\n\r\n")
    big.shutdown(SHUT_WR)
    r1: BaseHTTPRequestHandler = srv.handle_request()
    print(r1.command == "", r1.conn)
    print(read_all(big))
    big.close()

    ok: socket = create_connection(("127.0.0.1", port), 2.0)
    n = ok.send(b"POST /small HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nhello")
    r2: BaseHTTPRequestHandler = srv.handle_request()
    print(r2.command, r2.path, r2.rfile.read())
    r2.send_response(204)
    r2.end_headers()
    r2.finish()
    print(read_all(ok))
    ok.close()
    srv.server_close()
    print("done")


if __name__ == "__main__":
    main()
