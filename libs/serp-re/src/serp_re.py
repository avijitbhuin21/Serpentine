"""serp-re — a `re` drop-in with true backtracking semantics.

Pure Serpentine ([P]). Patterns compile to a small instruction program run
by a recursive backtracking VM, so alternation is first-alternative-wins,
quantifiers are greedy/lazy with full backtracking into repeated bodies, and
capture groups record the last iteration — CPython `re` semantics, not the
old leftmost-longest NFA. Surface: compile/match/fullmatch/search/findall/
finditer/sub/split/escape, Pattern and Match objects (group/groups/start/
end/span/string, CPython-style repr), error (Exception subclass) with
CPython 3.11 messages, flags IGNORECASE/I, MULTILINE/M, DOTALL/S (combine
with `+` — the subset has no `|` on ints). Syntax: literals, '.', escapes
(\\d \\D \\w \\W \\s \\S \\b \\B \\A \\Z, punctuation), classes [a-z]
[^...], quantifiers * + ? {m,n} (and lazy variants), groups (...) (?:...)
(?P<name>...) (named groups are positional here), alternation, anchors ^ $.
Caps: no backreferences or lookarounds (loud error), \\w is ASCII, findall
with 2+ groups raises (use finditer), groups() is a PyVal list (not a
tuple), split() fills unmatched group parts with '' (not None), sub() repl
is a string template (no callables), no inline flags, {m,n} capped at 1000,
deep quantified matches recurse (very long inputs can exhaust the stack).
ReDoS guard (divergence): each match attempt may run at most STEP_LIMIT VM
steps and recurse at most MAX_DEPTH levels; catastrophic backtracking or
very deep quantified matches raise error(...) instead of hanging or
overflowing the stack.
"""
from __future__ import annotations
from serpentine import Ref, Mut, Owned, PyVal, dataclass, move

I: int = 2
IGNORECASE: int = 2
M: int = 8
MULTILINE: int = 8
S: int = 16
DOTALL: int = 16
NOFLAG: int = 0
STEP_LIMIT: int = 1000000
MAX_DEPTH: int = 10000

DIGITS: str = "0123456789"
LOWER: str = "abcdefghijklmnopqrstuvwxyz"
UPPER: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPACE: str = " \t\n\r\x0b\x0c"
_SPECIAL: str = "()[]{}?*+-|^$\\.&~# \t\n\r\x0b\x0c"


class error(Exception):
    pass


def _word_chars() -> str:
    return LOWER + UPPER + DIGITS + "_"


def _is_word(c: str) -> bool:
    return _word_chars().find(c) >= 0


@dataclass
class Node:
    kind: str
    ch: str = ""
    chars: str = ""
    neg: bool = False
    kids: list[Node] = []
    min: int = 0
    max: int = 0
    lazy: bool = False
    gindex: int = -1


@dataclass
class Inst:
    op: str
    ch: str = ""
    chars: str = ""
    neg: bool = False
    a: int = 0
    b: int = 0


