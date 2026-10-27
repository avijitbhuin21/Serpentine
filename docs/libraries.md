# The Serpentine Library Tracker

> One line per library. `[x]` = shipped in `libs/serp-<name>/` (separate PyPI dist,
> installed with `serp add <name>`). Paths: **[P]** pure Serpentine, **[R]** runtime-backed
> (rt.rs primitives), **[L]** language-blocked. ✅ = drop-in for its CPython counterpart,
> ≈ = equivalent (own API). Blocked items reference the numbered blockers at the bottom.
> Verify sync anytime with `python tools/run_lib_tests.py` (all libs byte-identical across
> CPython, Rust and LLVM backends).
>
> Flagship codenames: **Coil**=numpy, **Scales**=pandas, **Fang**=httpx, **Venom**=FastAPI, **Molt**=pydantic.
>
> Libraries with an active work plan get a checklist at `libraries/<name>.md` — those docs
> own their own numbered **LB** (language-blocker) list; the `B*` blockers below are
> project-wide.

## Wave 1 — Foundations — SHIPPED

- [x] `serp-math` [R] 0.1.0 — ✅ `math` (60+ names; gamma/erf/remainder/prod/dist deferred)
- [x] `serp-random` [R] 0.1.0 — ✅ `random` (MT19937 bit-exact seeding; getrandbits ≤ 63)
- [x] `serp-time` [R] 0.1.0 — ✅ `time` subset (time/monotonic/sleep + _ns/perf_counter variants)
- [x] `serp-json` [P+R] 0.3.0 — ✅ `json` (PyVal loads/dumps, JSONDecodeError message parity;
      `dumps` uses the `pyval_json` runtime builtin unless `sort_keys=True`, plus an additive
      `compact=` flag since stdlib `separators=` needs a non-literal default)
- [x] `serp-test` [P] 0.2.0 — ≈ `unittest` (TestCase subclassing + build-time discovery via `serp test`; assert*/setUp/tearDown; no msg=/unittest.main)
- [x] `serp-log` [P] 0.2.1 — ✅ `logging` (D12 runtime-held registry, getLogger/basicConfig)

## Wave 2 — Daily-tool stdlib — SHIPPED

- [x] `serp-strings` [P] 0.1.0 — ✅ `textwrap` (wrap/fill/shorten/dedent/indent, full options)
- [x] `serp-structs` [P] 0.1.0 — ✅ `heapq` + `bisect` (CPython algorithms; int-only cap)
- [x] `serp-itertools` [P] 0.2.0 — ✅ `itertools` (lazy iterator classes; no starmap/groupby/tee)
- [x] `serp-statistics` [P] 0.1.0 — ✅ `statistics` (mean/median/stdev/quantiles/fmean; no mode/NormalDist)
- [x] `serp-base64` [P] 0.1.0 — ✅ `base64` (b64/b32/b16 + urlsafe/altchars/validate)
- [x] `serp-csv` [P] 0.2.0 — ✅ `csv` (reader/writer/DictReader; no restkey)
- [x] `serp-cli` [P] 0.2.0 — ✅ `argparse` (ArgumentParser/add_argument; D11 `args["dest"]` indexing) — PyPI dist **`serpentine-argparse`**, import `serp_cli`
- [x] `serp-pathlib` [P] 0.2.0 — ✅ `pathlib` (`Path` with `/` operator, fs ops, read/write helpers)
- [x] `serp-os` [R] 0.1.0 — ✅ `os` subset (env vars, cwd, mkdir/rmdir/remove/listdir)
- [x] `serp-datetime` [P] 0.4.0 — ✅ `datetime` (date/datetime/timedelta, `fromisoformat`, validation, repr parity; fixed-offset `timezone`/`timezone.utc`/`UTC` + aware datetimes; no IANA `zoneinfo`)
- [x] `serp-hashlib` [R] 0.2.0 — ✅ `hashlib` (sha256/sha1/md5 objects, `pbkdf2_hmac` native; no blake2)
- [x] `serp-hmac` [R] 0.1.0 — ✅ `hmac` (`new`/`digest`/`compare_digest`, name-string `digestmod`)
- [x] `serp-jwt` [P] 0.1.0 — PyJWT-compatible HS256 (`encode`/`decode`/`get_unverified_header`, exp/nbf/iat/aud/iss, PyJWT error classes)
- [x] `serp-bcrypt` [R] 0.1.0 — ✅ pyca `bcrypt` (`gensalt`/`hashpw`/`checkpw`, byte-identical hashes; native EksBlowfish)
- [x] `serp-re` [P] 0.2.1 — ✅ `re` (backtracking VM, groups, lazy/counted, flags; 30530/30533 differential; ReDoS guard: 1M steps / 10k depth per attempt → `re.error`)
- [x] `serp-tomllib` [P] 0.2.0 — ✅ `tomllib` subset (PyVal dict; no dates/inline tables/multi-line)
- [x] `serp-uuid` [R] 0.2.0 — ✅ `uuid` (uuid4 + `UUID(str)` in all four spellings → hex/urn/version/variant)
- [x] `serp-secrets` [R] 0.1.0 — ✅ `secrets` (token_*/randbelow/randbits/compare_digest; randbits ≤ 63)
- [x] `serp-queue` [R+P] 0.1.0 — ✅ `queue` (Queue/LifoQueue, blocking put/get + timeouts, put_nowait/get_nowait, qsize/empty/full, task_done/join, Empty/Full; PyVal items deep-copied across threads — the sharing channel for serp-threading; no PriorityQueue/SimpleQueue) — shipped 2026-09-04

