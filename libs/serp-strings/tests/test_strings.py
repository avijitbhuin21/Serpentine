from serp_strings import (wrap, fill, shorten, indent, dedent, ljust, rjust,
                          center, expandtabs, repeat_char)


def main() -> None:
    text: str = "The quick brown fox jumps over the lazy dog"
    lines: list[str] = wrap(text, 12)
    for line in lines:
        print(line)
    print("--")
    print(fill(text, 20))
    print("--")
    print(wrap("supercalifragilistic", 6))
    print(wrap("  lots   of\twhitespace\n here ", 30))
    print(wrap("", 5))
    try:
        bad: list[str] = wrap("x", 0)
        print(len(bad))
    except ValueError as e:
        print("caught:", e)
    print("--")
    print(wrap("this-is-a-hyphenated-word and some--em--dashes", 10))
    print(wrap("punct!--dash after bang, quote'--dash", 10))
    print(wrap("a-b-c-d-e re-enter x-ray", 8))
    print(wrap("looooooooooong-word-here", 10, break_on_hyphens=False))
    print(wrap("looooooooooong-word-here", 10, break_long_words=False))
    print(wrap("Sentence one. Two! Three? He said 'stop.'", 60,
               fix_sentence_endings=True))
    print(wrap(text, 20, initial_indent="* ", subsequent_indent="  "))
    print(wrap("  keep   spaces  ", 10, drop_whitespace=False))
    print(wrap(text, 15, max_lines=2))
    print(wrap(text, 15, max_lines=2, placeholder="..."))
    print(wrap(text, 44, max_lines=1))
    print(fill(text, 18, max_lines=3))
    print(shorten("Hello  world!  How are you?", 20))
    print(shorten("Hello  world!", 8, "[..]"))
    try:
        oops: list[str] = wrap("hello world", 5, max_lines=1,
                               placeholder=" [very long placeholder]")
        print(len(oops))
    except ValueError as e:
        print("caught:", e)
    print("--")
    print(indent("a\n\nb\n", "> "))
    print(indent("one\n  \nthree\n", ".."))
    print("--")
    src: str = "    def f():\n        return 1\n\n    # done\n"
    print(dedent(src))
    print(dedent("no margin\n  indented"))
    print(dedent("   \n   "))
    print(dedent("\ta\n\tb"))
    print(dedent("  a\n\tb"))
    print("--")
    print("[" + ljust("ab", 5) + "]")
    print("[" + rjust("ab", 5) + "]")
    print("[" + center("ab", 5) + "]")
    print("[" + center("ab", 7, "*") + "]")
    print("[" + ljust("abcdef", 3) + "]")
    print("--")
    print("[" + expandtabs("a\tbc\td") + "]")
    print("[" + expandtabs("a\tb", 4) + "]")
    print("[" + expandtabs("x\ny\tz", 4) + "]")
    print(repeat_char("=", 10))


if __name__ == "__main__":
    main()
