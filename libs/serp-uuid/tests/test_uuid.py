from serp_uuid import UUID, uuid4, parse

HEX: str = "0123456789abcdef"


def valid(u: str) -> bool:
    if len(u) != 36:
        return False
    for i in range(36):
        c: str = u[i]
        if i == 8 or i == 13 or i == 18 or i == 23:
            if c != "-":
                return False
        elif HEX.find(c) < 0:
            return False
    if u[14] != "4":
        return False
    return u[19] == "8" or u[19] == "9" or u[19] == "a" or u[19] == "b"


def main() -> None:
    a: UUID = uuid4()
    b: UUID = uuid4()
    print(valid(str(a)), valid(str(b)))
    print(str(a) != str(b))
    print(a.version, b.version)
    print(a.variant)
    print(len(a.hex), a.hex.find("-"))
    print(a.urn.startswith("urn:uuid:"), len(a.urn))
    print(f"id={a}" == "id=" + str(a))
    fixed: UUID = parse("12345678-1234-4234-9234-123456789abc")
    print(fixed)
    print(fixed.hex)
    print(fixed.version, fixed.variant)
    print(fixed == parse("12345678-1234-4234-9234-123456789ABC"))
    plain: UUID = UUID("12345678123442349234123456789abc")
    braced: UUID = UUID("{12345678-1234-4234-9234-123456789abc}")
    urned: UUID = UUID("urn:uuid:12345678-1234-4234-9234-123456789ABC")
    print(plain == fixed, braced == fixed, urned == fixed)
    try:
        short: UUID = UUID("1234")
        print(str(short))
    except ValueError as e0:
        print("caught:", e0)
    try:
        bad: UUID = parse("not-a-uuid")
        print(str(bad))
    except ValueError as e:
        print("caught:", e)
    seen: dict[str, bool] = {}
    for _ in range(50):
        seen[str(uuid4())] = True
    print(len(seen))


if __name__ == "__main__":
    main()
