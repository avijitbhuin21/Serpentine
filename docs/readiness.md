# The Serpentine Production-Readiness Checklist

> One line per item. `[x]` = done, `[~]` = partial, `[ ]` = open, `[?]` = unverified (someone
> must check before it can be ticked). Priority tags: **P0** = blocks *any* serious use,
> **P1** = blocks production services with real users, **P2** = needed for broad adoption.
> Each item names its evidence or the doc that owns it. [libraries.md](libraries.md) tracks
> library *features*; this doc tracks whether the project as a whole is safe to depend on.
>
> Last assessed: **2026-09-28**.

## Verdict

| Level | Meaning | Status |
|---|---|---|
| **L1 — Experimental** | Hobby projects, demos, benchmarks | ✅ **Here today** |
| **L2 — Internal tools** | CLIs, batch jobs, internal services where a crash costs little | ⚠️ Reachable once the P0s are cleared |
| **L3 — Production service** | Internet-facing, many users, on-call | ❌ Not yet (open P1s in security, ops and ecosystem) |

**Why not L3 yet:**
1. Two libraries (`serp-io`, `serp-cli`) still need new PyPI names, and the 0.7.0 prebuilt runtime assets were only just rebuilt.
2. There's no fuzzing or sanitizer coverage of the `unsafe` runtime. Its hand-written
   network, regex and compression parsers face untrusted input.
3. There are no database clients besides SQLite.
4. There are no timezones, no metrics or tracing, and no debugger story.
5. Performance and soak testing has only been done on one Windows box.

The compiler itself is strong: every test corpus is byte-identical across CPython, Backend A
and Backend B on all three OSes, and the rustc-agreement harness reports 0 disagreements.

---

## 1. Source control & CI — P0

- [x] **P0** Commit + push the Phase-7 work — landed 2026-09-28 (`fdd7161`), Molt/Venom/Coil/Scales/asyncio/threading/queue/subprocess + accept 070–102.
- [x] **P0** Master CI is green on all three OSes (2026-09-28, run 36398975310). Fixed along the way: shim `__init_subclass__` forwarding broke `Generic` on CPython 3.12; Unix TLS build referenced a Windows-only `dec` buffer (now `tls_buffered`/`SSL_pending`); accept 102 timer gaps widened. The old `serp-base64` Linux abort no longer reproduces.
- [x] **P0** `release-lib.yml` works: trusted publishing first (via PyPI pending publishers, which bypassed the `429 Too many new projects created` limit the token route hit), `PYPI_API_TOKEN` fallback.
- [ ] **P0** CI runs *every* lib suite, not just the "Wave 1 libs" named in the `ci.yml` step.
      Molt/Venom/Scales/Coil/asyncio need to be gated too.
- [ ] **P1** Remove stray artifacts, gitignore them, and confirm they were never committed:
      `pypi.org.har` (a browser capture that **may contain PyPI session cookies**),
      `tmp_serp_sqlite_test.db`, `tests/accept/064_kwargs.exe`, `tests/accept/tmp_serp_*`,
      `libs/serp-io/tests/tmp_serp_io_*`.
- [ ] **P1** Harness is stable under load. There are known byte-diff and `0xC0000005`
      flakes when benchmarks run in parallel (see memory venom-axum-parity).
- [~] **P2** Local dev matches the CI Python pin: CI uses 3.12, the local venv is 3.11.9.
- [x] Three-OS CI matrix (ubuntu/macos/windows) runs differential, reject, rustc-agreement,
      LLVM and LSP smoke.

## 2. Releases & distribution

- [x] `serpentine-lang` on PyPI via trusted publishing (tag-push `release.yml`), latest `v0.6.0`.
- [x] **P0** `serpentine-lang` 0.7.0 + `serpentine-shim` 0.9.0 released to PyPI (tag `v0.7.0`, 2026-09-28).
- [~] **P0** Prebuilt runtime (dist-rt) 0.7.0 assets: the `v0.7.0` runtime-assets jobs failed on a PyPI index race (fixed in `release.yml` for future releases); rerun `gh run rerun 36400503901 --failed` once pip sees shim 0.9.0. `__version__` was stale at 0.5.0 (drives asset naming) — now synced.
- [x] **P0** The PyPI name `serp-cli` is taken by an unrelated project — resolved: published as `serpentine-argparse` (import name `serp_cli`).
- [x] **P1** Publish the `serp-*` libraries to PyPI: all 37 live (2026-09-29); `serp-io`/`serp-cli` ship as `serpentine-io`/`serpentine-argparse` (import names unchanged), `serp-fang` 0.3.1 depends on `serpentine-io`.
- [ ] **P1** Add a `CHANGELOG.md`. There's none; release notes live only in commit messages.
- [ ] **P1** Stability and versioning policy. Everything is `0.x` with no compatibility
      promise for the language surface, SE codes or runtime ABI.
