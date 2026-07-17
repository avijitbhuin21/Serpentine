"""Backend A: typed AST -> Rust source. rustc is the borrow-check oracle (RESEARCH.md section 4).

Emits structured Rust (not linearized SIR) so the generated code stays readable
and rustc's own borrow checker re-validates every ownership decision.
Identifier mangling: v_<name> locals, f_<name> functions, m_<name> modules.
"""

import ast
import re
from pathlib import Path

from .frontend import Module, Program
from .ptypes import (Type, TBool, TClass, TDict, TExc, TFile, TFloat, TInt, TList, TNone,
                     TOptional, TShared, TStr, TTuple, TWeak, mangle_type, subst_type,
                     walk_types)
from .typecheck import FuncSig, TIter, TypeChecker

PRELUDE = (Path(__file__).parent / "prelude.rs").read_text(encoding="utf-8")


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", name)


def struct_name(t: TClass) -> str:
    """The Rust struct name for a class instantiation."""
    base = f"C_{t.module}_{t.name}"
    if t.args:
        base += "__" + "_".join(mangle_type(a) for a in t.args)
    return _sanitize(base)


def rust_type(t: Type) -> str:
    """Map a Tier-0/1 type to its Rust representation."""
    if isinstance(t, TInt):
        return "i64"
    if isinstance(t, TFloat):
        return "f64"
    if isinstance(t, TBool):
        return "bool"
    if isinstance(t, TStr):
        return "String"
    if isinstance(t, TNone):
        return "()"
    if isinstance(t, TList):
        return f"Vec<{rust_type(t.elem)}>"
    if isinstance(t, TDict):
        return f"SerpDict<{rust_type(t.key)}, {rust_type(t.value)}>"
    if isinstance(t, TTuple):
        return "(" + ", ".join(rust_type(i) for i in t.items) + ")"
    if isinstance(t, TOptional):
        return f"Option<{rust_type(t.inner)}>"
    if isinstance(t, TClass):
        return struct_name(t)
    if isinstance(t, TShared):
        return f"Rc<RefCell<{rust_type(t.inner)}>>"
    if isinstance(t, TWeak):
        return f"std::rc::Weak<RefCell<{rust_type(t.inner)}>>"
    if isinstance(t, TExc):
        return "SerpErr"
    if isinstance(t, TFile):
        return "SerpFile"
    raise CodegenError(f"no Rust type for {t}")


class CodegenError(Exception):
    """Internal error: the checker accepted something the backend cannot emit."""


def needs_clone(t: Type) -> bool:
    """Copy-semantics types that are not Rust-Copy (String, Shared handles, tuples of them)."""
    if isinstance(t, (TStr, TShared, TWeak, TExc)):
        return True
    if isinstance(t, TTuple):
        return any(needs_clone(i) for i in t.items)
    if isinstance(t, TOptional):
        return needs_clone(t.inner)
    return False


