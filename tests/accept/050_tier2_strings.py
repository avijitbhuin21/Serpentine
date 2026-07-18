"""Tier-2 strings: indexing, slicing, iteration, ord/chr, round."""


def main() -> None:
    s: str = "serpentine"
    print(s[0], s[3], s[-1], s[-3])
    print(s[2:6], s[:4], s[6:], s[4:4], s[-4:], s[:-6])
    print(s[2:100], s[100:], s[-100:3])
    for ch in "abc":
        print(ch)
    print(ord("A"), ord("z"), chr(97), chr(233))
    print(round(2.5), round(3.5), round(-0.5), round(2.675, 2), round(1.0 / 3.0, 4))
    print(round(7), round(7, 2))
    try:
        print(s[20])
    except IndexError as e:
        print("caught:", e)


if __name__ == "__main__":
    main()