- [~] **P2** Prebuilt runtime platforms. Covered: linux-x86_64, macos-arm64, windows-x86_64.
      Missing: linux-arm64, macos-x86_64, musl/Alpine.
- [ ] **P2** Public announcement (venues in [guides/publishing.md](guides/publishing.md)).

## 3. Language surface

- [x] Tier 0–2 static typing, ownership/borrowing, unions, enums, generics + protocols, PyVal
      ([features.md](features.md), [spec.md](spec.md)).
- [x] Classes: dataclasses, `__init__`/`__post_init__`, operators, properties, classmethods,
      single inheritance (D15 flattening).
- [x] Exceptions, first-class functions, decorators (D13), kwargs, iterator protocol.
- [x] Concurrency: `spawn`/`join` (D9 v1), `serp-threading` (D9 v2), asyncio baton runtime (D45).
- [ ] **P1** Python interop. D6 refuses foreign imports, so **no regular PyPI package can be
      used**; only `serp-*` libs work ([guides/interop.md](guides/interop.md)).
- [ ] **P1** General closures. Lambdas capture Copy values only; comprehensions allow one `for`
      and one `if`.
- [ ] **P1** `int` is int64 with an overflow trap, not a bignum. Code that relies on Python
      big ints diverges ([language/divergences.md](language/divergences.md)).
- [ ] **P1** Module system: only `from a.b import x`. Plain `import a.b` and relative imports are refused.
- [ ] **P2** Subtype polymorphism / `super()` / virtual dispatch. Out of scope by design
      (D15); document migration patterns for OO-heavy code.
- [ ] **P2** Returned borrows (SE209). `Sync[T]` and scoped borrows across threads; `Shared`
      can't cross threads.
- [ ] **P2** asyncio gaps: cancellation, `wait_for`, `async for`, `Task.result()`, one loop
      per process, mixed-type `gather`.
- [ ] **P2** `class Worker(Thread)` + `run()` subclassing.
- [ ] **P2** `Decimal` (D26 rejected); money-handling code needs a pattern or a library.

## 4. Compiler correctness & robustness

- [x] Differential corpus: accept 001–102 byte-identical across CPython, Backend A and
      Backend B (debug + release) on 3 OSes.
- [x] Reject corpus with exact SE codes; rustc-agreement harness at 0 disagreements.
- [x] Library dual-run suite (`tools/run_lib_tests.py`) runs across CPython, Rust and LLVM.
- [ ] **P0** Fix the open Backend-B `IfExp` defect: a non-Copy `str` ternary with a call arm
      crashes. Molt works around it; Backend A is clean ([libraries.md](libraries.md) Molt line).
- [?] **P1** Confirm the Backend-A `continue`-inside-`except` bug from Wave 4 is fixed and
      covered by an accept test.
- [ ] **P1** Compiler fuzzing: grammar/typed-AST fuzz that diffs CPython against both
      backends, and checks the checker never crashes on arbitrary input.
- [ ] **P1** Scale test: compile time and memory on a 10k–50k LOC program. Whole-program
      compilation has never been measured past the libs.
- [ ] **P2** Incremental / cached compilation for large projects.
- [ ] **P2** Diagnostics quality pass: every SE code has an example + fix in the docs.

## 5. Runtime safety & security — P1 for anything internet-facing

- [x] Ownership model rules out use-after-free and data races *in user code* (borrowck +
      rustc oracle).
- [x] `serp add` verifies wheel sha256; `serp.lock` pins exact versions.
- [ ] **P1** Audit the `unsafe` FFI runtime: `rt.rs` exports hundreds of `unsafe extern "C"`
      functions over raw pointers. Run the corpora under Miri (Backend A) and ASan/UBSan
      (Backend B).
- [ ] **P1** Fuzz every hand-written parser that sees untrusted input: HTTP request parsing
      (Venom/http-server), JSON, TOML, CSV, URL, regex compiler, DEFLATE inflate, zipfile,
      base64, TLS glue.
- [ ] **P1** ReDoS: the `serp-re` backtracking VM has no step limit or timeout.
- [ ] **P1** Resource limits: decompression-bomb caps (zlib/zipfile); HTTP header/body size
      limits, read timeouts and slowloris protection in Venom and http-server.
