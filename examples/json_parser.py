"""json_parser — the Serpentine north-star demo (RESEARCH.md §9).

A complete JSON parser + serializer written once in the Serpentine subset:
develop and debug it under CPython (`python json_parser.py [file.json]`),
then deploy it as a dependency-free native binary (`serp build json_parser.py`).

Notes: object member order is preserved on both sides (insertion-ordered
dicts); integers beyond 64 bits overflow natively (documented int64 divergence).
"""
from __future__ import annotations
import sys
from serpentine import Ref, Mut, dataclass, move

HEX: str = "0123456789abcdef"


@dataclass
class JVal:
    kind: str
    flag: bool
    i: int
    num: float
    s: str
    arr: list[JVal]
    obj: dict[str, JVal]


def jnull() -> JVal:
    return JVal("null", False, 0, 0.0, "", [], {})


def jbool(b: bool) -> JVal:
    return JVal("bool", b, 0, 0.0, "", [], {})


def jint(i: int) -> JVal:
    return JVal("int", False, i, 0.0, "", [], {})


def jfloat(f: float) -> JVal:
    return JVal("float", False, 0, f, "", [], {})


def jstr(s: str) -> JVal:
    return JVal("str", False, 0, 0.0, s, [], {})


@dataclass
class Parser:
    text: str
    pos: int

    def at_end(self: Ref[Parser]) -> bool:
        return self.pos >= len(self.text)

    def peek(self: Ref[Parser]) -> str:
        if self.pos >= len(self.text):
            raise ValueError("unexpected end of JSON input")
        return self.text[self.pos]

    def advance(self: Mut[Parser]) -> str:
        c: str = self.peek()
        self.pos += 1
        return c

    def skip_ws(self: Mut[Parser]) -> None:
        while not self.at_end():
            c: str = self.text[self.pos]
            if c == " " or c == "\t" or c == "\n" or c == "\r":
                self.pos += 1
            else:
                break

    def expect(self: Mut[Parser], want: str) -> None:
        c: str = self.advance()
        if c != want:
            raise ValueError(f"expected {want!r} at position {self.pos - 1}, got {c!r}")

    def match_word(self: Mut[Parser], word: str) -> bool:
        end: int = self.pos + len(word)
        if self.text[self.pos:end] == word:
            self.pos = end
            return True
        return False

    def hex_digit(self: Mut[Parser]) -> int:
        c: str = self.advance().lower()
        v: int = HEX.find(c)
        if v < 0:
            raise ValueError(f"invalid \\u escape digit {c!r}")
        return v

    def hex4(self: Mut[Parser]) -> int:
        a: int = self.hex_digit()
        b: int = self.hex_digit()
        c: int = self.hex_digit()
        d: int = self.hex_digit()
        return a * 4096 + b * 256 + c * 16 + d

    def parse_string(self: Mut[Parser]) -> str:
        self.expect('"')
        parts: list[str] = []
        while True:
            c: str = self.advance()
            if c == '"':
                break
            if c == "\\":
                e: str = self.advance()
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
                    code: int = self.hex4()
                    if 55296 <= code and code <= 56319:
                        self.expect("\\")
                        self.expect("u")
                        low: int = self.hex4()
                        if low < 56320 or low > 57343:
                            raise ValueError("invalid low surrogate in \\u escape")
                        code = 65536 + (code - 55296) * 1024 + (low - 56320)
                    elif 56320 <= code and code <= 57343:
                        raise ValueError("lone low surrogate in \\u escape")
                    parts.append(chr(code))
                else:
                    raise ValueError(f"invalid escape \\{e}")
            elif ord(c) < 32:
                raise ValueError("control character inside string literal")
            else:
                parts.append(c)
        return "".join(parts)

    def parse_number(self: Mut[Parser]) -> JVal:
        start: int = self.pos
        is_int: bool = True
        if self.peek() == "-":
            self.pos += 1
        while not self.at_end():
            c: str = self.text[self.pos]
            if c in "0123456789":
                self.pos += 1
            elif c == "." or c == "e" or c == "E" or c == "+" or c == "-":
                is_int = c == "+" or c == "-"
                if c == "+" or c == "-":
                    is_int = False
                self.pos += 1
            else:
                break
        tok: str = self.text[start:self.pos]
        if len(tok) == 0 or tok == "-":
            raise ValueError(f"invalid number at position {start}")
        has_frac: bool = False
        for ch in tok:
            if ch == "." or ch == "e" or ch == "E":
                has_frac = True
        if has_frac:
            return jfloat(float(tok))
        return jint(int(tok))

    def parse_array(self: Mut[Parser]) -> JVal:
        self.expect("[")
        items: list[JVal] = []
        self.skip_ws()
        if not self.at_end() and self.peek() == "]":
            self.pos += 1
            return JVal("arr", False, 0, 0.0, "", move(items), {})
        while True:
            v: JVal = self.parse_value()
            items.append(move(v))
            self.skip_ws()
            c: str = self.advance()
            if c == "]":
                break
            if c != ",":
                raise ValueError(f"expected ',' or ']' in array, got {c!r}")
            self.skip_ws()
        return JVal("arr", False, 0, 0.0, "", move(items), {})

    def parse_object(self: Mut[Parser]) -> JVal:
        self.expect("{")
        members: dict[str, JVal] = {}
        self.skip_ws()
        if not self.at_end() and self.peek() == "}":
            self.pos += 1
            return JVal("obj", False, 0, 0.0, "", [], move(members))
        while True:
            self.skip_ws()
            key: str = self.parse_string()
            self.skip_ws()
            self.expect(":")
            self.skip_ws()
            v: JVal = self.parse_value()
            members[key] = move(v)
            self.skip_ws()
            c: str = self.advance()
            if c == "}":
                break
            if c != ",":
                raise ValueError(f"expected ',' or '}}' in object, got {c!r}")
        return JVal("obj", False, 0, 0.0, "", [], move(members))

    def parse_value(self: Mut[Parser]) -> JVal:
        self.skip_ws()
        c: str = self.peek()
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c == '"':
            s: str = self.parse_string()
            return jstr(s)
        if self.match_word("true"):
            return jbool(True)
        if self.match_word("false"):
            return jbool(False)
        if self.match_word("null"):
            return jnull()
        return self.parse_number()


