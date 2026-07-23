from serp_url import (ParseResult, SplitResult, parse_qs, parse_qsl, quote,
                      quote_plus, unquote, unquote_plus, urldefrag, urlencode,
                      urljoin, urlparse, urlsplit, urlunparse, urlunsplit)
from serpentine import Ref


def show(u: Ref[ParseResult]) -> None:
    host: str = "None"
    if u.hostname is not None:
        host = u.hostname
    port: str = "None"
    if u.port is not None:
        port = str(u.port)
    print(u.scheme, "|", u.netloc, "|", u.path, "|", u.params, "|",
          u.query, "|", u.fragment, "|", host, "|", port)


def main() -> None:
    u1: ParseResult = urlparse("https://example.com:8443/a/b?x=1&y=two#frag")
    show(u1)
    u2: ParseResult = urlparse("http://EXAMPLE.com/path")
    show(u2)
    u3: ParseResult = urlparse("http://example.com")
    show(u3)
    u4: ParseResult = urlparse("http://[::1]:8080/v6")
    show(u4)
    u5: ParseResult = urlparse("http://[2001:db8::1]/x")
    show(u5)
    u6: ParseResult = urlparse("http://user:pw@example.com:9000/raw")
    show(u6)
    u7: ParseResult = urlparse("http://a/b/c/d;p?q")
    show(u7)
    u8: ParseResult = urlparse("localhost:8080")
    show(u8)

    s1: SplitResult = urlsplit("https://example.com:8443/a;p/b?x=1#f")
    print(s1.scheme, "|", s1.netloc, "|", s1.path, "|", s1.query, "|", s1.fragment)
    print(urlunsplit(s1))
    print(urlunparse(u1))
    print(urlunparse(u7))

    print(urljoin("http://a/b/c/d;p?q", "g"))
    print(urljoin("http://a/b/c/d;p?q", "./g"))
    print(urljoin("http://a/b/c/d;p?q", "g/"))
    print(urljoin("http://a/b/c/d;p?q", "/g"))
    print(urljoin("http://a/b/c/d;p?q", "//g"))
    print(urljoin("http://a/b/c/d;p?q", "?y"))
    print(urljoin("http://a/b/c/d;p?q", "#s"))
    print(urljoin("http://a/b/c/d;p?q", "../g"))
    print(urljoin("http://a/b/c/d;p?q", "../../g"))
    print(urljoin("http://a/b/c/d;p?q", "https://x/y"))
    print(urljoin("http://a/b/c/d", ""))
    print(urljoin("", "http://x/y"))

    df1: tuple[str, str] = urldefrag("http://e.com/p#frag")
    print(df1[0], "|", df1[1])
    df2: tuple[str, str] = urldefrag("http://e.com/p")
    print(df2[0], "|", df2[1])

    print(quote("a b/c?&=#"))
    print(quote("a b/c", ""))
    print(quote("a b/c:d", "/:"))
    print(quote("snake\u00e9\u00fc \U0001f40d"))
    print(unquote(quote("snake\u00e9\u00fc \U0001f40d")) == "snake\u00e9\u00fc \U0001f40d")
    print(quote_plus("a b+c/d"))
    print(quote_plus("a b/c", "/"))
    print(unquote_plus(quote_plus("a b+c/d")) == "a b+c/d")
    print(unquote("%41%42%43 %zz %4"))
    print(unquote("caf%C3%A9"))

    params: dict[str, str] = {}
    params["name"] = "J\u00fcrgen M\u00fcller"
    params["q"] = "a&b=c"
    params["empty"] = ""
    enc: str = urlencode(params)
    print(enc)
    back: dict[str, list[str]] = parse_qs(enc)
    print(back["name"], back["q"])
    print("empty" in back)
    multi: dict[str, list[str]] = parse_qs("x=1&x=2&lone&y=3&flag=")
    print(multi)
    pairs: list[tuple[str, str]] = parse_qsl("x=1&x=2&a=b+c")
    print(pairs)

    try:
        bad: ParseResult = urlparse("http://example.com:70000/")
        show(bad)
    except ValueError as e:
        print("port:", e)
    try:
        bad2: ParseResult = urlparse("http://example.com:12ab/")
        show(bad2)
    except ValueError as e:
        print("badport:", e)

    print("done")


if __name__ == "__main__":
    main()
