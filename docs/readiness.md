# The Serpentine Production-Readiness Checklist

> One line per item. `[x]` = done, `[~]` = partial, `[ ]` = open, `[?]` = unverified (someone
> must check before it can be ticked). Priority tags: **P0** = blocks *any* serious use,
> **P1** = blocks production services with real users, **P2** = needed for broad adoption.
> Each item names its evidence or the doc that owns it. [libraries.md](libraries.md) tracks
> library *features*; this doc tracks whether the project as a whole is safe to depend on.
>
> Last assessed: **2026-09-30**.

## Verdict

| Level | Meaning | Status |
|---|---|---|
| **L1 — Experimental** | Hobby projects, demos, benchmarks | ✅ Passed |
| **L2 — Internal tools** | CLIs, batch jobs, internal services where a crash costs little | ✅ **Reached 2026-09-30**: landed in `df1af15`, CI green on 3 OSes, released as 0.7.2 |
| **L3 — Production service** | Internet-facing, many users, on-call | ❌ Not yet (open P1s in security, ops and ecosystem) |

**Why not L3 yet:**
1. There's no versioning/stability promise: everything is `0.x`. (Distribution, CHANGELOG and SECURITY.md are done.)
2. Hardening first pass is done (fuzzing, Miri/ASan, limits, tracebacks, TLS check, soak), but
   there's no 24h Linux soak yet, no graceful SIGTERM drain, and Backend-B objects aren't sanitized.
3. There are no database clients besides SQLite.
4. There are no timezones, no metrics or tracing, and no debugger story.
5. Performance and soak testing has only been done on one Windows box.

The compiler itself is strong: every test corpus is byte-identical across CPython, Backend A
and Backend B on all three OSes, and the rustc-agreement harness reports 0 disagreements.

---

## 1. Source control & CI — P0

- [x] **P0** Commit + push the Phase-7 work — landed 2026-09-28 (`fdd7161`), Molt/Venom/Coil/Scales/asyncio/threading/queue/subprocess + accept 070–102.
- [x] **P0** Master CI is green on all three OSes (2026-09-28, run 36398975310). Fixed along the way: shim `__init_subclass__` forwarding broke `Generic` on CPython 3.12; Unix TLS build referenced a Windows-only `dec` buffer (now `tls_buffered`/`SSL_pending`); accept 102 timer gaps widened. The old `serp-base64` Linux abort no longer reproduces.
- [x] **P0** Committed + pushed the 2026-09-30 L2 work (`df1af15`): CI green on all three OSes (run 36750423875).
- [x] **P1** Released compiler **0.7.2** (tag `v0.7.2`), which fixes the silent `finally` skip on `break`/`continue`.
- [x] **P0** `release-lib.yml` works: trusted publishing first (via PyPI pending publishers, which bypassed the `429 Too many new projects created` limit the token route hit), `PYPI_API_TOKEN` fallback.
- [x] **P0** CI runs *every* lib suite. Verified 2026-09-30: `tools/run_lib_tests.py` auto-discovers all `libs/*/tests/*.py` (37 libs, no skip list), and CI was green on 2026-09-29 (run 36556498753); the `ci.yml` step label was renamed on 2026-09-30.
- [x] **P1** Stray artifacts: all gitignored (`*.har`, `*.exe`, `tmp_serp_*`), none ever committed (`git log --all`). The local copies and the `.rustic/tmp/pw-pypi-profile/` Chrome profile (logged-in PyPI session) were deleted on 2026-09-30. The server-side PyPI session expires on its own; to be sure, revoke it under pypi.org → Account settings → Sessions.
- [ ] **P1** Harness is stable under load. There are known byte-diff and `0xC0000005`
      flakes when benchmarks run in parallel (see memory venom-axum-parity). Also, as of 2026-09-30, `libs/serp-fang/tests/test_async_fang.py`
      fails **under CPython** about 3 times in 4 on the local Windows box (`OSError: connection reset` on the loopback POST, in the pure-Python
      `_serp_socket` facade); the native builds pass. CI passed it on 2026-09-29.
- [~] **P2** Local dev matches the CI Python pin: CI uses 3.12, the local venv is 3.11.9.
- [x] Three-OS CI matrix (ubuntu/macos/windows) runs differential, reject, rustc-agreement,
      LLVM and LSP smoke.

## 2. Releases & distribution