@dataclass
class RP:
    pat: str
    pos: int
    ngroups: int

    def at_end(self: Ref[RP]) -> bool:
        return self.pos >= len(self.pat)

    def peek(self: Ref[RP]) -> str:
        if self.pos >= len(self.pat):
            return ""
        return self.pat[self.pos]

    def advance(self: Mut[RP]) -> str:
        c: str = self.peek()
        if c == "":
            raise error("unexpected end of pattern")
        self.pos += 1
        return c

    def parse_alt(self: Mut[RP]) -> Node:
        branches: list[Node] = [self.parse_seq()]
        while self.peek() == "|":
            self.pos += 1
            branches.append(self.parse_seq())
        if len(branches) == 1:
            return branches.pop()
        return Node("alt", kids=move(branches))

    def parse_seq(self: Mut[RP]) -> Node:
        kids: list[Node] = []
        while not self.at_end():
            c: str = self.peek()
            if c == "|" or c == ")":
                break
            atom: Node = self.parse_atom()
            atom = self.parse_quant(move(atom))
            kids.append(move(atom))
        return Node("seq", kids=move(kids))

    def parse_quant(self: Mut[RP], atom: Owned[Node]) -> Node:
        c: str = self.peek()
        mn: int = 0
        mx: int = 0
        has: bool = False
        qpos: int = self.pos
        if c == "*":
            mx = -1
            has = True
            self.pos += 1
        elif c == "+":
            mn = 1
            mx = -1
            has = True
            self.pos += 1
        elif c == "?":
            mx = 1
            has = True
            self.pos += 1
        elif c == "{":
            spec: tuple[bool, int, int] = self._try_brace()
            has = spec[0]
            mn = spec[1]
            mx = spec[2]
        if not has:
            return atom
        if atom.kind == "rep" or (atom.kind == "seq" and len(atom.kids) == 0):
            raise error(f"nothing to repeat at position {qpos}")
        if mx != -1 and mn > mx:
            raise error(f"min repeat greater than max repeat at position {qpos + 1}")
        if mn > 1000 or mx > 1000:
            raise error(f"repeat count too large at position {qpos}")
        lz: bool = False
        if self.peek() == "?":
            lz = True
            self.pos += 1
        nxt: str = self.peek()
        if nxt == "*" or nxt == "+" or nxt == "?":
            raise error(f"multiple repeat at position {self.pos}")
        wrapped: list[Node] = [move(atom)]
        return Node("rep", kids=move(wrapped), min=mn, max=mx, lazy=lz)

    def _try_brace(self: Mut[RP]) -> tuple[bool, int, int]:
        """Parse {m}/{m,}/{,n}/{m,n} after an atom; '{' stays literal if malformed."""
        i: int = self.pos + 1
        n: int = len(self.pat)
        lo: int = 0
        lo_digits: int = 0
        while i < n and DIGITS.find(self.pat[i]) >= 0:
            lo = lo * 10 + int(self.pat[i])
            lo_digits += 1
            i += 1
        has_comma: bool = False
        hi: int = -1
        hi_digits: int = 0
        if i < n and self.pat[i] == ",":
            has_comma = True
            i += 1
            hi = 0
            while i < n and DIGITS.find(self.pat[i]) >= 0:
                hi = hi * 10 + int(self.pat[i])
                hi_digits += 1
                i += 1
        if i >= n or self.pat[i] != "}":
            return (False, 0, 0)
        if lo_digits == 0 and hi_digits == 0:
            return (False, 0, 0)
        self.pos = i + 1
        if not has_comma:
            return (True, lo, lo)
        if hi_digits == 0:
            return (True, lo, -1)
        if lo_digits == 0:
            return (True, 0, hi)
        return (True, lo, hi)

    def parse_atom(self: Mut[RP]) -> Node:
        apos: int = self.pos
        c: str = self.advance()
        if c == "(":
            if self.peek() == "?":
                self.pos += 1
                ext: str = self.peek()
                if ext == ":":
                    self.pos += 1
                    inner0: Node = self.parse_alt()
                    if self.peek() != ")":
                        raise error(f"missing ), unterminated subpattern at position {apos}")
                    self.pos += 1
                    return inner0
                if ext == "P":
                    self.pos += 1
                    if self.peek() != "<":
                        raise error(f"unknown extension ?P{self.peek()} at position {apos}")
                    self.pos += 1
                    while self.peek() != ">" and not self.at_end():
                        self.pos += 1
                    if self.peek() != ">":
                        raise error(f"missing >, unterminated name at position {apos}")
                    self.pos += 1
                    self.ngroups += 1
                    g0: int = self.ngroups
                    inner1: Node = self.parse_alt()
                    if self.peek() != ")":
                        raise error(f"missing ), unterminated subpattern at position {apos}")
                    self.pos += 1
                    named: list[Node] = [move(inner1)]
                    return Node("group", kids=move(named), gindex=g0)
                if ext == "=" or ext == "!" or ext == "<":
                    raise error("lookarounds are not supported natively")
                raise error(f"unsupported extension (?{ext} at position {apos}")
            self.ngroups += 1
            g: int = self.ngroups
            inner: Node = self.parse_alt()
            if self.peek() != ")":
                raise error(f"missing ), unterminated subpattern at position {apos}")
            self.pos += 1
            caught: list[Node] = [move(inner)]
            return Node("group", kids=move(caught), gindex=g)
        if c == "[":
            return self.parse_class(apos)
        if c == ".":
            return Node("any")
        if c == "^":
            return Node("start")
        if c == "$":
            return Node("end")
        if c == "\\":
            return self.parse_escape(apos)
        if c == "*" or c == "+" or c == "?":
            raise error(f"nothing to repeat at position {apos}")
        return Node("char", ch=c)

    def parse_escape(self: Mut[RP], bpos: int) -> Node:
        e: str = self.advance()
        if e == "d":
            return Node("class", chars=DIGITS)
        if e == "D":
            return Node("class", chars=DIGITS, neg=True)
        if e == "w":
            return Node("class", chars=_word_chars())
        if e == "W":
            return Node("class", chars=_word_chars(), neg=True)
        if e == "s":
            return Node("class", chars=SPACE)
        if e == "S":
            return Node("class", chars=SPACE, neg=True)
        if e == "b":
            return Node("bound")
        if e == "B":
            return Node("nbound")
        if e == "A":
            return Node("atA")
        if e == "Z":
            return Node("atZ")
        if e == "n":
            return Node("char", ch="\n")
        if e == "t":
            return Node("char", ch="\t")
        if e == "r":
            return Node("char", ch="\r")
        if e == "f":
            return Node("char", ch="\x0c")
        if e == "v":
            return Node("char", ch="\x0b")
        if DIGITS.find(e) >= 0:
            raise error("backreferences are not supported natively")
        if _word_chars().find(e) >= 0:
            raise error(f"bad escape \\{e} at position {bpos}")
        return Node("char", ch=e)

    def parse_class(self: Mut[RP], cpos: int) -> Node:
        neg: bool = False
        if self.peek() == "^":
            neg = True
            self.pos += 1
        chars: list[str] = []
        first: bool = True
        while True:
            c: str = self.peek()
            if c == "":
                raise error(f"unterminated character set at position {cpos}")
            if c == "]" and not first:
                self.pos += 1
                break
            first = False
            rpos: int = self.pos
            self.pos += 1
            if c == "\\":
                e: str = self.advance()
                if e == "d":
                    chars.append(DIGITS)
                    continue
                if e == "w":
                    chars.append(_word_chars())
                    continue
                if e == "s":
                    chars.append(SPACE)
                    continue
                if e == "D" or e == "W" or e == "S":
                    raise error("negated class escapes inside [] are not supported natively")
                if e == "n":
                    c = "\n"
                elif e == "t":
                    c = "\t"
                elif e == "r":
                    c = "\r"
                elif e == "f":
                    c = "\x0c"
                elif e == "v":
                    c = "\x0b"
                else:
                    c = e
            if self.peek() == "-" and self.pos + 1 < len(self.pat) \
                    and self.pat[self.pos + 1] != "]":
                self.pos += 1
                hi: str = self.advance()
                if hi == "\\":
                    hi = self.advance()
                if ord(hi) < ord(c):
                    raise error(f"bad character range {c}-{hi} at position {rpos}")
                code: int = ord(c)
                while code <= ord(hi):
                    chars.append(chr(code))
                    code += 1
            else:
                chars.append(c)
        return Node("class", chars="".join(chars), neg=neg)


