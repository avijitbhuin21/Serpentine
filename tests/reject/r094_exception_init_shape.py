# serp-reject: SE201 unsupported-feature
"""Reject: an exception __init__ may only assign self.<x> fields before its single
super().__init__(<message>) statement (D42) — any other statement is rejected."""


class AppError(Exception):
    def __init__(self, code: int) -> None:  # E: SE201
        self.code = code
        print(code)
        super().__init__(str(code))


def main() -> None:
    try:
        raise AppError(404)
    except AppError as e:
        print(e)


if __name__ == "__main__":
    main()
