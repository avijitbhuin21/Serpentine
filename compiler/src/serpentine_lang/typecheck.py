"""Type checker: symbols, annotation enforcement, Tier-0 typing, is-None narrowing.

Also enforces the subset (SE201/204/206/207/208/210/211/212/214), call-site move
discipline (SE002/SE003/SE006/SE209), and collects the ownership facts that SIR
lowering and the Rust backend consume.
"""

import ast
import copy
import re
from dataclasses import dataclass, field

from .diagnostics import Reporter, Span
from .frontend import (BUILTIN_EXC, Module, Program, collect_user_exceptions, enum_members,
                       exc_ancestors, expand_type_aliases, resolve_reexports)
from .ptypes import (BOOL, CONV_COPY, CONV_MUT, CONV_OWNED, CONV_REF, FLOAT, FnRef, INT,
                     NONE, STR,
                     Type, TBool, TByteArray, TBytes, TClass, TDict, TEnum, TExc, TFile, TFloat,
                     TFunc, TInt, TJoin, TList, TNone, TOptional, TPyVal, TSet, TShared, TStr,
                     TThread, TTuple, TVar, TWeak, has_tvar, mangle_type, parse_annotation, subst_type,
                     unify)
from .ptypes import TUnion, make_union, union_slot, union_tag


@dataclass(frozen=True)
class TIter(Type):
    """Internal type for keys()/values()/items()/range/enumerate results (for-only)."""

    kind: str
    elem: tuple[Type, ...]

    def __str__(self) -> str:
        return f"<{self.kind} iterator>"


@dataclass(frozen=True)
class TIterObj(Type):
    """A first-class list iterator handle (Tier 2): block-scoped borrow, next() only."""

    elem: Type

    def __str__(self) -> str:
        return f"<list iterator of {self.elem}>"


@dataclass
class Param:
    name: str
    conv: str
    typ: Type
    default: ast.expr | None = None


@dataclass
class FuncSig:
    module: str
    name: str
    params: list[Param]
    ret: Type
    node: ast.FunctionDef
    is_template: bool = False
    cls: str | None = None          # owning class for methods
    subst: dict = field(default_factory=dict)   # typevar substitution for instantiations


@dataclass
class ClassInfo:
    """A Tier-1 dataclass: fields in declaration order plus method templates."""

    module: str
    name: str
    node: ast.ClassDef
    fields: dict[str, Type] = field(default_factory=dict)
    field_order: list[str] = field(default_factory=list)
    field_defaults: dict[str, ast.Constant] = field(default_factory=dict)
    field_meta: dict[str, dict] = field(default_factory=dict)
    methods: dict[str, FuncSig] = field(default_factory=dict)
    properties: set[str] = field(default_factory=set)
    statics: dict[str, tuple[str, str]] = field(default_factory=dict)
    hooks: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    typevars: list[str] = field(default_factory=list)
    frozen: bool = False
    overloads: dict[str, list[FuncSig]] = field(default_factory=dict)   # D40 @overload stubs


@dataclass
class EnumInfo:
    """A C-like enum class: constant int/str members in declaration order."""

    module: str
    name: str
    node: ast.ClassDef
    base: str
    members: list = field(default_factory=list)
    value_type: Type = STR


@dataclass
class ProtoInfo:
    """A Tier-2 structural protocol: required method signatures only."""

    module: str
    name: str
    methods: dict[str, tuple[list[Param], Type]] = field(default_factory=dict)


# Exception classes recognized by raise/except (docs/spec.md section 11 + Tier-1 additions).
KNOWN_EXC = BUILTIN_EXC


@dataclass
class FuncFacts:
    """Ownership facts for one function, consumed by SIR lowering."""

    sig: FuncSig
    locals: dict[str, Type] = field(default_factory=dict)
    events: list[tuple] = field(default_factory=list)


NUMERIC = (TInt, TFloat)


def _expect_member(expect, kind):
    """Unwrap an expected sum type down to the member a literal of `kind` fits."""
    if isinstance(expect, TOptional):
        return expect.inner
    if isinstance(expect, TUnion):
        for m in expect.members:
            if isinstance(m, kind):
                return m
    return expect


# Calls recognized in a field-default (or Annotated extra) position as build-time
# metadata rather than a runtime value: their keyword arguments are folded into
# ClassInfo.field_meta and surfaced to generated code through fields_json().
META_CALLS = {"Field", "field"}
# Calls recognized in a class-body assignment position as build-time class metadata.
CONFIG_CALLS = {"ConfigDict", "dict"}
_NOMETA = object()

# Operator dunders (Tier-2 operator overloading on user classes).
BINOP_DUNDER = {ast.Add: "__add__", ast.Sub: "__sub__", ast.Mult: "__mul__",
                ast.Div: "__truediv__", ast.FloorDiv: "__floordiv__",
                ast.Mod: "__mod__", ast.Pow: "__pow__", ast.MatMult: "__matmul__",
                ast.BitAnd: "__and__", ast.BitOr: "__or__", ast.BitXor: "__xor__"}
CMP_DUNDER = {ast.Lt: "__lt__", ast.LtE: "__le__", ast.Gt: "__gt__", ast.GtE: "__ge__"}
EQ_DUNDER = {ast.Eq: "__eq__", ast.NotEq: "__ne__"}
# Reflected arithmetic (D39): `scalar <op> obj` dispatches to obj.__r<op>__(scalar).
RBINOP_DUNDER = {ast.Add: "__radd__", ast.Sub: "__rsub__", ast.Mult: "__rmul__",
                 ast.Div: "__rtruediv__", ast.FloorDiv: "__rfloordiv__",
                 ast.Mod: "__rmod__", ast.Pow: "__rpow__"}
OP_DUNDERS = set(BINOP_DUNDER.values()) | set(CMP_DUNDER.values()) | set(EQ_DUNDER.values()) | \
    set(RBINOP_DUNDER.values()) | \
    {"__neg__", "__invert__", "__getitem__", "__setitem__", "__len__"}
# Non-operator dunders with dedicated support (Tier-2 protocol forms).
UNSUPPORTED_EXPR_HINTS = {
    "GeneratorExp": ("a generator expression",
                     "use a list comprehension instead, e.g. `sum([x * x for x in xs])`"),
    "NamedExpr": ("the walrus operator `:=`", "assign the value on its own line first"),
    "Await": ("`await` here", "await only inside `async def` bodies, as a statement or "
              "assignment (`x = await f()`)"),
    "Yield": ("`yield` (generator functions)",
              "build and return a list, or write a class with `__iter__`/`__next__`"),
    "YieldFrom": ("`yield from` (generator functions)",
                  "build and return a list, or write a class with `__iter__`/`__next__`"),
    "Starred": ("`*` unpacking in an expression",
                "pass the list itself, or index the elements explicitly"),
}

ALLOWED_DUNDERS = OP_DUNDERS | {"__str__", "__repr__", "__post_init__", "__init__",
                                 "__setattr__", "__abs__",
                                "__next__", "__iter__",
                                "__enter__", "__exit__", "__aenter__", "__aexit__"}


def _int_widens(src: "Type", dst: "Type") -> bool:
    """Whether an int argument may widen into a `float` or `float | None` parameter."""
    if not isinstance(src, TInt):
        return False
    if isinstance(dst, TFloat):
        return True
    return isinstance(dst, TOptional) and isinstance(dst.inner, TFloat)


def _self_field(target: ast.expr) -> str | None:
    """The field name of a `self.<name>` place expression, else None."""
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
            and target.value.id == "self":
        return target.attr
    return None


class _SelfRewriter(ast.NodeTransformer):
    """Rewrite `self.<field>` reads in a user `__init__` into the hoisted local slots."""

    def __init__(self, info: "ClassInfo", slots: dict[str, str], assigned: list[str],
                 rep: Reporter, file: str):
        self.info = info
        self.slots = slots
        self.assigned = assigned
        self.rep = rep
        self.file = file

    def _span(self, node: ast.AST) -> Span:
        return Span(self.file, getattr(node, "lineno", 1), getattr(node, "col_offset", 0))

    def _reject_write(self, target: ast.expr, node: ast.AST) -> None:
        if _self_field(target) is not None:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"'self.{_self_field(target)}' must be assigned at the top "
                           f"level of __init__ — conditional or nested field writes are "
                           f"not supported", self._span(node))

    def visit_Assign(self, node: ast.Assign):
        for t in node.targets:
            self._reject_write(t, node)
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        self._reject_write(node.target, node)
        return self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        self._reject_write(node.target, node)
        return self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        self.rep.fatal("SE201", "unsupported-feature",
                       "__init__ cannot return — every field is assigned exactly once "
                       "and the instance is built at the end of the body",
                       self._span(node))

    def visit_Attribute(self, node: ast.Attribute):
        field_name = _self_field(node)
        if field_name is None:
            return self.generic_visit(node)
        if field_name not in self.info.fields:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"'self.{field_name}' is not a field of '{self.info.name}' — "
                           f"__init__ may only read and assign declared fields",
                           self._span(node))
        if field_name not in self.assigned:
            self.rep.fatal("SE217", "uninitialized-field",
                           f"field '{field_name}' is read in __init__ before it is "
                           f"assigned", self._span(node))
        return ast.copy_location(ast.Name(id=self.slots[field_name], ctx=node.ctx), node)

    def visit_Name(self, node: ast.Name):
        if node.id == "self":
            self.rep.fatal("SE201", "unsupported-feature",
                           "'self' may only be used as 'self.<field>' inside __init__",
                           self._span(node))
        return node


