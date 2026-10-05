from serp_re import compile, error, match, search


def rep(ch: str, n: int) -> str:
    """ch repeated n times."""
    out: str = ""
    i: int = 0
    while i < n:
        out += ch
        i += 1
    return out


def main() -> None:
    """Catastrophic backtracking must raise error instead of hanging; normal matching is unaffected."""
    evil: str = "(a*)*b"
    text: str = rep("a", 40)
    try:
        search(evil, text)
        print("no error")
    except error as e:
        print("error:", e)
    try:
        match("(a|a)*c", rep("a", 60))
        print("no error")
    except error as e:
        print("error:", e)
    m = compile("(a*)*b").search("aaaab")
    if m is not None:
        print("ok", m.group(0), m.span())
    hit = search("[0-9]+", rep("x", 5000) + "123")
    if hit is not None:
        print("found", hit.group(0), hit.span())


if __name__ == "__main__":
    main()
