"""Files: open/write/close, reopen/read; drop closes deterministically."""


def main() -> None:
    f = open("tmp_serp_043.txt", "w")
    n: int = f.write("hello\nworld\n")
    print(n)
    f.close()
    g = open("tmp_serp_043.txt", "r")
    text: str = g.read()
    g.close()
    print(len(text))
    lines: list[str] = text.strip().split("\n")
    for line in lines:
        print(line.upper())
    try:
        h = open("no_such_file_anywhere.txt", "r")
        print(h.read())
    except FileNotFoundError as e:
        print("missing:", e)


if __name__ == "__main__":
    main()
