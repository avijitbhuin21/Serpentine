# serp-test

Serpentine's test library ([P] pure Serpentine, docs/libraries.md Wave 1).

## unittest-style TestCase (0.2.0)

```python
from __future__ import annotations
from serp_test import TestCase
from serpentine import Ref, dataclass


@dataclass
class MathTest(TestCase):
    def test_add(self: Ref[MathTest]) -> None:
        self.assertEqual(2 + 2, 4)
```

Run with **`serp test`**: it discovers `test_*.py` files, finds `TestCase`
subclasses **at build time** (no runtime reflection), generates a native
runner per file, and reports `FAIL: test_x (Class) - message` lines plus a
`Ran N test(s)` / `OK` / `FAILED (failures=K)` summary. A file passes when
its runner exits 0. Files without TestCase subclasses run as plain programs
(exit-0 contract), so the legacy function style keeps working.

Assert methods (CPython-style messages, raising `AssertionError`):
`assertTrue/assertFalse`, `assertEqual/assertNotEqual` (PyVal — any values),
`assertIn/assertNotIn`, `assertIsNone/assertIsNotNone`,
`assertAlmostEqual(first, second, places=7)`, `assertRaises(fn)`
(zero-arg function reference; any exception counts), `fail(msg)`, plus
`setUp`/`tearDown` hooks (fresh instance per test method).

Divergences from `unittest`: subclasses carry `@dataclass` and must default
every field (zero-arg construction); `assertRaises` takes a function
reference instead of an exception class + callable; no `unittest.main()`
(discovery lives in `serp test`); no msg= parameter on asserts.

## Legacy helpers

- `from serp_test import assert_true, assert_false, assert_eq_int, assert_eq_str,
  assert_eq_float, assert_close, fail`
- Failed assertions raise `ValueError` with an `assertion failed:` prefix.

Install into a Serpentine project with `serp add serp-test`.
