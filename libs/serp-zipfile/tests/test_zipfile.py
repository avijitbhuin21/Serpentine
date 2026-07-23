from serp_zipfile import (ZipEntry, zip_bytes, zip_extract, zip_has,
                          zip_names, zip_parse, zip_read, zip_write,
                          ZipFile, ZIP_DEFLATED, ZIP_STORED)
from serpentine import move


def zipfile_section() -> None:
    path: str = "tmp_serp_zipobj_test.zip"
    zw = ZipFile(path, "w", ZIP_DEFLATED)
    zw.writestr("a.txt", b"alpha contents")
    zw.writestr("dir/b.bin", b"\x00\x01\x02" * 40)
    try:
        data0: bytes = zw.read("nope")
        print(len(data0))
    except KeyError:
        print("caught missing")
    zw.close()
    zw.close()
    print(zw.namelist())
    try:
        data1: bytes = zw.read("a.txt")
        print(len(data1))
    except ValueError as e:
        print("caught:", e)
    try:
        zw.writestr("later.txt", b"x")
    except ValueError as e:
        print("caught:", e)

    zr = ZipFile(path)
    print(zr.namelist())
    print(zr.read("a.txt"))
    print(len(zr.read("dir/b.bin")))
    try:
        zr.writestr("c.txt", b"x")
    except ValueError as e:
        print("caught:", e)
    zr.close()

    za = ZipFile(path, "a")
    za.writestr("c.txt", b"appended")
    za.close()
    zr2 = ZipFile(path, "r")
    print(zr2.namelist())
    print(zr2.read("c.txt"))
    zr2.close()

    try:
        zx = ZipFile(path, "q")
        print(zx.mode)
    except ValueError as e:
        print("caught:", e)
    try:
        zc = ZipFile(path, "r", 99)
        print(zc.mode)
    except NotImplementedError as e:
        print("caught:", e)
    print(ZIP_STORED, ZIP_DEFLATED)
    with ZipFile(path, "w", ZIP_DEFLATED) as zwith:
        zwith.writestr("w.txt", b"with works")
    print(zwith.closed)
    with ZipFile(path) as zread:
        print(zread.read("w.txt"))
        print(zread.namelist())


def build_entries() -> list[ZipEntry]:
    entries: list[ZipEntry] = []
    e1: ZipEntry = ZipEntry("hello.txt", b"hello zip world\n")
    entries.append(move(e1))
    e2: ZipEntry = ZipEntry("data/compressible.txt", b"repeat repeat repeat repeat " * 30)
    entries.append(move(e2))
    e3: ZipEntry = ZipEntry("empty.bin", b"")
    entries.append(move(e3))
    e4: ZipEntry = ZipEntry("unicode-\u00e9\u00fc.txt", b"accented name")
    entries.append(move(e4))
    return entries


def roundtrip(compress: bool) -> None:
    entries: list[ZipEntry] = build_entries()
    blob: bytes = zip_bytes(entries, compress)
    back: list[ZipEntry] = zip_parse(blob)
    print(zip_names(back))
    for e in entries:
        print(e.name, zip_extract(back, e.name) == e.data)


def main() -> None:
    roundtrip(False)
    roundtrip(True)

    entries: list[ZipEntry] = build_entries()
    path: str = "tmp_serp_zip_test.zip"
    zip_write(path, entries, True)
    ondisk: list[ZipEntry] = zip_read(path)
    print(len(ondisk))
    print(zip_extract(ondisk, "hello.txt"))
    print(zip_has(ondisk, "empty.bin"), zip_has(ondisk, "missing.bin"))

    fixture_hex: str = "504b030414000000000000002100a12907d10e0000000e0000000a00000073746f7265642e74787473746f726564207061796c6f6164504b030414000000080000002100d48f173610000000c600000011000000646565702f6465666c617465642e7478744b494dcb492c4955c84d554819ba4c00504b010214001400000000000000" + "2100a12907d10e0000000e0000000a000000000000000000000080010000000073746f7265642e747874504b0102140014000000080000002100d48f173610000000c6000000110000000000000000000000800136000000646565702f6465666c617465642e747874504b0506000000000200020077000000750000000000"
    fixture: bytes = bytes.fromhex(fixture_hex)
    fx: list[ZipEntry] = zip_parse(fixture)
    print(zip_names(fx))
    print(zip_extract(fx, "stored.txt"))
    deflated: bytes = zip_extract(fx, "deep/deflated.txt")
    print(len(deflated))
    print(deflated[0:11])

    try:
        bad: list[ZipEntry] = zip_parse(b"this is definitely not a zip archive!!")
        print(len(bad))
    except ValueError as e:
        print("parse:", e)
    try:
        blob2: bytes = zip_extract(fx, "nope.txt")
        print(len(blob2))
    except ValueError as e:
        print("extract:", e)

    zipfile_section()
    print("done")


if __name__ == "__main__":
    main()
