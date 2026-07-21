"""Frontend: parsing, module discovery, three-bin import resolution (SPEC.md section 9)."""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .diagnostics import Reporter, Span
from .project import ManifestError, import_context


@dataclass
class Module:
    """A discovered Serpentine module: its name, path, AST, and import map."""

    name: str
    path: Path
    tree: ast.Module
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    shim_imports: set[str] = field(default_factory=set)
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    constants: dict[str, ast.AnnAssign] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    protocols: dict[str, ast.ClassDef] = field(default_factory=dict)
    typevars: set[str] = field(default_factory=set)
    typevar_bounds: dict[str, str] = field(default_factory=dict)
    imports_sys: bool = False
    entry_call: str | None = None


@dataclass
class Program:
    """The whole program: entry module plus every transitively imported module."""

    entry: Module
    modules: dict[str, Module] = field(default_factory=dict)


def load_program(entry_path: Path, rep: Reporter,
                 overlay: dict[str, str] | None = None) -> Program:
    """Parse the entry file and every bin-1 import reachable from it.

    `overlay` maps resolved file paths (str) to in-memory buffer contents that
    take precedence over the on-disk text (used by the LSP for unsaved edits).
    """
    entry_path = entry_path.resolve()
    try:
        ctx = import_context(entry_path.parent)
    except ManifestError as exc:
        rep.fatal("SE201", "unsupported-feature", f"invalid serp.toml: {exc}",
                  Span(str(entry_path), 1, 0))
    entry = _load_module(entry_path, entry_path.stem, rep, overlay)
    program = Program(entry=entry, modules={entry.name: entry})
    queue = [entry]
    while queue:
        mod = queue.pop()
        for local, (mod_name, _orig) in mod.imports.items():
            if mod_name in program.modules:
                continue
            candidate = ctx.resolve(mod_name)
            if candidate is None:
                span = _import_span(mod, mod_name)
                roots = ", ".join(str(r) for r in ctx.searched_roots())
                rep.fatal("SE213", "foreign-import",
                          f"import of '{mod_name}' does not resolve to a Serpentine module "
                          f"(searched: {roots}) — the CPython interop boundary refuses foreign "
                          f"imports in native builds (docs/interop.md); run under CPython to "
                          f"use them", span)
            sub = _load_module(candidate, mod_name, rep, overlay)
            _check_name_collision(program, sub, rep)
            program.modules[mod_name] = sub
            queue.append(sub)
    return program


def _check_name_collision(program: Program, new: Module, rep: Reporter) -> None:
    """Refuse two module names that mangle to the same generated identifier."""
    key = new.name.replace(".", "_")
    for existing in program.modules.values():
        if existing.name != new.name and existing.name.replace(".", "_") == key:
            rep.fatal("SE201", "unsupported-feature",
                      f"module names '{existing.name}' and '{new.name}' collide in "
                      f"generated code (both mangle to '{key}')",
                      Span(str(new.path), 1, 0))


def _import_span(mod: Module, mod_name: str) -> Span:
    """Locate the import statement for mod_name for error reporting."""
    for node in mod.tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            target = getattr(node, "module", None)
            if target == mod_name or mod_name in names:
                return Span(str(mod.path), node.lineno, node.col_offset)
    return Span(str(mod.path), 1, 0)


