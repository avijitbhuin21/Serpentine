from __future__ import annotations

import asyncio

from _serp_socket import accept, close, listen, local_port, recv, send_all
from serp_fang import AsyncClient, Response
from serp_time import sleep
from serpentine import JoinHandle, spawn


def handle(c: int) -> None:
    """Serve one connection: /sleep/<ms>/<tag> waits then echoes the tag."""
    raw: bytes = b""
    while raw.find(b"\r\n\r\n") < 0:
        chunk: bytes = recv(c, 65536)
        if len(chunk) == 0:
            break
        raw = raw + chunk
    line: str = raw.split(b"\r\n")[0].decode("utf-8")
    path: str = line.split(" ")[1]
    parts: list[str] = path.split("/")
    ms: int = int(parts[2])
    tag: str = parts[3]
    sleep(ms / 1000.0)
    body: str = "hello " + tag
    head: str = ("HTTP/1.1 200 OK\r\ncontent-type: text/plain\r\ncontent-length: "
                 + str(len(body)) + "\r\nconnection: close\r\n\r\n")
    n: int = send_all(c, (head + body).encode("utf-8"), 0)
    close(c)


def serve(fd: int, count: int) -> int:
    """Accept `count` connections, one handler thread each."""
    served: int = 0
    while served < count:
        c: int = accept(fd)
        h: JoinHandle[None] = spawn(handle, c)
        served += 1
    return served


async def fetch(port: int, path: str) -> str:
    out: str = ""
    async with AsyncClient(base_url="http://127.0.0.1:" + str(port), timeout=5.0) as client:
        r: Response = await client.get(path)
        out = str(r.status_code) + " " + r.text() + " " + r.header("content-type")
    return out


async def post_it(port: int) -> str:
    client: AsyncClient = AsyncClient(base_url="http://127.0.0.1:" + str(port))
    r: Response = await client.post("/sleep/0/post", b"payload", "text/plain")
    await client.aclose()
    return str(r.status_code) + " " + r.text()


async def amain(port: int) -> None:
    rs: list[str] = await asyncio.gather(fetch(port, "/sleep/300/a"),
                                         fetch(port, "/sleep/100/b"),
                                         fetch(port, "/sleep/0/c"))
    for s in rs:
        print(s)
    print(await post_it(port))


def main() -> None:
    fd: int = listen("127.0.0.1", 0)
    port: int = local_port(fd)
    h: JoinHandle[int] = spawn(serve, fd, 4)
    asyncio.run(amain(port))
    print("served", h.join())
    close(fd)


if __name__ == "__main__":
    main()
