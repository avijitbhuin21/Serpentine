"""Tier-0 type model and annotation parsing (docs/spec.md section 2)."""

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
class TBytes(Type):
    """Immutable byte string (O(1)-copy handle, mirrors str)."""

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "bytes"


@dataclass(frozen=True)
class TByteArray(Type):
    """Mutable byte buffer (non-Copy, mirrors list)."""

    def __str__(self) -> str:
        return "bytearray"


@dataclass(frozen=True)
class TPyVal(Type):
    """Boxed dynamic Python value (immutable, refcounted, Copy handle)."""

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return "PyVal"


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
class TSet(Type):
    """An insertion-ordered set of Copy elements (docs/spec.md D20)."""

    elem: Type

    def __str__(self) -> str:
        return f"set[{self.elem}]"


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
class TUnion(Type):
    """A closed sum of runtime-distinguishable member types (docs/spec.md D24)."""

    members: tuple[Type, ...]

    def is_copy(self) -> bool:
        return all(m.is_copy() for m in self.members)

    def __str__(self) -> str:
        return " | ".join(str(m) for m in self.members)


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
class TEnum(Type):
    """A C-like enumeration: a Copy value carrying one member's ordinal."""

    module: str
    name: str

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
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
class TFunc(Type):
    """A first-class function value (Callable[[...], R]); O(1)-copy handle."""

    params: tuple[Type, ...]
    ret: Type

    def is_copy(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"Callable[[{', '.join(str(p) for p in self.params)}], {self.ret}]"


@dataclass(frozen=True)
class TFile(Type):
    """An open file object; deterministic drop closes it."""

    binary: bool = False

    def __str__(self) -> str:
        return "file"


@dataclass(frozen=True)
class TJoin(Type):
    """A spawned-thread handle (JoinHandle[T]) or asyncio Task[T]; join()/await delivers the result once."""

    ret: Type
    task: bool = False

    def __str__(self) -> str:
        return f"Task[{self.ret}]" if self.task else f"JoinHandle[{self.ret}]"


@dataclass(frozen=True)
class TThread(Type):
    """A threading.Thread/Timer object (D9 v2): start()/join()/is_alive(), name/ident/daemon."""

    def __str__(self) -> str:
        return "Thread"


INT = TInt()
FLOAT = TFloat()
BOOL = TBool()
STR = TStr()
NONE = TNone()

CONV_OWNED = "owned"
CONV_REF = "ref"
CONV_MUT = "mut"
CONV_COPY = "copy"


class FnRef:
    """A folded reference to a module-level function used as build-time metadata."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"FnRef({self.name!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, FnRef) and other.name == self.name

    def __hash__(self) -> int:
        return hash(("FnRef", self.name))

WRAPPERS = {"Owned": CONV_OWNED, "Ref": CONV_REF, "Mut": CONV_MUT}
SHIM_NAMES = {"Owned", "Ref", "Mut", "Shared", "Weak", "move", "native", "registrar", "block_on",
              "PyVal", "pyval_kind", "pyval_json", "fields_of", "fields_json", "fields_build",
              "fields_set", "hooks_json", "run_hook", "run_hook_self",
              "run_hook_get", "run_hook_val", "run_hook_info"}

# Names re-exported from `typing` that the subset understands (annotation-only helpers).
TYPING_NAMES = {"Annotated", "Optional", "Callable", "Generic", "Protocol", "TypeVar",
                "Any", "ClassVar", "Self", "Union", "overload"}

ENUM_BASES = {"Enum", "IntEnum", "StrEnum"}


def union_tag(t: Type) -> str | None:
    """The runtime kind a union member is narrowed by, or None if it cannot be one."""
    simple = {TInt: "int", TFloat: "float", TBool: "bool", TStr: "str", TBytes: "bytes",
              TByteArray: "bytearray", TNone: "NoneType", TList: "list", TDict: "dict",
              TSet: "set", TTuple: "tuple"}
    for cls, tag in simple.items():
        if isinstance(t, cls):
            return tag
    if isinstance(t, (TClass, TEnum)):
        return f"{'C' if isinstance(t, TClass) else 'E'}:{t.module}.{t.name}"
    return None


def union_members(t: Type) -> tuple[Type, ...]:
    """The member list of any sum type (a plain type is a one-member sum)."""
    if isinstance(t, TUnion):
        return t.members
    if isinstance(t, TOptional):
        return (t.inner, NONE)
    return (t,)


def make_union(members) -> Type:
    """Normalize a sum of types: flatten, dedupe, canonically order, collapse."""
    flat: list[Type] = []
    for m in members:
        for part in union_members(m):
            if part not in flat:
                flat.append(part)
    flat.sort(key=str)
    if len(flat) == 1:
        return flat[0]
    if len(flat) == 2 and NONE in flat:
        return TOptional(flat[0] if isinstance(flat[1], TNone) else flat[1])
    return TUnion(tuple(flat))


def union_slot(src: Type, dst: TUnion) -> int | None:
    """The member index a value of type src widens into, or None if it does not fit."""
    for i, m in enumerate(dst.members):
        if src == m:
            return i
    for i, m in enumerate(dst.members):
        if isinstance(m, TFloat) and isinstance(src, TInt):
            return i
    return None


def _union_of(members, rep: Reporter, span: Span) -> Type:
    """Build a union annotation, rejecting members no isinstance test can tell apart."""
    t = make_union(members)
    if not isinstance(t, TUnion):
        return t
    seen: dict[str, Type] = {}
    for m in t.members:
        tag = union_tag(m)
        if tag is None:
            rep.fatal("SE201", "unsupported-feature",
                      f"'{m}' cannot be a union member", span)
        if tag in seen:
            rep.fatal("SE218", "ambiguous-union",
                      f"union members '{seen[tag]}' and '{m}' are both {tag} at runtime, "
                      f"so isinstance() cannot tell them apart", span)
        seen[tag] = m
    return t




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
        simple = {"int": INT, "float": FLOAT, "bool": BOOL, "str": STR,
                  "bytes": TBytes(), "bytearray": TByteArray(), "PyVal": TPyVal()}
        if node.id in simple:
            return simple[node.id]
        if node.id in names:
            return names[node.id]
        if node.id in ("Thread", "Timer"):
            return TThread()
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
        left = _parse_type(node.left, rep, file, names)
        right = _parse_type(node.right, rep, file, names)
        return _union_of([left, right], rep, span)
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
        if base == "Annotated":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return _parse_type(elts[0], rep, file, names)
        if base == "Optional":
            return TOptional(_parse_type(node.slice, rep, file, names))
        if base == "Union":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return _union_of([_parse_type(e, rep, file, names) for e in elts], rep, span)
        if base == "list":
            return TList(_parse_type(node.slice, rep, file, names))
        if base in ("set", "frozenset"):
            elem = _parse_type(node.slice, rep, file, names)
            if not elem.is_copy() or isinstance(elem, (TFunc, TPyVal)):
                rep.fatal("SE201", "unsupported-feature", "set elements must be Copy types", span)
            return TSet(elem)
        if base == "dict":
            if not (isinstance(node.slice, ast.Tuple) and len(node.slice.elts) == 2):
                rep.fatal("SE201", "unsupported-feature", "dict takes exactly two type arguments", span)
            k = _parse_type(node.slice.elts[0], rep, file, names)
            v = _parse_type(node.slice.elts[1], rep, file, names)
            if not k.is_copy() or isinstance(k, (TFunc, TPyVal)):
                rep.fatal("SE201", "unsupported-feature", "dict keys must be Copy types", span)
            return TDict(k, v)
        if base == "tuple":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            return TTuple(tuple(_parse_type(e, rep, file, names) for e in elts))
        if base == "JoinHandle":
            return TJoin(_parse_type(node.slice, rep, file, names))
        if base == "_serp_aio_Task":
            return TJoin(_parse_type(node.slice, rep, file, names), task=True)
        if base == "Callable":
            sl = node.slice
            if not (isinstance(sl, ast.Tuple) and len(sl.elts) == 2
                    and isinstance(sl.elts[0], ast.List)):
                rep.fatal("SE201", "unsupported-feature",
                          "Callable takes the form Callable[[P1, ...], R]", span)
            params = tuple(_parse_type(e, rep, file, names) for e in sl.elts[0].elts)
            ret = _parse_type(sl.elts[1], rep, file, names)
            return TFunc(params, ret)
    rep.fatal("SE201", "unsupported-feature", "annotation is not a Tier-0/1 type", span)
    raise AssertionError("unreachable")


def subst_type(t: Type, sub: dict) -> Type:
    """Substitute type variables in t according to sub."""
    if isinstance(t, TVar):
        return sub.get(t.name, t)
    if isinstance(t, TList):
        return TList(subst_type(t.elem, sub))
    if isinstance(t, TSet):
        return TSet(subst_type(t.elem, sub))
    if isinstance(t, TDict):
        return TDict(subst_type(t.key, sub), subst_type(t.value, sub))
    if isinstance(t, TTuple):
        return TTuple(tuple(subst_type(i, sub) for i in t.items))
    if isinstance(t, TOptional):
        return TOptional(subst_type(t.inner, sub))
    if isinstance(t, TUnion):
        return make_union([subst_type(m, sub) for m in t.members])
    if isinstance(t, TShared):
        return TShared(subst_type(t.inner, sub))
    if isinstance(t, TWeak):
        return TWeak(subst_type(t.inner, sub))
    if isinstance(t, TFunc):
        return TFunc(tuple(subst_type(p, sub) for p in t.params), subst_type(t.ret, sub))
    if isinstance(t, TClass) and t.args:
        return TClass(t.module, t.name, tuple(subst_type(a, sub) for a in t.args))
    return t


def has_tvar(t: Type) -> bool:
    """Whether t contains any unresolved type variable."""
    if isinstance(t, TVar):
        return True
    if isinstance(t, TList):
        return has_tvar(t.elem)
    if isinstance(t, TSet):
        return has_tvar(t.elem)
    if isinstance(t, TDict):
        return has_tvar(t.key) or has_tvar(t.value)
    if isinstance(t, TTuple):
        return any(has_tvar(i) for i in t.items)
    if isinstance(t, (TOptional, TShared, TWeak)):
        return has_tvar(t.inner)
    if isinstance(t, TUnion):
        return any(has_tvar(m) for m in t.members)
    if isinstance(t, TFunc):
        return any(has_tvar(p) for p in t.params) or has_tvar(t.ret)
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
    if isinstance(param, TSet) and isinstance(arg, TSet):
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
    if isinstance(param, TUnion):
        if isinstance(arg, TUnion):
            return len(param.members) == len(arg.members) and \
                all(unify(p, a, sub) for p, a in zip(param.members, arg.members))
        return any(unify(m, arg, dict(sub)) for m in param.members) and not has_tvar(param)
    if isinstance(param, TShared) and isinstance(arg, TShared):
        return unify(param.inner, arg.inner, sub)
    if isinstance(param, TWeak) and isinstance(arg, TWeak):
        return unify(param.inner, arg.inner, sub)
    if isinstance(param, TFunc) and isinstance(arg, TFunc):
        return len(param.params) == len(arg.params) and \
            all(unify(p, a, sub) for p, a in zip(param.params, arg.params)) and \
            unify(param.ret, arg.ret, sub)
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
    elif isinstance(t, TSet):
        yield from walk_types(t.elem)
    elif isinstance(t, TDict):
        yield from walk_types(t.key)
        yield from walk_types(t.value)
    elif isinstance(t, TTuple):
        for i in t.items:
            yield from walk_types(i)
    elif isinstance(t, (TOptional, TShared, TWeak)):
        yield from walk_types(t.inner)
    elif isinstance(t, TUnion):
        for m in t.members:
            yield from walk_types(m)
    elif isinstance(t, TFunc):
        for p in t.params:
            yield from walk_types(p)
        yield from walk_types(t.ret)
    elif isinstance(t, TClass):
        for a in t.args:
            yield from walk_types(a)


def mangle_type(t: Type) -> str:
    """A deterministic identifier-safe encoding of a type (for monomorphized names)."""
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(t)).strip("_")