def _load_module(path: Path, name: str, rep: Reporter,
                 overlay: dict[str, str] | None = None) -> Module:
    """Parse one file and enforce the module-level structure rules."""
    text = None
    if overlay:
        text = overlay.get(str(path.resolve()))
    if text is None:
        text = path.read_text(encoding="utf-8")
    rep.add_source(str(path), text)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        rep.fatal("SE201", "unsupported-feature", f"syntax error: {exc.msg}",
                  Span(str(path), exc.lineno or 1, (exc.offset or 1) - 1))
    mod = Module(name=name, path=path, tree=tree)
    file = str(path)

    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]

    for node in body:
        span = Span(file, node.lineno, node.col_offset)
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                if [a.name for a in node.names] != ["annotations"]:
                    rep.fatal("SE201", "unsupported-feature",
                              "only 'from __future__ import annotations' is supported", span)
                continue
            if node.module == "serpentine":
                for alias in node.names:
                    if alias.asname:
                        rep.fatal("SE201", "unsupported-feature", "aliased shim imports are not supported", span)
                    mod.shim_imports.add(alias.name)
            elif node.module is not None and node.level == 0:
                for alias in node.names:
                    local = alias.asname or alias.name
                    mod.imports[local] = (node.module, alias.name)
            else:
                rep.fatal("SE213", "foreign-import",
                          f"relative import is not supported — use the full dotted module "
                          f"path from the project root", span)
        elif isinstance(node, ast.Import):
            if len(node.names) == 1 and node.names[0].name == "sys" and node.names[0].asname is None:
                mod.imports_sys = True
                continue
            rep.fatal("SE213", "foreign-import",
                      f"import of '{node.names[0].name}' is not supported — use "
                      f"'from {node.names[0].name} import ...' for Serpentine modules "
                      f"(only 'import sys' is special-cased); the interop boundary refuses "
                      f"foreign imports in native builds (docs/interop.md)",
                      span)
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                rep.fatal("SE201", "unsupported-feature", "decorators are not Tier 0/1", span)
            mod.functions[node.name] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            mod.constants[node.target.id] = node
        elif _is_entry_guard(node):
            call = node.body[0]
            assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
            assert isinstance(call.value.func, ast.Name)
            mod.entry_call = call.value.func.id
        elif isinstance(node, ast.ClassDef):
            if _is_protocol_class(node):
                if node.decorator_list or node.keywords:
                    rep.fatal("SE201", "unsupported-feature",
                              "protocol classes take no decorators or keywords", span)
                if "Protocol" not in mod.shim_imports:
                    rep.fatal("SE201", "unsupported-feature",
                              "protocol classes need 'from serpentine import Protocol'", span)
                mod.protocols[node.name] = node
                continue
            deco = node.decorator_list
            if not (len(deco) == 1 and isinstance(deco[0], ast.Name) and deco[0].id == "dataclass"):
                rep.fatal("SE201", "unsupported-feature",
                          "classes must carry exactly the @dataclass decorator "
                          "(from serpentine import dataclass)", span)
            if node.keywords or any(not _is_generic_base(b) for b in node.bases):
                rep.fatal("SE201", "unsupported-feature",
                          "class inheritance is not supported in Tier 1 (only a "
                          "Generic[...] base for generic classes)", span)
            mod.classes[node.name] = node
        elif _is_typevar_decl(node):
            assert isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            tv_name = node.targets[0].id
            mod.typevars.add(tv_name)
            assert isinstance(node.value, ast.Call)
            for kw in node.value.keywords:
                assert kw.arg == "bound" and isinstance(kw.value, ast.Name)
                mod.typevar_bounds[tv_name] = kw.value.id
        elif isinstance(node, ast.Assign):
            rep.fatal("SE206", "mutable-global",
                      "module-level bindings must be annotated Copy-typed constants", span)
        else:
            rep.fatal("SE205", "module-level-statement",
                      "only imports, function definitions, classes, Copy constants, and the "
                      "entry guard are allowed at module level", span)
    return mod


def _is_generic_base(node: ast.expr) -> bool:
    """Recognize `Generic[T, ...]` as the sole permitted class base."""
    return (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == "Generic")


def _is_protocol_class(node: ast.ClassDef) -> bool:
    """Recognize `class P(Protocol):` as a Tier-2 structural protocol."""
    return (len(node.bases) == 1 and isinstance(node.bases[0], ast.Name)
            and node.bases[0].id == "Protocol")


def _is_typevar_decl(node: ast.stmt) -> bool:
    """Recognize `T = TypeVar(\"T\")` (optionally with bound=Proto) at module level."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        return False
    v = node.value
    if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "TypeVar"
            and len(v.args) == 1 and isinstance(v.args[0], ast.Constant)
            and v.args[0].value == node.targets[0].id):
        return False
    return all(kw.arg == "bound" and isinstance(kw.value, ast.Name) for kw in v.keywords)


def _is_entry_guard(node: ast.stmt) -> bool:
    """Recognize `if __name__ == \"__main__\": some_call()`."""
    if not isinstance(node, ast.If) or node.orelse:
        return False
    t = node.test
    if not (isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)):
        return False
    if not (isinstance(t.left, ast.Name) and t.left.id == "__name__"):
        return False
    if not (len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "__main__"):
        return False
    if len(node.body) != 1:
        return False
    stmt = node.body[0]
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and not stmt.value.args)
