# Venom (`serp-venom`) — roadmap

> Per-library roadmap. One-line status lives in [../libraries.md](../libraries.md); this
> file is the working checklist. Two independent tracks: **A = performance** (goal: axum
> parity, then past it) and **B = drop-in `fastapi` parity** (goal: ✅ not ≈).
> Numbered blockers at the bottom — every `[L]` item names the blocker that gates it.
>
> Markers: `[x]` done · `[ ]` open · **[P]** library-only work · **[R]** needs runtime
> (`prelude.rs`/`rt.rs`) work · **[L]** language-blocked, see blockers.

## Where we are (measured 2026-08-29)

Interleaved A/B against axum, `/json` keep-alive, i7-8750H, server pinned to 3 physical
cores, 3 passes per case. Same-session ratios only — absolutes from this box are not
quotable. Raw data: `.rustic/tmp/perf/results_v3.jsonl`, summary `sum_v2.py`.

| | Venom | axum | ratio |
|---|---|---|---|
| 1 worker / 16 conns | 28.6k rps (42.3 µs/req) | 34.1k rps (35.1 µs/req) | **1.19x behind** |
| 3 workers / 64 conns | **51.4k rps** (66.4 µs/req) | 40.9k rps (54.6 µs/req) | **0.80x — Venom ahead** |

Scaling 1w→3w: **Venom 1.80x, axum 1.20x**.

**Targets.** T1 ≥30k rps — **met**. T2 axum parity — **met at w3/c64 (Venom is 25% faster);
w1/c16 is 1.19x behind, inside the ≤1.2x band**. T3 beat axum on the same box — **met at
w3/c64**, open at w1. CPU/req is still 1.2x axum's, so the win at w3 comes from scaling,
not from cheaper requests — that remains the honest headline.

### What moved it (2026-08-29)

Previous state was 1.72x behind at w1 and 1.68x at w3. Three changes, in order of effect:

1. **`pyval_json` runtime builtin** — serializing `{"message": "Hello, World!"}` cost
   **13.7 µs**, 32% of the entire per-request budget, because `serp_json._escape_string`
   walked the string one `Rc<str>` character at a time. Moved into `prelude.rs`
   (`json_write`/`json_escape`), exposed as a `pyval_json(v, ensure_ascii, compact)`
   builtin next to `pyval_kind`. **13.73 → 0.82 µs (16.7x).** `app._handle` 15.6 → 3.2 µs;
   `_serve_buffered` end-to-end 31.7 → 22.9 µs (`.rustic/tmp/perf/micro.py`).
2. **Thread-local socket-handle cache** — every `recv`/`send`/`poll_ready` took the global
   `SOCKS` RwLock in read mode, i.e. an atomic RMW on one cache line shared by all workers.
   Each thread now memoizes resolved `SockRef`s behind a relaxed `SOCK_EPOCH` load, and
   `close` bumps the epoch (and shuts the socket down explicitly, so a cached ref cannot
   keep an fd alive). This is what took 1w→3w scaling from 1.55x to 1.80x.
3. **Event-loop bookkeeping** — per-connection `dict[int, int]` slot map replaces the
   `_index_of` linear scan per ready handle; the packed poll array is patched on accept and
   only rebuilt on close; the response head is one precomposed `bytes` literal per status
   (`_status_head`) instead of four encodes; JSON responses use compact separators.

---

# Track A — Performance

## A0. Shipped 2026-07-26 (audit trail)

- [x] **[R]** Socket table `Mutex` → `RwLock` + `SOCK_FREE` slot free-list. Was the
      single biggest problem: every poll/recv/send/accept serialized on one global lock,
      which is why throughput *fell* as workers were added.
- [x] **[R]** `sock_get_many` — `poll_ready` resolves the whole poll set under one read
      lock instead of one lock acquisition per handle per iteration.
- [x] **[R]** `serp_sock_send` no longer uses `write_all` on non-blocking sockets
      (silently truncated responses — a correctness bug, reproduced).
- [x] **[R]** New `send_all` primitive with `POLLOUT` parking; backs `socket.sendall`,
      `serp_http_server` and Venom.
