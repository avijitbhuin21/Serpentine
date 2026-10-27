"""Venom middleware, CORS and BackgroundTasks through TestClient (FastAPI spellings)."""
from __future__ import annotations

from serp_fastapi import (BackgroundTasks, CORSMiddleware, FastAPI, HTTPException, JSONResponse,
                          Request, Response, TestClient, ClientResponse)
from serpentine import Ref

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["https://app.example"],
                   allow_methods=["GET", "POST"], allow_headers=["X-Token"],
                   allow_credentials=True, expose_headers=["X-Trace"])


@app.middleware("http")
def add_timing(request: Request, call_next):
    response = call_next(request)
    response.headers["x-inner"] = "timing"
    return response


@app.middleware("http")
def guard(request: Request, call_next):
    if request.url == "/blocked":
        return JSONResponse({"detail": "blocked by middleware"}, 403)
    response = call_next(request)
    response.headers["x-outer"] = "guard"
    return response


def note(msg: str) -> None:
    """A background side effect, logged to stdout after the response exists."""
    print("background:", msg)


@app.get("/hello/{name}")
def hello(name: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    background_tasks.add_task(lambda: note("greeted " + name))
    background_tasks.add_task(lambda: note("second task"))
    print("handler ran for", name)
    return {"hello": name}


@app.get("/boom")
def boom() -> dict[str, str]:
    raise HTTPException(status_code=418, detail="teapot")


@app.post("/items")
def create(name: str) -> dict[str, str]:
    return {"created": name}


def show(label: str, r: Ref[ClientResponse]) -> None:
    """Print status, body and the headers this test cares about, in a fixed order."""
    keys: list[str] = ["x-inner", "x-outer", "access-control-allow-origin",
                       "access-control-allow-credentials", "access-control-expose-headers",
                       "access-control-allow-methods", "access-control-allow-headers",
                       "access-control-max-age", "vary"]
    parts: list[str] = []
    for k in keys:
        v: str | None = r.headers.get(k)
        if v is not None:
            parts.append(k + "=" + v)
    print(label, r.status_code, r.text, "|", "; ".join(parts))


def main() -> None:
    client = TestClient(app)
    show("plain", client.get("/hello/ada"))
    show("cors", client.get("/hello/bob", headers={"Origin": "https://app.example"}))
    show("other-origin", client.get("/hello/eve", headers={"Origin": "https://evil.example"}))
    show("blocked", client.get("/blocked"))
    show("boom", client.get("/boom"))
    show("missing", client.get("/nope"))
    show("preflight", client.options("/items", headers={
        "Origin": "https://app.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Token, Content-Type"}))
    show("preflight-bad", client.options("/items", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "X-Other"}))
    show("post", client.post("/items", params={"name": "pen"},
                             headers={"Origin": "https://app.example"}))


if __name__ == "__main__":
    main()
