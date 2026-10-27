"""Backend A: typed AST -> Rust source. rustc is the borrow-check oracle.

Emits structured Rust (not linearized SIR) so the generated code stays readable
and rustc's own borrow checker re-validates every ownership decision.
Identifier mangling: v_<name> locals, f_<name> functions, m_<name> modules.
"""

import ast
import re
from pathlib import Path

from .frontend import Module, Program, exc_handler_names
from .ptypes import (NONE, Type, TBool, TByteArray, TBytes, TClass, TDict, TEnum, TExc, TFile,
                     TFloat,
                     TFunc, TInt, TJoin, TList, TNone, TOptional, TPyVal, TSet, TShared, TStr, TThread,
                     TTuple, TUnion, TWeak, mangle_type, subst_type, union_slot, walk_types)
from .typecheck import FuncSig, TIter, TypeChecker

PRELUDE = (Path(__file__).parent / "prelude.rs").read_text(encoding="utf-8")


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", name)


def _esc(s: str) -> str:
    """Escape a Python string for a Rust string literal."""
    return (s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def struct_name(t: TClass) -> str:
    """The Rust struct name for a class instantiation."""
    base = f"C_{t.module}_{t.name}"
    if t.args:
        base += "__" + "_".join(mangle_type(a) for a in t.args)
    return _sanitize(base)


def enum_name(t: "TEnum") -> str:
    """The Rust enum name for an enum class."""
    return _sanitize(f"E_{t.module}_{t.name}")


def union_name(t: "TUnion") -> str:
    """The Rust enum name for a union type."""
    return _sanitize("U_" + "__".join(mangle_type(m) for m in t.members))


def union_variant(i: int) -> str:
    """The Rust variant name for union member index i."""
    return f"V{i}"


def rust_type(t: Type) -> str:
    """Map a Tier-0/1 type to its Rust representation."""
    if isinstance(t, TEnum):
        return enum_name(t)
    if isinstance(t, TInt):
        return "i64"
    if isinstance(t, TFloat):
        return "f64"
    if isinstance(t, TBool):
        return "bool"
    if isinstance(t, TStr):
        return "SStr"
    if isinstance(t, TNone):
        return "()"
    if isinstance(t, TList):
        return f"Vec<{rust_type(t.elem)}>"
    if isinstance(t, TDict):
        return f"SerpDict<{rust_type(t.key)}, {rust_type(t.value)}>"
    if isinstance(t, TSet):
        return f"SerpSet<{rust_type(t.elem)}>"
    if isinstance(t, TTuple):
        return "(" + ", ".join(rust_type(i) for i in t.items) + ")"
    if isinstance(t, TOptional):
        return f"Option<{rust_type(t.inner)}>"
    if isinstance(t, TUnion):
        return union_name(t)
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
    if isinstance(t, TBytes):
        return "SBytes"
    if isinstance(t, TByteArray):
        return "SByteArray"
    if isinstance(t, TPyVal):
        return "PVal"
    if isinstance(t, TFunc):
        params = ", ".join(rust_type(p) for p in t.params)
        return f"Rc<dyn Fn({params}) -> SRes<{rust_type(t.ret)}>>"
    if isinstance(t, TJoin):
        return f"{'STask' if t.task else 'SJoin'}<{send_rust_type(t.ret)}>"
    if isinstance(t, TThread):
        return "SThread"
    raise CodegenError(f"no Rust type for {t}")


def send_rust_type(t: Type) -> str:
    """Rust type of a Send value as it crosses a thread boundary."""
    if isinstance(t, TStr):
        return "String"
    if isinstance(t, TBytes):
        return "Vec<u8>"
    return rust_type(t)


class CodegenError(Exception):
    """Internal error: the checker accepted something the backend cannot emit."""


def needs_clone(t: Type) -> bool:
    """Copy-semantics types that are not Rust-Copy (String, Shared handles, tuples of them)."""
    if isinstance(t, (TStr, TShared, TWeak, TExc, TFunc, TBytes, TPyVal)):
        return True
    if isinstance(t, TTuple):
        return any(needs_clone(i) for i in t.items)
    if isinstance(t, TOptional):
        return needs_clone(t.inner)
    if isinstance(t, TUnion):
        return True
    return False


class RustGen:
    """Whole-program Rust code generator."""

    def __init__(self, tc: TypeChecker):
        self.tc = tc
        self.program = tc.program
        self.out: list[str] = []
        self.indent = 0
        self.try_ctx: list[tuple[str, str]] = []   # (label, exc_var) of enclosing try blocks
        self.try_finals: list[list[ast.stmt]] = []
        self.loop_stack: list[tuple[str | None, int]] = []
        self.loop_counter = 0

    def _q(self, code: str) -> str:
        """Propagate a fallible expression: `?` normally, break-to-handler inside try."""
        if not self.try_ctx:
            return f"serp_tr({code}, {self._tb_args()})?"
        label, exc_var = self.try_ctx[-1]
        return (f"(match {code} {{ Ok(__v) => __v, "
                f"Err(__e) => {{ serp_tb_push({self._tb_args()}); {exc_var} = Some(__e); break '{label}; }} }})")

    def _tb_args(self) -> str:
        """Rust args (file, line, function) naming the current .py source location for tracebacks."""
        mod = getattr(self, "mod", None)
        path = str(getattr(mod, "path", "<unknown>")) if mod is not None else "<unknown>"
        sig = getattr(self, "sig", None)
        func = getattr(sig, "name", "<module>") if sig is not None else "<module>"
        lit = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return f"{lit(path)}, {getattr(self, 'cur_line', 0)}, {lit(func)}"

    def generate(self) -> str:
        """Emit the complete Rust program (prelude + structs + modules + entry)."""
        self.out = [PRELUDE, ""]
        entry = self.program.entry
        for key in sorted(self.tc.enums):
            self._emit_enum(self.tc.enums[key])
        for u in self._collect_union_insts():
            self._emit_union(u)
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
            self._line(f"mod m_{_sanitize(mod.name)} {{")
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
        self._line("    let __main = std::thread::Builder::new().name(\"main\".into()).stack_size(SERP_STACK).spawn(|| {")
        self._line(f"        if let Err(__e) = f_{entry.entry_call}() {{")
        self._line("            serp_abort(__e);")
        self._line("        }")
        self._line("        serp_threads_join_all();")
        self._line("    }).expect(\"spawn main thread\");")
        self._line("    if __main.join().is_err() { std::process::exit(101); }")
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

    def _class_has_func(self, t: TClass, visiting: set | None = None) -> bool:
        """Whether a class instantiation (transitively) stores a function value."""
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
                if isinstance(inner, TFunc):
                    return True
                if isinstance(inner, TClass) and self._class_has_func(inner, visiting):
                    return True
        return False

    def _emit_enum(self, info) -> None:
        """Emit the Rust enum, value/name accessors and PyShow impl for one enum class."""
        name = enum_name(TEnum(info.module, info.name))
        variants = [f"V_{_sanitize(m)}" for m, _ in info.members]
        self._line("#[derive(Clone, Copy, PartialEq)]")
        self._line("#[allow(non_camel_case_types)]")
        self._line(f"enum {name} {{ {', '.join(variants)} }}")
        self._line("")
        self._line(f"impl {name} {{")
        is_int = isinstance(info.value_type, TInt)
        vty = "i64" if is_int else "SStr"
        arms = []
        for (m, v), var in zip(info.members, variants):
            lit = f"{v}i64" if is_int else f'sstr("{_esc(v)}")'
            arms.append(f"{name}::{var} => {lit}")
        self._line(f"    fn evalue(&self) -> {vty} {{ match self {{ {', '.join(arms)} }} }}")
        narms = [f'{name}::{var} => sstr("{m}")'
                 for (m, _), var in zip(info.members, variants)]
        self._line(f"    fn ename(&self) -> SStr {{ match self {{ {', '.join(narms)} }} }}")
        farms = []
        for (m, v), var in zip(info.members, variants):
            pat = f"{v}" if is_int else f'"{_esc(v)}"'
            farms.append(f"{pat} => Ok({name}::{var})")
        arg = "v: i64" if is_int else "v: &SStr"
        subject = "v" if is_int else "v.as_str()"
        self._line(f"    fn from_value({arg}) -> SRes<{name}> {{")
        self._line(f"        match {subject} {{ {', '.join(farms)},")
        self._line(f'            _ => serp_err("ValueError", '
                   f'format!("{{}} is not a valid {info.name}", v.py_repr())) }}')
        self._line("    }")
        self._line("}")
        self._line("")
        self._line(f"impl PyShow for {name} {{")
        if info.base == "IntEnum":
            self._line("    fn py_str(&self) -> String { self.evalue().py_repr() }")
        elif info.base == "StrEnum":
            self._line("    fn py_str(&self) -> String { self.evalue().py_str() }")
        else:
            self._line(f'    fn py_str(&self) -> String '
                       f'{{ format!("{info.name}.{{}}", self.ename().py_str()) }}')
        self._line(f'    fn py_repr(&self) -> String {{ format!("<{info.name}.{{}}: {{}}>", '
                   f'self.ename().py_str(), self.evalue().py_repr()) }}')
        self._line("}")
        self._line("")

    def _emit_union(self, t: TUnion) -> None:
        """Emit the Rust enum, variant accessors and PyShow impl for one union type."""
        name = union_name(t)
        derives = ["Clone"]
        if not any(isinstance(i, (TWeak, TFunc)) for m in t.members for i in walk_types(m)):
            derives.append("PartialEq")
        variants = [f"{union_variant(i)}({rust_type(m)})" for i, m in enumerate(t.members)]
        self._line(f"#[derive({', '.join(derives)})]")
        self._line("#[allow(non_camel_case_types, dead_code)]")
        self._line(f"enum {name} {{ {', '.join(variants)} }}")
        self._line(f"impl {name} {{")
        for i, m in enumerate(t.members):
            var, mt = union_variant(i), rust_type(m)
            self._line(f"    fn is_{i}(&self) -> bool "
                       f"{{ matches!(self, {name}::{var}(_)) }}")
            self._line(f"    fn as_{i}(&self) -> &{mt} {{ match self "
                       f"{{ {name}::{var}(__x) => __x, _ => unreachable!() }} }}")
            self._line(f"    fn mut_{i}(&mut self) -> &mut {mt} {{ match self "
                       f"{{ {name}::{var}(__x) => __x, _ => unreachable!() }} }}")
            self._line(f"    fn into_{i}(self) -> {mt} {{ match self "
                       f"{{ {name}::{var}(__x) => __x, _ => unreachable!() }} }}")
        self._line("}")
        arms_s = ", ".join(
            f"{name}::{union_variant(i)}(__x) => "
            + ("{ let _ = __x; \"None\".to_string() }" if isinstance(m, TNone)
               else "__x.py_str()")
            for i, m in enumerate(t.members))
        arms_r = ", ".join(
            f"{name}::{union_variant(i)}(__x) => "
            + ("{ let _ = __x; \"None\".to_string() }" if isinstance(m, TNone)
               else "__x.py_repr()")
            for i, m in enumerate(t.members))
        self._line(f"impl PyShow for {name} {{")
        self._line(f"    fn py_str(&self) -> String {{ match self {{ {arms_s} }} }}")
        self._line(f"    fn py_repr(&self) -> String {{ match self {{ {arms_r} }} }}")
        self._line("}")
        self._line("")

    def _collect_union_insts(self) -> list[TUnion]:
        """Every concrete union type mentioned anywhere in the program."""
        seen: dict[str, TUnion] = {}

        def add(t: Type) -> None:
            for inner in walk_types(t):
                if isinstance(inner, TUnion) and not self._has_tvar(inner):
                    seen.setdefault(union_name(inner), inner)

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
        for cls in self._collect_class_insts():
            info = self.tc.classes.get((cls.module, cls.name))
            if info is not None:
                sub = dict(zip(info.typevars, cls.args))
                for ft in info.fields.values():
                    add(subst_type(ft, sub))
        return [seen[k] for k in sorted(seen)]

    def _emit_struct(self, t: TClass) -> None:
        """Emit the struct, PyShow impl, and derives for one class instantiation."""
        info = self.tc.classes.get((t.module, t.name))
        if info is None:
            raise CodegenError(f"unknown class {t}")
        sub = dict(zip(info.typevars, t.args))
        name = struct_name(t)
        has_func = self._class_has_func(t)
        derives = ["Clone"]
        if not self._class_has_weak(t) and not has_func:
            derives.append("PartialEq")
        self._line(f"#[derive({', '.join(derives)})]")
        self._line(f"struct {name} {{")
        for f in info.field_order:
            ft = subst_type(info.fields[f], sub)
            self._line(f"    a_{f}: {rust_type(ft)},")
        self._line("}")
        self._line(f"impl PyShow for {name} {{")
        qual = "" if t.module == self.program.entry.name else f"m_{_sanitize(t.module)}::"
        has_repr = not info.typevars and "__repr__" in info.methods
        repr_body = (f"match {qual}f_{_sanitize(info.name + '.__repr__')}(self) "
                     f"{{ Ok(__s) => __s.py_str(), Err(__e) => serp_abort(__e) }}")
        str_body = (f"match {qual}f_{_sanitize(info.name + '.__str__')}(self) "
                    f"{{ Ok(__s) => __s.py_str(), Err(__e) => serp_abort(__e) }}")
        has_str = not info.typevars and "__str__" in info.methods
        if has_str:
            self._line(f"    fn py_str(&self) -> String {{ {str_body} }}")
        elif has_repr or not has_func:
            self._line(f"    fn py_str(&self) -> String {{ self.py_repr() }}")
        else:
            self._line(f"    fn py_str(&self) -> String {{ unreachable!() }}")
        if has_repr:
            self._line(f"    fn py_repr(&self) -> String {{ {repr_body} }}")
        elif has_func:
            self._line(f"    fn py_repr(&self) -> String {{ unreachable!() }}")
        else:
            parts = ", ".join(f"{f}={{}}" for f in info.field_order)
            args = ", ".join(f"self.a_{f}.py_repr()" for f in info.field_order)
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
        self.scope_types: dict[str, Type] = {}
        self.tmp_counter = 0
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
        self.loop_bound = loop_bound
        param_names = {p.name for p in sig.params}
        try_assigned = self._try_assigned_names(fn.body)
        for name, t in self.facts.locals.items():
            if name in param_names or name in loop_bound:
                continue
            init = self._zero_init(t) if name in try_assigned else None
            if init is not None:
                self._line(f"let mut v_{name}: {rust_type(t)} = {init};")
            else:
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
            if isinstance(node, ast.For) and id(node) not in self.tc.for_lowered:
                targets = [node.target] if isinstance(node.target, ast.Name) else list(node.target.elts)
                for t in targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            if isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        names.add(item.optional_vars.id)
        return names

    # ---------- statements ----------

    def _emit_block(self, stmts: list[ast.stmt]) -> None:
        saved_scope = dict(self.scope_types)
        saved_ref = set(self.ref_bound)
        for stmt in stmts:
            self._emit_stmt(stmt)
        self.scope_types = saved_scope
        self.ref_bound = saved_ref

    def _emit_stmt(self, stmt: ast.stmt) -> None:
        if getattr(stmt, "lineno", None):
            self.cur_line = stmt.lineno
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
        if isinstance(stmt, (ast.Break, ast.Continue)):
            self._emit_loop_jump("break" if isinstance(stmt, ast.Break) else "continue")
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
        if isinstance(stmt, ast.With):
            self._emit_with(stmt)
            return
        if isinstance(stmt, ast.Try):
            self._emit_try(stmt)
            return
        if isinstance(stmt, ast.Raise):
            self._emit_raise(stmt)
            return
        raise CodegenError(f"cannot emit {type(stmt).__name__}")

    def _emit_with(self, stmt: ast.With) -> None:
        """`with open(...) as f:` — inner block whose end drops (closes) the file."""
        item = stmt.items[0]
        assert isinstance(item.optional_vars, ast.Name)
        name = item.optional_vars.id
        ctx = self._expr(item.context_expr, "val")
        self._line("{")
        self.indent += 1
        self._line(f"let mut v_{name}: SerpFile = {ctx};")
        saved = self.scope_types.get(name)
        self.scope_types[name] = TFile()
        self._emit_block(stmt.body)
        if saved is None:
            self.scope_types.pop(name, None)
        else:
            self.scope_types[name] = saved
        self.indent -= 1
        self._line("}")

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
                    msg = f"({msg}).to_string()"
            else:
                msg = "String::new()"
            err = f'SerpErr::new("{kind}", {msg})'
        self._propagate_stmt(err)

    def _propagate_stmt(self, err_code: str) -> None:
        """Raise an error value: break to the enclosing handler or return Err."""
        self._line(f"serp_tb_push({self._tb_args()});")
        if self.try_ctx:
            label, exc_var = self.try_ctx[-1]
            self._line(f"{exc_var} = Some({err_code});")
            self._line(f"break '{label};")
        else:
            self._line(f"return Err({err_code});")

    def _try_assigned_names(self, body: list[ast.stmt]) -> set[str]:
        """Names assigned anywhere inside a try body (rustc cannot prove them initialized after it)."""
        out: set[str] = set()

        def collect(nodes: list[ast.stmt], in_try: bool) -> None:
            for n in nodes:
                if in_try and isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            out.add(t.id)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(n, ast.Try):
                    collect(n.body, True)
                    for h in n.handlers:
                        collect(h.body, in_try)
                    collect(n.orelse, in_try)
                    collect(n.finalbody, in_try)
                    continue
                for field in ("body", "orelse"):
                    collect(getattr(n, field, None) or [], in_try)

        collect(body, False)
        return out

    @staticmethod
    def _zero_init(t: Type) -> str | None:
        """A Rust initializer for Copy scalars and Optionals; None when the type has no trivial default."""
        if isinstance(t, TInt):
            return "0"
        if isinstance(t, TFloat):
            return "0.0"
        if isinstance(t, TBool):
            return "false"
        if isinstance(t, TOptional):
            return "None"
        return None

    def _emit_loop_jump(self, kw: str) -> None:
        """Emit break/continue: run pending finally bodies, label the jump when it crosses a try block."""
        label, depth = self.loop_stack[-1] if self.loop_stack else (None, len(self.try_ctx))
        saved_ctx, saved_fin = self.try_ctx, self.try_finals
        for i in range(len(saved_fin) - 1, depth - 1, -1):
            if saved_fin[i]:
                self.try_ctx, self.try_finals = saved_ctx[:i], saved_fin[:i]
                self._emit_block(saved_fin[i])
        self.try_ctx, self.try_finals = saved_ctx, saved_fin
        if label is not None and len(self.try_ctx) > depth:
            self._line(f"{kw} '{label};")
        else:
            self._line(f"{kw};")

    def _loop_prefix(self, body: list[ast.stmt]) -> str:
        """Open a loop scope; returns a `'lpN: ` label prefix when a jump inside a try needs it."""
        label = None
        if self._jump_in_try(body, False):
            self.loop_counter += 1
            label = f"lp{self.loop_counter}"
        self.loop_stack.append((label, len(self.try_ctx)))
        return f"'{label}: " if label else ""

    def _jump_in_try(self, nodes: list[ast.stmt], in_try: bool) -> bool:
        """True when a break/continue of the current loop sits inside a nested try/with."""
        for n in nodes:
            if isinstance(n, (ast.Break, ast.Continue)):
                if in_try:
                    return True
                continue
            if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            inner = in_try or isinstance(n, (ast.Try, ast.With, ast.AsyncWith))
            kids: list[ast.stmt] = []
            for field in ("body", "orelse", "finalbody"):
                kids += getattr(n, field, None) or []
            for h in getattr(n, "handlers", None) or []:
                kids += h.body
            for c in getattr(n, "cases", None) or []:
                kids += c.body
            if kids and self._jump_in_try(kids, inner):
                return True
        return False

    def _emit_try(self, stmt: ast.Try) -> None:
        self.try_counter += 1
        n = self.try_counter
        exc, rexc = f"__exc{n}", f"__rexc{n}"
        self._line(f"let mut {exc}: Option<SerpErr> = None;")
        self._line(f"let mut {rexc}: Option<SerpErr> = None;")
        self._line(f"'try{n}: {{")
        self.indent += 1
        self.try_ctx.append((f"try{n}", exc))
        self.try_finals.append(stmt.finalbody)
        self._emit_block(stmt.body)
        self.try_finals.pop()
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
                self._line("serp_tb_clear();")
                if h.name:
                    self._line(f"v_{h.name} = __cur{n}.clone();")
                self.try_ctx.append((f"hnd{n}", rexc))
                self.try_finals.append(stmt.finalbody)
                self.cur_exc.append(f"__cur{n}")
                self._emit_block(h.body)
                self.cur_exc.pop()
                self.try_finals.pop()
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
            named = ["Exception"]
        elif isinstance(h.type, ast.Name):
            named = [h.type.id]
        else:
            assert isinstance(h.type, ast.Tuple)
            named = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
        out: list[str] = []
        for c in named:
            out += [n for n in exc_handler_names(c, self.tc.user_exc) if n not in out]
        return out

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

    def _hoist(self, code: str) -> str:
        """Bind a value expression to a `let` temp so it is evaluated before a later
        `&mut` borrow of a container it may read from (rustc E0502)."""
        n = getattr(self, "_sv_n", 0)
        self._sv_n = n + 1
        tmp = f"__rhs{n}"
        self._line(f"let {tmp} = {code};")
        return tmp

    def _emit_setitem_call(self, oc: ast.Call) -> None:
        """Emit a `__setitem__` desugar, hoisting non-trivial index/value arguments into
        `let` temps so they are evaluated before the `&mut` receiver borrow (rustc E0502)."""
        args = list(oc.args)
        saved = list(oc.args)
        for i, a in enumerate(args):
            if isinstance(a, (ast.Name, ast.Constant)):
                continue
            t = self._t(a)
            n = getattr(self, "_sv_n", 0)
            self._sv_n = n + 1
            tmp = f"__sv{n}"
            self._line(f"let v_{tmp} = {self._expr(a, 'val')};")
            self.scope_types[tmp] = t
            name = ast.Name(id=tmp, ctx=ast.Load())
            ast.copy_location(name, a)
            self.tc.expr_types[id(name)] = t
            oc.args[i] = name
        try:
            self._line(f"{self._expr(oc, 'val')};")
        finally:
            oc.args[:] = saved

    def _emit_assign(self, stmt: ast.Assign | ast.AnnAssign) -> None:
        oc = self.tc.op_calls.get(id(stmt))
        if oc is not None:
            self._emit_setitem_call(oc)
            return
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
        assert stmt.value is not None
        bind = self.tc.elem_borrow_binds.get(id(stmt))
        if bind is not None:
            name, _root = bind
            val = self._expr(stmt.value, "ref")
            self._line(f"let v_{name} = {val};")
            self.scope_types[name] = self._t(stmt.value)
            self.ref_bound.add(name)
            return
        ibind = self.tc.iter_binds.get(id(stmt))
        if ibind is not None:
            name, _root = ibind
            assert isinstance(stmt.value, ast.Call)
            seq = self._expr(stmt.value.args[0], "ref")
            self._line(f"let mut v_{name} = ({seq}).iter();")
            return
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
                tmp = self._hoist(val)
                recv = self._recv(target.value, True) if shared else self._expr(target.value, "mut")
                idx = self._expr(target.slice, "val")
                self._line(f"{self._q(f'serp_idx_set({recv}, {idx}, {tmp})')};")
                return
            if isinstance(cont_t, TDict):
                val = self._coerce(self._expr(stmt.value, "val", expect=cont_t.value),
                                   self._t(stmt.value), cont_t.value)
                tmp = self._hoist(val)
                recv = self._recv(target.value, True) if shared else self._expr(target.value, "mut")
                key = self._expr(target.slice, "val")
                self._line(f"({recv}).set({key}, {tmp});")
                return
            if isinstance(cont_t, TByteArray):
                recv = self._recv(target.value, True) if shared else self._expr(target.value, "mut")
                idx = self._expr(target.slice, "val")
                val = self._expr(stmt.value, "val")
                self._line(f"{self._q(f'({recv}).set({idx}, {val})')};")
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
        if isinstance(self._t(stmt.test), TPyVal):
            cond = f"pyval_truthy(&({cond}))"
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
            head = "loop {"
        else:
            cond = self._expr(stmt.test, "val")
            if isinstance(self._t(stmt.test), TPyVal):
                cond = f"pyval_truthy(&({cond}))"
            head = f"while {cond} {{"
        self._line(self._loop_prefix(stmt.body) + head)
        self.indent += 1
        self._emit_block(stmt.body)
        self.loop_stack.pop()
        self.indent -= 1
        self._line("}")

    def _for_header(self, iter_node: ast.expr, kind: str, names: list[str]) \
            -> tuple[str, list[str], set[str]]:
        """Build the Rust `for ... in ...` header for a loop or comprehension."""
        new_refs: set[str] = set()
        cast_lines: list[str] = []
        if kind == "range":
            assert isinstance(iter_node, ast.Call)
            args = [self._expr(a, "val") for a in iter_node.args]
            if len(args) == 1:
                rng = self._q(f"serp_range(0, {args[0]}, 1)")
            elif len(args) == 2:
                rng = self._q(f"serp_range({args[0]}, {args[1]}, 1)")
            else:
                rng = self._q(f"serp_range({args[0]}, {args[1]}, {args[2]})")
            return f"for v_{names[0]} in {rng}", cast_lines, new_refs
        if kind == "enumerate":
            assert isinstance(iter_node, ast.Call)
            seq = self._expr(iter_node.args[0], "ref")
            cast_lines.append(f"let v_{names[0]} = v_{names[0]} as i64;")
            new_refs.add(names[1])
            return f"for (v_{names[0]}, v_{names[1]}) in ({seq}).iter().enumerate()", \
                cast_lines, new_refs
        if kind == "zip":
            assert isinstance(iter_node, ast.Call)
            a = self._expr(iter_node.args[0], "ref")
            b = self._expr(iter_node.args[1], "ref")
            new_refs.update(names)
            return f"for (v_{names[0]}, v_{names[1]}) in ({a}).iter().zip(({b}).iter())", \
                cast_lines, new_refs
        if kind == "reversed":
            assert isinstance(iter_node, ast.Call)
            seq = self._expr(iter_node.args[0], "ref")
            elem_t = self._iter_elems(iter_node, kind)[0]
            if isinstance(elem_t, (TInt, TFloat, TBool)):
                return f"for v_{names[0]} in ({seq}).iter().rev().copied()", cast_lines, new_refs
            new_refs.add(names[0])
            return f"for v_{names[0]} in ({seq}).iter().rev()", cast_lines, new_refs
        if kind == "str":
            seq = self._expr(iter_node, "ref")
            return f"for v_{names[0]} in py_chars({seq})", cast_lines, new_refs
        if kind in ("bytes", "bytearray"):
            seq = self._expr(iter_node, "ref")
            fn = "pyb_ints" if kind == "bytes" else "pyba_ints"
            return f"for v_{names[0]} in {fn}({seq})", cast_lines, new_refs
        if kind == "pyval":
            seq = self._expr(iter_node, "ref")
            return f"for v_{names[0]} in {self._q(f'pyval_iter({seq})')}", cast_lines, new_refs
        if kind in ("keys", "values", "items"):
            assert isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Attribute)
            recv = self._expr(iter_node.func.value, "ref")
            if kind == "items":
                new_refs.update(names)
                return f"for (v_{names[0]}, v_{names[1]}) in ({recv}).items_it()", \
                    cast_lines, new_refs
            new_refs.add(names[0])
            return f"for v_{names[0]} in ({recv}).{kind}_it()", cast_lines, new_refs
        if kind == "set":
            seq = self._expr(iter_node, "ref")
            elem_t = self._iter_elems(iter_node, kind)[0]
            if isinstance(elem_t, (TInt, TFloat, TBool)):
                return f"for v_{names[0]} in ({seq}).iter_it().copied()", cast_lines, new_refs
            new_refs.add(names[0])
            return f"for v_{names[0]} in ({seq}).iter_it()", cast_lines, new_refs
        seq = self._expr(iter_node, "ref")
        elem_t = self._iter_elems(iter_node, kind)[0]
        if isinstance(elem_t, (TInt, TFloat, TBool)):
            return f"for v_{names[0]} in ({seq}).iter().copied()", cast_lines, new_refs
        new_refs.add(names[0])
        return f"for v_{names[0]} in ({seq}).iter()", cast_lines, new_refs

    def _iter_elems(self, iter_node: ast.expr, kind: str) -> tuple[Type, ...]:
        """Element types yielded by an iterable expression."""
        it_t = self._t(iter_node)
        if isinstance(it_t, TList):
            return (it_t.elem,)
        if isinstance(it_t, TSet):
            return (it_t.elem,)
        if isinstance(it_t, TStr):
            return (TStr(),)
        if isinstance(it_t, TPyVal):
            return (TPyVal(),)
        if isinstance(it_t, TIter):
            return it_t.elem
        raise CodegenError("unknown iterator element type")

    def _emit_for(self, stmt: ast.For) -> None:
        lowered = self.tc.for_lowered.get(id(stmt))
        if lowered is not None:
            self._emit_lowered_for(stmt, lowered)
            return
        kind = self.tc.loop_iter_kind.get(id(stmt), "list")
        targets = [stmt.target] if isinstance(stmt.target, ast.Name) else list(stmt.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        header, cast_lines, new_refs = self._for_header(stmt.iter, kind, names)
        self._line(f"{self._loop_prefix(stmt.body)}{header} {{")
        self.indent += 1
        for cl in cast_lines:
            self._line(cl)
        saved = set(self.ref_bound)
        self.ref_bound |= new_refs
        self._emit_block(stmt.body)
        self.loop_stack.pop()
        self.ref_bound = saved
        self.indent -= 1
        self._line("}")

    def _emit_lowered_for(self, stmt: ast.For, lowered: list) -> None:
        """Emit a user-iterator for loop: labeled loop + __next__ match skeleton."""
        for name in self.tc.for_lowered_names.get(id(stmt), []):
            if name in self.loop_bound:
                self._line(f"let mut v_{name}: {rust_type(self.facts.locals[name])};")
        wh = lowered[-1]
        if len(lowered) == 2:
            self._emit_stmt(lowered[0])
        tr = wh.body[0]
        step = tr.body[0]
        call = step.value
        tgt = step.targets[0].id
        self.sfor_counter = getattr(self, "sfor_counter", 0) + 1
        lbl = f"sfor{self.sfor_counter}"
        self._line(f"'{lbl}: loop {{")
        self.indent += 1
        raw = self._class_method_call_code(call)
        if self.try_ctx:
            outer, exc_var = self.try_ctx[-1]
            prop = f"{exc_var} = Some(__e); break '{outer};"
        else:
            prop = "return Err(__e);"
        self._line(f"match {raw} {{")
        self.indent += 1
        self._line(f"Ok(__v) => {{ v_{tgt} = __v; }}")
        self._line(f'Err(__e) => {{ if __e.matches("StopIteration") '
                   f'{{ break \'{lbl}; }} {prop} }}')
        self.indent -= 1
        self._line("}")
        self.loop_stack.append((lbl, len(self.try_ctx)))
        self._emit_block(wh.body[1:])
        self.loop_stack.pop()
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
        if isinstance(dst, TNone) and isinstance(src, TNone):
            return "()"
        if isinstance(dst, TOptional) and not isinstance(src, (TOptional, TNone)):
            return f"Some({self._coerce(code, src, dst.inner)})"
        if isinstance(dst, TOptional) and isinstance(src, TNone):
            return "None"
        if isinstance(dst, TFloat) and isinstance(src, TInt):
            return f"(({code}) as f64)"
        if isinstance(dst, TUnion) and not isinstance(src, TUnion):
            slot = union_slot(src, dst)
            if slot is None:
                raise CodegenError(f"{src} is not a member of {dst}")
            inner = self._coerce(code, src, dst.members[slot])
            return f"{union_name(dst)}::{union_variant(slot)}({inner})"
        if isinstance(dst, TPyVal) and not isinstance(src, TPyVal):
            return self._pyval_from(code, src)
        return code

    def _pyval_from(self, code: str, src: Type) -> str:
        """Convert a typed Rust value expression into a PVal."""
        if isinstance(src, TPyVal):
            return code
        if isinstance(src, TNone):
            return "pyval_none()"
        if isinstance(src, TBool):
            return f"pyval_bool({code})"
        if isinstance(src, TInt):
            return f"pyval_int({code})"
        if isinstance(src, TFloat):
            return f"pyval_float({code})"
        if isinstance(src, TStr):
            return f"pyval_str({code})"
        if isinstance(src, TBytes):
            return f"pyval_bytes({code})"
        if isinstance(src, TList):
            inner = self._pyval_from("__e.clone()", src.elem)
            return (f"pyval_list(({code}).iter()"
                    f".map(|__e: &{rust_type(src.elem)}| {inner})"
                    f".collect::<Vec<PVal>>())")
        if isinstance(src, TDict):
            inner = self._pyval_from("__v.clone()", src.value)
            kconv = self._pyval_from("__k.clone()", src.key)
            return (f"{{ let __src = &({code}); let mut __m: SerpDict<PVal, PVal> = "
                    f"SerpDict::new(); for (__k, __v) in __src.items_it() "
                    f"{{ __m.set({kconv}, {inner}); }} pyval_dict(__m) }}")
        raise CodegenError(f"cannot convert {src} to PyVal")

    def _expr(self, node: ast.expr, mode: str, expect: Type | None = None) -> str:
        oc = self.tc.op_calls.get(id(node))
        if oc is not None:
            return self._expr(oc, mode, expect)
        if isinstance(node, ast.Lambda):
            return self._wrap_ref(self._lambda_code(node), mode)
        if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)):
            return self._comp_expr(node, mode, expect)
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
        if isinstance(node, ast.Set):
            t = self._t(node)
            assert isinstance(t, TSet)
            lines = [f"{{ let mut __s: {rust_type(t)} = SerpSet::new();"]
            for e in node.elts:
                val = self._coerce(self._expr(e, "val", expect=t.elem), self._t(e), t.elem)
                lines.append(f"__s.add({val});")
            lines.append("__s }")
            return self._wrap_ref(" ".join(lines), mode)
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
            nc = getattr(node, "_narrow", None)
            if nc is not None:
                ut, mt = nc
                code = self._call(node, "val")
                return self._wrap_ref(f"({code}).into_{union_slot(mt, ut)}()", mode)
            return self._call(node, mode)
        if isinstance(node, ast.Attribute):
            return self._attribute(node, mode)
        raise CodegenError(f"cannot emit expression {type(node).__name__}")

    def _comp_expr(self, node: ast.expr, mode: str, expect: Type | None = None) -> str:
        """Emit a list/dict comprehension as a Rust block expression."""
        assert isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp))
        kind = self.tc.loop_iter_kind[id(node)]
        gen = node.generators[0]
        targets = [gen.target] if isinstance(gen.target, ast.Name) else list(gen.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        elems = self._iter_elems(gen.iter, kind)
        header, cast_lines, new_refs = self._for_header(gen.iter, kind, names)
        t = self._t(node)
        if expect is not None and type(expect) is type(t) and expect != t:
            t = expect
        self.tmp_counter += 1
        c = f"__comp{self.tmp_counter}"
        saved_refs = set(self.ref_bound)
        saved_scope = dict(self.scope_types)
        self.ref_bound |= new_refs
        for name, et in zip(names, elems):
            self.scope_types[name] = et
        cond = self._expr(gen.ifs[0], "val") if gen.ifs else None
        if isinstance(node, ast.DictComp):
            assert isinstance(t, TDict)
            decl = f"let mut {c}: {rust_type(t)} = SerpDict::new();"
            k = self._expr(node.key, "val")
            v = self._coerce(self._expr(node.value, "val", expect=t.value),
                             self._t(node.value), t.value)
            push = f"{c}.set({k}, {v});"
        elif isinstance(node, ast.SetComp):
            assert isinstance(t, TSet)
            decl = f"let mut {c}: {rust_type(t)} = SerpSet::new();"
            elem = self._coerce(self._expr(node.elt, "val", expect=t.elem),
                                self._t(node.elt), t.elem)
            push = f"{c}.add({elem});"
        else:
            assert isinstance(t, TList)
            decl = f"let mut {c}: {rust_type(t)} = Vec::new();"
            elem = self._coerce(self._expr(node.elt, "val", expect=t.elem),
                                self._t(node.elt), t.elem)
            push = f"{c}.push({elem});"
        self.ref_bound = saved_refs
        self.scope_types = saved_scope
        inner = push if cond is None else f"if {cond} {{ {push} }}"
        casts = " ".join(cast_lines)
        code = f"{{ {decl} {header} {{ {casts} {inner} }} {c} }}"
        return self._wrap_ref(code, mode)

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
            base = self._place(e.value, mut)
            if isinstance(e.value, (ast.Name, ast.Attribute)) \
                    and id(e.value) in self.tc.narrowed_uses:
                vslot = self.tc.narrow_variant.get(id(e.value))
                if vslot is not None:
                    base = f"{base}.mut_{vslot}()" if mut else f"{base}.as_{vslot}()"
                else:
                    base = f"{base}.as_mut().unwrap()" if mut else f"{base}.as_ref().unwrap()"
            return f"{base}.a_{e.attr}"
        if isinstance(e, ast.Subscript) and id(e) not in self.tc.op_calls:
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
        if isinstance(e, (ast.Subscript, ast.Call, ast.BinOp, ast.UnaryOp, ast.Compare)):
            return f"({self._expr(e, 'val')})"
        raise CodegenError("unsupported place expression")

    def _attribute(self, node: ast.Attribute, mode: str) -> str:
        if isinstance(node.value, ast.Name) and node.value.id == "sys" and self.mod.imports_sys:
            if node.attr == "argv":
                return self._wrap_ref("serp_argv()", mode)
            raise CodegenError(f"cannot emit sys.{node.attr}")
        member = self.tc.enum_members.get(id(node))
        if member is not None:
            emod, ename, mname = member
            return self._wrap_ref(f"{enum_name(TEnum(emod, ename))}::V_{_sanitize(mname)}", mode)
        t = self._t(node)
        base_t = self._t(node.value)
        if isinstance(base_t, TEnum):
            recv = self._expr(node.value, "ref")
            call = "evalue" if node.attr == "value" else "ename"
            return self._wrap_ref(f"({recv}).{call}()", mode)
        if isinstance(base_t, TThread):
            recv = self._expr(node.value, "ref")
            if node.attr == "name":
                return self._wrap_ref(f"serp_thread_name({recv})", mode)
            if node.attr == "ident":
                return self._wrap_ref(
                    f"{{ let __i = serp_thread_ident({recv}); if __i == 0 {{ None }} else {{ Some(__i) }} }}",
                    mode)
            return self._wrap_ref(f"serp_thread_daemon({recv})", mode)
        narrowed = id(node) in self.tc.narrowed_uses
        slot = self.tc.narrow_variant.get(id(node))
        if narrowed and not isinstance(base_t, TShared):
            code = f"{self._place(node.value, mut=(mode == 'mut'))}.a_{node.attr}"
            if slot is not None:
                if mode == "mut":
                    return f"{code}.mut_{slot}()"
                if mode == "ref":
                    return f"{code}.as_{slot}()"
                if needs_clone(t) or not t.is_copy():
                    return f"{code}.as_{slot}().clone()"
                return f"(*{code}.as_{slot}())"
            if mode == "mut":
                return f"{code}.as_mut().unwrap()"
            if mode == "ref":
                return f"{code}.as_ref().unwrap()"
            if needs_clone(t) or not t.is_copy():
                return f"{code}.clone().unwrap()"
            return f"{code}.unwrap()"
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
        place = self._place(node.value, mut=(mode == "mut"))
        if isinstance(node.value, (ast.Name, ast.Attribute)) \
                and id(node.value) in self.tc.narrowed_uses:
            vslot = self.tc.narrow_variant.get(id(node.value))
            if vslot is not None:
                place = f"{place}.mut_{vslot}()" if mode == "mut" else f"{place}.as_{vslot}()"
            else:
                place = f"{place}.as_mut().unwrap()" if mode == "mut" \
                    else f"{place}.as_ref().unwrap()"
        code = f"{place}.a_{node.attr}"
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
            return f"&mut ({code})"
        return code

    def _const(self, node: ast.Constant, mode: str) -> str:
        v = node.value
        if isinstance(v, bool):
            return self._wrap_ref("true" if v else "false", mode)
        if isinstance(v, int):
            return self._wrap_ref(f"{v}i64", mode)
        if isinstance(v, float):
            if v != v:
                return self._wrap_ref("f64::NAN", mode)
            if v == float("inf"):
                return self._wrap_ref("f64::INFINITY", mode)
            if v == float("-inf"):
                return self._wrap_ref("f64::NEG_INFINITY", mode)
            return self._wrap_ref(f"{v!r}f64", mode)
        if isinstance(v, str):
            esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") \
                .replace("\r", "\\r").replace("\t", "\\t")
            return self._wrap_ref(f'sstr("{esc}")', mode)
        if isinstance(v, bytes):
            if not v:
                return self._wrap_ref("sbytes(Vec::new())", mode)
            items = ", ".join(f"{b}u8" for b in v)
            return self._wrap_ref(f"sbytes(vec![{items}])", mode)
        if v is None:
            return self._wrap_ref("None", mode)
        raise CodegenError(f"cannot emit literal {v!r}")

    def _name(self, node: ast.Name, mode: str) -> str:
        name = node.id
        fref = self.tc.func_value_refs.get(id(node))
        if fref is not None:
            ft = self._t(node)
            return self._wrap_ref(self._func_ref_code(fref, ft), mode)
        t = self.scope_types.get(name)
        if t is None:
            t = self.facts.locals.get(name)
        if t is None:
            cmod, cname = self.mod.name, name
            if (cmod, cname) not in self.tc.constants and name in self.mod.imports:
                cmod, cname = self.mod.imports[name]
            const = self.tc.constants.get((cmod, cname))
            if const is not None:
                cnode = self.tc.program.modules[cmod].constants[cname].value
                assert isinstance(cnode, ast.Constant)
                self.tc.expr_types[id(cnode)] = const
                return self._const(cnode, mode)
            raise CodegenError(f"unknown name {name}")
        narrowed = id(node) in self.tc.narrowed_uses
        slot = self.tc.narrow_variant.get(id(node))
        is_ref = name in self.ref_bound or \
            (name in {p.name for p in self.sig.params} and
             next(p.conv for p in self.sig.params if p.name == name) in ("ref", "mut"))
        base = f"v_{name}"
        if mode == "mut":
            if slot is not None:
                return f"{base}.mut_{slot}()"
            if narrowed:
                return f"{base}.as_mut().unwrap()"
            if name in {p.name for p in self.sig.params} and \
                    next(p.conv for p in self.sig.params if p.name == name) == "mut":
                return base
            return f"&mut {base}"
        if mode == "ref":
            if slot is not None:
                return f"{base}.as_{slot}()"
            if narrowed:
                t0 = self._t(node)
                if isinstance(t0, TOptional) and isinstance(t0.inner, (TInt, TFloat, TBool)):
                    return f"&({self._name(node, 'val')})"
                return f"{base}.as_ref().unwrap()"
            return base if is_ref else f"&{base}"
        if slot is not None:
            member = self._t(node)
            if needs_clone(member) or not member.is_copy():
                return f"{base}.as_{slot}().clone()"
            return f"(*{base}.as_{slot}())"
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
            return f"{base}.clone()"
        if needs_clone(t):
            return f"{base}.clone()"
        return base

    def _subscript(self, node: ast.Subscript, mode: str) -> str:
        base_t = self._t(node.value)
        inner0 = base_t.inner if isinstance(base_t, TShared) else base_t
        if isinstance(inner0, TStr):
            recv = self._recv(node.value, False) if isinstance(base_t, TShared) \
                else self._expr(node.value, "ref")
            if isinstance(node.slice, ast.Slice):
                lo = "None" if node.slice.lower is None \
                    else f"Some({self._expr(node.slice.lower, 'val')})"
                hi = "None" if node.slice.upper is None \
                    else f"Some({self._expr(node.slice.upper, 'val')})"
                return self._wrap_ref(f"py_str_slice({recv}, {lo}, {hi})", mode)
            idx = self._expr(node.slice, "val")
            return self._wrap_ref(self._q(f"py_str_idx({recv}, {idx})"), mode)
        if isinstance(inner0, (TBytes, TByteArray)):
            recv = self._recv(node.value, False) if isinstance(base_t, TShared) \
                else self._expr(node.value, "ref")
            is_b = isinstance(inner0, TBytes)
            if isinstance(node.slice, ast.Slice):
                lo = "None" if node.slice.lower is None \
                    else f"Some({self._expr(node.slice.lower, 'val')})"
                hi = "None" if node.slice.upper is None \
                    else f"Some({self._expr(node.slice.upper, 'val')})"
                fn = "pyb_slice" if is_b else "pyba_slice"
                return self._wrap_ref(f"{fn}({recv}, {lo}, {hi})", mode)
            idx = self._expr(node.slice, "val")
            if is_b:
                return self._wrap_ref(self._q(f"pyb_index({recv}, {idx})"), mode)
            return self._wrap_ref(self._q(f"({recv}).get({idx})"), mode)
        if isinstance(inner0, TPyVal):
            recv = self._recv(node.value, False) if isinstance(base_t, TShared) \
                else self._expr(node.value, "ref")
            idx_t = self._t(node.slice)
            if isinstance(idx_t, TStr):
                idx = self._expr(node.slice, "ref")
                return self._wrap_ref(self._q(f"pyval_getitem_s({recv}, {idx})"), mode)
            if isinstance(idx_t, TPyVal):
                idx = self._expr(node.slice, "ref")
                return self._wrap_ref(self._q(f"pyval_getitem_v({recv}, {idx})"), mode)
            if isinstance(idx_t, (TFloat, TBool)):
                idx = self._pyval_from(self._expr(node.slice, "val"), idx_t)
                return self._wrap_ref(self._q(f"pyval_getitem_v({recv}, &({idx}))"), mode)
            idx = self._expr(node.slice, "val")
            return self._wrap_ref(self._q(f"pyval_getitem_i({recv}, {idx})"), mode)
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
            item = base_t.items[i]
            if getattr(node, "_destructure", False) and isinstance(node.value, ast.Name) \
                    and not item.is_copy() and mode == "val":
                return f"v_{node.value.id}.{i}"
            recv = self._expr(node.value, "ref")
            code = f"({recv}).{i}"
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
                                 .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
                continue
            assert isinstance(part, ast.FormattedValue)
            spec = ""
            if part.format_spec is not None:
                assert isinstance(part.format_spec, ast.JoinedStr)
                spec = "".join(str(c.value) for c in part.format_spec.values
                               if isinstance(c, ast.Constant))
            lit = '"' + spec.replace("\\", "\\\\").replace('"', '\\"') + '"'
            pt = self._t(part.value)
            if spec == "" and part.conversion == 114:
                fmt_parts.append("{}")
                args.append(f"py_repr({self._expr(part.value, 'ref')})")
            elif spec == "":
                fmt_parts.append("{}")
                args.append(f"py_str({self._expr(part.value, 'ref')})")
            elif part.conversion in (114, 115) or isinstance(pt, TStr):
                conv = "py_repr" if part.conversion == 114 else "py_str"
                fmt_parts.append("{}")
                args.append(f"py_fmt_str(&{conv}({self._expr(part.value, 'ref')}), {lit})")
            elif isinstance(pt, TBool):
                fmt_parts.append("{}")
                args.append(f"py_fmt_int(({self._expr(part.value, 'val')}) as i64, {lit})")
            elif isinstance(pt, TInt):
                fmt_parts.append("{}")
                args.append(f"py_fmt_int({self._expr(part.value, 'val')}, {lit})")
            elif isinstance(pt, TFloat):
                fmt_parts.append("{}")
                args.append(f"py_fmt_float({self._expr(part.value, 'val')}, {lit})")
            else:
                raise CodegenError(f"unsupported f-string format spec '{spec}'")
        fmt = "".join(fmt_parts)
        if args:
            return f'sstring(format!("{fmt}", {", ".join(args)}))'
        return f'sstr("{fmt}")'

    def _unary(self, node: ast.UnaryOp, mode: str) -> str:
        t = self._t(node.operand)
        v = self._expr(node.operand, "val")
        if isinstance(node.op, ast.Not):
            if isinstance(t, TPyVal):
                return self._wrap_ref(f"(!pyval_truthy(&({v})))", mode)
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
            return f'sstring(format!("{{}}{{}}", {l}, {r}))'
        if isinstance(lt, TBytes) and isinstance(rt, TBytes) and isinstance(op, ast.Add):
            return f"pyb_concat(&({l}), &({r}))"
        if isinstance(op, ast.Mult) and isinstance(lt, TBytes) and isinstance(rt, TInt):
            return f"pyb_repeat(&({l}), {r})"
        if isinstance(op, ast.Mult) and isinstance(lt, TInt) and isinstance(rt, TBytes):
            return f"pyb_repeat(&({r}), {l})"
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
            lt = self._t(node.left)
            if isinstance(lt, TPyVal):
                ref = self._expr(node.left, "ref")
                code = f'(pyval_type_name({ref}) == "NoneType")'
                return code if isinstance(op0, ast.Is) else f"(!{code})"
            if isinstance(lt, TUnion):
                slot = union_slot(NONE, lt)
                code = f"{self._place(node.left, mut=False)}.is_{slot}()"
                return code if isinstance(op0, ast.Is) else f"(!{code})"
            method = "is_none" if isinstance(op0, ast.Is) else "is_some"
            if isinstance(node.left, ast.Name):
                return f"v_{node.left.id}.{method}()"
            ref = self._expr(node.left, "ref")
            return f"({ref}).{method}()"
        if isinstance(op0, (ast.In, ast.NotIn)):
            ct = self._t(node.comparators[0])
            if isinstance(ct, TPyVal):
                c = self._expr(node.comparators[0], "ref")
                l = self._coerce(self._expr(node.left, "val", expect=TPyVal()),
                                 self._t(node.left), TPyVal())
                code = self._q(f"pyval_contains({c}, &({l}))")
                return f"(!{code})" if isinstance(op0, ast.NotIn) else code
            l = self._expr(node.left, "val")
            c = self._expr(node.comparators[0], "ref")
            if isinstance(ct, TDict):
                code = f"({c}).contains(&({l}))"
            elif isinstance(ct, (TList, TSet)):
                code = f"({c}).contains(&({l}))"
            elif isinstance(ct, TBytes):
                code = f"pyb_contains({c}, &({l}))"
            else:
                code = f"py_contains_str({c}, &({l}))"
            return f"(!{code})" if isinstance(op0, ast.NotIn) else code
        operands = [node.left] + list(node.comparators)
        types = [self._t(o) for o in operands]
        if any(isinstance(t, TPyVal) for t in types):
            if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                raise CodegenError("PyVal supports only single ==/!= comparisons")
            a = self._coerce(self._expr(operands[0], "val", expect=TPyVal()),
                             types[0], TPyVal())
            b = self._coerce(self._expr(operands[1], "val", expect=TPyVal()),
                             types[1], TPyVal())
            code = f"pyval_eq(&({a}), &({b}))"
            return f"(!{code})" if isinstance(node.ops[0], ast.NotEq) else code
        has_float = any(isinstance(t, TFloat) for t in types)
        has_opt = any(isinstance(t, TOptional) for t in types)
        vals = []
        for o, t in zip(operands, types):
            if not t.is_copy():
                vals.append(self._expr(o, "ref"))
                continue
            v = self._expr(o, "val")
            if has_float and isinstance(t, TInt):
                v = f"(({v}) as f64)"
            if has_opt and not isinstance(t, (TOptional, TNone)):
                v = f"Some({v})"
            vals.append(v)
        if len(node.ops) == 1:
            return f"({vals[0]} {self.CMP[type(node.ops[0])]} {vals[1]})"
        temps = [f"__c{i}" for i in range(len(vals))]
        lets = " ".join(f"let {tmp} = {v};" for tmp, v in zip(temps, vals))
        conds = " && ".join(f"{temps[i]} {self.CMP[type(op)]} {temps[i + 1]}"
                            for i, op in enumerate(node.ops))
        return f"{{ {lets} ({conds}) }}"

    # ---------- calls ----------

    def _func_ref_code(self, key: tuple[str, str], ft: TFunc) -> str:
        """Wrap a module function as an Rc closure value."""
        fmod, fname = key
        qual = f"m_{_sanitize(fmod)}::" if fmod != self.mod.name else ""
        params = ", ".join(f"p{i}: {rust_type(t)}" for i, t in enumerate(ft.params))
        argl = ", ".join(f"p{i}" for i in range(len(ft.params)))
        return (f"(Rc::new(move |{params}| -> SRes<{rust_type(ft.ret)}> "
                f"{{ {qual}f_{_sanitize(fname)}({argl}) }}) as {rust_type(ft)})")

    def _lambda_code(self, node: ast.Lambda) -> str:
        """Emit a capturing lambda as an Rc closure (captures cloned by value)."""
        ft = self._t(node)
        assert isinstance(ft, TFunc)
        caps = self.tc.lambda_caps.get(id(node), [])
        lets = " ".join(f"let v_{n} = v_{n}.clone();" for n, t in caps
                        if needs_clone(t) or not t.is_copy())
        saved_scope = {}
        for a, pt in zip(node.args.args, ft.params):
            saved_scope[a.arg] = self.scope_types.get(a.arg)
            self.scope_types[a.arg] = pt
        saved_ctx, self.try_ctx = self.try_ctx, []
        saved_fin, self.try_finals = self.try_finals, []
        saved_loops, self.loop_stack = self.loop_stack, []
        stmt_body: str | None = None
        if isinstance(ft.ret, TNone):
            saved_out, saved_indent = self.out, self.indent
            self.out, self.indent = [], 0
            st = ast.Expr(value=node.body)
            ast.copy_location(st, node.body)
            self._emit_stmt(st)
            stmt_body = " ".join(s.strip() for s in self.out)
            self.out, self.indent = saved_out, saved_indent
            body = ""
        else:
            body = self._coerce(self._expr(node.body, "val", expect=ft.ret),
                                self._t(node.body), ft.ret)
        self.try_ctx = saved_ctx
        self.try_finals = saved_fin
        self.loop_stack = saved_loops
        for arg_name, prev in saved_scope.items():
            if prev is None:
                self.scope_types.pop(arg_name, None)
            else:
                self.scope_types[arg_name] = prev
        params = ", ".join(f"v_{a.arg}: {rust_type(pt)}"
                           for a, pt in zip(node.args.args, ft.params))
        ret = "()" if isinstance(ft.ret, TNone) else rust_type(ft.ret)
        if stmt_body is not None:
            return (f"{{ {lets} (Rc::new(move |{params}| -> SRes<()> "
                    f"{{ {stmt_body} Ok(()) }}) as {rust_type(ft)}) }}")
        return (f"{{ {lets} (Rc::new(move |{params}| -> SRes<{ret}> "
                f"{{ Ok({body}) }}) as {rust_type(ft)}) }}")

    def _send_args(self, args: list[ast.expr], sig) -> tuple[list[str], list[str]]:
        """Copy Send arguments into `let` bindings usable inside a Send closure."""
        lets, argl = [], []
        for i, (a, p) in enumerate(zip(args, sig.params)):
            if isinstance(p.typ, TClass):
                lets.append(f"let __sp{i} = ({self._expr(a, 'ref')}).clone();")
                argl.append(f"__sp{i}")
                continue
            code = self._coerce(self._expr(a, "val", expect=p.typ), self._t(a), p.typ)
            if isinstance(p.typ, TStr):
                lets.append(f"let __sp{i} = send_str(&({code}));")
                argl.append(f"recv_str(__sp{i})")
            elif isinstance(p.typ, TBytes):
                lets.append(f"let __sp{i} = (*({code}).v).clone();")
                argl.append(f"SBytes {{ v: Rc::new(__sp{i}) }}")
            else:
                lets.append(f"let __sp{i} = {code};")
                argl.append(f"__sp{i}")
        return lets, argl

    def _thread_call(self, node: ast.Call) -> str:
        """Emit Thread(target=..)/Timer(..) as serp_thread_new over a deferred Send closure."""
        info = self.tc.thread_calls[id(node)]
        fmod, fname = info["target"]
        sig = self.tc.sigs[(fmod, fname)]
        qual = f"m_{_sanitize(fmod)}::" if fmod != self.mod.name else ""
        lets, argl = self._send_args(info["args"], sig)
        call = f"{qual}f_{_sanitize(fname)}({', '.join(argl)})"
        body = f"Box::new(move || {{ {call}.map(|_| ()).map_err(|e| (e.kind, e.msg)) }})"
        name = "None"
        if info["name"] is not None:
            name = f"Some(send_str(&({self._expr(info['name'], 'ref')})))"
        daemon = "false"
        if info["daemon"] is not None:
            daemon = self._expr(info["daemon"], "val")
        delay = "0"
        if info["interval"] is not None:
            iv = self._coerce(self._expr(info["interval"], "val", expect=TFloat()),
                              self._t(info["interval"]), TFloat())
            delay = f"(({iv}) * 1000.0) as i64"
        target = '""' if info["timer"] else f'"{fname}"'
        return (f"{{ {' '.join(lets)} serp_thread_new({body}, {name}, {daemon}, {delay}, "
                f"{target}) }}")

    def _spawn_call(self, node: ast.Call) -> str:
        """Emit spawn(f, args...) as serp_spawn over a Send closure (D9)."""
        key = self.tc.spawn_calls[id(node)]
        sig = self.tc.sigs[key]
        fmod, fname = key
        qual = f"m_{_sanitize(fmod)}::" if fmod != self.mod.name else ""
        lets, argl = self._send_args(node.args[1:], sig)
        call = f"{qual}f_{_sanitize(fname)}({', '.join(argl)})"
        if isinstance(sig.ret, TStr):
            body = f"{call}.map(|__r| send_str(&__r))"
        elif isinstance(sig.ret, TBytes):
            body = f"{call}.map(|__r| (*__r.v).clone())"
        else:
            body = call
        ctor = "serp_task_spawn" if self._t(node).task else "serp_spawn"
        return f"{{ {' '.join(lets)} {ctor}(move || {{ {body} }}) }}"

    def _func_value_call(self, node: ast.Call, ft: TFunc) -> str:
        """Emit a call through a first-class function value."""
        fcode = self._expr(node.func, "val")
        args = [self._coerce(self._expr(a, "val", expect=pt), self._t(a), pt)
                for a, pt in zip(node.args, ft.params)]
        return self._q(f"((*({fcode}))({', '.join(args)}))")

    def _call(self, node: ast.Call, mode: str) -> str:
        ftv = self.tc.expr_types.get(id(node.func))
        if isinstance(ftv, TFunc):
            return self._wrap_ref(self._func_value_call(node, ftv), mode)
        if isinstance(node.func, ast.Attribute):
            return self._wrap_ref(self._method_call(node), mode)
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if id(node) in self.tc.move_calls:
            return self._expr(node.args[0], mode)
        if id(node) in self.tc.ctor_calls:
            return self._wrap_ref(self._ctor_call(node), mode)
        ekey = self.tc.enum_calls.get(id(node))
        if ekey is not None:
            info = self.tc.enums[ekey]
            arg = self._expr(node.args[0], "val" if isinstance(info.value_type, TInt) else "ref")
            call = f"{enum_name(TEnum(*ekey))}::from_value({arg})"
            return self._wrap_ref(self._q(call), mode)
        if id(node) in self.tc.isinstance_checks:
            declared, member = self.tc.isinstance_checks[id(node)]
            assert isinstance(declared, TUnion)
            slot = union_slot(member, declared)
            place = self._expr(node.args[0], "ref")
            return self._wrap_ref(f"({place}).is_{slot}()", mode)
        if name == "share":
            v = self._expr(node.args[0], "val")
            return self._wrap_ref(f"serp_share({v})", mode)
        if name == "downgrade":
            s = self._expr(node.args[0], "ref")
            return self._wrap_ref(f"serp_downgrade({s})", mode)
        if name == "upgrade":
            w = self._expr(node.args[0], "ref")
            return self._wrap_ref(f"serp_upgrade({w})", mode)
        if name == "pyval_kind":
            return self._wrap_ref(f"pyval_kind({self._expr(node.args[0], 'ref')})", mode)
        if name == "pyval_json":
            v = self._expr(node.args[0], "ref")
            ea = self._expr(node.args[1], "val")
            cp = self._expr(node.args[2], "val")
            return self._wrap_ref(self._q(f"pyval_json({v}, {ea}, {cp})"), mode)
        if name == "open":
            path = self._expr(node.args[0], "ref")
            fmode = self._expr(node.args[1], "ref") if len(node.args) > 1 else '"r"'
            return self._wrap_ref(self._q(f"serp_open({path}, {fmode})"), mode)
        if name in self.mod.rtlib_imports:
            rf = self.mod.rtlib_imports[name]
            parts = []
            for a, p in zip(node.args, rf.params):
                if p in ("s", "y"):
                    parts.append(self._expr(a, "ref"))
                    continue
                if p == "p":
                    v = self._coerce(self._expr(a, "val", expect=TPyVal()),
                                     self._t(a), TPyVal())
                    parts.append(f"&({v})")
                    continue
                pt = TFloat() if p == "f" else TInt()
                parts.append(self._coerce(self._expr(a, "val", expect=pt), self._t(a), pt))
            code = f"{rf.rust}({', '.join(parts)})"
            if rf.can_raise:
                code = self._q(code)
            return self._wrap_ref(code, mode)
        if id(node) in self.tc.spawn_calls:
            return self._wrap_ref(self._spawn_call(node), mode)
        if id(node) in self.tc.thread_calls:
            return self._wrap_ref(self._thread_call(node), mode)
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
        lit = f"{struct_name(t)} {{ {', '.join(parts)} }}"
        if not info.typevars and "__post_init__" in info.methods:
            qual = "" if cmod == self.mod.name else f"m_{_sanitize(cmod)}::"
            call = f"{qual}f_{_sanitize(cname + '.__post_init__')}(&mut __o)"
            return self._q(f"{{ let mut __o = {lit}; {call}.map(move |_| __o) }}")
        return lit

    def _default_code(self, p) -> str:
        """Render a parameter's literal default value as Rust code."""
        c = p.default
        assert isinstance(c, ast.Constant)
        v = c.value
        if v is None:
            return self._coerce("None", TNone(), p.typ)
        if isinstance(v, bool):
            code, vt = ("true" if v else "false"), TBool()
        elif isinstance(v, int):
            code, vt = f"{v}i64", TInt()
        elif isinstance(v, float):
            code, vt = f"{v!r}f64", TFloat()
        elif isinstance(v, bytes):
            items = ", ".join(f"{b}u8" for b in v)
            code = f"sbytes(vec![{items}])" if v else "sbytes(Vec::new())"
            vt = TBytes()
        else:
            esc = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") \
                .replace("\r", "\\r").replace("\t", "\\t")
            code, vt = f'sstr("{esc}")', TStr()
        return self._coerce(code, vt, p.typ)

    def _union_ref_arg(self, a: ast.expr, p) -> str:
        """Wrap a non-union argument into a `Ref`/`Mut` union parameter's temporary; a live non-Copy place is cloned so the caller keeps ownership."""
        at = self._t(a)
        if p.conv == "ref" and not at.is_copy() \
                and isinstance(a, (ast.Name, ast.Attribute, ast.Subscript)):
            code = f"({self._expr(a, 'ref')}).clone()"
        else:
            code = self._expr(a, "val", expect=p.typ)
        val = self._coerce(code, at, p.typ)
        return f"&{'mut ' if p.conv == 'mut' else ''}({val})"

    def _user_call(self, node: ast.Call, sig: FuncSig) -> str:
        args = []
        for a, p in zip(node.args, sig.params):
            if p.conv in ("ref", "mut") and isinstance(p.typ, TUnion) \
                    and not isinstance(self._t(a), TUnion):
                args.append(self._union_ref_arg(a, p))
            elif p.conv == "ref":
                args.append(self._expr(a, "ref"))
            elif p.conv == "mut":
                args.append(self._expr(a, "mut"))
            else:
                args.append(self._coerce(self._expr(a, "val", expect=p.typ), self._t(a), p.typ))
        for p in sig.params[len(node.args):]:
            args.append(self._default_code(p))
        qual = ""
        if sig.module != self.mod.name:
            qual = f"m_{_sanitize(sig.module)}::"
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
            if isinstance(t, TSet):
                return f"({r}).len_i()"
            if isinstance(t, (TBytes, TByteArray)):
                return f"({r}).len_i()"
            if isinstance(t, TPyVal):
                return self._q(f"pyval_len({r})")
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
            return f"sstring(py_str({self._expr(args[0], 'ref')}))"
        if name == "int":
            t = self._t(args[0])
            if isinstance(t, TPyVal):
                return self._q(f"pyval_to_int({self._expr(args[0], 'ref')})")
            if isinstance(t, TStr):
                return self._q(f"py_int_from_str({self._expr(args[0], 'ref')})")
            if isinstance(t, TFloat):
                return self._q(f"py_int_from_f({self._expr(args[0], 'val')})")
            if isinstance(t, TBool):
                return f"(({self._expr(args[0], 'val')}) as i64)"
            return self._expr(args[0], "val")
        if name == "float":
            t = self._t(args[0])
            if isinstance(t, TPyVal):
                return self._q(f"pyval_to_float({self._expr(args[0], 'ref')})")
            if isinstance(t, TStr):
                return self._q(f"py_float_from_str({self._expr(args[0], 'ref')})")
            if isinstance(t, TInt):
                return f"(({self._expr(args[0], 'val')}) as f64)"
            return self._expr(args[0], "val")
        if name == "bool":
            t = self._t(args[0])
            if isinstance(t, TPyVal):
                return f"pyval_truthy({self._expr(args[0], 'ref')})"
            v = self._expr(args[0], "val")
            if isinstance(t, TInt):
                return f"(({v}) != 0)"
            if isinstance(t, TFloat):
                return f"(({v}) != 0.0)"
            if isinstance(t, TStr):
                return f"(!({v}).is_empty())"
            return v
        if name == "next":
            assert isinstance(args[0], ast.Name)
            return self._q(f"serp_next(&mut v_{args[0].id})")
        if name == "sorted":
            t = self._t(node)
            assert isinstance(t, TList)
            elem = t.elem
            key = next((kw.value for kw in node.keywords if kw.arg == "key"), None)
            if isinstance(self._t(args[0]), TSet):
                src = self._expr(args[0], "ref")
                seq = (f"&(({src}).iter_it().cloned()"
                       f".collect::<Vec<{rust_type(t.elem)}>>())")
            else:
                seq = self._expr(args[0], "ref")
            if key is None:
                return f"serp_sorted({seq})"
            assert isinstance(key, ast.Lambda)
            pname = key.args.args[0].arg
            kt = self._t(key.body)
            saved_refs = set(self.ref_bound)
            saved_scope = dict(self.scope_types)
            self.ref_bound.add(pname)
            self.scope_types[pname] = elem
            kexpr = self._expr(key.body, "val")
            self.ref_bound = saved_refs
            self.scope_types = saved_scope
            self.tmp_counter += 1
            p = f"__sk{self.tmp_counter}"
            et = rust_type(elem)
            return (f"{{ let mut {p}: Vec<({rust_type(kt)}, {et})> = Vec::new(); "
                    f"for __e in ({seq}).iter() {{ let v_{pname} = __e; "
                    f"{p}.push(({kexpr}, __e.clone())); }} "
                    f"{p}.sort_by(|__a, __b| __a.0.partial_cmp(&__b.0)"
                    f".unwrap_or(std::cmp::Ordering::Equal)); "
                    f"{p}.into_iter().map(|__t| __t.1).collect::<Vec<{et}>>() }}")
        if name == "round":
            t0 = self._t(args[0])
            if isinstance(t0, TInt):
                return self._expr(args[0], "val")
            if len(args) == 1:
                return self._q(f"py_round0({self._expr(args[0], 'val')})")
            return f"py_round_n({self._expr(args[0], 'val')}, {self._expr(args[1], 'val')})"
        if name == "ord":
            return self._q(f"py_ord({self._expr(args[0], 'ref')})")
        if name == "chr":
            return self._q(f"py_chr({self._expr(args[0], 'val')})")
        if name == "input":
            return self._q("serp_input()")
        if name in ("bytes", "bytearray"):
            is_b = name == "bytes"
            if not args:
                return "sbytes(Vec::new())" if is_b else "pyba_new()"
            t0 = self._t(args[0])
            if is_b and isinstance(t0, TPyVal):
                return self._q(f"pyval_to_bytes({self._expr(args[0], 'ref')})")
            if isinstance(t0, TInt):
                fn = "pyb_zeros" if is_b else "pyba_zeros"
                return self._q(f"{fn}({self._expr(args[0], 'val')})")
            if isinstance(t0, TList):
                fn = "pyb_from_ints" if is_b else "pyba_from_ints"
                return self._q(f"{fn}({self._expr(args[0], 'ref')})")
            if isinstance(t0, TBytes):
                if is_b:
                    return self._expr(args[0], "val")
                return f"pyba_from_bytes({self._expr(args[0], 'ref')})"
            if is_b:
                return f"({self._expr(args[0], 'ref')}).as_bytes()"
            return f"({self._expr(args[0], 'ref')}).clone()"
        if name in ("set", "frozenset"):
            t = self._t(node)
            assert isinstance(t, TSet)
            if not args:
                return f"<{rust_type(t)}>::new()"
            t0 = self._t(args[0])
            src = self._expr(args[0], "ref")
            if isinstance(t0, TSet):
                return f"({src}).clone()"
            return f"<{rust_type(t)}>::from_vec(&({src}))"
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

    def _class_method_call_code(self, node: ast.Call) -> str:
        """The raw (unpropagated) Rust call expression for a user-class method call."""
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        args = node.args
        target = self.tc.call_targets[id(node)]
        sig = self.tc.sigs[target]
        conv0 = sig.params[0].conv
        if conv0 == "owned":
            argv = [self._expr(recv, "val")]
        else:
            argv = [self._recv(recv, conv0 == "mut")]
        for a, p in zip(args, sig.params[1:]):
            if p.conv in ("ref", "mut") and isinstance(p.typ, TUnion) \
                    and not isinstance(self._t(a), TUnion):
                argv.append(self._union_ref_arg(a, p))
            elif p.conv == "ref":
                argv.append(self._expr(a, "ref"))
            elif p.conv == "mut":
                argv.append(self._expr(a, "mut"))
            else:
                argv.append(self._coerce(self._expr(a, "val", expect=p.typ),
                                         self._t(a), p.typ))
        for p in sig.params[1 + len(args):]:
            argv.append(self._default_code(p))
        qual = f"m_{_sanitize(sig.module)}::" if sig.module != self.mod.name else ""
        return f"{qual}f_{_sanitize(sig.name)}({', '.join(argv)})"

    def _method_call(self, node: ast.Call) -> str:
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        method = node.func.attr
        rt = self._t(recv)
        inner = rt.inner if isinstance(rt, TShared) else rt
        args = node.args
        if isinstance(inner, TClass):
            return self._q(self._class_method_call_code(node))
        if isinstance(inner, TFile):
            r = self._recv(recv, True)
            if method == "read":
                fn = "read_all_bytes" if inner.binary else "read_all"
                return self._q(f"({r}).{fn}()")
            if method == "write":
                if inner.binary:
                    at = self._t(args[0])
                    acc = ".v" if isinstance(at, (TBytes, TByteArray)) else ""
                    return self._q(f"({r}).write_bytes(&({self._expr(args[0], 'ref')}){acc})")
                return self._q(f"({r}).write_str(&({self._expr(args[0], 'val')}))")
            if method == "close":
                return f"({r}).close()"
            raise CodegenError(f"cannot emit file method '{method}'")
        if isinstance(inner, TJoin):
            r = self._expr(recv, "ref")
            if inner.task and method == "done":
                return f"serp_task_done({r})"
            code = self._q(f"{'serp_task_await' if inner.task else 'serp_join'}({r})")
            if isinstance(inner.ret, TStr):
                return f"recv_str({code})"
            if isinstance(inner.ret, TBytes):
                return f"SBytes {{ v: Rc::new({code}) }}"
            return code
        if isinstance(inner, TThread):
            r = self._expr(recv, "ref")
            if method == "start":
                return self._q(f"serp_thread_start({r})")
            if method == "join":
                ms = "-1"
                if node.args and not (isinstance(node.args[0], ast.Constant)
                                      and node.args[0].value is None):
                    at = self._t(node.args[0])
                    if isinstance(at, TOptional):
                        v = self._expr(node.args[0], "val")
                        ms = f"match {v} {{ Some(t) => (t as f64 * 1000.0) as i64, None => -1 }}"
                    else:
                        v = self._coerce(self._expr(node.args[0], "val", expect=TFloat()), at, TFloat())
                        ms = f"(({v}) * 1000.0) as i64"
                return self._q(f"serp_thread_join({r}, {ms})")
            if method == "is_alive":
                return f"serp_thread_is_alive({r})"
            if method == "cancel":
                return f"serp_thread_cancel({r})"
            raise CodegenError(f"cannot emit Thread method '{method}'")
        if isinstance(inner, TList):
            elem = inner.elem
            if method == "append":
                v = self._coerce(self._expr(args[0], "val", expect=elem), self._t(args[0]), elem)
                return f"{{ let __av = {v}; ({self._recv(recv, True)}).push(__av) }}"
            if method == "insert":
                i = self._expr(args[0], "val")
                v = self._coerce(self._expr(args[1], "val", expect=elem), self._t(args[1]), elem)
                return f"{{ let __ai = {i}; let __av = {v}; serp_insert({self._recv(recv, True)}, __ai, __av) }}"
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
        if isinstance(inner, TSet):
            elem = inner.elem
            if method == "add":
                v = self._coerce(self._expr(args[0], "val", expect=elem), self._t(args[0]), elem)
                return f"({self._recv(recv, True)}).add({v})"
            if method == "discard":
                v = self._coerce(self._expr(args[0], "val", expect=elem), self._t(args[0]), elem)
                return f"({self._recv(recv, True)}).discard(&({v}))"
            if method == "remove":
                v = self._coerce(self._expr(args[0], "val", expect=elem), self._t(args[0]), elem)
                return self._q(f"({self._recv(recv, True)}).remove(&({v}))")
            if method == "pop":
                return self._q(f"({self._recv(recv, True)}).take()")
            if method == "clear":
                return f"({self._recv(recv, True)}).clear()"
            if method == "copy":
                return f"({self._recv(recv, False)}).clone()"
            if method in ("update", "difference_update", "intersection_update"):
                return (f"({self._recv(recv, True)}).{method}"
                        f"(&({self._expr(args[0], 'ref')}))")
            if method in ("union", "intersection", "difference", "symmetric_difference",
                          "issubset", "issuperset", "isdisjoint"):
                return (f"({self._recv(recv, False)}).{method}"
                        f"(&({self._expr(args[0], 'ref')}))")
            raise CodegenError(f"cannot emit set method '{method}'")
        if isinstance(inner, TDict):
            if method == "get":
                return f"({self._recv(recv, False)}).get_opt(&({self._expr(args[0], 'val')}))"
            if method == "pop":
                return self._q(f"({self._recv(recv, True)}).pop_key(&({self._expr(args[0], 'val')}))")
        if isinstance(inner, TBytes):
            if method == "fromhex":
                return self._q(f"pyb_fromhex({self._expr(args[0], 'ref')})")
            r = self._recv(recv, False) if isinstance(rt, TShared) else self._expr(recv, "ref")
            argv = [f"&({self._expr(a, 'val')})" for a in args]
            table = {"find": "pyb_find", "count": "pyb_count",
                     "startswith": "pyb_startswith", "endswith": "pyb_endswith",
                     "replace": "pyb_replace", "strip": "pyb_strip",
                     "lstrip": "pyb_lstrip", "rstrip": "pyb_rstrip",
                     "upper": "pyb_upper", "lower": "pyb_lower", "hex": "pyb_hex"}
            if method == "split":
                if args:
                    return self._q(f"pyb_split({r}, {argv[0]})")
                return f"pyb_split_ws({r})"
            if method == "join":
                return f"pyb_join({r}, {self._expr(args[0], 'ref')})"
            if method == "decode":
                return self._q(f"pyb_decode({r})")
            if method in table:
                return f"{table[method]}({r}{''.join(', ' + a for a in argv)})"
            raise CodegenError(f"cannot emit bytes method '{method}'")
        if isinstance(inner, TByteArray):
            if method == "append":
                return self._q(f"({self._recv(recv, True)}).push_i({self._expr(args[0], 'val')})")
            if method == "extend":
                at = self._t(args[0])
                fn = "extend_bytes" if isinstance(at, TBytes) else "extend_arr"
                return f"({self._recv(recv, True)}).{fn}(&({self._expr(args[0], 'ref')}))"
            r = self._recv(recv, False) if isinstance(rt, TShared) else self._expr(recv, "ref")
            if method == "hex":
                return f"pyb_hex(&({r}).as_bytes())"
            if method == "decode":
                return self._q(f"pyb_decode(&({r}).as_bytes())")
            raise CodegenError(f"cannot emit bytearray method '{method}'")
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
            if method == "encode":
                return f"py_str_encode({r})"
            if method == "join":
                return f"py_join({r}, {self._expr(args[0], 'ref')})"
            if method in table:
                return f"{table[method]}({r}{''.join(', ' + a for a in argv)})"
        raise CodegenError(f"cannot emit method '{method}' on {rt}")


def generate_rust(tc: TypeChecker) -> str:
    """Generate the complete Rust program for a checked Serpentine program."""
    return RustGen(tc).generate()
