# Library Sync Status

> One-page health check for the `libs/` monorepo: what each library mirrors,
> whether it is a **drop-in** for its counterpart, which other serp libraries
> it uses, and whether its declared dependency pins match the versions
> currently in the repo. Regenerate/update this table whenever a library
> version is bumped. Last updated: **2026-07-22** (logging + regex push:
> serp-log and serp-re became drop-ins at 0.2.0; all 29/29 library dual-run
> tests green — CPython + Rust + LLVM byte-identical).

## Status table

"Uses" lists source-level imports of other serp libraries (a lib's own
`*_core` runtime module doesn't count — it ships inside the same package).
"Pin in sync?" compares the version pinned in the lib's `serp.toml`
`[dependencies]` against the dependency's current version in this repo.

| Library | Version | Drop-in? | Counterpart | Uses (serp libs) | Pin in sync? |
|---|---|---|---|---|---|
| serp-base64 | 0.1.0 | ✅ | `base64` | — | n/a |
| serp-cli | 0.2.0 | ✅ | `argparse` (D11: `args["dest"]` indexing) | — | n/a |
| serp-csv | 0.2.0 | ✅ | `csv` (reader/writer/DictReader) | — | n/a |
| serp-datetime | 0.2.0 | ✅ | `datetime` (date/datetime/timedelta) | serp-time | ⚠️ **undeclared** (no `[dependencies]` entry for serp-time) |
| serp-fang | 0.2.0 | ✅ | `httpx` (third-party counterpart) | serp-socket, serp-url, serp-base64, serp-json, serp-io, serp-zlib, serp-time, serp-uuid | ⚠️ **serp-json pinned 0.1.0, repo has 0.2.0**; serp-time + serp-uuid undeclared |
| serp-hashlib | 0.1.0 | ✅ | `hashlib` (sha256/sha1/md5) | — | n/a |
| serp-http-server | 0.1.0 | ✅ | `http.server` | serp-socket (0.1.0) | ✅ |
| serp-io | 0.1.0 | ✅ | `io` (StringIO/BytesIO) | — | n/a |
| serp-itertools | 0.2.0 | ✅ | `itertools` (lazy iterator classes; user iterator protocol) | — | n/a |
| serp-json | 0.2.0 | ✅ | `json` (PyVal-powered) | — | n/a |
| serp-log | 0.2.0 | ✅ | `logging` (D12: runtime-held registry; core `serp_log_core`) | — | n/a |
| serp-math | 0.1.0 | ✅ | `math` | — | n/a |
| serp-os | 0.1.0 | ✅ | `os` (env/fs subset) | — | n/a |
| serp-pathlib | 0.2.0 | ✅ | `pathlib` (Path) | serp-os | ⚠️ **undeclared** (imports `serp_os_core`, no `[dependencies]` entry) |
| serp-random | 0.1.0 | ✅ | `random` (MT19937 bit-exact) | — | n/a |
| serp-re | 0.2.0 | ✅ | `re` (backtracking engine; 30530/30533 differential) | — | n/a |
| serp-secrets | 0.1.0 | ✅ | `secrets` | — | n/a |
| serp-socket | 0.1.0 | ✅ | `socket` | — | n/a |
| serp-sqlite | 0.2.0 | ✅ | `sqlite3` (PyVal rows) | — | n/a |
| serp-statistics | 0.1.0 | ✅ | `statistics` | serp-math (0.1.0) | ✅ |
| serp-strings | 0.1.0 | ✅ | `textwrap` | — | n/a |
| serp-structs | 0.1.0 | ✅ | `heapq` + `bisect` | — | n/a |
| serp-test | 0.1.0 | ❌ equivalent | `unittest` (blocked: inheritance + reflection; `serp test` covers it) | — | n/a |
| serp-time | 0.1.0 | ✅ | `time` (subset) | — | n/a |
| serp-tomllib | 0.2.0 | ✅ | `tomllib` (PyVal dict) | — | n/a |
| serp-url | 0.1.0 | ✅ | `urllib.parse` | — | n/a |
| serp-uuid | 0.1.0 | ✅ | `uuid` (v4 only) | — | n/a |
| serp-zipfile | 0.2.0 | ✅ | `zipfile` (real ZipFile class) | serp-zlib (0.1.0) | ✅ |
| serp-zlib | 0.1.0 | ✅ | `zlib` (+ gzip helpers) | — | n/a |

Shim (`serpentine` PyPI package): **0.5.0** — `dataclass` wrapper mapping
empty `[]`/`{}` field defaults to `default_factory`; all libraries dual-run
against it.

## ⚠️ Drift found (declaration-level, not functional)

Everything above **works** right now — the full dual-run suite passes, so no
library is functionally broken by another's update. The drift is in the
metadata, which matters the moment libraries are installed from a registry
instead of built from repo paths:

1. **serp-fang pins `serp-json = "0.1.0"`** but serp-json is 0.2.0 (PyVal
   rewrite). Fang's imports (`dumps`, `loads`) survived the rewrite, so the
   pin just needs bumping to 0.2.0.
2. **Undeclared dependencies** (import exists, no `[dependencies]` entry):
   - serp-datetime → serp-time (`from serp_time import time`)
   - serp-pathlib → serp-os (`from serp_os_core import ...`)
   - serp-fang → serp-time (`monotonic`) and serp-uuid (`u4_str`)

   These resolve today because the test harness/build roots see the whole
   monorepo; a registry install of just the one package would miss them.

Test-only cross-lib imports (not package deps, listed for awareness):
serp-sqlite's tests use serp-os; serp-http-server's tests use serp-socket.

## How to keep this in sync

- When bumping a library's version, grep `libs/*/serp.toml` for pins on it
  and update this table + any stale pins in the same change.
- Functional verification is always `python tools/run_lib_tests.py`
  (29/29 = every library byte-identical across CPython, Rust and LLVM).
- Drop-in status of record lives in `docs/language/python-equivalence.md`;
  this file is the quick dependency/version view.
