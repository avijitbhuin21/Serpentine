"""Graceful-shutdown check server: a Venom app that drains on SIGTERM / Ctrl-Break.

Usage: app <mode> where mode is "async" (one event loop, serve_async) or "threads"
(three serve_on workers sharing the listener). Prints READY <port> once bound and
STOPPED after every serve loop has returned.
"""
from __future__ import annotations

import sys

from serp_fastapi import (FastAPI, JSONResponse, Request, Response, listen, listen_port,
                          serve_async, serve_on, shutdown_install)
from serp_time import sleep
from serpentine import Owned, spawn
from _serp_socket import close as _close


def healthz(req: Owned[Request]) -> Response:
    """Liveness probe."""
    return JSONResponse({"status": "ok"})


def slow(req: Owned[Request]) -> Response:
    """A request that is still in flight when the signal arrives."""
    sleep(1.0)
    return JSONResponse({"slow": "done"})


def build_app() -> FastAPI:
    """Routes used by tools/run_shutdown_check.py."""
    app: FastAPI = FastAPI()
    app.add_api_route("/healthz", healthz, ["GET"])
    app.add_api_route("/slow", slow, ["GET"])
    return app


def worker_entry(fd: int) -> None:
    """One threaded worker serving the shared listener until shutdown."""
    app: FastAPI = build_app()
    serve_on(app, fd)


def main() -> None:
    """Install the signal handler, bind, serve until a shutdown signal, then report."""
    mode: str = sys.argv[1]
    shutdown_install()
    fd: int = listen("127.0.0.1", 0)
    print("READY " + str(listen_port(fd)))
    if mode == "threads":
        h1 = spawn(worker_entry, fd)
        h2 = spawn(worker_entry, fd)
        worker_entry(fd)
        h1.join()
        h2.join()
    else:
        app: FastAPI = build_app()
        serve_async(app, fd)
    _close(fd)
    print("STOPPED")


if __name__ == "__main__":
    main()
