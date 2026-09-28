"""Async Venom: `async def` handlers served task-per-connection (D45).

The server runs on the main task (accept_async + create_task(serve_conn)); the
clients are plain sync Fang clients on spawned threads so the test is deadlock-free
under CPython too (where socket async mode is a no-op). Completion order is fixed by
the joins, so the output is deterministic in all three worlds.
"""
from __future__ import annotations

import asyncio

from serp_fang import Client
from serp_fang import Response as FangResponse
from serp_fastapi import FastAPI, TestClient, accept_async, listen, listen_port, serve_conn
from serpentine import JoinHandle, Owned, spawn

app = FastAPI()


@app.get("/slow/{ms}")
async def slow(ms: int) -> dict[str, int]:
    await asyncio.sleep(ms / 1000.0)
    return {"slept": ms}


@app.get("/fast")
def fast() -> dict[str, str]:
    return {"hi": "there"}


@app.get("/twice/{n}")
async def twice(n: int) -> dict[str, int]:
    await asyncio.sleep(0)
    return {"n": n * 2}


async def conn_task(conn: int, done: Owned[asyncio.Queue]) -> None:
    n: int = await serve_conn(app, conn)
    await done.put(n)


async def server(fd: int, conns: int) -> int:
    done: asyncio.Queue = asyncio.Queue()
    i: int = 0
    while i < conns:
        conn: int = await accept_async(fd)
        asyncio.create_task(conn_task(conn, done))
        i += 1
    total: int = 0
    j: int = 0
    while j < conns:
        total += int(await done.get())
        j += 1
    return total


def client_thread(port: int, path: str) -> str:
    """One blocking GET on its own thread."""
    c: Client = Client("http://127.0.0.1:" + str(port), [], [], 5.0, False, 20, True, "", "")
    r: FangResponse = c.get(path)
    return path + " -> " + str(r.status_code) + " " + r.text()


def main() -> None:
    tc: TestClient = TestClient(app)
    print("testclient", tc.get("/slow/10").text, tc.get("/fast").text, tc.get("/twice/21").text)
    fd: int = listen("127.0.0.1", 0)
    port: int = listen_port(fd)
    h1: JoinHandle[str] = spawn(client_thread, port, "/slow/300")
    h2: JoinHandle[str] = spawn(client_thread, port, "/slow/100")
    h3: JoinHandle[str] = spawn(client_thread, port, "/fast")
    total: int = asyncio.run(server(fd, 3))
    print(h1.join())
    print(h2.join())
    print(h3.join())
    print("requests served", total)


if __name__ == "__main__":
    main()
