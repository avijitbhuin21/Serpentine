"""Accept: str find and replace produce new owned strings; original unchanged."""


def main() -> None:
    s: str = "banana"
    print(s.find("na"), s.find("xyz"))
    print(s.replace("na", "NA"))
    print(s)


if __name__ == "__main__":
    main()
