"""serp-venom: `uvicorn.run(app, host=..., port=...)` spelled `serp_uvicorn.run`."""
from __future__ import annotations

from serp_fastapi import FastAPI, listen, serve_async
from serpentine import Owned


def run(app: Owned[FastAPI], host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve `app` forever on this thread (event-loop I/O, HTTP/1.1 keep-alive)."""
    fd: int = listen(host, port)
    serve_async(app, fd)
