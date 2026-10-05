"""TLS verification probe: bad certificates must be refused unless verify=False."""
from serp_fang import get


def probe(url: str, verify: bool) -> str:
    """One line: HTTP status, or the OSError message."""
    try:
        r = get(url, timeout=15.0, verify=verify)
        return "status " + str(r.status_code)
    except OSError as e:
        return "OSError " + str(e)


def main() -> None:
    """Print one verdict line per badssl.com case."""
    cases: list[str] = [
        "https://badssl.com/",
        "https://expired.badssl.com/",
        "https://self-signed.badssl.com/",
        "https://wrong.host.badssl.com/",
        "https://untrusted-root.badssl.com/",
    ]
    for url in cases:
        print(url, "->", probe(url, True))
    print("https://self-signed.badssl.com/ (verify=False) ->", probe("https://self-signed.badssl.com/", False))


if __name__ == "__main__":
    main()
