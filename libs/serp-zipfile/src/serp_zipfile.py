"""serp-zipfile — ZIP archive read/write in the Serpentine subset.

Pure Serpentine ([P]) over serp-zlib: stored (method 0) and DEFLATE
(method 8) entries, UTF-8 names, CRC-verified extraction. ZipFile is a real
class mirroring zipfile.ZipFile for the common object API (namelist/read/
writestr/close, `with` support, modes r/w/a, ZIP_STORED/ZIP_DEFLATED) —
writestr takes bytes only, close() is what flushes write-mode archives, and
the internal entries/compress/closed fields are visible as extra defaulted
constructor parameters. Writes use a fixed DOS timestamp (1980-01-01 00:00)
so archive bytes are deterministic. No zip64, encryption or multi-disk
support.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, dataclass, move
from serp_zlib import crc32, deflate, inflate


@dataclass
class ZipEntry:
    name: str
    data: bytes


def _w16(out: Mut[bytearray], v: int) -> None:
    out.append(v % 256)
    out.append((v // 256) % 256)


def _w32(out: Mut[bytearray], v: int) -> None:
    out.append(v % 256)
    out.append((v // 256) % 256)
    out.append((v // 65536) % 256)
    out.append((v // 16777216) % 256)


def _r16(d: bytes, i: int) -> int:
    return d[i] + 256 * d[i + 1]


def _r32(d: bytes, i: int) -> int:
    return d[i] + 256 * d[i + 1] + 65536 * d[i + 2] + 16777216 * d[i + 3]


def zip_bytes(entries: Ref[list[ZipEntry]], compress: bool) -> bytes:
    out: bytearray = bytearray(b"")
    offsets: list[int] = []
    methods: list[int] = []
    rawsizes: list[int] = []
    for e in entries:
        raw: bytes = e.data
        method: int = 0
        if compress:
            packed: bytes = deflate(e.data, 6)
            if len(packed) < len(e.data):
                raw = packed
                method = 8
        name_b: bytes = e.name.encode("utf-8")
        offsets.append(len(out))
        methods.append(method)
        rawsizes.append(len(raw))
        out.extend(b"PK\x03\x04")
        _w16(out, 20)
        _w16(out, 0)
        _w16(out, method)
        _w16(out, 0)
        _w16(out, 33)
        _w32(out, crc32(e.data))
        _w32(out, len(raw))
        _w32(out, len(e.data))
        _w16(out, len(name_b))
        _w16(out, 0)
        out.extend(name_b)
        out.extend(raw)
    cd_start: int = len(out)
    i: int = 0
    for e in entries:
        name_b2: bytes = e.name.encode("utf-8")
        out.extend(b"PK\x01\x02")
        _w16(out, 20)
        _w16(out, 20)
        _w16(out, 0)
        _w16(out, methods[i])
        _w16(out, 0)
        _w16(out, 33)
        _w32(out, crc32(e.data))
        _w32(out, rawsizes[i])
        _w32(out, len(e.data))
        _w16(out, len(name_b2))
        _w16(out, 0)
        _w16(out, 0)
        _w16(out, 0)
        _w16(out, 0)
        _w32(out, 0)
        _w32(out, offsets[i])
        out.extend(name_b2)
        i += 1
    cd_size: int = len(out) - cd_start
    out.extend(b"PK\x05\x06")
    _w16(out, 0)
    _w16(out, 0)
    _w16(out, len(entries))
    _w16(out, len(entries))
    _w32(out, cd_size)
    _w32(out, cd_start)
    _w16(out, 0)
    return bytes(out)


def zip_parse(data: bytes) -> list[ZipEntry]:
    n: int = len(data)
    if n < 22:
        raise ValueError("not a zip archive")
    pos: int = n - 22
    stop: int = 0
    if n - 22 - 65535 > 0:
        stop = n - 22 - 65535
    eocd: int = -1
    while pos >= stop:
        if data[pos] == 80 and data[pos + 1] == 75 and data[pos + 2] == 5 and data[pos + 3] == 6:
            eocd = pos
            break
        pos -= 1
    if eocd < 0:
        raise ValueError("not a zip archive")
    count: int = _r16(data, eocd + 10)
    cd_off: int = _r32(data, eocd + 16)
    entries: list[ZipEntry] = []
    p: int = cd_off
    k: int = 0
    while k < count:
        if p + 46 > n:
            raise ValueError("bad central directory")
        if not (data[p] == 80 and data[p + 1] == 75 and data[p + 2] == 1 and data[p + 3] == 2):
            raise ValueError("bad central directory")
        method: int = _r16(data, p + 10)
        crc_want: int = _r32(data, p + 16)
        csize: int = _r32(data, p + 20)
        usize: int = _r32(data, p + 24)
        nlen: int = _r16(data, p + 28)
        elen: int = _r16(data, p + 30)
        clen: int = _r16(data, p + 32)
        lofs: int = _r32(data, p + 42)
        name: str = data[p + 46:p + 46 + nlen].decode("utf-8")
        if lofs + 30 > n:
            raise ValueError("bad local header for " + name)
        lnlen: int = _r16(data, lofs + 26)
        lelen: int = _r16(data, lofs + 28)
        start: int = lofs + 30 + lnlen + lelen
        raw: bytes = data[start:start + csize]
        if len(raw) != csize:
            raise ValueError("truncated entry " + name)
        content: bytes = raw
        if method == 8:
            content = inflate(raw)
        elif method != 0:
            raise ValueError("unsupported compression method: " + str(method))
        if len(content) != usize or crc32(content) != crc_want:
            raise ValueError("bad checksum for " + name)
        e: ZipEntry = ZipEntry(name, content)
        entries.append(move(e))
        p = p + 46 + nlen + elen + clen
        k += 1
    return entries


def zip_names(entries: Ref[list[ZipEntry]]) -> list[str]:
    out: list[str] = []
    for e in entries:
        out.append(e.name)
    return out


def zip_has(entries: Ref[list[ZipEntry]], name: str) -> bool:
    for e in entries:
        if e.name == name:
            return True
    return False


def zip_extract(entries: Ref[list[ZipEntry]], name: str) -> bytes:
    for e in entries:
        if e.name == name:
            return e.data
    raise ValueError("no entry named " + name)


def zip_write(path: str, entries: Ref[list[ZipEntry]], compress: bool) -> None:
    blob: bytes = zip_bytes(entries, compress)
    with open(path, "wb") as f:
        f.write(blob)


def zip_read(path: str) -> list[ZipEntry]:
    with open(path, "rb") as f:
        data: bytes = f.read()
    return zip_parse(data)


ZIP_STORED: int = 0
ZIP_DEFLATED: int = 8


@dataclass
class ZipFile:
    filename: str
    mode: str = "r"
    compression: int = 0
    entries: list[ZipEntry] = []
    compress: bool = False
    closed: bool = False

    def __post_init__(self: Mut[ZipFile]) -> None:
        if self.compression != 0 and self.compression != 8:
            raise NotImplementedError("That compression method is not supported")
        self.compress = self.compression == 8
        if self.mode == "r":
            self.entries = zip_read(self.filename)
        elif self.mode == "a":
            with open(self.filename, "ab") as probe:
                probe.write(b"")
            with open(self.filename, "rb") as f:
                blob: bytes = f.read()
            if len(blob) > 0:
                self.entries = zip_parse(blob)
        elif self.mode != "w":
            raise ValueError("ZipFile requires mode 'r', 'w', 'x', or 'a'")

    def _check(self: Ref[ZipFile]) -> None:
        if self.closed:
            raise ValueError("Attempt to use ZIP archive that was already closed")

    def namelist(self: Ref[ZipFile]) -> list[str]:
        return zip_names(self.entries)

    def read(self: Ref[ZipFile], name: str) -> bytes:
        self._check()
        if not zip_has(self.entries, name):
            raise KeyError(f"There is no item named {name!r} in the archive")
        return zip_extract(self.entries, name)

    def writestr(self: Mut[ZipFile], name: str, data: bytes) -> None:
        if self.closed:
            raise ValueError("Attempt to write to ZIP archive that was already closed")
        if self.mode == "r":
            raise ValueError("write() requires mode 'w', 'x', or 'a'")
        e: ZipEntry = ZipEntry(name, data)
        self.entries.append(move(e))

    def __enter__(self: Ref[ZipFile]) -> ZipFile:
        return self

    def __exit__(self: Mut[ZipFile], exc_type: None, exc: None, tb: None) -> None:
        self.close()

    def close(self: Mut[ZipFile]) -> None:
        if self.closed:
            return
        if self.mode != "r":
            zip_write(self.filename, self.entries, self.compress)
        self.closed = True