- [x] **[R]** `TCP_NODELAY` on every accepted socket (runtime + CPython delegate).
- [x] **[P]** Batch accept ≤64 per wake; drain-recv while the 64 KB buffer fills.
- [x] **[P]** One buffer copy per wake (was 3); head decoded + split once and shared by
      both parsers (was 2 independent splits); response built in a `bytearray`.

## A1. Kill the remaining per-wake O(conns) work — **DONE 2026-08-29**

- [x] **[P]** Replace the `_index_of(conns, h)` linear scan **per ready handle** with a
      `slot: dict[int, int]` handle→index map; removal is a swap-with-last that patches
      the map instead of shifting every later index.
- [x] **[P]** Stop rebuilding `all_fds` + `_pack()` from scratch every iteration — the
      packed poll array is kept, appended to on accept (`_pack1`), and only rebuilt when a
      connection closes (`dirty`).
- [ ] **[P]** Reuse the per-connection `bytearray` instead of `bufs[idx] = bytearray(b"")`
      after every request. **Blocked on a language addition:** `bytearray` has no
      `clear()` (only `append`/`extend`/`hex`/`decode`), so the buffer cannot be emptied
      in place. One allocation per request remains.
- [ ] **[R]** Let `poll_ready` return only the ready subset in a form that needs no
      `_unpack` round-trip per wake.

## A2. Persistent readiness registration — the top structural item

`WSAPoll`/`poll(2)` are O(n) per call *by design*: the whole interest set crosses the
syscall boundary every wake. axum/tokio register once and get O(ready) notifications.

- [ ] **[R]** epoll (Linux) / kqueue (macOS) / IOCP or `WSAPoll`-with-registration
      (Windows) behind the existing `poll_ready` shape so Venom needs no rewrite.
- [ ] **[R]** Decide the Windows path explicitly — IOCP is completion-based, not
      readiness-based, so it does not slot into the current API. Needs a decision
      (**D16**, see blockers).
- Est. gain: this is what closes most of the remaining 1.5x, and it is what makes
  hundreds-to-thousands of connections cheap rather than merely survivable.

## A3. Response fast path

- [x] **[P]** Cache the status line + fixed header block per status instead of rebuilding
      the byte string per response — `_status_head(code)` returns one precomposed
      `b"HTTP/1.1 200 OK\r\ncontent-type: "` literal (was `bytearray(b"HTTP/1.1 ")` plus
      an `_status_line().encode()` plus two more extends). Measured head build 3.44 → 3.35
      µs/op; the remaining cost is `str(len(payload))` and the per-response `bytearray`.
- [ ] **[P]** Precompute `content-length` digits for small bodies (int→str per response
      today). Wants a module-level lookup table — gated on **LB1**.
- [ ] **[R]** `writev`/scatter send so headers and body go out without being concatenated
      into one buffer first.
- [ ] **[P]** Add a `Date` header — currently absent, and RFC 9110 says a server SHOULD
      send it. Deliberately **not** added yet: it costs per-response work and axum does not
      send one either, so adding it before the A/B was settled would have skewed the
      comparison. Do it with a once-per-second cache.

## A4. JSON fast path — **DONE 2026-08-29**

- [x] **[P/R]** Small-dict serialization fast path. Root cause was not dict size but
      per-character `Rc<str>` allocation in `serp_json._escape_string`. `dumps()` now calls
      the `pyval_json` builtin (`prelude.rs::json_write`) whenever `sort_keys` is false;
      the pure-Serpentine `_dump` remains for the `sort_keys=True` path and as the
      readable reference. **13.73 → 0.82 µs/op.**
- [x] **[P]** Emit compact separators (`,`/`:`) — matches FastAPI *and* is fewer bytes.
      `serp_json.dumps(..., compact=True)`; `JSONResponse` uses it. (`compact=` is an
      additive divergence from stdlib `json`: `separators=` needs a tuple default, and
      defaults must be literal constants.)

## A5. Accept + listener fairness

