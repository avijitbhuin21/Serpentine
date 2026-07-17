"""Benchmark: string processing — split/concat/upper over many rows."""


def process(rows: int) -> int:
    total: int = 0
    for i in range(rows):
        line: str = f"alpha,beta,gamma,delta,{i}"
        parts: list[str] = line.split(",")
        joined: str = "-".join(parts)
        u: str = joined.upper()
        total += len(u)
    return total


def main() -> None:
    print(process(300000))


if __name__ == "__main__":
    main()
