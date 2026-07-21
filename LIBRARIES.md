# LIBRARIES.md — The Serpentine Library Roadmap

> Tracker for the standard library and flagship ecosystem libraries. Every library
> ships as a **separate PyPI source distribution** installed with `serp add <name>`
> (docs/packages.md §3): pure-Serpentine where possible (dual-runs under CPython for
> free), runtime-backed where the OS is involved (rt.rs primitive + shim-side CPython
> delegate). CHECKLIST.md Phase 7 tracks the prerequisites; this file tracks the
> libraries themselves.

## Naming convention

- **PyPI distribution**: `serp-<name>` (e.g. `serp add serp-json`, `pip install serp-json`).
- **Import root**: the normalized dist name (`serp_json`), per packages.md resolution —
  `from serp_json.decode import loads`. Never shadows the CPython module it mirrors,
  so a file importing both worlds stays unambiguous.
- **Flagship ecosystem libraries get snake-themed codenames** (brandable, collision-free
  on PyPI, and they signal "equivalent, not clone"):

| Codename | PyPI dist | Import root | Equivalent of |
|---|---|---|---|
| **Coil** | `serp-coil` | `serp_coil` | numpy (arrays coil) |
| **Scales** | `serp-scales` | `serp_scales` | pandas (a snake's dataframe) |
| **Fang** | `serp-fang` | `serp_fang` | httpx / requests (fangs deliver) |
| **Venom** | `serp-venom` | `serp_venom` | FastAPI (injected routes) |
| **Molt** | `serp-molt` | `serp_molt` | pydantic (shed raw data, emerge typed) |

Stdlib-mirror libraries keep plain descriptive names (`serp-json`, `serp-math`) — they
should be boring and guessable.

## Implementation paths

- **[P] Pure Serpentine** — source-only, zero new compiler/runtime work once the
  prerequisites land. Dual execution automatic.
- **[R] Runtime-backed** — new `extern "C"` primitives in rt.rs + a compiler-known
  module; the PyPI package's CPython side simply delegates to the real stdlib module.
- **[L] Language-blocked** — needs a language feature first (listed under prerequisites).

---

## Wave 1 — Foundations (unblock everything else)

- [ ] `serp-math` [R] — `sqrt/sin/cos/tan/log/exp/pow/floor/ceil/pi/e/inf/nan/isnan/isinf` (libm calls; the easiest runtime-backed module — build it first to prove the [R] pattern)
- [ ] `serp-random` [R] — `random/randint/uniform/choice/shuffle/seed` (PCG or xoshiro in rt.rs; document divergence: sequences differ from CPython's Mersenne Twister even with the same seed)
- [ ] `serp-time` [R] — `time()/monotonic()/sleep()`; epoch arithmetic
- [ ] `serp-json` [P] — promote `examples/json_parser.py` into a real library: `loads/dumps`, nested values, escapes, error positions (north-star proof that pure-Serpentine libraries work end-to-end)
- [ ] `serp-test` [P] — pytest-lite: `assert_eq/assert_raises`, test discovery via `serp test` subcommand, readable failure reports (libraries can't grow without it)
- [ ] `serp-log` [P] — levels, formatters, stderr/file sinks

## Wave 2 — Daily-tool stdlib

- [ ] `serp-strings` [P] — `textwrap`-style wrap/fill/indent, padding, tabulation
- [ ] `serp-structs` [P] — `heapq`, `bisect`, `deque`, `Counter`, `defaultdict`-style helpers (Copy-element first, generic where the checker allows)
- [ ] `serp-itertools` [P] — `chain/takewhile/dropwhile/pairwise/batched` subset that fits the iterator-borrow model
- [ ] `serp-statistics` [P] — `mean/median/stdev/variance/quantiles`
- [ ] `serp-base64` [P] — b64/b32/hex encode+decode
- [ ] `serp-csv` [P] — reader/writer with quoting rules
- [ ] `serp-cli` [P] — argparse/click-lite: flags, positionals, subcommands, help text (native CLIs are Serpentine's first market)
- [ ] `serp-pathlib` [R] — `Path` join/parent/name/suffix (pure string ops [P]) + `exists/is_file/mkdir/listdir/remove` (rt.rs syscalls)
- [ ] `serp-os` [R] — `getenv/environ`, `getcwd/chdir`, process exit codes
- [ ] `serp-datetime` [R] — `date/time/datetime/timedelta`, ISO-8601 parse/format; UTC first, zoneinfo later
- [ ] `serp-hashlib` [R] — sha256/sha1/md5/blake2 (Rust crates in the runtime, stdlib delegation under CPython)
- [ ] `serp-re` [P/R] — regex: biggest single stdlib project; start with a literal/class/star subset [P], graduate to a runtime-backed engine [R] if perf demands
- [ ] `serp-tomllib` [P] — read-only TOML (we already dogfood serp.toml)
- [ ] `serp-uuid` [R] — uuid4 (needs OS randomness)
- [ ] `serp-secrets` [R] — CSPRNG tokens

## Wave 3 — Files, compression, persistence

- [ ] `serp-io` [R] — binary file mode, buffered reads, `bytes`-equivalent story (prerequisite: a bytes type — see Phase 7 prerequisites)
- [ ] `serp-zlib` [R] — gzip/zlib compress+decompress
- [ ] `serp-zipfile` [P over serp-zlib] — zip read/write
- [ ] `serp-sqlite` [R] — embedded SQLite via the runtime (bundled C library); the single highest-value battery for local tools

## Wave 4 — Networking

- [ ] `serp-socket` [R] — TCP client/server, UDP; the primitive everything above sits on
- [ ] `serp-url` [P] — urlparse/urlencode/quote
- [ ] **Fang** (`serp-fang`) [R over serp-socket] — httpx-equivalent HTTP client: get/post, headers, JSON bodies (via serp-json), timeouts; TLS via runtime (rustls); sync-only until async lands
- [ ] `serp-http-server` [R] — minimal HTTP/1.1 server (threaded-or-blocking model per the concurrency decision)
- [ ] **Venom** (`serp-venom`) [L→P] — FastAPI-equivalent: routing, path/query params, Molt-validated request/response models, OpenAPI-ish schema dump. **Blocked on: decorators-as-routing (or explicit registration API), closures, concurrency decision**

## Wave 5 — Data & modeling flagships

- [ ] **Molt** (`serp-molt`) [P] — pydantic-equivalent: dataclass validation from dict/JSON (via serp-json), field constraints, typed error reports. Start early — it's mostly protocols + generics we already have; nested-model support tracks language features
- [ ] **Coil** (`serp-coil`) [L→R] — numpy-equivalent: 1-D/2-D f64 arrays, elementwise ops, dot/matmul, slicing, reductions; contiguous buffers in rt.rs. **Blocked on: operator overloading (`__add__` etc.)**; API-first version with `.add()/.mul()` methods can ship before that
- [ ] **Scales** (`serp-scales`) [L→R over Coil] — pandas-equivalent: typed columns, filter/select/groupby/join, CSV+JSON IO. **Blocked on: Coil + probably keyword-argument ergonomics**; a columnar `Frame` with method chaining is achievable well before "pandas parity"

## Wave 6 — Language-level (not libraries — tracked here for sequencing honesty)

- [ ] Concurrency story — `Shared` is `Rc` (not thread-safe): decide scoped threads + `Send`-checked captures vs. keeping single-threaded; blocks `serp-threading`, real servers, Scales parallelism
- [ ] `async/await` — a full language feature (state-machine lowering in both backends); blocks asyncio-equivalent and async Fang/Venom
- [ ] `serp-subprocess` [R] — spawn/wait/capture (needs the bytes story; otherwise straightforward)

---

## Ordering rationale

Wave 1 proves both shipping paths ([P] and [R]) with tiny surface area. Wave 2 makes
`serp` genuinely useful for daily tools. Waves 3–4 are IO-heavy runtime work. Wave 5
flagships ride on everything before them. Wave 6 is honest about what is a language
project wearing a library costume.
