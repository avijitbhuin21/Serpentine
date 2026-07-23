# The Serpentine Library Roadmap

> Tracker for the standard library and flagship ecosystem libraries. Every library
> ships as a **separate PyPI source distribution** installed with `serp add <name>`
> (guides/packages.md §3): pure-Serpentine where possible (dual-runs under CPython for
> free), runtime-backed where the OS is involved (rt.rs primitive + shim-side CPython
> delegate). archive/checklist.md Phase 7 tracks the prerequisites; this file tracks the
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

## Wave 1 — Foundations (unblock everything else) — **SHIPPED (in-repo) 2026-07-21**

Wave-1 libraries live in `libs/serp-<name>/` (monorepo, separate PyPI dists published
via `serp-<name>-vX.Y.Z` tags → `.github/workflows/release-lib.yml`). The dual-run
differential harness for libraries is `tools/run_lib_tests.py` (CPython + both
backends, byte-compared; wired into CI).

- [x] `serp-math` [R] — `sqrt/sin/cos/tan/log/exp/pow/floor/ceil/isnan/isinf` + `pi/e/inf/nan` (rtlib.py whitelist → prelude.rs/rt.rs primitives; CPython side re-exports `math`; CPython-parity errors: `math domain error`, `math range error`)
- [x] `serp-random` [R] — `seed/random/randint/uniform` on **SplitMix64**, implemented bit-for-bit in the runtime AND the CPython delegate: seeded sequences are byte-identical in both worlds (stronger than the planned "document the divergence"). `choice/shuffle` deferred — they need generic runtime support (list[T] through the C ABI)
- [x] `serp-time` [R] — `time()/monotonic()/sleep()`; `ValueError` on negative sleep
- [x] `serp-json` [P] — **drop-in json (2026-07-22)**: `loads` returns nested PyVal dynamic values, `dumps(obj, ensure_ascii=, sort_keys=)`; CPython 3.11 JSONDecodeError message parity (12k differential checks); byte-identical dual-run locked by libs/serp-json/tests
- [x] `serp-test` [P] — `assert_true/false`, `assert_eq_int/str/float`, `assert_close`, `fail` + the **`serp test`** subcommand (discovers `test_*.py`, builds natively, PASS/FAIL report, exit-code contract). Generic `assert_eq` awaits protocol-bounded `__eq__`
- [x] `serp-log` [P] — level constants, `Logger` (level-filtered stdout sink), `log_line`, `append_log` file sink; timestamps deferred until serp-lib-on-serp-lib deps land

## Wave 2 — Daily-tool stdlib — **SHIPPED (in-repo) 2026-07-21**

All 15 libraries live in `libs/serp-<name>/` like Wave 1; 21/21 lib tests
(CPython + both backends byte-identical). The rtlib mechanism now supports
string params ('s') and str / list[str] returns ('s' / 'S') — see rtlib.py —
which unlocked the [R] entries. New rtlib modules: `serp_os`, `serp_hashlib`,
`serp_uuid`, `serp_secrets`.

