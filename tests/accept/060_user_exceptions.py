"""User-defined exception classes: define, raise, catch via hierarchy, re-raise."""


class AppError(Exception):
    pass


class ConfigError(AppError):
    pass


class BadValue(ValueError):
    """A user subclass of a builtin exception."""
    pass


def parse_level(s: str) -> int:
    if s == "":
        raise ConfigError("empty level")
    if s == "bad":
        raise BadValue("bad level")
    if s == "boom":
        raise AppError
    return len(s)


def main() -> None:
    try:
        print(parse_level("info"))
    except AppError as e:
        print("unreachable:", e)

    try:
        print(parse_level(""))
    except ConfigError as e:
        print("exact:", e)

    try:
        print(parse_level(""))
    except AppError as e:
        print("via user base:", e)

    try:
        print(parse_level("bad"))
    except ValueError as e:
        print("via builtin base:", e)

    try:
        print(parse_level("boom"))
    except Exception as e:
        print("via Exception:", e)

    try:
        print(parse_level("bad"))
    except (ConfigError, BadValue) as e:
        print("tuple:", e)

    try:
        try:
            raise ConfigError("inner")
        except AppError as e:
            print("re-raising:", e)
            raise
    except ConfigError as e:
        print("outer:", e)

    print("done")


if __name__ == "__main__":
    main()
