# Python Equivalence — drop-in status of the Serpentine libraries

> Status of the effort to make every `serp-*` library a **drop-in replacement**
> for its CPython stdlib counterpart: same names, same signatures, same observable
> behavior — with ownership-aware Serpentine + Rust runtime internals, compiled to
> native binaries. Updated 2026-07-23 after the itertools push: the user
> iterator protocol (`__iter__`/`__next__`, `for`-loop lowering, `next()`)
> made serp-itertools a lazy drop-in without generators; only unittest
> (inheritance + reflection) remains blocked, deliberately.

## The architecture (how a drop-in library is built)

Two layers per library:

1. **Core** — a compiler-known rtlib module (`serp_<name>_core`) whose functions map
   to `extern "C"` runtime primitives (prelude.rs / rt.rs). Explicit, fixed-arity,
   Rust-flavored. The PyPI dist ships a CPython delegate for the same module so the
   identical source dual-runs.
2. **Facade** — a pure-Serpentine module (`serp_<name>`) exposing the *exact* stdlib
   API (names, signatures, defaults, keyword arguments, error messages) and
   delegating to the core. This is the file users import.

The dual-run differential harness (`tools/run_lib_tests.py`) byte-compares CPython +
both native backends, so "drop-in" is continuously verified, not just claimed.

Language features that made facades possible (all shipped):
- keyword arguments (call-site desugar; functions, methods, dataclass ctors)
- literal default parameter values (incl. dataclass field defaults and bytes
  literals like `buf: bytes = b""`)
- int→float coercion at call arguments (`sqrt(2)`)
- negative-literal constants/defaults (`level: int = -1`)
- user exception classes, first-class functions, operator overloading,
  bytes/bytearray (from the Phase 7.0 prerequisite push)
- `NotImplementedError` added to the builtin exception set (RuntimeError child)
  for zipfile's unsupported-compression error
- `__str__` dunder (drives `str(x)`, `print(x)`, f-strings; typecheck-level
  desugar, zero backend changes)
- `__repr__` dunder — a true backend override: rustgen's `PyShow::py_repr` and
  llvmgen's `repr` helper call the user method, so containers, f-string `!r`,
  and `print()` (when no `__str__`) all show stdlib-style reprs
  (`Path('x')`, `datetime.date(2024, 1, 5)`). Shape-checked
  `(self: Ref[C]) -> str`; not on generic classes; a raise during repr aborts.
- `__post_init__` validation bodies — `(self: Mut[C]) -> None`, run by both
  backends after every dataclass construction (matching CPython's dataclass
  hook); it can validate (raise) and normalize (assign fields), which is what
  makes `date(2021, 2, 29)` raise like the stdlib. Not on generic classes.
