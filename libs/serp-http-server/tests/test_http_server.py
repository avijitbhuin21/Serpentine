from serp_http_server import BaseHTTPRequestHandler, HTTPServer
from serp_socket import SHUT_WR, create_connection, socket
from serpentine import Ref


def read_all(conn: Ref[socket]) -> bytes:
    out: bytearray = bytearray(b"")
    while True:
        chunk: bytes = conn.recv(4096)
        if len(chunk) == 0:
            break
        out.extend(chunk)
    return bytes(out)


def main() -> None:
    srv: HTTPServer = HTTPServer(("127.0.0.1", 0))
    srv.server_bind()
    port: int = srv.server_port
    print(port > 0, srv.server_name)

    cli: socket = create_connection(("127.0.0.1", port), 2.0)
    n: int = cli.send(b"GET /hello?name=world HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Test: Yes\r\n\r\n")
    req: BaseHTTPRequestHandler = srv.handle_request()
    print(req.command, req.path, req.request_version)
    print(req.headers.get("x-test"), req.headers.get("X-Test"), req.headers.get("missing") == "")
    print(req.headers.get("missing", "fallback"))
    req.send_response(200)
    req.send_header("Content-Type", "text/plain")
    req.send_header("Content-Length", "11")
    req.send_header("Connection", "close")
    req.end_headers()
    w: int = req.wfile.write(b"hello world")
    req.finish()
    print(read_all(cli))
    cli.close()

    cli2: socket = create_connection(("127.0.0.1", port), 2.0)
    payload: bytes = b'{"name": "serpentine", "wave": 4}'
    reqhead: str = ("POST /submit HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                    "Content-Length: " + str(len(payload)) + "\r\n\r\n")
    n = cli2.send(reqhead.encode("utf-8") + payload)
    req2: BaseHTTPRequestHandler = srv.handle_request()
    print(req2.command, req2.path)
    print(req2.headers.get("content-type"))
    print(req2.rfile.read(4))
    print(req2.rfile.read())
    req2.send_response(201, "Created")
    req2.send_header("Content-Length", "12")
    req2.end_headers()
    w = req2.wfile.write(b'{"ok": true}')
    req2.finish()
    print(read_all(cli2))
    cli2.close()

    cli3: socket = create_connection(("127.0.0.1", port), 2.0)
    n = cli3.send(b"NONSENSE\r\n\r\n")
    cli3.shutdown(SHUT_WR)
    req3: BaseHTTPRequestHandler = srv.handle_request()
    print(req3.command == "", req3.conn)
    print(read_all(cli3))
    cli3.close()

    cli4: socket = create_connection(("127.0.0.1", port), 2.0)
    n = cli4.send(b"GET /missing HTTP/1.1\r\nHost: x\r\n\r\n")
    req4: BaseHTTPRequestHandler = srv.handle_request()
    req4.send_error(404)
    print(read_all(cli4))
    cli4.close()

    srv.server_close()
    print("done")


if __name__ == "__main__":
    main()
