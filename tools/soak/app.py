"""Soak-test server: a small Venom app served by N blocking workers on one listening socket.

Usage: app <port> <workers>
"""
from __future__ import annotations

import sys

from serp_fastapi import FastAPI, JSONResponse, PlainTextResponse, Request, Response, listen, listen_port, serve_on
from serpentine import Owned, PyVal, spawn


def read_json(req: Owned[Request]) -> Response:
    """Tiny JSON body."""
    return JSONResponse({"message": "Hello, World!", "n": 42})


def read_item(req: Owned[Request]) -> Response:
    """Path parameter echo."""
    return JSONResponse({"item_id": req.path_params["item_id"]})


def read_kb(req: Owned[Request]) -> Response:
    """About 1 KB of text, rebuilt per request to exercise allocation."""
    out: str = ""
    i: int = 0
    while i < 64:
        out += "0123456789abcdef"
        i += 1
    return PlainTextResponse(out)


def echo(req: Owned[Request]) -> Response:
    """Parse the JSON body and send it back."""
    data: PyVal = req.json()
    return JSONResponse(data, 200)


def build_app() -> FastAPI:
    """Routes used by tools/run_soak.py."""
    app: FastAPI = FastAPI()
    app.add_api_route("/json", read_json, ["GET"])
    app.add_api_route("/items/{item_id}", read_item, ["GET"])
    app.add_api_route("/kb", read_kb, ["GET"])
    app.add_api_route("/echo", echo, ["POST"])
    return app


def worker_entry(fd: int) -> None:
    """One worker: its own app, serving the shared listener forever."""
    app: FastAPI = build_app()
    serve_on(app, fd)


def main() -> None:
    """Bind, announce the port, and start the workers."""
    port: int = int(sys.argv[1])
    workers: int = int(sys.argv[2])
    fd: int = listen("127.0.0.1", port)
    print("READY " + str(listen_port(fd)))
    i: int = 1
    while i < workers:
        h = spawn(worker_entry, fd)
        i += 1
    worker_entry(fd)


if __name__ == "__main__":
    main()
