from serp_fastapi import (ClientResponse, FastAPI, HTTPException, JSONResponse,
                          PlainTextResponse, RedirectResponse, Request, Response,
                          TestClient, handle_once, listen, listen_port, serve_async,
                          serve_on)
from serp_http_server import HTTPServer
from serp_socket import create_connection, socket
from serpentine import Owned, PyVal, Ref, move, spawn


def _q(params: Ref[dict[str, str]], k: str) -> str:
    v: str | None = params.get(k)
    if v is not None:
        return v
    return ""


def read_root(req: Owned[Request]) -> Response:
    return JSONResponse({"message": "Hello World"})


def read_item(req: Owned[Request]) -> Response:
    item_id: str = req.path_params["item_id"]
    q: str = _q(req.query_params, "q")
    return JSONResponse({"item_id": item_id, "q": q})


def create_item(req: Owned[Request]) -> Response:
    data: PyVal = req.json()
    return JSONResponse(data, 201)


def find_user(req: Owned[Request]) -> Response:
    uid: str = req.path_params["user_id"]
    if uid == "0":
        raise HTTPException(status_code=404, detail="User not found")
    if uid == "boom":
        raise ValueError("handler exploded")
    return PlainTextResponse("user " + uid)


def go_away(req: Owned[Request]) -> Response:
    return RedirectResponse("/new-home")


def build_app() -> FastAPI:
    app: FastAPI = FastAPI()
    app.add_api_route("/", read_root, ["GET"])
    app.add_api_route("/items/{item_id}", read_item, ["GET"])
    app.add_api_route("/items", create_item, ["POST"])
    app.add_api_route("/users/{user_id}", find_user, ["GET"])
    app.add_api_route("/old-home", go_away, ["GET"])
    return app


def client_section() -> None:
    client: TestClient = TestClient(build_app())
    r1: ClientResponse = client.get("/")
    print(r1.status_code, r1.text)
    print(r1.json())
    print(_q(r1.headers, "content-type"), _q(r1.headers, "content-length"))

    r2: ClientResponse = client.get("/items/42?q=hello%20world&n=2")
    print(r2.status_code, r2.text)

    r3: ClientResponse = client.get("/items/caf%C3%A9")
    print(r3.status_code, r3.text)

    r4: ClientResponse = client.post("/items", json={"name": "hammer", "price": 9.5, "tags": ["tool"]})
    print(r4.status_code, r4.text)
    print(r4.json()["name"], r4.json()["price"])

    r5: ClientResponse = client.get("/nope")
    print(r5.status_code, r5.text)

    r6: ClientResponse = client.delete("/items/7")
    print(r6.status_code, r6.text)

    r7: ClientResponse = client.get("/users/0")
    print(r7.status_code, r7.text)

    r8: ClientResponse = client.get("/users/12")
    print(r8.status_code, r8.text)

    r9: ClientResponse = client.get("/users/boom")
    print(r9.status_code, r9.text)

    r10: ClientResponse = client.get("/old-home")
    print(r10.status_code, _q(r10.headers, "location"))


def read_all(conn: Ref[socket]) -> bytes:
    out: bytearray = bytearray(b"")
    while True:
        chunk: bytes = conn.recv(4096)
        if len(chunk) == 0:
            break
        out.extend(chunk)
    return bytes(out)


