# serp-reject: SE201 unsupported-feature
"""Reject: a route handler parameter whose type the request cannot provide (D41)."""

from serpentine import Callable, Mut, Owned, dataclass, registrar


@dataclass
class Job:
    name: str


@dataclass
class Registry:
    names: list[str] = []

    @registrar
    def on(self: Mut[Registry], name: str, handler: Callable[[Job], str]) -> None:
        self.names.append(name)


reg = Registry()


@reg.on("first")
def first(tags: list[str]) -> str:  # E: SE201
    return str(len(tags))


def main() -> None:
    print(len(reg.names))


if __name__ == "__main__":
    main()
