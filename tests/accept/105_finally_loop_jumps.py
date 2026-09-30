"""Accept: finally runs exactly once around loops; handler break/continue with finally in while and nested loops."""
from serpentine import Mut, Ref


def loop_inside_try(xs: Ref[list[int]], log: Mut[list[str]]) -> int:
    """A break that stays inside the try must not run the try's finally early."""
    found: int = -1
    try:
        for x in xs:
            if x > 10:
                found = x
                break
            log.append("scan " + str(x))
        log.append("after loop")
    finally:
        log.append("fin once")
    return found


def while_handler_break(xs: Ref[list[int]], log: Mut[list[str]]) -> int:
    """break from an except handler inside a while loop runs the finally first."""
    seen: int = 0
    while seen < len(xs):
        x: int = xs[seen]
        seen += 1
        try:
            if x < 0:
                raise ValueError("neg " + str(x))
            log.append("val " + str(x))
        except ValueError as e:
            log.append("caught " + str(e))
            break
        finally:
            log.append("fin " + str(x))
    return seen


def inner_loop_continue(rows: Ref[list[list[int]]], log: Mut[list[str]]) -> int:
    """continue in an inner-loop handler skips only the inner iteration, after its finally."""
    good: int = 0
    for row in rows:
        for x in row:
            try:
                if x == 0:
                    raise ZeroDivisionError("zero")
                good += 100 // x
            except ZeroDivisionError:
                log.append("zero in row")
                continue
            finally:
                log.append("cell " + str(x))
        log.append("row done")
    return good


def main() -> None:
    log: list[str] = []
    print(loop_inside_try([3, 4, 12, 20], log))
    print(while_handler_break([5, 6, -1, 7], log))
    print(inner_loop_continue([[1, 0, 4], [0], [5]], log))
    for line in log:
        print(line)


if __name__ == "__main__":
    main()
