"""serp-json — drop-in `json` replacement in the Serpentine subset.

`loads` returns nested dynamic values (PyVal: dict/list/str/int/float/bool/None)
and `dumps` accepts them, matching the stdlib json module's API and error
messages (pinned to CPython 3.11). The same source compiles natively with
`serp` and imports under CPython.

Caps: ints saturate at int64 natively (OverflowError instead of big ints);
`load`/`dump` file variants, `indent`, `separators`, `cls`, and `object_hook`
are not provided.
"""
from __future__ import annotations
from serpentine import Mut, PyVal, pyval_kind, dataclass

HEX: str = "0123456789abcdef"


def _linecol(doc: str, pos: int) -> tuple[int, int]:
    line: int = 1
    col: int = 1
    i: int = 0
    while i < pos:
        if doc[i] == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1
    return (line, col)


def _errmsg(msg: str, doc: str, pos: int) -> str:
    lc: tuple[int, int] = _linecol(doc, pos)
    return f"{msg}: line {lc[0]} column {lc[1]} (char {pos})"


@dataclass
class _Parser:
    text: str
    pos: int

    def at_end(self: Mut[_Parser]) -> bool:
        return self.pos >= len(self.text)

    def skip_ws(self: Mut[_Parser]) -> None:
        while not self.at_end():
            c: str = self.text[self.pos]
            if c == " " or c == "\t" or c == "\n" or c == "\r":
                self.pos += 1
            else:
                break

    def match_word(self: Mut[_Parser], word: str) -> bool:
        end: int = self.pos + len(word)
        if self.text[self.pos:end] == word:
            self.pos = end
            return True
        return False

    def hex4(self: Mut[_Parser], escape_start: int) -> int:
        out: int = 0
        for _ in range(4):
            if self.at_end():
                raise ValueError(_errmsg("Invalid \\uXXXX escape", self.text, escape_start + 1))
            c: str = self.text[self.pos].lower()
            v: int = HEX.find(c)
            if v < 0:
                raise ValueError(_errmsg("Invalid \\uXXXX escape", self.text, escape_start + 1))
            out = out * 16 + v
            self.pos += 1
        return out

    def parse_string(self: Mut[_Parser]) -> str:
        start: int = self.pos
        self.pos += 1
        parts: list[str] = []
        while True:
            if self.at_end():
                raise ValueError(_errmsg("Unterminated string starting at", self.text, start))
            c: str = self.text[self.pos]
            self.pos += 1
            if c == '"':
                break
            if c == "\\":
                if self.at_end():
                    raise ValueError(_errmsg("Unterminated string starting at", self.text, start))
                esc_pos: int = self.pos - 1
                e: str = self.text[self.pos]
                self.pos += 1
                if e == '"' or e == "\\" or e == "/":
                    parts.append(e)
                elif e == "n":
                    parts.append("\n")
                elif e == "t":
                    parts.append("\t")
                elif e == "r":
                    parts.append("\r")
                elif e == "b":
                    parts.append(chr(8))
                elif e == "f":
                    parts.append(chr(12))
                elif e == "u":
                    code: int = self.hex4(esc_pos)
                    if 55296 <= code and code <= 56319 \
                            and self.text[self.pos:self.pos + 2] == "\\u":
                        surr_pos: int = self.pos
                        self.pos += 2
                        low: int = self.hex4(surr_pos)
                        if 56320 <= low and low <= 57343:
                            code = 65536 + (code - 55296) * 1024 + (low - 56320)
                            parts.append(chr(code))
                        else:
                            parts.append(chr(code))
                            parts.append(chr(low))
                    else:
                        parts.append(chr(code))
                else:
                    raise ValueError(_errmsg("Invalid \\escape", self.text, esc_pos))
            elif ord(c) < 32:
                raise ValueError(_errmsg("Invalid control character at",
                                         self.text, self.pos - 1))
            else:
                parts.append(c)
        return "".join(parts)

    def parse_number(self: Mut[_Parser]) -> PyVal:
        start: int = self.pos
        n: int = len(self.text)
        i: int = self.pos
        if i < n and self.text[i] == "-":
            i += 1
        if i < n and self.text[i] == "0":
            i += 1
        elif i < n and "1" <= self.text[i] and self.text[i] <= "9":
            while i < n and "0" <= self.text[i] and self.text[i] <= "9":
                i += 1
        else:
            raise ValueError(_errmsg("Expecting value", self.text, start))
        is_float: bool = False
        if i + 1 < n and self.text[i] == "." and "0" <= self.text[i + 1] \
                and self.text[i + 1] <= "9":
            is_float = True
            i += 1
            while i < n and "0" <= self.text[i] and self.text[i] <= "9":
                i += 1
        if i < n and (self.text[i] == "e" or self.text[i] == "E"):
            j: int = i + 1
            if j < n and (self.text[j] == "+" or self.text[j] == "-"):
                j += 1
            if j < n and "0" <= self.text[j] and self.text[j] <= "9":
                is_float = True
                i = j
                while i < n and "0" <= self.text[i] and self.text[i] <= "9":
                    i += 1
        tok: str = self.text[start:i]
        self.pos = i
        if is_float:
            return float(tok)
        return int(tok)

    def parse_object(self: Mut[_Parser]) -> PyVal:
        self.pos += 1
        members: dict[str, PyVal] = {}
        self.skip_ws()
        if not self.at_end() and self.text[self.pos] == "}":
            self.pos += 1
            return members
        while True:
            self.skip_ws()
            if self.at_end() or self.text[self.pos] != '"':
                raise ValueError(_errmsg("Expecting property name enclosed in double quotes",
                                         self.text, self.pos))
            key: str = self.parse_string()
            self.skip_ws()
            if self.at_end() or self.text[self.pos] != ":":
                raise ValueError(_errmsg("Expecting ':' delimiter", self.text, self.pos))
            self.pos += 1
            self.skip_ws()
            members[key] = self.parse_value()
            self.skip_ws()
            if not self.at_end() and self.text[self.pos] == "}":
                self.pos += 1
                break
            if self.at_end() or self.text[self.pos] != ",":
                raise ValueError(_errmsg("Expecting ',' delimiter", self.text, self.pos))
            self.pos += 1
        return members

    def parse_array(self: Mut[_Parser]) -> PyVal:
        self.pos += 1
        items: list[PyVal] = []
        self.skip_ws()
        if not self.at_end() and self.text[self.pos] == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.parse_value())
            self.skip_ws()
            if not self.at_end() and self.text[self.pos] == "]":
                self.pos += 1
                break
            if self.at_end() or self.text[self.pos] != ",":
                raise ValueError(_errmsg("Expecting ',' delimiter", self.text, self.pos))
            self.pos += 1
            self.skip_ws()
        return items

    def parse_value(self: Mut[_Parser]) -> PyVal:
        self.skip_ws()
        if self.at_end():
            raise ValueError(_errmsg("Expecting value", self.text, self.pos))
        c: str = self.text[self.pos]
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c == '"':
            return self.parse_string()
        if self.match_word("true"):
            return True
        if self.match_word("false"):
            return False
        if self.match_word("null"):
            return None
        if self.match_word("NaN"):
            return float("nan")
        if self.match_word("Infinity"):
            return float("inf")
        if self.match_word("-Infinity"):
            return -float("inf")
        return self.parse_number()


