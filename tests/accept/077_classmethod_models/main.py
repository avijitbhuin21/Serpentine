"""Inherited classmethods build and dump subclass instances across module boundaries."""

from __future__ import annotations

from serpentine import PyVal, dataclass, move

from modelbase import BadPayload, Model


@dataclass
class Tag(Model):
    label: str
    weight: int = 1


@dataclass
class Doc(Model):
    title: str
    tags: list[Tag]
    words: int = 0


def main() -> None:
    t = Tag.from_dict({"label": "draft"})
    print(t.label, t.weight, Tag.kind())
    print(t.to_dict())
    print(Tag.schema())
    src: dict[str, PyVal] = {"title": "notes", "tags": [{"label": "a", "weight": 3},
                                                        {"label": "b"}],
                             "words": 12}
    d = Doc.from_dict(src)
    print(d.title, d.words, len(d.tags), d.tags[0].weight, d.tags[1].label)
    print(d.to_dict())
    print(Doc.schema())
    kept = move(t)
    print(kept.label)
    try:
        oops = Doc.from_dict("nope")
        print("unreachable", oops.title)
    except BadPayload as e:
        print("rejected:", e)


if __name__ == "__main__":
    main()