- [ ] **[R]** `SO_REUSEPORT` (Unix) / per-worker listener sockets so workers stop
      contending on one shared listener. Measured symptom: `w4 c1 = 8.6k` vs
      `w1 c1 = 14.9k` — four workers fighting over one connection.
- [ ] **[P]** Tune/justify the accept batch cap (64 today, chosen not measured).

## A6. Connection lifecycle

- [ ] **[P]** HTTP/1.1 **pipelining** — the loop already drains multiple requests per
      buffer, but the framing is documented as no-pipelining; make it explicit and tested.
- [ ] **[P]** Idle-connection timeout + max-connections cap. Today a client that opens and
      never speaks holds a slot forever.
- [ ] **[P]** Graceful shutdown (stop accepting, drain in-flight, close).

## A7. Measurement infrastructure — gates every claim above

- [ ] Re-benchmark on **fixed-clock hardware**. This box gave a 3.3x spread on identical
      runs, and the *unchanged* axum binary measured 43–50 µs/req in one session and
      23–26 µs/req in another.
- [ ] Promote the harness out of `.rustic/tmp/perf/` into a committed benchmark and wire a
      regression gate into CI (see [../guides/benchmarks.md](../guides/benchmarks.md)).
- [ ] Publish numbers in the README **only** after the above. The current
      `libs/serp-venom/README.md` figures are stale.

## A8. Beyond parity (T3)

- [ ] **[R]** io_uring on Linux.
- [ ] **[P]** Per-worker arena/pool for request scratch so steady state is allocation-free.
- [ ] **[L]** Zero-copy request parsing — parse in place out of the connection buffer
      instead of materializing `bytes`/`str`. Needs **LB6** (borrowed slices/views).

---

# Track B — Drop-in `fastapi` parity

**Tracker line flipped to `✅ fastapi` on 2026-09-07.** D41 (module-level object bindings +
`@registrar` decorators with synthesized endpoints) cleared LB1 and LB2 for the route surface;
D42 cleared the `HTTPException(status_code=, detail=)` gap. Everything still open below is
either library work or gated on LB3/LB4/LB5/LB8. Test: `tests/test_dropin.py`.

## B1. Decorator registration — `@app.get("/x")` — **DONE (D41)**

- [x] **[L→done]** `@app.get(...)` / `@app.post(...)` / put/delete/patch/head/options /
      `@app.api_route(path, methods=[...])` on a module-level `app = FastAPI()`. The binding is a
      build-time factory (not a shared mutable global — see D41 for the consequence).
- [x] **[P]** `APIRouter(prefix=)` + `app.include_router(router, prefix=)` — a second D41
      binding; module-level `app.include_router(...)`/`app.add_api_route(...)` statements are
      emitted into the app factory in source order.

## B2. Handler signatures — parameter injection — **DONE (D41)**

- [x] **[L→done]** Path/query params by name and type (`int`/`str`/`float`/`bool`, defaults,
      `T | None`), FastAPI's 422 envelope with pydantic-shaped `int_parsing`/`missing`/... errors.
- [x] **[L→done]** Request-body models: `def create(item: Item)` for any serp_molt model;
      failures return `{"detail": [...]}` with `["body", ...]` locations.
- [x] **[L→done]** Returning a model / `list[Model]` / dict / list / scalar / `None` instead of a
      `Response`; `status_code=` on the decorator applies to converted returns.
- [x] **[L→done]** `Depends(fn)` for module-level function dependencies, nested arbitrarily
      (each dependency's own parameters are injected the same way; an `HTTPException` raised
      inside a dependency short-circuits). Class dependencies (`Depends(CommonParams)`) and
      `yield` dependencies are not supported.
- [ ] **[P]** `Query()`/`Path()`/`Header()`/`Body()` markers with validation — the extraction
      convention is in place; the marker surface is library + frontend work.
- [ ] **[P]** `list[int]` query params, `list[Model]` bodies, `dict` bodies.

## B3. Async handlers that actually concur

