"""Accept: bare continue (and break) inside except handlers within for/while loops."""
from serpentine import Ref


def parse(s: str) -> int:
    """Parse a non-negative int, raising ValueError on bad input."""
    if s == "":
        raise ValueError("bad number: " + s)
    for ch in s:
        if ch < "0" or ch > "9":
            raise ValueError("bad number: " + s)
    return int(s)


def sum_valid(items: Ref[list[str]]) -> int:
    """Skip unparsable entries with continue from the except arm."""
    total: int = 0
    for s in items:
        v: int = 0
        try:
            v = parse(s)
        except ValueError:
            continue
        total += v
    return total


def count_until_stop(items: Ref[list[str]]) -> int:
    """While-loop variant: continue in one handler, break in another."""
    i: int = 0
    seen: int = 0
    while i < len(items):
        s: str = items[i]
        i += 1
        try:
            if s == "stop":
                raise KeyError(s)
            parse(s)
        except ValueError as e:
            print("skip", e)
            continue
        except KeyError:
            break
        seen += 1
    return seen


def with_finally(items: Ref[list[str]]) -> list[str]:
    """continue inside except with a finally arm present."""
    log: list[str] = []
    for s in items:
        try:
            parse(s)
            log.append("ok:" + s)
        except ValueError:
            log.append("bad:" + s)
            continue
        finally:
            log.append("done:" + s)
        log.append("after:" + s)
    return log


def nested(rows: Ref[list[list[str]]]) -> int:
    """continue in an inner-loop handler must only skip the inner iteration."""
    good: int = 0
    for row in rows:
        for cell in row:
            try:
                parse(cell)
            except ValueError:
                continue
            good += 1
        good += 100
    return good


def main() -> None:
    items: list[str] = ["1", "x", "22", "", "333", "4y"]
    print(sum_valid(items))
    print(count_until_stop(["5", "bad", "6", "stop", "7"]))
    print(with_finally(["8", "no", "9"]))
    print(nested([["1", "a"], ["b"], ["2", "3", "c"]]))


if __name__ == "__main__":
    main()
