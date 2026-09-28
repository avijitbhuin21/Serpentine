# serp-reject: SE201 unsupported-feature
"""Reject: `@X.m(...)` on a module-level binding needs m to be a @registrar method (D41)."""

from serpentine import Callable, Mut, Owned, dataclass


@dataclass
class Job:
    name: str


@dataclass
class Registry:
    names: list[str] = []

    def on(self: Mut[Registry], name: str, handler: Callable[[Job], str]) -> None:
        self.names.append(name)


reg = Registry()


@reg.on("first")  # E: SE201
def first(job: Owned[Job]) -> str:
    return job.name


def main() -> None:
    print(len(reg.names))


if __name__ == "__main__":
    main()
