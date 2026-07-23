from serp_csv import (parse, parse_line, format_field, format_row, format_rows,
                      needs_quoting, reader, writer, DictReader, Error)
from serpentine import PyVal, pyval_kind, move


def dictreader_section() -> None:
    lines: list[str] = ["name,age,city", "ada,36,london", "grace,52", "", "linus,54,helsinki,extra"]
    rows: PyVal = DictReader(lines)
    for row in rows:
        print(row)
    print(len(rows), rows[0]["name"], rows[1]["age"] == "52")
    print(pyval_kind(rows[1]["city"]))
    named: PyVal = DictReader(lines, ["a", "b", "c"])
    print(named[0])
    filled: PyVal = DictReader(lines, None, "?")
    print(filled[1])


def reader_writer_section() -> None:
    lines: list[str] = ["a,b,c", '1,"two, three",4', '"say ""hi""",x,']
    rows: list[list[str]] = reader(lines)
    for row in rows:
        print(row)
    multi: list[str] = ['a,"start', 'end",z']
    print(reader(multi))
    blanks: list[str] = ["a", "", "b"]
    print(reader(blanks))
    terminated: list[str] = ["a,b\r\n", "c,d\n"]
    print(reader(terminated))
    lone: list[str] = ['""']
    print(reader(lone))
    try:
        bad: list[str] = ["a\rb"]
        print(reader(bad))
    except Error as e:
        print("caught:", e)

    w = writer()
    r1: list[str] = ["a", "b,c"]
    w.writerow(r1)
    r2: list[str] = ['q"x', "line\nbreak"]
    w.writerow(r2)
    r3: list[str] = [""]
    w.writerow(r3)
    r4: list[str] = []
    w.writerow(r4)
    print(w.getvalue().replace("\r\n", "<CRLF>").replace("\n", "<LF>"))
    w2 = writer()
    table2: list[list[str]] = [["h1", "h2"], ["v1", "v,2"]]
    w2.writerows(table2)
    print(w2.getvalue().replace("\r\n", "<CRLF>"))


def main() -> None:
    doc: str = 'a,b,c\r\n1,"two, three",4\n"say ""hi""",x,\n"multi\nline",z,w\n'
    rows: list[list[str]] = parse(doc)
    for row in rows:
        print(row)
    print(parse(""))
    print(parse("single"))
    print(parse("a,b"))
    print(parse("a,b\n"))
    print(parse(",\n,"))
    print(parse_line("x,y,z"))
    print(parse_line(""))
    try:
        print(parse('"unterminated'))
    except ValueError as e:
        print("caught:", e)
    print(needs_quoting("plain"), needs_quoting("a,b"), needs_quoting('q"t'), needs_quoting("n\nl"))
    print(format_field("plain"))
    print(format_field("a,b"))
    print(format_field('say "hi"'))
    row2: list[str] = ["1", "two, three", 'say "hi"', ""]
    print(format_row(row2))
    table: list[list[str]] = [["h1", "h2"], ["v1", "v,2"]]
    out: str = format_rows(table)
    print(out.replace("\r\n", "<CRLF>"))
    back: list[list[str]] = parse(format_rows(table))
    print(back == table)
    reader_writer_section()
    dictreader_section()


if __name__ == "__main__":
    main()
