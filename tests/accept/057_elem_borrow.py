"""Named element borrows: scoped Ref of list/dict elements (corpus study #2)."""
from __future__ import annotations
from serpentine import Ref, dataclass


@dataclass
class Student:
    name: str
    score: int


def total(xs: Ref[list[int]]) -> int:
    return sum(xs)


def main() -> None:
    rows: list[list[int]] = [[1, 2, 3], [4, 5]]
    if len(rows) > 0:
        first = rows[0]
        print(first)
        print(len(first), first[1], total(first))
        print(len(rows))
    rows.append([9])
    print(len(rows))
    grades: dict[str, list[int]] = {"amy": [90, 95]}
    amy = grades["amy"]
    print(amy[0] + amy[1])
    students: list[Student] = [Student("zed", 7)]
    top: Student = students[0]
    print(top.name, top.score)


if __name__ == "__main__":
    main()
