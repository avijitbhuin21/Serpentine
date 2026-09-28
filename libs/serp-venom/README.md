# serp-venom — Venom, Serpentine's FastAPI

A FastAPI drop-in that compiles natively with `serp build` and dual-runs under CPython.
Import name: `serp_fastapi` (plus `serp_uvicorn.run`).

```python
from serp_fastapi import FastAPI, HTTPException
from serp_molt import BaseModel

app = FastAPI()


class Item(BaseModel):
    name: str
    price: float


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None) -> PyVal:
    if item_id == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item_id": item_id, "q": q}


@app.post("/items", status_code=201)
def create_item(item: Item) -> Item:
    return item
```

Test it with `TestClient(app)`; serve it with `serp_uvicorn.run(app, host="127.0.0.1", port=8000)`
(an event loop: readiness-polled non-blocking sockets, one thread multiplexing every
connection). Multi-core: `listen(host, port) -> fd`, then one `serve_async(app, fd)` loop per
worker thread sharing the listener (`spawn(worker, fd)`), each worker building its own app.

## Covered surface

- Module-level `app = FastAPI(title=..., version=...)`; `@app.get/post/put/delete/patch/head/
  options(path, status_code=...)` and `@app.api_route(path, methods=[...])`; `add_api_route`.
  Routes match in registration order; `{param}` segments are percent-decoded; automatic
  `404 {"detail": "Not Found"}` / `405 {"detail": "Method Not Allowed"}`.
- **Parameter injection by name and type**: `{param}` path parameters and query parameters as
  `int`/`str`/`float`/`bool` (with defaults), `T | None` optionals, a serp_molt model
  parameter as the JSON body, or the raw `req: Owned[Request]`. Bad or missing values produce
  FastAPI's 422 envelope (`{"detail": [{"type": "int_parsing", "loc": ["path", "item_id"],
  "msg": ..., "input": ...}]}`); body validation errors carry pydantic's error list with
  `["body", ...]` locations.
- **Return values**: dicts/lists/scalars/`PyVal` are serialized as JSON (compact separators like
  FastAPI); a model or `list[Model]` is `model_dump()`ed; `None` sends `null` (an empty body on
  204); a `Response` passes through. `status_code=` on the decorator applies to converted
  returns.
- **Dependencies and routers**: `param: T = Depends(fn)` injects the result of a module-level
  function whose own parameters are injected the same way (nested `Depends` work; an
  `HTTPException` raised inside a dependency short-circuits). `APIRouter(prefix=...)` with the
  same decorators, mounted by a module-level `app.include_router(router, prefix=...)`;
  module-level `app.add_api_route(...)` statements are honored too.
- `Request`: `method`, `url`, `path_params`, `query_params`, `headers`, `body`, `json()`.
- `Response(content, status_code, headers, media_type)` plus `JSONResponse`,
  `PlainTextResponse`, `HTMLResponse`, `RedirectResponse` (all accept `status_code=`,
  `headers=`, `media_type=`).
- `HTTPException(status_code=404, detail="...")` → `404 {"detail": "..."}` (default detail is the
  HTTP phrase); any other uncaught handler error → `500 Internal Server Error`.
- `TestClient(app)` with `get/post/put/delete/patch/head/options/request`, `json=`, `params=`,
  `headers=`; responses expose `.status_code`, `.text`, `.json()`, `.headers`.

## How the decorators work

`@app.get(...)` and the module-level `app` are lowered at build time (docs/DECISIONS.md D41):
the compiler generates a `_serp_app_app()` factory that constructs the app and registers each
route with a synthesized `(Request) -> Response` endpoint that performs the parameter
extraction above, and every use of `app` in a function becomes a call to that factory. Under
CPython the same file runs as ordinary Python — the `serpentine.registrar` shim wraps
`FastAPI.get` and builds the identical endpoint from the handler's annotations.

## Divergences from FastAPI

- `JSONResponse` and friends are factory functions returning `Response` — annotate handlers
  that return them as `-> Response`.
- `HTTPException(status_code=, detail=)`: `exc.status_code`, `exc.detail` and `str(exc)`
  (`"404: detail"`) work inside `except HTTPException as exc:`; other attributes (`headers`)
  are not carried.
- `app` is a build-time factory, not a shared mutable object: configure it at module level
  (decorators, `app.include_router(...)`, `app.add_api_route(...)`) — mutating it from inside
  a function does not persist, and do not rely on identity.
- No middleware, `BackgroundTasks`, class/`yield` dependencies, `StreamingResponse`,
  WebSockets, cookies/forms, or automatic `/openapi.json` (build one by hand from
  `Model.model_json_schema()`, see `tests/test_molt_body.py`).
- `async def` handlers are awaited (D45): `TestClient`/`serve_on`/`serve_async` run them to
  completion inline; to make them *concur*, serve task-per-connection:
  `conn = await accept_async(fd)` then `asyncio.create_task(conn_task(conn))` with
  `await serve_conn(app, conn)` inside the task (each task references the module-level
  `app`, which rebuilds it — route tables never cross tasks). `request.json()` is synchronous.
- Handlers run to completion on the event loop; each worker builds its own app — route tables
  never cross threads.
