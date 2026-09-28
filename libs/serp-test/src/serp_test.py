"""serp-test — unittest-style TestCase plus assertion helpers for Serpentine tests.

Pure Serpentine: compiles natively and imports under CPython. Subclass
`TestCase` and write `test_*` methods; `serp test` discovers the subclasses at
build time and generates the runner. Assertion failures raise AssertionError
with CPython-style messages. The legacy `assert_*` helpers are kept.
"""
from __future__ import annotations
from serpentine import Callable, Mut, PyVal, Ref, dataclass, pyval_kind


@dataclass
class TestCase:
    """Base class for tests: subclass it and add test_* methods."""

    def setUp(self: Mut[TestCase]) -> None:
        """Hook run before each test method; override in subclasses."""
        return

    def tearDown(self: Mut[TestCase]) -> None:
        """Hook run after each test method; override in subclasses."""
        return

    def assertTrue(self: Ref[TestCase], expr: bool) -> None:
        """Fail unless expr is true."""
        if not expr:
            raise AssertionError("False is not true")

    def assertFalse(self: Ref[TestCase], expr: bool) -> None:
        """Fail if expr is true."""
        if expr:
            raise AssertionError("True is not false")

    def assertEqual(self: Ref[TestCase], first: PyVal, second: PyVal) -> None:
        """Fail unless first == second."""
        if first != second:
            raise AssertionError(f"{first!r} != {second!r}")

    def assertNotEqual(self: Ref[TestCase], first: PyVal, second: PyVal) -> None:
        """Fail if first == second."""
        if first == second:
            raise AssertionError(f"{first!r} == {second!r}")

    def assertIn(self: Ref[TestCase], member: PyVal, container: PyVal) -> None:
        """Fail unless member is in container."""
        if member not in container:
            raise AssertionError(f"{member!r} not found in {container!r}")

    def assertNotIn(self: Ref[TestCase], member: PyVal, container: PyVal) -> None:
        """Fail if member is in container."""
        if member in container:
            raise AssertionError(f"{member!r} unexpectedly found in {container!r}")

    def assertIsNone(self: Ref[TestCase], obj: PyVal) -> None:
        """Fail unless obj is None."""
        if pyval_kind(obj) != "NoneType":
            raise AssertionError(f"{obj!r} is not None")

    def assertIsNotNone(self: Ref[TestCase], obj: PyVal) -> None:
        """Fail if obj is None."""
        if pyval_kind(obj) == "NoneType":
            raise AssertionError("unexpectedly None")

    def assertAlmostEqual(self: Ref[TestCase], first: float, second: float,
                          places: int = 7) -> None:
        """Fail unless first and second are equal when rounded to `places`."""
        diff: float = abs(first - second)
        if round(diff, places) != 0.0:
            raise AssertionError(
                f"{first!r} != {second!r} within {places} places ({diff!r} difference)")

    def assertRaises(self: Ref[TestCase], fn: Callable[[], None]) -> None:
        """Fail unless calling fn raises an exception (any Exception counts)."""
        raised: bool = False
        try:
            fn()
        except Exception:
            raised = True
        if not raised:
            raise AssertionError("exception not raised")

    def fail(self: Ref[TestCase], msg: str = "") -> None:
        """Fail immediately with the given message."""
        raise AssertionError(msg)


def fail(msg: str) -> None:
    raise ValueError(f"assertion failed: {msg}")


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def assert_false(cond: bool, msg: str) -> None:
    if cond:
        fail(msg)


def assert_eq_int(got: int, want: int) -> None:
    if got != want:
        fail(f"got {got}, want {want}")


def assert_eq_str(got: str, want: str) -> None:
    if got != want:
        fail(f"got {got!r}, want {want!r}")


def assert_eq_float(got: float, want: float) -> None:
    if got != want:
        fail(f"got {got}, want {want}")


def assert_close(got: float, want: float, tol: float) -> None:
    if abs(got - want) > tol:
        fail(f"got {got}, want {want} (tol {tol})")
