"""serp-tomllib — drop-in read-only `tomllib` replacement in the Serpentine subset.

Pure Serpentine ([P]). `loads` returns nested dynamic values (PyVal dict) like
`tomllib.loads`, and parse errors raise `TOMLDecodeError` (a ValueError).
Supported: comments, bare/quoted/dotted keys, basic and literal strings,
decimal ints (with underscores), floats, booleans, single-line arrays, and
[a.b] table headers. Not supported (TOMLDecodeError): arrays of tables, inline
tables, multi-line strings/arrays, dates/times, hex/oct/bin ints; error
messages use this module's own "line N:" format, not CPython's.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, PyVal, dataclass, move


class TOMLDecodeError(ValueError):
    pass


@dataclass
class TVal:
    kind: str
    flag: bool
    i: int
    num: float
    s: str
    arr: list[TVal]
    tbl: dict[str, TVal]


def tstr(s: str) -> TVal:
    return TVal("str", False, 0, 0.0, s, [], {})


def tint(i: int) -> TVal:
    return TVal("int", False, i, 0.0, "", [], {})


def tfloat(f: float) -> TVal:
    return TVal("float", False, 0, f, "", [], {})


def tbool(b: bool) -> TVal:
    return TVal("bool", b, 0, 0.0, "", [], {})


def ttable() -> TVal:
    return TVal("table", False, 0, 0.0, "", [], {})


def tarr() -> TVal:
    return TVal("arr", False, 0, 0.0, "", [], {})


def _is_bare_char(c: str) -> bool:
    if c >= "a" and c <= "z":
        return True
    if c >= "A" and c <= "Z":
        return True
    if c >= "0" and c <= "9":
        return True
    return c == "_" or c == "-"


@dataclass
class VP:
    text: str
    pos: int
    line_no: int

    def at_end(self: Ref[VP]) -> bool:
        return self.pos >= len(self.text)

    def peek(self: Ref[VP]) -> str:
        if self.pos >= len(self.text):
            return ""
        return self.text[self.pos]

    def advance(self: Mut[VP]) -> str:
        c: str = self.peek()
        if c == "":
            raise TOMLDecodeError(f"line {self.line_no}: unexpected end of line")
        self.pos += 1
        return c

    def skip_ws(self: Mut[VP]) -> None:
        while not self.at_end():
            c: str = self.text[self.pos]
            if c == " " or c == "\t":
                self.pos += 1
            else:
                break

    def expect(self: Mut[VP], want: str) -> None:
        c: str = self.advance()
        if c != want:
            raise TOMLDecodeError(f"line {self.line_no}: expected {want!r}, got {c!r}")

    def only_trailing(self: Mut[VP]) -> None:
        self.skip_ws()
        if not self.at_end() and self.peek() != "#":
            raise TOMLDecodeError(f"line {self.line_no}: unexpected trailing content")

    def parse_basic_string(self: Mut[VP]) -> str:
        self.expect('"')
        out: list[str] = []
        while True:
            c: str = self.advance()
            if c == '"':
                break
            if c == "\\":
                e: str = self.advance()
                if e == "n":
                    out.append("\n")
                elif e == "t":
                    out.append("\t")
                elif e == "r":
                    out.append("\r")
                elif e == '"':
                    out.append('"')
                elif e == "\\":
                    out.append("\\")
                elif e == "u":
                    hexs: str = ""
                    for _ in range(4):
                        hexs = hexs + self.advance()
                    out.append(chr(_hex_to_int(hexs, self.line_no)))
                else:
                    raise TOMLDecodeError(f"line {self.line_no}: unsupported escape \\{e}")
            else:
                out.append(c)
        return "".join(out)

    def parse_literal_string(self: Mut[VP]) -> str:
        self.expect("'")
        out: list[str] = []
        while True:
            c: str = self.advance()
            if c == "'":
                break
            out.append(c)
        return "".join(out)

    def parse_key_segment(self: Mut[VP]) -> str:
        self.skip_ws()
        c: str = self.peek()
        if c == '"':
            return self.parse_basic_string()
        if c == "'":
            return self.parse_literal_string()
        out: list[str] = []
        while not self.at_end() and _is_bare_char(self.peek()):
            out.append(self.advance())
        if len(out) == 0:
            raise TOMLDecodeError(f"line {self.line_no}: expected a key")
        return "".join(out)

    def parse_key_path(self: Mut[VP]) -> list[str]:
        path: list[str] = [self.parse_key_segment()]
        while True:
            self.skip_ws()
            if self.peek() == ".":
                self.pos += 1
                path.append(self.parse_key_segment())
            else:
                break
        return path

    def parse_value(self: Mut[VP]) -> TVal:
        self.skip_ws()
        c: str = self.peek()
        if c == "":
            raise TOMLDecodeError(f"line {self.line_no}: missing value")
        if c == '"':
            return tstr(self.parse_basic_string())
        if c == "'":
            return tstr(self.parse_literal_string())
        if c == "[":
            return self.parse_array()
        if c == "{":
            raise TOMLDecodeError(f"line {self.line_no}: inline tables are not supported")
        return self.parse_scalar()

    def parse_array(self: Mut[VP]) -> TVal:
        self.expect("[")
        out: TVal = tarr()
        self.skip_ws()
        if self.peek() == "]":
            self.pos += 1
            return out
        while True:
            v: TVal = self.parse_value()
            out.arr.append(move(v))
            self.skip_ws()
            nxt: str = self.advance()
            if nxt == "]":
                break
            if nxt != ",":
                raise TOMLDecodeError(f"line {self.line_no}: expected ',' or ']' in array")
            self.skip_ws()
            if self.peek() == "]":
                self.pos += 1
                break
        return out

    def parse_scalar(self: Mut[VP]) -> TVal:
        out: list[str] = []
        while not self.at_end():
            c: str = self.peek()
            if c == " " or c == "\t" or c == "," or c == "]" or c == "#":
                break
            out.append(self.advance())
        token: str = "".join(out)
        if token == "true":
            return tbool(True)
        if token == "false":
            return tbool(False)
        return _parse_number(token, self.line_no)


def _hex_to_int(hexs: str, line_no: int) -> int:
    digits: str = "0123456789abcdef"
    out: int = 0
    for ch in hexs:
        d: int = digits.find(ch.lower())
        if d < 0:
            raise TOMLDecodeError(f"line {line_no}: invalid \\u escape")
        out = out * 16 + d
    return out


def _parse_number(token: str, line_no: int) -> TVal:
    if token == "":
        raise TOMLDecodeError(f"line {line_no}: missing value")
    body: str = token.replace("_", "")
    if body.startswith("0x") or body.startswith("0o") or body.startswith("0b") \
            or body.startswith("-0x") or body.startswith("+0x"):
        raise TOMLDecodeError(f"line {line_no}: non-decimal integers are not supported")
    is_float: bool = False
    for ch in body:
        if ch == "." or ch == "e" or ch == "E":
            is_float = True
            break
    digits: str = body
    if digits.startswith("-") or digits.startswith("+"):
        digits = digits[1:]
    if digits == "":
        raise TOMLDecodeError(f"line {line_no}: invalid value {token!r}")
    if not is_float:
        for ch2 in digits:
            if ch2 < "0" or ch2 > "9":
                raise TOMLDecodeError(f"line {line_no}: invalid value {token!r}")
        return tint(int(body))
    return tfloat(float(body))


def _with_table(t: Owned[TVal], path: Ref[list[str]], depth: int, line_no: int) -> TVal:
    if depth == len(path):
        return move(t)
    name: str = path[depth]
    sub: TVal = ttable()
    if name in t.tbl:
        sub = t.tbl.pop(name)
        if sub.kind != "table":
            raise TOMLDecodeError(f"line {line_no}: {name!r} is not a table")
    sub2: TVal = _with_table(move(sub), path, depth + 1, line_no)
    t.tbl[name] = move(sub2)
    return move(t)


def _with_set(t: Owned[TVal], path: Ref[list[str]], depth: int, key: str,
              v: Owned[TVal], line_no: int) -> TVal:
    if depth == len(path):
        if key in t.tbl:
            raise TOMLDecodeError(f"line {line_no}: duplicate key {key!r}")
        t.tbl[key] = move(v)
        return move(t)
    name: str = path[depth]
    sub: TVal = ttable()
    if name in t.tbl:
        sub = t.tbl.pop(name)
        if sub.kind != "table":
            raise TOMLDecodeError(f"line {line_no}: {name!r} is not a table")
    sub2: TVal = _with_set(move(sub), path, depth + 1, key, move(v), line_no)
    t.tbl[name] = move(sub2)
    return move(t)


def _loads_tval(text: str) -> TVal:
    root: TVal = ttable()
    table_path: list[str] = []
    lines: list[str] = text.split("\n")
    for idx in range(len(lines)):
        line: str = lines[idx].strip()
        n: int = idx + 1
        if line == "" or line.startswith("#"):
            continue
        if line.startswith("[["):
            raise TOMLDecodeError(f"line {n}: arrays of tables are not supported")
        if line.startswith("["):
            end: int = line.find("]")
            if end < 0:
                raise TOMLDecodeError(f"line {n}: missing ']' in table header")
            rest: str = line[end + 1:].strip()
            if rest != "" and not rest.startswith("#"):
                raise TOMLDecodeError(f"line {n}: unexpected content after table header")
            hp: VP = VP(line[1:end], 0, n)
            table_path = hp.parse_key_path()
            hp.skip_ws()
            if not hp.at_end():
                raise TOMLDecodeError(f"line {n}: invalid table header")
            root = _with_table(move(root), table_path, 0, n)
            continue
        vp: VP = VP(line, 0, n)
        key_path: list[str] = vp.parse_key_path()
        vp.skip_ws()
        vp.expect("=")
        v: TVal = vp.parse_value()
        vp.only_trailing()
        full: list[str] = []
        for seg in table_path:
            full.append(seg)
        for j in range(len(key_path) - 1):
            full.append(key_path[j])
        key: str = key_path[len(key_path) - 1]
        root = _with_set(move(root), full, 0, key, move(v), n)
    return root


def _to_pyval(t: Ref[TVal]) -> PyVal:
    """Convert the internal mutable TVal tree into an immutable PyVal."""
    if t.kind == "str":
        return t.s
    if t.kind == "int":
        return t.i
    if t.kind == "float":
        return t.num
    if t.kind == "bool":
        return t.flag
    if t.kind == "arr":
        items: list[PyVal] = []
        for i in range(len(t.arr)):
            items.append(_to_pyval(t.arr[i]))
        return items
    members: dict[str, PyVal] = {}
    for k, v in t.tbl.items():
        members[k] = _to_pyval(v)
    return members


def loads(s: str) -> PyVal:
    root: TVal = _loads_tval(s)
    return _to_pyval(root)