class TypeChecker:
    """Whole-program Tier-0 type checker."""


    def __init__(self, program: Program, rep: Reporter):
        self.program = program
        self.rep = rep
        self.sigs: dict[tuple[str, str], FuncSig] = {}
        self.expr_types: dict[int, Type] = {}
        self.narrowed_uses: set[int] = set()
        self.narrow_variant: dict[int, int] = {}
        self.isinstance_checks: dict[int, tuple[Type, Type]] = {}
        self.move_calls: set[int] = set()
        self.spawn_calls: dict[int, tuple[str, str]] = {}
        self.thread_calls: dict[int, dict] = {}
        self.fields_calls: dict[int, TClass] = {}
        self.field_helpers: dict[tuple[str, str, str], str] = {}
        self.field_helper_queue: list = []
        self.loop_iter_kind: dict[int, str] = {}
        self.facts: dict[tuple[str, str], FuncFacts] = {}
        self.constants: dict[tuple[str, str], Type] = {}
        self.classes: dict[tuple[str, str], ClassInfo] = {}
        self.enums: dict[tuple[str, str], EnumInfo] = {}
        self.enum_members: dict[int, tuple[str, str, str]] = {}  # expr id -> (mod, enum, member)
        self.enum_calls: dict[int, tuple[str, str]] = {}         # call id -> enum key
        self.init_ctors: dict[tuple[str, str], str] = {}   # class key -> factory function
        self.cls_bind: dict[tuple[str, str], TClass] = {}   # lifted classmethod key -> bound class
        self.cls_now: TClass | None = None
        self.inherited_statics: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
        self.class_bases: dict[tuple[str, str], tuple[str, str]] = {}  # subclass key -> base key
        self.protocols: dict[tuple[str, str], ProtoInfo] = {}
        self.tvar_bounds: dict[tuple[str, str], tuple[str, str]] = {}
        self.call_targets: dict[int, tuple[str, str]] = {}   # call node id -> sig key
        self.ctor_calls: dict[int, tuple[str, str, tuple]] = {}   # call node id -> class inst
        self.lambda_elems: dict[int, Type] = {}   # sorted-key lambda node id -> element type
        self.elem_borrow_binds: dict[int, tuple[str, str]] = {}  # stmt id -> (name, root)
        self.iter_binds: dict[int, tuple[str, str]] = {}         # stmt id -> (name, root)
        self.checked_bodies: set[tuple[str, str]] = set()
        self.user_exc: dict[str, str] = {}
        self.lambda_caps: dict[int, list[tuple[str, Type]]] = {}  # lambda id -> captures
        self.func_value_refs: dict[int, tuple[str, str]] = {}     # Name id -> function key
        self.op_calls: dict[int, ast.Call] = {}   # operator node id -> desugared dunder call
        self.for_lowered: dict[int, list] = {}    # For stmt id -> lowered stmts (user iterators)
        self.stmt_rewrites: dict[int, ast.stmt] = {}   # stmt id -> replacement (__setattr__ hook)
        self.for_lowered_names: dict[int, list[str]] = {}  # For stmt id -> names the lowering assigns
        self._for_counter = 0

    def run(self) -> None:
        """Check every module: classes and signatures first, then all bodies."""
        resolve_reexports(self.program.modules)
        expand_type_aliases(self.program.modules)
        self._collect_user_exceptions()
        for mod in self.program.modules.values():
            self._collect_enums(mod)
        for mod in self.program.modules.values():
            self._collect_classes(mod)
        self._flatten_inheritance()
        for mod in self.program.modules.values():
            self._collect_protocols(mod)
            self._resolve_tvar_bounds(mod)
        for mod in self.program.modules.values():
            self._collect_class_members(mod)
            self._desugar_inits(mod)
            self._collect_signatures(mod)
        self._check_class_cycles()
        for mod in self.program.modules.values():
            self._check_constants(mod)
        for mod in self.program.modules.values():
            for fn in mod.functions.values():
                sig = self.sigs[(mod.name, fn.name)]
                if sig.is_template:
                    continue
                self._check_function(mod, fn, sig)
            for cls in self.classes.values():
                if cls.module != mod.name or cls.typevars:
                    continue
                for m in cls.methods.values():
                    if m.is_template:
                        continue
                    if m.node.name == "__iter__":
                        continue
                    self._check_function(mod, m.node, m)
            if mod.entry_call and mod.entry_call not in mod.functions:
                self.rep.fatal("SE214", "type-mismatch",
                               f"entry guard calls unknown function '{mod.entry_call}'",
                               Span(str(mod.path), 1, 0))
        self._emit_field_helpers()

    def _need_field_helper(self, t: TClass, kind: str, mod: Module) -> str:
        """Reserve the (class, kind) helper and return a name callable inside `mod`."""
        suffix = "__" + "_".join(mangle_type(a) for a in t.args) if t.args else ""
        key = (t.module, t.name + suffix, kind)
        fname = self.field_helpers.get(key)
        if fname is None:
            fname = f"_serp_f{kind}_{t.name}{suffix}"
            self.field_helpers[key] = fname
            self.field_helper_queue.append((t, kind, fname))
        if t.module != mod.name:
            mod.imports.setdefault(fname, (t.module, fname))
        return fname

    def _emit_field_helpers(self) -> None:
        """Generate, sign and check every field-table helper the program asked for."""
        from .fieldsyn import FieldHelperGen
        gen = FieldHelperGen(self)
        made: list[tuple[Module, ast.FunctionDef]] = []
        while self.field_helper_queue:
            t, kind, fname = self.field_helper_queue.pop(0)
            mod = self.program.modules[t.module]
            cnode = self.classes[(t.module, t.name)].node
            if kind == "json":
                schema = self._field_schema(t, cnode)
            elif kind in ("hooks", "hook", "hookself", "hookget", "hookval", "hookinfo"):
                schema = self._hooks_schema(t, cnode)
            else:
                schema = {}
            src = gen.source(kind, t, fname, schema)
            fn = ast.parse(src).body[0]
            assert isinstance(fn, ast.FunctionDef)
            ast.fix_missing_locations(fn)
            mod.functions[fname] = fn
            made.append((mod, fn))
        for mod in {id(m): m for m, _ in made}.values():
            self._collect_signatures(mod)
        for mod, fn in made:
            self._check_function(mod, fn, self.sigs[(mod.name, fn.name)])

    def _type_names(self, mod: Module) -> dict[str, Type]:
        """The class/typevar names visible in a module's annotations."""
        names: dict[str, Type] = {}
        for cname in mod.classes:
            names[cname] = TClass(mod.name, cname)
        for ename in mod.enums:
            names[ename] = TEnum(mod.name, ename)
        for tv in mod.typevars:
            names[tv] = TVar(tv)
        for alias, (tmod, orig) in mod.imports.items():
            tm = self.program.modules.get(tmod)
            if tm is not None and orig in tm.classes:
                names[alias] = TClass(tmod, orig)
            elif tm is not None and orig in tm.enums:
                names[alias] = TEnum(tmod, orig)
            elif tm is not None and orig in tm.typevars:
                names[alias] = TVar(orig)
        return names

    def _collect_enums(self, mod: Module) -> None:
        """Register every enum class and its constant members."""
        for ename, enode in mod.enums.items():
            members = enum_members(enode)
            vt = INT if isinstance(members[0][1], int) else STR
            self.enums[(mod.name, ename)] = EnumInfo(
                mod.name, ename, enode, enode.bases[0].id, members, vt)

    def _resolve_enum(self, mod: Module, name: str) -> EnumInfo | None:
        """The EnumInfo a bare name refers to in this module, if any."""
        if (mod.name, name) in self.enums:
            return self.enums[(mod.name, name)]
        if name in mod.imports:
            return self.enums.get(mod.imports[name])
        return None

    def _collect_classes(self, mod: Module) -> None:
        """Register every class name so annotations across modules resolve."""
        for cname, cnode in mod.classes.items():
            self.classes[(mod.name, cname)] = ClassInfo(
                mod.name, cname, cnode, frozen=cname in mod.frozen_classes)

    def _flatten_inheritance(self) -> None:
        """Flatten single inheritance: copy base fields/methods into each subclass node."""
        done: set[tuple[str, str]] = set()
        stack: list[tuple[str, str]] = []

        def flatten(key: tuple[str, str]) -> None:
            if key in done:
                return
            mod = self.program.modules[key[0]]
            bname = mod.class_bases.get(key[1])
            if bname is None:
                done.add(key)
                return
            cnode = self.classes[key].node
            span = Span(str(mod.path), cnode.lineno, cnode.col_offset)
            if key in stack:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"inheritance cycle through class '{key[1]}'", span)
            if bname in mod.classes:
                bkey = (mod.name, bname)
            elif bname in mod.imports:
                bkey = mod.imports[bname]
            else:
                bkey = (mod.name, bname)
            if bkey not in self.classes:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"unknown base class '{bname}' — a class base must be "
                               f"another @dataclass class visible in this module", span)
            stack.append(key)
            flatten(bkey)
            stack.pop()
            bnode = self.classes[bkey].node
            if bnode.bases:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"cannot inherit from generic class '{bname}'", span)
            self._merge_base(bkey, key)
            self._inherit_statics(bkey, key)
            self._inherit_hooks(bkey, key)
            if self.classes[bkey].frozen:
                self.classes[key].frozen = True
            elif self.classes[key].frozen:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"frozen class '{key[1]}' cannot inherit from non-frozen "
                               f"class '{bname}' — CPython rejects the same pair", span)
            self.class_bases[key] = bkey
            done.add(key)

        for mname, mod in self.program.modules.items():
            for cname in mod.classes:
                flatten((mname, cname))

    def _inherit_statics(self, bkey: tuple[str, str], skey: tuple[str, str]) -> None:
        """Carry a base's statics into a subclass; classmethods are re-emitted bound to it."""
        bmod = self.program.modules[bkey[0]]
        smod = self.program.modules[skey[0]]
        own = smod.class_statics.get(skey[1], {})
        visible = dict(self.inherited_statics.get(bkey, {}))
        for name, fname in bmod.class_statics.get(bkey[1], {}).items():
            visible[name] = (bkey[0], fname)
        out = self.inherited_statics.setdefault(skey, {})
        for name, (fmod, fname) in visible.items():
            if name in own or name in out:
                continue
            src = self.program.modules[fmod]
            if fname not in src.cls_bound:
                out[name] = (fmod, fname)
                continue
            new = f"_static_{skey[1]}_{name}"
            fn = copy.deepcopy(src.functions[fname])
            fn.name = new
            smod.functions[new] = fn
            smod.cls_bound[new] = skey[1]
            self._import_free_names(src, smod, fn)
            out[name] = (smod.name, new)

    def _inherit_hooks(self, bkey: tuple[str, str], skey: tuple[str, str]) -> None:
        """Carry a base's validator hooks into a subclass, minus redefined methods."""
        bmod = self.program.modules[bkey[0]]
        smod = self.program.modules[skey[0]]
        base_hooks = bmod.class_hooks.get(bkey[1], [])
        if not base_hooks:
            return
        own = smod.class_hooks.get(skey[1], [])
        own_methods = {h["method"] for h in own}
        merged = [dict(h) for h in base_hooks if h["method"] not in own_methods] + own
        smod.class_hooks[skey[1]] = merged

    def _import_free_names(self, src: Module, dst: Module, fn: ast.FunctionDef) -> None:
        """Make the free names of a classmethod copied out of `src` resolve inside `dst`."""
        if src is dst:
            return
        dst.shim_imports |= src.shim_imports
        dst.imports_sys = dst.imports_sys or src.imports_sys
        local = {a.arg for a in fn.args.args} | {"cls", "Self"}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                name = node.value.id
            else:
                continue
            if name in local or name in dst.functions or name in dst.classes \
                    or name in dst.imports or name in dst.constants:
                continue
            if name in src.functions or name in src.classes or name in src.constants:
                dst.imports[name] = (src.name, name)
            elif name in src.imports:
                dst.imports[name] = src.imports[name]
            elif name in src.rtlib_imports:
                dst.rtlib_imports.setdefault(name, src.rtlib_imports[name])
            elif name in src.rtlib_consts:
                dst.rtlib_consts.setdefault(name, src.rtlib_consts[name])

    def inherits_from(self, key: tuple[str, str], base: tuple[str, str]) -> bool:
        """True when class `key` has `base` anywhere in its (flattened) base chain."""
        while key in self.class_bases:
            key = self.class_bases[key]
            if key == base:
                return True
        return False

    def _merge_base(self, bkey: tuple[str, str], skey: tuple[str, str]) -> None:
        """Copy non-overridden base fields/methods into the subclass ClassDef body."""

        def split_doc(body: list) -> tuple:
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                return body[0], body[1:]
            return None, list(body)

        bnode = self.classes[bkey].node
        snode = self.classes[skey].node
        sdoc, sbody = split_doc(snode.body)
        _, bbody = split_doc(bnode.body)
        sub_fields = {st.target.id: st for st in sbody
                      if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)}
        sub_defs = {st.name for st in sbody if isinstance(st, ast.FunctionDef)}
        sub_meta = {t.id for st in sbody if isinstance(st, ast.Assign)
                    for t in st.targets if isinstance(t, ast.Name)}
        merged_fields: list = []
        overriding: set[str] = set()
        for st in bbody:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                if st.target.id in sub_fields:
                    merged_fields.append(sub_fields[st.target.id])
                    overriding.add(st.target.id)
                else:
                    merged_fields.append(copy.deepcopy(st))
        inherited_defs: list = []
        for st in bbody:
            if isinstance(st, ast.Assign) and all(
                    isinstance(t, ast.Name) and t.id not in sub_meta for t in st.targets):
                inherited_defs.append(copy.deepcopy(st))
        for st in bbody:
            if isinstance(st, ast.FunctionDef) and st.name not in sub_defs:
                cp = copy.deepcopy(st)
                self._retarget_self(cp, bkey[1], skey[1])
                self._import_free_names(self.program.modules[bkey[0]],
                                        self.program.modules[skey[0]], cp)
                inherited_defs.append(cp)
        own_rest = [st for st in sbody
                    if not (isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
                            and st.target.id in overriding)]
        new_body = ([sdoc] if sdoc is not None else []) + merged_fields + own_rest + inherited_defs
        snode.body = new_body if new_body else [ast.Pass()]

    @staticmethod
    def _retarget_self(fn: ast.FunctionDef, base: str, sub: str) -> None:
        """Rewrite an inherited method's self annotation from the base class to the subclass."""
        if not (fn.args.args and fn.args.args[0].arg == "self"):
            return
        ann = fn.args.args[0].annotation
        if isinstance(ann, ast.Subscript) and isinstance(ann.slice, ast.Name) \
                and ann.slice.id == base:
            ann.slice.id = sub
        elif isinstance(ann, ast.Name) and ann.id == base:
            ann.id = sub

    def _collect_user_exceptions(self) -> None:
        """Merge + validate every module's exception classes (bases, collisions, cycles)."""
        self.user_exc = collect_user_exceptions(self.program)
        for mod in self.program.modules.values():
            for name, base in mod.exceptions.items():
                node = next((n for n in mod.tree.body
                             if isinstance(n, ast.ClassDef) and n.name == name), mod.tree)
                if name in BUILTIN_EXC:
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"exception class '{name}' shadows a built-in exception",
                                   self._span_of(mod, node))
                other = next((m.exceptions[name] for m in self.program.modules.values()
                              if m is not mod and name in m.exceptions), None)
                if other is not None and other != base:
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"exception class '{name}' is defined with conflicting "
                                   f"bases '{base}' and '{other}' in two modules",
                                   self._span_of(mod, node))
                if base not in BUILTIN_EXC and base not in self.user_exc:
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"exception base '{base}' of '{name}' is not a known "
                                   f"exception class", self._span_of(mod, node))
                if base in self.user_exc and name in exc_ancestors(base, self.user_exc):
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"exception class '{name}' inherits from itself",
                                   self._span_of(mod, node))

    def _span_of(self, mod: Module, node) -> Span:
        """Best-effort span for a module-level node."""
        return Span(str(mod.path), getattr(node, "lineno", 1),
                    getattr(node, "col_offset", 0))

    def _exc_ok(self, name: str) -> bool:
        """True when `name` is a raise/except-usable exception class in this module."""
        if name in BUILTIN_EXC:
            return True
        if name not in self.user_exc:
            return False
        if name in self.mod.exceptions:
            return True
        imp = self.mod.imports.get(name)
        if imp is not None:
            tmod, orig = imp
            src = self.program.modules.get(tmod)
            if orig == name and src is not None and name in src.exceptions:
                return True
        home = {m.name for m in self.program.modules.values() if name in m.exceptions}
        return any(tmod in home for tmod, _orig in self.mod.imports.values())

    def _collect_class_members(self, mod: Module) -> None:
        """Parse fields and method signatures of every class in a module."""
        file = str(mod.path)
        names = self._type_names(mod)
        for cname, cnode in mod.classes.items():
            info = self.classes[(mod.name, cname)]
            info.statics = dict(self.inherited_statics.get((mod.name, cname), {}))
            info.statics.update({n: (mod.name, f)
                                 for n, f in mod.class_statics.get(cname, {}).items()})
            for base in cnode.bases:
                assert isinstance(base, ast.Subscript)
                elts = base.slice.elts if isinstance(base.slice, ast.Tuple) else [base.slice]
                for e in elts:
                    if not (isinstance(e, ast.Name) and e.id in mod.typevars):
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "Generic[...] arguments must be module-level TypeVars",
                                       Span(file, base.lineno, base.col_offset))
                    info.typevars.append(e.id)
            body = cnode.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            for stmt in body:
                span = Span(file, stmt.lineno, stmt.col_offset)
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    parsed = parse_annotation(stmt.annotation, self.rep, file,
                                              allow_wrapper=False, names=names)
                    meta, dvalue = self._field_metadata(stmt, file)
                    if meta:
                        info.field_meta[stmt.target.id] = meta
                    if dvalue is not None:
                        if (isinstance(dvalue, ast.List) and not dvalue.elts
                                and isinstance(parsed.typ, TList)) \
                                or (isinstance(dvalue, ast.Dict) and not dvalue.keys
                                    and isinstance(parsed.typ, TDict)):
                            info.field_defaults[stmt.target.id] = dvalue
                        else:
                            self._check_default(stmt.target.id, parsed.typ, CONV_COPY,
                                                dvalue, file)
                            folded_default = self._default_const(dvalue)
                            assert folded_default is not None
                            info.field_defaults[stmt.target.id] = folded_default
                    elif info.field_defaults:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       f"field '{stmt.target.id}' without a default cannot "
                                       f"follow a defaulted field", span)
                    info.fields[stmt.target.id] = parsed.typ
                    info.field_order.append(stmt.target.id)
                    for t in self._walk(parsed.typ):
                        if isinstance(t, TVar) and t.name not in info.typevars:
                            self.rep.fatal(
                                "SE203", "missing-annotation",
                                f"field '{stmt.target.id}' uses type variable "
                                f"'{t.name}' — declare it: class {cname}(Generic[{t.name}])",
                                span)
                elif isinstance(stmt, ast.FunctionDef):
                    deco = stmt.decorator_list
                    is_property = (len(deco) == 1 and isinstance(deco[0], ast.Name)
                                   and deco[0].id == "property")
                    if deco and not is_property:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "method decorators are not Tier 1 (only @property, "
                                       "@staticmethod and @classmethod)", span)
                    if stmt.name.startswith("__") and stmt.name not in ALLOWED_DUNDERS:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       f"dunder method '{stmt.name}' is not supported "
                                       f"(supported: {', '.join(sorted(ALLOWED_DUNDERS))}; "
                                       f"dataclass generates __init__/__repr__/__eq__)", span)
                    sig = self._parse_method_sig(mod, info, stmt,
                                                 dict(names, Self=self._self_type(info)))
                    if is_property:
                        if len(sig.params) != 1 or sig.params[0].conv != CONV_REF:
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"@property '{stmt.name}' must take only "
                                           f"'self: Ref[{cname}]'", span)
                        info.properties.add(stmt.name)
                    if stmt.name == "__str__":
                        if len(sig.params) != 1 or sig.params[0].conv != CONV_REF \
                                or not isinstance(sig.ret, TStr):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__str__ must be (self: Ref[{cname}]) -> str", span)
                    if stmt.name == "__repr__":
                        if info.typevars:
                            self.rep.fatal("SE201", "unsupported-feature",
                                           "__repr__ is not supported on generic classes", span)
                        if len(sig.params) != 1 or sig.params[0].conv != CONV_REF \
                                or not isinstance(sig.ret, TStr):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__repr__ must be (self: Ref[{cname}]) -> str", span)
                    if stmt.name == "__post_init__":
                        if info.typevars:
                            self.rep.fatal("SE201", "unsupported-feature",
                                           "__post_init__ is not supported on generic classes",
                                           span)
                        if len(sig.params) != 1 or sig.params[0].conv != CONV_MUT \
                                or not isinstance(sig.ret, TNone):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__post_init__ must be (self: Mut[{cname}]) -> None",
                                           span)
                    if stmt.name == "__init__":
                        if len(sig.params) < 1 or sig.params[0].conv != CONV_MUT \
                                or not isinstance(sig.ret, TNone):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__init__ must be "
                                           f"(self: Mut[{cname}], ...) -> None", span)
                    if stmt.name == "__setattr__":
                        if len(sig.params) != 3 or sig.params[0].conv != CONV_MUT \
                                or not isinstance(sig.params[1].typ, TStr) \
                                or not isinstance(sig.params[2].typ, TPyVal) \
                                or not isinstance(sig.ret, TNone):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__setattr__ must be (self: Mut[{cname}], "
                                           f"name: str, value: PyVal) -> None", span)
                    if stmt.name in ("__enter__", "__aenter__"):
                        self._check_enter_shape(info, stmt, sig, span)
                    if stmt.name == "__iter__":
                        self._check_iter_shape(info, stmt, sig, span)
                    if stmt.name == "__next__":
                        if len(sig.params) != 1 or sig.params[0].conv != CONV_MUT \
                                or isinstance(sig.ret, TNone):
                            self.rep.fatal("SE201", "unsupported-feature",
                                           f"__next__ must be (self: Mut[{cname}]) -> T "
                                           f"where T is a non-None value type", span)
                    if stmt.name in ("__exit__", "__aexit__"):
                        self._check_exit_shape(cname, sig, span)
                    info.methods[stmt.name] = sig
                elif isinstance(stmt, ast.Pass):
                    continue
                elif isinstance(stmt, ast.Assign):
                    self._class_metadata(info, stmt, file)
                else:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   "class bodies may only contain annotated fields, methods "
                                   "and build-time metadata assignments",
                                   span)
            info.hooks = [dict(h) for h in mod.class_hooks.get(cname, [])]
            for oname, stubs in mod.class_overloads.get(cname, {}).items():
                if oname not in info.methods:
                    continue
                impl_key = (mod.name, f"{info.name}.{oname}")
                impl_sig = self.sigs.get(impl_key)
                parsed_stubs = [
                    self._parse_method_sig(mod, info, st, dict(names, Self=self._self_type(info)))
                    for st in stubs]
                if impl_sig is not None:
                    self.sigs[impl_key] = impl_sig
                info.overloads[oname] = parsed_stubs
            if not info.fields and not info.methods:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"class '{cname}' has no fields or methods",
                               Span(file, cnode.lineno, cnode.col_offset))

    def _desugar_inits(self, mod: Module) -> None:
        """Rewrite every user `__init__` into a module-level factory returning the class."""
        for cname in list(mod.classes):
            info = self.classes[(mod.name, cname)]
            sig = info.methods.get("__init__")
            if sig is None:
                continue
            file = str(mod.path)
            span = Span(file, sig.node.lineno, sig.node.col_offset)
            if info.typevars:
                self.rep.fatal("SE201", "unsupported-feature",
                               "__init__ is not supported on generic classes", span)
            if info.frozen:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"frozen class '{cname}' cannot define __init__ — a frozen "
                               f"instance cannot be assigned field by field", span)
            for other in ("__post_init__", "__setattr__"):
                if other in info.methods:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"class '{cname}' defines both __init__ and {other} — "
                                   f"{other} only runs for the generated constructor", span)
            if info.hooks:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"class '{cname}' defines __init__ and validator hooks — "
                               f"hooks only run for the generated constructor", span)
            fname = f"_serp_init_{cname}"
            mod.functions[fname] = self._init_factory(mod, info, sig, fname)
            self.init_ctors[(mod.name, cname)] = fname
            info.methods.pop("__init__")
            self.sigs.pop((mod.name, f"{cname}.__init__"), None)

    def _init_factory(self, mod: Module, info: ClassInfo, sig: FuncSig,
                      fname: str) -> ast.FunctionDef:
        """Build the factory function a user `__init__` lowers to (fields hoisted to locals)."""
        file = str(mod.path)
        node = copy.deepcopy(sig.node)
        anns = {s.target.id: s.annotation for s in info.node.body
                if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
        slots = {f: f"_serp_i_{f}" for f in info.field_order}
        assigned: list[str] = []
        body: list[ast.stmt] = []
        for stmt in node.body:
            field_name = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                field_name = _self_field(stmt.targets[0])
            elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) \
                    and _self_field(stmt.target) is not None:
                self.rep.fatal("SE201", "unsupported-feature",
                               "fields are initialized with a plain 'self.f = value' "
                               "inside __init__", Span(file, stmt.lineno, stmt.col_offset))
            rw = _SelfRewriter(info, slots, assigned, self.rep, file)
            if field_name is None:
                body.append(rw.visit(stmt))
                continue
            fspan = Span(file, stmt.lineno, stmt.col_offset)
            if field_name not in info.fields:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"'self.{field_name}' is not a field of '{info.name}' — "
                               f"__init__ may only assign declared fields", fspan)
            if field_name in assigned:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"field '{field_name}' is assigned twice in __init__ — "
                               f"every field is assigned exactly once", fspan)
            assert isinstance(stmt, ast.Assign)
            new = ast.AnnAssign(target=ast.Name(id=slots[field_name], ctx=ast.Store()),
                                annotation=copy.deepcopy(anns[field_name]),
                                value=rw.visit(stmt.value), simple=1)
            ast.copy_location(new, stmt)
            body.append(new)
            assigned.append(field_name)
        missing = [f for f in info.field_order if f not in assigned]
        if missing:
            self.rep.fatal("SE217", "uninitialized-field",
                           f"__init__ of '{info.name}' leaves field(s) "
                           f"{', '.join(missing)} unassigned — every field must be "
                           f"assigned exactly once, at the top level of the body",
                           Span(file, node.lineno, node.col_offset))
        args: list[ast.expr] = []
        for f in info.field_order:
            ref: ast.expr = ast.Name(id=slots[f], ctx=ast.Load())
            if not info.fields[f].is_copy():
                ref = ast.Call(func=ast.Name(id="move", ctx=ast.Load()), args=[ref],
                               keywords=[])
            args.append(ref)
        call = ast.Call(func=ast.Name(id=info.name, ctx=ast.Load()), args=args, keywords=[])
        call.serp_raw_ctor = True
        body.append(ast.Return(value=call))
        node.name = fname
        node.body = body
        node.args.args = node.args.args[1:]
        node.returns = ast.Name(id=info.name, ctx=ast.Load())
        node.decorator_list = []
        ast.fix_missing_locations(node)
        return node

    def _walk(self, t: Type):
        from .ptypes import walk_types
        return walk_types(t)

    def _class_ref(self, arg: ast.expr, narrow: dict[str, Type], call: ast.Call) -> TClass:
        """Resolve an intrinsic's first argument to a concrete class: a class name or a value."""
        if isinstance(arg, ast.Name) and arg.id in ("cls", "Self") \
                and self.cls_now is not None and arg.id not in self.env:
            self.expr_types[id(arg)] = self.cls_now
            return self.cls_now
        if isinstance(arg, ast.Name) and arg.id not in self.env and arg.id not in narrow:
            t = self._type_names(self.mod).get(arg.id)
            if isinstance(t, TClass) and (t.module, t.name) in self.classes:
                self.expr_types[id(arg)] = t
                return t
        if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name) \
                and arg.value.id not in self.env:
            base = self._type_names(self.mod).get(arg.value.id)
            if isinstance(base, TClass) and (base.module, base.name) in self.classes:
                t = parse_annotation(arg, self.rep, str(self.mod.path), allow_wrapper=False,
                                     names=self._type_names(self.mod)).typ
                if isinstance(t, TClass):
                    self.expr_types[id(arg)] = t
                    return t
        vt = self._type_expr(arg, narrow)
        if not isinstance(vt, TClass):
            self._err("SE214", "type-mismatch",
                      f"field-table intrinsics take a class name or a class-typed value, "
                      f"got {vt}", call)
            return TClass(self.mod.name, "?")
        return vt

    @staticmethod
    def _inst_ok(info: "ClassInfo", t: TClass) -> bool:
        """True when `t` names a fully concrete class: no free type variables left."""
        return len(t.args) == len(info.typevars) and not any(has_tvar(a) for a in t.args)

    def _inst_fields(self, t: TClass) -> dict[str, Type]:
        """A class's field types with its type arguments substituted in."""
        info = self.classes[(t.module, t.name)]
        if not info.typevars:
            return info.fields
        sub = dict(zip(info.typevars, t.args))
        return {k: subst_type(v, sub) for k, v in info.fields.items()}

    def _type_fields_intrinsic(self, node: ast.Call, name: str,
                               narrow: dict[str, Type]) -> Type:
        """Type fields_of / fields_json / fields_build / fields_set (docs/DECISIONS.md D17)."""
        want = {"fields_build": 2, "fields_set": 3}.get(name, 1)
        if len(node.args) != want or node.keywords:
            self._err("SE214", "type-mismatch",
                      f"{name}() takes exactly {want} positional argument(s)", node)
            return TPyVal() if name != "fields_json" else STR
        t = self._class_ref(node.args[0], narrow, node)
        info = self.classes.get((t.module, t.name))
        if info is None or not self._inst_ok(info, t):
            self._err("SE201", "unsupported-feature",
                      f"{name}() needs a concrete @dataclass class, got {t}", node)
            return STR if name == "fields_json" else t
        self.fields_calls[id(node)] = t
        self._field_schema(t, node)
        kind = {"fields_of": "dump", "fields_json": "json", "fields_build": "build",
                "fields_set": "set"}[name]
        if kind == "build":
            dt = self._type_expr(node.args[1], narrow, expect=TPyVal())
            if not isinstance(dt, TPyVal) and not self._pyval_coercible(dt):
                self._err("SE214", "type-mismatch",
                          f"fields_build() takes a PyVal or dict[str, PyVal], got {dt}", node)
            kept = [node.args[1]]
        elif kind == "set":
            if info.frozen:
                self._err("SE201", "unsupported-feature",
                          f"fields_set() cannot write to frozen class '{t.name}'", node)
            nt = self._type_expr(node.args[1], narrow, expect=STR)
            if not isinstance(nt, TStr):
                self._err("SE214", "type-mismatch",
                          f"fields_set() takes the field name as a str, got {nt}", node)
            vt = self._type_expr(node.args[2], narrow, expect=TPyVal())
            if not isinstance(vt, TPyVal) and not self._pyval_coercible(vt):
                self._err("SE214", "type-mismatch",
                          f"fields_set() takes a PyVal value, got {vt}", node)
            self._mut_borrow_place(node.args[0], node)
            kept = [node.args[0], node.args[1], node.args[2]]
        elif kind == "dump":
            kept = [node.args[0]]
        else:
            kept = []
        helper = self._need_field_helper(t, kind, self.mod)
        node.func = ast.copy_location(ast.Name(id=helper, ctx=ast.Load()), node.func)
        node.args = kept
        self.call_targets[id(node)] = (t.module, helper)
        return {"dump": TDict(STR, TPyVal()), "json": STR, "build": t, "set": NONE}[kind]

    def _type_hook_intrinsic(self, node: ast.Call, name: str,
                             narrow: dict[str, Type]) -> Type:
        """Type the hook intrinsics (docs/DECISIONS.md D18, D27)."""
        arity = {"hooks_json": 1, "run_hook": 3, "run_hook_self": 2,
                 "run_hook_get": 2, "run_hook_val": 3, "run_hook_info": 4}[name]
        kind = {"hooks_json": "hooks", "run_hook": "hook", "run_hook_self": "hookself",
                "run_hook_get": "hookget", "run_hook_val": "hookval",
                "run_hook_info": "hookinfo"}[name]
        ret = {"hooks": STR, "hook": TPyVal(), "hookself": TNone(), "hookget": TPyVal(),
               "hookval": TPyVal(), "hookinfo": TPyVal()}[kind]
        if len(node.args) != arity or node.keywords:
            self._err("SE214", "type-mismatch",
                      f"{name}() takes exactly {arity} positional argument(s)", node)
            return ret
        t = self._class_ref(node.args[0], narrow, node)
        info = self.classes.get((t.module, t.name))
        if info is None or not self._inst_ok(info, t):
            self._err("SE201", "unsupported-feature",
                      f"{name}() needs a concrete @dataclass class, got {t}", node)
            return ret
        self._hooks_schema(t, node)
        nt = STR if arity == 1 else self._type_expr(node.args[1], narrow, expect=STR)
        if arity > 1 and not isinstance(nt, TStr):
            self._err("SE214", "type-mismatch",
                      f"{name}() takes the hook name as a str, got {nt}", node)
        for extra in node.args[2:]:
            self._type_expr(extra, narrow, expect=TPyVal())
        if kind == "hooks":
            kept: list = []
        elif kind in ("hookself", "hookget"):
            kept = [node.args[0], node.args[1]]
        elif kind == "hookval":
            kept = [node.args[0], node.args[1], node.args[2]]
        elif kind == "hookinfo":
            kept = [node.args[1], node.args[2], node.args[3]]
        else:
            kept = [node.args[1], node.args[2]]
        helper = self._need_field_helper(t, kind, self.mod)
        node.func = ast.copy_location(ast.Name(id=helper, ctx=ast.Load()), node.func)
        node.args = kept
        self.call_targets[id(node)] = (t.module, helper)
        return ret

    def _meta_fn_refs(self, info: ClassInfo) -> list[str]:
        """Every function name referenced from a class's build-time metadata (LB14)."""
        out: list[str] = []

        def walk(v) -> None:
            if isinstance(v, FnRef):
                if v.name not in out:
                    out.append(v.name)
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)

        for meta in info.field_meta.values():
            walk(meta)
        walk(info.config)
        return out

    def _meta_funcs(self, t: TClass, info: ClassInfo, node: ast.AST) -> list[str]:
        """Check every metadata-referenced function's shape and return the callable ones."""
        mod = self.program.modules.get(t.module)
        funcs: list[str] = []
        for fn in self._meta_fn_refs(info):
            sig = self._resolve_callee(mod, fn) if mod is not None else None
            if sig is None:
                self._err("SE214", "type-mismatch",
                          f"build-time metadata of class '{t.name}' references '{fn}', "
                          f"which is not a function visible in module '{t.module}'", node)
                continue
            if len(sig.params) != 1 or not isinstance(sig.params[0].typ, TPyVal) \
                    or not isinstance(sig.ret, TPyVal):
                self._err("SE201", "unsupported-feature",
                          f"function '{fn}' referenced from '{t.name}' metadata must be "
                          f"(v: PyVal) -> PyVal", node)
                continue
            funcs.append(fn)
        return funcs

    def _hooks_schema(self, t: TClass, node: ast.AST) -> dict:
        """The build-time hook table of a class: validators, serializers, computed fields."""
        info = self.classes.get((t.module, t.name))
        if info is None:
            return {"class": t.name, "hooks": [], "funcs": []}
        hooks: list[dict] = []
        for h in info.hooks:
            method = h["method"]
            kind = h["kind"]
            deco = {"field": "@field_validator", "model": "@model_validator",
                    "serializer": "@field_serializer", "modelser": "@model_serializer",
                    "computed": "@computed_field"}[kind]
            if kind in ("field", "serializer"):
                missing = [f for f in h["fields"] if f not in info.fields]
                if missing:
                    self._err("SE214", "type-mismatch",
                              f"{deco} on '{method}' names unknown field(s) "
                              f"{', '.join(missing)} of class '{t.name}'", node)
                    continue
            args = 1
            ret_schema: dict | None = None
            if kind in ("modelser", "computed", "serializer") \
                    or (kind == "model" and h["mode"] == "after"):
                sig = info.methods.get(method)
                if sig is None:
                    self._err("SE201", "unsupported-feature",
                              f"{deco} '{method}' must be an instance method "
                              f"of '{t.name}'", node)
                    continue
                want = 2 if kind == "serializer" else 1
                ok = len(sig.params) == want and sig.params[0].conv == CONV_REF
                if ok and kind == "serializer":
                    ok = isinstance(sig.params[1].typ, TPyVal)
                if ok:
                    ok = isinstance(sig.ret, TNone) if kind == "model" \
                        else self._pyval_coercible(sig.ret) and not isinstance(sig.ret, TNone)
                if not ok:
                    shape = {"model": f"(self: Ref[{t.name}]) -> None",
                             "modelser": f"(self: Ref[{t.name}]) -> PyVal",
                             "computed": f"(self: Ref[{t.name}]) -> T (a PyVal-coercible T)",
                             "serializer": f"(self: Ref[{t.name}], v: PyVal) -> PyVal"}[kind]
                    self._err("SE201", "unsupported-feature",
                              f"{deco} '{method}' must be {shape}", node)
                    continue
                if kind == "computed":
                    ret_schema = self.field_type_schema(sig.ret, node)
            else:
                static = info.statics.get(method)
                sig = self.sigs.get(static) if static is not None else None
                if sig is None:
                    self._err("SE201", "unsupported-feature",
                              f"{deco} '{method}' of '{t.name}' must be a "
                              f"@classmethod (or @staticmethod)", node)
                    continue
                args = len(sig.params)
                if args not in (1, 2) or not all(isinstance(p.typ, TPyVal) for p in sig.params) \
                        or not isinstance(sig.ret, TPyVal):
                    self._err("SE201", "unsupported-feature",
                              f"{deco} '{method}' must be (cls, v: PyVal) -> PyVal "
                              f"or (cls, v: PyVal, info: PyVal) -> PyVal", node)
                    continue
            rec = {"kind": kind, "mode": h["mode"], "args": args,
                   "fields": list(h["fields"]), "method": method}
            if ret_schema is not None:
                rec["ret"] = ret_schema
            hooks.append(rec)
        return {"class": t.name, "hooks": hooks, "funcs": self._meta_funcs(t, info, node)}

    def field_type_schema(self, t: Type, node: ast.AST, seen: tuple = ()) -> dict:
        """Describe one field type as build-time JSON-able data (see fields_json())."""
        simple = {TInt: "int", TFloat: "float", TBool: "bool", TStr: "str",
                  TBytes: "bytes", TPyVal: "PyVal", TNone: "none"}
        for cls, tag in simple.items():
            if isinstance(t, cls):
                return {"k": tag}
        if isinstance(t, TOptional):
            return {"k": "optional", "inner": self.field_type_schema(t.inner, node, seen)}
        if isinstance(t, TList):
            return {"k": "list", "elem": self.field_type_schema(t.elem, node, seen)}
        if isinstance(t, TSet):
            return {"k": "set", "elem": self.field_type_schema(t.elem, node, seen)}
        if isinstance(t, TUnion):
            models = [m for m in t.members if isinstance(m, TClass)]
            if len(models) > 1 and self.union_discriminator(t) is None:
                names = ", ".join(m.name for m in models)
                self._err("SE201", "unsupported-feature",
                          f"a union field with more than one model member ({names}) cannot "
                          f"be validated: every model arrives as a JSON object, so the member "
                          f"is ambiguous — give every member a shared discriminator field "
                          f"with a distinct constant default (e.g. `kind: str = \"cat\"`)",
                          node)
            return {"k": "union",
                    "members": [self.field_type_schema(m, node, seen) for m in t.members]}
        if isinstance(t, TEnum):
            info = self.enums[(t.module, t.name)]
            return {"k": "enum", "class": t.name,
                    "base": "int" if isinstance(info.value_type, TInt) else "str",
                    "members": [n for n, _v in info.members],
                    "values": [v for _n, v in info.members]}
        if isinstance(t, TDict):
            if not isinstance(t.key, TStr):
                self._err("SE201", "unsupported-feature",
                          f"the field-table intrinsics only read dict fields with str keys, "
                          f"got {t}", node)
            return {"k": "dict", "key": {"k": "str"},
                    "value": self.field_type_schema(t.value, node, seen)}
        if isinstance(t, TTuple):
            return {"k": "tuple",
                    "items": [self.field_type_schema(i, node, seen) for i in t.items]}
        if isinstance(t, TClass):
            key = (t.module, t.name)
            if key in seen:
                return {"k": "model", "class": t.name, "cycle": True, "fields": []}
            return self._field_schema(t, node, seen + (key,))
        self._err("SE201", "unsupported-feature",
                  f"field type {t} is not readable by the field-table intrinsics", node)
        return {"k": "PyVal"}

    def _field_schema(self, t: TClass, node: ast.AST, seen: tuple = ()) -> dict:
        """The full build-time field table of a class (recursing into class-typed fields)."""
        from .fieldsyn import json_safe
        info = self.classes.get((t.module, t.name))
        if info is None:
            self._err("SE201", "unsupported-feature", f"unknown class {t}", node)
            return {"k": "model", "class": t.name, "fields": []}
        if not seen:
            seen = ((t.module, t.name),)
        ftypes = self._inst_fields(t)
        fields = []
        for fname in info.field_order:
            entry: dict = {"name": fname,
                           "type": self.field_type_schema(ftypes[fname], node, seen)}
            d = info.field_defaults.get(fname)
            if d is not None:
                entry["has_default"] = True
                if isinstance(d, ast.List):
                    entry["default"] = []
                elif isinstance(d, ast.Dict):
                    entry["default"] = {}
                elif isinstance(d.value, bytes):
                    entry["default_hex"] = d.value.hex()
                elif isinstance(d.value, float) and (d.value != d.value
                                                     or d.value in (float("inf"),
                                                                    float("-inf"))):
                    entry["default_special"] = "nan" if d.value != d.value else \
                        ("inf" if d.value > 0 else "-inf")
                else:
                    entry["default"] = d.value
            else:
                entry["has_default"] = False
            meta = info.field_meta.get(fname)
            if meta:
                entry["meta"] = {k: json_safe(v) for k, v in meta.items()
                                 if k not in ("default", "default_factory")}
            fields.append(entry)
        return {"k": "model", "class": t.name, "fields": fields,
                "config": {k: json_safe(v) for k, v in info.config.items()}}

    def _meta_literal(self, node: ast.expr):
        """Fold one metadata argument into a plain Python value, or _NOMETA."""
        if isinstance(node, ast.Name) and node.id in ("list", "dict"):
            return [] if node.id == "list" else {}
        if isinstance(node, ast.Name):
            return FnRef(node.id)
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError):
            return _NOMETA

    def _class_metadata(self, info: ClassInfo, stmt: ast.Assign, file: str) -> None:
        """Fold a class-body assignment (`model_config = ConfigDict(...)`) into build-time data."""
        span = Span(file, stmt.lineno, stmt.col_offset)
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            self.rep.fatal("SE201", "unsupported-feature",
                           "a class-body assignment must bind exactly one name", span)
        name = stmt.targets[0].id
        value = stmt.value
        if isinstance(value, ast.Call):
            if not (isinstance(value.func, ast.Name) and value.func.id in CONFIG_CALLS):
                self.rep.fatal("SE201", "unsupported-feature",
                               f"class-body assignment '{name}' must be a literal or a "
                               f"{'/'.join(sorted(CONFIG_CALLS))}(...) call read at build time",
                               span)
            if value.args:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"{value.func.id}() takes keyword arguments only", span)
            folded: dict = {}
            for kw in value.keywords:
                if kw.arg is None:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{value.func.id}() cannot be **unpacked", span)
                val = self._meta_literal(kw.value)
                if val is _NOMETA:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{value.func.id}({kw.arg}=...) must be a literal — it is "
                                   f"read at build time", span)
                folded[kw.arg] = val
            info.config[name] = folded
            return
        lit = self._meta_literal(value)
        if lit is _NOMETA:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"class-body assignment '{name}' must be a literal or a "
                           f"{'/'.join(sorted(CONFIG_CALLS))}(...) call read at build time", span)
        info.config[name] = lit

    def _field_metadata(self, stmt: ast.AnnAssign, file: str) -> tuple[dict, ast.expr | None]:
        """Split a field declaration into build-time metadata and its real default value.

        `Annotated[T, Field(...)]` extras and a `Field(...)`/`field(...)` call standing
        in the default position both contribute keyword metadata; `default=` and
        `default_factory=` inside them become the field's actual default.
        """
        span = Span(file, stmt.lineno, stmt.col_offset)
        extras: list[ast.expr] = []
        ann = stmt.annotation
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                and ann.value.id == "Annotated":
            elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
            extras.extend(elts[1:])
        default: ast.expr | None = stmt.value
        if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) \
                and default.func.id in META_CALLS:
            extras.append(default)
            default = None
        meta: dict = {}
        for ex in extras:
            if not (isinstance(ex, ast.Call) and isinstance(ex.func, ast.Name)):
                continue
            if ex.func.id not in META_CALLS:
                if ex.keywords:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{ex.func.id}(...) metadata takes positional arguments "
                                   f"only — it is read at build time", span)
                folded_args = []
                for a in ex.args:
                    av = self._meta_literal(a)
                    if av is _NOMETA:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       f"{ex.func.id}(...) metadata arguments must be "
                                       f"literals or function names", span)
                    folded_args.append(av)
                meta.setdefault("annotated", []).append(
                    {"call": ex.func.id, "args": folded_args})
                continue
            if len(ex.args) > 1:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"{ex.func.id}() metadata takes at most one positional "
                               f"argument (the default)", span)
            if ex.args:
                pv = self._meta_literal(ex.args[0])
                if pv is _NOMETA:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{ex.func.id}() positional default must be a literal "
                                   f"— it is read at build time", span)
                meta["default"] = pv
            for kw in ex.keywords:
                if kw.arg is None:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{ex.func.id}() metadata cannot be **unpacked", span)
                val = self._meta_literal(kw.value)
                if val is _NOMETA:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   f"{ex.func.id}({kw.arg}=...) metadata must be a literal "
                                   f"— it is read at build time", span)
                meta[kw.arg] = val
        if default is None and "default_factory" in meta:
            fac = meta["default_factory"]
            if isinstance(fac, list):
                default = ast.copy_location(ast.List(elts=[], ctx=ast.Load()), stmt)
            elif isinstance(fac, dict):
                default = ast.copy_location(ast.Dict(keys=[], values=[]), stmt)
            else:
                self.rep.fatal("SE201", "unsupported-feature",
                               "default_factory must be `list` or `dict` — arbitrary "
                               "factories are not build-time values", span)
        if default is None and "default" in meta:
            dv = meta["default"]
            if isinstance(dv, list) and not dv:
                default = ast.copy_location(ast.List(elts=[], ctx=ast.Load()), stmt)
            elif isinstance(dv, dict) and not dv:
                default = ast.copy_location(ast.Dict(keys=[], values=[]), stmt)
            elif isinstance(dv, (bool, int, float, str, bytes)) or dv is None:
                default = ast.copy_location(ast.Constant(value=dv), stmt)
            else:
                self.rep.fatal("SE201", "unsupported-feature",
                               "Field(default=...) must be a scalar constant or an empty "
                               "list/dict", span)
        if default is not None:
            ast.fix_missing_locations(default)
        return meta, default

    def _self_type(self, info: ClassInfo) -> TClass:
        return TClass(info.module, info.name,
                      tuple(TVar(tv) for tv in info.typevars))

    def _check_enter_shape(self, info: ClassInfo, stmt: ast.FunctionDef,
                           sig: FuncSig, span: Span) -> None:
        """Enforce that __enter__ returns the class and ends with `return self` (side effects allowed)."""
        ok = (len(sig.params) == 1 and sig.params[0].conv == CONV_REF
              and sig.ret == self._self_type(info))
        body = stmt.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        ok = ok and len(body) >= 1 and isinstance(body[-1], ast.Return) \
            and isinstance(body[-1].value, ast.Name) and body[-1].value.id == "self" \
            and not any(isinstance(s, ast.Return) for s in body[:-1])
        if not ok:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"__enter__ must be 'def __enter__(self: "
                           f"Ref[{info.name}]) -> {info.name}' ending in 'return self' — the with "
                           f"protocol binds the object itself", span)

    def _check_iter_shape(self, info: ClassInfo, stmt: ast.FunctionDef,
                          sig: FuncSig, span: Span) -> None:
        """Enforce that __iter__ is exactly `return self` returning the class."""
        ok = (len(sig.params) == 1 and sig.params[0].conv == CONV_REF
              and sig.ret == self._self_type(info))
        body = stmt.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        ok = ok and len(body) == 1 and isinstance(body[0], ast.Return) \
            and isinstance(body[0].value, ast.Name) and body[0].value.id == "self"
        if not ok:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"__iter__ must be exactly 'def __iter__(self: "
                           f"Ref[{info.name}]) -> {info.name}: return self' — iterators "
                           f"are their own iterables", span)

    def _check_exit_shape(self, cname: str, sig: FuncSig, span: Span) -> None:
        """Enforce __exit__(self, exc_type: None, exc: None, tb: None) -> None."""
        ok = (len(sig.params) == 4
              and sig.params[0].conv in (CONV_REF, CONV_MUT)
              and all(isinstance(p.typ, TNone) for p in sig.params[1:])
              and isinstance(sig.ret, TNone))
        if not ok:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"__exit__ must be (self: Ref[{cname}]|Mut[{cname}], "
                           f"exc_type: None, exc: None, tb: None) -> None (exception "
                           f"details are not passed natively)", span)

    def _parse_method_sig(self, mod: Module, info: ClassInfo, fn: ast.FunctionDef,
                          names: dict[str, Type]) -> FuncSig:
        """Parse a method signature; self must be annotated Ref[C] or Mut[C]."""
        file = str(mod.path)
        a = fn.args
        span = Span(file, fn.lineno, fn.col_offset)
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.kw_defaults:
            self.rep.fatal("SE201", "unsupported-feature",
                           "methods take plain positional parameters", span)
        if not a.args or a.args[0].arg != "self":
            self.rep.fatal("SE203", "missing-annotation",
                           f"method '{fn.name}' must take 'self' as its first parameter", span)
        self_arg = a.args[0]
        if self_arg.annotation is None:
            self.rep.fatal("SE203", "missing-annotation",
                           f"'self' of method '{fn.name}' needs a convention annotation — "
                           f"write 'self: Ref[{info.name}]' or 'self: Mut[{info.name}]'",
                           Span(file, self_arg.lineno, self_arg.col_offset))
        parsed = parse_annotation(self_arg.annotation, self.rep, file,
                                  allow_wrapper=True, names=names)
        if parsed.conv not in (CONV_REF, CONV_MUT, CONV_OWNED) or not isinstance(parsed.typ, TClass) \
                or parsed.typ.name != info.name or parsed.typ.module != info.module:
            self.rep.fatal("SE202", "invalid-wrapper-position",
                           f"'self' of method '{fn.name}' must be Ref[{info.name}], "
                           f"Mut[{info.name}], or Owned[{info.name}] (consuming)",
                           Span(file, self_arg.lineno, self_arg.col_offset))
        params = [Param("self", parsed.conv, self._self_type(info))]
        defaults_off = len(a.args) - len(a.defaults)
        for i, arg in enumerate(a.args[1:], start=1):
            if arg.annotation is None:
                self.rep.fatal("SE203", "missing-annotation",
                               f"parameter '{arg.arg}' has no type annotation",
                               Span(file, arg.lineno, arg.col_offset))
            p = parse_annotation(arg.annotation, self.rep, file, allow_wrapper=True, names=names)
            conv = p.conv
            if conv is None:
                if p.typ.is_copy() and not has_tvar(p.typ):
                    conv = CONV_COPY
                elif has_tvar(p.typ):
                    conv = CONV_OWNED if isinstance(p.typ, TVar) else CONV_OWNED
                else:
                    self.rep.fatal("SE203", "missing-annotation",
                                   f"non-Copy parameter '{arg.arg}' must state a convention "
                                   f"(Owned/Ref/Mut)", Span(file, arg.lineno, arg.col_offset))
            default = a.defaults[i - defaults_off] if i >= defaults_off else None
            if default is not None:
                self._check_default(arg.arg, p.typ, conv, default, file)
                default = self._default_const(default) or default
            params.append(Param(arg.arg, conv, p.typ, default))
        if fn.returns is None:
            self.rep.fatal("SE203", "missing-annotation",
                           f"method '{fn.name}' has no return annotation", span)
        if isinstance(fn.returns, ast.Subscript) and isinstance(fn.returns.value, ast.Name) \
                and fn.returns.value.id in ("Ref", "Mut"):
            self.rep.fatal("SE209", "returned-borrow",
                           "borrows cannot be returned — return values are owned",
                           Span(file, fn.returns.lineno, fn.returns.col_offset))
        ret = parse_annotation(fn.returns, self.rep, file, allow_wrapper=False, names=names).typ
        template = bool(info.typevars) or any(has_tvar(p.typ) for p in params) or has_tvar(ret)
        sig = FuncSig(mod.name, f"{info.name}.{fn.name}", params, ret, fn,
                      is_template=template, cls=info.name)
        self.sigs[(mod.name, sig.name)] = sig
        return sig

    def _collect_protocols(self, mod: Module) -> None:
        """Parse every Tier-2 protocol class: method signatures with no bodies."""
        file = str(mod.path)
        names = self._type_names(mod)
        for pname, pnode in mod.protocols.items():
            names_p = dict(names)
            names_p[pname] = TClass(mod.name, pname)
            info = ProtoInfo(mod.name, pname)
            body = pnode.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            for stmt in body:
                span = Span(file, stmt.lineno, stmt.col_offset)
                if isinstance(stmt, ast.Pass):
                    continue
                if not isinstance(stmt, ast.FunctionDef):
                    self.rep.fatal("SE201", "unsupported-feature",
                                   "protocol bodies may only contain method signatures", span)
                for b in stmt.body:
                    if not (isinstance(b, ast.Pass) or
                            (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))):
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "protocol methods have no body — write '...'",
                                       Span(file, b.lineno, b.col_offset))
                a = stmt.args
                if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults \
                        or a.kw_defaults:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   "protocol methods take plain positional parameters", span)
                if not a.args or a.args[0].arg != "self" or a.args[0].annotation is None:
                    self.rep.fatal("SE203", "missing-annotation",
                                   f"protocol method '{stmt.name}' needs an annotated 'self' "
                                   f"(Ref[{pname}] or Mut[{pname}])", span)
                parsed = parse_annotation(a.args[0].annotation, self.rep, file,
                                          allow_wrapper=True, names=names_p)
                if parsed.conv not in (CONV_REF, CONV_MUT) \
                        or parsed.typ != TClass(mod.name, pname):
                    self.rep.fatal("SE202", "invalid-wrapper-position",
                                   f"'self' of protocol method '{stmt.name}' must be "
                                   f"Ref[{pname}] or Mut[{pname}]", span)
                params = [Param("self", parsed.conv, parsed.typ)]
                for arg in a.args[1:]:
                    if arg.annotation is None:
                        self.rep.fatal("SE203", "missing-annotation",
                                       f"parameter '{arg.arg}' has no type annotation",
                                       Span(file, arg.lineno, arg.col_offset))
                    p = parse_annotation(arg.annotation, self.rep, file, allow_wrapper=True,
                                         names=names)
                    conv = p.conv
                    if conv is None:
                        if p.typ.is_copy():
                            conv = CONV_COPY
                        else:
                            self.rep.fatal("SE203", "missing-annotation",
                                           f"non-Copy protocol parameter '{arg.arg}' must "
                                           f"state a convention (Owned/Ref/Mut)",
                                           Span(file, arg.lineno, arg.col_offset))
                    params.append(Param(arg.arg, conv, p.typ))
                if stmt.returns is None:
                    self.rep.fatal("SE203", "missing-annotation",
                                   f"protocol method '{stmt.name}' has no return annotation",
                                   span)
                ret = parse_annotation(stmt.returns, self.rep, file, allow_wrapper=False,
                                       names=names).typ
                info.methods[stmt.name] = (params, ret)
            if not info.methods:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"protocol '{pname}' declares no methods",
                               Span(file, pnode.lineno, pnode.col_offset))
            self.protocols[(mod.name, pname)] = info

    def _resolve_tvar_bounds(self, mod: Module) -> None:
        """Resolve every `TypeVar(..., bound=P)` to a collected protocol."""
        for tv, bname in mod.typevar_bounds.items():
            if bname in mod.protocols:
                self.tvar_bounds[(mod.name, tv)] = (mod.name, bname)
                continue
            if bname in mod.imports:
                tmod, orig = mod.imports[bname]
                if (tmod, orig) in self.protocols or orig in \
                        self.program.modules.get(tmod, mod).protocols:
                    self.tvar_bounds[(mod.name, tv)] = (tmod, orig)
                    continue
            self.rep.fatal("SE201", "unsupported-feature",
                           f"TypeVar '{tv}' bound '{bname}' must name a Protocol class",
                           Span(str(mod.path), 1, 0))

    def _check_bounds(self, module: str, sub: dict, node: ast.AST) -> None:
        """Enforce protocol bounds on every inferred type argument."""
        for tv, concrete in sub.items():
            pkey = self.tvar_bounds.get((module, tv))
            if pkey is not None:
                self._check_protocol(concrete, pkey, tv, node)

    def _check_protocol(self, concrete: Type, pkey: tuple[str, str], tvname: str,
                        node: ast.AST) -> None:
        """Structurally check that a concrete class satisfies a protocol bound."""
        pname = pkey[1]
        proto = self.protocols[pkey]
        label = f"protocol '{pname}' (bound of {tvname})"
        if not isinstance(concrete, TClass):
            self._err("SE215", "unsatisfied-protocol",
                      f"{concrete} does not satisfy {label} — only classes can "
                      f"implement protocols", node)
            raise AssertionError
        info = self.classes.get((concrete.module, concrete.name))
        assert info is not None
        sub2 = dict(zip(info.typevars, concrete.args))
        for mname, (pparams, pret) in proto.methods.items():
            m = info.methods.get(mname)
            if m is None:
                self._err("SE215", "unsatisfied-protocol",
                          f"{concrete} is missing method '{mname}' required by {label}",
                          node)
                raise AssertionError
            mparams = [Param(p.name, p.conv, subst_type(p.typ, sub2)) for p in m.params]
            if len(mparams) != len(pparams):
                self._err("SE215", "unsatisfied-protocol",
                          f"{concrete}.{mname}() takes {len(mparams) - 1} parameter(s) but "
                          f"{label} requires {len(pparams) - 1}", node)
            if mparams[0].conv != pparams[0].conv:
                self._err("SE215", "unsatisfied-protocol",
                          f"{concrete}.{mname}() takes self by "
                          f"{mparams[0].conv} but {label} requires {pparams[0].conv}", node)
            for pp, mp in zip(pparams[1:], mparams[1:]):
                if pp.conv != mp.conv or pp.typ != mp.typ:
                    self._err("SE215", "unsatisfied-protocol",
                              f"{concrete}.{mname}() parameter '{mp.name}' is "
                              f"{mp.conv}[{mp.typ}] but {label} requires "
                              f"{pp.conv}[{pp.typ}]", node)
            mret = subst_type(m.ret, sub2)
            if mret != pret:
                self._err("SE215", "unsatisfied-protocol",
                          f"{concrete}.{mname}() returns {mret} but {label} requires "
                          f"{pret}", node)

    def _check_class_cycles(self) -> None:
        """Reject classes that contain themselves by value (infinite size)."""
        def by_value_deps(t: Type):
            if isinstance(t, TClass):
                yield (t.module, t.name)
            elif isinstance(t, TTuple):
                for i in t.items:
                    yield from by_value_deps(i)
            elif isinstance(t, TOptional):
                yield from by_value_deps(t.inner)
            elif isinstance(t, TUnion):
                for m in t.members:
                    yield from by_value_deps(m)

        for key, info in self.classes.items():
            seen: set = set()
            stack = [key]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                cinfo = self.classes.get(cur)
                if cinfo is None:
                    continue
                for ft in cinfo.fields.values():
                    for dep in by_value_deps(ft):
                        if dep == key:
                            self.rep.fatal(
                                "SE214", "type-mismatch",
                                f"class '{info.name}' contains itself by value — break the "
                                f"cycle with Shared[{info.name}], Weak[{info.name}], or a list",
                                Span(str(self.program.modules[info.module].path),
                                     info.node.lineno, info.node.col_offset))
                        stack.append(dep)

    def _span(self, mod: Module, node: ast.AST) -> Span:
        return Span(str(mod.path), node.lineno, node.col_offset,
                    getattr(node, "end_col_offset", None))

    def _default_const(self, default: ast.expr) -> ast.Constant | None:
        """Fold a literal default (including negated numbers) to a Constant node."""
        if isinstance(default, ast.Constant):
            return default
        if (isinstance(default, ast.UnaryOp) and isinstance(default.op, ast.USub)
                and isinstance(default.operand, ast.Constant)
                and isinstance(default.operand.value, (int, float))
                and not isinstance(default.operand.value, bool)):
            c = ast.Constant(value=-default.operand.value)
            ast.copy_location(c, default)
            return c
        return None

    def _check_default(self, pname: str, typ: Type, conv: str, default: ast.expr,
                       file: str) -> None:
        """Validate a Tier-2 default parameter value: literal, type-compatible."""
        span = Span(file, default.lineno, default.col_offset)
        empty_list = isinstance(default, ast.List) and not default.elts
        empty_dict = isinstance(default, ast.Dict) and not default.keys
        if empty_list or empty_dict:
            want = TList if empty_list else TDict
            if not isinstance(typ, want) or conv in (CONV_REF, CONV_MUT):
                self.rep.fatal("SE214", "type-mismatch",
                               f"default value of '{pname}' is an empty "
                               f"{'list' if empty_list else 'dict'}, expected {typ} "
                               f"(borrowed parameters cannot take defaults)", span)
            return
        folded = self._default_const(default)
        if folded is None:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"default value of '{pname}' must be a literal constant "
                           f"(mutable or computed defaults are not Tier 2)", span)
        if has_tvar(typ):
            self.rep.fatal("SE201", "unsupported-feature",
                           f"generic parameter '{pname}' cannot take a default value", span)
        v = folded.value
        vt: Type
        if isinstance(v, bool):
            vt = BOOL
        elif isinstance(v, int):
            vt = INT
        elif isinstance(v, float):
            vt = FLOAT
        elif isinstance(v, str):
            vt = STR
        elif v is None:
            vt = NONE
        elif isinstance(v, bytes):
            vt = TBytes()
        else:
            self.rep.fatal("SE201", "unsupported-feature",
                           f"default value of '{pname}' must be an int/float/bool/str/bytes/"
                           f"None literal", span)
            raise AssertionError
        if not self._assignable(vt, typ) and not (isinstance(typ, TFloat) and isinstance(vt, TInt)):
            self.rep.fatal("SE214", "type-mismatch",
                           f"default value of '{pname}' is {vt}, expected {typ}", span)
        if conv in (CONV_REF, CONV_MUT):
            self.rep.fatal("SE202", "invalid-wrapper-position",
                           f"borrowed parameter '{pname}' cannot take a default value", span)

    def _collect_signatures(self, mod: Module) -> None:
        """Parse and validate every function signature in a module."""
        file = str(mod.path)
        names = self._type_names(mod)
        for fn in mod.functions.values():
            if (mod.name, fn.name) in self.sigs:
                continue
            bound = mod.cls_bound.get(fn.name)
            if bound is not None:
                bt = names.get(bound)
                if not isinstance(bt, TClass):
                    bt = TClass(mod.name, bound)
                binfo = self.classes.get((bt.module, bt.name))
                if binfo is not None and binfo.typevars and not bt.args:
                    bt = TClass(bt.module, bt.name,
                                tuple(TVar(tv) for tv in binfo.typevars))
                self.cls_bind[(mod.name, fn.name)] = bt
                names = dict(names)
                names["Self"] = bt
                names["cls"] = bt
            elif "Self" in names:
                names = self._type_names(mod)
            a = fn.args
            if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg:
                if a.vararg:
                    hint = "replace `*args` with a list parameter, e.g. `def f(xs: list[int])`"
                elif a.kwarg:
                    hint = ("replace `**kwargs` with explicit keyword parameters that have "
                            "defaults, e.g. `def f(x: int, verbose: bool = False)`")
                else:
                    hint = "drop the `*` / `/` markers; callers may still pass these by keyword"
                self.rep.fatal("SE201", "unsupported-feature",
                               "only plain positional parameters (with optional defaults) are "
                               "supported", self._span(mod, fn), help=hint)
            defaults_off = len(a.args) - len(a.defaults)
            params = []
            for i, arg in enumerate(a.args):
                if arg.annotation is None:
                    self.rep.fatal("SE203", "missing-annotation",
                                   f"parameter '{arg.arg}' has no type annotation",
                                   Span(file, arg.lineno, arg.col_offset))
                parsed = parse_annotation(arg.annotation, self.rep, file, allow_wrapper=True,
                                          names=names)
                conv = parsed.conv
                if conv is None:
                    if has_tvar(parsed.typ):
                        conv = CONV_OWNED
                    elif parsed.typ.is_copy():
                        conv = CONV_COPY
                    else:
                        self.rep.fatal("SE203", "missing-annotation",
                                       f"non-Copy parameter '{arg.arg}' must state a convention "
                                       f"(Owned/Ref/Mut)", Span(file, arg.lineno, arg.col_offset))
                default = a.defaults[i - defaults_off] if i >= defaults_off else None
                if default is not None:
                    self._check_default(arg.arg, parsed.typ, conv, default, file)
                    default = self._default_const(default) or default
                params.append(Param(arg.arg, conv, parsed.typ, default))
            if fn.returns is None:
                self.rep.fatal("SE203", "missing-annotation",
                               f"function '{fn.name}' has no return annotation", self._span(mod, fn))
            r = fn.returns
            if isinstance(r, ast.Subscript) and isinstance(r.value, ast.Name):
                if r.value.id in ("Ref", "Mut"):
                    self.rep.fatal("SE209", "returned-borrow",
                                   "borrows cannot be returned in Tier 0 — return values are owned",
                                   Span(file, r.lineno, r.col_offset))
            ret = parse_annotation(r, self.rep, file, allow_wrapper=False, names=names).typ
            template = any(has_tvar(p.typ) for p in params) or has_tvar(ret)
            cls_bt = self.cls_bind.get((mod.name, fn.name)) if bound is not None else None
            if cls_bt is not None and any(has_tvar(a) for a in cls_bt.args):
                template = True
            if template and has_tvar(ret):
                ret_vars = {t.name for t in self._walk(ret) if isinstance(t, TVar)}
                param_vars = {t.name for p in params for t in self._walk(p.typ)
                              if isinstance(t, TVar)}
                cls_vars: set[str] = set()
                if bound is not None:
                    cb = self.cls_bind.get((mod.name, fn.name))
                    if cb is not None:
                        cls_vars = {t.name for a in cb.args for t in self._walk(a)
                                    if isinstance(t, TVar)}
                if not ret_vars <= (param_vars | cls_vars):
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"return type of '{fn.name}' uses a type variable that no "
                                   f"parameter mentions — it can never be inferred",
                                   Span(file, r.lineno, r.col_offset))
            self.sigs[(mod.name, fn.name)] = FuncSig(mod.name, fn.name, params, ret, fn,
                                                     is_template=template)

    def union_discriminator(self, t: TUnion):
        """The tag of an all-model union: (field name, one constant default per member).

        Serpentine has no `Literal`, so the discriminator is spelled as a shared field whose
        **default** differs in every member (`kind: str = "cat"`). None when not discriminable.
        """
        if len(t.members) < 2 or not all(isinstance(m, TClass) for m in t.members):
            return None
        infos = []
        for m in t.members:
            assert isinstance(m, TClass)
            info = self.classes.get((m.module, m.name))
            if info is None:
                return None
            infos.append(info)
        for name in infos[0].field_order:
            vals = []
            for info in infos:
                node = info.field_defaults.get(name)
                if node is None or isinstance(node.value, bool) \
                        or not isinstance(node.value, (str, int)):
                    vals = []
                    break
                vals.append(node.value)
            if len(vals) == len(infos) and len(set(vals)) == len(vals):
                return (name, vals)
        return None

    def _check_constants(self, mod: Module) -> None:
        for name, node in mod.constants.items():
            parsed = parse_annotation(node.annotation, self.rep, str(mod.path), allow_wrapper=False)
            if not parsed.typ.is_copy():
                self.rep.fatal("SE206", "mutable-global",
                               f"module-level '{name}' is not a Copy type — mutable globals are "
                               f"rejected in Tier 0", self._span(mod, node))
            if node.value is None or not isinstance(node.value, ast.Constant):
                self.rep.fatal("SE205", "module-level-statement",
                               f"module-level constant '{name}' must have a literal initializer",
                               self._span(mod, node))
            self.constants[(mod.name, name)] = parsed.typ

    def _resolve_callee(self, mod: Module, name: str) -> FuncSig | None:
        if (mod.name, name) in self.sigs:
            return self.sigs[(mod.name, name)]
        if name in mod.imports:
            target_mod, orig = mod.imports[name]
            return self.sigs.get((target_mod, orig))
        return None

    def _expand_literal_stars(self, node: ast.Call) -> None:
        """Expand `**{"a": 1}` into ordinary keyword arguments (LB8, docs D19)."""
        if not any(kw.arg is None for kw in node.keywords):
            return
        out: list[ast.keyword] = []
        for kw in node.keywords:
            d = kw.value
            if kw.arg is None and isinstance(d, ast.Dict) and d.keys and all(
                    isinstance(k, ast.Constant) and isinstance(k.value, str)
                    for k in d.keys):
                for k, v in zip(d.keys, d.values):
                    out.append(ast.keyword(arg=k.value, value=v))
                continue
            out.append(kw)
        node.keywords = out

    def _apply_keywords(self, node: ast.Call, params: list, label: str) -> None:
        """Rewrite keyword arguments into positional order, filling gaps with literal defaults."""
        if not node.keywords:
            return
        self._expand_literal_stars(node)
        if not node.keywords:
            return
        names = [p.name for p in params]
        kwmap: dict[str, ast.expr] = {}
        for kw in node.keywords:
            if kw.arg is None:
                self._err("SE201", "unsupported-feature",
                          f"**mapping in a call to {label} needs a dict literal with "
                          f"constant string keys (only a class constructor accepts a "
                          f"runtime mapping)", node)
                continue
            if kw.arg not in names:
                self._err("SE214", "type-mismatch",
                          f"{label} has no parameter '{kw.arg}'", node)
            if names.index(kw.arg) < len(node.args):
                self._err("SE214", "type-mismatch",
                          f"{label} got multiple values for parameter '{kw.arg}'", node)
            if kw.arg in kwmap:
                self._err("SE214", "type-mismatch",
                          f"{label} got duplicate keyword argument '{kw.arg}'", node)
            kwmap[kw.arg] = kw.value
        last = max(names.index(k) for k in kwmap)
        new_args = list(node.args)
        for i in range(len(node.args), last + 1):
            p = params[i]
            if p.name in kwmap:
                new_args.append(kwmap[p.name])
            elif p.default is not None:
                if isinstance(p.default, ast.Constant):
                    c: ast.expr = ast.Constant(value=p.default.value)
                else:
                    c = copy.deepcopy(p.default)
                ast.copy_location(c, node)
                new_args.append(c)
            else:
                self._err("SE214", "type-mismatch",
                          f"{label} missing required argument '{p.name}'", node)
        node.args = new_args
        node.keywords = []


    # ---------- function body checking ----------

    def _check_function(self, mod: Module, fn: ast.FunctionDef, sig: FuncSig) -> None:
        key = (sig.module, sig.name)
        if key in self.checked_bodies:
            return
        self.checked_bodies.add(key)
        facts = FuncFacts(sig=sig)
        self.facts[key] = facts
        self.env: dict[str, tuple[Type, str]] = {}
        self.mod = mod
        self.fn = fn
        self.sig = sig
        self.cls_now = self.cls_bind.get(key)
        self.cur_facts = facts
        self.loop_refs: list[dict[str, str]] = []
        self.comp_borrows: list[list[str]] = []
        self.with_targets: list[str] = []
        self.ref_locals: dict[str, str] = {}      # scoped borrow name -> root
        self.elem_borrows: dict[str, set[str]] = {}   # root -> active borrow names
        self.borrow_scopes: list[list[tuple[str, str]]] = []
        self.loop_depth = 0
        self.try_stack: list[dict] = []
        self.handler_depth = 0
        self.captured_frozen: set[str] = set()    # names captured by a lambda (immutable after)
        self.frozen_noncopy: set[str] = set()     # non-Copy captures: no mutation/move after
        self.lambda_caps_active: list[set[str]] = []   # non-Copy captures of lambdas being typed
        self.loop_assigned = set()                # names stored anywhere inside a loop
        for n in ast.walk(fn):
            if isinstance(n, (ast.For, ast.While)):
                for sub in ast.walk(n):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        self.loop_assigned.add(sub.id)
        for p in sig.params:
            self.env[p.name] = (p.typ, p.conv)
            facts.locals[p.name] = p.typ
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        _, term = self._check_block(body, {})
        if not term and not isinstance(sig.ret, TNone):
            self.rep.fatal("SE214", "type-mismatch",
                           f"function '{sig.name}' returns {sig.ret} but can fall off the end",
                           self._span(mod, fn))

    def _cur_names(self) -> dict[str, Type]:
        """Annotation names visible in the current function (module names + subst)."""
        names = self._type_names(self.mod)
        if self.cls_now is not None:
            names["Self"] = self.cls_now
            names["cls"] = self.cls_now
        for tv, concrete in self.sig.subst.items():
            names[tv] = concrete
        return names

    def _instantiate(self, template: FuncSig, sub: dict, node: ast.AST) -> FuncSig:
        """Monomorphize a generic function/method for a concrete substitution."""
        params = [Param(p.name, p.conv, subst_type(p.typ, sub), p.default)
                  for p in template.params]
        ret = subst_type(template.ret, sub)
        mangle = "_".join(mangle_type(sub[k]) for k in sorted(sub))
        inst_name = f"{template.name}__{mangle}" if sub else template.name
        key = (template.module, inst_name)
        if key in self.sigs:
            return self.sigs[key]
        node_copy = copy.deepcopy(template.node)
        inst = FuncSig(template.module, inst_name, params, ret, node_copy,
                       is_template=False, cls=template.cls, subst=dict(sub))
        self.sigs[key] = inst
        tb = self.cls_bind.get((template.module, template.name))
        if tb is not None:
            self.cls_bind[key] = subst_type(tb, sub)
        # Fix conventions that were deferred while the type was still a TVar.
        for p in inst.params:
            if p.conv == CONV_OWNED and p.typ.is_copy():
                p.conv = CONV_COPY
        saved = (self.env, self.mod, self.fn, self.sig, self.cur_facts, self.loop_refs,
                 self.loop_depth, self.try_stack, self.handler_depth, self.comp_borrows,
                 self.with_targets, self.ref_locals, self.elem_borrows, self.borrow_scopes)
        target_mod = self.program.modules[template.module]
        self._check_function(target_mod, node_copy, inst)
        (self.env, self.mod, self.fn, self.sig, self.cur_facts, self.loop_refs,
         self.loop_depth, self.try_stack, self.handler_depth, self.comp_borrows,
         self.with_targets, self.ref_locals, self.elem_borrows, self.borrow_scopes) = saved
        return inst

    def _err(self, code: str, name: str, msg: str, node: ast.AST, label: str = "",
             help: str = "") -> None:
        self.rep.fatal(code, name, msg, self._span(self.mod, node), label, help=help)

    def _setattr_rewrite(self, stmt: ast.Assign, target: ast.Attribute,
                         narrow: dict[str, Type]) -> ast.stmt | None:
        """The `obj.__setattr__("f", v)` statement replacing a write to a hooked class."""
        if not isinstance(target.value, ast.Name) \
                or self.fn.name.startswith("_serp_f") \
                or self.fn.name == "__post_init__":
            return None
        entry = self.env.get(target.value.id)
        bt = narrow.get(target.value.id) or (entry[0] if entry is not None else None)
        info = self.classes.get((bt.module, bt.name)) if isinstance(bt, TClass) else None
        if info is None or "__setattr__" not in info.methods:
            return None
        call = ast.Call(
            func=ast.Attribute(value=ast.Name(id=target.value.id, ctx=ast.Load()),
                               attr="__setattr__", ctx=ast.Load()),
            args=[ast.Constant(value=target.attr), stmt.value], keywords=[])
        new = ast.Expr(value=call)
        ast.copy_location(new, stmt)
        ast.fix_missing_locations(new)
        self.stmt_rewrites[id(stmt)] = new
        return new

    def _check_block(self, stmts: list[ast.stmt], narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        """Check a statement list; returns (narrowings after, definitely-terminates)."""
        self.borrow_scopes.append([])
        term = False
        for i, stmt in enumerate(stmts):
            if term:
                break
            narrow, term = self._check_stmt(stmt, narrow)
            repl = self.stmt_rewrites.pop(id(stmt), None)
            if repl is not None:
                stmts[i] = repl
        for (name, root) in self.borrow_scopes.pop():
            self.env.pop(name, None)
            self.ref_locals.pop(name, None)
            self.elem_borrows.get(root, set()).discard(name)
        return narrow, term

    def _assigned_names(self, stmts: list[ast.stmt]) -> set[str]:
        """Names assigned anywhere in a statement list (for narrowing invalidation)."""
        names: set[str] = set()
        for stmt in stmts:
            for node in ast.walk(stmt):
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if isinstance(tgt, ast.Name):
                        names.add(tgt.id)
                    elif isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name):
                        names.add(tgt.value.id)
                if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
        return names

    def _check_stmt(self, stmt: ast.stmt, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        if isinstance(stmt, ast.TryStar):
            self._err("SE201", "unsupported-feature", "except* is not Tier 1", stmt)
        if isinstance(stmt, ast.Try):
            return self._check_try(stmt, narrow)
        if isinstance(stmt, ast.Raise):
            self._check_raise(stmt, narrow)
            return narrow, True
        if isinstance(stmt, ast.With):
            return self._check_with(stmt, narrow)
        if isinstance(stmt, (ast.Match, ast.Assert, ast.Delete, ast.Global,
                             ast.Nonlocal, ast.Import, ast.ImportFrom,
                             ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self._err("SE201", "unsupported-feature",
                      f"'{type(stmt).__name__}' is not in the Tier-0/1 grammar", stmt)
        if isinstance(stmt, ast.Pass):
            return narrow, False
        if isinstance(stmt, ast.Return):
            if self.try_stack and any(t["has_finally"] for t in self.try_stack):
                self._err("SE201", "unsupported-feature",
                          "return inside a try with finally is not Tier 1", stmt)
            self._check_return(stmt, narrow)
            return narrow, True
        if isinstance(stmt, (ast.Break, ast.Continue)):
            if self.try_stack and self.loop_depth <= self.try_stack[-1]["loop_depth"]:
                self._err("SE201", "unsupported-feature",
                          "break/continue may not jump out of a try/except block in Tier 1",
                          stmt)
            return narrow, True
        if isinstance(stmt, ast.Expr):
            et = self._type_expr(stmt.value, narrow)
            if isinstance(et, TIterObj):
                self._err("SE201", "unsupported-feature",
                          "iter() must be bound to a name: it = iter(xs)", stmt.value)
            return narrow, self._is_sys_exit(stmt.value)
        if isinstance(stmt, ast.AnnAssign):
            return self._check_annassign(stmt, narrow), False
        if isinstance(stmt, ast.Assign):
            return self._check_assign(stmt, narrow), False
        if isinstance(stmt, ast.AugAssign):
            return self._check_augassign(stmt, narrow), False
        if isinstance(stmt, ast.If):
            return self._check_if(stmt, narrow)
        if isinstance(stmt, ast.While):
            return self._check_while(stmt, narrow)
        if isinstance(stmt, ast.For):
            return self._check_for(stmt, narrow)
        self._err("SE201", "unsupported-feature",
                  f"'{type(stmt).__name__}' is not in the Tier-0/1 grammar", stmt)
        raise AssertionError

    def _is_sys_exit(self, e: ast.expr) -> bool:
        return (isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute)
                and isinstance(e.func.value, ast.Name) and e.func.value.id == "sys"
                and e.func.attr == "exit" and self.mod.imports_sys)

    def _check_try(self, stmt: ast.Try, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        """Tier-1 try/except/finally: try is a sub-scope, E1 join at except entry."""
        if stmt.orelse:
            self._err("SE201", "unsupported-feature", "try/else is not Tier 1", stmt)
        if not stmt.handlers and not stmt.finalbody:
            self._err("SE201", "unsupported-feature", "try needs except or finally", stmt)
        self.try_stack.append({"has_finally": bool(stmt.finalbody),
                               "loop_depth": self.loop_depth})
        assigned = self._assigned_names(stmt.body)
        body_narrow = self._filter_narrow(narrow, assigned)
        _, body_term = self._check_block(stmt.body, body_narrow)
        self.try_stack.pop()

        handler_terms = []
        seen_classes: list[str] = []
        for h in stmt.handlers:
            classes = self._handler_classes(h)
            for c in classes:
                covered = {c} | exc_ancestors(c, self.user_exc)
                if covered & set(seen_classes):
                    self._err("SE201", "unsupported-feature",
                              f"except clause for '{c}' is unreachable — already handled", h)
            seen_classes.extend(classes)
            if h.name:
                self._declare(h.name, TExc(), h)
                self.cur_facts.events.append(("assign", h.name, h))
            self.handler_depth += 1
            h_assigned = self._assigned_names(h.body)
            h_narrow = {k: v for k, v in narrow.items()
                        if k.split('.')[0] not in assigned and k.split('.')[0] not in h_assigned}
            _, h_term = self._check_block(h.body, h_narrow)
            self.handler_depth -= 1
            handler_terms.append(h_term)

        if stmt.finalbody:
            for node in ast.walk(ast.Module(body=stmt.finalbody, type_ignores=[])):
                if isinstance(node, (ast.Return, ast.Break, ast.Continue)):
                    self._err("SE201", "unsupported-feature",
                              "return/break/continue inside finally would swallow the "
                              "in-flight exception", node)
            self._check_block(stmt.finalbody, {})

        all_assigned = assigned | set().union(*(self._assigned_names(h.body)
                                                for h in stmt.handlers)) \
            if stmt.handlers else assigned
        after = self._filter_narrow(narrow, all_assigned)
        term = body_term and bool(stmt.handlers) and all(handler_terms)
        return after, term

    def _handler_classes(self, h: ast.ExceptHandler) -> list[str]:
        if h.type is None:
            return ["Exception"]
        if isinstance(h.type, ast.Name):
            if not self._exc_ok(h.type.id):
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{h.type.id}' — define it as "
                          f"'class {h.type.id}(Exception): pass' or import it", h.type)
            return [h.type.id]
        if isinstance(h.type, ast.Tuple):
            out = []
            for e in h.type.elts:
                if not isinstance(e, ast.Name) or not self._exc_ok(e.id):
                    self._err("SE214", "type-mismatch",
                              "except tuple entries must be known exception classes", e)
                out.append(e.id)
            return out
        self._err("SE201", "unsupported-feature", "unsupported except clause", h)
        raise AssertionError

    def _check_raise(self, stmt: ast.Raise, narrow: dict[str, Type]) -> None:
        if stmt.cause is not None:
            self._err("SE201", "unsupported-feature", "raise ... from ... is not Tier 1", stmt)
        if stmt.exc is None:
            if self.handler_depth == 0:
                self._err("SE201", "unsupported-feature",
                          "bare raise is only allowed inside an except handler", stmt)
            return
        e = stmt.exc
        if isinstance(e, ast.Name):
            if not self._exc_ok(e.id):
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{e.id}' — define it as "
                          f"'class {e.id}(Exception): pass' or import it", e)
            return
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name):
            if not self._exc_ok(e.func.id):
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{e.func.id}' — define it as "
                          f"'class {e.func.id}(Exception): pass' or import it", e)
            if e.keywords or len(e.args) > 1:
                self._err("SE214", "type-mismatch",
                          "exceptions take at most one positional message argument", e)
            if e.args:
                t = self._type_expr(e.args[0], narrow)
                if not isinstance(t, TStr):
                    self._err("SE214", "type-mismatch",
                              f"exception message must be str, got {t}", e.args[0])
            return
        self._err("SE201", "unsupported-feature",
                  "raise takes a known exception class or class(message)", stmt)

    def _check_with(self, stmt: ast.With, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        """Tier-2 `with open(...) as f:` — RAII sugar; f closes and scopes to the block."""
        if len(stmt.items) != 1:
            self._err("SE201", "unsupported-feature",
                      "with takes exactly one context manager in Tier 2", stmt)
        item = stmt.items[0]
        ctx = item.context_expr
        if not (isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Name)
                and ctx.func.id == "open"):
            self._err("SE201", "unsupported-feature",
                      "with supports only open(...) in Tier 2", ctx)
        ctx_t = self._type_expr(ctx, narrow)
        if item.optional_vars is None or not isinstance(item.optional_vars, ast.Name):
            self._err("SE201", "unsupported-feature",
                      "with open(...) needs a single 'as <name>' target", stmt)
        name = item.optional_vars.id
        if name in self.env:
            self._err("SE201", "unsupported-feature",
                      f"with target '{name}' shadows an existing variable — use a fresh name",
                      item.optional_vars)
        self.env[name] = (ctx_t, "local")
        self.expr_types[id(item.optional_vars)] = ctx_t
        self.with_targets.append(name)
        assigned = self._assigned_names(stmt.body)
        body_narrow = self._filter_narrow(narrow, assigned)
        _, term = self._check_block(stmt.body, body_narrow)
        self.with_targets.pop()
        self.env.pop(name, None)
        return self._filter_narrow(narrow, assigned), term

    def _check_return(self, stmt: ast.Return, narrow: dict[str, Type]) -> None:
        if stmt.value is None:
            if not isinstance(self.sig.ret, TNone):
                self._err("SE214", "type-mismatch",
                          f"bare return in function returning {self.sig.ret}", stmt)
            return
        t = self._type_expr(stmt.value, narrow, expect=self.sig.ret)
        if not self._assignable(t, self.sig.ret):
            self._err("SE214", "type-mismatch",
                      f"return type mismatch: expected {self.sig.ret}, got {t}", stmt)
        if isinstance(stmt.value, ast.Name) and not t.is_copy():
            if self.env.get(stmt.value.id, (None, None))[1] == "reflocal":
                self._err("SE209", "returned-borrow",
                          f"cannot return '{stmt.value.id}' — it is a scoped Ref borrow "
                          f"of an element of '{self.ref_locals.get(stmt.value.id)}'", stmt)
            self.cur_facts.events.append(("move", stmt.value.id, stmt))

    def _declare(self, name: str, typ: Type, node: ast.AST) -> None:
        if name in self.env:
            old, conv = self.env[name]
            if old != typ and not self._assignable(typ, old):
                self._err("SE214", "type-mismatch",
                          f"'{name}' redeclared as {typ}, previously {old}", node)
        else:
            self.env[name] = (typ, "local")
            self.cur_facts.locals[name] = typ

    def _rhs_transfer_check(self, value: ast.expr, typ: Type, node: ast.AST) -> None:
        """Enforce J3: bare-Name RHS of non-Copy type requires move()."""
        if typ.is_copy():
            return
        if isinstance(value, ast.Name):
            self._err("SE003", "implicit-transfer",
                      f"assignment of live non-Copy value '{value.id}'",
                      value, label="this would silently create a second owner",
                      help=f"write 'move({value.id})' to transfer ownership")
        if isinstance(value, ast.Subscript) and id(value) not in self.op_calls:
            self._err("SE006", "move-out-of-container",
                      "cannot copy a non-Copy element out of a container — use pop(), "
                      "borrow in place, or overwrite", value)
        if isinstance(value, ast.Attribute) and not self._is_sys_attr(value):
            self._err("SE003", "implicit-transfer",
                      f"assignment of live non-Copy field '{ast.unparse(value)}' — write "
                      f"'move({ast.unparse(value)})' to transfer ownership", value)

    def _is_sys_attr(self, e: ast.expr) -> bool:
        return (isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name)
                and e.value.id == "sys" and self.mod.imports_sys)

    def _try_elem_borrow(self, target: ast.Name, value: ast.expr, t: Type,
                         node: ast.stmt) -> bool:
        """Bind `name = container[idx]` (non-Copy element) as a scoped Ref borrow."""
        if not isinstance(value, ast.Subscript) or isinstance(value.slice, ast.Slice):
            return False
        if t.is_copy() or isinstance(t, TOptional):
            return False
        if not isinstance(value.value, ast.Name):
            return False
        base = value.value.id
        base_t = self.env.get(base, (None, None))[0]
        if base_t is None or isinstance(base_t, TShared) \
                or not isinstance(base_t, (TList, TDict)):
            return False
        if target.id in self.env:
            self._err("SE201", "unsupported-feature",
                      f"scoped element borrow target '{target.id}' must be a fresh name",
                      target)
        self.env[target.id] = (t, "reflocal")
        self.ref_locals[target.id] = base
        self.elem_borrows.setdefault(base, set()).add(target.id)
        self.borrow_scopes[-1].append((target.id, base))
        self.elem_borrow_binds[id(node)] = (target.id, base)
        return True

    def _try_iter_bind(self, target: ast.Name, value: ast.expr, t: Type,
                       node: ast.stmt) -> bool:
        """Bind `it = iter(xs)` as a block-scoped iterator borrow of xs."""
        if not isinstance(t, TIterObj):
            return False
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == "iter" and value.args
                and isinstance(value.args[0], ast.Name)):
            self._err("SE201", "unsupported-feature",
                      "iterators may only be created with 'it = iter(xs)'", value)
        root = value.args[0].id
        if target.id in self.env:
            self._err("SE201", "unsupported-feature",
                      f"iterator target '{target.id}' must be a fresh name", target)
        self.env[target.id] = (t, "iterlocal")
        self.ref_locals[target.id] = root
        self.elem_borrows.setdefault(root, set()).add(target.id)
        self.borrow_scopes[-1].append((target.id, root))
        self.iter_binds[id(node)] = (target.id, root)
        return True

    def _check_annassign(self, stmt: ast.AnnAssign, narrow: dict[str, Type]) -> dict[str, Type]:
        if not isinstance(stmt.target, ast.Name):
            self._err("SE201", "unsupported-feature", "annotated assignment target must be a name", stmt)
        if stmt.target.id in self.captured_frozen:
            self._err("SE004", "conflicting-borrow",
                      f"'{stmt.target.id}' was captured by a lambda and is frozen — "
                      f"reassigning it would diverge from CPython's late binding", stmt)
        parsed = parse_annotation(stmt.annotation, self.rep, str(self.mod.path),
                                  allow_wrapper=True, names=self._cur_names())
        if parsed.conv in (CONV_REF, CONV_MUT):
            self._err("SE202", "invalid-wrapper-position",
                      "Ref/Mut may only annotate parameters — a Ref/Mut local would be a "
                      "stored borrow", stmt.annotation)
        if stmt.value is None:
            self._err("SE201", "unsupported-feature", "declarations must be initialized", stmt)
        t = self._type_expr(stmt.value, narrow, expect=parsed.typ)
        if not self._assignable(t, parsed.typ):
            self._err("SE214", "type-mismatch",
                      f"cannot assign {t} to '{stmt.target.id}: {parsed.typ}'", stmt)
        if self._try_elem_borrow(stmt.target, stmt.value, parsed.typ, stmt):
            narrow = dict(narrow)
            narrow.pop(stmt.target.id, None)
            return narrow
        self._rhs_transfer_check(stmt.value, parsed.typ, stmt)
        self._declare(stmt.target.id, parsed.typ, stmt)
        self._record_assign_events(stmt.target.id, stmt.value, stmt)
        narrow = dict(narrow)
        narrow.pop(stmt.target.id, None)
        return narrow

    def _record_assign_events(self, name: str, value: ast.expr, node: ast.AST) -> None:
        self.cur_facts.events.append(("assign", name, node))

    def _check_assign(self, stmt: ast.Assign, narrow: dict[str, Type]) -> dict[str, Type]:
        if len(stmt.targets) != 1:
            self._err("SE201", "unsupported-feature", "chained assignment is not Tier 0", stmt)
        target = stmt.targets[0]
        if isinstance(target, ast.Tuple):
            self._err("SE201", "unsupported-feature", "tuple unpacking is not Tier 0", stmt)
        if isinstance(target, ast.Name):
            if target.id in self.captured_frozen:
                self._err("SE004", "conflicting-borrow",
                          f"'{target.id}' was captured by a lambda and is frozen — "
                          f"reassigning it would diverge from CPython's late binding", stmt)
            t = self._type_expr(stmt.value, narrow,
                                expect=self.env[target.id][0] if target.id in self.env else None)
            if isinstance(t, TIter):
                self._err("SE201", "unsupported-feature",
                          "this iterator may only be consumed by a for loop", stmt.value)
            if target.id in self.env:
                if self.env[target.id][1] == "reflocal":
                    self._err("SE201", "unsupported-feature",
                              f"scoped element borrow '{target.id}' cannot be re-assigned "
                              f"— it lives until the end of its block", stmt)
                declared = self.env[target.id][0]
                if not self._assignable(t, declared):
                    self._err("SE214", "type-mismatch",
                              f"cannot assign {t} to '{target.id}: {declared}'", stmt)
                t = declared
            else:
                if self._is_empty_literal(stmt.value):
                    self._err("SE204", "unknown-element-type",
                              "empty container literal needs a type annotation", stmt.value)
            if getattr(stmt.value, "_destructure", False):
                # `a, b = it.__next__()` lowering: the tuple temp is dead after the
                # unpack, so each element is owned by its name (a move, not a copy).
                self._declare(target.id, t, stmt)
                self._record_assign_events(target.id, stmt.value, stmt)
                narrow = dict(narrow)
                narrow.pop(target.id, None)
                return narrow
            if self._try_elem_borrow(target, stmt.value, t, stmt):
                narrow = dict(narrow)
                narrow.pop(target.id, None)
                return narrow
            if self._try_iter_bind(target, stmt.value, t, stmt):
                narrow = dict(narrow)
                narrow.pop(target.id, None)
                return narrow
            self._rhs_transfer_check(stmt.value, t, stmt)
            self._declare(target.id, t, stmt)
            self._record_assign_events(target.id, stmt.value, stmt)
            narrow = dict(narrow)
            narrow.pop(target.id, None)
            return narrow
        if isinstance(target, ast.Subscript):
            cont_t = self._type_expr(target.value, narrow)
            if isinstance(cont_t, TShared):
                cont_t = cont_t.inner
            if isinstance(cont_t, TByteArray):
                idx_t0 = self._type_expr(target.slice, narrow)
                if not isinstance(idx_t0, TInt):
                    self._err("SE214", "type-mismatch",
                              f"bytearray index must be int, got {idx_t0}", target.slice)
                vt0 = self._type_expr(stmt.value, narrow, expect=INT)
                if not isinstance(vt0, TInt):
                    self._err("SE214", "type-mismatch",
                              f"bytearray items must be int, got {vt0}", stmt.value)
                self._mut_borrow_place(target.value, stmt)
                self._check_narrow_invalidation_by_mut(target.value, narrow)
                return narrow
            if isinstance(cont_t, TClass):
                self._type_expr(stmt.value, narrow)
                keys: list[ast.expr] = [target.slice]
                if isinstance(target.slice, ast.Tuple) \
                        and self._dunder_arity(cont_t, "__setitem__") > 2:
                    keys = [self._slice_call(e) if isinstance(e, ast.Slice) else e
                            for e in target.slice.elts]
                elif isinstance(target.slice, ast.Slice):
                    keys = [self._slice_call(target.slice)]
                t = self._op_method_call(stmt, target.value, "__setitem__",
                                         keys + [stmt.value], narrow, require=NONE)
                if t is None:
                    self._err("SE214", "type-mismatch",
                              f"{cont_t} does not support item assignment — define "
                              f"__setitem__()", target)
                return narrow
            idx_t = self._type_expr(target.slice, narrow)
            if isinstance(cont_t, TList):
                if not isinstance(idx_t, TInt):
                    self._err("SE214", "type-mismatch", f"list index must be int, got {idx_t}", target.slice)
                elem = cont_t.elem
            elif isinstance(cont_t, TDict):
                if not self._assignable(idx_t, cont_t.key):
                    self._err("SE214", "type-mismatch",
                              f"dict key must be {cont_t.key}, got {idx_t}", target.slice)
                elem = cont_t.value
            else:
                self._err("SE214", "type-mismatch", f"{cont_t} does not support item assignment", target)
                raise AssertionError
            vt = self._type_expr(stmt.value, narrow, expect=elem)
            if not self._assignable(vt, elem):
                self._err("SE214", "type-mismatch", f"cannot store {vt} in {cont_t}", stmt.value)
            if not elem.is_copy() and isinstance(stmt.value, ast.Name):
                self._err("SE002", "missing-move",
                          f"storing non-Copy value '{stmt.value.id}' transfers ownership — "
                          f"write 'move({stmt.value.id})'", stmt.value)
            self._mut_borrow_place(target.value, stmt)
            self._check_narrow_invalidation_by_mut(target.value, narrow)
            return narrow
        if isinstance(target, ast.Attribute):
            hook = self._setattr_rewrite(stmt, target, narrow)
            if hook is not None:
                return self._check_stmt(hook, narrow)[0]
            base_t = self._type_expr(target.value, narrow)
            cls_t = base_t.inner if isinstance(base_t, TShared) else base_t
            if not isinstance(cls_t, TClass):
                self._err("SE214", "type-mismatch",
                          f"{base_t} has no assignable attribute '{target.attr}'", target)
            ft = self._field_type(cls_t, target.attr, target)
            finfo = self.classes.get((cls_t.module, cls_t.name))
            if finfo is not None and finfo.frozen:
                self._err("SE201", "unsupported-feature",
                          f"class '{cls_t.name}' is frozen — field '{target.attr}' cannot "
                          f"be assigned after construction", target)
            vt = self._type_expr(stmt.value, narrow, expect=ft)
            if not self._assignable(vt, ft):
                self._err("SE214", "type-mismatch",
                          f"cannot assign {vt} to field '{target.attr}: {ft}'", stmt.value)
            if not ft.is_copy() and isinstance(stmt.value, (ast.Name, ast.Attribute)):
                self._err("SE002", "missing-move",
                          f"storing a non-Copy value in field '{target.attr}' transfers "
                          f"ownership — write 'move(...)'", stmt.value)
            self.expr_types[id(target)] = ft
            if isinstance(base_t, TShared):
                self._mut_borrow_place(target.value, stmt)
            elif isinstance(target.value, ast.Name):
                self._mut_root_check(target.value.id, stmt)
                self.cur_facts.events.append(("field_def", f"{target.value.id}.{target.attr}", stmt))
            else:
                self._mut_borrow_place(target.value, stmt)
            self._check_narrow_invalidation_by_mut(target.value, narrow)
            return narrow
        self._err("SE201", "unsupported-feature", "unsupported assignment target", stmt)
        raise AssertionError

    def _check_augassign(self, stmt: ast.AugAssign, narrow: dict[str, Type]) -> dict[str, Type]:
        if isinstance(stmt.target, ast.Name) and stmt.target.id in self.captured_frozen:
            self._err("SE004", "conflicting-borrow",
                      f"'{stmt.target.id}' was captured by a lambda and is frozen — "
                      f"reassigning it would diverge from CPython's late binding", stmt)
        tt = self._type_expr_place(stmt.target, narrow)
        vt = self._type_expr(stmt.value, narrow)
        rt = self._binop_type(stmt.op, tt, vt, stmt, narrow)
        if not self._assignable(rt, tt):
            self._err("SE214", "type-mismatch", f"augmented assignment changes type {tt} -> {rt}", stmt)
        if isinstance(stmt.target, (ast.Subscript, ast.Attribute)):
            if isinstance(stmt.target, ast.Attribute):
                bt = self.expr_types.get(id(stmt.target.value))
                bt = bt.inner if isinstance(bt, TShared) else bt
                binfo = self.classes.get((bt.module, bt.name)) \
                    if isinstance(bt, TClass) else None
                if binfo is not None and binfo.frozen:
                    self._err("SE201", "unsupported-feature",
                              f"class '{binfo.name}' is frozen — field "
                              f"'{stmt.target.attr}' cannot be assigned", stmt)
            self._mut_borrow_place(stmt.target.value, stmt)
        if isinstance(stmt.target, ast.Name):
            narrow = dict(narrow)
            narrow.pop(stmt.target.id, None)
            self._record_assign_events(stmt.target.id, stmt.value, stmt)
        return narrow

    def _check_if(self, stmt: ast.If, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        cond_t = self._type_expr(stmt.test, narrow)
        if not isinstance(cond_t, (TBool, TPyVal)):
            self._err("SE214", "type-mismatch", f"if condition must be bool, got {cond_t}", stmt.test)
        pos, neg = self._narrow_from_test(stmt.test, narrow)
        then_after, then_term = self._check_block(stmt.body, pos)
        else_after, else_term = self._check_block(stmt.orelse, neg) if stmt.orelse else (neg, False)
        assigned = self._assigned_names(stmt.body) | self._assigned_names(stmt.orelse)
        after = self._filter_narrow(narrow, assigned)
        if then_term and not else_term:
            after.update(self._filter_narrow(else_after, self._assigned_names(stmt.orelse)))
        elif else_term and not then_term:
            after.update(self._filter_narrow(then_after, self._assigned_names(stmt.body)))
        elif not then_term and not else_term and stmt.orelse:
            common = {k: v for k, v in then_after.items() if else_after.get(k) == v}
            after.update(self._filter_narrow(common, assigned))
        return after, then_term and (else_term if stmt.orelse else False)

    def _narrow_from_test(self, test: ast.expr, narrow: dict[str, Type]) \
            -> tuple[dict[str, Type], dict[str, Type]]:
        """Compute narrowings for the true and false branches of a condition."""
        pos = dict(narrow)
        neg = dict(narrow)
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) \
                and test.func.id == "isinstance" and len(test.args) == 2:
            key, declared = self._narrow_place(test.args[0])
            member = self._isinstance_member(declared, test.args[1], test) \
                if key is not None and isinstance(declared, TUnion) else None
            if member is not None:
                pos[key] = member
                rest = [m for m in declared.members if m != member]
                if len(rest) == 1:
                    neg[key] = rest[0]
            return pos, neg
        if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.ops[0], (ast.Is, ast.IsNot)):
            key, declared = self._narrow_place(test.left)
            if key is not None and isinstance(declared, TOptional):
                if isinstance(test.ops[0], ast.IsNot):
                    pos[key] = declared.inner
                else:
                    neg[key] = declared.inner
            elif key is not None and isinstance(declared, TUnion) \
                    and NONE in declared.members:
                if isinstance(test.ops[0], ast.IsNot):
                    neg[key] = NONE
                else:
                    pos[key] = NONE
        return pos, neg

    def _narrow_place(self, place: ast.expr) -> tuple[str | None, Type | None]:
        """The narrowing key and declared type of a narrowable place expression."""
        if isinstance(place, ast.Name):
            return place.id, self.env.get(place.id, (None, None))[0]
        if isinstance(place, ast.Attribute) and isinstance(place.value, ast.Name):
            base_t = self.env.get(place.value.id, (None, None))[0]
            if isinstance(base_t, TClass):
                return (f"{place.value.id}.{place.attr}",
                        self._field_type(base_t, place.attr, place))
        return None, None

    def _type_isinstance(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        """Type an isinstance() union tag test — the only narrowing form for unions."""
        if len(node.args) != 2 or node.keywords:
            self._err("SE214", "type-mismatch", "isinstance() takes exactly two arguments", node)
        key, declared = self._narrow_place(node.args[0])
        if key is None or not isinstance(declared, TUnion):
            self._err("SE201", "unsupported-feature",
                      "isinstance() only tests a union-typed name or field", node)
        member = self._isinstance_member(declared, node.args[1], node)
        self.isinstance_checks[id(node)] = (declared, member)
        self._type_expr(node.args[0], {k: v for k, v in narrow.items() if k != key})
        return BOOL

    def _isinstance_member(self, declared: TUnion, cls: ast.expr, node: ast.AST) -> Type | None:
        """Resolve the union member an isinstance() class argument selects."""
        builtin = {"int": "int", "float": "float", "bool": "bool", "str": "str",
                   "bytes": "bytes", "bytearray": "bytearray", "list": "list",
                   "dict": "dict", "set": "set", "frozenset": "set", "tuple": "tuple"}
        tag = None
        if isinstance(cls, ast.Name):
            tag = builtin.get(cls.id)
            if tag is None:
                known = self._type_names(self.mod).get(cls.id)
                if isinstance(known, (TClass, TEnum)):
                    tag = union_tag(known)
        if tag is None:
            self._err("SE214", "type-mismatch",
                      "isinstance() needs a concrete type as its second argument", node)
            return None
        for m in declared.members:
            if union_tag(m) == tag:
                return m
        self._err("SE214", "type-mismatch",
                  f"'{tag}' is not a member of {declared}", node)
        return None

    def _filter_narrow(self, narrow: dict[str, Type], assigned: set[str]) -> dict[str, Type]:
        """Drop narrowings whose root name is (re)assigned."""
        return {k: v for k, v in narrow.items() if k.split(".")[0] not in assigned}

    def _check_while(self, stmt: ast.While, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        assigned = self._assigned_names(stmt.body)
        loop_narrow = self._filter_narrow(narrow, assigned)
        cond_t = self._type_expr(stmt.test, loop_narrow)
        if not isinstance(cond_t, (TBool, TPyVal)):
            self._err("SE214", "type-mismatch", f"while condition must be bool, got {cond_t}", stmt.test)
        pos, _neg = self._narrow_from_test(stmt.test, loop_narrow)
        self.loop_depth += 1
        self._check_block(stmt.body, pos)
        self.loop_depth -= 1
        if stmt.orelse:
            self._err("SE201", "unsupported-feature", "while-else is not Tier 0", stmt)
        return self._filter_narrow(narrow, assigned), False

    def _check_for(self, stmt: ast.For, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        if stmt.orelse:
            self._err("SE201", "unsupported-feature", "for-else is not Tier 0", stmt)
        iter_t = self._type_expr(stmt.iter, narrow)
        if isinstance(iter_t, TClass):
            cinfo = self.classes.get((iter_t.module, iter_t.name))
            if cinfo is not None and "__next__" in cinfo.methods:
                return self._lower_class_for(stmt, narrow)
        kind = "list"
        elems: tuple[Type, ...]
        if isinstance(iter_t, TList):
            elems = (iter_t.elem,)
        elif isinstance(iter_t, TSet):
            kind = "set"
            elems = (iter_t.elem,)
        elif isinstance(iter_t, TStr):
            kind = "str"
            elems = (STR,)
        elif isinstance(iter_t, (TBytes, TByteArray)):
            kind = "bytes" if isinstance(iter_t, TBytes) else "bytearray"
            elems = (INT,)
        elif isinstance(iter_t, TPyVal):
            kind = "pyval"
            elems = (TPyVal(),)
        elif isinstance(iter_t, TIter):
            kind = iter_t.kind
            elems = iter_t.elem
        else:
            self._err("SE214", "type-mismatch", f"cannot iterate over {iter_t}", stmt.iter)
            raise AssertionError
        self.loop_iter_kind[id(stmt)] = kind

        targets: list[ast.Name] = []
        if isinstance(stmt.target, ast.Name):
            targets = [stmt.target]
        elif isinstance(stmt.target, ast.Tuple) and len(stmt.target.elts) == 2 \
                and all(isinstance(e, ast.Name) for e in stmt.target.elts):
            targets = list(stmt.target.elts)  # type: ignore[arg-type]
        else:
            self._err("SE201", "unsupported-feature", "for target must be one or two names", stmt.target)
        if len(targets) != len(elems):
            self._err("SE214", "type-mismatch",
                      f"for target unpacks {len(targets)} names but iterator yields {len(elems)}",
                      stmt.target)
        loop_ref_vars: dict[str, str] = {}
        for tgt, et in zip(targets, elems):
            self._declare(tgt.id, et, tgt)
            if not et.is_copy():
                loop_ref_vars[tgt.id] = "ref"

        borrowed = self._borrowable_root(stmt.iter)
        if borrowed is not None:
            self.cur_facts.events.append(("loop_borrow_begin", borrowed, stmt))
        self.loop_refs.append(loop_ref_vars)
        self.loop_depth += 1
        assigned = self._assigned_names(stmt.body)
        body_narrow = self._filter_narrow(narrow, assigned)
        self._check_block(stmt.body, body_narrow)
        self.loop_depth -= 1
        self.loop_refs.pop()
        if borrowed is not None:
            self.cur_facts.events.append(("loop_borrow_end", borrowed, stmt))
        for tgt in targets:
            assigned.add(tgt.id)
        return self._filter_narrow(narrow, assigned), False

    def _lower_class_for(self, stmt: ast.For, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        """Lower `for x in obj` over a user iterator class into while/__next__/except."""
        self._for_counter += 1
        n = self._for_counter
        out: list[ast.stmt] = []
        lowered_names: list[str] = []
        it = stmt.iter
        if isinstance(it, (ast.Name, ast.Attribute, ast.Subscript)):
            recv: ast.expr = copy.deepcopy(it)
        else:
            tname = f"_serp_for_{n}"
            hoist = ast.Assign(targets=[ast.Name(id=tname, ctx=ast.Store())], value=it)
            ast.copy_location(hoist, stmt)
            ast.fix_missing_locations(hoist)
            self._declare(tname, self.expr_types[id(it)], stmt)
            out.append(hoist)
            lowered_names.append(tname)
            recv = ast.Name(id=tname, ctx=ast.Load())
        call = ast.Call(func=ast.Attribute(value=recv, attr="__next__", ctx=ast.Load()),
                        args=[], keywords=[])
        unpack: list[ast.stmt] = []
        if isinstance(stmt.target, ast.Name):
            step = ast.Assign(targets=[ast.Name(id=stmt.target.id, ctx=ast.Store())],
                              value=call)
            lowered_names.append(stmt.target.id)
        elif isinstance(stmt.target, ast.Tuple) \
                and all(isinstance(e, ast.Name) for e in stmt.target.elts):
            ttmp = f"_serp_for_{n}_t"
            step = ast.Assign(targets=[ast.Name(id=ttmp, ctx=ast.Store())], value=call)
            lowered_names.append(ttmp)
            for i, elt in enumerate(stmt.target.elts):
                sub = ast.Subscript(value=ast.Name(id=ttmp, ctx=ast.Load()),
                                    slice=ast.Constant(value=i), ctx=ast.Load())
                sub._destructure = True
                unpack.append(ast.Assign(targets=[ast.Name(id=elt.id, ctx=ast.Store())],
                                         value=sub))
                lowered_names.append(elt.id)
        else:
            self._err("SE201", "unsupported-feature",
                      "for target must be one or more names", stmt.target)
            raise AssertionError
        handler = ast.ExceptHandler(type=ast.Name(id="StopIteration", ctx=ast.Load()),
                                    name=None, body=[ast.Break()])
        tr = ast.Try(body=[step], handlers=[handler], orelse=[], finalbody=[])
        wh = ast.While(test=ast.Constant(value=True),
                       body=[tr] + unpack + list(stmt.body), orelse=[])
        for nd in (wh, tr, handler):
            ast.copy_location(nd, stmt)
        ast.fix_missing_locations(wh)
        out.append(wh)
        self.for_lowered[id(stmt)] = out
        self.for_lowered_names[id(stmt)] = lowered_names
        if out[0] is not wh:
            self.cur_facts.events.append(("assign", lowered_names[0], stmt))
        narrow, _term = self._check_stmt(wh, narrow)
        return narrow, False

    def _borrowable_root(self, iter_expr: ast.expr) -> str | None:
        """The root variable Ref-borrowed by a for loop, if any (range borrows nothing)."""
        e = iter_expr
        if isinstance(e, ast.Call):
            if isinstance(e.func, ast.Name) and e.func.id == "range":
                return None
            if isinstance(e.func, ast.Name) and e.func.id in ("enumerate", "reversed", "zip") \
                    and e.args:
                e = e.args[0]
            elif isinstance(e.func, ast.Attribute):
                e = e.func.value
        while isinstance(e, (ast.Subscript, ast.Attribute)):
            if isinstance(e, ast.Attribute) and self._is_sys_attr(e):
                return None
            e = e.value
        if isinstance(e, ast.Name):
            t = self.env.get(e.id, (None, None))[0]
            if t is not None and not t.is_copy():
                return e.id
        return None

    # ---------- expressions ----------

    def _is_empty_literal(self, node: ast.expr) -> bool:
        return (isinstance(node, ast.List) and not node.elts) or \
               (isinstance(node, ast.Dict) and not node.keys)

    def _pyval_coercible(self, src: Type) -> bool:
        """Whether src implicitly coerces into a PyVal at annotated boundaries."""
        if isinstance(src, (TPyVal, TNone, TBool, TInt, TFloat, TStr, TBytes)):
            return True
        if isinstance(src, TList):
            return self._pyval_coercible(src.elem)
        if isinstance(src, TDict):
            return isinstance(src.key, (TStr, TInt, TFloat, TBool)) \
                and self._pyval_coercible(src.value)
        return False

    def _assignable(self, src: Type, dst: Type) -> bool:
        if src == dst:
            return True
        if isinstance(dst, TPyVal):
            return self._pyval_coercible(src)
        if isinstance(dst, TOptional):
            return isinstance(src, TNone) or self._assignable(src, dst.inner)
        if isinstance(dst, TUnion):
            return union_slot(src, dst) is not None
        if isinstance(dst, TList) and isinstance(src, TList):
            return self._assignable(src.elem, dst.elem)
        if isinstance(dst, TSet) and isinstance(src, TSet):
            return self._assignable(src.elem, dst.elem)
        if isinstance(dst, TDict) and isinstance(src, TDict):
            return self._assignable(src.key, dst.key) and self._assignable(src.value, dst.value)
        return False

    def _type_expr_place(self, node: ast.expr, narrow: dict[str, Type]) -> Type:
        return self._type_expr(node, narrow)

    def _lookup(self, name: str, node: ast.AST, narrow: dict[str, Type]) -> Type:
        if name in narrow:
            self.narrowed_uses.add(id(node))
            declared = self.env.get(name, (None, None))[0]
            if isinstance(declared, TUnion):
                slot = union_slot(narrow[name], declared)
                if slot is not None:
                    self.narrow_variant[id(node)] = slot
            return narrow[name]
        if name in self.env:
            return self.env[name][0]
        if (self.mod.name, name) in self.constants:
            return self.constants[(self.mod.name, name)]
        if name in self.mod.imports:
            tmod, orig = self.mod.imports[name]
            if (tmod, orig) in self.constants:
                return self.constants[(tmod, orig)]
        sig = self._resolve_callee(self.mod, name)
        if sig is not None:
            ft = self._func_value_type(sig, node)
            self.func_value_refs[id(node)] = (sig.module, sig.name)
            return ft
        self._err("SE214", "type-mismatch", f"unknown name '{name}'", node)
        raise AssertionError

    def _type_expr(self, node: ast.expr, narrow: dict[str, Type], expect: Type | None = None) -> Type:
        t = self._type_expr_inner(node, narrow, expect)
        self.expr_types[id(node)] = t
        return t

    def _type_expr_inner(self, node: ast.expr, narrow: dict[str, Type], expect: Type | None) -> Type:
        if isinstance(node, (ast.GeneratorExp, ast.NamedExpr,
                             ast.Await, ast.Yield, ast.YieldFrom, ast.Starred)):
            name, hint = UNSUPPORTED_EXPR_HINTS.get(type(node).__name__,
                                                    (type(node).__name__, ""))
            self._err("SE201", "unsupported-feature",
                      f"{name} is not supported by Serpentine", node, help=hint)
        if isinstance(node, ast.Set):
            return self._type_set_literal(node, narrow, expect)
        if isinstance(node, ast.Lambda):
            return self._type_lambda(node, narrow, expect)
        if isinstance(node, ast.Slice):
            self._err("SE201", "unsupported-feature",
                      "slices are only allowed directly inside a str subscript (s[a:b])", node)
        if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)):
            return self._type_comprehension(node, narrow)
        if isinstance(node, ast.Constant):
            return self._const_type(node)
        if isinstance(node, ast.Name):
            t = self._lookup(node.id, node, narrow)
            if isinstance(t, TOptional) and expect is not None and not isinstance(expect, TOptional):
                self._err("SE210", "unnarrowed-optional",
                          f"'{node.id}' is {t} here — test 'is not None' before using it as "
                          f"{t.inner}", node)
            if isinstance(t, TUnion) and expect is not None and not isinstance(expect, TUnion):
                self._err("SE210", "unnarrowed-union",
                          f"'{node.id}' is {t} here — test isinstance() before using it as "
                          f"{expect}", node)
            return t
        if isinstance(node, ast.JoinedStr):
            return self._type_fstring(node, narrow)
        if isinstance(node, ast.List):
            return self._type_list_literal(node, narrow, expect)
        if isinstance(node, ast.Dict):
            return self._type_dict_literal(node, narrow, expect)
        if isinstance(node, ast.Tuple):
            return TTuple(tuple(self._type_expr(e, narrow) for e in node.elts))
        if isinstance(node, ast.Subscript):
            return self._type_subscript(node, narrow)
        if isinstance(node, ast.UnaryOp):
            return self._type_unary(node, narrow)
        if isinstance(node, ast.BinOp):
            lt = self._type_expr(node.left, narrow)
            rt = self._type_expr(node.right, narrow)
            return self._binop_type(node.op, lt, rt, node, narrow)
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                vt = self._type_expr(v, narrow)
                if not isinstance(vt, TBool):
                    self._err("SE214", "type-mismatch",
                              f"'and'/'or' operands must be bool, got {vt}", v)
            return BOOL
        if isinstance(node, ast.Compare):
            return self._type_compare(node, narrow)
        if isinstance(node, ast.IfExp):
            ct = self._type_expr(node.test, narrow)
            if not isinstance(ct, TBool):
                self._err("SE214", "type-mismatch", f"ternary condition must be bool, got {ct}", node.test)
            bt = self._type_expr(node.body, narrow)
            et = self._type_expr(node.orelse, narrow)
            if self._assignable(et, bt):
                return bt
            if self._assignable(bt, et):
                return et
            self._err("SE214", "type-mismatch", f"ternary branches disagree: {bt} vs {et}", node)
        if isinstance(node, ast.Call):
            return self._type_call(node, narrow, expect)
        if isinstance(node, ast.Attribute):
            return self._type_attribute(node, narrow)
        name, hint = UNSUPPORTED_EXPR_HINTS.get(type(node).__name__,
                                                (f"the '{type(node).__name__}' expression", ""))
        self._err("SE201", "unsupported-feature",
                  f"{name} is not supported by Serpentine", node, help=hint)
        raise AssertionError

    def _field_type(self, cls_t: TClass, attr: str, node: ast.AST) -> Type:
        """The (substituted) type of a field on a class instance."""
        info = self.classes.get((cls_t.module, cls_t.name))
        if info is None or attr not in info.fields:
            self._err("SE214", "type-mismatch",
                      f"{cls_t} has no field '{attr}'", node)
            raise AssertionError
        ft = info.fields[attr]
        if info.typevars:
            if len(cls_t.args) != len(info.typevars):
                self._err("SE214", "type-mismatch",
                          f"generic class {cls_t.name} used without its type arguments", node)
            sub = dict(zip(info.typevars, cls_t.args))
            ft = subst_type(ft, sub)
        return ft

    def _type_attribute(self, node: ast.Attribute, narrow: dict[str, Type]) -> Type:
        if isinstance(node.value, ast.Name) and node.value.id == "sys" and self.mod.imports_sys:
            if node.attr == "argv":
                return TList(STR)
            self._err("SE201", "unsupported-feature",
                      f"'sys.{node.attr}' is not Tier 1 (only sys.argv and sys.exit)", node)
        if isinstance(node.value, ast.Name):
            key = f"{node.value.id}.{node.attr}"
            base_env = self.env.get(node.value.id, (None, None))[0]
            if key in narrow and isinstance(base_env, TClass):
                self.narrowed_uses.add(id(node))
                declared = self._field_type(base_env, node.attr, node)
                if isinstance(declared, TUnion):
                    slot = union_slot(narrow[key], declared)
                    if slot is not None:
                        self.narrow_variant[id(node)] = slot
                self._type_expr(node.value, narrow)
                return narrow[key]
        if isinstance(node.value, ast.Name) and node.value.id not in self.env:
            einfo = self._resolve_enum(self.mod, node.value.id)
            if einfo is not None:
                if node.attr not in dict(einfo.members):
                    self._err("SE214", "type-mismatch",
                              f"enum '{einfo.name}' has no member '{node.attr}'", node)
                self.enum_members[id(node)] = (einfo.module, einfo.name, node.attr)
                return TEnum(einfo.module, einfo.name)
        base = self._type_expr(node.value, narrow)
        if isinstance(base, TThread):
            if node.attr == "name":
                return STR
            if node.attr == "ident":
                return TOptional(INT)
            if node.attr == "daemon":
                return BOOL
            self._err("SE214", "type-mismatch",
                      f"Thread has no attribute '{node.attr}' — name/ident/daemon", node)
        if isinstance(base, TEnum):
            einfo = self.enums[(base.module, base.name)]
            if node.attr == "value":
                return einfo.value_type
            if node.attr == "name":
                return STR
            self._err("SE214", "type-mismatch",
                      f"enum value {base} has only '.value' and '.name'", node)
        if isinstance(base, TOptional):
            self._err("SE210", "unnarrowed-optional",
                      "attribute access on an optional — test 'is not None' first", node)
        if isinstance(base, TUnion):
            self._err("SE210", "unnarrowed-union",
                      f"attribute access on {base} — narrow with isinstance() first", node)
        cls_t = base.inner if isinstance(base, TShared) else base
        if isinstance(cls_t, TClass):
            info = self.classes.get((cls_t.module, cls_t.name))
            if info is not None and node.attr in info.properties:
                t = self._op_method_call(node, node.value, node.attr, [], narrow)
                if t is not None:
                    return t
            return self._field_type(cls_t, node.attr, node)
        self._err("SE214", "type-mismatch", f"{base} has no attribute '{node.attr}'", node)
        raise AssertionError

    def _const_type(self, node: ast.Constant) -> Type:
        v = node.value
        if isinstance(v, bool):
            return BOOL
        if isinstance(v, int):
            return INT
        if isinstance(v, float):
            return FLOAT
        if isinstance(v, str):
            return STR
        if isinstance(v, bytes):
            return TBytes()
        if v is None:
            return NONE
        self._err("SE201", "unsupported-feature", f"literal {v!r} is not Tier 0", node)
        raise AssertionError

    def _contains_func(self, t: Type, _seen: frozenset = frozenset()) -> bool:
        """Whether a type transitively contains a function value (no repr/eq parity)."""
        for w in self._walk(t):
            if isinstance(w, TFunc):
                return True
            if isinstance(w, TClass):
                key = (w.module, w.name)
                if key in _seen:
                    continue
                info = self.classes.get(key)
                if info is not None:
                    sub = dict(zip(info.typevars, w.args)) if info.typevars else {}
                    for ft in info.fields.values():
                        if self._contains_func(subst_type(ft, sub), _seen | {key}):
                            return True
        return False

    def _type_fstring(self, node: ast.JoinedStr, narrow: dict[str, Type]) -> Type:
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                t = self._type_expr(part.value, narrow)
                if isinstance(t, (TIter, TIterObj, TFile, TJoin, TThread)) or self._contains_func(t):
                    self._err("SE214", "type-mismatch", f"cannot format a {t}", part.value)
                if part.conversion in (-1, 115):
                    t0 = t.inner if isinstance(t, TShared) else t
                    if isinstance(t0, TClass):
                        info0 = self.classes.get((t0.module, t0.name))
                        if info0 is not None and "__str__" in info0.methods:
                            recv_copy = copy.copy(part.value)
                            self.expr_types[id(recv_copy)] = t
                            r = self._op_method_call(part.value, recv_copy, "__str__",
                                                     [], narrow, require=STR)
                            if r is not None:
                                self.expr_types[id(part.value)] = STR
                if part.format_spec is not None:
                    self._check_format_spec(part, self._t_of(part.value, t))
        return STR

    def _t_of(self, node: ast.expr, fallback: Type) -> Type:
        """The recorded type of a node after any desugaring, else the given fallback."""
        return self.expr_types.get(id(node), fallback)

    def _check_format_spec(self, part: ast.FormattedValue, t: Type) -> None:
        """Reject f-string format specs CPython would refuse or the runtime does not implement."""
        fs = part.format_spec
        assert isinstance(fs, ast.JoinedStr)
        if any(not isinstance(c, ast.Constant) for c in fs.values):
            self._err("SE201", "unsupported-feature",
                      "format specs must be literal text (no nested {...} fields); compute "
                      "the width first and use str.rjust/ljust/center instead", part)
            return
        spec = "".join(str(c.value) for c in fs.values)
        if spec == "":
            return
        if part.conversion == 97:
            self._err("SE201", "unsupported-feature", "the !a conversion is not supported; "
                      "use !r", part)
            return
        if part.conversion in (114, 115) or isinstance(t, TStr):
            sample: object = ""
            kind = "str"
        elif isinstance(t, (TInt, TBool)):
            sample, kind = 0, "int"
        elif isinstance(t, TFloat):
            sample, kind = 0.0, "float"
        else:
            self._err("SE214", "type-mismatch",
                      f"format spec '{spec}' applied to {t}: CPython only formats int, float, "
                      f"bool and str with a spec (others raise TypeError)",
                      part.value, help="convert first, e.g. f\"{str(x):>10}\" or f\"{x!s:>10}\"")
            return
        try:
            format(sample, spec)
        except (ValueError, TypeError) as exc:
            self._err("SE214", "type-mismatch",
                      f"invalid format spec '{spec}' for {kind}: {exc}", part)
            return
        m = re.fullmatch(r"(?:.?[<>=^])?[-+ ]?(z)?(#)?(0)?\d*([,_])?(?:\.\d+)?([a-zA-Z%])?", spec,
                         re.S)
        bad = None
        if m is None:
            bad = "this format spec"
        elif m.group(1):
            bad = "the 'z' (negative-zero) flag"
        elif m.group(3) and m.group(4):
            bad = "zero-padding combined with a thousands separator"
        elif m.group(2) and kind != "int":
            bad = "the '#' alternate form for float/str"
        elif m.group(2) and (m.group(5) or "") in ("e", "E", "f", "F", "g", "G", "%"):
            bad = "the '#' alternate form for float presentation types"
        if bad is not None:
            self._err("SE201", "unsupported-feature",
                      f"{bad} is not supported in native builds (format spec '{spec}')", part)

    def _type_list_literal(self, node: ast.List, narrow: dict[str, Type], expect: Type | None) -> Type:
        expect = _expect_member(expect, TList)
        if not node.elts:
            if isinstance(expect, TList):
                return expect
            if isinstance(expect, TPyVal):
                return TList(TPyVal())
            return TList(NONE)
        elem_expect = expect.elem if isinstance(expect, TList) else None
        if isinstance(expect, TPyVal):
            elem_expect = TPyVal()
        if elem_expect is not None:
            for e in node.elts:
                t = self._type_expr(e, narrow, expect=elem_expect)
                if not self._assignable(t, elem_expect):
                    self._err("SE214", "type-mismatch",
                              f"list element is {t}, expected {elem_expect}", e)
        else:
            first = self._type_expr(node.elts[0], narrow)
            for e in node.elts[1:]:
                t = self._type_expr(e, narrow)
                if not self._assignable(t, first) and not self._assignable(first, t):
                    self._err("SE214", "type-mismatch", f"list elements disagree: {first} vs {t}", e)
        for e in node.elts:
            elem_t = elem_expect if elem_expect is not None else self.expr_types.get(id(node.elts[0]))
            if isinstance(e, ast.Name) and elem_t is not None and not elem_t.is_copy():
                self._err("SE003", "implicit-transfer",
                          f"list literal takes ownership of '{e.id}' — write 'move({e.id})'", e)
        return TList(elem_expect if elem_expect is not None else self.expr_types[id(node.elts[0])])

    def _type_set_literal(self, node: ast.Set, narrow: dict[str, Type],
                          expect: Type | None) -> Type:
        """Type a `{a, b, c}` set literal against an optional expected element type."""
        expect = _expect_member(expect, TSet)
        elem_expect = expect.elem if isinstance(expect, TSet) else None
        first: Type | None = None
        for e in node.elts:
            t = self._type_expr(e, narrow, expect=elem_expect)
            if elem_expect is not None:
                if not self._assignable(t, elem_expect):
                    self._err("SE214", "type-mismatch",
                              f"set element is {t}, expected {elem_expect}", e)
            elif first is None:
                first = t
            elif t != first:
                self._err("SE214", "type-mismatch", f"set elements disagree: {first} vs {t}", e)
        elem = elem_expect if elem_expect is not None else first
        assert elem is not None
        if not elem.is_copy() or isinstance(elem, (TFunc, TPyVal)):
            self._err("SE214", "type-mismatch", "set elements must be Copy types", node)
        return TSet(elem)

    def _type_dict_literal(self, node: ast.Dict, narrow: dict[str, Type], expect: Type | None) -> Type:
        expect = _expect_member(expect, TDict)
        if not node.keys:
            if isinstance(expect, TDict):
                return expect
            if isinstance(expect, TPyVal):
                return TDict(STR, TPyVal())
            return TDict(NONE, NONE)
        if isinstance(expect, TPyVal) or \
                (isinstance(expect, TDict) and isinstance(expect.value, TPyVal)):
            vexp: Type = TPyVal()
            kt0: Type | None = None
            for k, v in zip(node.keys, node.values):
                if k is None:
                    self._err("SE201", "unsupported-feature", "dict unpacking is not Tier 0", node)
                k2 = self._type_expr(k, narrow)
                if not isinstance(k2, (TStr, TInt, TFloat, TBool)):
                    self._err("SE214", "type-mismatch",
                              f"dynamic dict keys must be str, int, float or bool, got {k2}", k)
                if kt0 is None:
                    kt0 = k2
                elif k2 != kt0:
                    self._err("SE214", "type-mismatch",
                              f"dynamic dict keys must share one type, got {kt0} and {k2}", k)
                v2 = self._type_expr(v, narrow, expect=vexp)
                if not self._assignable(v2, vexp):
                    self._err("SE214", "type-mismatch",
                              f"dict value is {v2}, expected {vexp}", v)
            return TDict(kt0 if kt0 is not None else STR, vexp)
        if isinstance(expect, TDict):
            for k, v in zip(node.keys, node.values):
                if k is None:
                    self._err("SE201", "unsupported-feature", "dict unpacking is not Tier 0", node)
                k2 = self._type_expr(k, narrow, expect=expect.key)
                v2 = self._type_expr(v, narrow, expect=expect.value)
                if not self._assignable(k2, expect.key) or not self._assignable(v2, expect.value):
                    self._err("SE214", "type-mismatch",
                              f"dict entry is {k2}: {v2}, expected "
                              f"{expect.key}: {expect.value}", v)
            return expect
        kt = self._type_expr(node.keys[0], narrow)
        vt = self._type_expr(node.values[0], narrow)
        for k, v in zip(node.keys[1:], node.values[1:]):
            if k is None:
                self._err("SE201", "unsupported-feature", "dict unpacking is not Tier 0", node)
            k2 = self._type_expr(k, narrow)
            v2 = self._type_expr(v, narrow)
            if k2 != kt or not (self._assignable(v2, vt) or self._assignable(vt, v2)):
                self._err("SE214", "type-mismatch", "dict literal entries disagree in type", v)
        return TDict(kt, vt)

    def _type_subscript(self, node: ast.Subscript, narrow: dict[str, Type]) -> Type:
        base = self._type_expr(node.value, narrow)
        if isinstance(base, TShared):
            base = base.inner
        if isinstance(base, TStr):
            if isinstance(node.slice, ast.Slice):
                if node.slice.step is not None:
                    self._err("SE201", "unsupported-feature",
                              "str slicing with a step is not Tier 2 — use s[a:b]", node.slice)
                for bound in (node.slice.lower, node.slice.upper):
                    if bound is not None:
                        bt = self._type_expr(bound, narrow)
                        if not isinstance(bt, TInt):
                            self._err("SE214", "type-mismatch",
                                      f"str slice bounds must be int, got {bt}", bound)
                return STR
            it = self._type_expr(node.slice, narrow)
            if not isinstance(it, TInt):
                self._err("SE214", "type-mismatch", f"str index must be int, got {it}", node.slice)
            return STR
        if isinstance(base, (TBytes, TByteArray)):
            if isinstance(node.slice, ast.Slice):
                if node.slice.step is not None:
                    self._err("SE201", "unsupported-feature", "slice steps are not supported", node.slice)
                for part in (node.slice.lower, node.slice.upper):
                    if part is not None and not isinstance(self._type_expr(part, narrow), TInt):
                        self._err("SE214", "type-mismatch", "slice bounds must be int", part)
                return TBytes() if isinstance(base, TBytes) else TByteArray()
            idx0 = self._type_expr(node.slice, narrow)
            if not isinstance(idx0, TInt):
                self._err("SE214", "type-mismatch", f"{base} index must be int, got {idx0}", node.slice)
            return INT
        if isinstance(base, TPyVal):
            if isinstance(node.slice, ast.Slice):
                self._err("SE201", "unsupported-feature",
                          "PyVal values do not support slicing", node.slice)
            it0 = self._type_expr(node.slice, narrow)
            if not isinstance(it0, (TInt, TStr, TPyVal, TFloat, TBool)):
                self._err("SE214", "type-mismatch",
                          f"PyVal index must be int, str, float, bool or PyVal, got {it0}", node.slice)
            return TPyVal()
        if isinstance(base, TClass):
            if isinstance(node.slice, ast.Slice):
                t = self._op_method_call(node, node.value, "__getitem__",
                                         [self._slice_call(node.slice)], narrow)
                if t is not None:
                    return t
            elif isinstance(node.slice, ast.Tuple) and self._dunder_arity(base, "__getitem__") > 1:
                t = self._op_method_call(node, node.value, "__getitem__",
                                         [self._slice_call(e) if isinstance(e, ast.Slice) else e
                                          for e in node.slice.elts], narrow)
                if t is not None:
                    return t
            else:
                t = self._op_method_call(node, node.value, "__getitem__",
                                         [node.slice], narrow)
                if t is not None:
                    return t
        if isinstance(node.slice, ast.Slice) and not isinstance(base, TClass):
            self._err("SE201", "unsupported-feature",
                      "slicing is Tier-2 for str/bytes/bytearray only (s[a:b])", node.slice)
        idx = self._type_expr(node.slice, narrow) if not isinstance(node.slice, ast.Slice) \
            else NONE
        if isinstance(base, TList):
            if not isinstance(idx, TInt):
                self._err("SE214", "type-mismatch", f"list index must be int, got {idx}", node.slice)
            return base.elem
        if isinstance(base, TDict):
            if not self._assignable(idx, base.key):
                self._err("SE214", "type-mismatch", f"dict key must be {base.key}, got {idx}", node.slice)
            return base.value
        if isinstance(base, TTuple):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int) \
                    and not isinstance(node.slice.value, bool):
                i = node.slice.value
                if 0 <= i < len(base.items):
                    return base.items[i]
                self._err("SE214", "type-mismatch", f"tuple index {i} out of range", node.slice)
            self._err("SE201", "unsupported-feature", "tuple indices must be integer literals", node.slice)
        if isinstance(base, TOptional):
            self._err("SE210", "unnarrowed-optional",
                      "cannot index an optional — test 'is not None' first", node)
        if isinstance(base, TUnion):
            self._err("SE210", "unnarrowed-union",
                      f"cannot index {base} — narrow with isinstance() first", node)
        self._err("SE214", "type-mismatch", f"{base} is not subscriptable", node)
        raise AssertionError

    def _type_unary(self, node: ast.UnaryOp, narrow: dict[str, Type]) -> Type:
        t = self._type_expr(node.operand, narrow)
        if isinstance(node.op, ast.Not):
            if not isinstance(t, (TBool, TPyVal)):
                self._err("SE214", "type-mismatch", f"'not' operand must be bool, got {t}", node)
            return BOOL
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            t0 = t.inner if isinstance(t, TShared) else t
            if isinstance(node.op, ast.USub) and isinstance(t0, TClass):
                r = self._op_method_call(node, node.operand, "__neg__", [], narrow)
                if r is not None:
                    return r
            if isinstance(t, TBool):
                self._err("SE208", "bool-arithmetic", "bool in arithmetic position — write int(b)", node)
            if not isinstance(t, NUMERIC):
                self._err("SE214", "type-mismatch", f"unary +/- needs a number, got {t}", node)
            return t
        if isinstance(node.op, ast.Invert):
            t0 = t.inner if isinstance(t, TShared) else t
            if isinstance(t0, TClass):
                r = self._op_method_call(node, node.operand, "__invert__", [], narrow)
                if r is not None:
                    return r
            self._err("SE201", "unsupported-feature",
                      "'~' is only supported on classes defining __invert__()", node)
        self._err("SE201", "unsupported-feature", "unsupported unary operator", node)
        raise AssertionError

    def _dunder_arity(self, cls_t: Type, method: str) -> int:
        """Number of parameters after self on a class dunder (0 when absent) — D43 splats a
        tuple key only when the method declares more than one key parameter."""
        info = self.classes.get((cls_t.module, cls_t.name)) if isinstance(cls_t, TClass) else None
        if info is None or method not in info.methods:
            return 0
        return max(0, len(info.methods[method].params) - 1)

    def _slice_call(self, sl: ast.Slice) -> ast.Call:
        """`slice(lower, upper, step)` constructor call for an `x[a:b:c]` key (D43)."""
        args: list[ast.expr] = []
        for part in (sl.lower, sl.upper, sl.step):
            if part is None:
                c = ast.Constant(value=None)
                ast.copy_location(c, sl)
                args.append(c)
            else:
                args.append(part)
        call = ast.Call(func=ast.Name(id="slice", ctx=ast.Load()), args=args, keywords=[])
        ast.copy_location(call, sl)
        ast.copy_location(call.func, sl)
        ast.fix_missing_locations(call)
        return call

    def _op_method_call(self, node: ast.AST, recv: ast.expr, method: str,
                        arg_exprs: list, narrow: dict[str, Type],
                        require: Type | None = None) -> Type | None:
        """Desugar an operator onto its dunder method call (None when not applicable)."""
        rt = self.expr_types.get(id(recv))
        if rt is None:
            rt = self._type_expr(recv, narrow)
        inner = rt.inner if isinstance(rt, TShared) else rt
        if not isinstance(inner, TClass):
            return None
        info = self.classes.get((inner.module, inner.name))
        if info is None or method not in info.methods:
            return None
        call = ast.Call(func=ast.Attribute(value=recv, attr=method, ctx=ast.Load()),
                        args=list(arg_exprs), keywords=[])
        anchor = node if hasattr(node, "lineno") else recv
        ast.copy_location(call, anchor)
        ast.copy_location(call.func, anchor)
        ast.fix_missing_locations(call)
        t = self._type_method_call(call, narrow)
        ols = info.overloads.get(method)
        if ols and isinstance(t, TUnion) and len(arg_exprs) >= 1:
            argts = []
            for a in arg_exprs:
                at = self.expr_types.get(id(a))
                if at is None:
                    at = self._type_expr(a, narrow)
                argts.append(at)
            for osig in ols:
                if len(osig.params) == 1 + len(argts) and all(
                        self._assignable(at, p.typ) for at, p in zip(argts, osig.params[1:])):
                    if osig.ret != t and osig.ret in t.members:
                        call._narrow = (t, osig.ret)
                        t = osig.ret
                    break
        self.expr_types[id(call)] = t
        self.op_calls[id(node)] = call
        if require is not None and t != require:
            self._err("SE214", "type-mismatch",
                      f".{method}() must return {require}, got {t}", anchor)
        return t

    def _binop_type(self, op: ast.operator, lt: Type, rt: Type, node: ast.AST,
                    narrow: dict[str, Type] | None = None) -> Type:
        linner = lt.inner if isinstance(lt, TShared) else lt
        if isinstance(linner, TClass):
            dunder = BINOP_DUNDER.get(type(op))
            if isinstance(node, ast.AugAssign):
                self._err("SE201", "unsupported-feature",
                          "augmented assignment on class operands — write x = x + y", node)
            elif dunder is not None and isinstance(node, ast.BinOp):
                t = self._op_method_call(node, node.left, dunder,
                                         [node.right], narrow or {})
                if t is not None:
                    return t
                self._err("SE214", "type-mismatch",
                          f"unsupported operand types: {lt} and {rt} — define "
                          f"{dunder}() on {linner} to overload this operator", node)
            else:
                self._err("SE214", "type-mismatch",
                          f"unsupported operand types: {lt} and {rt}", node)
        rinner = rt.inner if isinstance(rt, TShared) else rt
        if isinstance(rinner, TClass) and isinstance(node, ast.BinOp):
            rdunder = RBINOP_DUNDER.get(type(op))
            if rdunder is not None:
                t = self._op_method_call(node, node.right, rdunder, [node.left], narrow or {})
                if t is not None:
                    return t
            self._err("SE214", "type-mismatch",
                      f"unsupported operand types: {lt} and {rt} — define "
                      f"{rdunder or 'the reflected dunder'}() on {rinner} to overload this operator", node)
        for t, operand in ((lt, "left"), (rt, "right")):
            if isinstance(t, TBool):
                self._err("SE208", "bool-arithmetic",
                          f"bool in arithmetic position ({operand} operand) — write int(b)", node)
            if isinstance(t, TOptional):
                self._err("SE210", "unnarrowed-optional",
                          "optional value in arithmetic — test 'is not None' first", node)
            if isinstance(t, TUnion):
                self._err("SE210", "unnarrowed-union",
                          f"{t} value in arithmetic — narrow with isinstance() first", node)
        if isinstance(op, ast.Add) and isinstance(lt, TStr) and isinstance(rt, TStr):
            return STR
        if isinstance(op, ast.Add) and isinstance(lt, TBytes) and isinstance(rt, TBytes):
            return TBytes()
        if isinstance(op, ast.Mult) and (
                (isinstance(lt, TBytes) and isinstance(rt, TInt))
                or (isinstance(lt, TInt) and isinstance(rt, TBytes))):
            return TBytes()
        if isinstance(op, (ast.BitOr, ast.BitAnd, ast.BitXor, ast.LShift, ast.RShift,
                           ast.MatMult)):
            self._err("SE201", "unsupported-feature", "bitwise operators are not Tier 0", node)
        if not isinstance(lt, NUMERIC) or not isinstance(rt, NUMERIC):
            self._err("SE214", "type-mismatch", f"unsupported operand types: {lt} and {rt}", node)
        if isinstance(op, ast.Div):
            return FLOAT
        if isinstance(lt, TFloat) or isinstance(rt, TFloat):
            return FLOAT
        return INT

    def _type_compare(self, node: ast.Compare, narrow: dict[str, Type]) -> Type:
        ops = node.ops
        if any(isinstance(o, (ast.Is, ast.IsNot)) for o in ops):
            if len(ops) != 1 or not isinstance(node.comparators[0], ast.Constant) \
                    or node.comparators[0].value is not None:
                self._err("SE207", "identity-comparison",
                          "'is' comparisons are only allowed against None", node)
            place_ok = isinstance(node.left, ast.Name) or \
                (isinstance(node.left, ast.Attribute) and isinstance(node.left.value, ast.Name))
            if not place_ok:
                self._err("SE210", "unnarrowed-optional",
                          "narrowing applies to names and one-level fields only — bind "
                          "the value first (v = d.get(k))", node.left)
            probe = dict(narrow)
            if isinstance(node.left, ast.Attribute) and isinstance(node.left.value, ast.Name):
                probe.pop(f"{node.left.value.id}.{node.left.attr}", None)
            self._type_expr(node.left, probe)
            return BOOL
        if any(isinstance(o, (ast.In, ast.NotIn)) for o in ops):
            if len(ops) != 1:
                self._err("SE201", "unsupported-feature", "chained 'in' is not Tier 0", node)
            lt = self._type_expr(node.left, narrow)
            ct = self._type_expr(node.comparators[0], narrow)
            if isinstance(lt, TFunc):
                self._err("SE214", "type-mismatch",
                          "function values cannot be compared, so 'in' is not supported", node)
            if isinstance(ct, TPyVal):
                if not (isinstance(lt, TPyVal) or self._pyval_coercible(lt)):
                    self._err("SE214", "type-mismatch",
                              f"'in' on PyVal needs a PyVal-compatible operand, got {lt}", node)
            elif isinstance(ct, TDict):
                if not self._assignable(lt, ct.key):
                    self._err("SE214", "type-mismatch", f"'in' key must be {ct.key}, got {lt}", node)
            elif isinstance(ct, TList):
                if not ct.elem.is_copy() or not self._assignable(lt, ct.elem):
                    self._err("SE214", "type-mismatch", f"'in' needs a Copy element match on {ct}", node)
            elif isinstance(ct, TSet):
                if not self._assignable(lt, ct.elem):
                    self._err("SE214", "type-mismatch",
                              f"'in' element must be {ct.elem}, got {lt}", node)
            elif isinstance(ct, TStr):
                if not isinstance(lt, TStr):
                    self._err("SE214", "type-mismatch", "'in' on str needs a str operand", node)
            elif isinstance(ct, TBytes):
                if not isinstance(lt, TBytes):
                    self._err("SE214", "type-mismatch",
                              "'in' on bytes needs a bytes operand", node)
            else:
                self._err("SE214", "type-mismatch", f"'in' is not supported on {ct}", node)
            return BOOL
        prev = self._type_expr(node.left, narrow)
        if len(ops) == 1 and (type(ops[0]) in CMP_DUNDER or type(ops[0]) in EQ_DUNDER):
            l0 = prev.inner if isinstance(prev, TShared) else prev
            if isinstance(l0, TClass):
                dunder = CMP_DUNDER.get(type(ops[0])) or EQ_DUNDER[type(ops[0])]
                r = self._op_method_call(node, node.left, dunder,
                                         [node.comparators[0]], narrow)
                if r is not None:
                    return r
        for op, comp in zip(ops, node.comparators):
            cur = self._type_expr(comp, narrow)
            self._check_comparable(op, prev, cur, node, narrow)
            prev = cur
        return BOOL

    def _check_comparable(self, op: ast.cmpop, lt: Type, rt: Type, node: ast.AST,
                          narrow: dict[str, Type] | None = None) -> None:
        if isinstance(lt, (TWeak, TFile, TExc, TFunc, TJoin, TThread)) or isinstance(rt, (TWeak, TFile, TExc, TFunc, TJoin, TThread)):
            self._err("SE214", "type-mismatch", f"cannot compare {lt} and {rt}", node)
        if isinstance(lt, TPyVal) or isinstance(rt, TPyVal):
            other = rt if isinstance(lt, TPyVal) else lt
            if isinstance(op, (ast.Eq, ast.NotEq)) and self._pyval_coercible(other):
                return
            self._err("SE214", "type-mismatch",
                      f"PyVal supports only ==/!= against PyVal-compatible values "
                      f"({lt} vs {rt})", node)
        l0 = lt.inner if isinstance(lt, TShared) else lt
        if isinstance(l0, TClass) and type(op) in CMP_DUNDER and isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                self._err("SE201", "unsupported-feature",
                          "chained comparisons on class operands are not supported", node)
            r = self._op_method_call(node, node.left, CMP_DUNDER[type(op)],
                                     [node.comparators[0]], narrow or {}, require=BOOL)
            if r is not None:
                return
            self._err("SE214", "type-mismatch",
                      f"{l0} does not define {CMP_DUNDER[type(op)]}() — ordering "
                      f"comparisons need the dunder method", node)
        if isinstance(lt, TEnum) or isinstance(rt, TEnum):
            if lt != rt or not isinstance(op, (ast.Eq, ast.NotEq)):
                self._err("SE214", "type-mismatch",
                          f"enum values support only ==/!= against the same enum "
                          f"({lt} vs {rt}) — compare '.value' for ordering", node)
            return
        if isinstance(lt, TClass) or isinstance(rt, TClass):
            if lt != rt or not isinstance(op, (ast.Eq, ast.NotEq)) or self._contains_func(lt):
                self._err("SE214", "type-mismatch",
                          f"class instances support only ==/!= against the same class "
                          f"({lt} vs {rt})", node)
            return
        if isinstance(lt, TUnion) or isinstance(rt, TUnion):
            if lt == rt and isinstance(op, (ast.Eq, ast.NotEq)):
                return
            self._err("SE210", "unnarrowed-union",
                      f"cannot compare {lt} and {rt} — narrow with isinstance() first "
                      f"(==/!= is allowed between identical unions)", node)
        if isinstance(lt, TOptional) or isinstance(rt, TOptional):
            if isinstance(op, (ast.Eq, ast.NotEq)) and (lt.is_copy() and rt.is_copy()):
                return
            self._err("SE210", "unnarrowed-optional",
                      "optional value in comparison — test 'is not None' first", node)
        if isinstance(lt, NUMERIC) and isinstance(rt, NUMERIC):
            return
        if type(lt) is type(rt) and (lt.is_copy() or isinstance(op, (ast.Eq, ast.NotEq))):
            return
        if type(lt) is type(rt):
            return
        self._err("SE214", "type-mismatch", f"cannot compare {lt} and {rt}", node)

    # ---------- calls ----------

    def _type_lambda(self, node: ast.Lambda, narrow: dict[str, Type],
                     expect: Type | None) -> Type:
        """Type a general lambda against an expected Callable type (Tier 2)."""
        if not isinstance(expect, TFunc):
            self._err("SE201", "unsupported-feature",
                      "a lambda needs an expected Callable[...] type here — annotate the "
                      "target or parameter it is assigned to", node)
            raise AssertionError
        la = node.args
        if la.posonlyargs or la.kwonlyargs or la.vararg or la.kwarg or la.defaults:
            self._err("SE201", "unsupported-feature",
                      "lambdas take plain positional parameters only", node)
        if len(la.args) != len(expect.params):
            self._err("SE214", "type-mismatch",
                      f"lambda takes {len(la.args)} parameters but {expect} expects "
                      f"{len(expect.params)}", node)
        caps = self._lambda_captures(node)
        noncopy = {name for name, t in caps if not t.is_copy()}
        saved: dict[str, tuple | None] = {}
        for a, pt in zip(la.args, expect.params):
            if a.annotation is not None:
                self._err("SE201", "unsupported-feature",
                          "lambda parameters take no annotations (types come from the "
                          "expected Callable)", node)
            saved[a.arg] = self.env.get(a.arg)
            self.env[a.arg] = (pt, "local")
        inner_narrow = {k: v for k, v in narrow.items()
                        if k.split(".")[0] not in saved}
        self.lambda_caps_active.append(noncopy)
        bt = self._type_expr(node.body, inner_narrow, expect=expect.ret)
        self.lambda_caps_active.pop()
        for a in la.args:
            if saved[a.arg] is None:
                self.env.pop(a.arg, None)
            else:
                self.env[a.arg] = saved[a.arg]
        if not self._assignable(bt, expect.ret):
            self._err("SE214", "type-mismatch",
                      f"lambda body returns {bt} but {expect} expects {expect.ret}",
                      node.body)
        for name, _t in caps:
            self.captured_frozen.add(name)
        self.frozen_noncopy |= noncopy
        self.lambda_caps[id(node)] = caps
        return expect

    def _lambda_captures(self, node: ast.Lambda) -> list[tuple[str, Type]]:
        """Collect the enclosing locals a lambda reads (Copy-only, by value)."""
        bound: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Lambda):
                bound |= {a.arg for a in n.args.args}
            elif isinstance(n, (ast.ListComp, ast.DictComp)):
                for gen in n.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            bound.add(t.id)
        caps: dict[str, Type] = {}
        for n in ast.walk(node.body):
            if not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)):
                continue
            if n.id in bound or n.id in caps or n.id not in self.env:
                continue
            t = self.env[n.id][0]
            if not t.is_copy() and self.loop_depth > 0:
                self._err("SE005", "move-while-borrowed",
                          f"lambda inside a loop captures non-Copy '{n.id}' ({t}) — the "
                          f"capture is a copy, and a later iteration could change the "
                          f"original before the closure runs; build the closure outside the "
                          f"loop or capture Copy values", n)
            if n.id in self.loop_assigned:
                self._err("SE005", "move-while-borrowed",
                          f"lambda captures '{n.id}', which is assigned inside a loop — "
                          f"by-value capture would diverge from CPython's late binding; "
                          f"pass it through a factory function instead", n)
            caps[n.id] = t
        return sorted(caps.items())

    def _func_value_type(self, sig: FuncSig, node: ast.AST) -> Type:
        """The Callable type of a module function used as a first-class value."""
        if sig.is_template:
            self._err("SE201", "unsupported-feature",
                      f"generic function '{sig.name}' cannot be used as a value — "
                      f"first-class functions must be concrete", node)
        if sig.cls is not None:
            self._err("SE201", "unsupported-feature",
                      f"method '{sig.name}' cannot be used as a value", node)
        if any(p.default is not None for p in sig.params):
            self._err("SE201", "unsupported-feature",
                      f"function '{sig.name}' has default parameters and cannot be used "
                      f"as a value", node)
        if any(p.conv in (CONV_REF, CONV_MUT) for p in sig.params):
            self._err("SE201", "unsupported-feature",
                      f"function '{sig.name}' takes Ref/Mut parameters and cannot be used "
                      f"as a value — first-class calls pass arguments by value", node)
        return TFunc(tuple(p.typ for p in sig.params), sig.ret)

    def _type_func_value_call(self, node: ast.Call, ft: TFunc,
                              narrow: dict[str, Type]) -> Type:
        """Type a call through a first-class function value."""
        self._type_expr(node.func, narrow)
        if node.keywords:
            self._err("SE201", "unsupported-feature",
                      "calls through function values take positional arguments only", node)
        if len(node.args) != len(ft.params):
            self._err("SE214", "type-mismatch",
                      f"{ft} takes {len(ft.params)} arguments, got {len(node.args)}", node)
        for a, pt in zip(node.args, ft.params):
            at = self._type_expr(a, narrow, expect=pt)
            if not self._assignable(at, pt):
                self._err("SE214", "type-mismatch",
                          f"argument expects {pt}, got {at}", a)
            if not pt.is_copy():
                if not (isinstance(a, ast.Call) and id(a) in self.move_calls):
                    if isinstance(a, (ast.Name, ast.Subscript, ast.Attribute)):
                        self._require_move_for_owned(a, f"non-Copy parameter ({pt})")
        return ft.ret

    def _type_call(self, node: ast.Call, narrow: dict[str, Type], expect: Type | None) -> Type:
        is_sorted = isinstance(node.func, ast.Name) and node.func.id == "sorted"
        if node.keywords and not is_sorted and not isinstance(node.func, ast.Attribute):
            kw_ok = (isinstance(node.func, ast.Name)
                     and node.func.id not in self.env
                     and (self._resolve_callee(self.mod, node.func.id) is not None
                          or self._resolve_class(self.mod, node.func.id) is not None
                          or (node.func.id in ("Thread", "Timer")
                              and self._shim_name(node.func.id) == node.func.id)))
            if not kw_ok:
                self._err("SE201", "unsupported-feature",
                          "keyword arguments are only supported on user-defined "
                          "functions and methods", node)
        if isinstance(node.func, ast.Attribute):
            return self._type_method_call(node, narrow)
        if not isinstance(node.func, ast.Name):
            ft = self._type_expr(node.func, narrow)
            if isinstance(ft, TFunc):
                return self._type_func_value_call(node, ft, narrow)
            self._err("SE201", "unsupported-feature", "only named functions can be called", node)
        name = node.func.id
        vt = narrow.get(name) if isinstance(narrow.get(name), TFunc) else \
            (self.env[name][0] if name in self.env and
             isinstance(self.env[name][0], TFunc) else None)
        if vt is not None:
            return self._type_func_value_call(node, vt, narrow)
        if name == "move":
            return self._type_move(node, narrow)
        if name == "share":
            return self._type_share(node, narrow)
        if name == "downgrade":
            if len(node.args) != 1:
                self._err("SE214", "type-mismatch", "downgrade() takes exactly one argument", node)
            t = self._type_expr(node.args[0], narrow)
            if not isinstance(t, TShared):
                self._err("SE214", "type-mismatch",
                          f"downgrade() takes a Shared value, got {t}", node)
            return TWeak(t.inner)
        if name == "upgrade":
            if len(node.args) != 1:
                self._err("SE214", "type-mismatch", "upgrade() takes exactly one argument", node)
            t = self._type_expr(node.args[0], narrow)
            if not isinstance(t, TWeak):
                self._err("SE214", "type-mismatch", f"upgrade() takes a Weak value, got {t}", node)
            return TOptional(TShared(t.inner))
        if name == "isinstance":
            return self._type_isinstance(node, narrow)
        if name == "pyval_kind":
            if len(node.args) != 1:
                self._err("SE214", "type-mismatch", "pyval_kind() takes exactly one argument", node)
            t = self._type_expr(node.args[0], narrow, expect=TPyVal())
            if not isinstance(t, TPyVal):
                self._err("SE214", "type-mismatch", f"pyval_kind() takes a PyVal, got {t}", node)
            return STR
        if name == "pyval_json":
            if len(node.args) != 3:
                self._err("SE214", "type-mismatch",
                          "pyval_json() takes (PyVal, bool, bool)", node)
            t = self._type_expr(node.args[0], narrow, expect=TPyVal())
            if not isinstance(t, TPyVal):
                self._err("SE214", "type-mismatch", f"pyval_json() takes a PyVal, got {t}", node)
            for a in node.args[1:]:
                at = self._type_expr(a, narrow, expect=BOOL)
                if not isinstance(at, TBool):
                    self._err("SE214", "type-mismatch",
                              f"pyval_json() flags must be bool, got {at}", a)
            return STR
        if name in ("fields_of", "fields_json", "fields_build", "fields_set"):
            return self._type_fields_intrinsic(node, name, narrow)
        if name in ("hooks_json", "run_hook", "run_hook_self", "run_hook_get",
                    "run_hook_val", "run_hook_info"):
            return self._type_hook_intrinsic(node, name, narrow)
        if name == "spawn" and "spawn" in self.mod.shim_imports:
            return self._type_spawn(node, narrow)
        if name == "_serp_create_task":
            return self._type_spawn(node, narrow, task=True)
        if name in ("Thread", "Timer") and self._shim_name(name) == name:
            return self._type_thread_ctor(node, narrow, timer=(name == "Timer"))
        if name == "open":
            return self._type_open(node, narrow)
        if name in KNOWN_EXC or (name in self.user_exc and self._exc_ok(name)):
            self._err("SE201", "unsupported-feature",
                      f"exception values can only be created in a raise statement", node)
        cls = self._resolve_class(self.mod, name)
        if cls is not None:
            return self._type_ctor(node, cls, narrow)
        einfo = self._resolve_enum(self.mod, name) if name not in self.env else None
        if einfo is not None:
            if len(node.args) != 1 or node.keywords:
                self._err("SE214", "type-mismatch",
                          f"enum lookup '{einfo.name}(value)' takes exactly one argument", node)
            at = self._type_expr(node.args[0], narrow)
            if at != einfo.value_type:
                self._err("SE214", "type-mismatch",
                          f"enum '{einfo.name}' has {einfo.value_type} values, got {at}", node)
            self.enum_calls[id(node)] = (einfo.module, einfo.name)
            return TEnum(einfo.module, einfo.name)
        if name in self.mod.rtlib_imports:
            return self._type_rtlib_call(node, self.mod.rtlib_imports[name], narrow)
        sig = self._resolve_callee(self.mod, name)
        if sig is not None:
            return self._type_user_call(node, sig, narrow)
        if name in ("eval", "exec", "globals", "locals", "compile", "id",
                    "map", "filter", "any", "all", "type"):
            self._err("SE201", "unsupported-feature", f"'{name}' is not a Tier-0/1 builtin", node)
        return self._type_builtin_call(node, name, narrow, expect)

    def _type_rtlib_call(self, node: ast.Call, rf, narrow: dict[str, Type]) -> Type:
        """Type a call to a runtime-backed library function (rtlib.py)."""
        if len(node.args) != len(rf.params):
            self._err("SE214", "type-mismatch",
                      f"{rf.name}() takes {len(rf.params)} argument(s), "
                      f"got {len(node.args)}", node)
        for a, p in zip(node.args, rf.params):
            if p == "s":
                t = self._type_expr(a, narrow, expect=STR)
                if not isinstance(t, TStr):
                    self._err("SE214", "type-mismatch",
                              f"{rf.name}() expects a str, got {t}", a)
                continue
            if p == "y":
                t = self._type_expr(a, narrow, expect=TBytes())
                if not isinstance(t, TBytes):
                    self._err("SE214", "type-mismatch",
                              f"{rf.name}() expects bytes, got {t}", a)
                continue
            if p == "p":
                t = self._type_expr(a, narrow, expect=TPyVal())
                if not (isinstance(t, TPyVal) or self._pyval_coercible(t)):
                    self._err("SE214", "type-mismatch",
                              f"{rf.name}() expects a PyVal-compatible value, got {t}", a)
                continue
            t = self._type_expr(a, narrow, expect=FLOAT if p == "f" else INT)
            if p == "f" and (isinstance(t, TBool) or not isinstance(t, NUMERIC)):
                self._err("SE214", "type-mismatch",
                          f"{rf.name}() expects a number, got {t}", a)
            if p == "i" and (isinstance(t, TBool) or not isinstance(t, TInt)):
                self._err("SE214", "type-mismatch",
                          f"{rf.name}() expects an int, got {t}", a)
        return {"f": FLOAT, "i": INT, "b": BOOL, "n": NONE,
                "s": STR, "S": TList(STR), "y": TBytes(), "p": TPyVal()}[rf.ret]

    def _type_sorted(self, node: ast.Call, ts: list[Type], narrow: dict[str, Type]) -> Type:
        """Type sorted(xs) and sorted(xs, key=lambda v: ...) (Tier 2)."""
        args = node.args
        if len(args) != 1:
            self._err("SE214", "type-mismatch",
                      "sorted() takes exactly one positional argument", node)
        t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
        if not isinstance(t0, (TList, TSet)):
            self._err("SE214", "type-mismatch", f"sorted() takes a list or set, got {ts[0]}", node)
        elem = t0.elem
        key = None
        for kw in node.keywords:
            if kw.arg != "key":
                self._err("SE201", "unsupported-feature",
                          f"sorted() keyword '{kw.arg}' is not Tier 2 (only key=lambda)", node)
            key = kw.value
        if key is None:
            if not isinstance(elem, (TInt, TFloat, TStr)):
                self._err("SE214", "type-mismatch",
                          f"sorted() without a key needs int/float/str elements, got {t0}",
                          node)
            return TList(elem)
        if not elem.is_copy():
            self._err("SE211", "extend-non-copy",
                      f"sorted(key=...) on {t0} would bulk-copy non-Copy elements — "
                      f"sort a list of Copy keys instead", node)
        if not isinstance(key, ast.Lambda):
            self._err("SE201", "unsupported-feature",
                      "sorted() key must be an inline lambda in Tier 2", key)
        la = key.args
        if la.posonlyargs or la.kwonlyargs or la.vararg or la.kwarg or la.defaults \
                or len(la.args) != 1:
            self._err("SE201", "unsupported-feature",
                      "sorted() key lambda takes exactly one plain parameter", key)
        pname = la.args[0].arg
        saved = self.env.get(pname)
        self.env[pname] = (elem, "local")
        root = self._borrowable_root(args[0])
        self.comp_borrows.append(([root] if root else []) + [pname])
        body_narrow = dict(narrow)
        body_narrow.pop(pname, None)
        kt = self._type_expr(key.body, body_narrow)
        self.comp_borrows.pop()
        if saved is None:
            self.env.pop(pname, None)
        else:
            self.env[pname] = saved
        if not isinstance(kt, (TInt, TFloat, TStr)):
            self._err("SE214", "type-mismatch",
                      f"sorted() key must return int/float/str, got {kt}", key.body)
        self.lambda_elems[id(key)] = elem
        return TList(elem)

    def _comp_transfer_check(self, value: ast.expr, typ: Type) -> None:
        """Reject comprehensions that would copy a live non-Copy place out."""
        if typ.is_copy():
            return
        if isinstance(value, (ast.Name, ast.Attribute, ast.Subscript)):
            self._err("SE003", "implicit-transfer",
                      "a comprehension may only produce Copy values or freshly "
                      "constructed ones — this would silently copy a non-Copy value",
                      value)

    def _type_comprehension(self, node: ast.expr, narrow: dict[str, Type]) -> Type:
        """Type a list or dict comprehension (Tier 2: one for clause, one optional if)."""
        assert isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp))
        gens = node.generators
        if len(gens) != 1:
            self._err("SE201", "unsupported-feature",
                      "comprehensions take exactly one 'for' clause in Tier 2", node)
        gen = gens[0]
        if gen.is_async:
            self._err("SE201", "unsupported-feature", "async comprehensions are not supported", node)
        if len(gen.ifs) > 1:
            self._err("SE201", "unsupported-feature",
                      "comprehensions take at most one 'if' clause in Tier 2", node)
        iter_t = self._type_expr(gen.iter, narrow)
        kind = "list"
        elems: tuple[Type, ...]
        if isinstance(iter_t, TList):
            elems = (iter_t.elem,)
        elif isinstance(iter_t, TSet):
            kind = "set"
            elems = (iter_t.elem,)
        elif isinstance(iter_t, TStr):
            kind = "str"
            elems = (STR,)
        elif isinstance(iter_t, (TBytes, TByteArray)):
            kind = "bytes" if isinstance(iter_t, TBytes) else "bytearray"
            elems = (INT,)
        elif isinstance(iter_t, TIter):
            kind = iter_t.kind
            elems = iter_t.elem
        else:
            self._err("SE214", "type-mismatch", f"cannot iterate over {iter_t}", gen.iter)
            raise AssertionError
        self.loop_iter_kind[id(node)] = kind
        targets: list[ast.Name] = []
        if isinstance(gen.target, ast.Name):
            targets = [gen.target]
        elif isinstance(gen.target, ast.Tuple) and len(gen.target.elts) == 2 \
                and all(isinstance(e, ast.Name) for e in gen.target.elts):
            targets = list(gen.target.elts)  # type: ignore[arg-type]
        else:
            self._err("SE201", "unsupported-feature",
                      "comprehension target must be one or two names", gen.target)
        if len(targets) != len(elems):
            self._err("SE214", "type-mismatch",
                      f"comprehension target unpacks {len(targets)} names but iterator "
                      f"yields {len(elems)}", gen.target)
        saved: dict[str, tuple | None] = {}
        for tgt, et in zip(targets, elems):
            saved[tgt.id] = self.env.get(tgt.id)
            self.env[tgt.id] = (et, "local")
        root = self._borrowable_root(gen.iter)
        self.comp_borrows.append(([root] if root else []) + [t.id for t in targets])
        body_narrow = {k: v for k, v in narrow.items()
                       if k.split('.')[0] not in {t.id for t in targets}}
        if gen.ifs:
            ct = self._type_expr(gen.ifs[0], body_narrow)
            if not isinstance(ct, TBool):
                self._err("SE214", "type-mismatch",
                          f"comprehension condition must be bool, got {ct}", gen.ifs[0])
            body_narrow, _neg = self._narrow_from_test(gen.ifs[0], body_narrow)
        if isinstance(node, ast.DictComp):
            kt = self._type_expr(node.key, body_narrow)
            if not kt.is_copy():
                self._err("SE214", "type-mismatch", "dict keys must be Copy types", node.key)
            vt = self._type_expr(node.value, body_narrow)
            self._comp_transfer_check(node.value, vt)
            result: Type = TDict(kt, vt)
        elif isinstance(node, ast.SetComp):
            st = self._type_expr(node.elt, body_narrow)
            if not st.is_copy() or isinstance(st, (TFunc, TPyVal)):
                self._err("SE214", "type-mismatch", "set elements must be Copy types", node.elt)
            result = TSet(st)
        else:
            et2 = self._type_expr(node.elt, body_narrow)
            self._comp_transfer_check(node.elt, et2)
            result = TList(et2)
        self.comp_borrows.pop()
        for name, old in saved.items():
            if old is None:
                self.env.pop(name, None)
            else:
                self.env[name] = old
        return result

    def _resolve_class(self, mod: Module, name: str) -> ClassInfo | None:
        if name in ("cls", "Self") and self.cls_now is not None:
            return self.classes.get((self.cls_now.module, self.cls_now.name))
        if (mod.name, name) in self.classes:
            return self.classes[(mod.name, name)]
        if name in mod.imports:
            tmod, orig = mod.imports[name]
            return self.classes.get((tmod, orig))
        return None

    def _type_share(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        if len(node.args) != 1:
            self._err("SE214", "type-mismatch", "share() takes exactly one argument", node)
        arg = node.args[0]
        t = self._type_expr(arg, narrow)
        if isinstance(t, (TIter, TShared, TWeak)):
            self._err("SE214", "type-mismatch", f"cannot share a {t}", node)
        if not t.is_copy():
            if not (isinstance(arg, ast.Call) and id(arg) in self.move_calls):
                if isinstance(arg, (ast.Name, ast.Subscript, ast.Attribute)):
                    self._require_move_for_owned(arg, "share() (Owned argument)")
        return TShared(t)

    def _type_open(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        if len(node.args) not in (1, 2):
            self._err("SE214", "type-mismatch", "open() takes a path and an optional mode", node)
        for a in node.args:
            t = self._type_expr(a, narrow)
            if not isinstance(t, TStr):
                self._err("SE214", "type-mismatch", f"open() arguments must be str, got {t}", a)
        binary = False
        if len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
            if mode not in ("r", "w", "a", "rb", "wb", "ab"):
                self._err("SE201", "unsupported-feature",
                          f"open() mode {mode!r} is not supported — use 'r', 'w', 'a', "
                          f"'rb', 'wb' or 'ab'", node.args[1])
            binary = isinstance(mode, str) and mode.endswith("b")
        elif len(node.args) == 2:
            self._err("SE201", "unsupported-feature",
                      "open() mode must be a string literal (the file's text/binary type "
                      "is static)", node.args[1])
        return TFile(binary=binary)

    def _ctor_from_mapping(self, node: ast.Call, cls: ClassInfo,
                           narrow: dict[str, Type]) -> Type:
        """Lower `Model(**mapping)` to the class's synthesized field-build helper (LB8)."""
        if node.args or len(node.keywords) != 1:
            self._err("SE201", "unsupported-feature",
                      f"{cls.name}(**mapping) cannot be mixed with other arguments", node)
        if cls.typevars:
            self._err("SE201", "unsupported-feature",
                      f"{cls.name}(**mapping) needs a concrete non-generic class", node)
        data = node.keywords[0].value
        t = TClass(cls.module, cls.name)
        dt = self._type_expr(data, narrow, expect=TPyVal())
        if not isinstance(dt, TPyVal) and not self._pyval_coercible(dt):
            self._err("SE214", "type-mismatch",
                      f"{cls.name}(**mapping) takes a PyVal or dict[str, PyVal], "
                      f"got {dt}", node)
        self.fields_calls[id(node)] = t
        self._field_schema(t, node)
        helper = self._need_field_helper(t, "build", self.mod)
        node.func = ast.copy_location(ast.Name(id=helper, ctx=ast.Load()), node.func)
        node.args = [data]
        node.keywords = []
        self.call_targets[id(node)] = (t.module, helper)
        return t

    def _type_ctor(self, node: ast.Call, cls: ClassInfo, narrow: dict[str, Type]) -> Type:
        """Type a dataclass constructor call, inferring generic arguments."""
        if node.keywords:
            self._expand_literal_stars(node)
        if (cls.module, cls.name) in self.init_ctors \
                and not getattr(node, "serp_raw_ctor", False):
            return self._type_init_ctor(node, cls, narrow)
        if any(kw.arg is None for kw in node.keywords):
            return self._ctor_from_mapping(node, cls, narrow)
        if node.keywords:
            params = [Param(f, CONV_COPY, cls.fields[f], cls.field_defaults.get(f))
                      for f in cls.field_order]
            self._apply_keywords(node, params, f"{cls.name}()")
        if len(node.args) < len(cls.field_order):
            for fname in cls.field_order[len(node.args):]:
                d = cls.field_defaults.get(fname)
                if d is None:
                    break
                if isinstance(d, ast.Constant):
                    c: ast.expr = ast.Constant(value=d.value)
                else:
                    c = copy.deepcopy(d)
                ast.copy_location(c, node)
                node.args.append(c)
        if len(node.args) != len(cls.field_order):
            self._err("SE214", "type-mismatch",
                      f"{cls.name}() takes {len(cls.field_order)} arguments "
                      f"({', '.join(cls.field_order)}), got {len(node.args)}", node)
        sub: dict = {}
        for arg, fname in zip(node.args, cls.field_order):
            ft = cls.fields[fname]
            at = self._type_expr(arg, narrow,
                                 expect=None if has_tvar(ft) else ft)
            if not unify(ft, at, sub) and not self._assignable(at, subst_type(ft, sub)):
                self._err("SE214", "type-mismatch",
                          f"field '{fname}' of {cls.name} expects {subst_type(ft, sub)}, "
                          f"got {at}", arg)
            concrete_ft = subst_type(ft, sub)
            if not concrete_ft.is_copy():
                if not (isinstance(arg, ast.Call) and id(arg) in self.move_calls):
                    if isinstance(arg, (ast.Name, ast.Subscript, ast.Attribute)):
                        self._require_move_for_owned(arg, f"field '{fname}' of {cls.name}")
        args: tuple = ()
        if cls.typevars:
            missing = [tv for tv in cls.typevars if tv not in sub]
            if missing:
                self._err("SE214", "type-mismatch",
                          f"cannot infer type argument(s) {', '.join(missing)} for "
                          f"{cls.name} — annotate the target", node)
            args = tuple(sub[tv] for tv in cls.typevars)
        self._check_bounds(cls.module, sub, node)
        t = TClass(cls.module, cls.name, args)
        self.ctor_calls[id(node)] = (cls.module, cls.name, args)
        return t

    def _type_init_ctor(self, node: ast.Call, cls: ClassInfo,
                        narrow: dict[str, Type]) -> Type:
        """Type `C(...)` for a class with a user `__init__` as a call to its factory."""
        fname = self.init_ctors[(cls.module, cls.name)]
        if any(kw.arg is None for kw in node.keywords):
            self._err("SE201", "unsupported-feature",
                      f"'{cls.name}' defines __init__, so it cannot be built from a "
                      f"mapping — pass the constructor's arguments", node)
        if cls.module != self.mod.name:
            self.mod.imports.setdefault(fname, (cls.module, fname))
        node.func = ast.copy_location(ast.Name(id=fname, ctx=ast.Load()), node.func)
        return self._type_user_call(node, self.sigs[(cls.module, fname)], narrow)

    def _type_move(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        if len(node.args) != 1:
            self._err("SE214", "type-mismatch", "move() takes exactly one argument", node)
        arg = node.args[0]
        self.move_calls.add(id(node))
        if isinstance(arg, ast.Name):
            if any(arg.id in active for active in self.lambda_caps_active):
                self._err("SE004", "conflicting-borrow",
                          f"a lambda may not move its captured '{arg.id}' — it would be "
                          f"gone on the second call", node)
            if arg.id in self.frozen_noncopy:
                self._err("SE004", "conflicting-borrow",
                          f"'{arg.id}' was captured by a lambda — moving it afterwards would "
                          f"diverge from CPython (the closure would still see the object)", node)
        t = self._type_expr(arg, narrow)
        if t.is_copy():
            return t
        if isinstance(arg, ast.Subscript):
            self._err("SE006", "move-out-of-container",
                      "cannot move a non-Copy element out of a container — use pop(), "
                      "borrow in place, or overwrite", node)
        if isinstance(arg, ast.Attribute):
            if not isinstance(arg.value, ast.Name):
                self._err("SE201", "unsupported-feature",
                          "only one level of field projection can be moved (move(x.f))", arg)
            root = arg.value.id
            root_t, conv = self.env.get(root, (None, None))
            if isinstance(root_t, TShared):
                self._err("SE006", "move-out-of-container",
                          "cannot move a field out of a Shared value — contents stay shared",
                          node)
            if conv in (CONV_REF, CONV_MUT):
                self._err("SE008", "move-out-of-borrow",
                          f"cannot move field '{arg.attr}' out of borrowed parameter "
                          f"'{root}' — that would leave the caller's value with a hole", node)
            for scope in self.loop_refs:
                if root in scope:
                    self._err("SE007", "move-loop-variable",
                              f"'{root}' is a per-iteration Ref loop variable and cannot be "
                              f"moved from", node)
            self.cur_facts.events.append(("move", f"{root}.{arg.attr}", node))
            return t
        if not isinstance(arg, ast.Name):
            self._err("SE214", "type-mismatch", "move() takes a variable or field place", arg)
        for scope in self.loop_refs:
            if arg.id in scope:
                self._err("SE007", "move-loop-variable",
                          f"'{arg.id}' is a per-iteration Ref loop variable and cannot be moved",
                          node)
        for scope in self.comp_borrows:
            if arg.id in scope:
                self._err("SE005", "move-while-borrowed",
                          f"'{arg.id}' is borrowed by an enclosing comprehension or key "
                          f"lambda and cannot be moved there", node)
        if arg.id in self.with_targets:
            self._err("SE005", "move-while-borrowed",
                      f"cannot move '{arg.id}' out of its 'with' block — the file closes "
                      f"at block end", node)
        if arg.id in self.ref_locals:
            self._err("SE008", "move-out-of-borrow",
                      f"cannot move '{arg.id}' — it is a scoped Ref borrow of an element "
                      f"of '{self.ref_locals[arg.id]}'", node)
        if self.elem_borrows.get(arg.id):
            names = ", ".join(f"'{n}'" for n in sorted(self.elem_borrows[arg.id]))
            self._err("SE005", "move-while-borrowed",
                      f"cannot move '{arg.id}' while element borrow {names} is live "
                      f"(the borrow ends at the end of its block)", node)
        conv = self.env.get(arg.id, (None, None))[1]
        if conv in (CONV_REF, CONV_MUT):
            self._err("SE008", "move-out-of-borrow",
                      f"cannot move borrowed parameter '{arg.id}' — the caller still owns it",
                      node)
        self.cur_facts.events.append(("move", arg.id, node))
        return t

    def _require_move_for_owned(self, arg: ast.expr, param_desc: str) -> None:
        """SE002 when a live named non-Copy value is passed to an Owned position."""
        if isinstance(arg, ast.Name):
            t = self.env.get(arg.id, (None, None))[0]
            if t is not None and not t.is_copy():
                self._err("SE002", "missing-move",
                          f"passing '{arg.id}' to {param_desc} transfers ownership",
                          arg, label="ownership leaves this variable here",
                          help=f"write 'move({arg.id})' to make the transfer explicit")
        if isinstance(arg, ast.Subscript):
            base_t = self.expr_types.get(id(arg))
            self._err("SE006", "move-out-of-container",
                      "cannot move a non-Copy element out of a container here", arg)
        if isinstance(arg, ast.Attribute) and not self._is_sys_attr(arg):
            self._err("SE002", "missing-move",
                      f"passing field '{ast.unparse(arg)}' to {param_desc} transfers "
                      f"ownership — write 'move({ast.unparse(arg)})'", arg)

    def _borrow_root(self, e: ast.expr) -> str | None:
        while isinstance(e, (ast.Subscript, ast.Attribute)):
            if isinstance(e, ast.Attribute) and self._is_sys_attr(e):
                return None
            e = e.value
        if isinstance(e, ast.Name) and e.id in self.env:
            return e.id
        return None

    def _mut_root_check(self, root: str, node: ast.AST) -> None:
        """Reject mutation through a per-iteration Ref loop variable (matches rustc)."""
        for active in self.lambda_caps_active:
            if root in active:
                self._err("SE004", "conflicting-borrow",
                          f"a lambda may not mutate its captured non-Copy '{root}' — the "
                          f"capture is a copy, while CPython would mutate the shared object", node)
        if root in self.frozen_noncopy:
            self._err("SE004", "conflicting-borrow",
                      f"'{root}' was captured by a lambda — mutating it afterwards would "
                      f"diverge from CPython (the closure holds a copy, CPython shares it)", node)
        for scope in self.loop_refs:
            if root in scope:
                self._err("SE004", "conflicting-borrow",
                          f"'{root}' is a per-iteration Ref loop variable — it cannot be "
                          f"mutated through", node)
        for scope in self.comp_borrows:
            if root in scope:
                self._err("SE004", "conflicting-borrow",
                          f"'{root}' is borrowed by an enclosing comprehension or key "
                          f"lambda — it cannot be mutated there", node)
        if root in self.ref_locals:
            self._err("SE004", "conflicting-borrow",
                      f"'{root}' is a scoped element borrow of "
                      f"'{self.ref_locals[root]}' — it cannot be mutated through", node)
        if self.elem_borrows.get(root):
            names = ", ".join(f"'{n}'" for n in sorted(self.elem_borrows[root]))
            self._err("SE004", "conflicting-borrow",
                      f"'{root}' cannot be mutated while element borrow {names} is live "
                      f"(the borrow ends at the end of its block)", node)

    def _mut_borrow_place(self, e: ast.expr, node: ast.AST) -> None:
        root = self._borrow_root(e)
        if root is not None:
            self._mut_root_check(root, node)
            self.cur_facts.events.append(("mut_use", root, node))

    def _check_narrow_invalidation_by_mut(self, e: ast.expr, narrow: dict[str, Type]) -> None:
        root = self._borrow_root(e)
        if root is not None:
            narrow.pop(root, None)
            for k in [k for k in narrow if k.split(".")[0] == root]:
                narrow.pop(k, None)

    def _pad_container_defaults(self, node: ast.Call, params: list) -> None:
        """Materialize omitted trailing arguments when any of them defaults to an empty
        `[]`/`{}` literal (backends only render constant defaults themselves)."""
        rest = params[len(node.args):]
        if not any(isinstance(p.default, (ast.List, ast.Dict)) for p in rest):
            return
        for p in rest:
            if p.default is None:
                return
            c: ast.expr = ast.Constant(value=p.default.value) \
                if isinstance(p.default, ast.Constant) else copy.deepcopy(p.default)
            ast.copy_location(c, node)
            ast.fix_missing_locations(c)
            node.args.append(c)

    def _type_user_call(self, node: ast.Call, sig: FuncSig, narrow: dict[str, Type],
                        pre_sub: dict | None = None) -> Type:
        self._apply_keywords(node, sig.params, f"'{sig.name}'")
        self._pad_container_defaults(node, sig.params)
        required = len([p for p in sig.params if p.default is None])
        if not (required <= len(node.args) <= len(sig.params)):
            want = str(len(sig.params)) if required == len(sig.params) \
                else f"{required} to {len(sig.params)}"
            self._err("SE214", "type-mismatch",
                      f"'{sig.name}' takes {want} arguments, got {len(node.args)}", node)
        if sig.is_template:
            sub: dict = dict(pre_sub) if pre_sub else {}
            arg_ts: list = [None] * len(node.args)
            order = sorted(range(len(node.args)),
                           key=lambda i: isinstance(node.args[i], ast.Lambda))
            for i in order:
                arg = node.args[i]
                p = sig.params[i]
                if has_tvar(p.typ) and self._is_empty_literal(arg):
                    self._err("SE204", "unknown-element-type",
                              f"empty literal cannot infer type variable for parameter "
                              f"'{p.name}' — bind it to an annotated variable first", arg)
                pt = subst_type(p.typ, sub)
                at = self._type_expr(arg, narrow,
                                     expect=None if has_tvar(pt) else pt)
                arg_ts[i] = at
                if not unify(p.typ, at, sub) and not self._assignable(at, subst_type(p.typ, sub)):
                    self._err("SE214", "type-mismatch",
                              f"argument '{p.name}' expects {subst_type(p.typ, sub)}, got {at}",
                              arg)
            tvars = {t.name for p in sig.params for t in self._walk(p.typ)
                     if isinstance(t, TVar)}
            missing = [tv for tv in sorted(tvars) if tv not in sub]
            if missing:
                self._err("SE214", "type-mismatch",
                          f"cannot infer type argument(s) {', '.join(missing)} for "
                          f"'{sig.name}'", node)
            self._check_bounds(sig.module, sub, node)
            sig = self._instantiate(sig, sub, node)
            return self._finish_user_call(node, sig, narrow, pre_typed=arg_ts)
        return self._finish_user_call(node, sig, narrow, pre_typed=None)

    def _finish_user_call(self, node: ast.Call, sig: FuncSig, narrow: dict[str, Type],
                          pre_typed: list | None) -> Type:
        self.call_targets[id(node)] = (sig.module, sig.name)
        mut_roots: list[str] = []
        ref_roots: list[str] = []
        for i, (arg, p) in enumerate(zip(node.args, sig.params)):
            at = pre_typed[i] if pre_typed is not None else \
                self._type_expr(arg, narrow, expect=p.typ)
            if not self._assignable(at, p.typ) and not _int_widens(at, p.typ):
                self._err("SE214", "type-mismatch",
                          f"argument '{p.name}' expects {p.typ}, got {at}", arg)
            if p.conv == CONV_OWNED and not p.typ.is_copy():
                if not (isinstance(arg, ast.Call) and id(arg) in self.move_calls):
                    if isinstance(arg, (ast.Name, ast.Subscript, ast.Attribute)):
                        self._require_move_for_owned(arg, f"Owned parameter '{p.name}'")
            if p.conv == CONV_MUT:
                root = self._borrow_root(arg)
                if root is not None:
                    self._mut_root_check(root, node)
                    mut_roots.append(root)
                    self.cur_facts.events.append(("mut_use", root, node))
                    self._check_narrow_invalidation_by_mut(arg, narrow)
            if p.conv == CONV_REF:
                root = self._borrow_root(arg)
                if root is not None:
                    ref_roots.append(root)
        for m in mut_roots:
            if mut_roots.count(m) > 1 or m in ref_roots:
                self._err("SE004", "conflicting-borrow",
                          f"'{m}' is passed as Mut and borrowed again in the same call", node)
        return sig.ret

    def _type_builtin_call(self, node: ast.Call, name: str, narrow: dict[str, Type],
                           expect: Type | None = None) -> Type:
        args = node.args
        ts = [self._type_expr(a, narrow) for a in args]

        def arity(n: int) -> None:
            if len(args) != n:
                self._err("SE214", "type-mismatch", f"{name}() takes {n} argument(s)", node)

        if name == "print":
            for a, t in zip(args, ts):
                if isinstance(t, (TIter, TIterObj, TFile, TJoin)) or self._contains_func(t):
                    self._err("SE214", "type-mismatch", f"cannot print a {t}", node)
                t0 = t.inner if isinstance(t, TShared) else t
                if isinstance(t0, TClass):
                    info0 = self.classes.get((t0.module, t0.name))
                    if info0 is not None and "__str__" in info0.methods:
                        recv_copy = copy.copy(a)
                        self.expr_types[id(recv_copy)] = t
                        r = self._op_method_call(a, recv_copy, "__str__", [], narrow,
                                                 require=STR)
                        if r is not None:
                            self.expr_types[id(a)] = STR
            return NONE
        if name == "len":
            arity(1)
            t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
            if isinstance(t0, TClass):
                r = self._op_method_call(node, args[0], "__len__", [], narrow, require=INT)
                if r is not None:
                    return INT
            if not isinstance(t0, (TList, TDict, TSet, TStr, TBytes, TByteArray, TPyVal)):
                self._err("SE214", "type-mismatch", f"len() is not supported on {ts[0]}", node)
            return INT
        if name in ("set", "frozenset"):
            if len(args) == 0:
                exp = _expect_member(expect, TSet)
                if isinstance(exp, TSet):
                    return exp
                self._err("SE214", "type-mismatch",
                          "set() needs an annotated target so its element type is known", node)
            arity(1)
            t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
            if isinstance(t0, TSet):
                return t0
            if not isinstance(t0, TList):
                self._err("SE214", "type-mismatch", f"set() cannot convert {ts[0]}", node)
            if not t0.elem.is_copy() or isinstance(t0.elem, (TFunc, TPyVal)):
                self._err("SE214", "type-mismatch", "set elements must be Copy types", node)
            return TSet(t0.elem)
        if name == "range":
            if len(args) not in (1, 2, 3):
                self._err("SE214", "type-mismatch", "range() takes 1-3 arguments", node)
            for t in ts:
                if not isinstance(t, TInt):
                    self._err("SE214", "type-mismatch", "range() arguments must be int", node)
            return TIter("range", (INT,))
        if name == "enumerate":
            arity(1)
            if not isinstance(ts[0], TList):
                self._err("SE214", "type-mismatch", "enumerate() takes a list in Tier 0", node)
            return TIter("enumerate", (INT, ts[0].elem))
        if name == "zip":
            arity(2)
            if not (isinstance(ts[0], TList) and isinstance(ts[1], TList)):
                self._err("SE214", "type-mismatch", "zip() takes two lists in Tier 2", node)
            return TIter("zip", (ts[0].elem, ts[1].elem))
        if name == "reversed":
            arity(1)
            if not isinstance(ts[0], TList):
                self._err("SE214", "type-mismatch", "reversed() takes a list in Tier 2", node)
            return TIter("reversed", (ts[0].elem,))
        if name == "sum":
            arity(1)
            if isinstance(ts[0], TList) and isinstance(ts[0].elem, NUMERIC):
                return ts[0].elem
            if isinstance(ts[0], TList) and isinstance(ts[0].elem, TBool):
                self._err("SE208", "bool-arithmetic", "sum() over bools — convert with int(b)", node)
            self._err("SE214", "type-mismatch", f"sum() is not supported on {ts[0]}", node)
        if name in ("min", "max"):
            if len(args) == 1:
                if isinstance(ts[0], TList) and isinstance(ts[0].elem, (TInt, TFloat, TStr)):
                    return ts[0].elem
                self._err("SE214", "type-mismatch", f"{name}() is not supported on {ts[0]}", node)
            arity(2)
            if ts[0] != ts[1] or not isinstance(ts[0], (TInt, TFloat, TStr)):
                self._err("SE214", "type-mismatch", f"{name}() arguments must match", node)
            return ts[0]
        if name == "abs":
            arity(1)
            t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
            if isinstance(t0, TClass):
                r = self._op_method_call(node, args[0], "__abs__", [], narrow)
                if r is not None:
                    return r
            if isinstance(ts[0], TBool) or not isinstance(ts[0], NUMERIC):
                self._err("SE214", "type-mismatch", f"abs() needs a number, got {ts[0]}", node)
            return ts[0]
        if name == "str":
            arity(1)
            t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
            if isinstance(t0, TClass):
                r = self._op_method_call(node, args[0], "__str__", [], narrow, require=STR)
                if r is not None:
                    return STR
            return STR
        if name == "int":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TBool, TStr, TPyVal)):
                self._err("SE214", "type-mismatch", f"int() cannot convert {ts[0]}", node)
            return INT
        if name == "float":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TStr, TPyVal)):
                self._err("SE214", "type-mismatch", f"float() cannot convert {ts[0]}", node)
            return FLOAT
        if name == "bool":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TBool, TStr, TPyVal)):
                self._err("SE214", "type-mismatch", f"bool() cannot convert {ts[0]}", node)
            return BOOL
        if name == "round":
            if len(args) not in (1, 2):
                self._err("SE214", "type-mismatch", "round() takes 1 or 2 arguments", node)
            if isinstance(ts[0], TBool) or not isinstance(ts[0], NUMERIC):
                self._err("SE214", "type-mismatch", f"round() needs a number, got {ts[0]}", node)
            if len(args) == 2:
                if not isinstance(ts[1], TInt):
                    self._err("SE214", "type-mismatch", "round() ndigits must be int", args[1])
                return ts[0]
            return INT
        if name == "ord":
            arity(1)
            if not isinstance(ts[0], TStr):
                self._err("SE214", "type-mismatch", f"ord() expects a str, got {ts[0]}", node)
            return INT
        if name == "chr":
            arity(1)
            if not isinstance(ts[0], TInt):
                self._err("SE214", "type-mismatch", f"chr() expects an int, got {ts[0]}", node)
            return STR
        if name == "iter":
            arity(1)
            if not isinstance(ts[0], TList):
                self._err("SE214", "type-mismatch", f"iter() takes a list, got {ts[0]}", node)
            if not ts[0].elem.is_copy():
                self._err("SE201", "unsupported-feature",
                          f"iter() over {ts[0]} — next() copies elements out, so Tier-2 "
                          f"iterators need Copy elements", node)
            if not isinstance(args[0], ast.Name):
                self._err("SE201", "unsupported-feature",
                          "iter() takes a named list variable (the iterator borrows it)",
                          node)
            return TIterObj(ts[0].elem)
        if name == "next":
            arity(1)
            if isinstance(ts[0], TClass):
                r = self._op_method_call(node, args[0], "__next__", [], narrow)
                if r is not None:
                    return r
            if not (isinstance(args[0], ast.Name)
                    and self.env.get(args[0].id, (None, None))[1] == "iterlocal"):
                self._err("SE201", "unsupported-feature",
                          "next() takes an iterator bound with 'it = iter(xs)'", node)
            assert isinstance(ts[0], TIterObj)
            return ts[0].elem
        if name == "sorted":
            return self._type_sorted(node, ts, narrow)
        if name in ("bytes", "bytearray"):
            ret: Type = TBytes() if name == "bytes" else TByteArray()
            if len(args) == 0:
                return ret
            if len(args) == 1:
                t0 = ts[0]
                if isinstance(t0, TInt) or isinstance(t0, (TBytes, TByteArray)) \
                        or (isinstance(t0, TList) and isinstance(t0.elem, TInt)) \
                        or (name == "bytes" and isinstance(t0, TPyVal)):
                    return ret
            self._err("SE214", "type-mismatch",
                      f"{name}() takes no argument, an int count, a list[int], bytes, "
                      f"or bytearray", node)
        if name == "input":
            if len(args) > 1:
                self._err("SE214", "type-mismatch", "input() takes at most one argument", node)
            return STR
        self._err("SE201", "unsupported-feature", f"'{name}' is not a Tier-0 builtin or known function", node)
        raise AssertionError

    def _type_generic_static(self, node: ast.Call, recv: ast.Subscript, scls: "ClassInfo",
                             method: str, narrow: dict[str, Type]) -> Type:
        """Type `Cls[int].classmethod(...)` — a static call on a generic instantiation."""
        t = parse_annotation(recv, self.rep, str(self.mod.path), allow_wrapper=False,
                             names=self._type_names(self.mod)).typ
        if not isinstance(t, TClass) or not self._inst_ok(scls, t):
            self._err("SE214", "type-mismatch",
                      f"'{recv.value.id}[...]' must name a concrete instantiation of a "
                      f"generic class to call '{method}' on it", node)
            return TPyVal()
        skey = scls.statics[method]
        sig = self.sigs[skey]
        synth = ast.Call(func=ast.Name(id=skey[1], ctx=ast.Load()),
                         args=list(node.args), keywords=list(node.keywords))
        ast.copy_location(synth, node)
        ast.copy_location(synth.func, node)
        ast.fix_missing_locations(synth)
        rt = self._type_user_call(synth, sig, narrow, pre_sub=dict(zip(scls.typevars, t.args)))
        self.expr_types[id(synth)] = rt
        self.op_calls[id(node)] = synth
        return rt

    def _type_method_call(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        method = node.func.attr
        if isinstance(recv, ast.Name) and recv.id not in self.env:
            scls = self._resolve_class(self.mod, recv.id)
            if scls is not None and method in scls.statics:
                if scls.typevars:
                    self._err("SE214", "type-mismatch",
                              f"'{recv.id}' is generic — call '{method}' on a concrete "
                              f"instantiation such as {recv.id}[int]", node)
                skey = scls.statics[method]
                sig = self.sigs[skey]
                synth = ast.Call(func=ast.Name(id=skey[1], ctx=ast.Load()),
                                 args=list(node.args), keywords=list(node.keywords))
                ast.copy_location(synth, node)
                ast.copy_location(synth.func, node)
                ast.fix_missing_locations(synth)
                t = self._type_user_call(synth, sig, narrow)
                self.expr_types[id(synth)] = t
                self.op_calls[id(node)] = synth
                return t
        if isinstance(recv, ast.Subscript) and isinstance(recv.value, ast.Name) \
                and recv.value.id not in self.env:
            scls = self._resolve_class(self.mod, recv.value.id)
            if scls is not None and method in scls.statics:
                return self._type_generic_static(node, recv, scls, method, narrow)
        if method in ("__enter__", "__aenter__", "__iter__") and not getattr(node, "_serp_with_enter", False):
            self._err("SE201", "unsupported-feature",
                      f"{method} cannot be called directly — use a "
                      f"{'for' if method == '__iter__' else 'with'} statement", node)
        if isinstance(recv, ast.Name) and recv.id == "sys" and self.mod.imports_sys:
            return self._type_sys_call(node, method, narrow)
        if isinstance(recv, ast.Name) and recv.id == "bytes" and recv.id not in self.env:
            if method != "fromhex" or len(node.args) != 1 \
                    or not isinstance(self._type_expr(node.args[0], narrow), TStr):
                self._err("SE214", "type-mismatch",
                          "bytes.fromhex(s) is the only bytes classmethod", node)
            self.expr_types[id(recv)] = TBytes()
            return TBytes()
        rt = self._type_expr(recv, narrow)
        inner0 = rt.inner if isinstance(rt, TShared) else rt
        if isinstance(inner0, TClass):
            info = self.classes.get((inner0.module, inner0.name))
            if info is not None and method in info.fields:
                ft = self._field_type(inner0, method, node)
                if isinstance(ft, TFunc):
                    return self._type_func_value_call(node, ft, narrow)
        if isinstance(inner0, TClass):
            minfo0 = self.classes.get((inner0.module, inner0.name))
            msig0 = minfo0.methods.get(method) if minfo0 is not None else None
            if msig0 is not None:
                if node.keywords:
                    self._apply_keywords(node, msig0.params[1:], f".{method}()")
                self._pad_container_defaults(node, msig0.params[1:])
        if node.keywords:
            self._err("SE201", "unsupported-feature",
                      "keyword arguments are only supported on user-defined "
                      "functions and methods", node)
        args = node.args
        expects: list = [None] * len(args)
        inner_pre = rt.inner if isinstance(rt, TShared) else rt
        if isinstance(inner_pre, TClass):
            minfo2 = self.classes.get((inner_pre.module, inner_pre.name))
            msig2 = minfo2.methods.get(method) if minfo2 is not None else None
            if msig2 is not None:
                sub0 = dict(zip(minfo2.typevars, inner_pre.args))
                pts = [subst_type(p.typ, sub0) for p in msig2.params[1:]]
                for i in range(min(len(args), len(pts))):
                    if not has_tvar(pts[i]):
                        expects[i] = pts[i]
        if isinstance(inner_pre, TList) and method == "append" and len(args) == 1 \
                and not has_tvar(inner_pre.elem):
            expects[0] = inner_pre.elem
        ts = [self._type_expr(a, narrow, expect=e) for a, e in zip(args, expects)]
        span_node = node

        def arity(n: int) -> None:
            if len(args) != n:
                self._err("SE214", "type-mismatch", f".{method}() takes {n} argument(s)", span_node)

        if isinstance(rt, TOptional):
            self._err("SE210", "unnarrowed-optional",
                      "method call on an optional — test 'is not None' first", node)
        if isinstance(rt, TUnion):
            self._err("SE210", "unnarrowed-union",
                      f"method call on {rt} — narrow with isinstance() first", node)

        inner = rt.inner if isinstance(rt, TShared) else rt
        if isinstance(inner, TClass):
            return self._type_class_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TFile):
            return self._type_file_method(node, inner, method, args, ts)
        if isinstance(inner, TJoin):
            if inner.task:
                if method == "_serp_await":
                    arity(0)
                    return inner.ret
                if method == "done":
                    arity(0)
                    return BOOL
                self._err("SE214", "type-mismatch",
                          f"Task has no method '{method}' — only `await task` and done() "
                          f"(docs/DECISIONS.md D45)", node)
            if method != "join":
                self._err("SE214", "type-mismatch",
                          f"JoinHandle has no method '{method}' — only join()", node)
            arity(0)
            return inner.ret
        if isinstance(inner, TThread):
            if method in ("start", "is_alive", "cancel"):
                arity(0)
                return BOOL if method == "is_alive" else NONE
            if method == "join":
                if len(args) > 1:
                    self._err("SE214", "type-mismatch", "join() takes at most one argument (timeout)", node)
                if args and not (isinstance(args[0], ast.Constant) and args[0].value is None):
                    if isinstance(ts[0], TBool) or not isinstance(ts[0], NUMERIC + (TOptional,)):
                        self._err("SE214", "type-mismatch",
                                  f"join() timeout must be a number or None, got {ts[0]}", args[0])
                return NONE
            self._err("SE214", "type-mismatch",
                      f"Thread has no method '{method}' — start()/join()/is_alive()/cancel()", node)
        if isinstance(inner, TList):
            return self._type_list_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TDict):
            return self._type_dict_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TSet):
            return self._type_set_method(node, inner, method, args, ts)
        if isinstance(inner, TStr):
            return self._type_str_method(node, method, args, ts)
        if isinstance(inner, TBytes):
            return self._type_bytes_method(node, method, args, ts)
        if isinstance(inner, TByteArray):
            return self._type_bytearray_method(node, method, args, ts)
        self._err("SE214", "type-mismatch", f"{rt} has no method '{method}'", node)
        raise AssertionError

    def _type_bytes_method(self, node: ast.Call, method: str,
                           args: list[ast.expr], ts: list[Type]) -> Type:
        """Type a method call on an immutable bytes value."""
        def arity(n: int, want: tuple = (TBytes,)) -> None:
            if len(args) != n or not all(isinstance(t, want) for t in ts):
                names = "/".join(w().__str__() for w in want) if n else ""
                self._err("SE214", "type-mismatch",
                          f"bytes.{method}() takes {n} {names} argument(s)", node)
        if method in ("find", "count"):
            arity(1)
            return INT
        if method in ("startswith", "endswith"):
            arity(1)
            return BOOL
        if method == "replace":
            arity(2)
            return TBytes()
        if method == "split":
            if not args:
                return TList(TBytes())
            arity(1)
            return TList(TBytes())
        if method == "join":
            if len(args) != 1 or ts[0] != TList(TBytes()):
                self._err("SE214", "type-mismatch",
                          "bytes.join() takes one list[bytes] argument", node)
            return TBytes()
        if method in ("strip", "lstrip", "rstrip", "upper", "lower"):
            arity(0)
            return TBytes()
        if method == "hex":
            arity(0)
            return STR
        if method == "decode":
            if args and not (len(args) == 1 and isinstance(args[0], ast.Constant)
                             and args[0].value in ("utf-8", "utf8")):
                self._err("SE201", "unsupported-feature",
                          "bytes.decode() supports only the 'utf-8' encoding", node)
            return STR
        self._err("SE214", "type-mismatch", f"bytes has no method '{method}'", node)
        raise AssertionError

    def _type_bytearray_method(self, node: ast.Call, method: str,
                               args: list[ast.expr], ts: list[Type]) -> Type:
        """Type a method call on a mutable bytearray."""
        if method == "append":
            if len(args) != 1 or not isinstance(ts[0], TInt):
                self._err("SE214", "type-mismatch",
                          "bytearray.append() takes one int argument", node)
            self._mut_receiver(node)
            return NONE
        if method == "extend":
            if len(args) != 1 or not isinstance(ts[0], (TBytes, TByteArray)):
                self._err("SE214", "type-mismatch",
                          "bytearray.extend() takes a bytes or bytearray argument", node)
            self._mut_receiver(node)
            return NONE
        if method == "hex":
            if args:
                self._err("SE214", "type-mismatch", "bytearray.hex() takes no arguments", node)
            return STR
        if method == "decode":
            if args and not (len(args) == 1 and isinstance(args[0], ast.Constant)
                             and args[0].value in ("utf-8", "utf8")):
                self._err("SE201", "unsupported-feature",
                          "bytearray.decode() supports only the 'utf-8' encoding", node)
            return STR
        self._err("SE214", "type-mismatch", f"bytearray has no method '{method}'", node)
        raise AssertionError

    def _type_sys_call(self, node: ast.Call, method: str, narrow: dict[str, Type]) -> Type:
        if method != "exit":
            self._err("SE201", "unsupported-feature",
                      f"'sys.{method}()' is not Tier 1 (only sys.argv and sys.exit)", node)
        if len(node.args) > 1:
            self._err("SE214", "type-mismatch", "sys.exit() takes at most one argument", node)
        if node.args:
            t = self._type_expr(node.args[0], narrow)
            if not isinstance(t, TInt):
                self._err("SE214", "type-mismatch",
                          f"sys.exit() takes an int status in Tier 1, got {t}", node.args[0])
        return NONE

    def _type_class_method(self, node: ast.Call, rt: TClass, method: str,
                           args: list[ast.expr], ts: list[Type],
                           narrow: dict[str, Type]) -> Type:
        info = self.classes.get((rt.module, rt.name))
        assert info is not None
        tmpl = info.methods.get(method)
        if tmpl is None:
            self._err("SE214", "type-mismatch", f"{rt} has no method '{method}'", node)
            raise AssertionError
        sub: dict = dict(zip(info.typevars, rt.args))
        params = [Param(p.name, p.conv, subst_type(p.typ, sub), p.default)
                  for p in tmpl.params]
        required = len([p for p in params[1:] if p.default is None])
        if not (required <= len(args) <= len(params) - 1):
            want = str(len(params) - 1) if required == len(params) - 1 \
                else f"{required} to {len(params) - 1}"
            self._err("SE214", "type-mismatch",
                      f".{method}() takes {want} argument(s), got {len(args)}", node)
        method_tvars = {t.name for p in params for t in self._walk(p.typ) if isinstance(t, TVar)}
        for arg, at, p in zip(args, ts, params[1:]):
            if not unify(p.typ, at, sub) and not self._assignable(at, subst_type(p.typ, sub)) \
                    and not _int_widens(at, subst_type(p.typ, sub)):
                self._err("SE214", "type-mismatch",
                          f"argument '{p.name}' expects {subst_type(p.typ, sub)}, got {at}", arg)
        missing = [tv for tv in sorted(method_tvars) if tv not in sub]
        if missing:
            self._err("SE214", "type-mismatch",
                      f"cannot infer type argument(s) {', '.join(missing)} for "
                      f".{method}()", node)
        self._check_bounds(tmpl.module, sub, node)
        if tmpl.is_template:
            sig = self._instantiate(tmpl, sub, node)
        else:
            sig = tmpl
        self.call_targets[id(node)] = (sig.module, sig.name)
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        recv_root = self._borrow_root(recv)
        shared_recv = isinstance(self.expr_types.get(id(recv)), TShared)
        if sig.params[0].conv == CONV_OWNED:
            if shared_recv:
                self._err("SE006", "move-out-of-container",
                          f"cannot consume a Shared value with .{method}() — contents "
                          f"stay shared", node)
            if isinstance(recv, (ast.Name, ast.Attribute, ast.Subscript)):
                self._err("SE002", "missing-move",
                          f".{method}() consumes its receiver (Owned self) — write "
                          f"'move({ast.unparse(recv)}).{method}(...)'", node,
                          help=f"the receiver's ownership ends inside .{method}()")
        if sig.params[0].conv == CONV_MUT and not shared_recv:
            self._mut_receiver(node)
            self._check_narrow_invalidation_by_mut(recv, narrow)
        for arg, p in zip(args, sig.params[1:]):
            concrete = subst_type(p.typ, sub)
            if p.conv == CONV_OWNED and not concrete.is_copy():
                if not (isinstance(arg, ast.Call) and id(arg) in self.move_calls):
                    if isinstance(arg, (ast.Name, ast.Subscript, ast.Attribute)):
                        self._require_move_for_owned(arg, f"Owned parameter '{p.name}'")
            if p.conv in (CONV_MUT, CONV_REF) and recv_root is not None \
                    and self._borrow_root(arg) == recv_root \
                    and sig.params[0].conv == CONV_MUT:
                self._err("SE004", "conflicting-borrow",
                          f"'{recv_root}' is mutably borrowed as the receiver and borrowed "
                          f"again as an argument", node)
            if p.conv == CONV_MUT:
                root = self._borrow_root(arg)
                if root is not None:
                    self._mut_root_check(root, node)
                    self.cur_facts.events.append(("mut_use", root, node))
                    self._check_narrow_invalidation_by_mut(arg, narrow)
        return subst_type(sig.ret, sub) if tmpl.is_template else sig.ret

    SEND_TYPES = (TInt, TFloat, TBool, TStr, TBytes)

    def _type_spawn(self, node: ast.Call, narrow: dict[str, Type], *, task: bool = False) -> Type:
        """spawn(f, args...) -> JoinHandle[R] / create_task(f(args...)) -> Task[R]; Send-checked per D9."""
        what = "asyncio.create_task()" if task else "spawn()"
        if node.keywords:
            self._err("SE201", "unsupported-feature",
                      f"{what} takes positional arguments only", node)
        if not node.args:
            self._err("SE214", "type-mismatch",
                      f"{what} takes a function name plus its arguments", node)
        sig = self._thread_target(node.args[0], what)
        self._check_send_args(sig, node.args[0], node.args[1:], node, narrow)
        if not isinstance(sig.ret, self.SEND_TYPES + (TNone,)):
            self._err("SE216", "not-send",
                      f"'{sig.name}' returns {sig.ret}, which cannot cross a "
                      f"{'task' if task else 'thread'} boundary — only int, float, bool, "
                      f"str, bytes, and None are Send (docs/DECISIONS.md D9)", node.args[0])
        self.spawn_calls[id(node)] = (sig.module, sig.name)
        return TJoin(sig.ret, task=task)

    def _shim_name(self, name: str) -> str | None:
        """Resolve a name to the serpentine-shim member it denotes (directly or re-exported)."""
        if name in self.mod.shim_imports:
            return name
        seen: set[str] = set()
        mod = self.mod
        cur = name
        while cur in mod.imports and mod.name not in seen:
            seen.add(mod.name)
            target_mod, orig = mod.imports[cur]
            nxt = self.program.modules.get(target_mod)
            if nxt is None:
                return None
            if orig in nxt.shim_imports:
                return orig
            mod, cur = nxt, orig
        return None

    def _is_send_type(self, t: Type) -> bool:
        """Send-by-copy types: scalars/str/bytes, plus classes made only of scalar fields."""
        if isinstance(t, self.SEND_TYPES):
            return True
        return self._is_scalar_class(t)

    def _is_scalar_class(self, t: Type) -> bool:
        """A non-generic dataclass whose fields are all int/float/bool (bitwise-copyable)."""
        if not isinstance(t, TClass) or t.args:
            return False
        info = self.classes.get((t.module, t.name))
        if info is None or info.typevars:
            return False
        return all(isinstance(info.fields[f], (TInt, TFloat, TBool)) for f in info.field_order)

    def _thread_target(self, fnode: ast.expr, what: str) -> FuncSig:
        """Resolve and validate a thread entry point (a concrete module function)."""
        if not isinstance(fnode, ast.Name):
            self._err("SE201", "unsupported-feature",
                      f"{what} takes a named module function as its target", fnode)
        sig = self._resolve_callee(self.mod, fnode.id)
        if sig is None or sig.cls is not None:
            self._err("SE201", "unsupported-feature",
                      f"{what} target '{fnode.id}' is not a module function", fnode)
        if sig.is_template:
            self._err("SE201", "unsupported-feature",
                      f"generic function '{sig.name}' cannot be spawned — thread "
                      f"entry points must be concrete", fnode)
        if any(p.default is not None for p in sig.params):
            self._err("SE201", "unsupported-feature",
                      f"function '{sig.name}' has default parameters and cannot be "
                      f"spawned", fnode)
        if any(p.conv in (CONV_REF, CONV_MUT) for p in sig.params):
            self._err("SE216", "not-send",
                      f"function '{sig.name}' takes Ref/Mut parameters — spawned "
                      f"threads cannot borrow from the spawning thread "
                      f"(docs/DECISIONS.md D9)", fnode)
        return sig

    def _check_send_args(self, sig: FuncSig, fnode: ast.expr, args: list[ast.expr],
                         node: ast.AST, narrow: dict[str, Type]) -> None:
        """Type thread arguments against the target and enforce the Send-by-copy rule."""
        if len(args) != len(sig.params):
            self._err("SE214", "type-mismatch",
                      f"'{sig.name}' takes {len(sig.params)} arguments, got {len(args)}", node)
        for a, p in zip(args, sig.params):
            if not self._is_send_type(p.typ):
                self._err("SE216", "not-send",
                          f"parameter '{p.name}' of '{sig.name}' is {p.typ}, which "
                          f"cannot cross a thread boundary — only int, float, bool, "
                          f"str, bytes and classes made of those scalars are Send "
                          f"(docs/DECISIONS.md D9)", a)
            at = self._type_expr(a, narrow, expect=p.typ)
            if not self._assignable(at, p.typ) and \
                    not (isinstance(p.typ, TFloat) and isinstance(at, TInt)):
                self._err("SE214", "type-mismatch",
                          f"argument '{p.name}' expects {p.typ}, got {at}", a)

    def _type_thread_ctor(self, node: ast.Call, narrow: dict[str, Type], *, timer: bool) -> Type:
        """Thread(target=f, args=(...), name=, daemon=) / Timer(interval, function, args=())."""
        what = "Timer()" if timer else "Thread()"
        kws = {kw.arg: kw.value for kw in node.keywords}
        if None in kws:
            self._err("SE201", "unsupported-feature", f"{what} does not accept **kwargs", node)
        info: dict = {"timer": timer, "name": None, "daemon": None, "interval": None}
        pos = list(node.args)
        if timer:
            if len(pos) > 3:
                self._err("SE214", "type-mismatch", "Timer() takes at most 3 positional arguments", node)
            interval = pos[0] if pos else kws.pop("interval", None)
            fnode = pos[1] if len(pos) > 1 else kws.pop("function", None)
            argsnode = pos[2] if len(pos) > 2 else kws.pop("args", None)
            if interval is None or fnode is None:
                self._err("SE214", "type-mismatch", "Timer() needs interval and function", node)
            it = self._type_expr(interval, narrow, expect=FLOAT)
            if isinstance(it, TBool) or not isinstance(it, NUMERIC):
                self._err("SE214", "type-mismatch", f"Timer() interval must be a number, got {it}", interval)
            info["interval"] = interval
        else:
            if pos:
                self._err("SE201", "unsupported-feature",
                          "Thread() takes keyword arguments only (target=, args=, name=, daemon=)", node)
            fnode = kws.pop("target", None)
            argsnode = kws.pop("args", None)
            if fnode is None:
                self._err("SE201", "unsupported-feature",
                          "Thread() needs target= (or subclass Thread and override run)", node)
        for key in ("name", "daemon"):
            v = kws.pop(key, None)
            if v is not None:
                if isinstance(v, ast.Constant) and v.value is None:
                    continue
                vt = self._type_expr(v, narrow, expect=STR if key == "name" else BOOL)
                want = TStr if key == "name" else TBool
                if not isinstance(vt, want):
                    self._err("SE214", "type-mismatch",
                              f"{what} {key}= must be {'str' if key == 'name' else 'bool'}, got {vt}", v)
                info[key] = v
        if "kwargs" in kws:
            self._err("SE201", "unsupported-feature", f"{what} kwargs= is not supported", kws["kwargs"])
        if kws:
            self._err("SE201", "unsupported-feature",
                      f"{what} got unsupported keyword(s): {', '.join(sorted(kws))}", node)
        sig = self._thread_target(fnode, what)
        args: list[ast.expr] = []
        if argsnode is not None:
            if not isinstance(argsnode, (ast.Tuple, ast.List)):
                self._err("SE201", "unsupported-feature",
                          f"{what} args= must be a tuple literal", argsnode)
            args = list(argsnode.elts)
        self._check_send_args(sig, fnode, args, node, narrow)
        if not isinstance(sig.ret, self.SEND_TYPES + (TNone,)):
            self._err("SE216", "not-send",
                      f"'{sig.name}' returns {sig.ret}, which cannot cross a thread "
                      f"boundary (docs/DECISIONS.md D9)", fnode)
        info["target"] = (sig.module, sig.name)
        info["args"] = args
        self.thread_calls[id(node)] = info
        return TThread()

    def _type_file_method(self, node: ast.Call, ftype: TFile, method: str,
                          args: list[ast.expr], ts: list[Type]) -> Type:
        if method == "read":
            if args:
                self._err("SE214", "type-mismatch", ".read() takes no arguments in Tier 1", node)
            self._mut_receiver(node)
            return TBytes() if ftype.binary else STR
        if method == "write":
            if ftype.binary:
                if len(args) != 1 or not isinstance(ts[0], (TBytes, TByteArray)):
                    self._err("SE214", "type-mismatch",
                              ".write() on a binary file takes one bytes/bytearray argument",
                              node)
            elif len(args) != 1 or not isinstance(ts[0], TStr):
                self._err("SE214", "type-mismatch", ".write() takes one str argument", node)
            self._mut_receiver(node)
            return INT
        if method == "close":
            if args:
                self._err("SE214", "type-mismatch", ".close() takes no arguments", node)
            self._mut_receiver(node)
            return NONE
        self._err("SE201", "unsupported-feature",
                  f"file has no Tier-1 method '{method}' (read/write/close)", node)
        raise AssertionError

    def _mut_receiver(self, node: ast.Call) -> None:
        assert isinstance(node.func, ast.Attribute)
        root = self._borrow_root(node.func.value)
        if root is not None:
            self._mut_root_check(root, node)
            self.cur_facts.events.append(("mut_use", root, node))

    def _type_list_method(self, node: ast.Call, rt: TList, method: str,
                          args: list[ast.expr], ts: list[Type],
                          narrow: dict[str, Type]) -> Type:
        elem = rt.elem
        if method == "append":
            if len(args) != 1:
                self._err("SE214", "type-mismatch", ".append() takes 1 argument", node)
            if not self._assignable(ts[0], elem):
                self._err("SE214", "type-mismatch", f".append() expects {elem}, got {ts[0]}", args[0])
            if not elem.is_copy():
                self._require_move_for_owned(args[0], "list.append (Owned argument)")
            self._mut_receiver(node)
            self._self_alias_check(node, args)
            return NONE
        if method == "insert":
            if len(args) != 2:
                self._err("SE214", "type-mismatch", ".insert() takes 2 arguments", node)
            if not isinstance(ts[0], TInt):
                self._err("SE214", "type-mismatch", ".insert() index must be int", args[0])
            if not self._assignable(ts[1], elem):
                self._err("SE214", "type-mismatch", f".insert() expects {elem}, got {ts[1]}", args[1])
            if not elem.is_copy():
                self._require_move_for_owned(args[1], "list.insert (Owned argument)")
            self._mut_receiver(node)
            return NONE
        if method == "pop":
            if len(args) not in (0, 1):
                self._err("SE214", "type-mismatch", ".pop() takes 0 or 1 arguments", node)
            if args and not isinstance(ts[0], TInt):
                self._err("SE214", "type-mismatch", ".pop() index must be int", args[0])
            self._mut_receiver(node)
            return elem
        if method == "extend":
            if len(args) != 1 or not self._assignable(ts[0], rt):
                self._err("SE214", "type-mismatch", f".extend() expects {rt}", node)
            if not elem.is_copy():
                self._err("SE211", "extend-non-copy",
                          f"extend() on {rt} would bulk-copy non-Copy elements — move them "
                          f"in a loop instead", node)
            self._mut_receiver(node)
            self._self_alias_check(node, args)
            return NONE
        if method in ("clear", "reverse"):
            if args:
                self._err("SE214", "type-mismatch", f".{method}() takes no arguments", node)
            self._mut_receiver(node)
            return NONE
        if method == "sort":
            if args:
                self._err("SE201", "unsupported-feature",
                          "sort() with arguments needs closures — Tier 2", node)
            if not isinstance(elem, (TInt, TFloat, TStr)):
                self._err("SE214", "type-mismatch", f"sort() is not supported on {rt}", node)
            self._mut_receiver(node)
            return NONE
        self._err("SE201", "unsupported-feature", f"list has no Tier-0 method '{method}'", node)
        raise AssertionError

    def _type_set_method(self, node: ast.Call, rt: TSet, method: str,
                         args: list[ast.expr], ts: list[Type]) -> Type:
        """Type a method call on a set value."""
        elem = rt.elem
        if method in ("add", "discard", "remove"):
            if len(args) != 1:
                self._err("SE214", "type-mismatch", f".{method}() takes 1 argument", node)
            if not self._assignable(ts[0], elem):
                self._err("SE214", "type-mismatch",
                          f".{method}() expects {elem}, got {ts[0]}", args[0])
            self._mut_receiver(node)
            return NONE
        if method == "clear":
            if args:
                self._err("SE214", "type-mismatch", ".clear() takes no arguments", node)
            self._mut_receiver(node)
            return NONE
        if method in ("update", "difference_update", "intersection_update"):
            if len(args) != 1 or not self._assignable(ts[0], rt):
                self._err("SE214", "type-mismatch", f".{method}() expects {rt}", node)
            self._mut_receiver(node)
            self._self_alias_check(node, args)
            return NONE
        if method in ("union", "intersection", "difference", "symmetric_difference"):
            if len(args) != 1 or not self._assignable(ts[0], rt):
                self._err("SE214", "type-mismatch", f".{method}() expects {rt}", node)
            return rt
        if method in ("issubset", "issuperset", "isdisjoint"):
            if len(args) != 1 or not self._assignable(ts[0], rt):
                self._err("SE214", "type-mismatch", f".{method}() expects {rt}", node)
            return BOOL
        if method == "copy":
            if args:
                self._err("SE214", "type-mismatch", ".copy() takes no arguments", node)
            return rt
        if method == "pop":
            if args:
                self._err("SE214", "type-mismatch", ".pop() takes no arguments", node)
            self._mut_receiver(node)
            return elem
        self._err("SE201", "unsupported-feature", f"set has no Tier-2 method '{method}'", node)
        raise AssertionError

    def _self_alias_check(self, node: ast.Call, args: list[ast.expr]) -> None:
        """SE004 when a Mut receiver is also borrowed by an argument (xs.extend(xs))."""
        assert isinstance(node.func, ast.Attribute)
        recv_root = self._borrow_root(node.func.value)
        if recv_root is None:
            return
        for a in args:
            if self._borrow_root(a) == recv_root:
                self._err("SE004", "conflicting-borrow",
                          f"'{recv_root}' is mutably borrowed as the receiver and borrowed "
                          f"again as an argument", node)

    def _type_dict_method(self, node: ast.Call, rt: TDict, method: str,
                          args: list[ast.expr], ts: list[Type],
                          narrow: dict[str, Type]) -> Type:
        if method == "get":
            if len(args) != 1 or not self._assignable(ts[0], rt.key):
                self._err("SE214", "type-mismatch", f".get() expects {rt.key}", node)
            if not rt.value.is_copy():
                self._err("SE212", "get-non-copy",
                          f"get() on {rt} would copy a non-Copy value out — use 'k in d' "
                          f"plus d[k], or d.pop(k)", node)
            return TOptional(rt.value)
        if method == "pop":
            if len(args) != 1 or not self._assignable(ts[0], rt.key):
                self._err("SE214", "type-mismatch", f".pop() expects {rt.key}", node)
            self._mut_receiver(node)
            return rt.value
        if method == "keys":
            if args:
                self._err("SE214", "type-mismatch", ".keys() takes no arguments", node)
            return TIter("keys", (rt.key,))
        if method == "values":
            if args:
                self._err("SE214", "type-mismatch", ".values() takes no arguments", node)
            return TIter("values", (rt.value,))
        if method == "items":
            if args:
                self._err("SE214", "type-mismatch", ".items() takes no arguments", node)
            return TIter("items", (rt.key, rt.value))
        self._err("SE201", "unsupported-feature", f"dict has no Tier-0 method '{method}'", node)
        raise AssertionError

    def _type_str_method(self, node: ast.Call, method: str,
                         args: list[ast.expr], ts: list[Type]) -> Type:
        def need(n: int, types: tuple = ()) -> None:
            if len(args) != n:
                self._err("SE214", "type-mismatch", f".{method}() takes {n} argument(s)", node)
            for t in ts:
                if not isinstance(t, TStr):
                    self._err("SE214", "type-mismatch", f".{method}() arguments must be str", node)

        if method == "encode":
            if args and not (len(args) == 1 and isinstance(args[0], ast.Constant)
                             and args[0].value in ("utf-8", "utf8")):
                self._err("SE201", "unsupported-feature",
                          "str.encode() supports only the 'utf-8' encoding", node)
            return TBytes()
        if method == "split":
            if len(args) == 0:
                return TList(STR)
            need(1)
            return TList(STR)
        if method == "join":
            if len(args) != 1 or not (isinstance(ts[0], TList) and isinstance(ts[0].elem, TStr)):
                self._err("SE214", "type-mismatch", ".join() expects list[str]", node)
            return STR
        if method in ("strip", "lstrip", "rstrip", "upper", "lower"):
            need(0)
            return STR
        if method in ("startswith", "endswith"):
            need(1)
            return BOOL
        if method == "find":
            need(1)
            return INT
        if method == "replace":
            need(2)
            return STR
        self._err("SE201", "unsupported-feature", f"str has no Tier-0 method '{method}'", node)
        raise AssertionError
