"""Accept: nested list places — grid[i][j] reads and writes (SPEC section 5.3)."""


def main() -> None:
    grid: list[list[int]] = [[1, 2], [3, 4]]
    grid[0][1] = 9
    print(grid[0][1], grid[1][0])
    print(grid)


if __name__ == "__main__":
    main()
