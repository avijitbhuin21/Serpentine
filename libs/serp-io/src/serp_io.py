"""serp-io — file helpers, StringIO/BytesIO, and buffered byte reading.

Pure Serpentine ([P]): the same source runs under CPython and compiles
natively, sitting directly on the language's built-in text/binary file IO
(open modes r/w/a/rb/wb/ab). StringIO and BytesIO mirror io.StringIO /
io.BytesIO (read/readline/write/seek/tell/truncate/getvalue/close with
CPython's error messages); no context-manager support yet (`with` is
file-only). ByteReader gives buffered, position-tracked reads over an
in-memory bytes value.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, dataclass, move


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        data: bytes = f.read()
    return data


def write_bytes(path: str, data: bytes) -> int:
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def append_bytes(path: str, data: bytes) -> int:
    with open(path, "ab") as f:
        f.write(data)
    return len(data)


def read_text(path: str) -> str:
    with open(path, "r") as f:
        text: str = f.read()
    return text


def write_text(path: str, text: str) -> int:
    with open(path, "w") as f:
        f.write(text)
    return len(text)


def append_text(path: str, text: str) -> int:
    with open(path, "a") as f:
        f.write(text)
    return len(text)


def read_lines(path: str) -> list[str]:
    text: str = read_text(path)
    if text == "":
        return []
    if text.endswith("\n"):
        text = text[0:len(text) - 1]
    lines: list[str] = text.split("\n")
    out: list[str] = []
    for line in lines:
        if line.endswith("\r"):
            out.append(line[0:len(line) - 1])
        else:
            out.append(line)
    return out


def file_size(path: str) -> int:
    return len(read_bytes(path))


def copy_file(src: str, dst: str) -> int:
    return write_bytes(dst, read_bytes(src))


@dataclass
class StringIO:
    buf: str = ""
    pos: int = 0
    closed: bool = False

    def _check(self: Ref[StringIO]) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file")

    def getvalue(self: Ref[StringIO]) -> str:
        self._check()
        return self.buf

    def read(self: Mut[StringIO], size: int = -1) -> str:
        self._check()
        if size < 0:
            rest: str = self.buf[self.pos:len(self.buf)]
            self.pos = len(self.buf)
            return rest
        out: str = self.buf[self.pos:self.pos + size]
        self.pos = self.pos + len(out)
        return out

    def readline(self: Mut[StringIO], size: int = -1) -> str:
        self._check()
        end: int = len(self.buf)
        i: int = self.pos
        while i < end:
            if self.buf[i] == "\n":
                i += 1
                break
            i += 1
        if size >= 0 and self.pos + size < i:
            i = self.pos + size
        out: str = self.buf[self.pos:i]
        self.pos = i
        return out

    def readlines(self: Mut[StringIO]) -> list[str]:
        out: list[str] = []
        while True:
            line: str = self.readline()
            if line == "":
                break
            out.append(line)
        return out

    def write(self: Mut[StringIO], s: str) -> int:
        self._check()
        if self.pos > len(self.buf):
            pad: list[str] = []
            for _ in range(self.pos - len(self.buf)):
                pad.append("\x00")
            self.buf = self.buf + "".join(pad)
        self.buf = self.buf[0:self.pos] + s + self.buf[self.pos + len(s):len(self.buf)]
        self.pos = self.pos + len(s)
        return len(s)

    def writelines(self: Mut[StringIO], lines: Ref[list[str]]) -> None:
        for i in range(len(lines)):
            n: int = self.write(lines[i])

    def tell(self: Ref[StringIO]) -> int:
        self._check()
        return self.pos

    def seek(self: Mut[StringIO], offset: int, whence: int = 0) -> int:
        self._check()
        if whence == 0:
            if offset < 0:
                raise ValueError(f"Negative seek position {offset}")
            self.pos = offset
        elif whence == 1:
            if offset != 0:
                raise OSError("Can't do nonzero cur-relative seeks")
        elif whence == 2:
            if offset != 0:
                raise OSError("Can't do nonzero cur-relative seeks")
            self.pos = len(self.buf)
        else:
            raise ValueError(f"Invalid whence ({whence}, should be 0, 1 or 2)")
        return self.pos

    def truncate(self: Mut[StringIO], size: int = -1) -> int:
        self._check()
        n: int = self.pos if size < 0 else size
        if len(self.buf) > n:
            self.buf = self.buf[0:n]
        return n

    def flush(self: Ref[StringIO]) -> None:
        pass

    def __enter__(self: Ref[StringIO]) -> StringIO:
        return self

    def __exit__(self: Mut[StringIO], exc_type: None, exc: None, tb: None) -> None:
        self.closed = True

    def close(self: Mut[StringIO]) -> None:
        self.closed = True


@dataclass
class BytesIO:
    buf: bytes = b""
    pos: int = 0
    closed: bool = False

    def _check(self: Ref[BytesIO]) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file.")

    def getvalue(self: Ref[BytesIO]) -> bytes:
        self._check()
        return self.buf

    def read(self: Mut[BytesIO], size: int = -1) -> bytes:
        self._check()
        if size < 0:
            rest: bytes = self.buf[self.pos:len(self.buf)]
            self.pos = len(self.buf)
            return rest
        out: bytes = self.buf[self.pos:self.pos + size]
        self.pos = self.pos + len(out)
        return out

    def readline(self: Mut[BytesIO], size: int = -1) -> bytes:
        self._check()
        end: int = len(self.buf)
        i: int = self.pos
        while i < end:
            if self.buf[i] == 10:
                i += 1
                break
            i += 1
        if size >= 0 and self.pos + size < i:
            i = self.pos + size
        out: bytes = self.buf[self.pos:i]
        self.pos = i
        return out

    def write(self: Mut[BytesIO], data: bytes) -> int:
        self._check()
        if self.pos > len(self.buf):
            pad: bytearray = bytearray(b"")
            for _ in range(self.pos - len(self.buf)):
                pad.append(0)
            self.buf = self.buf + bytes(pad)
        self.buf = self.buf[0:self.pos] + data + self.buf[self.pos + len(data):len(self.buf)]
        self.pos = self.pos + len(data)
        return len(data)

    def tell(self: Ref[BytesIO]) -> int:
        self._check()
        return self.pos

    def seek(self: Mut[BytesIO], offset: int, whence: int = 0) -> int:
        self._check()
        target: int = 0
        if whence == 0:
            target = offset
            if target < 0:
                raise ValueError(f"negative seek value {offset}")
        elif whence == 1:
            target = self.pos + offset
            if target < 0:
                target = 0
        elif whence == 2:
            target = len(self.buf) + offset
            if target < 0:
                target = 0
        else:
            raise ValueError(f"invalid whence ({whence}, should be 0, 1 or 2)")
        if target < 0:
            raise ValueError(f"negative seek value {target}")
        self.pos = target
        return self.pos

    def truncate(self: Mut[BytesIO], size: int = -1) -> int:
        self._check()
        n: int = self.pos if size < 0 else size
        if len(self.buf) > n:
            self.buf = self.buf[0:n]
        return n

    def flush(self: Ref[BytesIO]) -> None:
        self._check()

    def __enter__(self: Ref[BytesIO]) -> BytesIO:
        return self

    def __exit__(self: Mut[BytesIO], exc_type: None, exc: None, tb: None) -> None:
        self.closed = True

    def close(self: Mut[BytesIO]) -> None:
        self.closed = True


@dataclass
class ByteReader:
    data: bytes
    pos: int

    def remaining(self: Ref[ByteReader]) -> int:
        return len(self.data) - self.pos

    def at_eof(self: Ref[ByteReader]) -> bool:
        return self.pos >= len(self.data)

    def tell(self: Ref[ByteReader]) -> int:
        return self.pos

    def seek(self: Mut[ByteReader], pos: int) -> None:
        if pos < 0:
            raise ValueError("negative seek position")
        self.pos = pos

    def skip(self: Mut[ByteReader], n: int) -> None:
        if n < 0:
            raise ValueError("negative skip amount")
        self.pos = self.pos + n

    def peek(self: Ref[ByteReader], n: int) -> bytes:
        return self.data[self.pos:self.pos + n]

    def read(self: Mut[ByteReader], n: int) -> bytes:
        if n < 0:
            raise ValueError("negative read amount")
        chunk: bytes = self.data[self.pos:self.pos + n]
        self.pos = self.pos + len(chunk)
        return chunk

    def read_all(self: Mut[ByteReader]) -> bytes:
        chunk: bytes = self.data[self.pos:len(self.data)]
        self.pos = len(self.data)
        return chunk


def reader(data: bytes) -> ByteReader:
    return ByteReader(data, 0)


def file_reader(path: str) -> ByteReader:
    return ByteReader(read_bytes(path), 0)
