"""Type checker: symbols, annotation enforcement, Tier-0 typing, is-None narrowing.

Also enforces the subset (SE201/204/206/207/208/210/211/212/214), call-site move
discipline (SE002/SE003/SE006/SE209), and collects the ownership facts that SIR
lowering and the Rust backend consume.
"""

import ast
from dataclasses import dataclass, field

from .diagnostics import Reporter, Span
from .frontend import Module, Program
from .ptypes import (BOOL, CONV_COPY, CONV_MUT, CONV_OWNED, CONV_REF, FLOAT, INT, NONE, STR,
                     Type, TBool, TDict, TFloat, TInt, TList, TNone, TOptional, TStr, TTuple,
                     parse_annotation)


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

    def run(self) -> None:
        """Check every module: signatures first, then all bodies."""
        for mod in self.program.modules.values():
            self._collect_signatures(mod)
        for mod in self.program.modules.values():
            self._check_constants(mod)
            for fn in mod.functions.values():
                self._check_function(mod, fn)
            if mod.entry_call and mod.entry_call not in mod.functions:
                self.rep.fatal("SE214", "type-mismatch",
                               f"entry guard calls unknown function '{mod.entry_call}'",
                               Span(str(mod.path), 1, 0))

    def _span(self, mod: Module, node: ast.AST) -> Span:
        return Span(str(mod.path), node.lineno, node.col_offset,
                    getattr(node, "end_col_offset", None))

    def _collect_signatures(self, mod: Module) -> None:
        """Parse and validate every function signature in a module."""
        file = str(mod.path)
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
                parsed = parse_annotation(arg.annotation, self.rep, file, allow_wrapper=True)
                conv = parsed.conv
                if conv is None:
                    if parsed.typ.is_copy():
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
            ret = parse_annotation(r, self.rep, file, allow_wrapper=False).typ
            self.sigs[(mod.name, fn.name)] = FuncSig(mod.name, fn.name, params, ret, fn)

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

    def _check_function(self, mod: Module, fn: ast.FunctionDef) -> None:
        sig = self.sigs[(mod.name, fn.name)]
        facts = FuncFacts(sig=sig)
        self.facts[(mod.name, fn.name)] = facts
        self.env: dict[str, tuple[Type, str]] = {}
        self.mod = mod
        self.fn = fn
        self.sig = sig
        self.cur_facts = facts
        self.loop_refs: list[dict[str, str]] = []
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
                           f"function '{fn.name}' returns {sig.ret} but can fall off the end",
                           self._span(mod, fn))

    def _err(self, code: str, name: str, msg: str, node: ast.AST, label: str = "") -> None:
        self.rep.fatal(code, name, msg, self._span(self.mod, node), label)

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
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            self._err("SE201", "unsupported-feature", "try/except is Tier 1, not Tier 0", stmt)
        if isinstance(stmt, (ast.With, ast.Match, ast.Assert, ast.Delete, ast.Global,
                             ast.Nonlocal, ast.Raise, ast.Import, ast.ImportFrom,
                             ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self._err("SE201", "unsupported-feature",
                      f"'{type(stmt).__name__}' is not in the Tier-0 grammar", stmt)
        if isinstance(stmt, ast.Pass):
            return narrow, False
        if isinstance(stmt, ast.Return):
            self._check_return(stmt, narrow)
            return narrow, True
        if isinstance(stmt, (ast.Break, ast.Continue)):
            return narrow, True
        if isinstance(stmt, ast.Expr):
            self._type_expr(stmt.value, narrow)
            return narrow, False
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
                  f"'{type(stmt).__name__}' is not in the Tier-0 grammar", stmt)
        raise AssertionError

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
                      f"assignment of live non-Copy value '{value.id}' — write "
                      f"'move({value.id})' to transfer ownership", value)
        if isinstance(value, ast.Subscript):
            self._err("SE006", "move-out-of-container",
                      "cannot copy a non-Copy element out of a container — use pop(), "
                      "borrow in place, or overwrite", value)

    def _check_annassign(self, stmt: ast.AnnAssign, narrow: dict[str, Type]) -> dict[str, Type]:
        if not isinstance(stmt.target, ast.Name):
            self._err("SE201", "unsupported-feature", "annotated assignment target must be a name", stmt)
        parsed = parse_annotation(stmt.annotation, self.rep, str(self.mod.path), allow_wrapper=True)
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
        self._err("SE201", "unsupported-feature", "unsupported assignment target", stmt)
        raise AssertionError

    def _check_augassign(self, stmt: ast.AugAssign, narrow: dict[str, Type]) -> dict[str, Type]:
        tt = self._type_expr_place(stmt.target, narrow)
        vt = self._type_expr(stmt.value, narrow)
        rt = self._binop_type(stmt.op, tt, vt, stmt)
        if not self._assignable(rt, tt):
            self._err("SE214", "type-mismatch", f"augmented assignment changes type {tt} -> {rt}", stmt)
        if isinstance(stmt.target, ast.Subscript):
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
        self._check_block(stmt.body, pos)
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
        assigned = self._assigned_names(stmt.body)
        body_narrow = {k: v for k, v in narrow.items() if k not in assigned}
        self._check_block(stmt.body, body_narrow)
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
        while isinstance(e, ast.Subscript):
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
            self._err("SE201", "unsupported-feature",
                      "attribute access outside a method call is not Tier 0", node)
        self._err("SE201", "unsupported-feature",
                  f"'{type(node).__name__}' is not in the Tier-0 grammar", node)
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
                self._type_expr(part.value, narrow)
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
        if name in ("eval", "exec", "globals", "locals", "compile", "id", "open",
                    "sorted", "map", "filter", "zip", "any", "all", "type", "isinstance"):
            self._err("SE201", "unsupported-feature", f"'{name}' is not a Tier-0 builtin", node)
        sig = self._resolve_callee(self.mod, name)
        if sig is not None:
            return self._type_user_call(node, sig, narrow)
        return self._type_builtin_call(node, name, narrow)

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
        if not isinstance(arg, ast.Name):
            self._err("SE214", "type-mismatch", "move() takes a variable", arg)
        for scope in self.loop_refs:
            if arg.id in scope:
                self._err("SE007", "move-loop-variable",
                          f"'{arg.id}' is a per-iteration Ref loop variable and cannot be moved",
                          node)
        self.cur_facts.events.append(("move", arg.id, node))
        return t

    def _require_move_for_owned(self, arg: ast.expr, param_desc: str) -> None:
        """SE002 when a live named non-Copy value is passed to an Owned position."""
        if isinstance(arg, ast.Name):
            t = self.env.get(arg.id, (None, None))[0]
            if t is not None and not t.is_copy():
                self._err("SE002", "missing-move",
                          f"passing '{arg.id}' to {param_desc} transfers ownership — write "
                          f"'move({arg.id})'", arg)
        if isinstance(arg, ast.Subscript):
            base_t = self.expr_types.get(id(arg))
            self._err("SE006", "move-out-of-container",
                      "cannot move a non-Copy element out of a container here", arg)

    def _borrow_root(self, e: ast.expr) -> str | None:
        while isinstance(e, ast.Subscript):
            e = e.value
        if isinstance(e, ast.Name):
            return e.id
        return None

    def _mut_borrow_place(self, e: ast.expr, node: ast.AST) -> None:
        root = self._borrow_root(e)
        if root is not None:
            self.cur_facts.events.append(("mut_use", root, node))

    def _check_narrow_invalidation_by_mut(self, e: ast.expr, narrow: dict[str, Type]) -> None:
        root = self._borrow_root(e)
        if root is not None:
            narrow.pop(root, None)

    def _type_user_call(self, node: ast.Call, sig: FuncSig, narrow: dict[str, Type]) -> Type:
        if len(node.args) != len(sig.params):
            self._err("SE214", "type-mismatch",
                      f"'{sig.name}' takes {len(sig.params)} arguments, got {len(node.args)}", node)
        mut_roots: list[str] = []
        ref_roots: list[str] = []
        for arg, p in zip(node.args, sig.params):
            at = self._type_expr(arg, narrow, expect=p.typ)
            if not self._assignable(at, p.typ):
                self._err("SE214", "type-mismatch",
                          f"argument '{p.name}' expects {p.typ}, got {at}", arg)
            if p.conv == CONV_OWNED and not p.typ.is_copy():
                if not (isinstance(arg, ast.Call) and id(arg) in self.move_calls):
                    if isinstance(arg, (ast.Name, ast.Subscript)):
                        self._require_move_for_owned(arg, f"Owned parameter '{p.name}'")
            if p.conv == CONV_MUT:
                root = self._borrow_root(arg)
                if root is not None:
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
                if isinstance(t, TIter):
                    self._err("SE201", "unsupported-feature", "cannot print an iterator", node)
            return NONE
        if name == "len":
            arity(1)
            if not isinstance(ts[0], (TList, TDict, TStr)):
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

        if isinstance(rt, TList):
            return self._type_list_method(node, rt, method, args, ts, narrow)
        if isinstance(rt, TDict):
            return self._type_dict_method(node, rt, method, args, ts, narrow)
        if isinstance(rt, TStr):
            return self._type_str_method(node, method, args, ts)
        self._err("SE214", "type-mismatch", f"{rt} has no method '{method}'", node)
        raise AssertionError

    def _mut_receiver(self, node: ast.Call) -> None:
        assert isinstance(node.func, ast.Attribute)
        root = self._borrow_root(node.func.value)
        if root is not None:
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