- [x] `serpentine-lang` on PyPI via trusted publishing (tag-push `release.yml`), latest `v0.7.1`.
- [x] **P0** `serpentine-lang` 0.7.0 + `serpentine-shim` 0.9.0 released to PyPI (tag `v0.7.0`, 2026-09-28); 0.7.1 (dist-info import roots for renamed dists) followed on 2026-09-29.
- [x] **P0** Prebuilt runtime (dist-rt) assets: `serp-rt-0.7.0-*` and `serp-rt-0.7.1-*` are attached to their GitHub releases for linux-x86_64, macos-arm64 and windows-x86_64 (all runtime-assets jobs green, verified 2026-09-30).
- [x] **P0** The PyPI name `serp-cli` is taken by an unrelated project — resolved: published as `serpentine-argparse` (import name `serp_cli`).
- [x] **P1** Publish the `serp-*` libraries to PyPI: all 37 live (2026-09-29); `serp-io`/`serp-cli` ship as `serpentine-io`/`serpentine-argparse` (import names unchanged), `serp-fang` 0.3.1 depends on `serpentine-io`.
- [x] **P1** `CHANGELOG.md` added 2026-09-30: per-version summaries from 0.4.0, plus an Unreleased section.
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

- [x] Differential corpus: accept 001–104 byte-identical across CPython, Backend A and
      Backend B (debug + release) on 3 OSes.
- [x] Reject corpus with exact SE codes; rustc-agreement harness at 0 disagreements.
- [x] Library dual-run suite (`tools/run_lib_tests.py`) runs across CPython, Rust and LLVM.
- [x] **P0** Backend-B `IfExp` defect (non-Copy `str` ternary with a call arm crashed): fixed 2026-08-30 in `llvmgen._ifexp`, and Molt uses the original ternary again. Regression guard added 2026-09-30: `libs/serp-molt/tests/test_schema_repeat.py`, which crashes a pre-fix compiler 10/10 times. Shape coverage is in accept 103.
- [x] **P1** Backend-A `continue`-inside-`except` bug: it was **still open** (rustc E0695) and is fixed 2026-09-30 with labeled loops. The same accept test (104) exposed a **silent miscompile in both backends**: `break`/`continue` leaving a `try` skipped the `finally`. Also fixed.
- [x] **P1** Backend-A E0381 (a local assigned in a `try` body, used after a diverging handler): fixed 2026-09-30. Scalar and Optional try-assigned locals get a zero initializer; covered by accept 106. Non-Copy locals in the same shape still need pre-initialization, but the failure is a rustc error, never a miscompile.
- [x] **P1** `return` inside `try`/`finally`: verified 2026-09-30 that it is **rejected at compile time** (SE201, reject r044), as is `break`/`continue` out of a `try` body. No silent `finally` skip is possible. Accept 105 covers the allowed shapes.
- [x] **P1** Compiler fuzzing (2026-09-30): `tools/run_compiler_fuzz.py` generates random well-typed programs and diffs CPython against both backends; 30/30 identical, and an 8-program smoke run is in CI. The checker-never-crashes-on-arbitrary-input variant is still open.
- [ ] **P1** Scale test: compile time and memory on a 10k–50k LOC program. Whole-program
      compilation has never been measured past the libs.
- [ ] **P2** Incremental / cached compilation for large projects.
- [ ] **P2** Diagnostics quality pass: every SE code has an example + fix in the docs.

## 5. Runtime safety & security — P1 for anything internet-facing

- [x] Ownership model rules out use-after-free and data races *in user code* (borrowck +
      rustc oracle).
- [x] `serp add` verifies wheel sha256; `serp.lock` pins exact versions.
- [~] **P1** Audit the `unsafe` runtime (2026-09-30):
      - **Miri** (`tools/run_miri.py`) runs Backend-A output for 19 FFI-free accept programs: all clean, no UB, stdout identical to CPython.
      - **AddressSanitizer** (`tools/run_asan.py`, nightly `-Zsanitizer=address`) runs all 101 single-file accept programs: clean.
      - Still open: ASan/UBSan on Backend B's LLVM objects, and Miri can't reach the FFI parts (sockets, TLS, SQLite).
- [x] **P1** Fuzz the untrusted-input parsers (2026-09-30): `tools/run_fuzz.py` covers JSON, TOML, URL, base64, regex, raw/zlib/gzip inflate and CSV.
      - 72k mutated cases over 4 seeds, CPython vs native: 0 divergences and 0 crashes after fixes. The only remaining difference is 2 known int64-vs-bignum cases.
      - Real bugs it found and fixed: `bytes.fromhex` whitespace; zlib Adler-32 placement and trailing data; gzip multi-member/padding; `str.strip`/`split`/`int()` treating `\x1c`–`\x1f` as whitespace like CPython.
      - A fixed-seed run is in CI. HTTP request parsing is covered by the limit tests rather than the fuzzer.