def parse(doc: str) -> JVal:
    p: Parser = Parser(doc, 0)
    v: JVal = p.parse_value()
    p.skip_ws()
    if not p.at_end():
        raise ValueError(f"trailing data at position {p.pos}")
    return move(v)


def escape_string(s: str) -> str:
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
        else:
            n: int = ord(c)
            if n < 32:
                parts.append("\\u00" + HEX[n // 16] + HEX[n % 16])
            else:
                parts.append(c)
    parts.append('"')
    return "".join(parts)


def dumps(v: Ref[JVal]) -> str:
    if v.kind == "null":
        return "null"
    if v.kind == "bool":
        return "true" if v.flag else "false"
    if v.kind == "int":
        return f"{v.i}"
    if v.kind == "float":
        return f"{v.num}"
    if v.kind == "str":
        return escape_string(v.s)
    if v.kind == "arr":
        inner: list[str] = [dumps(x) for x in v.arr]
        return "[" + ", ".join(inner) + "]"
    parts: list[str] = []
    for k, m in v.obj.items():
        parts.append(escape_string(k) + ": " + dumps(m))
    return "{" + ", ".join(parts) + "}"


def describe(v: Ref[JVal]) -> str:
    if v.kind == "arr":
        return f"array of {len(v.arr)}"
    if v.kind == "obj":
        return f"object with {len(v.obj)} members"
    return v.kind


def self_test() -> None:
    docs: list[str] = [
        "null",
        "[1, 2.5, -3, 1e3]",
        '  {"name": "serpentine", "tags": ["fast", "safe"], "stars": 128}  ',
        '{"escaped": "line\\nbreak \\u0041\\u00e9 \\ud83d\\ude00", "empty": [], "obj": {"deep": [true, false, null]}}',
        '"just a string"',
    ]
    for doc in docs:
        v: JVal = parse(doc)
        print(describe(v))
        print(dumps(v))
    bad: list[str] = ['{"open": ', "[1, 2", '"unterminated', "01x", ""]
    for doc in bad:
        try:
            w: JVal = parse(doc)
            print("unexpectedly parsed:", dumps(w))
        except ValueError as e:
            print("rejected:", e)


def run_file(path: str) -> None:
    with open(path, "r") as f:
        doc: str = f.read()
    v: JVal = parse(doc)
    print(describe(v))
    print(dumps(v))


def main() -> None:
    args: list[str] = sys.argv
    if len(args) > 1:
        run_file(args[1])
    else:
        self_test()


if __name__ == "__main__":
    main()
