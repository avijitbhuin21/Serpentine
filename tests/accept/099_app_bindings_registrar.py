"""D41 module-level object bindings + @registrar decorators, D42 exception __init__,
empty-container parameter defaults."""
from __future__ import annotations

from serpentine import Callable, Mut, Owned, Ref, dataclass, move, registrar


class AppError(Exception):
    def __init__(self, code: int, detail: str = "") -> None:
        super().__init__(str(code) + ": " + detail)


@dataclass
class Job:
    name: str
    tags: list[str]


@dataclass
class Registry:
    prefix: str = "job"
    names: list[str] = []
    handlers: list[Callable[[Job], str]] = []

    @registrar
    def on(self: Mut[Registry], name: str, handler: Callable[[Job], str], weight: int = 1) -> None:
        self.names.append(self.prefix + ":" + name + "@" + str(weight))
        self.handlers.append(handler)

    def run_all(self: Ref[Registry], tags: Owned[list[str]] = []) -> list[str]:
        out: list[str] = []
        i: int = 0
        while i < len(self.handlers):
            h: Callable[[Job], str] = self.handlers[i]
            copy_tags: list[str] = [t for t in tags]
            out.append(h(Job(self.names[i], move(copy_tags))))
            i += 1
        return out


reg = Registry(prefix="task")


@reg.on("first")
def first(job: Owned[Job]) -> str:
    return "first saw " + job.name + " with " + str(len(job.tags)) + " tag(s)"


@reg.on("second", weight=5)
def second(job: Owned[Job]) -> str:
    return "second saw " + job.name


def describe(names: Owned[list[str]] = [], opts: Owned[dict[str, int]] = {}) -> str:
    return str(len(names)) + "/" + str(len(opts))


def fail(code: int) -> None:
    if code == 404:
        raise AppError(status_code_or_code(code), detail="missing")
    raise AppError(code)


def status_code_or_code(c: int) -> int:
    return c


def main() -> None:
    print(reg.names)
    for line in reg.run_all():
        print(line)
    for line in reg.run_all(["a", "b"]):
        print(line)
    print(describe())
    print(describe(["x"]))
    print(describe(opts={"k": 1, "j": 2}))
    try:
        fail(404)
    except AppError as e:
        print("caught", e)
    try:
        fail(500)
    except AppError as e:
        print("caught", e)
    other = Registry()
    other.on("plain", second)
    print(other.names, len(other.handlers))


if __name__ == "__main__":
    main()
