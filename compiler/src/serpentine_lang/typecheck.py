"""Type checker: symbols, annotation enforcement, Tier-0 typing, is-None narrowing.

Also enforces the subset (SE201/204/206/207/208/210/211/212/214), call-site move
discipline (SE002/SE003/SE006/SE209), and collects the ownership facts that SIR
lowering and the Rust backend consume.
"""

import ast
import copy
from dataclasses import dataclass, field

from .diagnostics import Reporter, Span
from .frontend import Module, Program
from .ptypes import (BOOL, CONV_COPY, CONV_MUT, CONV_OWNED, CONV_REF, FLOAT, INT, NONE, STR,
                     Type, TBool, TClass, TDict, TExc, TFile, TFloat, TInt, TList, TNone,
                     TOptional, TShared, TStr, TTuple, TVar, TWeak,
                     has_tvar, mangle_type, parse_annotation, subst_type, unify)


@dataclass(frozen=True)
class TIter(Type):
    """Internal type for keys()/values()/items()/range/enumerate results (for-only)."""

    kind: str
    elem: tuple[Type, ...]

    def __str__(self) -> str:
        return f"<{self.kind} iterator>"


@dataclass
class Param:
    name: str
    conv: str
    typ: Type


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
    methods: dict[str, FuncSig] = field(default_factory=dict)
    typevars: list[str] = field(default_factory=list)


# Exception classes recognized by raise/except (SPEC.md section 11 + Tier-1 additions).
KNOWN_EXC = {"Exception", "ValueError", "RuntimeError", "TypeError", "IndexError", "KeyError",
             "ZeroDivisionError", "OverflowError", "EOFError", "FileNotFoundError",
             "PermissionError", "OSError", "ArithmeticError", "LookupError"}


@dataclass
class FuncFacts:
    """Ownership facts for one function, consumed by SIR lowering."""

    sig: FuncSig
    locals: dict[str, Type] = field(default_factory=dict)
    events: list[tuple] = field(default_factory=list)


NUMERIC = (TInt, TFloat)