- [x] **[L]** `async def` handlers — **DONE 2026-09-07 (D45)**: awaited in `_handle_async`,
      served task-per-connection via `accept_async` + `serve_conn`; `TestClient` and the
      blocking servers run them inline through `block_on`. Test: `tests/test_async_venom.py`.
- [x] **[P]** README documents the pattern and the CPython no-op socket async mode.

## B4. Middleware & lifecycle

- [ ] **[L]** `@app.middleware("http")` / `add_middleware` chains. Needs **LB3** —
      middleware is a closure over non-Copy state, and lambdas capture Copy-only today.
- [ ] **[P]** CORS middleware (once B4's chain exists).
- [ ] **[L]** `startup`/`shutdown` / `lifespan` hooks. Needs LB1 (module-level app).
- [ ] **[L]** `BackgroundTasks`. Needs **LB5** — `spawn`'s Send boundary is by-copy over
      primitives only (D9 v1), so a task cannot carry a request payload.

## B5. Errors & responses

- [x] **[L→done]** `HTTPException(status_code=404, detail="...")` — D42 exception `__init__`
      message builders; default detail is the HTTP phrase; `exc.status_code`/`exc.detail` read
      back through library getters inside `except` handlers.
- [ ] **[P]** `JSONResponse`/`PlainTextResponse`/… as **classes** rather than factory
      functions. LB7 is cleared (`__init__` bodies), but a handler typed `-> JSONResponse` would
      need subtyping to be accepted where `Response` is expected — keep factories, annotate
      `-> Response`.
- [ ] **[P]** `@app.exception_handler(...)` — another `@registrar` on `FastAPI` (D41 makes the
      decorator form available).
- [x] **[P]** Compact JSON separators (also A4).

## B6. Request surface

- [ ] **[P]** Cookies — `request.cookies`, `response.set_cookie(...)`.
- [ ] **[P]** Form data + `multipart/form-data` file uploads. Fang already parses/builds
      multipart on the client side; port the parser.
- [ ] **[P]** Repeated headers / repeated query keys (multi-dict semantics).
- [ ] **[P]** `await request.json()` / `request.body()` shapes — `json()` is sync today.
      Cosmetic until LB4, then real.

## B7. Streaming & long-lived connections

- [ ] **[L]** `StreamingResponse` — needs `yield`/generators, which the language does not
      have (this is why `serp-itertools` uses explicit iterator classes). Needs **LB8**.
- [ ] **[P]** `FileResponse` + static files (`StaticFiles` mount) — needs `os.stat`-class
      metadata in `serp-os`.
- [ ] **[L]** WebSockets. Framing and masking are library work, but usable duplex needs
      LB4.
- [ ] **[R]** Chunked transfer encoding (send + receive).

## B8. Tooling parity

- [ ] **[L]** OpenAPI schema generation + `/docs` / `/redoc`. The *model* half is done —
      Molt emits per-model JSON Schema and a handler can serve a hand-assembled
      `/openapi.json` today. Automatic generation needs LB2's signature introspection
      (that *is* the paths/params half of the schema).
- [ ] **[P]** `TestClient` gaps: headers/cookies/params kwargs, `PATCH`/`HEAD`/`OPTIONS`,
      redirect following.
- [ ] **[R]** HTTPS termination. Fang has client-side TLS (schannel/OpenSSL); the server
      side needs an accept-time TLS handshake primitive.
- [ ] **[R]** HTTP/2. Only after A2 and HTTPS; large.

---

# Dependencies

Library and runtime prerequisites that are not language blockers:

| Needed by | Depends on | Status |
|---|---|---|
| B2 body models, `response_model`, B8 schemas | **Molt** (`serp-molt`, pydantic drop-in — [molt.md](molt.md)) | ✅ **shipped 0.6.0**; usable from a handler today (`test_molt_body.py`), only LB2 remains |
| B7 static files / `FileResponse` | `serp-os` file metadata (`stat`-class) | needs a small `serp-os` addition |
| B8 HTTPS | server-side TLS accept primitive in `prelude.rs` (client side exists via Fang) | runtime work, not started |
| A4 | `serp-json` fast path | library work, not started |
| A7 CI gate | committed benchmark harness | currently scratch in `.rustic/tmp/perf/` |

# Language blockers

Numbered like the tracker's `B*` blockers but prefixed **LB** to avoid collision. Each
says what must be true in the *language*, not in Venom. Nothing here is Venom-specific —
every one of these unblocks other libraries too.

- **LB1 — module-level non-Copy constants.** ✅ **CLEARED for registries (D41)**: a
  module-level `app = FastAPI()` is a build-time factory; uses of the name construct a fresh,
  fully-registered instance. Not a shared mutable global — state that must persist across
  calls still needs to live in a function or a runtime-held table (D12 pattern).

- **LB2 — build-time signature introspection + generated call shims.** ✅ **CLEARED (D41)**:
  `@registrar` methods receive a compiler-synthesized `(Request) -> Response` endpoint built from
  the handler's annotated parameters via the `_serp_path_*`/`_serp_query_*`/`_serp_body`/
  `_serp_respond_json` convention on the request class. OpenAPI path generation (B8) can read
  the same information but is not wired yet.

- **LB3 — closures capturing non-Copy state.** Lambdas capture Copy-only today, and
  non-Copy arguments through a function value need an explicit `move()` (B1-cleared
  semantics). Middleware chains and nested `Depends()` are closures over shared,
  non-Copy state. *Gates:* B4 middleware, B2 nested dependencies.

- **LB4 — a real task runtime.** ✅ **CLEARED 2026-09-07 (D45).** Baton-scheduled tasks
  (`create_task`/`gather`/`await task`, CPython `_run_once` ordering) plus a socket async mode
  whose would-blocks park the task on the reactor. *Unblocked:* B3 async handlers (done);
  B7 WebSockets/streaming duplex now only needs the framing work. *Note:* Track A never
  needed it — the one-thread-many-connections loop already gets the throughput; LB4 was
  about *programming model*, not speed.

- **LB5 — `Send` for compound types.** D9 v1 restricts the `spawn` boundary to by-copy
  primitives (int/float/bool/str/bytes, SE216). A background task needs to carry a
  request/payload object across the boundary. *Gates:* B4 `BackgroundTasks`.
  *Also unblocks:* worker pools in `serp-threading`.

- **LB6 — borrowed slices / views over owned buffers.** Parsing without materializing
  `bytes`/`str` copies, i.e. a `&[u8]`-shaped value the borrow checker can track into a
  parser. *Gates:* A8 zero-copy parsing. *Also unblocks:* Coil/Scales and every parser
  library.

- **LB7 — `__init__` bodies.** ✅ **CLEARED** (molt LB10 / D22). A class may define
  `__init__(self: Mut[C], ...) -> None` with a parameter list independent of the field
  list, so `JSONResponse(content, status_code=...)` can be a class rather than a factory
  function. Every field must be assigned exactly once at the top level of the body.

- **LB8 — generators (`yield`).** No generator functions today; `serp-itertools` uses
  explicit `__iter__`/`__next__` classes instead. *Gates:* B7 `StreamingResponse`.
  *Also unblocks:* lazy pipelines everywhere.

## Dependency chains, shortest first

```
B5 HTTPException kwargs ......... no blocker — do it now
A1, A3, A4, A5, A6 ............. no blocker — library/runtime work, do in parallel
A2 (epoll/IOCP) ................ needs D16 decision on the Windows completion model
B1 decorators .................. LB1
B2 param injection ............. LB2  (Molt done)
B8 OpenAPI ..................... LB2  (after B2; model schemas already available)
B4 middleware .................. LB3
B4 BackgroundTasks ............. LB5
B3 async handlers .............. LB4
B7 StreamingResponse ........... LB8
B7 WebSockets .................. LB4  (framing itself is library work)
A8 zero-copy parsing ........... LB6
B5 response classes ............ LB7
```

**If only two language items ever land: LB1 then LB2.** Those two convert Venom from
"FastAPI-shaped" to "recognizably FastAPI". Everything in Track A is reachable without
any language change at all.
