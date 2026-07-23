from serp_io import (append_bytes, append_text, copy_file, file_reader,
                     file_size, read_bytes, read_lines, read_text, reader,
                     write_bytes, write_text, StringIO, BytesIO)


def sio_section() -> None:
    s: StringIO = StringIO("hello\nworld\n")
    print(s.read(4))
    print(s.tell())
    print(s.readline())
    print(s.readline())
    print(s.readline() == "")
    s.seek(0)
    print(s.readlines())
    w: StringIO = StringIO()
    print(w.write("hello"), w.write(" world"))
    print(w.getvalue())
    print(w.seek(2))
    print(w.write("XY"))
    print(w.getvalue())
    print(w.seek(0, 2), w.tell())
    print(w.truncate(4))
    print(w.getvalue())
    lines: list[str] = ["a\n", "b\n"]
    w2: StringIO = StringIO()
    w2.writelines(lines)
    print(w2.getvalue())
    try:
        n1: int = w.seek(-1)
        print(n1)
    except ValueError as e:
        print("caught:", e)
    try:
        n2: int = w.seek(1, 1)
        print(n2)
    except OSError as e:
        print("caught:", e)
    try:
        n3: int = w.seek(0, 7)
        print(n3)
    except ValueError as e:
        print("caught:", e)
    w.close()
    print(w.closed)
    try:
        v: str = w.getvalue()
        print(v)
    except ValueError as e:
        print("caught:", e)
    with StringIO("ctx text") as cf:
        print(cf.read(3))
    print(cf.closed)


def bio_section() -> None:
    b: BytesIO = BytesIO(b"hello\nworld\n")
    print(b.read(4))
    print(b.readline())
    print(b.readline(3))
    b.seek(0)
    print(b.read())
    w: BytesIO = BytesIO()
    print(w.write(b"hello"))
    print(w.seek(2))
    print(w.write(b"XY"))
    print(w.getvalue())
    print(w.seek(-1, 2))
    print(w.seek(-99, 2))
    print(w.seek(1, 1), w.tell())
    print(w.truncate(3))
    print(w.getvalue())
    try:
        n1: int = w.seek(-4)
        print(n1)
    except ValueError as e:
        print("caught:", e)
    w.close()
    print(w.closed)
    try:
        data: bytes = w.read()
        print(data)
    except ValueError as e:
        print("caught:", e)
    with BytesIO(b"ctx bytes") as cb:
        print(cb.read(3))
    print(cb.closed)


def main() -> None:
    bpath: str = "tmp_serp_io_blob.bin"
    n: int = write_bytes(bpath, b"\x00\x01binary\xffdata")
    print(n)
    print(read_bytes(bpath))
    print(file_size(bpath))
    print(append_bytes(bpath, b"+tail"))
    print(read_bytes(bpath))
    print(file_size(bpath))

    cpath: str = "tmp_serp_io_copy.bin"
    print(copy_file(bpath, cpath))
    print(read_bytes(cpath) == read_bytes(bpath))

    tpath: str = "tmp_serp_io_text.txt"
    print(write_text(tpath, "alpha\nbeta\ngamma\n"))
    print(read_text(tpath) == "alpha\nbeta\ngamma\n")
    print(read_lines(tpath))
    print(append_text(tpath, "delta"))
    print(read_lines(tpath))

    epath: str = "tmp_serp_io_empty.txt"
    write_text(epath, "")
    print(read_lines(epath))
    print(read_text(epath))

    crlf: str = "tmp_serp_io_crlf.bin"
    write_bytes(crlf, b"one\r\ntwo\r\nthree")
    print(read_lines(crlf))

    r = reader(b"hello world")
    print(r.read(5))
    print(r.tell(), r.remaining(), r.at_eof())
    print(r.peek(3))
    r.skip(1)
    print(r.read_all())
    print(r.at_eof(), r.remaining())
    r.seek(6)
    print(r.read(100))
    print(r.read(5))

    fr = file_reader(bpath)
    print(fr.read(2).hex())
    print(fr.read_all())

    try:
        r.seek(-1)
    except ValueError as e:
        print("seek:", e)
    try:
        chunk: bytes = r.read(-2)
        print(len(chunk))
    except ValueError as e:
        print("read:", e)

    print("done")
    sio_section()
    bio_section()


if __name__ == "__main__":
    main()