## Wave 3 — Files, compression, persistence — SHIPPED

- [x] `serp-io` [P] 0.1.0 — ✅ `io` (StringIO/BytesIO) + file helpers and ByteReader — PyPI dist **`serpentine-io`**, import `serp_io`
- [x] `serp-zlib` [R] 0.1.1 — ✅ `zlib` (+ gzip helpers; self-contained DEFLATE, wbits routing; 256 MiB output cap and CPython trailing-data/multi-member semantics)
- [x] `serp-zipfile` [P] 0.2.0 — ✅ `zipfile` (ZipFile r/w/a, stored+DEFLATED; no zip64/encryption; inherits the 256 MiB inflate cap)
- [x] `serp-sqlite` [R] 0.3.0 — ✅ `sqlite3` subset (Connection/Cursor, `?` params, PyVal rows; legacy-mode transactions: implicit BEGIN, `commit`/`rollback`, `in_transaction`, `isolation_level`)
- [x] `serp-redis` [P] 0.1.0 — redis-py-style client over RESP2 (strings/counters/expiry/hashes/lists/sets/publish, AUTH/SELECT; no pool/pipeline/pub-sub)

## Wave 4 — Networking — SHIPPED (incl. Venom, 2026-07-23)

- [x] `serp-socket` [R+P] 0.1.0 — ✅ `socket` (TCP/UDP, timeouts, exception types, normalized errors)
- [x] `serp-url` [P] 0.1.0 — ✅ `urllib.parse` (urlparse/urljoin/quote/urlencode/parse_qs)
- [x] `serp-fang` **Fang** [P] 0.3.1 — ✅ `httpx` sync client (native TLS, redirects, cookies, streaming, multipart)
- [x] `serp-http-server` [P] 0.2.0 — ✅ `http.server` (HTTPServer + handler objects; single-threaded; 64 KiB heads, 16 MiB `MAX_BODY` → 413, 30 s whole-request read deadline)
- [x] `serp-prometheus` [R] 0.1.0 — prometheus_client-style Counter/Gauge/Histogram/Summary with labels + text exposition (process-global runtime store)
- [x] `serp-tracing` [P] 0.1.0 — OpenTelemetry-style spans, W3C traceparent propagation, memory/stderr/file JSON exporters
- [x] `serp-bigint` [P] 0.1.0 — arbitrary-precision `BigInt` (`+ - * // % **`, abs, comparisons, divmod), CPython-exact
- [x] `serp-venom` **Venom** [P+L] 0.4.0 — ✅ `fastapi` (module-level `app = FastAPI()`, `@app.get/post/put/delete/patch(path, status_code=)` with parameter injection by name/type — path/query scalars, `T | None`, serp_molt model bodies, raw `Owned[Request]` — JSON-serialized returns incl. models/`list[Model]`, FastAPI's 422 envelope, `HTTPException(status_code=, detail=)`, `JSONResponse`/`PlainTextResponse`/`HTMLResponse`/`RedirectResponse` with `headers=`, `TestClient(app)` with `json=`/`params=`/`headers=`, `serp_uvicorn.run`; `Depends(fn)` (nested), `APIRouter(prefix=)` + module-level `app.include_router`/`add_api_route`; threaded keep-alive + event-loop servers) — drop-in since 2026-09-07 via D41 (module-level object bindings + `@registrar`) and D42 (exception `__init__`); **axum parity** (1.05x at w1/c16, 0.92–1.03x at w3/c64, 2026-08-30) — **roadmap: [libraries/venom.md](libraries/venom.md)** (still open: middleware/BackgroundTasks/streaming/WebSockets)

## Wave 5 — Data & modeling flagships

- [x] `serp-molt` **Molt** [P+L] 0.7.1 — ✅ `pydantic` v2 (BaseModel/Field/ValidationError, lax coercion, constraints, aliases, nested + `list`/`dict` + self-referential models, enums/sets/unions/generic models, `date`/`datetime`/`timedelta`/`UUID` fields, **`SecretStr`**, **`Base64Bytes`**, `Strict*` types, `model_dump`/`model_dump_json`/`model_validate`/`model_validate_json`/`model_validate_errors`/`model_validate_json_errors`/`model_copy`/`model_construct`/`model_fields`/`model_fields_set`/`model_json_schema`, v1 aliases, `@field_validator`/`@model_validator` before+after with `ValidationInfo` + `context`, `@field_serializer`/`@model_serializer`/`@computed_field`, `Annotated` `AfterValidator`/`BeforeValidator`/`Json`/`SkipValidation`, `PositiveInt`…`HttpUrl`/`EmailStr` aliases, `PydanticCustomError`, root models, `Model(**data)`, `model_config` extra/`str_*`/`populate_by_name`/`frozen`/`validate_assignment`/`alias_generator`) — unblocked by D16/D18/D19–D25 plus D27 hooks, D28 type aliases and D31–D37; discriminated unions and `conint()`/`constr()`/`conlist()` shipped 2026-08-30. Suite green (`49/49` incl. the `test_schema_repeat` regression guard) since the same-day fix of the intermittent `0xC0000005`: a **Backend-B `IfExp` codegen defect** on a non-Copy `str` ternary with a call arm. The compiler fix landed in `llvmgen._ifexp` on 2026-08-30, and `_model_json` uses the original ternary again. Remaining: `mode="plain"` validators (feasible, not implemented), `mode="wrap"` validators (blocked on LB3) and `Decimal` (D26 rejected) — **roadmap: [libraries/molt.md](libraries/molt.md)**
- [x] `serp-coil` **Coil** [P] 0.1.0 — ✅ `numpy` (1-D/2-D `ndarray` with `float64`/`int64`/`bool` dtypes; `array`/`zeros`/`ones`/`full`/`arange`/`linspace`/`eye`; all arithmetic/comparison/bitwise operators incl. reflected forms with numpy broadcasting and dtype promotion; `a[i]`/`a[i, j]`/`a[mask] = v`; reductions with numpy's pairwise summation + `*_axis` variants; 40+ ufuncs; `where`/`clip`/`sort`/`argsort`/`unique`/`concatenate`/`vstack`/`hstack`; `dot`/`matmul`/`@`/`outer`/`trace`/`det`/`inv`/`solve`; **numpy-exact `repr`/`str`** incl. wrapping and `...` summarization — `tests/test_printing.py` is byte-identical to numpy 2.4.6) — shipped 2026-09-06; pure Serpentine over `serp-math`; needed a Backend-A/B fix (live non-Copy place moved into a `Ref[union]` temp — now cloned, accept 095), `__eq__`/`__ne__` overrides, `resolve_reexports` and int→`float | None` widening. Divergences (lists for shapes, float scalars, `*_axis` instead of `axis=`, no slicing syntax, `from serp_coil import …` only) in `libs/serp-coil/README.md`
- [x] `serp-scales` **Scales** [P+L] 0.2.0 — ✅ `pandas` (DataFrame/Series over PyVal columns: `df["c"]`/`df[["a","b"]]`/`df[mask]`/`df[a:b]`/`df["c"] = …`/`df.loc[mask|label|a:b, col|cols]`/`df.iloc[i|[i,j]|a:b, j|[p,q]]`, masks via `== != < > & | ~`, index-aligned arithmetic incl. reflected `2 * s`, reductions, `rank`/`pct_change`/`cum*`, `rolling`, `corr`/`cov`, `sort_values`, `groupby`+`agg`/`apply`/`transform` (+`groupby()["v"].sum()` Series), `pivot_table`/`pivot`/`melt`/`crosstab`, `merge`, `concat`, `query`/`eval`, `fillna`/`dropna`/`replace({...})`, `apply`/`map`, `value_counts`, `.str`, `to_datetime`/`.dt`, `iterrows`/`itertuples`, `to_dict`/`to_csv`/`read_csv(parse_dates=)`/`to_json`/`read_json`, pandas text layout incl. 60-row/20-column truncation) — 0.1.0 shipped 2026-09-06 (D38–D40), 0.2.0 drop-in 2026-09-07 (D43 tuple/slice keys + `iterrows` destructuring, D44 non-str PyVal dict keys); depends on serp-json + serp-datetime; **without** Coil (PyVal cells; typed storage is the S3 follow-up). Divergences (`s[mask]`→`s.loc[mask]`, `.loc` assignment, `s.map(dict)`, MultiIndex) in `libs/serp-scales/README.md` — **roadmap: [libraries/scales.md](libraries/scales.md)**

## Wave 6 — Language-level (language projects, not libraries)

- [x] `serp-threading` [L+R+P] 0.1.0 — ✅ `threading` (D9 v2, 2026-09-04): `Thread(target=, args=, name=, daemon=)`/`Timer` are language intrinsics (shim 0.7.0, re-exported) with start/join(timeout)/is_alive/name/ident/daemon/cancel and CPython's join-non-daemon-at-exit; Lock/RLock/Event/Semaphore/BoundedSemaphore/Condition/Barrier/`local()` are runtime-held handles passable to threads (scalar-field classes now cross the Send boundary by copy via `Owned[...]`); current_thread/main_thread/get_ident/active_count. Divergences: targets are module functions with Send params (no lambdas/bound methods/kwargs), `local()` uses get/set/has/delete, `Thread.name` read-only, no enumerate/excepthook. **Not yet**: `class Worker(Thread)` + `run()` subclassing (needs hidden-handle class layout + self deep-copy in both backends — next session)
- [x] `serp-asyncio` [L+R+P] 0.1.0 — ✅ `asyncio` (D45, 2026-09-07): `run`/`sleep`/`create_task`/`gather`/`Task[T]`/`await task`/`done()` are language intrinsics over the **baton task runtime** (tasks = OS threads, exactly one runs, CPython `_run_once` ordering → byte-identical dual runs); `Event`/`Lock`/`Semaphore`/`BoundedSemaphore`/`Queue`/`QueueEmpty`/`QueueFull` + `async with` come from the package (runtime-held handles, passable to tasks). Sockets gained an **async mode** (would-block parks the task on the reactor) so **Fang `AsyncClient`** (0.3.0) and **Venom async handlers + task-per-connection serving** (`accept_async`/`serve_conn`, 0.4.0) concur natively: four 300 ms requests finish in 0.30 s. Divergences: no cancellation/`wait_for`/`async for`/`Task.result()`, one loop per process, mixed-type `gather` rejected, CPython-side socket async mode is a no-op
- [x] `serp-subprocess` [R+P] 0.1.0 — ✅ `subprocess` (run/check_output/check_call/call + Popen communicate/wait/poll/kill/terminate, PIPE/STDOUT/DEVNULL, input/text/cwd/env/shell/timeout/check, CPython-worded CalledProcessError/TimeoutExpired; std::process + platform pipes for `stderr=STDOUT`; exceptions carry only messages, `communicate()` result is indexed not unpacked) — shipped 2026-09-03

---

## Sync status

**PyPI:** `serpentine-lang` 0.7.4 + `serpentine-shim` 0.9.2, and all 44 libs at the versions above (`serp-jwt`, `serp-redis` and `serp-tracing` were published through PyPI pending publishers after the account hit the new-project rate limit).
The hardening changes to serp-re, serp-zlib, serp-http-server and serp-venom shipped in their
0.7.3-wave releases.
Two libs publish under different dist names than their folder/import names: `libs/serp-io` →
**`serpentine-io`** and `libs/serp-cli` → **`serpentine-argparse`** (the `serp-*` names were
rejected or taken). Imports stay `serp_io`/`serp_cli`, because the compiler reads import roots from
`*.dist-info` metadata. `serp-fang` depends on `serpentine-io`.
New libs publish via a PyPI *pending publisher* (owner `avijitbhuin21`, repo `Serpentine`, workflow
`release-lib.yml`, env blank) + tag push `serp-<name>-vX.Y.Z`, one pending publisher at a time.

**Dependency pins:** every declared lib→lib dependency is listed in both `serp.toml` and
`pyproject.toml` and matches the repo versions (last verified 2026-09-07). Test-only cross-lib
imports, which aren't package deps: serp-log/serp-sqlite tests use serp-os; serp-http-server tests
use serp-socket; serp-venom's `test_molt_body.py` uses serp-molt (+ its re/datetime/uuid/time roots).

## Blockers — ALL CLEARED (2026-07-23)

- **B1** — ~~`Callable` signatures are Copy-only~~ **CLEARED**: Callable params/returns may
  be any type; non-Copy arguments through a function value require an explicit `move()`
  (SE002 otherwise), lambdas still capture Copy-only.
- **B2** — ~~no decorators~~ **CLEARED**: registration-style `@deco` / `@deco(args)` on
  module functions (D13 — decorated name stays bound to the original; decorator result is
  typechecked against the exact signature).
- **B3** — ~~no concurrency story~~ **CLEARED**: `from serpentine import spawn` →
  `spawn(f, args...) -> JoinHandle[R]` + `.join()`, Send-checked by-copy boundary
  (int/float/bool/str/bytes, SE216), thread-local error state (D9 v1). `Shared` stays `Rc`
  and cannot cross threads.
- **B4** — ~~Coil must ship first~~ **RECLASSIFIED**: not a technical blocker — ordinary
  roadmap sequencing (Scales builds on Coil's arrays; the B3 half is cleared).
- **B5** — ~~no class inheritance + reflection discovery~~ **CLEARED 2026-07-23** (D15
  superseded): single `@dataclass` inheritance shipped (check-time flattening — no
  subtyping/`super()`/vtables; field-less bases allowed) + `AssertionError` builtin;
  `serp test` discovers `TestCase` subclasses at build time and generates the native
  runner (no runtime reflection). serp-test 0.2.0 ships the unittest-style `TestCase`.
- **B6** — ~~no `async/await`~~ **CLEARED**: eager coroutines (D14), then **real tasks (D45)** —
  `create_task`/`gather`/`await task`/`asyncio.sleep` suspend on a baton-scheduled runtime with
  CPython's event-loop order; `serp-asyncio` ships the sync primitives.

## Unlocked

Cleared blockers unlock the following (in suggested order):

1. **Venom** (`serp-venom`) — ✅ SHIPPED 2026-07-23; **drop-in since 2026-09-07** (D41
   `@app.get` decorators + parameter injection, D42 `HTTPException(status_code=, detail=)`).
2. **Threaded serp-http-server** — thread-per-connection or a small worker pool via `spawn`.
3. **`serp-threading`** — higher-level conveniences over `spawn` (pools, channels, timers).
4. **Scales** (`serp-scales`) — ✅ SHIPPED 2026-09-06 over PyVal cells (Coil is now only the
   performance follow-up; parallel column ops can use D9 threads).
5. **Async Fang/Venom APIs** — ✅ SHIPPED 2026-09-07 (D45): `httpx.AsyncClient` façade and
   `async def` FastAPI handlers served task-per-connection.
