from serpentine import Owned
from serp_re import (DOTALL, IGNORECASE, MULTILINE, Match, Pattern, compile, error,
                     escape, findall, finditer, fullmatch, match, search, split, sub)


def show(m: Owned[Match | None]) -> None:
    print(m)


def main() -> None:
    show(match("a+b", "aaab"))
    show(match("a+b", "bbb"))
    show(search(r"\d+", "ab 123 cd 45"))
    show(fullmatch("[a-z]+", "hello"))
    show(fullmatch("[a-z]+", "hello!"))
    m: Match | None = search(r"(\w+)@(\w+)\.(\w+)", "mail me@example.com now")
    if m is not None:
        print(m.group(0), m.group(1), m.group(2), m.group(3))
        print(m.groups())
        print(m.start(), m.end(), m.span())
        print(m.span(2), m.start(3), m.end(3))
        print(m.string)
    bt: Match | None = match("(ab|a)*b", "abab")
    if bt is not None:
        print(bt.span(), bt.group(1))
    lazy: Match | None = match("<(.*?)>", "<a><b>")
    if lazy is not None:
        print(lazy.group(0), lazy.group(1))
    greedy: Match | None = match("<(.*)>", "<a><b>")
    if greedy is not None:
        print(greedy.group(0), greedy.group(1))
    print(findall(r"\d+", "a1 bb22 c333"))
    print(findall(r"(\w+)@\w+", "x@y a@b now"))
    print(findall("a*", "bac"))
    print(findall("a*?", "aab"))
    its: list[Match] = finditer(r"[aeiou]+", "sequence of words")
    for it in its:
        print(it)
    print(sub(r"\d+", "#", "a1b22c333"))
    print(sub(r"(\w+) (\w+)", r"\2 \1", "hello world"))
    print(sub("an", "-", "banana", 1))
    print(split(r"\s*,\s*", "a , b,c ,  d"))
    print(split(r"(\d)", "a1b2c"))
    print(split("x*", "abc"))
    print(escape("1+1=2 (maybe)"))
    p: Pattern = compile(r"(\d{2}):(\d{2})")
    print(p.pattern, p.groups, p.flags)
    show(p.search("at 12:34 now"))
    print(p.sub(r"\1h\2m", "at 12:34 now"))
    print(findall("ab", "ABab aB", IGNORECASE))
    show(search("^b$", "a\nb", MULTILINE))
    show(match("a.b", "a\nb", DOTALL))
    show(match("a.b", "a\nb"))
    m2: Match | None = match("(a)(b)?", "a")
    if m2 is not None:
        print(m2.groups(), m2.start(2), m2.end(2))
        g2: str | None = m2.group(2)
        print(g2 is None)
    m3: Match | None = fullmatch("(a*)*", "aaa")
    if m3 is not None:
        print(m3.span(), m3.groups())
    m4: Match | None = match(r"\b(\w+){2,3}\b", "hey")
    if m4 is not None:
        print(m4.span(), m4.group(1))
    try:
        bad: Pattern = compile("a(")
        print(bad.pattern)
    except error as e:
        print("caught:", e)
    try:
        multi: list[str] = findall("(a)(b)", "ab")
        print(multi)
    except error as e2:
        print("caught:", e2)
    try:
        m5: Match | None = match("(a)", "a")
        if m5 is not None:
            print(m5.group(5))
    except IndexError as e3:
        print("caught:", e3)
    try:
        look: Pattern = compile("a(?=b)")
        print(look.pattern)
    except error as e4:
        print("caught:", e4)


if __name__ == "__main__":
    main()