- [x] `serp-strings` [P] — wrap/fill (greedy, whitespace-collapsing), indent/dedent, ljust/rjust/center, expandtabs, repeat_char
- [x] `serp-structs` [P] — int min-heap (heap_push/heap_pop/heapify), int bisect_left/right + insort, generic two-stack `Deque[T]`, counter helpers (count_items/increment/most_common). Heap/bisect are int-first: generic ordering needs protocol-bounded `__lt__`
- [x] `serp-itertools` [P] — **drop-in `itertools` facade (0.2.0)**: lazy iterator classes over the user iterator protocol (`__iter__`/`__next__`); count/cycle/repeat are infinite, plus chain/islice/compress/accumulate/pairwise/product/zip_longest/takewhile/dropwhile/filterfalse/batched/permutations/combinations/combinations_with_replacement — 8801/8801 differential vs `itertools`. Combinatorics yield `list[T]` rows; no starmap/groupby/tee (see README divergences)
- [x] `serp-statistics` [P] — mean/median(_low/_high)/variance/pvariance/stdev/pstdev/quantiles (exclusive method) over list[float]; depends on serp-math (first serp-lib-on-serp-lib dep)
- [x] `serp-base64` [P] — b64/b32/b16 encode+decode (str↔str via internal UTF-8 codec; utf8_bytes/utf8_text exported)
- [x] `serp-csv` [P] — RFC 4180 parse (quotes, CRLF, embedded newlines) + QUOTE_MINIMAL-style writer (CRLF records)
- [x] `serp-cli` [P] — new_cli/add_flag/add_opt/add_pos/add_command, --x / --x=v / --x v, -h/--help, ParseResult, usage() help text
- [x] `serp-pathlib` [P over serp-os] — join/parent/name/suffix/stem/with_suffix/parts/is_absolute (handles / and \\ + drive prefixes) + exists/is_file/is_dir/mkdir/rmdir/remove/listdir re-exports
- [x] `serp-os` [R] — getenv("" when unset)/has_env/setenv/unsetenv, getcwd/chdir, exists/is_file/is_dir, mkdir/rmdir/remove, listdir (always sorted). Error messages normalized identically in runtime + delegate so dual runs stay byte-identical
- [x] `serp-datetime` [P over serp-time] — Dt dataclass (UTC, second resolution), days-from-civil calendar math, to_unix/from_unix, ISO-8601 format/parse, weekday/day_of_year/is_leap/days_in_month, add_days/add_seconds/diff_seconds, now_utc(). Zoneinfo later
- [x] `serp-hashlib` [R] — sha256_hex/sha1_hex/md5_hex, self-contained Rust digests in the runtime (no crates), stdlib delegation under CPython; bit-identical. blake2 deferred
- [x] `serp-re` [P] — NFA-style subset engine: literals, '.', \\d\\w\\s classes, [a-z]/[^...], * + ?, groups, |, ^ $. API: fullmatch/prefix_match/search/findall. Leftmost-LONGEST semantics (documented divergence from re's first-alternative-wins); no capturing/{m,n}/lazy
- [x] `serp-tomllib` [P] — **drop-in tomllib subset (2026-07-22)**: `loads` returns a PyVal dict like `tomllib.loads`; `TOMLDecodeError` (ValueError subclass). Comments, dotted keys, basic/literal strings, ints/floats/bools, single-line arrays, [a.b] headers. No dates, inline tables, arrays-of-tables, multi-line; messages use its own "line N:" format
- [x] `serp-uuid` [R] — uuid4() from OS CSPRNG (BCryptGenRandom / /dev/urandom)
- [x] `serp-secrets` [R] — token_hex/token_urlsafe/randbelow on the OS CSPRNG with rejection sampling

## Wave 3 — Files, compression, persistence — **SHIPPED (in-repo) 2026-07-22**

> **Prerequisites cleared 2026-07-22**: `bytes`/`bytearray` + binary file IO shipped
> (archive/checklist.md 7.0), so serp-io/zlib are unblocked. General closures, operator
> overloading, and user exception classes also landed — Coil's `__add__`/`__getitem__`
> blocker and Venom's closures blocker are gone (concurrency decision: decisions.md D9).

All four libraries live in `libs/serp-<name>/` like Waves 1–2. The rtlib mechanism
gained a bytes kind ('y' param/return) for the [R] entries. Compressed output is
world-divergent by design (different DEFLATE encoders) but fully interoperable —
tests compare roundtrips, checksums and fixture decompression, all byte-identical.

- [x] `serp-io` [P] — read/write/append for text+bytes, read_lines (CR-tolerant),
  file_size, copy_file, and a buffered `ByteReader` (read/peek/seek/skip/tell/
  remaining/at_eof) + reader/file_reader. Pure over the language's binary IO.
  Documented divergence: native text mode does no `\r\n` translation.
- [x] `serp-zlib` [R] — crc32/adler32 + compress/decompress (zlib format),
  deflate/inflate (raw), gzip_compress/gzip_decompress. Self-contained DEFLATE in
  the runtime (LZ77 + fixed-Huffman encoder, full stored/fixed/dynamic inflate;
  no crates); stdlib zlib/gzip delegate under CPython. Errors normalized:
  ValueError("Bad compression level") / ValueError("invalid compressed data").
- [x] `serp-zipfile` [P over serp-zlib] — ZipEntry + zip_bytes/zip_parse,
  zip_write/zip_read, zip_names/zip_has/zip_extract; stored + DEFLATE members,
  UTF-8 names, CRC-verified extraction, deterministic 1980-01-01 timestamps.
  Interop verified both directions with CPython's zipfile. No zip64/encryption.
- [x] `serp-sqlite` [R] — **drop-in sqlite3 subset (2026-07-22)**: `connect()` →
  `Connection`/`Cursor` objects, `?` parameters from PyVal lists (int/float/
  str/bytes/None), `fetchone`/`fetchall` PyVal rows, `rowcount`/`lastrowid`,
  `Error`/`DatabaseError`/`OperationalError`/`ProgrammingError` hierarchy;
  core handle API moved to `serp_sqlite_core` (system SQLite loaded dynamically
  at first use — winsqlite3.dll / sqlite3.dll on Windows, libsqlite3 on
  Linux/macOS — no link-time dep, no crates). Rows are lists (not tuples);
  no description/executemany/row_factory; autocommit only. CPython delegate
  emulates the handle API over stdlib sqlite3 (eager prepare validation via
  EXPLAIN); SQLite errors carry the C error message in both worlds.

## Wave 4 — Networking — **SHIPPED (in-repo) 2026-07-22** (Venom deferred: language-blocked)

All four unblocked libraries live in `libs/serp-<name>/` like Waves 1–3. Socket
error messages are normalized identically in the runtime and the CPython delegate
("connection refused" / "timed out" / ...), so networking tests dual-run
byte-identically (TCP via kernel-backlog loopback, UDP via send-to-self).

- [x] `serp-socket` [R core + P facade] — CPython socket-module drop-in: `socket`
  class (connect/bind/listen/accept/send/sendall/recv/sendto/recvfrom/settimeout/
  gettimeout/getsockname/shutdown/fileno/close), `create_connection`, AF_/SOCK_/SHUT_
  constants, exception types (ConnectionRefusedError/ConnectionResetError/timeout/
  gaierror/... mapped from normalized core errors). Core = intercepted `_serp_socket`
  runtime module (std::net + TLS natively; stdlib delegate under CPython).
- [x] `serp-url` [P] — urllib.parse drop-in: urlparse/urlsplit (ParseResult/
  SplitResult with hostname/port), urlunparse/urlunsplit, urljoin (RFC 3986 dot
  segments), urldefrag, quote/quote_plus (safe=), unquote/unquote_plus, urlencode,
  parse_qs/parse_qsl.
- [x] **Fang** (`serp-fang`) [P over _serp_socket + serp-url + serp-json + serp-base64
  + serp-io] — httpx-style sync HTTP(S) client, layered core/façade: native TLS in the
  runtime (schannel on Windows, dlopen'd OpenSSL on Linux/macOS, SNI + system trust,
  verify=False opt-out) under a pure-Serpentine façade with httpx names — Client
  (base_url/headers/cookie jar/auth/timeout/follow_redirects/max_redirects/verify),
  Response (status_code/reason_phrase/http_version/url/headers/content/history/elapsed,
  text()/json()/cookies()/is_*/raise_for_status()), get/head/options/delete,
  post/put/patch, post_form/post_json/post_multipart (FilePart), request,
  stream (incremental ResponseStream), download (stream-to-disk), upload_file,
  with_params/basic_auth helpers; redirects (301/302/303→GET, 307/308 preserve,
  urljoin resolution, cross-host auth strip, TooManyRedirects), cookie persistence,
  gzip/deflate auto-decode, Content-Length + chunked framing, HTTPStatusError.
  kwargs + scalar defaults throughout (httpx-like call syntax). Verified live against
  https://example.com and http→https redirect chains (github.com) — CPython + both
  backends byte-identical. Remaining divergences: methods-not-properties, no
  pooling/HTTP2/async/proxies, utf-8 text() only.
- [x] `serp-http-server` [P over _serp_socket] — http.server-aliased blocking
  HTTP/1.1 server: HTTPServer(server_address) + server_bind/handle_request/
  server_close; BaseHTTPRequestHandler request objects (command/path/
  request_version/headers.get/rfile.read/wfile.write, send_response/send_header/
  end_headers/send_error/finish). Loop dispatch instead of subclassing (no class
  inheritance); threaded model waits for Wave-6 concurrency (D9).
- [ ] **Venom** (`serp-venom`) [L→P] — still language-blocked, precisely:
  (1) `Callable` signatures are Copy-only, so route handlers cannot receive a
  Request dataclass or return a Response — the registration API would have to be
  JSON-string-in/JSON-string-out, a throwaway design; (2) no decorators;
  (3) concurrency (D9, Wave 6) for a real server. Revisit after non-Copy
  Callable params (or trait-object callables) land.

## Drop-in facade push — **SHIPPED (in-repo) 2026-07-22**

> Full per-library status, blockers, and ranked next steps: **language/python-equivalence.md**.

Selected Wave 1–3 libraries were rebuilt as **drop-in facades**: stdlib-identical
names/signatures on the surface, ownership-aware Serpentine + Rust runtime cores
underneath. Enabled by new language features shipped in the same push: **keyword
arguments** (call-site desugar), int→float argument coercion, and negative-literal
constants/defaults. Pattern: `serp_<name>` is now a pure-Serpentine facade module;
runtime primitives moved to a compiler-known `serp_<name>_core` rtlib module (the
PyPI dist ships both files).

- [x] `serp-random` — **true drop-in for the surface**: MT19937 implemented bit-for-bit
  (CPython seeding + genrand_res53 + _randbelow rejection sampling), so `seed(42)`
  produces CPython's exact stream in native builds. seed/random/randint/uniform/
  randrange/getrandbits/choice/shuffle. Caps: getrandbits ≤ 63 bits; error messages
  pinned to CPython 3.11. SplitMix64 is gone.
- [x] `serp-math` — 60+ names matching `math` exactly (verified against stdlib):
  trig/hyperbolic/exp/log families, isclose (kwargs), factorial/gcd/lcm/isqrt/comb/perm
  (int64-capped), frexp/modf (tuples), fsum, ldexp/copysign/fmod/nextafter/ulp/hypot,
  pi/e/tau/inf/nan. Deferred: gamma/lgamma/erf/erfc/remainder (need CPython's hand-rolled
  algorithms for bit parity), prod (needs overload sets), dist.
- [x] `serp-statistics` — StatisticsError (ValueError child, CPython messages), fmean,
  geometric/harmonic mean, covariance/correlation, quantiles(n=, method=). Deferred:
  mode/multimode/NormalDist; mean/variance stay float-based (CPython uses exact rationals).
- [x] `serp-secrets` — token_bytes/token_hex/token_urlsafe (optional nbytes, default 32),
  randbelow/randbits/choice/compare_digest, DEFAULT_ENTROPY. randbits ≤ 63.
- [x] `serp-hashlib` — stdlib object API: sha256/sha1/md5 (optional bytes arg) with
  update/hexdigest/digest/copy. update() re-hashes the accumulated buffer.
- [x] `serp-base64` — bytes-first like stdlib: b64/b32/b16 encode+decode plus
  standard_/urlsafe_ variants, altchars, validate, casefold. Errors are ValueError
  (stdlib: binascii.Error, a ValueError subclass).
- [x] `serp-time` — added time_ns/monotonic_ns/perf_counter/perf_counter_ns (all
  stdlib-named; still rtlib-direct, no facade needed).
- [x] `serp-zlib` — crc32/adler32 running `value` param, compress(level=-1) default,
  decompress wbits routing (15 zlib / -15 raw / 31 gzip), MAX_WBITS/Z_* constants.

**"Feasible today" wrap-up — SHIPPED (in-repo) 2026-07-22** (details, caps and
verification numbers in language/python-equivalence.md):

- [x] `serp-os` — `os` facade over the renamed `serp_os_core` rtlib module:
  getenv(key, default=None), putenv/unsetenv, getcwd/chdir, mkdir/rmdir/remove/
  unlink, listdir(path=".").
- [x] `serp-strings` — full `textwrap` parity: wrap/fill (all TextWrapper options
  incl. break_on_hyphens word splitting, fix_sentence_endings, max_lines/
  placeholder), shorten, dedent, indent. 1201/1201 differential checks vs stdlib.
- [x] `serp-structs` — stdlib `heapq` + `bisect` names with CPython's exact
  algorithms (heap layouts match); lo/hi params; int-only cap remains.
- [x] `serp-io` — `StringIO`/`BytesIO` objects with CPython behavior and messages.
- [x] `serp-pathlib` — `Path` object (`/` operator, name/stem/suffix/parent/parts
  as methods, fs ops, read/write helpers); PurePosixPath-verified derivations.
- [x] `serp-zipfile` — `ZipFile(file, mode, compression)` object facade
  (namelist/read/writestr/close, r/w/a, ZIP_STORED/ZIP_DEFLATED).
- [x] `serp-csv` — `reader(lines)` byte-matches csv.reader (3k fuzz checks,
  csv.Error parity); `writer()` matches csv.writer quoting but owns its buffer;
  **`DictReader(lines, fieldnames=, restval=)` (2026-07-22)** returns eager
  PyVal dict rows (no restkey — extra fields dropped).
- [x] `serp-datetime` — `date/datetime/timedelta` real-class trio with stdlib
  fields, `__post_init__` validation, arithmetic, comparisons, isoformat,
  str/repr parity, CPython 3.11 messages (9k randomized checks).

Language/compiler additions in this push: **bytes literal defaults**
(`buf: bytes = b""`) and **NotImplementedError** as a builtin exception
(RuntimeError child; prelude.rs `matches()` updated → dist-rt asset needs a
refresh before the next release).

**Tier-1 language push — SHIPPED (in-repo) 2026-07-22** (triage + details in
language/python-equivalence.md "Remaining blockers, triaged"):

- **`__str__` dunder** — `str(x)`, `print(x)`, and f-strings use it
  (typecheck-level desugar; `__repr__` deferred pending a backend
  repr-override).
- **`@property`** — attribute reads desugar to zero-arg method calls.
- **`@staticmethod`** — lifted to module functions at load; `Class.method()`
  call sites dispatch statically (classmethod-style constructors).
- **`with` on user objects** — `__enter__` (shape-enforced `return self`) +
  `__exit__(self, None, None, None)`; frontend rewrites to assign +
  try/finally so `__exit__` runs on exception paths.
- Applied: **serp-uuid is now a drop-in** (`uuid4()` → printable `UUID` object
  with `.hex/.urn/.version/.variant` properties; rtlib renamed
  `serp_uuid_core`, serp-fang updated); `Path` gained stdlib-shaped
  properties + `str()` parity + `Path.cwd()`; `StringIO`/`BytesIO`/`ZipFile`
  gained `with` support; `date`/`datetime`/`timedelta` print like CPython
  (incl. the timedelta "N days, H:MM:SS.ffffff" format).

**Still an equivalent, not a drop-in (with the blocking reason):**
`serp-test` (TestCase inheritance + reflection discovery — `serp test`
covers the need).
`serp-json`, `serp-tomllib`, `serp-sqlite`, and `csv.DictReader` became
drop-ins on 2026-07-22 via the PyVal dynamic value type (DECISIONS.md D10);
`serp-log` and `serp-re` followed the same day (D12 + engine rewrite).
`serp-itertools` became a lazy drop-in on 2026-07-23 via the user iterator
protocol (`__iter__`/`__next__` + for-loop lowering + `next()` on objects) —
no generators needed.

**Object-fidelity push — SHIPPED (in-repo) 2026-07-22** (details in
language/python-equivalence.md):

- **`__repr__` backend override** — rustgen `PyShow::py_repr` / llvmgen repr
  helper call the user method; containers, `!r`, and KeyError messages show
  stdlib-style reprs. Applied: `Path('a/b')`, `datetime.date(...)`,
  `datetime.datetime(...)`, zero-omitting `datetime.timedelta(...)`.
- **`__post_init__` validation bodies** + **empty `[]`/`{}` field defaults**
  (fresh per construction; shim `dataclass` 0.5.0 maps them to
  `default_factory` under CPython) — `date`/`datetime`/`timedelta`/`ZipFile`
  are now real classes with validating ctors; `datetime.utcnow()` added.
- **`serp-cli` is now an argparse drop-in** (0.2.0) — `ArgumentParser` /
  `add_argument` (short+long, store/store_true/store_false, default/required/
  help) / `parse_args` over a dict-shaped PyVal Namespace; usage/help/error
  text byte-matches argparse 3.11; `args["dest"]` indexing is the documented
  divergence (D11). Legacy `Cli` API retained.
- Checker fix: `list.append(x)` passes the element type as the argument's
  expected type (r056 now correctly rejects loop-capturing lambdas with
  SE005 instead of tripping over lambda typing).

**Logging + regex push — SHIPPED (in-repo) 2026-07-22** (details in
language/python-equivalence.md; design in DECISIONS.md D12):

- **serp-log is a logging drop-in** (0.2.0) — global registry/config lives
  in the runtime (`serp_log_core` str→str KV + stderr sink, D12; precedent:
  MT19937 state). getLogger hierarchy, basicConfig(level/format/filename/
  filemode), last-resort handler, getLevelName; 19/19 stdlib parity incl.
  byte-identical file output. Legacy helpers kept.
- **serp-re is a `re` drop-in** (0.2.0) — full backtracking engine rewrite:
  patterns compile to an instruction program run by a recursive VM
  (split/jmp/save + per-star mark/progress guards), capture groups,
  lazy/counted quantifiers, must-advance empty-match scanning, Match/Pattern
  objects with CPython reprs, `error` with 3.11 messages, flags I/M/S.
  30530/30533 differential checks vs CPython `re` (2 corner diffs: captures
  inside counted reps of lazy nullable bodies). Old NFA API removed.
- Compiler fixes ridden along: imported/user functions may shadow rejected
  builtin names (`compile`); rustgen field/method access on narrowed
  Optional locals borrows (`as_ref()/as_mut()`) instead of moving.

## Wave 5 — Data & modeling flagships

- [ ] **Molt** (`serp-molt`) [P] — pydantic-equivalent: dataclass validation from dict/JSON (via serp-json), field constraints, typed error reports. Start early — it's mostly protocols + generics we already have; nested-model support tracks language features
- [ ] **Coil** (`serp-coil`) [L→R] — numpy-equivalent: 1-D/2-D f64 arrays, elementwise ops, dot/matmul, slicing, reductions; contiguous buffers in rt.rs. **Unblocked 2026-07-22: operator overloading (`__add__`/`__mul__`/`__matmul__`/`__getitem__`/`__setitem__`) shipped**
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
