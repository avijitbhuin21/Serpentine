# Testing & Verification

How Serpentine checks that the same `.py` file behaves the same under CPython and both native
backends, and how the hardening tools are run. Everything lives in `tools/`. Run from the repo
root with the dev venv active (`.\.venv\Scripts\Activate.ps1`) and `PYTHONPATH=shim/src`.

## Core suites (CI, every push, 3 OSes)

| Command | What it checks |
|---|---|
| `python tools/run_accept_tests.py` | Every `tests/accept/*.py` runs clean under CPython. |
| `python tools/check_reject_tests.py` | Every `tests/reject/r*.py` is well-formed and annotated with its expected SE code. |
| `python tools/run_reject_serp.py` | `serp check` rejects each reject test with the **exact** SE code. |
| `python tools/run_differential_tests.py` | Accept corpus: CPython vs Backend A (Rust) stdout + exit code, byte-identical. |
| `python tools/run_llvm_differential.py` | Accept corpus: CPython vs Backend B (LLVM), debug and release. |
| `python tools/run_rustc_agreement.py` | The borrow checker agrees with rustc on every reject case (0 disagreements). |
| `python tools/run_lib_tests.py [pattern]` | Every `libs/*/tests/*.py`: CPython vs Rust vs LLVM. |
| `python tools/run_lsp_smoke.py` | `serp lsp` publishes diagnostics over stdio. |
| `python tools/run_traceback_check.py` | Native crash tracebacks list the same `.py` (line, function) frames as CPython, in every backend; a caught error leaves no frames behind. |
| `python tools/run_fuzz.py --per-kind 300 --seed 20260930` | Parser fuzz smoke (see below). |
| `python tools/run_compiler_fuzz.py --seed 1 --count 8` | Compiler fuzz smoke (see below). |
| `python tools/run_tls_check.py` | Fang refuses expired, self-signed, wrong-host and untrusted-root certificates (badssl.com). It needs the network, so it's informational in CI: read the `tls check (...)` line. |

## Fuzzing

**Parser differential fuzzer** — `python tools/run_fuzz.py [--seed N] [--per-kind N] [--backend llvm|rust]`.
Mutates seed inputs for JSON, TOML, URL, base64, regex, raw/zlib/gzip inflate and CSV. Every case
runs through `tools/fuzz/driver.py` under CPython and as a native binary, and the verdicts must
match. A native crash is bisected to the first crashing case; int64-vs-bignum differences are
reported separately as known. Add a parser by adding seeds in `run_fuzz.py` and a branch in the
driver.

**Compiler differential fuzzer** — `python tools/run_compiler_fuzz.py [--seed N] [--count N]`.
Generates random well-typed programs (bounded int arithmetic, strings, lists, branches, loops,
helper functions, `try`/`except`) and requires identical output from CPython, Backend A and
Backend B. Failing programs are kept in the printed temp directory.

**Checker robustness fuzzer** — `python tools/run_check_fuzz.py [--seed N] [--count N]`. Mutates
the accept/reject corpora line- and token-wise (plus random garbage) and runs the checker
in-process via `serpentine_lang.api.check_source`. Any escaping Python exception is a crash;
crashing inputs are saved.

**HTTP request fuzzer** — `python tools/run_http_fuzz.py [--seed N] [--count N] [--backend ...]`.
Builds `tools/shutdown/app.py` per backend and serving mode and throws malformed requests at it.
Every reply must be a well-formed status line or a close, `/healthz` must keep answering, and the
process must stay alive.

## Service checks

- **Graceful shutdown** — `python tools/run_shutdown_check.py`: real SIGTERM / Ctrl-Break while a
  1 s request is in flight; the request must complete, new connections must be refused and the
  process must exit 0 (both backends × `serve_async`/`serve_on`).
- **Scale** — `python tools/run_scale_test.py [--loc 50000]`: generates a multi-module program,
  times `serp check` and both builds, reports the compiler's peak memory and compares the
  binaries' output with CPython.

## Memory-safety checks (local, nightly toolchain)

Both need `rustup toolchain install nightly`.

- **Miri** — `python tools/run_miri.py [test ...]` (`rustup +nightly component add miri rust-src`).
  Runs Backend-A output for FFI-free accept programs under Miri, an undefined-behaviour detector,
  and compares stdout with CPython. Loop-heavy programs are too slow for Miri and are left out
  of the default set.
- **AddressSanitizer** — `python tools/run_asan.py [test ...]`. Builds the accept corpus with
  Backend A and `-Zsanitizer=address` (through the `SERP_RUSTC_FLAGS` env hook) and fails on any
  ASan report or output change. On Windows it puts MSVC's `clang_rt.asan_dynamic` DLL on `PATH`
  automatically. `--backend llvm` does the same for Backend B: the runtime and link stub are
  instrumented, but the LLVM-emitted program code isn't (llvmlite has no sanitizer passes).

## Soak test

`python tools/run_soak.py [--seconds 600] [--clients 8] [--workers 3]` builds `tools/soak/app.py`
(a Venom service) in release mode, drives it with keep-alive clients, and samples RSS and handle
count every 15 s. It fails if either keeps growing after warm-up, and checks that the port is
released once the server is killed. Use `--seconds 86400` for the 24h run.

## Conventions

- New behaviour gets an accept test (`tests/accept/NNN_name.py`, printing deterministic output);
  new rejections get a reject test whose first line is `# serp-reject: SEnnn category`.
- Library tests live in `libs/<lib>/tests/` and must print identical output in all three runs.
  Scratch files must start with `tmp_serp_` (gitignored).
- A regression test is only trusted once it has been shown to fail on the buggy compiler.
  Re-introduce the bug temporarily and confirm the test catches it.
- Known flakes: `serp-fang/test_async_fang` under CPython on Windows, and `serp-asyncio/test_asyncio`
  under heavy parallel load ([readiness.md](../readiness.md)).
