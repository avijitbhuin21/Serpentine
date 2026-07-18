"""North-star regression: a self-contained JSON parse/serialize round-trip.

Trimmed from examples/json_parser.py (no CLI, ASCII-only escapes) so the
differential harness locks the parser's dual-execution behavior forever.
"""
from __future__ import annotations
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


def jleaf(kind: str) -> JVal:
    return JVal(kind, False, 0, 0.0, "", [], {})


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
            raise ValueError(f"invalid escape digit {c!r}")
        return v

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
                elif e == "u":
                    a: int = self.hex_digit()
                    b: int = self.hex_digit()
                    cc: int = self.hex_digit()
                    d: int = self.hex_digit()
                    parts.append(chr(a * 4096 + b * 256 + cc * 16 + d))
                else:
                    raise ValueError(f"invalid escape \\{e}")
            else:
                parts.append(c)
        return "".join(parts)

    def parse_number(self: Mut[Parser]) -> JVal:
        start: int = self.pos
        if self.peek() == "-":
            self.pos += 1
        is_float: bool = False
        while not self.at_end():
            c: str = self.text[self.pos]
            if c in "0123456789":
                self.pos += 1
            elif c in ".eE+-":
                is_float = True
                self.pos += 1
            else:
                break
        tok: str = self.text[start:self.pos]
        if len(tok) == 0 or tok == "-":
            raise ValueError(f"invalid number at position {start}")
        if is_float:
            v: JVal = jleaf("float")
            v.num = float(tok)
            return move(v)
        w: JVal = jleaf("int")
        w.i = int(tok)
        return move(w)

    def parse_array(self: Mut[Parser]) -> JVal:
        self.expect("[")
        items: list[JVal] = []
        self.skip_ws()
        if not self.at_end() and self.peek() == "]":
            self.pos += 1
        else:
            while True:
                v: JVal = self.parse_value()
                items.append(move(v))
                self.skip_ws()
                c: str = self.advance()
                if c == "]":
                    break
                if c != ",":
                    raise ValueError(f"expected ',' or ']' in array, got {c!r}")
        out: JVal = jleaf("arr")
        out.arr = move(items)
        return move(out)

    def parse_object(self: Mut[Parser]) -> JVal:
        self.expect("{")
        members: dict[str, JVal] = {}
        self.skip_ws()
        if not self.at_end() and self.peek() == "}":
            self.pos += 1
        else:
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
        out: JVal = jleaf("obj")
        out.obj = move(members)
        return move(out)

    def parse_value(self: Mut[Parser]) -> JVal:
        self.skip_ws()
        c: str = self.peek()
        if c == "{":
            return self.parse_object()
        if c == "[":
            return self.parse_array()
        if c == '"':
            s: str = self.parse_string()
            v: JVal = jleaf("str")
            v.s = s
            return move(v)
        if self.match_word("true"):
            v2: JVal = jleaf("bool")
            v2.flag = True
            return move(v2)
        if self.match_word("false"):
            return jleaf("bool")
        if self.match_word("null"):
            return jleaf("null")
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


def main() -> None:
    docs: list[str] = [
        "null",
        "[1, 2.5, -3, 1e3]",
        '  {"name": "serpentine", "tags": ["fast", "safe"], "stars": 128}  ',
        '{"escaped": "line\\nbreak \\u0041 tab\\there", "empty": [], "deep": {"a": [true, false, null]}}',
        '"just a string"',
    ]
    for doc in docs:
        v: JVal = parse(doc)
        print(dumps(v))
    bad: list[str] = ['{"open": ', "[1, 2", '"unterminated', "01x", ""]
    for doc in bad:
        try:
            w: JVal = parse(doc)
            print("unexpectedly parsed:", dumps(w))
        except ValueError as e:
            print("rejected:", e)


if __name__ == "__main__":
    main()
