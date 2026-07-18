"""Tier-2 with-open RAII, zip, reversed."""


def main() -> None:
    with open("tmp_serp_053.txt", "w") as f:
        n: int = f.write("alpha\nbeta\n")
        print(n)
    with open("tmp_serp_053.txt", "r") as g:
        text: str = g.read()
    lines: list[str] = text.strip().split("\n")
    print(lines)
    nums: list[int] = [10, 20]
    for word, num in zip(lines, nums):
        print(word, num)
    for v in reversed(nums):
        print(v)
    try:
        with open("no_such_dir_053/x.txt", "r") as h:
            print(h.read())
    except FileNotFoundError as e:
        print("missing:", e)


if __name__ == "__main__":
    main()
