"""serp-molt discriminated unions: a model union dispatched on a tag field's default."""
from __future__ import annotations

from serp_molt import BaseModel, ValidationError
from serpentine import Owned, PyVal, move


class Cat(BaseModel):
    pet_type: str = "cat"
    meows: int = 0


class Dog(BaseModel):
    pet_type: str = "dog"
    barks: float = 0.0


class Home(BaseModel):
    owner: str
    pet: Cat | Dog


def describe(h: Owned[Home]) -> str:
    """Render the discriminated pet by narrowing the union it validated into."""
    p: Cat | Dog = move(h.pet)
    if isinstance(p, Cat):
        return "cat meows=" + str(p.meows)
    return "dog barks=" + str(p.barks)


def main() -> None:
    h1: Home = Home.model_validate({"owner": "ada",
                                    "pet": {"pet_type": "cat", "meows": 3}})
    print(h1.model_dump())
    print(h1.model_dump_json())
    print(describe(move(h1)))

    h2: Home = Home.model_validate({"owner": "bob",
                                    "pet": {"pet_type": "dog", "barks": 2.5}})
    print(h2.model_dump_json())
    print(describe(move(h2)))

    h3: Home = Home.model_validate_json('{"owner": "cy", "pet": {"pet_type": "dog", '
                                        '"barks": 1.0}}')
    print(describe(move(h3)))

    errs: list[PyVal] = Home.model_validate_errors(
        {"owner": "d", "pet": {"pet_type": "cat", "meows": "no"}})
    for e in errs:
        print(e["type"], e["loc"], e["msg"])

    caught: bool = False
    try:
        bad: Home = Home.model_validate({"owner": "e", "pet": {"pet_type": "cat",
                                                              "meows": "x"}})
    except ValidationError as exc:
        caught = True
    print(caught)


if __name__ == "__main__":
    main()
