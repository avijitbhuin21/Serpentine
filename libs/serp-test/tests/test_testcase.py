from __future__ import annotations
from serp_test import TestCase, fail
from serpentine import Mut, Ref, dataclass


@dataclass
class MathTest(TestCase):
    calls: int = 0

    def setUp(self: Mut[MathTest]) -> None:
        self.calls += 1

    def test_arith(self: Ref[MathTest]) -> None:
        self.assertEqual(2 + 2, 4)
        self.assertEqual("ab", "ab")
        self.assertNotEqual(2, 3)
        self.assertTrue(1 < 2)
        self.assertFalse(2 < 1)

    def test_containers(self: Ref[MathTest]) -> None:
        self.assertIn(2, [1, 2, 3])
        self.assertNotIn(9, [1, 2, 3])
        self.assertAlmostEqual(1.0, 1.00000000001)


def _boom() -> None:
    """Raise an assertion failure for assertRaises coverage."""
    fail("boom")


def main() -> None:
    t: MathTest = MathTest()
    t.setUp()
    t.setUp()
    print(t.calls)
    t.test_arith()
    t.test_containers()
    t.tearDown()
    try:
        t.assertEqual(1, 2)
    except AssertionError as e:
        print(f"AssertionError: {e}")
    try:
        t.assertTrue(False)
    except AssertionError as e:
        print(f"AssertionError: {e}")
    try:
        t.assertIn(4, [1, 2, 3])
    except AssertionError as e:
        print(f"AssertionError: {e}")
    try:
        t.assertIsNone(5)
    except AssertionError as e:
        print(f"AssertionError: {e}")
    t.assertRaises(_boom)
    try:
        t.fail("custom message")
    except AssertionError as e:
        print(f"AssertionError: {e}")
    print("done")


if __name__ == "__main__":
    main()