- [x] **P1** ReDoS: `serp-re` caps each match attempt at 1M VM steps and 10k recursion levels, raising `serp_re.error` in both worlds (`libs/serp-re/tests/test_redos.py`).
- [x] **P1** Resource limits (2026-09-30):
      - zlib/gzip/zipfile output is capped at 256 MiB (`libs/serp-zlib/tests/test_bomb.py`, a real 289 MB bomb).
      - HTTP bodies over 16 MiB get 413 before being read in http-server and in all three Venom readers (`test_limits.py`).
      - Heads are capped at 64 KiB, with 10 s socket read timeouts.
      - Slowloris is only partly handled: the timeout is per `recv`, not per request.
- [x] **P1** TLS (2026-09-30): `tools/run_tls_check.py` against badssl.com.
      - schannel: 6/6. Expired, self-signed, wrong-host and untrusted-root are refused with `OSError("certificate verify failed")`; the good site and `verify=False` return 200.
      - The OpenSSL path (Linux/macOS) runs in CI as an informational step.
- [~] **P1** `SECURITY.md` added 2026-09-30 (GitHub private vulnerability reporting, latest-only support). Still to do: enable private vulnerability reporting in the repo settings, and optionally add an email contact.
- [~] **P1** `Shared` reference cycles leak (D3). Guidance is written ([language/ownership.md](language/ownership.md) §7.1: `Weak` back-edges, owned per-request graphs, soak-check before deploying). There's still no runtime cycle detection.
- [x] **P2** Dependency audit: the runtime links **zero third-party crates** (only the in-tree `serp_rt`; the native dependencies are OS schannel, a dynamically loaded OpenSSL, and system SQLite), so `cargo audit` has nothing to scan (verified 2026-09-30).

## 6. Running services in production (Venom stack)

- [x] Venom is a FastAPI drop-in (0.3.0) with threaded keep-alive, an event-loop server and
      async handlers.
- [x] Throughput reaches axum parity: 1.05–1.06x at w1/c16, 0.92–1.03x at w3/c64, from two
      runs on one i7 Windows box.
- [ ] **P1** Re-benchmark on Linux server hardware, and against multiple load generators on
      separate hosts.
- [~] **P1** Soak test. Bounded run done 2026-09-30 with `tools/run_soak.py` (native Venom, 3 workers, 8 keep-alive clients, 600 s, Windows):
      10,433,661 requests (~17.3k rps); after warm-up RSS 5.7→5.7 MiB and handles 73→73. PASS.
      A 24h+ run on Linux server hardware (with latency-drift tracking) is still to do.
- [~] **P1** Shutdown and restart (2026-09-30): killing the server releases the listening port immediately, so a process manager can restart it at once (checked by `run_soak.py`).
      **Not implemented:** graceful drain on SIGTERM/Ctrl-C (there's no signal handling, so in-flight requests are dropped), and a built-in health endpoint.
- [ ] **P1** Venom middleware, `BackgroundTasks`, streaming responses, WebSockets, CORS
      ([libraries/venom.md](libraries/venom.md)).
- [ ] **P1** Observability. `serp-log` exists, but there are no metrics (Prometheus) or
      tracing (OpenTelemetry) libs.
- [x] **P1** Crash diagnostics (2026-09-30): uncaught native errors print a CPython-style traceback (`.py` file, line and function per frame). It's recorded on the error path only, in both backends, and `tools/run_traceback_check.py` in CI checks the frames match CPython's.
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
- [x] **P1** CI + PyPI badges and a "status: experimental" warning in `README.md` (2026-09-30).
- [ ] **P2** `CONTRIBUTING.md`, issue/PR templates, code of conduct.
- [ ] **P2** Bus factor: design docs let a second maintainer onboard (spec, DECISIONS,
      memory-style gotcha notes as docs).

---

## Suggested order

0. **Land L2 (immediate, short).** Commit + push the 2026-09-30 work, get CI green on all three
   OSes (§1), tag `v0.7.2` (silent-miscompile fix), then delete the stray artifacts and revoke the
   PyPI browser session.
1. **Close the `finally` family — DONE 2026-09-30.** `return` in `try`/`finally` is rejected at
   compile time (SE201), and the E0381 try-init disagreement is fixed (accept 105/106).
2. **Harden — DONE 2026-09-30** (first pass): crash tracebacks, ReDoS/bomb/body limits, 256 MiB
   stacks, a TLS check, parser + compiler differential fuzzers (which found and fixed 4 real
   divergences), Miri 19/19 and ASan 101/101 clean, and a 10-minute soak PASS.
   Still open for L3: a 24h Linux soak, graceful SIGTERM drain, Backend-B sanitizers, and making
   the checker never crash on arbitrary input.
3. **Fill production gaps.** Postgres/Redis clients, timezones, hmac/JWT, metrics, and Venom
   middleware.
4. **Adoption.** Section 8 DX, section 9 platforms, section 10 governance, the versioning policy, then
   the announcement.