class TypeChecker:
    """Whole-program Tier-0 type checker."""

    def __init__(self, program: Program, rep: Reporter):
        self.program = program
        self.rep = rep
        self.sigs: dict[tuple[str, str], FuncSig] = {}
        self.expr_types: dict[int, Type] = {}
        self.narrowed_uses: set[int] = set()
        self.move_calls: set[int] = set()
        self.loop_iter_kind: dict[int, str] = {}
        self.facts: dict[tuple[str, str], FuncFacts] = {}
        self.constants: dict[tuple[str, str], Type] = {}
        self.classes: dict[tuple[str, str], ClassInfo] = {}
        self.call_targets: dict[int, tuple[str, str]] = {}   # call node id -> sig key
        self.ctor_calls: dict[int, tuple[str, str, tuple]] = {}   # call node id -> class inst
        self.checked_bodies: set[tuple[str, str]] = set()

    def run(self) -> None:
        """Check every module: classes and signatures first, then all bodies."""
        for mod in self.program.modules.values():
            self._collect_classes(mod)
        for mod in self.program.modules.values():
            self._collect_class_members(mod)
            self._collect_signatures(mod)
        self._check_class_cycles()
        for mod in self.program.modules.values():
            self._check_constants(mod)
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
                    self._check_function(mod, m.node, m)
            if mod.entry_call and mod.entry_call not in mod.functions:
                self.rep.fatal("SE214", "type-mismatch",
                               f"entry guard calls unknown function '{mod.entry_call}'",
                               Span(str(mod.path), 1, 0))

    def _type_names(self, mod: Module) -> dict[str, Type]:
        """The class/typevar names visible in a module's annotations."""
        names: dict[str, Type] = {}
        for cname in mod.classes:
            names[cname] = TClass(mod.name, cname)
        for tv in mod.typevars:
            names[tv] = TVar(tv)
        for alias, (tmod, orig) in mod.imports.items():
            tm = self.program.modules.get(tmod)
            if tm is not None and orig in tm.classes:
                names[alias] = TClass(tmod, orig)
            elif tm is not None and orig in tm.typevars:
                names[alias] = TVar(orig)
        return names

    def _collect_classes(self, mod: Module) -> None:
        """Register every class name so annotations across modules resolve."""
        for cname, cnode in mod.classes.items():
            self.classes[(mod.name, cname)] = ClassInfo(mod.name, cname, cnode)

    def _collect_class_members(self, mod: Module) -> None:
        """Parse fields and method signatures of every class in a module."""
        file = str(mod.path)
        names = self._type_names(mod)
        for cname, cnode in mod.classes.items():
            info = self.classes[(mod.name, cname)]
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
                    if stmt.value is not None:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "dataclass field defaults are not Tier 1", span)
                    parsed = parse_annotation(stmt.annotation, self.rep, file,
                                              allow_wrapper=False, names=names)
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
                    if stmt.decorator_list:
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "method decorators are not Tier 1", span)
                    if stmt.name.startswith("__"):
                        self.rep.fatal("SE201", "unsupported-feature",
                                       "dunder methods are not Tier 1 (dataclass generates "
                                       "__init__/__repr__/__eq__)", span)
                    info.methods[stmt.name] = self._parse_method_sig(mod, info, stmt, names)
                elif isinstance(stmt, ast.Pass):
                    continue
                else:
                    self.rep.fatal("SE201", "unsupported-feature",
                                   "class bodies may only contain annotated fields and methods",
                                   span)
            if not info.fields:
                self.rep.fatal("SE201", "unsupported-feature",
                               f"class '{cname}' has no fields — empty dataclasses are not "
                               f"Tier 1", Span(file, cnode.lineno, cnode.col_offset))

    def _walk(self, t: Type):
        from .ptypes import walk_types
        return walk_types(t)

    def _self_type(self, info: ClassInfo) -> TClass:
        return TClass(info.module, info.name,
                      tuple(TVar(tv) for tv in info.typevars))

    def _parse_method_sig(self, mod: Module, info: ClassInfo, fn: ast.FunctionDef,
                          names: dict[str, Type]) -> FuncSig:
        """Parse a method signature; self must be annotated Ref[C] or Mut[C]."""
        file = str(mod.path)
        a = fn.args
        span = Span(file, fn.lineno, fn.col_offset)
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults or a.kw_defaults:
            self.rep.fatal("SE201", "unsupported-feature",
                           "methods take plain positional parameters without defaults", span)
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
        if parsed.conv not in (CONV_REF, CONV_MUT) or not isinstance(parsed.typ, TClass) \
                or parsed.typ.name != info.name or parsed.typ.module != info.module:
            self.rep.fatal("SE202", "invalid-wrapper-position",
                           f"'self' of method '{fn.name}' must be Ref[{info.name}] or "
                           f"Mut[{info.name}] (Owned self is Tier 2)",
                           Span(file, self_arg.lineno, self_arg.col_offset))
        params = [Param("self", parsed.conv, self._self_type(info))]
        for arg in a.args[1:]:
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
            params.append(Param(arg.arg, conv, p.typ))
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

    def _collect_signatures(self, mod: Module) -> None:
        """Parse and validate every function signature in a module."""
        file = str(mod.path)
        names = self._type_names(mod)
        for fn in mod.functions.values():
            a = fn.args
            if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg:
                self.rep.fatal("SE201", "unsupported-feature",
                               "only plain positional parameters are Tier 0", self._span(mod, fn))
            if a.defaults or a.kw_defaults:
                self.rep.fatal("SE201", "unsupported-feature",
                               "default parameter values are not Tier 0", self._span(mod, fn))
            params = []
            for arg in a.args:
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
                params.append(Param(arg.arg, conv, parsed.typ))
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
            if template and has_tvar(ret):
                ret_vars = {t.name for t in self._walk(ret) if isinstance(t, TVar)}
                param_vars = {t.name for p in params for t in self._walk(p.typ)
                              if isinstance(t, TVar)}
                if not ret_vars <= param_vars:
                    self.rep.fatal("SE214", "type-mismatch",
                                   f"return type of '{fn.name}' uses a type variable that no "
                                   f"parameter mentions — it can never be inferred",
                                   Span(file, r.lineno, r.col_offset))
            self.sigs[(mod.name, fn.name)] = FuncSig(mod.name, fn.name, params, ret, fn,
                                                     is_template=template)

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
        self.cur_facts = facts
        self.loop_refs: list[dict[str, str]] = []
        self.loop_depth = 0
        self.try_stack: list[dict] = []
        self.handler_depth = 0
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
        for tv, concrete in self.sig.subst.items():
            names[tv] = concrete
        return names

    def _instantiate(self, template: FuncSig, sub: dict, node: ast.AST) -> FuncSig:
        """Monomorphize a generic function/method for a concrete substitution."""
        params = [Param(p.name, p.conv, subst_type(p.typ, sub)) for p in template.params]
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
        # Fix conventions that were deferred while the type was still a TVar.
        for p in inst.params:
            if p.conv == CONV_OWNED and p.typ.is_copy():
                p.conv = CONV_COPY
        saved = (self.env, self.mod, self.fn, self.sig, self.cur_facts, self.loop_refs,
                 self.loop_depth, self.try_stack, self.handler_depth)
        target_mod = self.program.modules[template.module]
        self._check_function(target_mod, node_copy, inst)
        (self.env, self.mod, self.fn, self.sig, self.cur_facts, self.loop_refs,
         self.loop_depth, self.try_stack, self.handler_depth) = saved
        return inst

    def _err(self, code: str, name: str, msg: str, node: ast.AST, label: str = "",
             help: str = "") -> None:
        self.rep.fatal(code, name, msg, self._span(self.mod, node), label, help=help)

    def _check_block(self, stmts: list[ast.stmt], narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        """Check a statement list; returns (narrowings after, definitely-terminates)."""
        term = False
        for stmt in stmts:
            if term:
                break
            narrow, term = self._check_stmt(stmt, narrow)
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
        if isinstance(stmt, (ast.With, ast.Match, ast.Assert, ast.Delete, ast.Global,
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
            self._type_expr(stmt.value, narrow)
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
        body_narrow = {k: v for k, v in narrow.items() if k not in assigned}
        _, body_term = self._check_block(stmt.body, body_narrow)
        self.try_stack.pop()

        handler_terms = []
        seen_classes: list[str] = []
        for h in stmt.handlers:
            classes = self._handler_classes(h)
            for c in classes:
                if c in seen_classes or "Exception" in seen_classes:
                    self._err("SE201", "unsupported-feature",
                              f"except clause for '{c}' is unreachable — already handled", h)
            seen_classes.extend(classes)
            if h.name:
                self._declare(h.name, TExc(), h)
                self.cur_facts.events.append(("assign", h.name, h))
            self.handler_depth += 1
            h_assigned = self._assigned_names(h.body)
            h_narrow = {k: v for k, v in narrow.items()
                        if k not in assigned and k not in h_assigned}
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
        after = {k: v for k, v in narrow.items() if k not in all_assigned}
        term = body_term and bool(stmt.handlers) and all(handler_terms)
        return after, term

    def _handler_classes(self, h: ast.ExceptHandler) -> list[str]:
        if h.type is None:
            return ["Exception"]
        if isinstance(h.type, ast.Name):
            if h.type.id not in KNOWN_EXC:
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{h.type.id}' — user exception classes "
                          f"are Tier 2", h.type)
            return [h.type.id]
        if isinstance(h.type, ast.Tuple):
            out = []
            for e in h.type.elts:
                if not isinstance(e, ast.Name) or e.id not in KNOWN_EXC:
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
            if e.id not in KNOWN_EXC:
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{e.id}' — user exception classes are "
                          f"Tier 2", e)
            return
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name):
            if e.func.id not in KNOWN_EXC:
                self._err("SE214", "type-mismatch",
                          f"unknown exception class '{e.func.id}' — user exception classes "
                          f"are Tier 2", e)
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

    def _check_return(self, stmt: ast.Return, narrow: dict[str, Type]) -> None:
        if stmt.value is None:
            if not isinstance(self.sig.ret, TNone):
                self._err("SE214", "type-mismatch",
                          f"bare return in function returning {self.sig.ret}", stmt)
            return
        t = self._type_expr(stmt.value, narrow)
        if not self._assignable(t, self.sig.ret):
            self._err("SE214", "type-mismatch",
                      f"return type mismatch: expected {self.sig.ret}, got {t}", stmt)
        if isinstance(stmt.value, ast.Name) and not t.is_copy():
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
        if isinstance(value, ast.Subscript):
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

    def _check_annassign(self, stmt: ast.AnnAssign, narrow: dict[str, Type]) -> dict[str, Type]:
        if not isinstance(stmt.target, ast.Name):
            self._err("SE201", "unsupported-feature", "annotated assignment target must be a name", stmt)
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
            t = self._type_expr(stmt.value, narrow,
                                expect=self.env[target.id][0] if target.id in self.env else None)
            if isinstance(t, TIter):
                self._err("SE201", "unsupported-feature",
                          "this iterator may only be consumed by a for loop", stmt.value)
            if target.id in self.env:
                declared = self.env[target.id][0]
                if not self._assignable(t, declared):
                    self._err("SE214", "type-mismatch",
                              f"cannot assign {t} to '{target.id}: {declared}'", stmt)
                t = declared
            else:
                if self._is_empty_literal(stmt.value):
                    self._err("SE204", "unknown-element-type",
                              "empty container literal needs a type annotation", stmt.value)
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
            base_t = self._type_expr(target.value, narrow)
            cls_t = base_t.inner if isinstance(base_t, TShared) else base_t
            if not isinstance(cls_t, TClass):
                self._err("SE214", "type-mismatch",
                          f"{base_t} has no assignable attribute '{target.attr}'", target)
            ft = self._field_type(cls_t, target.attr, target)
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
        tt = self._type_expr_place(stmt.target, narrow)
        vt = self._type_expr(stmt.value, narrow)
        rt = self._binop_type(stmt.op, tt, vt, stmt)
        if not self._assignable(rt, tt):
            self._err("SE214", "type-mismatch", f"augmented assignment changes type {tt} -> {rt}", stmt)
        if isinstance(stmt.target, (ast.Subscript, ast.Attribute)):
            self._mut_borrow_place(stmt.target.value, stmt)
        if isinstance(stmt.target, ast.Name):
            narrow = dict(narrow)
            narrow.pop(stmt.target.id, None)
            self._record_assign_events(stmt.target.id, stmt.value, stmt)
        return narrow

    def _check_if(self, stmt: ast.If, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        cond_t = self._type_expr(stmt.test, narrow)
        if not isinstance(cond_t, TBool):
            self._err("SE214", "type-mismatch", f"if condition must be bool, got {cond_t}", stmt.test)
        pos, neg = self._narrow_from_test(stmt.test, narrow)
        then_after, then_term = self._check_block(stmt.body, pos)
        else_after, else_term = self._check_block(stmt.orelse, neg) if stmt.orelse else (neg, False)
        assigned = self._assigned_names(stmt.body) | self._assigned_names(stmt.orelse)
        after = {k: v for k, v in narrow.items() if k not in assigned}
        if then_term and not else_term:
            after.update({k: v for k, v in else_after.items() if k not in self._assigned_names(stmt.orelse)})
        elif else_term and not then_term:
            after.update({k: v for k, v in then_after.items() if k not in self._assigned_names(stmt.body)})
        elif not then_term and not else_term and stmt.orelse:
            common = {k: v for k, v in then_after.items() if else_after.get(k) == v}
            after.update({k: v for k, v in common.items() if k not in assigned})
        return after, then_term and (else_term if stmt.orelse else False)

    def _narrow_from_test(self, test: ast.expr, narrow: dict[str, Type]) \
            -> tuple[dict[str, Type], dict[str, Type]]:
        """Compute narrowings for the true and false branches of a condition."""
        pos = dict(narrow)
        neg = dict(narrow)
        if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                and isinstance(test.ops[0], (ast.Is, ast.IsNot)) \
                and isinstance(test.left, ast.Name):
            name = test.left.id
            declared = self.env.get(name, (None, None))[0]
            if isinstance(declared, TOptional):
                if isinstance(test.ops[0], ast.IsNot):
                    pos[name] = declared.inner
                else:
                    neg[name] = declared.inner
        return pos, neg

    def _check_while(self, stmt: ast.While, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        assigned = self._assigned_names(stmt.body)
        loop_narrow = {k: v for k, v in narrow.items() if k not in assigned}
        cond_t = self._type_expr(stmt.test, loop_narrow)
        if not isinstance(cond_t, TBool):
            self._err("SE214", "type-mismatch", f"while condition must be bool, got {cond_t}", stmt.test)
        pos, _neg = self._narrow_from_test(stmt.test, loop_narrow)
        self.loop_depth += 1
        self._check_block(stmt.body, pos)
        self.loop_depth -= 1
        if stmt.orelse:
            self._err("SE201", "unsupported-feature", "while-else is not Tier 0", stmt)
        return {k: v for k, v in narrow.items() if k not in assigned}, False

    def _check_for(self, stmt: ast.For, narrow: dict[str, Type]) -> tuple[dict[str, Type], bool]:
        if stmt.orelse:
            self._err("SE201", "unsupported-feature", "for-else is not Tier 0", stmt)
        iter_t = self._type_expr(stmt.iter, narrow)
        kind = "list"
        elems: tuple[Type, ...]
        if isinstance(iter_t, TList):
            elems = (iter_t.elem,)
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
        body_narrow = {k: v for k, v in narrow.items() if k not in assigned}
        self._check_block(stmt.body, body_narrow)
        self.loop_depth -= 1
        self.loop_refs.pop()
        if borrowed is not None:
            self.cur_facts.events.append(("loop_borrow_end", borrowed, stmt))
        for tgt in targets:
            assigned.add(tgt.id)
        return {k: v for k, v in narrow.items() if k not in assigned}, False

    def _borrowable_root(self, iter_expr: ast.expr) -> str | None:
        """The root variable Ref-borrowed by a for loop, if any (range borrows nothing)."""
        e = iter_expr
        if isinstance(e, ast.Call):
            if isinstance(e.func, ast.Name) and e.func.id == "range":
                return None
            if isinstance(e.func, ast.Name) and e.func.id == "enumerate" and e.args:
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

    def _assignable(self, src: Type, dst: Type) -> bool:
        if src == dst:
            return True
        if isinstance(dst, TOptional):
            return isinstance(src, TNone) or self._assignable(src, dst.inner)
        if isinstance(dst, TList) and isinstance(src, TList):
            return self._assignable(src.elem, dst.elem)
        if isinstance(dst, TDict) and isinstance(src, TDict):
            return self._assignable(src.key, dst.key) and self._assignable(src.value, dst.value)
        return False

    def _type_expr_place(self, node: ast.expr, narrow: dict[str, Type]) -> Type:
        return self._type_expr(node, narrow)

    def _lookup(self, name: str, node: ast.AST, narrow: dict[str, Type]) -> Type:
        if name in narrow:
            self.narrowed_uses.add(id(node))
            return narrow[name]
        if name in self.env:
            return self.env[name][0]
        if (self.mod.name, name) in self.constants:
            return self.constants[(self.mod.name, name)]
        self._err("SE214", "type-mismatch", f"unknown name '{name}'", node)
        raise AssertionError

    def _type_expr(self, node: ast.expr, narrow: dict[str, Type], expect: Type | None = None) -> Type:
        t = self._type_expr_inner(node, narrow, expect)
        self.expr_types[id(node)] = t
        return t

    def _type_expr_inner(self, node: ast.expr, narrow: dict[str, Type], expect: Type | None) -> Type:
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp, ast.NamedExpr, ast.Await, ast.Yield,
                             ast.YieldFrom, ast.Starred, ast.Set, ast.Slice)):
            self._err("SE201", "unsupported-feature",
                      f"'{type(node).__name__}' is not in the Tier-0 grammar", node)
        if isinstance(node, ast.Constant):
            return self._const_type(node)
        if isinstance(node, ast.Name):
            t = self._lookup(node.id, node, narrow)
            if isinstance(t, TOptional) and expect is not None and not isinstance(expect, TOptional):
                self._err("SE210", "unnarrowed-optional",
                          f"'{node.id}' is {t} here — test 'is not None' before using it as "
                          f"{t.inner}", node)
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
            return self._binop_type(node.op, lt, rt, node)
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
        self._err("SE201", "unsupported-feature",
                  f"'{type(node).__name__}' is not in the Tier-0 grammar", node)
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
        base = self._type_expr(node.value, narrow)
        if isinstance(base, TOptional):
            self._err("SE210", "unnarrowed-optional",
                      "attribute access on an optional — test 'is not None' first", node)
        cls_t = base.inner if isinstance(base, TShared) else base
        if isinstance(cls_t, TClass):
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
        if v is None:
            return NONE
        self._err("SE201", "unsupported-feature", f"literal {v!r} is not Tier 0", node)
        raise AssertionError

    def _type_fstring(self, node: ast.JoinedStr, narrow: dict[str, Type]) -> Type:
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                t = self._type_expr(part.value, narrow)
                if isinstance(t, (TIter, TFile)):
                    self._err("SE214", "type-mismatch", f"cannot format a {t}", part.value)
        return STR

    def _type_list_literal(self, node: ast.List, narrow: dict[str, Type], expect: Type | None) -> Type:
        if not node.elts:
            if isinstance(expect, TList):
                return expect
            return TList(NONE)
        elem_expect = expect.elem if isinstance(expect, TList) else None
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

    def _type_dict_literal(self, node: ast.Dict, narrow: dict[str, Type], expect: Type | None) -> Type:
        if not node.keys:
            if isinstance(expect, TDict):
                return expect
            return TDict(NONE, NONE)
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
        idx = self._type_expr(node.slice, narrow)
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
        self._err("SE214", "type-mismatch", f"{base} is not subscriptable", node)
        raise AssertionError

    def _type_unary(self, node: ast.UnaryOp, narrow: dict[str, Type]) -> Type:
        t = self._type_expr(node.operand, narrow)
        if isinstance(node.op, ast.Not):
            if not isinstance(t, TBool):
                self._err("SE214", "type-mismatch", f"'not' operand must be bool, got {t}", node)
            return BOOL
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            if isinstance(t, TBool):
                self._err("SE208", "bool-arithmetic", "bool in arithmetic position — write int(b)", node)
            if not isinstance(t, NUMERIC):
                self._err("SE214", "type-mismatch", f"unary +/- needs a number, got {t}", node)
            return t
        self._err("SE201", "unsupported-feature", "unsupported unary operator", node)
        raise AssertionError

    def _binop_type(self, op: ast.operator, lt: Type, rt: Type, node: ast.AST) -> Type:
        for t, operand in ((lt, "left"), (rt, "right")):
            if isinstance(t, TBool):
                self._err("SE208", "bool-arithmetic",
                          f"bool in arithmetic position ({operand} operand) — write int(b)", node)
            if isinstance(t, TOptional):
                self._err("SE210", "unnarrowed-optional",
                          "optional value in arithmetic — test 'is not None' first", node)
        if isinstance(op, ast.Add) and isinstance(lt, TStr) and isinstance(rt, TStr):
            return STR
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
            if not isinstance(node.left, ast.Name):
                self._err("SE210", "unnarrowed-optional",
                          "narrowing applies to names only — bind the value first "
                          "(v = d.get(k))", node.left)
            self._type_expr(node.left, narrow)
            return BOOL
        if any(isinstance(o, (ast.In, ast.NotIn)) for o in ops):
            if len(ops) != 1:
                self._err("SE201", "unsupported-feature", "chained 'in' is not Tier 0", node)
            lt = self._type_expr(node.left, narrow)
            ct = self._type_expr(node.comparators[0], narrow)
            if isinstance(ct, TDict):
                if not self._assignable(lt, ct.key):
                    self._err("SE214", "type-mismatch", f"'in' key must be {ct.key}, got {lt}", node)
            elif isinstance(ct, TList):
                if not ct.elem.is_copy() or not self._assignable(lt, ct.elem):
                    self._err("SE214", "type-mismatch", f"'in' needs a Copy element match on {ct}", node)
            elif isinstance(ct, TStr):
                if not isinstance(lt, TStr):
                    self._err("SE214", "type-mismatch", "'in' on str needs a str operand", node)
            else:
                self._err("SE214", "type-mismatch", f"'in' is not supported on {ct}", node)
            return BOOL
        prev = self._type_expr(node.left, narrow)
        for op, comp in zip(ops, node.comparators):
            cur = self._type_expr(comp, narrow)
            self._check_comparable(op, prev, cur, node)
            prev = cur
        return BOOL

    def _check_comparable(self, op: ast.cmpop, lt: Type, rt: Type, node: ast.AST) -> None:
        if isinstance(lt, (TWeak, TFile, TExc)) or isinstance(rt, (TWeak, TFile, TExc)):
            self._err("SE214", "type-mismatch", f"cannot compare {lt} and {rt}", node)
        if isinstance(lt, TClass) or isinstance(rt, TClass):
            if lt != rt or not isinstance(op, (ast.Eq, ast.NotEq)):
                self._err("SE214", "type-mismatch",
                          f"class instances support only ==/!= against the same class "
                          f"({lt} vs {rt})", node)
            return
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

    def _type_call(self, node: ast.Call, narrow: dict[str, Type], expect: Type | None) -> Type:
        if node.keywords:
            self._err("SE201", "unsupported-feature", "keyword arguments are not Tier 0", node)
        if isinstance(node.func, ast.Attribute):
            return self._type_method_call(node, narrow)
        if not isinstance(node.func, ast.Name):
            self._err("SE201", "unsupported-feature", "only named functions can be called", node)
        name = node.func.id
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
        if name == "open":
            return self._type_open(node, narrow)
        if name in KNOWN_EXC:
            self._err("SE201", "unsupported-feature",
                      f"exception values can only be created in a raise statement", node)
        cls = self._resolve_class(self.mod, name)
        if cls is not None:
            return self._type_ctor(node, cls, narrow)
        if name in ("eval", "exec", "globals", "locals", "compile", "id",
                    "sorted", "map", "filter", "zip", "any", "all", "type", "isinstance"):
            self._err("SE201", "unsupported-feature", f"'{name}' is not a Tier-0/1 builtin", node)
        sig = self._resolve_callee(self.mod, name)
        if sig is not None:
            return self._type_user_call(node, sig, narrow)
        return self._type_builtin_call(node, name, narrow)

    def _resolve_class(self, mod: Module, name: str) -> ClassInfo | None:
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
        if len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            if node.args[1].value not in ("r", "w", "a"):
                self._err("SE201", "unsupported-feature",
                          f"open() mode {node.args[1].value!r} is not Tier 1 — use 'r', 'w' "
                          f"or 'a'", node.args[1])
        return TFile()

    def _type_ctor(self, node: ast.Call, cls: ClassInfo, narrow: dict[str, Type]) -> Type:
        """Type a dataclass constructor call, inferring generic arguments."""
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
        t = TClass(cls.module, cls.name, args)
        self.ctor_calls[id(node)] = (cls.module, cls.name, args)
        return t

    def _type_move(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        if len(node.args) != 1:
            self._err("SE214", "type-mismatch", "move() takes exactly one argument", node)
        arg = node.args[0]
        self.move_calls.add(id(node))
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
        for scope in self.loop_refs:
            if root in scope:
                self._err("SE004", "conflicting-borrow",
                          f"'{root}' is a per-iteration Ref loop variable — it cannot be "
                          f"mutated through", node)

    def _mut_borrow_place(self, e: ast.expr, node: ast.AST) -> None:
        root = self._borrow_root(e)
        if root is not None:
            self._mut_root_check(root, node)
            self.cur_facts.events.append(("mut_use", root, node))

    def _check_narrow_invalidation_by_mut(self, e: ast.expr, narrow: dict[str, Type]) -> None:
        root = self._borrow_root(e)
        if root is not None:
            narrow.pop(root, None)

    def _type_user_call(self, node: ast.Call, sig: FuncSig, narrow: dict[str, Type]) -> Type:
        if len(node.args) != len(sig.params):
            self._err("SE214", "type-mismatch",
                      f"'{sig.name}' takes {len(sig.params)} arguments, got {len(node.args)}", node)
        if sig.is_template:
            sub: dict = {}
            arg_ts = []
            for arg, p in zip(node.args, sig.params):
                if has_tvar(p.typ) and self._is_empty_literal(arg):
                    self._err("SE204", "unknown-element-type",
                              f"empty literal cannot infer type variable for parameter "
                              f"'{p.name}' — bind it to an annotated variable first", arg)
                at = self._type_expr(arg, narrow,
                                     expect=None if has_tvar(p.typ) else p.typ)
                arg_ts.append(at)
                if not unify(p.typ, at, sub):
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
            if not self._assignable(at, p.typ):
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

    def _type_builtin_call(self, node: ast.Call, name: str, narrow: dict[str, Type]) -> Type:
        args = node.args
        ts = [self._type_expr(a, narrow) for a in args]

        def arity(n: int) -> None:
            if len(args) != n:
                self._err("SE214", "type-mismatch", f"{name}() takes {n} argument(s)", node)

        if name == "print":
            for t in ts:
                if isinstance(t, (TIter, TFile)):
                    self._err("SE214", "type-mismatch", f"cannot print a {t}", node)
            return NONE
        if name == "len":
            arity(1)
            t0 = ts[0].inner if isinstance(ts[0], TShared) else ts[0]
            if not isinstance(t0, (TList, TDict, TStr)):
                self._err("SE214", "type-mismatch", f"len() is not supported on {ts[0]}", node)
            return INT
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
            if isinstance(ts[0], TBool) or not isinstance(ts[0], NUMERIC):
                self._err("SE214", "type-mismatch", f"abs() needs a number, got {ts[0]}", node)
            return ts[0]
        if name == "str":
            arity(1)
            return STR
        if name == "int":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TBool, TStr)):
                self._err("SE214", "type-mismatch", f"int() cannot convert {ts[0]}", node)
            return INT
        if name == "float":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TStr)):
                self._err("SE214", "type-mismatch", f"float() cannot convert {ts[0]}", node)
            return FLOAT
        if name == "bool":
            arity(1)
            if not isinstance(ts[0], (TInt, TFloat, TBool, TStr)):
                self._err("SE214", "type-mismatch", f"bool() cannot convert {ts[0]}", node)
            return BOOL
        if name == "input":
            if len(args) > 1:
                self._err("SE214", "type-mismatch", "input() takes at most one argument", node)
            return STR
        self._err("SE201", "unsupported-feature", f"'{name}' is not a Tier-0 builtin or known function", node)
        raise AssertionError

    def _type_method_call(self, node: ast.Call, narrow: dict[str, Type]) -> Type:
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        method = node.func.attr
        if isinstance(recv, ast.Name) and recv.id == "sys" and self.mod.imports_sys:
            return self._type_sys_call(node, method, narrow)
        rt = self._type_expr(recv, narrow)
        args = node.args
        ts = [self._type_expr(a, narrow) for a in args]
        span_node = node

        def arity(n: int) -> None:
            if len(args) != n:
                self._err("SE214", "type-mismatch", f".{method}() takes {n} argument(s)", span_node)

        if isinstance(rt, TOptional):
            self._err("SE210", "unnarrowed-optional",
                      "method call on an optional — test 'is not None' first", node)

        inner = rt.inner if isinstance(rt, TShared) else rt
        if isinstance(inner, TClass):
            return self._type_class_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TFile):
            return self._type_file_method(node, method, args, ts)
        if isinstance(inner, TList):
            return self._type_list_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TDict):
            return self._type_dict_method(node, inner, method, args, ts, narrow)
        if isinstance(inner, TStr):
            return self._type_str_method(node, method, args, ts)
        self._err("SE214", "type-mismatch", f"{rt} has no method '{method}'", node)
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
        params = [Param(p.name, p.conv, subst_type(p.typ, sub)) for p in tmpl.params]
        if len(args) != len(params) - 1:
            self._err("SE214", "type-mismatch",
                      f".{method}() takes {len(params) - 1} argument(s), got {len(args)}", node)
        method_tvars = {t.name for p in params for t in self._walk(p.typ) if isinstance(t, TVar)}
        for arg, at, p in zip(args, ts, params[1:]):
            if not unify(p.typ, at, sub) and not self._assignable(at, subst_type(p.typ, sub)):
                self._err("SE214", "type-mismatch",
                          f"argument '{p.name}' expects {subst_type(p.typ, sub)}, got {at}", arg)
        missing = [tv for tv in sorted(method_tvars) if tv not in sub]
        if missing:
            self._err("SE214", "type-mismatch",
                      f"cannot infer type argument(s) {', '.join(missing)} for "
                      f".{method}()", node)
        if tmpl.is_template:
            sig = self._instantiate(tmpl, sub, node)
        else:
            sig = tmpl
        self.call_targets[id(node)] = (sig.module, sig.name)
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        recv_root = self._borrow_root(recv)
        shared_recv = isinstance(self.expr_types.get(id(recv)), TShared)
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

    def _type_file_method(self, node: ast.Call, method: str,
                          args: list[ast.expr], ts: list[Type]) -> Type:
        if method == "read":
            if args:
                self._err("SE214", "type-mismatch", ".read() takes no arguments in Tier 1", node)
            self._mut_receiver(node)
            return STR
        if method == "write":
            if len(args) != 1 or not isinstance(ts[0], TStr):
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