def loads(s: str) -> PyVal:
    p: _Parser = _Parser(s, 0)
    v: PyVal = p.parse_value()
    p.skip_ws()
    if not p.at_end():
        raise ValueError(_errmsg("Extra data", s, p.pos))
    return v


def _u4(n: int) -> str:
    return "\\u" + HEX[n // 4096 % 16] + HEX[n // 256 % 16] + HEX[n // 16 % 16] + HEX[n % 16]


def _escape_string(s: str, ensure_ascii: bool) -> str:
    parts: list[str] = ['"']
    for c in s:
        if c == '"':
            parts.append('\\"')
        elif c == "\\":
            parts.append("\\\\")
        elif c == "\n":
            parts.append("\\n")
        elif c == "\t":
            parts.append("\\t")
        elif c == "\r":
            parts.append("\\r")
        elif c == chr(8):
            parts.append("\\b")
        elif c == chr(12):
            parts.append("\\f")
        else:
            n: int = ord(c)
            if n < 32:
                parts.append("\\u00" + HEX[n // 16] + HEX[n % 16])
            elif n > 126 and ensure_ascii:
                if n > 65535:
                    m: int = n - 65536
                    parts.append(_u4(55296 + m // 1024))
                    parts.append(_u4(56320 + m % 1024))
                else:
                    parts.append(_u4(n))
            else:
                parts.append(c)
    parts.append('"')
    return "".join(parts)


def _dump_float(v: PyVal) -> str:
    f: float = float(v)
    if f != f:
        return "NaN"
    text: str = f"{f}"
    if text == "inf":
        return "Infinity"
    if text == "-inf":
        return "-Infinity"
    return text


def _dump(v: PyVal, ensure_ascii: bool, sort_keys: bool) -> str:
    kind: str = pyval_kind(v)
    if kind == "NoneType":
        return "null"
    if kind == "bool":
        return "true" if bool(v) else "false"
    if kind == "int":
        return str(v)
    if kind == "float":
        return _dump_float(v)
    if kind == "str":
        return _escape_string(str(v), ensure_ascii)
    if kind == "list":
        inner: list[str] = []
        for x in v:
            inner.append(_dump(x, ensure_ascii, sort_keys))
        return "[" + ", ".join(inner) + "]"
    if kind == "dict":
        keys: list[str] = []
        for k in v:
            keys.append(str(k))
        if sort_keys:
            keys = sorted(keys)
        parts: list[str] = []
        for key in keys:
            parts.append(_escape_string(key, ensure_ascii) + ": "
                         + _dump(v[key], ensure_ascii, sort_keys))
        return "{" + ", ".join(parts) + "}"
    raise TypeError(f"Object of type {kind} is not JSON serializable")


def dumps(obj: PyVal, ensure_ascii: bool = True, sort_keys: bool = False) -> str:
    return _dump(obj, ensure_ascii, sort_keys)