def _size(n: Ref[Node]) -> int:
    """Instruction count a node compiles to (mirrors _emit exactly)."""
    if n.kind == "seq":
        total: int = 0
        for i in range(len(n.kids)):
            total += _size(n.kids[i])
        return total
    if n.kind == "alt":
        return _size_alt(n.kids, 0)
    if n.kind == "group":
        return _size(n.kids[0]) + 2
    if n.kind == "rep":
        k: int = _size(n.kids[0])
        if n.max == -1:
            return n.min * k + k + 3
        return n.min * k + (n.max - n.min) * (k + 1)
    return 1


def _size_alt(kids: Ref[list[Node]], i: int) -> int:
    """Instruction count for alternation branches kids[i:]."""
    if i == len(kids) - 1:
        return _size(kids[i])
    return 2 + _size(kids[i]) + _size_alt(kids, i + 1)


def _emit(n: Ref[Node], out: Mut[list[Inst]], ctr: Mut[list[int]]) -> None:
    """Append a node's instructions (relative jump targets, no patching)."""
    if n.kind == "char":
        out.append(Inst("char", ch=n.ch))
        return
    if n.kind == "class":
        out.append(Inst("class", chars=n.chars, neg=n.neg))
        return
    if n.kind == "seq":
        for i in range(len(n.kids)):
            _emit(n.kids[i], out, ctr)
        return
    if n.kind == "alt":
        _emit_alt(n.kids, 0, out, ctr)
        return
    if n.kind == "group":
        out.append(Inst("save", a=2 * n.gindex))
        _emit(n.kids[0], out, ctr)
        out.append(Inst("save", a=2 * n.gindex + 1))
        return
    if n.kind == "rep":
        for _ in range(n.min):
            _emit(n.kids[0], out, ctr)
        k: int = _size(n.kids[0])
        if n.max == -1:
            sid: int = ctr[0]
            ctr[0] += 1
            if n.lazy:
                out.append(Inst("split", a=k + 3, b=1))
            else:
                out.append(Inst("split", a=1, b=k + 3))
            out.append(Inst("mark", a=sid))
            _emit(n.kids[0], out, ctr)
            out.append(Inst("prog", a=-(k + 2), b=sid))
            return
        _emit_opts(n.kids, n.max - n.min, n.lazy, out, ctr)
        return
    out.append(Inst(n.kind))


