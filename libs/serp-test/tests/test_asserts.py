from serp_test import assert_true, assert_false, assert_eq_int, assert_eq_str, assert_eq_float, assert_close, fail


def main() -> None:
    assert_true(1 + 1 == 2, "arithmetic works")
    assert_false(1 > 2, "ordering works")
    assert_eq_int(6 * 7, 42)
    assert_eq_str("ab" + "cd", "abcd")
    assert_eq_float(0.5 + 0.25, 0.75)
    assert_close(1.0 / 3.0, 0.3333333333, 1e-9)
    print("positive assertions passed")
    try:
        assert_eq_int(1, 2)
    except ValueError as ex:
        print(f"caught: {ex}")
    try:
        assert_eq_str("a", "b")
    except ValueError as ex2:
        print(f"caught: {ex2}")
    try:
        fail("explicit")
    except ValueError as ex3:
        print(f"caught: {ex3}")


if __name__ == "__main__":
    main()
