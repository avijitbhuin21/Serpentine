# serp-test

Serpentine's test library ([P] pure Serpentine, docs/libraries.md Wave 1).

- `from serp_test import assert_true, assert_false, assert_eq_int, assert_eq_str,
  assert_eq_float, assert_close, fail`
- Failed assertions raise `ValueError` with an `assertion failed:` prefix (the
  Tier-2 error convention — user-defined exception classes are a later tier).
- Run test files with **`serp test`**: it discovers `test_*.py` under `tests/` (or the
  given path), builds each natively, runs it, and reports PASS/FAIL. A test passes
  when it exits 0.
- Monomorphic `assert_eq_*` helpers are deliberate: a generic `assert_eq` needs
  protocol-bounded generics over `__eq__`, which is on the roadmap.

Install into a Serpentine project with `serp add serp-test`.