def _emit_alt(kids: Ref[list[Node]], i: int, out: Mut[list[Inst]], ctr: Mut[list[int]]) -> None:
    """Emit alternation branches in priority order."""
    if i == len(kids) - 1:
        _emit(kids[i], out, ctr)
        return
    k: int = _size(kids[i])
    rest: int = _size_alt(kids, i + 1)
    out.append(Inst("split", a=1, b=k + 2))
    _emit(kids[i], out, ctr)
    out.append(Inst("jmp", a=rest + 1))
    _emit_alt(kids, i + 1, out, ctr)


def _emit_opts(kids: Ref[list[Node]], count: int, lazy: bool, out: Mut[list[Inst]],
               ctr: Mut[list[int]]) -> None:
    """Emit `count` nested optional copies of kids[0] (bounded {m,n} tail)."""
    if count == 0:
        return
    k: int = _size(kids[0])
    inner: int = (count - 1) * (k + 1)
    if lazy:
        out.append(Inst("split", a=1 + k + inner, b=1))
    else:
        out.append(Inst("split", a=1, b=1 + k + inner))
    _emit(kids[0], out, ctr)
    _emit_opts(kids, count - 1, lazy, out, ctr)


def _ch_eq(c: str, want: str, ic: bool) -> bool:
    """Single-character comparison honoring IGNORECASE (ASCII)."""
    if c == want:
        return True
    if ic:
        return c.lower() == want.lower()
    return False


def _in_class(c: str, chars: str, ic: bool) -> bool:
    """Character-class membership honoring IGNORECASE (ASCII)."""
    if chars.find(c) >= 0:
        return True
    if ic:
        return chars.find(c.lower()) >= 0 or chars.find(c.upper()) >= 0
    return False


