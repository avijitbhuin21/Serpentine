"""Tier-0 type model and annotation parsing (SPEC.md section 2)."""

import ast
from dataclasses import dataclass

from .diagnostics import Reporter, Span


class Type:
    """Base class for Tier-0 types."""

    def is_copy(self) -> bool:
        """Whether values of this type have Copy (value) semantics."""
        return False


@dataclass(frozen=True)
class TInt(Type):
    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "int"


@dataclass(frozen=True)
class TFloat(Type):
    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "float"


@dataclass(frozen=True)
class TBool(Type):
    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "bool"


@dataclass(frozen=True)
class TStr(Type):
    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "str"


@dataclass(frozen=True)
class TNone(Type):
    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "None"


@dataclass(frozen=True)
class TList(Type):
    elem: Type

    def __str__(self) -> str:
        return f"list[{self.elem}]"


@dataclass(frozen=True)
class TDict(Type):
    key: Type
    value: Type

    def __str__(self) -> str:
        return f"dict[{self.key}, {self.value}]"


@dataclass(frozen=True)
class TTuple(Type):
    items: tuple[Type, ...]

    def is_copy(self) -> bool:
        return all(t.is_copy() for t in self.items)

    def __str__(self) -> str:
        return f"tuple[{', '.join(str(t) for t in self.items)}]"


@dataclass(frozen=True)
class TOptional(Type):
    inner: Type

    def is_copy(self) -> bool:
        return self.inner.is_copy()

    def __str__(self) -> str:
        return f"{self.inner} | None"


INT = TInt()
FLOAT = TFloat()
BOOL = TBool()
STR = TStr()
NONE = TNone()

CONV_OWNED = "owned"
CONV_REF = "ref"
CONV_MUT = "mut"
CONV_COPY = "copy"

WRAPPERS = {"Owned": CONV_OWNED, "Ref": CONV_REF, "Mut": CONV_MUT}
SHIM_NAMES = {"Owned", "Ref", "Mut", "Shared", "Weak", "move", "native"}


@dataclass
class ParsedAnnotation:
    """An annotation split into its optional ownership wrapper and inner type."""

    conv: str | None
    typ: Type


def parse_annotation(node: ast.expr, rep: Reporter, file: str, *, allow_wrapper: bool) -> ParsedAnnotation:
    """Parse an annotation AST into (wrapper, Type), reporting SE201/SE202 as needed."""
    span = Span(file, node.lineno, node.col_offset)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in WRAPPERS:
        if not allow_wrapper:
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{node.value.id}' is not allowed in this position", span)
        inner = _parse_type(node.slice, rep, file)
        return ParsedAnnotation(WRAPPERS[node.value.id], inner)
    if isinstance(node, ast.Name) and node.id in ("Shared", "Weak"):
        rep.fatal("SE201", "unsupported-feature", f"'{node.id}' is Tier 1, not Tier 0", span)
    return ParsedAnnotation(None, _parse_type(node, rep, file))


def _parse_type(node: ast.expr, rep: Reporter, file: str) -> Type:
    """Parse a type expression with no wrapper permitted anywhere inside."""
    span = Span(file, node.lineno, node.col_offset)
    if isinstance(node, ast.Name):
        simple = {"int": INT, "float": FLOAT, "bool": BOOL, "str": STR}
        if node.id in simple:
            return simple[node.id]
        if node.id in WRAPPERS or node.id in ("Shared", "Weak"):
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{node.id}' cannot be used as a type here", span)
        rep.fatal("SE201", "unsupported-feature", f"unknown Tier-0 type '{node.id}'", span)
    if isinstance(node, ast.Constant) and node.value is None:
        return NONE
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = node.left
        right = node.right
        if isinstance(right, ast.Constant) and right.value is None:
            return TOptional(_parse_type(left, rep, file))
        rep.fatal("SE201", "unsupported-feature",
                  "general unions are not Tier 0; only 'T | None' is allowed", span)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base in WRAPPERS:
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{base}' cannot be nested inside a type", span)
        if base == "list":
            return TList(_parse_type(node.slice, rep, file))
        if base == "dict":
            if not (isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2):
                rep.fatal("SE201", "unsupported-feature", "dict takes exactly two type arguments", span)
            k = _parse_type(node.slice.elts[0], rep, file)
            v = _parse_type(node.slice.elts[1], rep, file)
            if not k.is_copy():
                rep.fatal("SE201", "unsupported-feature", "dict keys must be Copy types", span)
            return TDict(k, v)
        if base == "tuple":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return TTuple(tuple(_parse_type(e, rep, file) for e in elts))
    rep.fatal("SE201", "unsupported-feature", "annotation is not a Tier-0 type", span)
    raise AssertionError("unreachable")
