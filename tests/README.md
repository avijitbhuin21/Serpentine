# Test Corpus — the executable half of the spec

These programs ARE the spec (docs/spec.md §1.3). Every design change must keep this corpus green.

## `tests/accept/`

Programs `serp check` MUST accept. Every one is a complete, runnable CPython program using
only the Tier-0 subset, and MUST exit 0 with deterministic stdout under CPython 3.12 with
`serpentine-shim` installed. From Phase 1 on, the differential harness runs each under both
CPython and the native binary and diffs stdout byte-for-byte.

- Single-file tests: `NNN_name.py`.
- Multi-module tests: a directory `NNN_name/` whose entry point is `main.py`.

Run locally: `python tools/run_accept_tests.py`

## `tests/reject/`

Programs `serp check` MUST reject. Annotation convention (machine-checked):

- Line 1: `# serp-reject: <CODE> <error-name>` — the exact error the checker must emit.
- The offending line carries an inline marker: `# E: <CODE>`.
- Every file must still parse as valid Python 3.12 (the checker runs post-parse); reject
  tests are never executed.

Check locally: `python tools/check_reject_tests.py`

Error codes are defined in docs/spec.md §12 and are frozen once released.