def _vm(prog: Ref[list[Inst]], text: str, pc: int, pos: int, anchor: int,
        caps: Mut[list[int]], marks: Mut[list[int]], ic: bool, dotall: bool,
        ml: bool, budget: Mut[list[int]], depth: int) -> int:
    """Recursive backtracking VM: end position of a match from (pc, pos), or -1."""
    if depth > MAX_DEPTH:
        raise error("regex recursion limit exceeded (input too long for this pattern)")
    p: int = pc
    at: int = pos
    n: int = len(text)
    while True:
        budget[0] -= 1
        if budget[0] < 0:
            raise error("regex step limit exceeded (catastrophic backtracking)")
        op: str = prog[p].op
        if op == "char":
            if at < n and _ch_eq(text[at], prog[p].ch, ic):
                p += 1
                at += 1
                continue
            return -1
        if op == "class":
            if at < n and _in_class(text[at], prog[p].chars, ic) != prog[p].neg:
                p += 1
                at += 1
                continue
            return -1
        if op == "any":
            if at < n and (dotall or text[at] != "\n"):
                p += 1
                at += 1
                continue
            return -1
        if op == "split":
            r: int = _vm(prog, text, p + prog[p].a, at, anchor, caps, marks, ic, dotall, ml, budget, depth + 1)
            if r >= 0:
                return r
            p = p + prog[p].b
            continue
        if op == "jmp":
            p = p + prog[p].a
            continue
        if op == "save":
            idx: int = prog[p].a
            old: int = caps[idx]
            caps[idx] = at
            r2: int = _vm(prog, text, p + 1, at, anchor, caps, marks, ic, dotall, ml, budget, depth + 1)
            if r2 < 0:
                caps[idx] = old
            return r2
        if op == "mark":
            midx: int = prog[p].a
            mold: int = marks[midx]
            marks[midx] = at
            r3: int = _vm(prog, text, p + 1, at, anchor, caps, marks, ic, dotall, ml, budget, depth + 1)
            if r3 < 0:
                marks[midx] = mold
            return r3
        if op == "prog":
            if at == marks[prog[p].b]:
                p += 1
                continue
            p = p + prog[p].a
            continue
        if op == "start":
            if at == 0 or (ml and at > 0 and text[at - 1] == "\n"):
                p += 1
                continue
            return -1
        if op == "end":
            if at == n or (at == n - 1 and text[at] == "\n") \
                    or (ml and at < n and text[at] == "\n"):
                p += 1
                continue
            return -1
        if op == "atA":
            if at == 0:
                p += 1
                continue
            return -1
        if op == "atZ":
            if at == n:
                p += 1
                continue
            return -1
        if op == "ne":
            if at > anchor:
                p += 1
                continue
            return -1
        if op == "bound" or op == "nbound":
            before: bool = at > 0 and _is_word(text[at - 1])
            after: bool = at < n and _is_word(text[at])
            hit: bool = before != after
            if (op == "bound" and hit) or (op == "nbound" and not hit):
                p += 1
                continue
            return -1
        if op == "match":
            return at
        return -1
    return -1