def server_section() -> None:
    app: FastAPI = build_app()
    srv: HTTPServer = HTTPServer(("127.0.0.1", 0))
    srv.server_bind()
    port: int = srv.server_port
    print(port > 0)

    cli: socket = create_connection(("127.0.0.1", port), 2.0)
    n: int = cli.send(b"GET /items/9?q=fast HTTP/1.1\r\nHost: x\r\n\r\n")
    handle_once(app, srv)
    print(read_all(cli))
    cli.close()

    cli2: socket = create_connection(("127.0.0.1", port), 2.0)
    payload: bytes = b'{"kind": "venom", "n": 3}'
    head: str = ("POST /items HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                 "Content-Length: " + str(len(payload)) + "\r\n\r\n")
    n = cli2.send(head.encode("utf-8") + payload)
    handle_once(app, srv)
    print(read_all(cli2))
    cli2.close()

    cli3: socket = create_connection(("127.0.0.1", port), 2.0)
    n = cli3.send(b"GET /missing HTTP/1.1\r\nHost: x\r\n\r\n")
    handle_once(app, srv)
    print(read_all(cli3))
    cli3.close()

    srv.server_close()


def worker(fd: int) -> None:
    app: FastAPI = build_app()
    serve_on(app, fd, 2)


def _read_response(conn: Ref[socket]) -> str:
    raw: bytearray = bytearray(b"")
    clen: int = -1
    body_at: int = -1
    while True:
        if body_at >= 0 and len(raw) >= body_at + clen:
            break
        chunk: bytes = conn.recv(4096)
        if len(chunk) == 0:
            break
        raw.extend(chunk)
        if body_at < 0:
            sep: int = bytes(raw).find(b"\r\n\r\n")
            if sep >= 0:
                body_at = sep + 4
                head: str = bytes(raw)[0:sep].decode("utf-8")
                for line in head.split("\r\n"):
                    low: str = line.lower()
                    if low.startswith("content-length:"):
                        clen = int(line[15:len(line)].strip())
                if clen < 0:
                    clen = 0
    return bytes(raw).decode("utf-8")


def threaded_section() -> None:
    fd: int = listen("127.0.0.1", 0)
    port: int = listen_port(fd)
    h1 = spawn(worker, fd)
    h2 = spawn(worker, fd)

    c1: socket = create_connection(("127.0.0.1", port), 5.0)
    n: int = c1.send(b"GET /items/1?q=one HTTP/1.1\r\nHost: x\r\n\r\n")
    r1: str = _read_response(c1)
    print(r1.replace("\r\n", " | "))
    n = c1.send(b"GET /users/7 HTTP/1.1\r\nHost: x\r\n\r\n")
    r2: str = _read_response(c1)
    print(r2.replace("\r\n", " | "))
    c1.close()

    c2: socket = create_connection(("127.0.0.1", port), 5.0)
    n = c2.send(b"GET /items/2 HTTP/1.1\r\nHost: x\r\n\r\n")
    r3: str = _read_response(c2)
    print(r3.replace("\r\n", " | "))
    n = c2.send(b"GET /nope HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    r4: str = _read_response(c2)
    print(r4.replace("\r\n", " | "))
    c2.close()

    h1.join()
    h2.join()
    print("threads joined")


def async_worker(fd: int) -> None:
    app: FastAPI = build_app()
    serve_async(app, fd, 4)


def async_section() -> None:
    fd: int = listen("127.0.0.1", 0)
    port: int = listen_port(fd)
    h = spawn(async_worker, fd)

    c1: socket = create_connection(("127.0.0.1", port), 5.0)
    c2: socket = create_connection(("127.0.0.1", port), 5.0)

    n: int = c1.send(b"GET /items/first HTTP/1.1\r\nHost: x\r\n\r\n")
    print(_read_response(c1).replace("\r\n", " | "))
    n = c2.send(b"GET /items/second HTTP/1.1\r\nHost: x\r\n\r\n")
    print(_read_response(c2).replace("\r\n", " | "))
    n = c1.send(b"GET /users/9 HTTP/1.1\r\nHost: x\r\n\r\n")
    print(_read_response(c1).replace("\r\n", " | "))
    n = c2.send(b"GET /nope HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    print(_read_response(c2).replace("\r\n", " | "))

    c1.close()
    c2.close()
    h.join()
    print("async loop done (1 worker, 2 interleaved connections)")


def main() -> None:
    client_section()
    server_section()
    threaded_section()
    async_section()
    print("done")


if __name__ == "__main__":
    main()
