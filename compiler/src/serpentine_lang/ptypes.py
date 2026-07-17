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


@dataclass(frozen=True)
class TClass(Type):
    """A Tier-1 dataclass type (args filled for generic class instantiations)."""

    module: str
    name: str
    args: tuple = ()

    def __str__(self) -> str:
        if self.args:
            return f"{self.name}[{', '.join(str(a) for a in self.args)}]"
        return self.name


@dataclass(frozen=True)
class TVar(Type):
    """An opaque generic type parameter (treated as non-Copy)."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class TShared(Type):
    """Refcounted escape hatch: handle copies freely, contents behind runtime borrow."""

    inner: Type

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"Shared[{self.inner}]"


@dataclass(frozen=True)
class TWeak(Type):
    """Weak counterpart of Shared (cycles leak unless broken with Weak)."""

    inner: Type

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"Weak[{self.inner}]"


@dataclass(frozen=True)
class TExc(Type):
    """A caught exception value (except E as e)."""

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "exception"


@dataclass(frozen=True)
class TFile(Type):
    """An open file object; deterministic drop closes it."""

    def __str__(self) -> str:
        return "file"


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


def parse_annotation(node: ast.expr, rep: Reporter, file: str, *, allow_wrapper: bool,
                     names: dict[str, Type] | None = None) -> ParsedAnnotation:
    """Parse an annotation AST into (wrapper, Type), reporting SE201/SE202 as needed."""
    names = names or {}
    span = Span(file, node.lineno, node.col_offset)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
            node = ast.copy_location(node, ast.Constant(value=None, lineno=span.line,
                                                        col_offset=span.col))
            ast.fix_missing_locations(node)
        except SyntaxError:
            rep.fatal("SE201", "unsupported-feature", "unparsable string annotation", span)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in WRAPPERS:
        if not allow_wrapper:
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{node.value.id}' is not allowed in this position", span)
        inner = _parse_type(node.slice, rep, file, names)
        return ParsedAnnotation(WRAPPERS[node.value.id], inner)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id in ("Shared", "Weak"):
        inner = _parse_type(node.slice, rep, file, names)
        return ParsedAnnotation(None, TShared(inner) if node.value.id == "Shared" else TWeak(inner))
    return ParsedAnnotation(None, _parse_type(node, rep, file, names))


def _parse_type(node: ast.expr, rep: Reporter, file: str, names: dict[str, Type]) -> Type:
    """Parse a type expression with no ownership wrapper permitted anywhere inside."""
    span = Span(file, node.lineno, node.col_offset)
    if isinstance(node, ast.Name):
        simple = {"int": INT, "float": FLOAT, "bool": BOOL, "str": STR}
        if node.id in simple:
            return simple[node.id]
        if node.id in names:
            return names[node.id]
        if node.id in WRAPPERS or node.id in ("Shared", "Weak"):
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{node.id}' cannot be used as a type here", span)
        rep.fatal("SE201", "unsupported-feature", f"unknown Tier-0/1 type '{node.id}'", span)
    if isinstance(node, ast.Constant) and node.value is None:
        return NONE
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            inner = ast.parse(node.value, mode="eval").body
            ast.fix_missing_locations(inner)
            return _parse_type(inner, rep, file, names)
        except SyntaxError:
            rep.fatal("SE201", "unsupported-feature", "unparsable string annotation", span)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = node.left
        right = node.right
        if isinstance(right, ast.Constant) and right.value is None:
            return TOptional(_parse_type(left, rep, file, names))
        rep.fatal("SE201", "unsupported-feature",
                  "general unions are not Tier 0/1; only 'T | None' is allowed", span)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base in WRAPPERS:
            rep.fatal("SE202", "invalid-wrapper-position",
                      f"ownership wrapper '{base}' cannot be nested inside a type", span)
        if base == "Shared":
            return TShared(_parse_type(node.slice, rep, file, names))
        if base == "Weak":
            return TWeak(_parse_type(node.slice, rep, file, names))
        if base in names and isinstance(names[base], TClass):
            cls = names[base]
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return TClass(cls.module, cls.name,
                          tuple(_parse_type(e, rep, file, names) for e in elts))
        if base == "list":
            return TList(_parse_type(node.slice, rep, file, names))
        if base == "dict":
            if not (isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2):
                rep.fatal("SE201", "unsupported-feature", "dict takes exactly two type arguments", span)
            k = _parse_type(node.slice.elts[0], rep, file, names)
            v = _parse_type(node.slice.elts[1], rep, file, names)
            if not k.is_copy():
                rep.fatal("SE201", "unsupported-feature", "dict keys must be Copy types", span)
            return TDict(k, v)
        if base == "tuple":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return TTuple(tuple(_parse_type(e, rep, file, names) for e in elts))
    rep.fatal("SE201", "unsupported-feature", "annotation is not a Tier-0/1 type", span)
    raise AssertionError("unreachable")


def subst_type(t: Type, sub: dict) -> Type:
    """Substitute type variables in t according to sub."""
    if isinstance(t, TVar):
        return sub.get(t.name, t)
    if isinstance(t, TList):
        return TList(subst_type(t.elem, sub))
    if isinstance(t, TDict):
        return TDict(subst_type(t.key, sub), subst_type(t.value, sub))
    if isinstance(t, TTuple):
        return TTuple(tuple(subst_type(i, sub) for i in t.items))
    if isinstance(t, TOptional):
        return TOptional(subst_type(t.inner, sub))
    if isinstance(t, TShared):
        return TShared(subst_type(t.inner, sub))
    if isinstance(t, TWeak):
        return TWeak(subst_type(t.inner, sub))
    if isinstance(t, TClass) and t.args:
        return TClass(t.module, t.name, tuple(subst_type(a, sub) for a in t.args))
    return t


def has_tvar(t: Type) -> bool:
    """Whether t contains any unresolved type variable."""
    if isinstance(t, TVar):
        return True
    if isinstance(t, TList):
        return has_tvar(t.elem)
    if isinstance(t, TDict):
        return has_tvar(t.key) or has_tvar(t.value)
    if isinstance(t, TTuple):
        return any(has_tvar(i) for i in t.items)
    if isinstance(t, (TOptional, TShared, TWeak)):
        return has_tvar(t.inner)
    if isinstance(t, TClass):
        return any(has_tvar(a) for a in t.args)
    return False


def unify(param: Type, arg: Type, sub: dict) -> bool:
    """Unify a (possibly generic) parameter type against a concrete argument type."""
    if isinstance(param, TVar):
        if param.name in sub:
            return sub[param.name] == arg
        sub[param.name] = arg
        return True
    if isinstance(param, TList) and isinstance(arg, TList):
        return unify(param.elem, arg.elem, sub)
    if isinstance(param, TDict) and isinstance(arg, TDict):
        return unify(param.key, arg.key, sub) and unify(param.value, arg.value, sub)
    if isinstance(param, TTuple) and isinstance(arg, TTuple):
        return len(param.items) == len(arg.items) and \
            all(unify(p, a, sub) for p, a in zip(param.items, arg.items))
    if isinstance(param, TOptional):
        if isinstance(arg, TOptional):
            return unify(param.inner, arg.inner, sub)
        if isinstance(arg, TNone):
            return not has_tvar(param)
        return unify(param.inner, arg, sub)
    if isinstance(param, TShared) and isinstance(arg, TShared):
        return unify(param.inner, arg.inner, sub)
    if isinstance(param, TWeak) and isinstance(arg, TWeak):
        return unify(param.inner, arg.inner, sub)
    if isinstance(param, TClass) and isinstance(arg, TClass):
        return param.module == arg.module and param.name == arg.name and \
            len(param.args) == len(arg.args) and \
            all(unify(p, a, sub) for p, a in zip(param.args, arg.args))
    return param == arg


def walk_types(t: Type):
    """Yield t and every type nested inside it."""
    yield t
    if isinstance(t, TList):
        yield from walk_types(t.elem)
    elif isinstance(t, TDict):
        yield from walk_types(t.key)
        yield from walk_types(t.value)
    elif isinstance(t, TTuple):
        for i in t.items:
            yield from walk_types(i)
    elif isinstance(t, (TOptional, TShared, TWeak)):
        yield from walk_types(t.inner)
    elif isinstance(t, TClass):
        for a in t.args:
            yield from walk_types(a)


def mangle_type(t: Type) -> str:
    """A deterministic identifier-safe encoding of a type (for monomorphized names)."""
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(t)).strip("_")