def _run(prog: Ref[list[Inst]], text: str, pos: int, ngroups: int, nstars: int,
         flags: int) -> list[int]:
    """Attempt a match anchored at pos; caps list with caps[1] = -1 on failure."""
    caps: list[int] = []
    i: int = 0
    while i < 2 * ngroups + 2:
        caps.append(-1)
        i += 1
    marks: list[int] = []
    j: int = 0
    while j < nstars:
        marks.append(-1)
        j += 1
    ic: bool = (flags // 2) % 2 == 1
    ml: bool = (flags // 8) % 2 == 1
    dotall: bool = (flags // 16) % 2 == 1
    budget: list[int] = [STEP_LIMIT]
    end: int = _vm(prog, text, 0, pos, pos, caps, marks, ic, dotall, ml, budget, 0)
    caps[0] = pos
    caps[1] = end
    return caps


@dataclass
class Match:
    string: str
    _caps: list[int]
    _groups: int

    def _check(self: Ref[Match], n: int) -> None:
        if n < 0 or n > self._groups:
            raise IndexError("no such group")

    def group(self: Ref[Match], n: int = 0) -> str | None:
        self._check(n)
        s: int = self._caps[2 * n]
        if s < 0:
            return None
        return self.string[s:self._caps[2 * n + 1]]

    def groups(self: Ref[Match]) -> PyVal:
        out: list[PyVal] = []
        g: int = 1
        while g <= self._groups:
            s: int = self._caps[2 * g]
            if s < 0:
                out.append(None)
            else:
                out.append(self.string[s:self._caps[2 * g + 1]])
            g += 1
        return out

    def start(self: Ref[Match], n: int = 0) -> int:
        self._check(n)
        return self._caps[2 * n]

    def end(self: Ref[Match], n: int = 0) -> int:
        self._check(n)
        return self._caps[2 * n + 1]

    def span(self: Ref[Match], n: int = 0) -> tuple[int, int]:
        return (self.start(n), self.end(n))

    def __repr__(self: Ref[Match]) -> str:
        got: str = self.string[self._caps[0]:self._caps[1]]
        return f"<re.Match object; span=({self._caps[0]}, {self._caps[1]}), match={got!r}>"


def _expand(repl: str, text: str, caps: Ref[list[int]], ngroups: int) -> str:
    """Expand a sub() replacement template (\\1..\\99, \\g<n>, \\\\, \\n...)."""
    out: list[str] = []
    i: int = 0
    n: int = len(repl)
    while i < n:
        c: str = repl[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e: str = repl[i + 1]
        if DIGITS.find(e) >= 0:
            g: int = int(e)
            j: int = i + 2
            if j < n and DIGITS.find(repl[j]) >= 0 and g * 10 + int(repl[j]) <= ngroups:
                g = g * 10 + int(repl[j])
                j += 1
            if g > ngroups:
                raise error(f"invalid group reference {g} at position {i + 1}")
            s: int = caps[2 * g]
            if s >= 0:
                out.append(text[s:caps[2 * g + 1]])
            i = j
            continue
        if e == "g":
            j2: int = i + 2
            if j2 >= n or repl[j2] != "<":
                raise error(f"missing < at position {i + 2}")
            j2 += 1
            g2: int = 0
            digs: int = 0
            while j2 < n and DIGITS.find(repl[j2]) >= 0:
                g2 = g2 * 10 + int(repl[j2])
                digs += 1
                j2 += 1
            if digs == 0 or j2 >= n or repl[j2] != ">":
                raise error(f"missing group name at position {i + 3}")
            if g2 > ngroups:
                raise error(f"invalid group reference {g2} at position {i + 3}")
            s2: int = caps[2 * g2]
            if s2 >= 0:
                out.append(text[s2:caps[2 * g2 + 1]])
            i = j2 + 1
            continue
        if e == "\\":
            out.append("\\")
        elif e == "n":
            out.append("\n")
        elif e == "t":
            out.append("\t")
        elif e == "r":
            out.append("\r")
        else:
            raise error(f"bad escape \\{e} at position {i}")
        i += 2
    return "".join(out)


@dataclass
class Pattern:
    pattern: str
    flags: int
    groups: int
    _prog: list[Inst]
    _prog_full: list[Inst]
    _prog_ne: list[Inst]
    _nstars: int

    def _scan_at(self: Ref[Pattern], string: str, pos: int, mv: bool) -> list[int]:
        """One scan attempt at pos honoring CPython's must-advance rule."""
        caps: list[int] = _run(self._prog, string, pos, self.groups, self._nstars,
                               self.flags)
        if caps[1] >= 0 and mv and caps[1] == pos:
            return _run(self._prog_ne, string, pos, self.groups, self._nstars,
                        self.flags)
        return caps

    def match(self: Ref[Pattern], string: str) -> Match | None:
        caps: list[int] = _run(self._prog, string, 0, self.groups, self._nstars,
                               self.flags)
        if caps[1] < 0:
            return None
        return Match(string, move(caps), self.groups)

    def fullmatch(self: Ref[Pattern], string: str) -> Match | None:
        caps: list[int] = _run(self._prog_full, string, 0, self.groups, self._nstars,
                               self.flags)
        if caps[1] < 0:
            return None
        return Match(string, move(caps), self.groups)

    def search(self: Ref[Pattern], string: str) -> Match | None:
        pos: int = 0
        while pos <= len(string):
            caps: list[int] = _run(self._prog, string, pos, self.groups, self._nstars,
                                   self.flags)
            if caps[1] >= 0:
                return Match(string, move(caps), self.groups)
            pos += 1
        return None

    def findall(self: Ref[Pattern], string: str) -> list[str]:
        if self.groups > 1:
            raise error("findall with more than one group is not supported natively "
                        "— use finditer")
        out: list[str] = []
        pos: int = 0
        mv: bool = False
        n: int = len(string)
        while pos <= n:
            caps: list[int] = self._scan_at(string, pos, mv)
            if caps[1] < 0:
                pos += 1
                mv = False
                continue
            if self.groups == 1:
                s: int = caps[2]
                out.append("" if s < 0 else string[s:caps[3]])
            else:
                out.append(string[caps[0]:caps[1]])
            mv = caps[1] == caps[0]
            pos = caps[1]
        return out

    def finditer(self: Ref[Pattern], string: str) -> list[Match]:
        out: list[Match] = []
        pos: int = 0
        mv: bool = False
        n: int = len(string)
        while pos <= n:
            caps: list[int] = self._scan_at(string, pos, mv)
            if caps[1] < 0:
                pos += 1
                mv = False
                continue
            end: int = caps[1]
            mv = end == caps[0]
            out.append(Match(string, move(caps), self.groups))
            pos = end
        return out

    def sub(self: Ref[Pattern], repl: str, string: str, count: int = 0) -> str:
        out: list[str] = []
        last: int = 0
        pos: int = 0
        done: int = 0
        mv: bool = False
        n: int = len(string)
        while pos <= n:
            if count > 0 and done >= count:
                break
            caps: list[int] = self._scan_at(string, pos, mv)
            if caps[1] < 0:
                pos += 1
                mv = False
                continue
            out.append(string[last:caps[0]])
            out.append(_expand(repl, string, caps, self.groups))
            done += 1
            last = caps[1]
            mv = caps[1] == caps[0]
            pos = caps[1]
        out.append(string[last:])
        return "".join(out)

    def split(self: Ref[Pattern], string: str, maxsplit: int = 0) -> list[str]:
        out: list[str] = []
        last: int = 0
        pos: int = 0
        done: int = 0
        mv: bool = False
        n: int = len(string)
        while pos <= n:
            if maxsplit > 0 and done >= maxsplit:
                break
            caps: list[int] = self._scan_at(string, pos, mv)
            if caps[1] < 0:
                pos += 1
                mv = False
                continue
            out.append(string[last:caps[0]])
            g: int = 1
            while g <= self.groups:
                s: int = caps[2 * g]
                out.append("" if s < 0 else string[s:caps[2 * g + 1]])
                g += 1
            done += 1
            last = caps[1]
            mv = caps[1] == caps[0]
            pos = caps[1]
        out.append(string[last:])
        return out


def compile(pattern: str, flags: int = 0) -> Pattern:
    """Compile a pattern like re.compile."""
    p: RP = RP(pattern, 0, 0)
    root: Node = p.parse_alt()
    if not p.at_end():
        raise error(f"unbalanced parenthesis at position {p.pos}")
    prog: list[Inst] = []
    ctr: list[int] = [0]
    _emit(root, prog, ctr)
    prog.append(Inst("match"))
    nstars: int = ctr[0]
    progf: list[Inst] = []
    ctr2: list[int] = [0]
    _emit(root, progf, ctr2)
    progf.append(Inst("atZ"))
    progf.append(Inst("match"))
    progn: list[Inst] = []
    ctr3: list[int] = [0]
    _emit(root, progn, ctr3)
    progn.append(Inst("ne"))
    progn.append(Inst("match"))
    return Pattern(pattern, flags, p.ngroups, move(prog), move(progf), move(progn),
                   nstars)


def match(pattern: str, string: str, flags: int = 0) -> Match | None:
    """re.match: anchored at the start of the string."""
    return compile(pattern, flags).match(string)


def fullmatch(pattern: str, string: str, flags: int = 0) -> Match | None:
    """re.fullmatch: must consume the whole string."""
    return compile(pattern, flags).fullmatch(string)


def search(pattern: str, string: str, flags: int = 0) -> Match | None:
    """re.search: first match scanning left to right."""
    return compile(pattern, flags).search(string)


def findall(pattern: str, string: str, flags: int = 0) -> list[str]:
    """re.findall (0 or 1 groups; use finditer for more)."""
    return compile(pattern, flags).findall(string)


def finditer(pattern: str, string: str, flags: int = 0) -> list[Match]:
    """re.finditer, eager: the list of Match objects."""
    return compile(pattern, flags).finditer(string)


def sub(pattern: str, repl: str, string: str, count: int = 0, flags: int = 0) -> str:
    """re.sub with a string replacement template."""
    return compile(pattern, flags).sub(repl, string, count)


def split(pattern: str, string: str, maxsplit: int = 0, flags: int = 0) -> list[str]:
    """re.split; capture-group parts are included ('' when unmatched)."""
    return compile(pattern, flags).split(string, maxsplit)


def escape(pattern: str) -> str:
    """re.escape: backslash special characters."""
    out: list[str] = []
    for i in range(len(pattern)):
        c: str = pattern[i]
        if _SPECIAL.find(c) >= 0:
            out.append("\\" + c)
        else:
            out.append(c)
    return "".join(out)