- [?] **P1** TLS (schannel/OpenSSL): verify certificate + hostname validation, and
      rejection of expired/self-signed certs by default in Fang.
- [ ] **P1** `SECURITY.md` with a vulnerability-disclosure contact and a supported-versions policy.
- [ ] **P1** `Shared` reference cycles leak (D3). Needs guidance or detection for long-running
      servers.
- [ ] **P2** Dependency audit of the runtime's Rust crates (`cargo audit`) in CI.

## 6. Running services in production (Venom stack)

- [x] Venom is a FastAPI drop-in (0.3.0) with threaded keep-alive, an event-loop server and
      async handlers.
- [x] Throughput reaches axum parity: 1.05–1.06x at w1/c16, 0.92–1.03x at w3/c64, from two
      runs on one i7 Windows box.
- [ ] **P1** Re-benchmark on Linux server hardware, and against multiple load generators on
      separate hosts.
- [ ] **P1** Soak test: 24h+ at steady load, checking RSS growth, fd/handle leaks and latency
      drift.
- [?] **P1** Graceful shutdown (SIGTERM/Ctrl-C drains in-flight requests), health checks, and
      restart behavior under a process manager or container.
- [ ] **P1** Venom middleware, `BackgroundTasks`, streaming responses, WebSockets, CORS
      ([libraries/venom.md](libraries/venom.md)).
- [ ] **P1** Observability. `serp-log` exists, but there are no metrics (Prometheus) or
      tracing (OpenTelemetry) libs.
- [?] **P1** Crash diagnostics: do native runtime errors report the `.py` file/line and a
      traceback, or only the message? Make it the former.
- [ ] **P2** Debugger support: DWARF/PDB line mapping back to the `.py` source for gdb/lldb/VS.
- [ ] **P2** Profiling guide (perf/VTune/ETW on generated binaries).
- [ ] **P2** HTTP/2; container image + deployment guide.

## 7. Ecosystem gaps for typical production apps

- [x] 37 `serp-*` libs, most of them CPython drop-ins ([libraries.md](libraries.md)).
- [ ] **P1** Database clients: PostgreSQL, MySQL, Redis. Only SQLite exists, and it's
      autocommit-only.
- [ ] **P1** Timezone support in `serp-datetime` (`zoneinfo` / tz-aware datetimes).
- [ ] **P1** Auth/crypto primitives: `hmac`, JWT, password hashing (bcrypt/argon2).
- [ ] **P2** Templating (Jinja-like), ORM/query builder, background job queue, cloud SDKs
      (S3 and similar).
- [ ] **P2** `serp-molt` `mode="plain"`/`mode="wrap"` validators; typed Scales storage (S3).

## 8. Developer experience

- [x] `serp new/init/run/add/remove/test/check/build`, `serp.toml` + `serp.lock`.
- [x] Source is valid Python, so black/ruff/mypy-style editors already work.
- [x] Docs: tour, ownership, migration, divergences, packages, publishing.
- [~] **P2** LSP: diagnostics only. Missing completion, hover, go-to-definition, and a VS Code
      extension.
- [ ] **P2** "Build a production web service" end-to-end tutorial (Venom + Molt + deployment).
- [ ] **P2** Error-code reference page with examples (currently spec §12 only).

## 9. Platforms

- [x] Windows, Linux and macOS are CI-tested; static native binaries.
- [ ] **P2** linux-arm64 (Graviton/Raspberry Pi) and musl CI + prebuilt runtime.
- [ ] **P2** Vs-Codon benchmark comparison (needs a Linux host).

## 10. Project governance

- [x] `LICENSE`, `README.md`, public GitHub repo.
- [ ] **P1** A CI badge and "status: experimental" note in `README.md` until L3 is reached.
- [ ] **P2** `CONTRIBUTING.md`, issue/PR templates, code of conduct.
- [ ] **P2** Bus factor: design docs let a second maintainer onboard (spec, DECISIONS,
      memory-style gotcha notes as docs).

---

## Suggested order

1. **Get to green.** Clear every **P0** in sections 1, 2 and 4: commit, fix CI, release shim +
   dist-rt, fix the IfExp bug. That makes it L2-ready.
2. **Harden.** Section 5 (fuzzing, sanitizers, limits, SECURITY.md) plus the crash diagnostics
   and soak test from section 6.
3. **Fill production gaps.** Postgres/Redis clients, timezones, hmac/JWT, metrics, and Venom
   middleware.
4. **Adoption.** Section 8 DX, section 9 platforms, section 10 governance, then the announcement.
