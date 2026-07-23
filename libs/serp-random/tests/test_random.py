from serp_random import seed, random, randint, uniform, randrange, getrandbits, choice, shuffle


def main() -> None:
    seed(42)
    print(random())
    print(random())
    print(randint(1, 6))
    print(randint(1, 6))
    print(randint(-100, 100))
    print(uniform(0.0, 10.0))
    print(uniform(-5.0, 5.0))
    seed(42)
    print(random())
    seed(-1)
    print(random())
    print(randint(0, 0))
    seed(123)
    print(getrandbits(1))
    print(getrandbits(8))
    print(getrandbits(32))
    print(getrandbits(63))
    print(randrange(10))
    print(randrange(5, 15))
    print(randrange(0, 100, 7))
    print(randrange(10, 0, -2))
    seed(99)
    items: list[int] = [10, 20, 30, 40, 50]
    print(choice(items))
    print(choice(items))
    letters: list[str] = ["a", "b", "c", "d"]
    print(choice(letters))
    nums: list[int] = [1, 2, 3, 4, 5, 6, 7, 8]
    shuffle(nums)
    print(nums)
    ok: bool = True
    i: int = 0
    seed(7)
    while i < 1000:
        r: float = random()
        if r < 0.0 or r >= 1.0:
            ok = False
        n: int = randint(1, 6)
        if n < 1 or n > 6:
            ok = False
        i += 1
    print(ok)
    try:
        bad: int = randint(5, 4)
        print(bad)
    except ValueError as ex:
        print(f"randint(5,4): {ex}")
    try:
        z: int = getrandbits(0)
        print(z)
    except ValueError as ex2:
        print(f"getrandbits(0): {ex2}")
    try:
        w: int = randrange(0)
        print(w)
    except ValueError as ex3:
        print(f"randrange(0): {ex3}")


if __name__ == "__main__":
    main()