- empty `[]` / `{}` dataclass field defaults (fresh container per construction;
  the shim's `dataclass` maps them to `default_factory` under CPython) — this
  is what lets a class own derived state that `__post_init__` fills in
- **user iterator protocol** — `__next__(self: Mut[C]) -> T` (raises
  StopIteration when done) plus shape-enforced `__iter__` (`return self`);
  `for x in obj:` lowers in typecheck to a while/`__next__`/except loop
  (rustgen emits a labeled match-loop skeleton to satisfy rustc's
  definite-init analysis), `next(obj)` desugars via op_calls, lambdas infer
  against generic `Callable[[T], bool]` params (two-phase unification), and
  `Callable` signatures may mention type variables (Copy-checked at
  instantiation) — this is what made lazy itertools possible without `yield`
- `list.append(x)` now propagates the element type as the argument's expected
  type (lambdas and heterogeneous/empty literals work as append arguments)
- `@property` (attribute read desugars to a zero-arg method call)
- `@staticmethod` (lifted to module functions at load time; `Class.method(...)`
  call sites dispatch statically — classmethod-style constructors)
- `with` on user objects (`__enter__` must be exactly `return self`; the
  frontend rewrites the block to assign + try/finally `__exit__(None, None,
  None)`, so `__exit__` runs on exception paths like CPython; `__exit__`'s
  three params are None-typed and never carry exception details natively)
- **`PyVal` dynamic values (Tier 2, DECISIONS.md D10)** — an immutable
  refcounted Copy handle over None/bool/int/float/str/bytes/list/dict with
  `[]` indexing, truthiness, `==`/`!=` (Python cross-numeric + deep-container
  semantics), `len()`, iteration, `in`, explicit `int()/float()/str()/bool()/
  bytes()` extraction and the `pyval_kind()` discriminator; scalars, str-keyed
  dicts, and lists implicitly coerce *into* PyVal at annotated boundaries
  (`json.dumps({"a": [1, "x"]})` just works)

## ✅ Done — true drop-ins (verified against stdlib under CPython)

| Library | Mirrors | Notes / accepted caps |
|---|---|---|
| `serp-random` | `random` | MT19937 bit-for-bit (seeding, genrand_res53, `_randbelow`): seeded streams equal CPython's exactly. `seed/random/randint/uniform/randrange/getrandbits/choice/shuffle`. getrandbits ≤ 63 bits; no `sample/choices/Random`; messages pinned to CPython 3.11. |
| `serp-math` | `math` | 60+ names verified identical. Int results cap at int64 (`factorial` > 20 → OverflowError). Missing: `gamma/lgamma/erf/erfc/remainder` (need CPython's hand-rolled algorithms for bit parity), `prod` (overloads), `dist`. `hypot` is 2-arg. |
| `serp-statistics` | `statistics` | `StatisticsError` + CPython messages, `fmean/geometric_mean/harmonic_mean/covariance/correlation`, `quantiles(n=, method=)`. mean/variance are float-based (CPython uses exact rationals — last-ulp differences possible). Missing: `mode/multimode/median_grouped/NormalDist`. |
| `serp-secrets` | `secrets` | Full surface incl. optional `nbytes` (default 32), `randbits` (≤ 63), `choice`, `compare_digest` (plain equality, not constant-time). No `SystemRandom`. |
| `serp-hashlib` | `hashlib` | Object API: `sha256(b"x")`, `.update()`, `.hexdigest()`, `.digest()`, `.copy()`. `update()` re-hashes the buffer (O(n) memory). Only sha256/sha1/md5; no `new()`/`name`/`digest_size`. |
| `serp-base64` | `base64` | Bytes-first: b64/b32/b16 + `standard_`/`urlsafe_` variants, `altchars`, `validate`, `casefold`. Errors are ValueError (stdlib: `binascii.Error`, a ValueError subclass). No a85/b85/b32hex. |
| `serp-time` | `time` (subset) | `time/monotonic/sleep/time_ns/monotonic_ns/perf_counter/perf_counter_ns` — stdlib-named and call-compatible. No struct_time/strftime/localtime. |
| `serp-zlib` | `zlib` | `crc32/adler32` with running `value`, `compress(level=-1)`, `decompress(wbits=)` routing (15 zlib / -15 raw / 31 gzip), `MAX_WBITS`/`Z_*` constants. Compressed bytes differ between worlds (interoperable by design). No compressobj/decompressobj. |
| `serp-os` | `os` (env/fs subset) | `getenv(key, default=None)`, `putenv/unsetenv`, `getcwd/chdir`, `mkdir/rmdir/remove/unlink`, `listdir(path=".")`. Caps: error messages normalized (not `[Errno N]` forms), `listdir` always sorted, `putenv` updates `getenv` (CPython decouples them), no `environ` mapping. Filesystem predicates (`exists/is_file/is_dir`) live in `serp_os_core` (stdlib puts them in `os.path`). |
| `serp-strings` | `textwrap` | Full TextWrapper algorithm: `wrap/fill` with all options (indents, `fix_sentence_endings`, `break_long_words`, `break_on_hyphens` incl. hyphenated-word/em-dash splitting, `max_lines`/`placeholder`), `shorten`, `dedent`, `indent` — 1201/1201 differential checks vs stdlib. Caps: `\w` classification is ASCII-based; `indent()` takes no predicate; options are also positional. |
| `serp-structs` | `heapq` + `bisect` | `heappush/heappop/heapify/heappushpop/heapreplace` and `bisect_left/bisect_right/bisect/insort_left/insort_right/insort` (with `lo`/`hi`) use CPython's exact algorithms — heap layouts and error messages match (14k randomized checks). Cap: int elements only until protocol-bounded generic ordering exists. |
| `serp-io` | `io` (StringIO/BytesIO) | Object API with CPython messages: read/readline(size)/readlines/write/writelines/seek(whence quirks incl. BytesIO clamping + StringIO's cur-relative-only)/tell/truncate/getvalue/flush/close/`closed`, plus `with StringIO() as f:` context-manager support. Caps: no newline translation param, `read(None)` unsupported. |
| `serp-pathlib` | `pathlib` (PurePosix-ish) | `Path` dataclass with stdlib-shaped **properties** (`p.name/stem/suffix/parent/parts` — no parens), `/` operator, `str(p)`/`print(p)` parity via `__str__`, `__repr__` as `Path('a/b')` (as_posix form), `Path.cwd()` static constructor, `with_suffix/with_name`, `exists/is_file/is_dir/mkdir/rmdir/unlink/iterdir`, `read_text/write_text/read_bytes/write_bytes`, `as_posix`, `==`. Caps: ctor takes one string, `parts` is a list (not tuple), `iterdir` eager, repr says `Path(...)` — not the platform-flavored `WindowsPath`/`PosixPath` (our paths are portable). |
| `serp-zipfile` | `zipfile` | `ZipFile(file, mode="r", compression=ZIP_STORED)` is a **real class** (`__post_init__` opens/parses the archive and raises stdlib errors), object API (`namelist/read/writestr/close`, modes r/w/a, `ZIP_STORED`/`ZIP_DEFLATED`), **`with ZipFile(...) as z:` support** (close/flush on exit, incl. exception paths), stdlib error types and messages. Caps: `writestr` takes bytes only, fixed DOS timestamp, ctor param is `filename` (not `file`), internal `entries/compress/closed` fields visible as extra defaulted ctor params. |
| `serp-csv` | `csv` (reader/writer) | `reader(lines)` matches csv.reader byte-for-byte on the default dialect (quoted multi-line fields, blank-line `[]` rows, literal mid-field quotes, EAT_CRNL semantics, `Error` with CPython's message) — 3k fuzz checks; eager list instead of iterator. `writer()` matches csv.writer quoting/CRLF exactly but owns its buffer (`getvalue()`) since storing a borrowed file object is rejected by the ownership model; fields are str-only. |
| `serp-datetime` | `datetime` (subset) | `date/datetime/timedelta` are **real classes**: `__post_init__` validation with CPython 3.11 messages (`date(2021, 2, 29)` raises), timedelta keyword normalization in the ctor, stdlib field names, `isoformat(sep)`, `toordinal/weekday/isoweekday/replace`, comparisons, `+`/`-` arithmetic, `total_seconds`, `datetime.utcnow()` static ctor, and `str()`/`repr()` parity (`datetime.date(2024, 1, 5)`, zero-component-omitting `datetime.timedelta(...)` reprs) — 9k+ randomized checks vs stdlib. Caps: timedelta exposes zeroed `milliseconds/minutes/hours/weeks` fields (normalization inputs), int-only timedelta args, one `__sub__` per class (subtract a timedelta by adding its negation), no strftime/timezones/local-time `today()`/`now()`. |
| `serp-uuid` | `uuid` | `uuid4()` returns a `UUID` object that prints as the dashed hex string; `.hex/.urn/.version/.variant` properties; `parse()` builds one from text (subset of `UUID(hex=...)`). Caps: only v4 generation; no `.int/.bytes/.fields` (int exceeds int64). |
| `serp-json` | `json` | **PyVal-powered (D10).** `loads` returns nested dynamic values; `dumps(obj, ensure_ascii=True, sort_keys=False)` accepts them. CPython 3.11 JSONDecodeError *messages* on ValueError (12k differential checks incl. error-message parity); NaN/Infinity round-trip. Caps: ints cap at int64 natively; no `load/dump` file variants, `indent`, `separators`, `object_hook`, or `JSONDecodeError` type (plain ValueError). |
| `serp-tomllib` | `tomllib` | `loads` returns a PyVal dict; `TOMLDecodeError` (ValueError subclass). TOML subset: comments, bare/quoted/dotted keys, basic/literal strings, decimal ints, floats, bools, single-line arrays, `[a.b]` headers. Caps: no dates/times, inline tables, arrays-of-tables, multi-line strings/arrays, hex/oct/bin ints; error messages use its own `line N:` format; no `load(fp)`. |
| `serp-sqlite` | `sqlite3` | `connect() -> Connection`, `cursor()`, `execute(sql, params)` with `?` placeholders (params list of int/float/str/bytes/None), `fetchone() -> row | None`, `fetchall()`, `rowcount`/`lastrowid`, `commit()` (no-op, autocommit), `close()`, `Error`/`DatabaseError`/`OperationalError`/`ProgrammingError`. Rows are PyVal **lists, not tuples**. Caps: no `description`, `executemany`, `row_factory`, transactions, or context-manager `Connection`. |
| `serp-csv` (DictReader) | `csv.DictReader` | `DictReader(lines, fieldnames=None, restval=None)` returns an eager list of PyVal dict rows; header/fieldnames semantics, blank-row skipping, and restval fill match CPython. Caps: eager (not an iterator); no `restkey` (extra fields dropped — dict keys must be str); no dialect options. |
| `serp-cli` | `argparse` | **PyVal-powered.** `ArgumentParser(prog=, description=)`, `add_argument()` with short/long option strings, `store`/`store_true`/`store_false`, `default`, `required`, `help`; `parse_args()` (explicit list or `sys.argv[1:]`) returns a dict-shaped PyVal Namespace; usage/help text and error messages byte-match argparse 3.11 (15/15 parity checks incl. exit codes 0/2). Caps: values read as `args["dest"]` (attribute access on dynamic values is not in the subset — deliberate, see triage), Namespace prints as a dict, errors go to stdout (no stderr in the subset), no nargs/type/choices/metavar/subparsers, no fused `-ovalue` shorts, no help line wrapping. |
| `serp-log` | `logging` | **Runtime-held global state (D12).** `getLogger` + dotted-name effective-level inheritance, `setLevel/getEffectiveLevel/isEnabledFor/level`, `debug..critical/log` on loggers and module level (module-level calls basicConfig implicitly like CPython), `basicConfig(level=, format=, filename=, filemode=)` configure-once semantics, last-resort bare-message stderr handler when unconfigured, `getLevelName` incl. `Level N` — 19/19 parity checks incl. byte-identical file output and subprocess-verified stderr. Caps: messages are pre-formatted strings (f-strings, no %-args), format fields limited to `%(levelname)s/%(name)s/%(message)s`, no Handler/Formatter/Filter objects, no `exception()`. |
| `serp-re` | `re` | **True backtracking engine** (compiled instruction program + recursive VM): first-alternative-wins, greedy/lazy quantifiers with full backtracking into repeated bodies, capture groups (last iteration wins, incl. CPython's final-empty-iteration capture update), CPython's must-advance empty-match scan rule, `Match` objects (`group/groups/start/end/span/string`, CPython repr), `Pattern` via `compile()`, `match/fullmatch/search/findall/finditer/sub/split/escape`, `error` with CPython 3.11 messages, flags I/M/S (combine with `+`) — **30530/30533 differential checks vs `re`** (3k random pattern fuzz; the 2 diffs are capture positions inside counted repetitions of lazy nullable bodies). Caps: no backreferences/lookarounds/named-group access (loud errors), ASCII `\w`, findall with 2+ groups raises (use finditer), `groups()` is a PyVal list not a tuple, split fills unmatched group parts with `''`, string-template `sub` only, finditer eager, `{m,n}` ≤ 1000, deep quantified matches recurse. |
| `serp-itertools` | `itertools` | **Lazy iterator classes** over the user iterator protocol (no `yield` needed): `count/cycle/repeat` are genuinely infinite, `next()` and `for` drain them like CPython — 8801/8801 randomized differential checks vs `itertools`. Full surface: `count/cycle/repeat/chain/islice/compress/accumulate/pairwise/product/zip_longest/takewhile/dropwhile/filterfalse/batched/permutations/combinations/combinations_with_replacement`. Caps: inputs are `list[T]` (snapshotted, Copy elements); `chain/product/zip_longest` are two-input same-type; combinatoric functions and `batched` yield `list[T]` rows (not tuples); `repeat` uses `times=-1` and `islice` uses `stop=-2`/`-1` as sentinels; `accumulate` is `+`-only; `zip_longest` requires `fillvalue`; no `starmap/groupby/tee`. |

## 🚧 Remaining — what blocks each library

### Blocked by missing language features (library work cannot fix these)

| Library | Mirrors | Blocker |
|---|---|---|
| `serp-test` | `unittest` | `TestCase` requires inheriting from a library base class plus reflection-based method discovery (`test_*`) — no inheritance across modules or runtime introspection. The `serp test` runner covers the practical need. |

### Deliberate divergences on shipped drop-ins

- **Namespace indexing** (argparse): `parse_args()` returns a dict-shaped
  PyVal read as `args["verbose"]`, not `args.verbose`. Attribute sugar on
  PyVal was rejected deliberately: it would make *every* compiled PyVal
  accept `.attr` that CPython plain dicts raise `AttributeError` on,
  breaking the dual-run guarantee far beyond argparse.
- **`with` caveats**: `return` inside a user-object `with` body is rejected
  (the lowering is try/finally and return-in-finally is a Tier-2 error);
  `__exit__` never receives exception details (its three params are
  None-typed) and cannot suppress exceptions.
- **Storing borrows**: csv's `writer(fileobj)` cannot hold the file it writes
  to; the writer owns a buffer instead (`getvalue()`).
- **Extra visible fields**: classes built on `__post_init__` normalization
  expose their working fields as defaulted ctor params (timedelta's zeroed
  `milliseconds/minutes/hours/weeks`, ZipFile's `entries/compress/closed`) —
  a strict superset of the stdlib signatures.

## Remaining blockers, triaged (feasible now → impossible)

**Tier 1 — small compiler additions: SHIPPED 2026-07-22.** `__str__`,
`@property`, `@staticmethod`, `with` on user objects (see the language-features
list above). This closed serp-uuid and erased the property/classmethod/with
divergences on Path/StringIO/BytesIO/ZipFile/datetime.

**Tier 2 — the big multiplier: `PyVal` dynamic value type — SHIPPED
2026-07-22 (../decisions.md D10).** The compiler-known boxed dynamic value
(immutable refcounted Copy handle over None/bool/int/float/str/bytes/list/dict
with `[]`, truthiness, `==`, `len`, iteration, `in`, explicit extraction,
`pyval_kind()`, and implicit coercion into PyVal at annotated boundaries)
landed across typecheck + both backends + prelude.rs/rt.rs. It flipped
**serp-json, serp-tomllib, serp-sqlite, and csv.DictReader** to drop-ins and
unblocks argparse's Namespace (dict-shaped).

**Tier 3 — big but purely mechanical (no language blocker):**
- ~~`serp-re`~~ — **SHIPPED 2026-07-22**: full backtracking engine rewrite
  (instruction program + recursive VM, capture groups, Match/Pattern objects,
  30530/30533 differential checks vs CPython `re`).
- ~~`serp-log`~~ — **SHIPPED 2026-07-22**: the global-singleton question was
  answered by D12 (runtime-held state in `serp_log_core`, precedent:
  MT19937); logging is a drop-in for the common surface.
- ~~`serp-cli`~~ — **SHIPPED 2026-07-22** as an argparse drop-in over PyVal
  (dict-shaped Namespace; `args["dest"]` indexing is the documented
  divergence — see "Deliberate divergences").
- ~~`__repr__` backend override + `__init__` validation bodies~~ — **SHIPPED
  2026-07-22** as `__repr__` + `__post_init__` (see the language-features
  list); date/datetime/timedelta/ZipFile are real classes and Path has a
  stdlib-style repr.

**Tier 4 — genuinely big language features (Wave-6 scale):**
- ~~Generators/`yield` (serp-itertools)~~ — **made unnecessary 2026-07-23**:
  the user iterator protocol (`__iter__`/`__next__` + `for`-lowering +
  `next()`) shipped serp-itertools as a lazy drop-in with hand-written
  state-machine classes; `yield` itself remains a Wave-6 item for user code
  ergonomics only.
- Inheritance + reflection discovery (serp-test/unittest): large type-system
  change for the lowest-value target — `serp test` covers the need.

**Impossible (by design, not on the blocker list):** `eval`/`exec`, runtime
monkey-patching, dynamic class creation — these conflict with the AOT
whole-program model and stay out permanently. Everything in the tables above
has a known path.

## Known global caveats (apply to all drop-ins)

- Integer results cap at **int64**; where CPython would return a big int, we raise
  `OverflowError` with a normalized message (mirrored in the CPython delegates so
  dual runs stay byte-identical).
- Error **messages are pinned to CPython 3.11** (the project's Python); 3.12+
  reworded some (e.g. randrange).
- Exception **types** sometimes generalize to `ValueError` where CPython uses a
  ValueError subclass from a C module (`binascii.Error`, `zlib.error`).
- Compressed bytes (zlib/gzip) are world-divergent by design — interoperable, but
  not byte-identical across CPython and native runs.
- Facades accept **keyword arguments everywhere**, even where CPython's C functions
  are positional-only (a strict superset — positional call sites behave identically).
