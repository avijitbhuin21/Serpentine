"""serp-test — assertion helpers for Serpentine test files.

Pure Serpentine: compiles natively and imports under CPython. Failures raise
ValueError with an `assertion failed:` prefix; `serp test` treats a non-zero
exit as FAIL.
"""


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