class RustGen:
    """Whole-program Rust code generator."""

    def __init__(self, tc: TypeChecker):
        self.tc = tc
        self.program = tc.program
        self.out: list[str] = []
        self.indent = 0
        self.try_ctx: list[tuple[str, str]] = []   # (label, exc_var) of enclosing try blocks

    def _q(self, code: str) -> str:
        """Propagate a fallible expression: `?` normally, break-to-handler inside try."""
        if not self.try_ctx:
            return f"{code}?"
        label, exc_var = self.try_ctx[-1]
        return (f"(match {code} {{ Ok(__v) => __v, "
                f"Err(__e) => {{ {exc_var} = Some(__e); break '{label}; }} }})")

    def generate(self) -> str:
        """Emit the complete Rust program (prelude + structs + modules + entry)."""
        self.out = [PRELUDE, ""]
        entry = self.program.entry
        for t in self._collect_class_insts():
            self._emit_struct(t)
        for mod in self.program.modules.values():
            sigs = [s for (m, _n), s in self.tc.sigs.items()
                    if m == mod.name and not s.is_template
                    and (s.module, s.name) in self.tc.facts]
            if mod.name == entry.name:
                for sig in sigs:
                    self._emit_function(mod, sig, public=False)
                continue
            self._line(f"mod m_{mod.name} {{")
            self.indent += 1
            self._line("use super::*;")
            for sig in sigs:
                self._emit_function(mod, sig, public=True)
            self.indent -= 1
            self._line("}")
            self._line("")
        if entry.entry_call is None:
            raise CodegenError("no entry point: expected `if __name__ == \"__main__\":` guard")
        self._line("fn main() {")
        self._line(f"    if let Err(__e) = f_{entry.entry_call}() {{")
        self._line("        serp_abort(__e);")
        self._line("    }")
        self._line("}")
        return "\n".join(self.out)

    def _collect_class_insts(self) -> list[TClass]:
        """Every concrete class instantiation mentioned anywhere in the program."""
        seen: dict[str, TClass] = {}

        def add(t: Type) -> None:
            for inner in walk_types(t):
                if isinstance(inner, TClass) and not self._has_tvar(inner):
                    key = struct_name(inner)
                    if key not in seen:
                        seen[key] = inner
                        info = self.tc.classes.get((inner.module, inner.name))
                        if info is not None:
                            sub = dict(zip(info.typevars, inner.args))
                            for ft in info.fields.values():
                                add(subst_type(ft, sub))

        for sig in self.tc.sigs.values():
            if sig.is_template:
                continue
            for p in sig.params:
                add(p.typ)
            add(sig.ret)
        for facts in self.tc.facts.values():
            for t in facts.locals.values():
                add(t)
        for t in self.tc.expr_types.values():
            add(t)
        return [seen[k] for k in sorted(seen)]

    def _has_tvar(self, t: Type) -> bool:
        from .ptypes import has_tvar
        return has_tvar(t)

    def _class_has_weak(self, t: TClass, visiting: set | None = None) -> bool:
        visiting = visiting or set()
        key = struct_name(t)
        if key in visiting:
            return False
        visiting.add(key)
        info = self.tc.classes.get((t.module, t.name))
        if info is None:
            return False
        sub = dict(zip(info.typevars, t.args))
        for ft in info.fields.values():
            for inner in walk_types(subst_type(ft, sub)):
                if isinstance(inner, TWeak):
                    return True
                if isinstance(inner, TClass) and self._class_has_weak(inner, visiting):
                    return True
        return False

    def _emit_struct(self, t: TClass) -> None:
        """Emit the struct, PyShow impl, and derives for one class instantiation."""
        info = self.tc.classes.get((t.module, t.name))
        if info is None:
            raise CodegenError(f"unknown class {t}")
        sub = dict(zip(info.typevars, t.args))
        name = struct_name(t)
        derives = ["Clone"]
        if not self._class_has_weak(t):
            derives.append("PartialEq")
        self._line(f"#[derive({', '.join(derives)})]")
        self._line(f"struct {name} {{")
        for f in info.field_order:
            ft = subst_type(info.fields[f], sub)
            self._line(f"    a_{f}: {rust_type(ft)},")
        self._line("}")
        parts = ", ".join(f"{f}={{}}" for f in info.field_order)
        args = ", ".join(f"self.a_{f}.py_repr()" for f in info.field_order)
        self._line(f"impl PyShow for {name} {{")
        self._line(f'    fn py_str(&self) -> String {{ self.py_repr() }}')
        self._line(f'    fn py_repr(&self) -> String {{ format!("{info.name}({parts})", {args}) }}')
        self._line("}")
        self._line("")

    def _line(self, s: str) -> None:
        self.out.append("    " * self.indent + s)

    # ---------- functions ----------

    def _emit_function(self, mod: Module, sig: FuncSig, public: bool) -> None:
        fn = sig.node
        self.mod = mod
        self.sig = sig
        self.facts = self.tc.facts[(sig.module, sig.name)]
        self.ref_bound: set[str] = set()
        self.try_counter = 0
        self.cur_exc: list[str] = []
        params = []
        for p in sig.params:
            rt = rust_type(p.typ)
            if p.conv == "ref":
                params.append(f"v_{p.name}: &{rt}")
            elif p.conv == "mut":
                params.append(f"v_{p.name}: &mut {rt}")
            else:
                params.append(f"mut v_{p.name}: {rt}")
        ret = f" -> SRes<{'()' if isinstance(sig.ret, TNone) else rust_type(sig.ret)}>"
        pub = "pub " if public else ""
        self._line(f"{pub}fn f_{_sanitize(sig.name)}({', '.join(params)}){ret} {{")
        self.indent += 1
        loop_bound = self._loop_bound_names(fn)
        param_names = {p.name for p in sig.params}
        for name, t in self.facts.locals.items():
            if name in param_names or name in loop_bound:
                continue
            self._line(f"let mut v_{name}: {rust_type(t)};")
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        self._emit_block(body)
        if isinstance(sig.ret, TNone):
            self._line("return Ok(());")
        else:
            self._line('panic!("serp: non-None function fell off the end");')
        self.indent -= 1
        self._line("}")
        self._line("")

    def _loop_bound_names(self, fn: ast.FunctionDef) -> set[str]:
        names = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.For):
                targets = [node.target] if isinstance(node.target, ast.Name) else list(node.target.elts)
                for t in targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
        return names

    # ---------- statements ----------

    def _emit_block(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            self._emit_stmt(stmt)

    def _emit_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Pass):
            return
        if isinstance(stmt, ast.Expr):
            self._emit_expr_stmt(stmt.value)
            return
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            self._emit_assign(stmt)
            return
        if isinstance(stmt, ast.AugAssign):
            self._emit_augassign(stmt)
            return
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                self._line("return Ok(());")
            else:
                val = self._coerce(self._expr(stmt.value, "val"),
                                   self._t(stmt.value), self.sig.ret)
                self._line(f"return Ok({val});")
            return
        if isinstance(stmt, ast.Break):
            self._line("break;")
            return
        if isinstance(stmt, ast.Continue):
            self._line("continue;")
            return
        if isinstance(stmt, ast.If):
            self._emit_if(stmt)
            return
        if isinstance(stmt, ast.While):
            self._emit_while(stmt)
            return
        if isinstance(stmt, ast.For):
            self._emit_for(stmt)
            return
        if isinstance(stmt, ast.Try):
            self._emit_try(stmt)
            return
        if isinstance(stmt, ast.Raise):
            self._emit_raise(stmt)
            return
        raise CodegenError(f"cannot emit {type(stmt).__name__}")

    def _emit_raise(self, stmt: ast.Raise) -> None:
        if stmt.exc is None:
            cur = self.cur_exc[-1]
            self._propagate_stmt(f"{cur}.clone()")
            return
        e = stmt.exc
        if isinstance(e, ast.Name):
            err = f'SerpErr::new("{e.id}", String::new())'
        else:
            assert isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
            kind = e.func.id
            if e.args:
                msg = self._expr(e.args[0], "val")
                if kind == "KeyError":
                    msg = f"py_repr(&({msg}))"
            else:
                msg = "String::new()"
            err = f'SerpErr::new("{kind}", {msg})'
        self._propagate_stmt(err)

    def _propagate_stmt(self, err_code: str) -> None:
        """Raise an error value: break to the enclosing handler or return Err."""
        if self.try_ctx:
            label, exc_var = self.try_ctx[-1]
            self._line(f"{exc_var} = Some({err_code});")
            self._line(f"break '{label};")
        else:
            self._line(f"return Err({err_code});")

    def _emit_try(self, stmt: ast.Try) -> None:
        self.try_counter += 1
        n = self.try_counter
        exc, rexc = f"__exc{n}", f"__rexc{n}"
        self._line(f"let mut {exc}: Option<SerpErr> = None;")
        self._line(f"let mut {rexc}: Option<SerpErr> = None;")
        self._line(f"'try{n}: {{")
        self.indent += 1
        self.try_ctx.append((f"try{n}", exc))
        self._emit_block(stmt.body)
        self.try_ctx.pop()
        self.indent -= 1
        self._line("}")
        if stmt.handlers:
            self._line(f"'hnd{n}: {{")
            self.indent += 1
            self._line(f"if let Some(__cur{n}) = {exc}.clone() {{")
            self.indent += 1
            first = True
            for h in stmt.handlers:
                classes = self._handler_class_names(h)
                cond = " || ".join(f'__cur{n}.matches("{c}")' for c in classes)
                kw = "if" if first else "} else if"
                self._line(f"{kw} {cond} {{")
                first = False
                self.indent += 1
                self._line(f"{exc} = None;")
                if h.name:
                    self._line(f"v_{h.name} = __cur{n}.clone();")
                self.try_ctx.append((f"hnd{n}", rexc))
                self.cur_exc.append(f"__cur{n}")
                self._emit_block(h.body)
                self.cur_exc.pop()
                self.try_ctx.pop()
                self.indent -= 1
            self._line("}")
            self.indent -= 1
            self._line("}")
            self.indent -= 1
            self._line("}")
        if stmt.finalbody:
            self._emit_block(stmt.finalbody)
        self._line(f"if let Some(__e) = {rexc} {{")
        self.indent += 1
        self._propagate_stmt("__e")
        self.indent -= 1
        self._line("}")
        self._line(f"if let Some(__e) = {exc} {{")
        self.indent += 1
        self._propagate_stmt("__e")
        self.indent -= 1
        self._line("}")

    def _handler_class_names(self, h: ast.ExceptHandler) -> list[str]:
        if h.type is None:
            return ["Exception"]
        if isinstance(h.type, ast.Name):
            return [h.type.id]
        assert isinstance(h.type, ast.Tuple)
        return [e.id for e in h.type.elts if isinstance(e, ast.Name)]

    def _emit_expr_stmt(self, e: ast.expr) -> None:
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "print":
            self._emit_print(e)
            return
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) \
                and isinstance(e.func.value, ast.Name) and e.func.value.id == "sys" \
                and e.func.attr == "exit" and self.mod.imports_sys:
            code = self._expr(e.args[0], "val") if e.args else "0"
            self._line(f"process::exit(({code}) as i32);")
            return
        t = self._t(e)
        code = self._expr(e, "val")
        if isinstance(t, TNone):
            self._line(f"{code};")
        else:
            self._line(f"let _ = {code};")

    def _emit_print(self, e: ast.Call) -> None:
        if not e.args:
            self._line('println!();')
            return
        parts = [f"py_str({self._expr(a, 'ref')})" for a in e.args]
        if len(parts) == 1:
            self._line(f'println!("{{}}", {parts[0]});')
        else:
            self._line(f'println!("{{}}", [{", ".join(parts)}].join(" "));')

    def _emit_assign(self, stmt: ast.Assign | ast.AnnAssign) -> None:
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
        assert stmt.value is not None
        if isinstance(target, ast.Name):
            declared = self.facts.locals[target.id]
            val = self._coerce(self._expr(stmt.value, "val", expect=declared),
                               self._t(stmt.value), declared)
            self._line(f"v_{target.id} = {val};")
            return
        if isinstance(target, ast.Subscript):
            cont_t = self._t(target.value)
            shared = isinstance(cont_t, TShared)
            if shared:
                cont_t = cont_t.inner
            if isinstance(cont_t, TList):
                elem = cont_t.elem
                val = self._coerce(self._expr(stmt.value, "val", expect=elem),
                                   self._t(stmt.value), elem)
                recv = self._recv(target.value, True) if shared else self._expr(target.value, "mut")
                idx = self._expr(target.slice, "val")
                self._line(f"{self._q(f'serp_idx_set({recv}, {idx}, {val})')};")
                return
            if isinstance(cont_t, TDict):
                val = self._coerce(self._expr(stmt.value, "val", expect=cont_t.value),
                                   self._t(stmt.value), cont_t.value)
                recv = self._recv(target.value, True) if shared else self._expr(target.value, "mut")
                key = self._expr(target.slice, "val")
                self._line(f"({recv}).set({key}, {val});")
                return
        if isinstance(target, ast.Attribute):
            base_t = self._t(target.value)
            ft = self._t(target)
            val = self._coerce(self._expr(stmt.value, "val", expect=ft),
                               self._t(stmt.value), ft)
            if isinstance(base_t, TShared):
                guard = self._q(f"shared_mut({self._expr(target.value, 'ref')})")
                self._line(f"{guard}.a_{target.attr} = {val};")
                return
            place = self._place(target.value, mut=True)
            self._line(f"{place}.a_{target.attr} = {val};")
            return
        raise CodegenError("unsupported assignment target")

    def _emit_augassign(self, stmt: ast.AugAssign) -> None:
        if isinstance(stmt.target, ast.Name):
            t = self.facts.locals[stmt.target.id]
            cur = self._expr(stmt.target, "val")
            rhs = self._expr(stmt.value, "val")
            code = self._binop_code(stmt.op, cur, rhs, t, self._t(stmt.value))
            self._line(f"v_{stmt.target.id} = {code};")
            return
        if isinstance(stmt.target, ast.Subscript):
            elem_t = self._t(stmt.target)
            rhs = self._expr(stmt.value, "val")
            place = self._expr(stmt.target, "mut")
            code = self._binop_code(stmt.op, "(*__t)", "__rhs", elem_t, self._t(stmt.value))
            self._line(f"{{ let __rhs = {rhs}; let __t = {place}; *__t = {code}; }}")
            return
        if isinstance(stmt.target, ast.Attribute):
            elem_t = self._t(stmt.target)
            rhs = self._expr(stmt.value, "val")
            place = self._expr(stmt.target, "mut")
            code = self._binop_code(stmt.op, "(*__t)", "__rhs", elem_t, self._t(stmt.value))
            self._line(f"{{ let __rhs = {rhs}; let __t = {place}; *__t = {code}; }}")
            return
        raise CodegenError("unsupported augmented assignment target")

    def _emit_if(self, stmt: ast.If) -> None:
        cond = self._expr(stmt.test, "val")
        self._line(f"if {cond} {{")
        self.indent += 1
        self._emit_block(stmt.body)
        self.indent -= 1
        if stmt.orelse:
            if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                self._line("} else {")
                self.indent += 1
                self._emit_if(stmt.orelse[0])
                self.indent -= 1
                self._line("}")
            else:
                self._line("} else {")
                self.indent += 1
                self._emit_block(stmt.orelse)
                self.indent -= 1
                self._line("}")
        else:
            self._line("}")

    def _emit_while(self, stmt: ast.While) -> None:
        if isinstance(stmt.test, ast.Constant) and stmt.test.value is True:
            self._line("loop {")
        else:
            self._line(f"while {self._expr(stmt.test, 'val')} {{")
        self.indent += 1
        self._emit_block(stmt.body)
        self.indent -= 1
        self._line("}")

    def _emit_for(self, stmt: ast.For) -> None:
        kind = self.tc.loop_iter_kind.get(id(stmt), "list")
        targets = [stmt.target] if isinstance(stmt.target, ast.Name) else list(stmt.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        new_refs: set[str] = set()
        cast_lines: list[str] = []

        if kind == "range":
            it = stmt.iter
            assert isinstance(it, ast.Call)
            args = [self._expr(a, "val") for a in it.args]
            if len(args) == 1:
                rng = self._q(f"serp_range(0, {args[0]}, 1)")
            elif len(args) == 2:
                rng = self._q(f"serp_range({args[0]}, {args[1]}, 1)")
            else:
                rng = self._q(f"serp_range({args[0]}, {args[1]}, {args[2]})")
            self._line(f"for v_{names[0]} in {rng} {{")
        elif kind == "enumerate":
            it = stmt.iter
            assert isinstance(it, ast.Call)
            seq = self._expr(it.args[0], "ref")
            self._line(f"for (v_{names[0]}, v_{names[1]}) in ({seq}).iter().enumerate() {{")
            cast_lines.append(f"let v_{names[0]} = v_{names[0]} as i64;")
            new_refs.add(names[1])
        elif kind in ("keys", "values", "items"):
            it = stmt.iter
            assert isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute)
            recv = self._expr(it.func.value, "ref")
            if kind == "items":
                self._line(f"for (v_{names[0]}, v_{names[1]}) in ({recv}).items_it() {{")
                new_refs.update(names)
            else:
                self._line(f"for v_{names[0]} in ({recv}).{kind}_it() {{")
                new_refs.add(names[0])
        else:
            seq = self._expr(stmt.iter, "ref")
            elem_t = self._t_loop_elem(stmt)
            if isinstance(elem_t, (TInt, TFloat, TBool)):
                self._line(f"for v_{names[0]} in ({seq}).iter().copied() {{")
            else:
                self._line(f"for v_{names[0]} in ({seq}).iter() {{")
                new_refs.add(names[0])

        self.indent += 1
        for cl in cast_lines:
            self._line(cl)
        saved = set(self.ref_bound)
        self.ref_bound |= new_refs
        self._emit_block(stmt.body)
        self.ref_bound = saved
        self.indent -= 1
        self._line("}")

    def _t_loop_elem(self, stmt: ast.For) -> Type:
        it_t = self._t(stmt.iter)
        if isinstance(it_t, TList):
            return it_t.elem
        if isinstance(it_t, TIter):
            return it_t.elem[0]
        raise CodegenError("unknown loop element type")

    # ---------- expressions ----------

    def _t(self, node: ast.expr) -> Type:
        t = self.tc.expr_types.get(id(node))
        if t is None:
            raise CodegenError(f"untyped expression {ast.dump(node)[:60]}")
        return t

    def _coerce(self, code: str, src: Type, dst: Type) -> str:
        """Wrap a value expression when the static type needs Option adaptation."""
        if isinstance(dst, TOptional) and not isinstance(src, (TOptional, TNone)):
            return f"Some({code})"
        if isinstance(dst, TOptional) and isinstance(src, TNone):
            return "None"
        if isinstance(dst, TFloat) and isinstance(src, TInt):
            return f"(({code}) as f64)"
        return code

    def _expr(self, node: ast.expr, mode: str, expect: Type | None = None) -> str:
        if isinstance(node, ast.Constant):
            return self._const(node, mode)
        if isinstance(node, ast.Name):
            return self._name(node, mode)
        if isinstance(node, ast.Subscript):
            return self._subscript(node, mode)
        if isinstance(node, ast.List):
            elems_t = self._t(node)
            assert isinstance(elems_t, TList)
            parts = [self._coerce(self._expr(e, "val", expect=elems_t.elem),
                                  self._t(e), elems_t.elem) for e in node.elts]
            return self._wrap_ref(f"vec![{', '.join(parts)}]", mode)
        if isinstance(node, ast.Dict):
            return self._dict_literal(node, mode)
        if isinstance(node, ast.Tuple):
            parts = [self._expr(e, "val") for e in node.elts]
            return self._wrap_ref(f"({', '.join(parts)})", mode)
        if isinstance(node, ast.JoinedStr):
            return self._wrap_ref(self._fstring(node), mode)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node, mode)
        if isinstance(node, ast.BinOp):
            code = self._binop_code(node.op, self._expr(node.left, "val"),
                                    self._expr(node.right, "val"),
                                    self._t(node.left), self._t(node.right))
            return self._wrap_ref(code, mode)
        if isinstance(node, ast.BoolOp):
            op = "&&" if isinstance(node.op, ast.And) else "||"
            parts = [f"({self._expr(v, 'val')})" for v in node.values]
            return self._wrap_ref(f"({f' {op} '.join(parts)})", mode)
        if isinstance(node, ast.Compare):
            return self._wrap_ref(self._compare(node), mode)
        if isinstance(node, ast.IfExp):
            t = self._t(node)
            c = self._expr(node.test, "val")
            a = self._coerce(self._expr(node.body, "val"), self._t(node.body), t)
            b = self._coerce(self._expr(node.orelse, "val"), self._t(node.orelse), t)
            return self._wrap_ref(f"(if {c} {{ {a} }} else {{ {b} }})", mode)
        if isinstance(node, ast.Call):
            return self._call(node, mode)
        if isinstance(node, ast.Attribute):
            return self._attribute(node, mode)
        raise CodegenError(f"cannot emit expression {type(node).__name__}")

    def _place(self, e: ast.expr, mut: bool) -> str:
        """Render an lvalue path expression (field chains auto-deref in Rust)."""
        if isinstance(e, ast.Name):
            return f"v_{e.id}"
        if isinstance(e, ast.Attribute):
            base_t = self._t(e.value)
            if isinstance(base_t, TShared):
                guard = self._q(f"shared_mut({self._expr(e.value, 'ref')})") if mut \
                    else self._q(f"shared_ref({self._expr(e.value, 'ref')})")
                return f"{guard}.a_{e.attr}"
            return f"{self._place(e.value, mut)}.a_{e.attr}"
        if isinstance(e, ast.Subscript):
            base_t = self._t(e.value)
            idx = self._expr(e.slice, "val")
            if isinstance(base_t, TShared):
                base_t = base_t.inner
            if isinstance(base_t, TList):
                if mut:
                    recv = self._expr(e.value, "mut")
                    return f"(*{self._q(f'serp_idx_mut({recv}, {idx})')})"
                recv = self._expr(e.value, "ref")
                return f"(*{self._q(f'serp_idx({recv}, {idx})')})"
            if isinstance(base_t, TDict):
                if mut:
                    recv = self._expr(e.value, "mut")
                    return f"(*{self._q(f'({recv}).get_mut(&({idx}))')})"
                recv = self._expr(e.value, "ref")
                return f"(*{self._q(f'({recv}).get_ref(&({idx}))')})"
        raise CodegenError("unsupported place expression")

    def _attribute(self, node: ast.Attribute, mode: str) -> str:
        if isinstance(node.value, ast.Name) and node.value.id == "sys" and self.mod.imports_sys:
            if node.attr == "argv":
                return self._wrap_ref("serp_argv()", mode)
            raise CodegenError(f"cannot emit sys.{node.attr}")
        t = self._t(node)
        base_t = self._t(node.value)
        if isinstance(base_t, TShared):
            guard = self._q(f"shared_ref({self._expr(node.value, 'ref')})")
            code = f"{guard}.a_{node.attr}"
            if mode == "mut":
                guard = self._q(f"shared_mut({self._expr(node.value, 'ref')})")
                return f"&mut {guard}.a_{node.attr}"
            if mode == "ref":
                return f"&{code}"
            if needs_clone(t) or not t.is_copy():
                return f"{code}.clone()"
            return code
        code = f"{self._place(node.value, mut=(mode == 'mut'))}.a_{node.attr}"
        if mode == "mut":
            return f"&mut {code}"
        if mode == "ref":
            return f"&{code}"
        if needs_clone(t):
            return f"{code}.clone()"
        return code

    def _wrap_ref(self, code: str, mode: str) -> str:
        if mode == "ref":
            return f"&({code})"
        if mode == "mut":
            raise CodegenError("temporary cannot be mutably borrowed")
        return code

    def _const(self, node: ast.Constant, mode: str) -> str:
        v = node.value
        if isinstance(v, bool):
            return self._wrap_ref("true" if v else "false", mode)
        if isinstance(v, int):
            return self._wrap_ref(f"{v}i64", mode)
        if isinstance(v, float):
            return self._wrap_ref(f"{v!r}f64", mode)
        if isinstance(v, str):
            esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
            return self._wrap_ref(f'"{esc}".to_string()', mode)
        if v is None:
            return self._wrap_ref("None", mode)
        raise CodegenError(f"cannot emit literal {v!r}")

    def _name(self, node: ast.Name, mode: str) -> str:
        name = node.id
        t = self.facts.locals.get(name)
        if t is None:
            const = self.tc.constants.get((self.mod.name, name))
            if const is not None:
                cnode = self.mod.constants[name].value
                assert isinstance(cnode, ast.Constant)
                self.tc.expr_types[id(cnode)] = const
                return self._const(cnode, mode)
            raise CodegenError(f"unknown name {name}")
        narrowed = id(node) in self.tc.narrowed_uses
        is_ref = name in self.ref_bound or \
            (name in {p.name for p in self.sig.params} and
             next(p.conv for p in self.sig.params if p.name == name) in ("ref", "mut"))
        base = f"v_{name}"
        if mode == "mut":
            if name in {p.name for p in self.sig.params} and \
                    next(p.conv for p in self.sig.params if p.name == name) == "mut":
                return base
            return f"&mut {base}"
        if mode == "ref":
            if narrowed:
                return f"&({self._name(node, 'val')})"
            return base if is_ref else f"&{base}"
        if narrowed:
            assert isinstance(t, TOptional)
            inner = t.inner
            if needs_clone(inner):
                return f"{base}.clone().unwrap()"
            return f"{base}.unwrap()"
        if is_ref:
            if needs_clone(t):
                return f"{base}.clone()"
            if isinstance(t, (TInt, TFloat, TBool)):
                return f"(*{base})"
            return f"{base}.clone()" if t.is_copy() else base
        if needs_clone(t):
            return f"{base}.clone()"
        return base

    def _subscript(self, node: ast.Subscript, mode: str) -> str:
        base_t = self._t(node.value)
        if isinstance(base_t, TShared):
            inner = base_t.inner
            idx = self._expr(node.slice, "val")
            if isinstance(inner, TList):
                if mode == "mut":
                    return self._q(f"serp_idx_mut({self._recv(node.value, True)}, {idx})")
                code = self._q(f"serp_idx({self._recv(node.value, False)}, {idx})")
                elem = inner.elem
            else:
                assert isinstance(inner, TDict)
                if mode == "mut":
                    return self._q(f"({self._recv(node.value, True)}).get_mut(&({idx}))")
                code = self._q(f"({self._recv(node.value, False)}).get_ref(&({idx}))")
                elem = inner.value
            if mode == "ref":
                return code
            if needs_clone(elem) or not elem.is_copy():
                return f"{code}.clone()"
            return f"(*{code})"
        if isinstance(base_t, TList):
            idx = self._expr(node.slice, "val")
            if mode == "mut":
                return self._q(f"serp_idx_mut({self._expr(node.value, 'mut')}, {idx})")
            recv = self._expr(node.value, "ref")
            code = self._q(f"serp_idx({recv}, {idx})")
            if mode == "ref":
                return code
            elem = base_t.elem
            if needs_clone(elem) or not elem.is_copy():
                return f"{code}.clone()"
            return f"(*{code})"
        if isinstance(base_t, TDict):
            key = self._expr(node.slice, "val")
            if mode == "mut":
                return self._q(f"({self._expr(node.value, 'mut')}).get_mut(&({key}))")
            recv = self._expr(node.value, "ref")
            code = self._q(f"({recv}).get_ref(&({key}))")
            if mode == "ref":
                return code
            val_t = base_t.value
            if needs_clone(val_t) or not val_t.is_copy():
                return f"{code}.clone()"
            return f"(*{code})"
        if isinstance(base_t, TTuple):
            assert isinstance(node.slice, ast.Constant)
            i = node.slice.value
            recv = self._expr(node.value, "ref")
            code = f"({recv}).{i}"
            item = base_t.items[i]
            if mode == "ref":
                return f"&{code}"
            if mode == "val":
                return f"{code}.clone()" if needs_clone(item) else code
        raise CodegenError("unsupported subscript")

    def _dict_literal(self, node: ast.Dict, mode: str) -> str:
        t = self._t(node)
        assert isinstance(t, TDict)
        lines = [f"{{ let mut __d: {rust_type(t)} = SerpDict::new();"]
        for k, v in zip(node.keys, node.values):
            assert k is not None
            kv = self._expr(k, "val")
            vv = self._coerce(self._expr(v, "val", expect=t.value), self._t(v), t.value)
            lines.append(f"__d.set({kv}, {vv});")
        lines.append("__d }")
        return self._wrap_ref(" ".join(lines), mode)

    def _fstring(self, node: ast.JoinedStr) -> str:
        fmt_parts: list[str] = []
        args: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                fmt_parts.append(str(part.value).replace("{", "{{").replace("}", "}}")
                                 .replace("\\", "\\\\").replace('"', '\\"')
                                 .replace("\n", "\\n").replace("\t", "\\t"))
                continue
            assert isinstance(part, ast.FormattedValue)
            spec = ""
            if part.format_spec is not None:
                assert isinstance(part.format_spec, ast.JoinedStr)
                spec = "".join(str(c.value) for c in part.format_spec.values
                               if isinstance(c, ast.Constant))
            if part.conversion == 114:  # !r
                fmt_parts.append("{}")
                args.append(f"py_repr({self._expr(part.value, 'ref')})")
            elif spec == "":
                fmt_parts.append("{}")
                args.append(f"py_str({self._expr(part.value, 'ref')})")
            elif re.fullmatch(r"\.(\d+)f", spec):
                n = spec[1:-1]
                fmt_parts.append(f"{{:.{n}}}")
                args.append(self._expr(part.value, "val"))
            elif re.fullmatch(r"[<>^]\d+", spec):
                fmt_parts.append(f"{{:{spec}}}")
                args.append(self._expr(part.value, "val"))
            elif spec == "d":
                fmt_parts.append("{}")
                args.append(self._expr(part.value, "val"))
            else:
                raise CodegenError(f"unsupported f-string format spec '{spec}'")
        fmt = "".join(fmt_parts)
        if args:
            return f'format!("{fmt}", {", ".join(args)})'
        return f'"{fmt}".to_string()'

    def _unary(self, node: ast.UnaryOp, mode: str) -> str:
        t = self._t(node.operand)
        v = self._expr(node.operand, "val")
        if isinstance(node.op, ast.Not):
            return self._wrap_ref(f"(!({v}))", mode)
        if isinstance(node.op, ast.USub):
            if isinstance(t, TInt):
                if isinstance(node.operand, ast.Constant):
                    return self._wrap_ref(f"(-{v})", mode)
                return self._wrap_ref(self._q(f"serp_neg_i({v})"), mode)
            return self._wrap_ref(f"(-({v}))", mode)
        return self._wrap_ref(f"({v})", mode)

    def _binop_code(self, op: ast.operator, l: str, r: str, lt: Type, rt: Type) -> str:
        if isinstance(lt, TStr) and isinstance(rt, TStr) and isinstance(op, ast.Add):
            return f'format!("{{}}{{}}", {l}, {r})'
        both_int = isinstance(lt, TInt) and isinstance(rt, TInt)
        if both_int:
            table = {ast.Add: "serp_add_i", ast.Sub: "serp_sub_i", ast.Mult: "serp_mul_i",
                     ast.FloorDiv: "serp_floordiv_i", ast.Mod: "serp_mod_i",
                     ast.Pow: "serp_pow_i", ast.Div: "serp_div_i"}
            return self._q(f"{table[type(op)]}({l}, {r})")
        lf = f"(({l}) as f64)" if isinstance(lt, TInt) else l
        rf = f"(({r}) as f64)" if isinstance(rt, TInt) else r
        if isinstance(op, ast.Add):
            return f"({lf} + {rf})"
        if isinstance(op, ast.Sub):
            return f"({lf} - {rf})"
        if isinstance(op, ast.Mult):
            return f"({lf} * {rf})"
        if isinstance(op, ast.Div):
            return self._q(f"serp_div_f({lf}, {rf})")
        if isinstance(op, ast.FloorDiv):
            return self._q(f"serp_floordiv_f({lf}, {rf})")
        if isinstance(op, ast.Mod):
            return self._q(f"serp_mod_f({lf}, {rf})")
        if isinstance(op, ast.Pow):
            return f"({lf}).powf({rf})"
        raise CodegenError(f"unsupported operator {type(op).__name__}")

    CMP = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}

    def _compare(self, node: ast.Compare) -> str:
        op0 = node.ops[0]
        if isinstance(op0, (ast.Is, ast.IsNot)):
            assert isinstance(node.left, ast.Name)
            method = "is_none" if isinstance(op0, ast.Is) else "is_some"
            return f"v_{node.left.id}.{method}()"
        if isinstance(op0, (ast.In, ast.NotIn)):
            ct = self._t(node.comparators[0])
            l = self._expr(node.left, "val")
            c = self._expr(node.comparators[0], "ref")
            if isinstance(ct, TDict):
                code = f"({c}).contains(&({l}))"
            elif isinstance(ct, TList):
                code = f"({c}).contains(&({l}))"
            else:
                code = f"py_contains_str({c}, &({l}))"
            return f"(!{code})" if isinstance(op0, ast.NotIn) else code
        operands = [node.left] + list(node.comparators)
        types = [self._t(o) for o in operands]
        has_float = any(isinstance(t, TFloat) for t in types)
        vals = []
        for o, t in zip(operands, types):
            if not t.is_copy():
                vals.append(self._expr(o, "ref"))
                continue
            v = self._expr(o, "val")
            if has_float and isinstance(t, TInt):
                v = f"(({v}) as f64)"
            vals.append(v)
        if len(node.ops) == 1:
            return f"({vals[0]} {self.CMP[type(node.ops[0])]} {vals[1]})"
        temps = [f"__c{i}" for i in range(len(vals))]
        lets = " ".join(f"let {tmp} = {v};" for tmp, v in zip(temps, vals))
        conds = " && ".join(f"{temps[i]} {self.CMP[type(op)]} {temps[i + 1]}"
                            for i, op in enumerate(node.ops))
        return f"{{ {lets} ({conds}) }}"

    # ---------- calls ----------

    def _call(self, node: ast.Call, mode: str) -> str:
        if isinstance(node.func, ast.Attribute):
            return self._wrap_ref(self._method_call(node), mode)
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if id(node) in self.tc.move_calls:
            return self._expr(node.args[0], mode)
        if id(node) in self.tc.ctor_calls:
            return self._wrap_ref(self._ctor_call(node), mode)
        if name == "share":
            v = self._expr(node.args[0], "val")
            return self._wrap_ref(f"serp_share({v})", mode)
        if name == "downgrade":
            s = self._expr(node.args[0], "ref")
            return self._wrap_ref(f"serp_downgrade({s})", mode)
        if name == "upgrade":
            w = self._expr(node.args[0], "ref")
            return self._wrap_ref(f"serp_upgrade({w})", mode)
        if name == "open":
            path = self._expr(node.args[0], "ref")
            fmode = self._expr(node.args[1], "ref") if len(node.args) > 1 else '&"r".to_string()'
            return self._wrap_ref(self._q(f"serp_open({path}, {fmode})"), mode)
        target = self.tc.call_targets.get(id(node))
        if target is not None:
            return self._wrap_ref(self._user_call(node, self.tc.sigs[target]), mode)
        sig = self.tc._resolve_callee(self.mod, name)
        if sig is not None:
            return self._wrap_ref(self._user_call(node, sig), mode)
        return self._wrap_ref(self._builtin_call(node, name), mode)

    def _ctor_call(self, node: ast.Call) -> str:
        cmod, cname, args = self.tc.ctor_calls[id(node)]
        t = TClass(cmod, cname, args)
        info = self.tc.classes[(cmod, cname)]
        sub = dict(zip(info.typevars, args))
        parts = []
        for arg, fname in zip(node.args, info.field_order):
            ft = subst_type(info.fields[fname], sub)
            parts.append(f"a_{fname}: "
                         + self._coerce(self._expr(arg, "val", expect=ft), self._t(arg), ft))
        return f"{struct_name(t)} {{ {', '.join(parts)} }}"

    def _user_call(self, node: ast.Call, sig: FuncSig) -> str:
        args = []
        for a, p in zip(node.args, sig.params):
            if p.conv == "ref":
                args.append(self._expr(a, "ref"))
            elif p.conv == "mut":
                args.append(self._expr(a, "mut"))
            else:
                args.append(self._coerce(self._expr(a, "val", expect=p.typ), self._t(a), p.typ))
        qual = ""
        if sig.module != self.mod.name:
            qual = f"m_{sig.module}::"
        return self._q(f"{qual}f_{_sanitize(sig.name)}({', '.join(args)})")

    def _builtin_call(self, node: ast.Call, name: str) -> str:
        args = node.args
        if name == "print":
            raise CodegenError("print used as an expression")
        if name == "len":
            t = self._t(args[0])
            if isinstance(t, TShared):
                r = self._recv(args[0], False)
                t = t.inner
            else:
                r = self._expr(args[0], "ref")
            if isinstance(t, TList):
                return f"(({r}).len() as i64)"
            if isinstance(t, TDict):
                return f"({r}).len_i()"
            return f"py_len_str({r})"
        if name == "sum":
            t = self._t(args[0])
            assert isinstance(t, TList)
            r = self._expr(args[0], "ref")
            return self._q(f"serp_sum_i({r})") if isinstance(t.elem, TInt) else self._q(f"serp_sum_f({r})")
        if name in ("min", "max"):
            if len(args) == 1:
                r = self._expr(args[0], "ref")
                return self._q(f"serp_{name}_list({r}, \"{name}\")")
            a = self._expr(args[0], "val")
            b = self._expr(args[1], "val")
            return f"serp_{name}2({a}, {b})"
        if name == "abs":
            t = self._t(args[0])
            v = self._expr(args[0], "val")
            return self._q(f"serp_abs_i({v})") if isinstance(t, TInt) else f"(({v}) as f64).abs()"
        if name == "str":
            return f"py_str({self._expr(args[0], 'ref')})"
        if name == "int":
            t = self._t(args[0])
            if isinstance(t, TStr):
                return self._q(f"py_int_from_str({self._expr(args[0], 'ref')})")
            if isinstance(t, TFloat):
                return self._q(f"py_int_from_f({self._expr(args[0], 'val')})")
            if isinstance(t, TBool):
                return f"(({self._expr(args[0], 'val')}) as i64)"
            return self._expr(args[0], "val")
        if name == "float":
            t = self._t(args[0])
            if isinstance(t, TStr):
                return self._q(f"py_float_from_str({self._expr(args[0], 'ref')})")
            if isinstance(t, TInt):
                return f"(({self._expr(args[0], 'val')}) as f64)"
            return self._expr(args[0], "val")
        if name == "bool":
            t = self._t(args[0])
            v = self._expr(args[0], "val")
            if isinstance(t, TInt):
                return f"(({v}) != 0)"
            if isinstance(t, TFloat):
                return f"(({v}) != 0.0)"
            if isinstance(t, TStr):
                return f"(!({v}).is_empty())"
            return v
        if name == "input":
            return self._q("serp_input()")
        raise CodegenError(f"cannot emit builtin '{name}'")

    def _recv(self, recv: ast.expr, want_mut: bool) -> str:
        """Render a method receiver, runtime-borrowing through Shared handles."""
        rt = self._t(recv)
        if isinstance(rt, TShared):
            r = self._expr(recv, "ref")
            if want_mut:
                return f"(&mut *{self._q(f'shared_mut({r})')})"
            return f"(&*{self._q(f'shared_ref({r})')})"
        return self._expr(recv, "mut" if want_mut else "ref")

    def _method_call(self, node: ast.Call) -> str:
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        method = node.func.attr
        rt = self._t(recv)
        inner = rt.inner if isinstance(rt, TShared) else rt
        args = node.args
        if isinstance(inner, TClass):
            target = self.tc.call_targets[id(node)]
            sig = self.tc.sigs[target]
            argv = [self._recv(recv, sig.params[0].conv == "mut")]
            for a, p in zip(args, sig.params[1:]):
                if p.conv == "ref":
                    argv.append(self._expr(a, "ref"))
                elif p.conv == "mut":
                    argv.append(self._expr(a, "mut"))
                else:
                    argv.append(self._coerce(self._expr(a, "val", expect=p.typ),
                                             self._t(a), p.typ))
            qual = f"m_{sig.module}::" if sig.module != self.mod.name else ""
            return self._q(f"{qual}f_{_sanitize(sig.name)}({', '.join(argv)})")
        if isinstance(inner, TFile):
            r = self._recv(recv, True)
            if method == "read":
                return self._q(f"({r}).read_all()")
            if method == "write":
                return self._q(f"({r}).write_str(&({self._expr(args[0], 'val')}))")
            if method == "close":
                return f"({r}).close()"
            raise CodegenError(f"cannot emit file method '{method}'")
        if isinstance(inner, TList):
            elem = inner.elem
            if method == "append":
                v = self._coerce(self._expr(args[0], "val", expect=elem), self._t(args[0]), elem)
                return f"({self._recv(recv, True)}).push({v})"
            if method == "insert":
                i = self._expr(args[0], "val")
                v = self._coerce(self._expr(args[1], "val", expect=elem), self._t(args[1]), elem)
                return f"serp_insert({self._recv(recv, True)}, {i}, {v})"
            if method == "pop":
                if args:
                    return self._q(f"serp_pop_at({self._recv(recv, True)}, {self._expr(args[0], 'val')})")
                return self._q(f"serp_pop({self._recv(recv, True)})")
            if method == "extend":
                return f"({self._recv(recv, True)}).extend(({self._expr(args[0], 'ref')}).iter().cloned())"
            if method == "clear":
                return f"({self._recv(recv, True)}).clear()"
            if method == "reverse":
                return f"({self._recv(recv, True)}).reverse()"
            if method == "sort":
                if isinstance(elem, TFloat):
                    return f"serp_sort_f({self._recv(recv, True)})"
                return f"({self._recv(recv, True)}).sort()"
        if isinstance(inner, TDict):
            if method == "get":
                return f"({self._recv(recv, False)}).get_opt(&({self._expr(args[0], 'val')}))"
            if method == "pop":
                return self._q(f"({self._recv(recv, True)}).pop_key(&({self._expr(args[0], 'val')}))")
        if isinstance(inner, TStr):
            r = self._recv(recv, False)
            argv = [f"&({self._expr(a, 'val')})" for a in args]
            table = {"strip": "py_strip", "lstrip": "py_lstrip", "rstrip": "py_rstrip",
                     "upper": "py_upper", "lower": "py_lower",
                     "startswith": "py_startswith", "endswith": "py_endswith",
                     "find": "py_find", "replace": "py_replace"}
            if method == "split":
                if args:
                    return self._q(f"py_split({r}, {argv[0]})")
                return f"py_split_ws({r})"
            if method == "join":
                return f"py_join({r}, {self._expr(args[0], 'ref')})"
            if method in table:
                return f"{table[method]}({r}{''.join(', ' + a for a in argv)})"
        raise CodegenError(f"cannot emit method '{method}' on {rt}")


def generate_rust(tc: TypeChecker) -> str:
    """Generate the complete Rust program for a checked Serpentine program."""
    return RustGen(tc).generate()
