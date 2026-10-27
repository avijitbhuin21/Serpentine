"""Frontend: parsing, module discovery, three-bin import resolution (docs/spec.md section 9)."""

import ast
import copy
from dataclasses import dataclass, field
from pathlib import Path

from .diagnostics import Reporter, Span
from .project import ManifestError, import_context
from .ptypes import ENUM_BASES, TYPING_NAMES
from .rtlib import RTLIB_CONSTS, RTLIB_FUNCS, RTLIB_MODULES, RtFn


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
    enums: dict[str, ast.ClassDef] = field(default_factory=dict)
    class_statics: dict[str, dict[str, str]] = field(default_factory=dict)
    class_hooks: dict[str, list[dict]] = field(default_factory=dict)
    class_overloads: dict[str, dict[str, list[ast.FunctionDef]]] = field(default_factory=dict)
    cls_bound: dict[str, str] = field(default_factory=dict)
    class_bases: dict[str, str] = field(default_factory=dict)
    frozen_classes: set[str] = field(default_factory=set)
    protocols: dict[str, ast.ClassDef] = field(default_factory=dict)
    typevars: set[str] = field(default_factory=set)
    typevar_bounds: dict[str, str] = field(default_factory=dict)
    type_aliases: dict[str, ast.expr] = field(default_factory=dict)
    imports_sys: bool = False
    rtlib_imports: dict[str, RtFn] = field(default_factory=dict)
    rtlib_consts: dict[str, float] = field(default_factory=dict)
    entry_call: str | None = None
    exceptions: dict[str, str] = field(default_factory=dict)
    decorations: list[tuple[str, ast.expr]] = field(default_factory=list)
    async_fns: set[str] = field(default_factory=set)
    async_methods: bool = False
    imports_asyncio: bool = False
    app_bindings: dict[str, ast.Call] = field(default_factory=dict)
    class_attrs: dict[tuple[str, str], str] = field(default_factory=dict)
    module_aliases: dict[str, str] = field(default_factory=dict)
    app_stmts: list[ast.Call] = field(default_factory=list)
    registrars: dict[str, dict[str, ast.FunctionDef]] = field(default_factory=dict)
    exc_inits: dict[str, str] = field(default_factory=dict)
    exc_attrs: dict[str, list[str]] = field(default_factory=dict)


# Built-in exception classes recognized by raise/except (docs/spec.md section 11).
BUILTIN_EXC = {"Exception", "ValueError", "RuntimeError", "TypeError", "IndexError", "KeyError",
               "ZeroDivisionError", "OverflowError", "EOFError", "FileNotFoundError",
               "PermissionError", "OSError", "ArithmeticError", "LookupError", "StopIteration",
               "UnicodeDecodeError", "NotImplementedError", "AssertionError", "AttributeError"}

# Foreign import -> (PyPI dist, import module) suggested by SE213 diagnostics.
SERP_EQUIVALENTS = {
    "os": ("serp-os", "serp_os"), "json": ("serp-json", "serp_json"), "re": ("serp-re", "serp_re"),
    "math": ("serp-math", "serp_math"), "random": ("serp-random", "serp_random"),
    "time": ("serp-time", "serp_time"), "datetime": ("serp-datetime", "serp_datetime"),
    "csv": ("serp-csv", "serp_csv"), "base64": ("serp-base64", "serp_base64"),
    "hashlib": ("serp-hashlib", "serp_hashlib"), "hmac": ("serp-hmac", "serp_hmac"),
    "uuid": ("serp-uuid", "serp_uuid"), "secrets": ("serp-secrets", "serp_secrets"),
    "sqlite3": ("serp-sqlite", "serp_sqlite"), "zlib": ("serp-zlib", "serp_zlib"),
    "gzip": ("serp-zlib", "serp_zlib"), "zipfile": ("serp-zipfile", "serp_zipfile"),
    "socket": ("serp-socket", "serp_socket"), "urllib": ("serp-url", "serp_url"),
    "logging": ("serp-log", "serp_log"), "argparse": ("serpentine-argparse", "serp_cli"),
    "pathlib": ("serp-pathlib", "serp_pathlib"), "io": ("serpentine-io", "serp_io"),
    "subprocess": ("serp-subprocess", "serp_subprocess"),
    "threading": ("serp-threading", "serp_threading"), "queue": ("serp-queue", "serp_queue"),
    "asyncio": ("serp-asyncio", "serp_asyncio"), "itertools": ("serp-itertools", "serp_itertools"),
    "unittest": ("serp-test", "serp_test"), "http": ("serp-http-server", "serp_http_server"),
    "statistics": ("serp-statistics", "serp_statistics"), "tomllib": ("serp-tomllib", "serp_tomllib"),
    "heapq": ("serp-structs", "serp_structs"), "bisect": ("serp-structs", "serp_structs"),
    "requests": ("serp-fang", "serp_fang"), "httpx": ("serp-fang", "serp_fang"),
    "fastapi": ("serp-venom", "serp_fastapi"), "uvicorn": ("serp-venom", "serp_uvicorn"),
    "pydantic": ("serp-molt", "serp_molt"), "numpy": ("serp-coil", "serp_coil"),
    "pandas": ("serp-scales", "serp_scales"), "jwt": ("serp-jwt", "serp_jwt"),
    "bcrypt": ("serp-bcrypt", "serp_bcrypt"), "redis": ("serp-redis", "serp_redis"),
    "prometheus_client": ("serp-prometheus", "serp_prometheus"),
    "opentelemetry": ("serp-tracing", "serp_tracing"),
}

# Direct parent of each non-root builtin (mirrors prelude.rs SerpErr::matches).
BUILTIN_EXC_PARENT = {"FileNotFoundError": "OSError",
                      "ZeroDivisionError": "ArithmeticError",
                      "OverflowError": "ArithmeticError",
                      "IndexError": "LookupError",
                      "KeyError": "LookupError",
                      "UnicodeDecodeError": "ValueError",
                      "NotImplementedError": "RuntimeError"}


def collect_user_exceptions(program: "Program") -> dict[str, str]:
    """Merge every module's user exception classes into one {name: base} map."""
    out: dict[str, str] = {}
    for mod in program.modules.values():
        out.update(mod.exceptions)
    return out


def exc_ancestors(name: str, user_exc: dict[str, str]) -> set[str]:
    """All classes (excluding itself) that a raise of `name` should match."""
    out: set[str] = {"Exception"}
    cur = name
    seen = {name}
    while True:
        parent = user_exc.get(cur) or BUILTIN_EXC_PARENT.get(cur)
        if parent is None or parent in seen:
            return out
        out.add(parent)
        seen.add(parent)
        cur = parent


def exc_handler_names(cls: str, user_exc: dict[str, str]) -> list[str]:
    """Expand a handler class to itself plus every user subclass (whole-program)."""
    names = [cls]
    names += sorted(u for u in user_exc if cls in exc_ancestors(u, user_exc))
    return names


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
        for target in sorted(set(mod.module_aliases.values())):
            if target in program.modules or target in RTLIB_MODULES:
                continue
            if ctx.resolve(target) is None:
                _report_foreign_import(rep, mod, target, ctx)
        for local, (mod_name, _orig) in mod.imports.items():
            if mod_name in program.modules:
                continue
            candidate = ctx.resolve(mod_name)
            if candidate is None:
                _report_foreign_import(rep, mod, mod_name, ctx)
            sub = _load_module(candidate, mod_name, rep, overlay)
            _check_name_collision(program, sub, rep)
            program.modules[mod_name] = sub
            queue.append(sub)
    _inject_builtins(program, rep, overlay)
    _desugar_async(program, rep)
    _erase_block_on(program)
    _rewrite_exception_ctors(program)
    _synthesize_app_bindings(program, rep)
    _synthesize_decorations(program)
    return program


BUILTINS_MODULE = "_serp_builtins"
BUILTINS_PATH = Path(__file__).resolve().parent / "_serp_builtins.py"
BUILTIN_CLASSES = ("slice",)


def _inject_builtins(program: Program, rep: Reporter,
                     overlay: dict[str, str] | None) -> None:
    """Load the compiler-provided builtin classes and make them visible in every module
    that does not define or import a name of its own with the same spelling (D43)."""
    if BUILTINS_MODULE in program.modules:
        return
    bi = _load_module(BUILTINS_PATH, BUILTINS_MODULE, rep, overlay)
    program.modules[BUILTINS_MODULE] = bi
    for mod in program.modules.values():
        if mod is bi:
            continue
        for cname in BUILTIN_CLASSES:
            if cname in mod.imports or cname in mod.classes or cname in mod.functions \
                    or cname in mod.constants or cname in mod.enums:
                continue
            mod.imports[cname] = (BUILTINS_MODULE, cname)


AIO_CORE = ("run", "sleep", "create_task", "gather", "Task", "TimeoutError")


def _erase_block_on(program: Program) -> None:
    """`block_on(e)` -> `e`: natively every coroutine already ran to completion (D45)."""
    for mod in program.modules.values():
        if "block_on" not in mod.shim_imports:
            continue

        class Eraser(ast.NodeTransformer):
            def visit_Call(self, node: ast.Call):
                """Unwrap block_on(...)."""
                self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id == "block_on" \
                        and len(node.args) == 1 and not node.keywords:
                    return node.args[0]
                return node

        mod.tree = ast.fix_missing_locations(Eraser().visit(mod.tree))
AIO_EXC = ("QueueEmpty", "QueueFull", "CancelledError", "InvalidStateError")


def _aio_local(attr: str) -> str:
    """Module-local name for `asyncio.<attr>` (exceptions keep their name so except/raise resolve)."""
    return attr if attr in AIO_EXC else f"_serp_aio_{attr}"


def _desugar_async(program: Program, rep: Reporter) -> None:
    """Lower async/await onto the baton task runtime (docs/DECISIONS.md D14 + D45).

    `await f(...)` on a coroutine runs the call inline (same task, CPython order);
    `asyncio.create_task(f(...))` becomes the `_serp_create_task` intrinsic and
    `await <task>` its `_serp_await()`; `await asyncio.gather(...)` is spread into
    task temporaries at statement level; `asyncio.sleep` is the runtime's cooperative
    sleep. Every direct call to an async function must still be awaited (or wrapped in
    create_task/gather/asyncio.run) so no coroutine object is ever created un-run.
    """
    sleep_fn = RTLIB_FUNCS[("_serp_asyncio", "sleep")]
    for mod in program.modules.values():
        if not (mod.async_fns or mod.imports_asyncio or mod.async_methods
                or any(m in program.modules and program.modules[m].async_fns
                       for m, _o in mod.imports.values())):
            continue
        file = str(mod.path)
        awaited: set[int] = set()
        counter = [0]

        def _span(node: ast.AST) -> Span:
            return Span(file, node.lineno, node.col_offset)

        def is_async_callee(fn: ast.expr) -> bool:
            """Whether a call-func expression names an async function."""
            if not isinstance(fn, ast.Name):
                return False
            if fn.id in mod.async_fns:
                return True
            tgt = mod.imports.get(fn.id)
            if tgt is not None:
                sub = program.modules.get(tgt[0])
                return sub is not None and tgt[1] in sub.async_fns
            return False

        def is_aio(f: ast.expr, attr: str) -> bool:
            """Whether `f` is the attribute `asyncio.<attr>`."""
            return (mod.imports_asyncio and isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name) and f.value.id == "asyncio"
                    and f.attr == attr)

        def make_task(call: ast.expr, where: ast.AST) -> ast.Call:
            """`asyncio.create_task(f(a, b))` -> `_serp_create_task(f, a, b)`."""
            if not (isinstance(call, ast.Call) and is_async_callee(call.func)):
                rep.fatal("SE201", "unsupported-feature",
                          "create_task/gather take direct calls to async functions "
                          "(docs/DECISIONS.md D45)", _span(where))
            if call.keywords:
                rep.fatal("SE201", "unsupported-feature",
                          "a task's coroutine call takes positional arguments only",
                          _span(call))
            awaited.add(id(call))
            out = ast.Call(func=ast.Name(id="_serp_create_task", ctx=ast.Load()),
                           args=[call.func] + list(call.args), keywords=[])
            return ast.copy_location(out, call)

        def task_await(expr: ast.expr, where: ast.AST) -> ast.Call:
            """`await t` on a task value -> `t._serp_await()`."""
            out = ast.Call(func=ast.Attribute(value=expr, attr="_serp_await", ctx=ast.Load()),
                           args=[], keywords=[])
            ast.copy_location(out.func, where)
            return ast.copy_location(out, where)

        def check_task_kws(node: ast.Call) -> None:
            """create_task/gather keywords: `name=` is accepted and dropped, others refused."""
            for kw in node.keywords:
                if kw.arg != "name":
                    rep.fatal("SE201", "unsupported-feature",
                              f"asyncio.{node.func.attr}() keyword '{kw.arg}' is not "
                              f"supported (docs/DECISIONS.md D45)", _span(node))

        def gather_stmts(node: ast.Call, where: ast.AST) -> tuple[list[ast.stmt], list[ast.expr]]:
            """Spread `asyncio.gather(c1(), c2())` into task temporaries + their awaits."""
            check_task_kws(node)
            counter[0] += 1
            pre: list[ast.stmt] = []
            waits: list[ast.expr] = []
            for i, a in enumerate(node.args):
                if isinstance(a, ast.Starred):
                    rep.fatal("SE201", "unsupported-feature",
                              "asyncio.gather(*coros) is not supported — list the "
                              "coroutine calls explicitly", _span(a))
                tname = f"_serp_g{counter[0]}_{i}"
                asg = ast.Assign(targets=[ast.Name(id=tname, ctx=ast.Store())],
                                 value=make_task(a, a))
                pre.append(ast.copy_location(asg, where))
                waits.append(task_await(ast.Name(id=tname, ctx=ast.Load()), where))
            return pre, waits

        def is_gather_await(v: ast.expr | None) -> bool:
            """Whether `v` is exactly `await asyncio.gather(...)`."""
            return (isinstance(v, ast.Await) and isinstance(v.value, ast.Call)
                    and is_aio(v.value.func, "gather"))

        class AsyncLower(ast.NodeTransformer):
            def _stmt_with_gather(self, node: ast.stmt, value: ast.expr):
                """Lower a statement whose value is `await asyncio.gather(...)`."""
                pre, waits = gather_stmts(value.value, node)
                if isinstance(node, ast.Expr):
                    out = pre + [ast.copy_location(ast.Expr(value=w), node) for w in waits]
                    return [self.visit(s) for s in out]
                lst = ast.copy_location(ast.List(elts=waits, ctx=ast.Load()), node)
                if isinstance(node, ast.Assign):
                    node.value = lst
                elif isinstance(node, ast.AnnAssign):
                    node.value = lst
                else:
                    node.value = lst
                return [self.visit(s) for s in pre] + [self.generic_visit(node)]

            def visit_Expr(self, node: ast.Expr):
                if is_gather_await(node.value):
                    return self._stmt_with_gather(node, node.value)
                return self.generic_visit(node)

            def visit_Assign(self, node: ast.Assign):
                if is_gather_await(node.value):
                    return self._stmt_with_gather(node, node.value)
                return self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign):
                if is_gather_await(node.value):
                    return self._stmt_with_gather(node, node.value)
                return self.generic_visit(node)

            def visit_Return(self, node: ast.Return):
                if is_gather_await(node.value):
                    return self._stmt_with_gather(node, node.value)
                return self.generic_visit(node)

            def visit_Await(self, node: ast.Await):
                """Lower one await: inline call, task await, or cooperative sleep."""
                inner = node.value
                if isinstance(inner, ast.Call):
                    f = inner.func
                    if is_aio(f, "gather"):
                        rep.fatal("SE201", "unsupported-feature",
                                  "await asyncio.gather(...) must be the whole right-hand "
                                  "side of an assignment, a return value or a bare "
                                  "statement (docs/DECISIONS.md D45)", _span(node))
                    if is_aio(f, "create_task"):
                        check_task_kws(inner)
                        if len(inner.args) != 1:
                            rep.fatal("SE201", "unsupported-feature",
                                      "asyncio.create_task takes one coroutine call", _span(inner))
                        t = make_task(inner.args[0], inner)
                        self.generic_visit(t)
                        return task_await(t, node)
                    self.generic_visit(node)
                    inner = node.value
                    f = inner.func
                    if is_aio(f, "sleep"):
                        inner.func = ast.copy_location(
                            ast.Name(id="_serp_aio_sleep", ctx=ast.Load()), f)
                        mod.rtlib_imports.setdefault("_serp_aio_sleep", sleep_fn)
                        awaited.add(id(inner))
                        return inner
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                            and f.value.id == "asyncio" and mod.imports_asyncio:
                        rep.fatal("SE201", "unsupported-feature",
                                  f"await asyncio.{f.attr}(...) is not supported natively "
                                  f"(docs/DECISIONS.md D45)", _span(node))
                    awaited.add(id(inner))
                    return inner
                self.generic_visit(node)
                return task_await(node.value, node)

            def visit_Call(self, node: ast.Call):
                """Rewrite asyncio.run(coro()) and asyncio.create_task(coro())."""
                f = node.func
                if is_aio(f, "run"):
                    if len(node.args) == 1 and not node.keywords \
                            and isinstance(node.args[0], ast.Call) \
                            and is_async_callee(node.args[0].func):
                        awaited.add(id(node.args[0]))
                        self.generic_visit(node.args[0])
                        return node.args[0]
                    rep.fatal("SE201", "unsupported-feature",
                              "asyncio.run takes exactly one direct call to an async "
                              "function", _span(node))
                if is_aio(f, "create_task"):
                    check_task_kws(node)
                    if len(node.args) != 1:
                        rep.fatal("SE201", "unsupported-feature",
                                  "asyncio.create_task takes one coroutine call", _span(node))
                    t = make_task(node.args[0], node)
                    self.generic_visit(t)
                    return t
                if is_aio(f, "sleep"):
                    node.args = [self.visit(a) for a in node.args]
                    node.func = ast.copy_location(
                        ast.Name(id="_serp_aio_sleep", ctx=ast.Load()), f)
                    mod.rtlib_imports.setdefault("_serp_aio_sleep", sleep_fn)
                    return node
                if is_aio(f, "gather"):
                    rep.fatal("SE201", "unsupported-feature",
                              "asyncio.gather(...) must be awaited directly "
                              "(docs/DECISIONS.md D45)", _span(node))
                self.generic_visit(node)
                return node

            def visit_Attribute(self, node: ast.Attribute):
                """Remaining `asyncio.X` names: Task type, builtin TimeoutError, or serp_asyncio members."""
                self.generic_visit(node)
                if not (mod.imports_asyncio and isinstance(node.value, ast.Name)
                        and node.value.id == "asyncio"):
                    return node
                if node.attr == "Task":
                    return ast.copy_location(ast.Name(id="_serp_aio_Task", ctx=node.ctx), node)
                if node.attr == "TimeoutError":
                    return ast.copy_location(ast.Name(id="TimeoutError", ctx=node.ctx), node)
                if node.attr in AIO_CORE:
                    rep.fatal("SE201", "unsupported-feature",
                              f"asyncio.{node.attr} must be called (docs/DECISIONS.md D45)",
                              _span(node))
                return ast.copy_location(ast.Name(id=_aio_local(node.attr), ctx=node.ctx), node)

        mod.tree = ast.fix_missing_locations(AsyncLower().visit(mod.tree))
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Call):
                if id(node) not in awaited and is_async_callee(node.func):
                    assert isinstance(node.func, ast.Name)
                    rep.fatal("SE201", "unsupported-feature",
                              f"call to async function '{node.func.id}' must be awaited "
                              f"(or passed to asyncio.run/create_task/gather)", _span(node))
            if isinstance(node, (ast.AsyncFor, ast.AsyncWith)):
                rep.fatal("SE201", "unsupported-feature",
                          "'async for' is not supported (docs/DECISIONS.md D45)", _span(node))


def _module_postorder(program: Program) -> list[Module]:
    """Modules in CPython import-execution order (imports first, entry last)."""
    out: list[Module] = []
    seen: set[str] = set()

    def visit(mod: Module) -> None:
        if mod.name in seen:
            return
        seen.add(mod.name)
        for (mname, _orig) in mod.imports.values():
            sub = program.modules.get(mname)
            if sub is not None:
                visit(sub)
        out.append(mod)

    visit(program.entry)
    for m in list(program.modules.values()):
        visit(m)
    return out


def _callable_annotation(fn: ast.FunctionDef) -> ast.expr:
    """Build the Callable[[...], R] annotation matching a function's signature."""
    params = []
    for a in fn.args.args:
        ann = copy.deepcopy(a.annotation)
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                and ann.value.id == "Owned":
            ann = ann.slice
        params.append(ann)
    ret = copy.deepcopy(fn.returns) or ast.Constant(value=None)
    return ast.Subscript(
        value=ast.Name(id="Callable", ctx=ast.Load()),
        slice=ast.Tuple(elts=[ast.List(elts=params, ctx=ast.Load()), ret],
                        ctx=ast.Load()),
        ctx=ast.Load())


def _synthesize_decorations(program: Program) -> None:
    """Lower @decorators into startup registration calls at the top of the entry function.

    Decorators are registration-only (docs/DECISIONS.md D13): the decorated name stays
    bound to the original function; each decorator application must produce a Callable
    of the same signature (enforced by the synthesized annotated binding below) and is
    expected to return the function it was given. Applications run in CPython import
    order (imported modules first, entry module last, source order within a module).
    """
    entry = program.entry
    entry_fn = entry.functions.get(entry.entry_call) if entry.entry_call else None
    calls: list[ast.stmt] = []
    for mod in _module_postorder(program):
        if not mod.decorations:
            continue
        deco_name = f"_serp_deco_{mod.name.replace('.', '_')}"
        body: list[ast.stmt] = []
        for i, (fname, dexpr) in enumerate(mod.decorations):
            fn = mod.functions.get(fname)
            if fn is None:
                continue
            call = ast.Call(func=copy.deepcopy(dexpr),
                            args=[ast.Name(id=fname, ctx=ast.Load())], keywords=[])
            body.append(ast.AnnAssign(
                target=ast.Name(id=f"_serp_deco_r{i}", ctx=ast.Store()),
                annotation=_callable_annotation(fn), value=call, simple=1))
        node = ast.FunctionDef(
            name=deco_name,
            args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                               kw_defaults=[], kwarg=None, defaults=[]),
            body=body or [ast.Pass()], decorator_list=[],
            returns=ast.Constant(value=None))
        anchor = mod.functions.get(mod.decorations[0][0]) or mod.tree.body[0]
        ast.copy_location(node, anchor)
        ast.fix_missing_locations(node)
        mod.functions[deco_name] = node
        if entry_fn is not None:
            if mod is not entry:
                entry.imports[deco_name] = (mod.name, deco_name)
            calls.append(ast.Expr(value=ast.Call(
                func=ast.Name(id=deco_name, ctx=ast.Load()), args=[], keywords=[])))
    if entry_fn is not None and calls:
        for c in calls:
            ast.copy_location(c, entry_fn.body[0])
            ast.fix_missing_locations(c)
        entry_fn.body[0:0] = calls


SCALAR_KINDS = {"int": ("int", 0), "str": ("str", ""), "float": ("float", 0.0),
                "bool": ("bool", False)}


def _name(id_: str) -> ast.Name:
    """A Load-context Name node."""
    return ast.Name(id=id_, ctx=ast.Load())


def _origin_of(program: Program, mod: Module, name: str) -> tuple[str, str] | None:
    """The (module, name) that a class/function name in mod ultimately refers to."""
    if name in mod.classes or name in mod.functions or name in mod.exceptions:
        return (mod.name, name)
    seen = set()
    cur: tuple[str, str] | None = mod.imports.get(name)
    while cur is not None and cur not in seen:
        seen.add(cur)
        sub = program.modules.get(cur[0])
        if sub is None:
            return cur
        if cur[1] in sub.classes or cur[1] in sub.functions or cur[1] in sub.exceptions:
            return cur
        cur = sub.imports.get(cur[1])
    return cur


def _import_alias(mod: Module, origin: tuple[str, str]) -> str:
    """A local name in mod for the class/function `origin`, importing it if necessary."""
    if origin[0] == mod.name:
        return origin[1]
    for local, tgt in mod.imports.items():
        if tgt == origin:
            return local
    alias = f"_serp_t_{origin[0].replace('.', '_')}_{origin[1]}"
    mod.imports[alias] = origin
    return alias


def _class_def(program: Program, origin: tuple[str, str] | None) -> ast.ClassDef | None:
    """The ClassDef behind a resolved origin, if it names a class."""
    if origin is None:
        return None
    sub = program.modules.get(origin[0])
    return sub.classes.get(origin[1]) if sub is not None else None


def _class_has_method(program: Program, origin: tuple[str, str] | None, method: str) -> bool:
    """Whether a class (or one of its @dataclass bases) defines `method`."""
    seen = set()
    while origin is not None and origin not in seen:
        seen.add(origin)
        sub = program.modules.get(origin[0])
        cdef = sub.classes.get(origin[1]) if sub is not None else None
        if cdef is None:
            return False
        if any(isinstance(s, ast.FunctionDef) and s.name == method for s in cdef.body) \
                or method in sub.class_statics.get(origin[1], {}):
            return True
        base = sub.class_bases.get(origin[1])
        origin = _origin_of(program, sub, base) if base else None
    return False


def _unwrap_owned(ann: ast.expr | None) -> ast.expr | None:
    """Strip an `Owned[...]` wrapper from an annotation."""
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
            and ann.value.id == "Owned":
        return ann.slice
    return ann


def _optional_inner(ann: ast.expr) -> ast.expr | None:
    """The T of `T | None`, `None | T` or `Optional[T]`, else None."""
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        for a, b in ((ann.left, ann.right), (ann.right, ann.left)):
            if isinstance(a, ast.Constant) and a.value is None:
                return b
    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
            and ann.value.id == "Optional":
        return ann.slice
    return None


def _path_param_names(path: str) -> list[str]:
    """The `{name}` segments of a route path."""
    return [seg[1:-1] for seg in path.split("/") if seg.startswith("{") and seg.endswith("}")]


def _depends_target(dflt: ast.expr | None) -> str | None:
    """The function name inside a `Depends(fn)` default, else None."""
    if isinstance(dflt, ast.Call) and isinstance(dflt.func, ast.Name) \
            and dflt.func.id == "Depends" and len(dflt.args) == 1 \
            and isinstance(dflt.args[0], ast.Name) and not dflt.keywords:
        return dflt.args[0].id
    return None


def _rq_call(method: str, args: list[ast.expr]) -> ast.Call:
    """`_serp_rq.<method>(args...)`."""
    return ast.Call(func=ast.Attribute(value=_name("_serp_rq"), attr=method, ctx=ast.Load()),
                    args=args, keywords=[])


def _inject_params(program: Program, mod: Module, rep: Reporter, fn: ast.FunctionDef,
                   path_names: list[str], body: list[ast.stmt], prefix: str, span: Span,
                   rq: str, rs: str) -> list[ast.expr]:
    """Append the extraction statements for every parameter of `fn` to `body` (D41) and
    return the argument expressions to call `fn` with. `Depends(g)` parameters recurse
    into `g`'s own parameters and bind the call result."""
    params = fn.args.args
    defaults: list[ast.expr | None] = [None] * (len(params) - len(fn.args.defaults)) \
        + list(fn.args.defaults)
    call_args: list[ast.expr] = []
    has_depends = False
    for p, dflt in zip(params, defaults):
        local = prefix + p.arg
        ann = _unwrap_owned(p.annotation)
        moved = False
        if ann is None:
            rep.fatal("SE203", "missing-annotation",
                      f"route handler parameter '{p.arg}' needs a type annotation", span)
        inner = _optional_inner(ann)
        dep = _depends_target(dflt)
        is_class = isinstance(ann, ast.Name) \
            and _class_def(program, _origin_of(program, mod, ann.id)) is not None
        if dep is not None:
            has_depends = True
            g = mod.functions.get(dep)
            if g is None:
                rep.fatal("SE201", "unsupported-feature",
                          f"Depends({dep}) must name a module-level function", span)
            g_args = _inject_params(program, mod, rep, g, path_names, body,
                                    f"_serp_d_{dep}_{prefix}", span, rq, rs)
            value: ast.expr = ast.Call(func=_name(dep), args=g_args, keywords=[])
            if is_class or not (isinstance(ann, ast.Name) and ann.id in SCALAR_KINDS) \
                    and inner is None:
                moved = True
        elif isinstance(ann, ast.Name) and ann.id in SCALAR_KINDS:
            kind, zero = SCALAR_KINDS[ann.id]
            if p.arg in path_names:
                value = _rq_call(f"_serp_path_{kind}", [ast.Constant(value=p.arg)])
            else:
                value = _rq_call(f"_serp_query_{kind}", [
                    ast.Constant(value=p.arg),
                    copy.deepcopy(dflt) if dflt is not None else ast.Constant(value=zero),
                    ast.Constant(value=dflt is not None)])
        elif isinstance(inner, ast.Name) and inner.id in SCALAR_KINDS:
            kind, _zero = SCALAR_KINDS[inner.id]
            value = _rq_call(f"_serp_query_opt_{kind}", [ast.Constant(value=p.arg)])
        elif is_class and isinstance(ann, ast.Name) \
                and (_origin_of(program, mod, ann.id) or ("", ""))[1] == "BackgroundTasks":
            value = ast.Call(func=_name(ann.id), args=[], keywords=[])
            if not (isinstance(p.annotation, ast.Subscript) and isinstance(p.annotation.value, ast.Name)
                    and p.annotation.value.id == "Mut"):
                p.annotation = ast.Subscript(value=_name("Mut"), slice=copy.deepcopy(ann),
                                             ctx=ast.Load())
                ast.copy_location(p.annotation, ann)
            mod.shim_imports.update({"Mut", "move"})
            setattr(fn, "_serp_bg_local", local)
            body.append(ast.AnnAssign(target=ast.Name(id=local, ctx=ast.Store()),
                                      annotation=copy.deepcopy(ann), value=value, simple=1))
            call_args.append(_name(local))
            continue
        elif is_class:
            assert isinstance(ann, ast.Name)
            if not _class_has_method(program, _origin_of(program, mod, ann.id),
                                     "model_validate_json_errors"):
                rep.fatal("SE201", "unsupported-feature",
                          f"route handler body parameter '{p.arg}: {ann.id}' must be a "
                          f"serp_molt model (needs model_validate_json/_errors)", span)
            errs = f"_serp_errs_{local}"
            body.append(ast.AnnAssign(
                target=ast.Name(id=errs, ctx=ast.Store()),
                annotation=ast.Subscript(value=_name("list"), slice=_name("PyVal"),
                                         ctx=ast.Load()),
                value=ast.Call(func=ast.Attribute(value=_name(ann.id),
                                                  attr="model_validate_json_errors",
                                                  ctx=ast.Load()),
                               args=[_rq_call("_serp_body", [])], keywords=[]),
                simple=1))
            body.append(ast.If(
                test=ast.Compare(left=ast.Call(func=_name("len"), args=[_name(errs)],
                                               keywords=[]),
                                 ops=[ast.Gt()], comparators=[ast.Constant(value=0)]),
                body=[ast.Return(value=_rq_call("_serp_validation_error", [
                    ast.Call(func=_name("move"), args=[_name(errs)], keywords=[])]))],
                orelse=[]))
            value = ast.Call(func=ast.Attribute(value=_name(ann.id), attr="model_validate_json",
                                                ctx=ast.Load()),
                             args=[_rq_call("_serp_body", [])], keywords=[])
            moved = True
        else:
            rep.fatal("SE201", "unsupported-feature",
                      f"route handler parameter '{p.arg}' has a type the request cannot "
                      f"provide — use int/str/float/bool (optionally `| None`), a "
                      f"serp_molt model for the body, `Depends(fn)`, or "
                      f"`(req: Owned[{rq}]) -> {rs}`", span)
        if moved and not (isinstance(p.annotation, ast.Subscript)
                          and isinstance(p.annotation.value, ast.Name)
                          and p.annotation.value.id == "Owned"):
            p.annotation = ast.Subscript(value=_name("Owned"), slice=copy.deepcopy(ann),
                                         ctx=ast.Load())
            ast.copy_location(p.annotation, ann)
        mod.shim_imports.update({"PyVal", "move"})
        body.append(ast.AnnAssign(target=ast.Name(id=local, ctx=ast.Store()),
                                  annotation=copy.deepcopy(ann), value=value, simple=1))
        call_args.append(ast.Call(func=_name("move"), args=[_name(local)], keywords=[])
                         if moved else _name(local))
    if has_depends:
        fn.args.defaults = []
    return call_args


def _endpoint_for(program: Program, mod: Module, rep: Reporter, fn: ast.FunctionDef,
                  path: str, rq: str, rs: str) -> str:
    """Return the name of the endpoint to register for handler `fn` (D41).

    A handler already shaped `(x: Owned[Rq]) -> Rs` is registered as is; any other
    signature gets a synthesized `_serp_ep_<fn>` that pulls each parameter out of the
    request (path → `_serp_path_<kind>`, scalar → `_serp_query_<kind>`, class → JSON
    body via `model_validate_json`) and converts the return value with
    `_serp_respond_json` unless it already is an `Rs`.
    """
    file = str(mod.path)
    span = Span(file, fn.lineno, fn.col_offset)
    params = fn.args.args
    defaults: list[ast.expr | None] = [None] * (len(params) - len(fn.args.defaults)) \
        + list(fn.args.defaults)
    ret = fn.returns
    ret_origin = _origin_of(program, mod, ret.id) if isinstance(ret, ast.Name) else None
    rq_origin = _origin_of(program, mod, rq)
    rs_origin = _origin_of(program, mod, rs)
    if len(params) == 1 and ret_origin == rs_origin:
        p_ann = _unwrap_owned(params[0].annotation)
        if isinstance(p_ann, ast.Name) and _origin_of(program, mod, p_ann.id) == rq_origin:
            return fn.name
    if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs or fn.args.posonlyargs:
        rep.fatal("SE201", "unsupported-feature",
                  f"route handler '{fn.name}' may only take plain positional parameters", span)
    path_names = _path_param_names(path)
    body: list[ast.stmt] = []
    call_args = _inject_params(program, mod, rep, fn, path_names, body, "", span, rq, rs)
    handler_call = ast.Call(func=_name(fn.name), args=call_args, keywords=[])
    respond = ast.Attribute(value=_name("_serp_rq"), attr="_serp_respond_json", ctx=ast.Load())
    if ret is None or (isinstance(ret, ast.Constant) and ret.value is None):
        body.append(ast.Expr(value=handler_call))
        body.append(ast.Return(value=ast.Call(func=respond, args=[ast.Constant(value=None)],
                                              keywords=[])))
    elif ret_origin == rs_origin and ret_origin is not None:
        body.append(ast.Return(value=handler_call))
    else:
        body.append(ast.AnnAssign(target=ast.Name(id="_serp_r", ctx=ast.Store()),
                                  annotation=copy.deepcopy(ret), value=handler_call, simple=1))
        payload: ast.expr = _name("_serp_r")
        elem = ret.slice if isinstance(ret, ast.Subscript) and isinstance(ret.value, ast.Name) \
            and ret.value.id == "list" else None
        if isinstance(ret, ast.Name) and _class_def(program, ret_origin) is not None:
            payload = _dump_expr(program, mod, ret_origin, payload)
        elif isinstance(elem, ast.Name) and _class_def(
                program, _origin_of(program, mod, elem.id)) is not None:
            payload = ast.ListComp(
                elt=_dump_expr(program, mod, _origin_of(program, mod, elem.id), _name("_serp_x")),
                generators=[ast.comprehension(target=ast.Name(id="_serp_x", ctx=ast.Store()),
                                              iter=_name("_serp_r"), ifs=[], is_async=0)])
        body.append(ast.Return(value=ast.Call(func=respond, args=[payload], keywords=[])))
    bg_local = getattr(fn, "_serp_bg_local", None)
    if bg_local is not None and body and isinstance(body[-1], ast.Return):
        final = body.pop()
        assert isinstance(final, ast.Return) and final.value is not None
        body.append(ast.AnnAssign(target=ast.Name(id="_serp_resp", ctx=ast.Store()),
                                  annotation=_name(rs), value=final.value, simple=1))
        body.append(ast.Assign(
            targets=[ast.Attribute(value=_name("_serp_resp"), attr="background", ctx=ast.Store())],
            value=ast.Call(func=_name("move"),
                           args=[ast.Attribute(value=_name(bg_local), attr="tasks", ctx=ast.Load())],
                           keywords=[])))
        body.append(ast.Return(value=_name("_serp_resp")))
    ep_name = f"_serp_ep_{fn.name}"
    ep = ast.FunctionDef(
        name=ep_name,
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="_serp_rq",
                          annotation=ast.Subscript(value=_name("Owned"), slice=_name(rq),
                                                   ctx=ast.Load()))],
            vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=body, decorator_list=[], returns=_name(rs))
    ast.copy_location(ep, fn)
    ast.fix_missing_locations(ep)
    mod.functions[ep_name] = ep
    mod.shim_imports.add("Owned")
    return ep_name


def _dump_expr(program: Program, mod: Module, origin: tuple[str, str] | None,
               value: ast.expr) -> ast.expr:
    """`value.model_dump()` for serp_molt models, `fields_of(value)` for plain dataclasses."""
    if _class_has_method(program, origin, "model_dump"):
        return ast.Call(func=ast.Attribute(value=value, attr="model_dump", ctx=ast.Load()),
                        args=[], keywords=[])
    mod.shim_imports.add("fields_of")
    return ast.Call(func=_name("fields_of"), args=[value], keywords=[])


def _synthesize_app_bindings(program: Program, rep: Reporter) -> None:
    """Lower module-level object bindings and their route decorators (docs/DECISIONS.md D41).

    `X = C(...)` at module level becomes the factory `_serp_app_X() -> C`; every
    `@X.m(args...)` on a module function (m a `@registrar` method of C) becomes the call
    `X.m(args..., <endpoint>)` inside that factory, and every other use of the name X
    becomes a call to the factory. Under CPython the binding and the decorators run as
    ordinary Python; the shim's `registrar` wrapper builds the same endpoint dynamically.
    """
    for mod in list(program.modules.values()):
        if not mod.app_bindings:
            continue
        file = str(mod.path)
        rewrites: list[tuple[str, str]] = []
        for xname, call in mod.app_bindings.items():
            span = Span(file, call.lineno, call.col_offset)
            assert isinstance(call.func, ast.Name)
            cname = call.func.id
            c_origin = _origin_of(program, mod, cname)
            cdef = _class_def(program, c_origin)
            if cdef is None:
                rep.fatal("SE206", "mutable-global",
                          f"module-level '{xname}' must be a Copy constant or a class "
                          f"instance `{xname} = SomeClass(...)`", span)
            assert c_origin is not None
            cmod = program.modules[c_origin[0]]
            regs = cmod.registrars.get(c_origin[1], {})
            factory = f"_serp_app_{xname}"
            fbody: list[ast.stmt] = [ast.AnnAssign(
                target=ast.Name(id=xname, ctx=ast.Store()), annotation=_name(cname),
                value=copy.deepcopy(call), simple=1)]
            kept: list[tuple[str, ast.expr]] = []
            ordered: list[tuple[int, ast.stmt]] = []
            for fname, dexpr in mod.decorations:
                target = dexpr.func if isinstance(dexpr, ast.Call) else dexpr
                if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                        and target.value.id == xname):
                    kept.append((fname, dexpr))
                    continue
                dspan = Span(file, dexpr.lineno, dexpr.col_offset)
                meth = regs.get(target.attr)
                if meth is None or not isinstance(dexpr, ast.Call):
                    rep.fatal("SE201", "unsupported-feature",
                              f"@{xname}.{target.attr}(...) is not a @registrar method of "
                              f"'{cname}'", dspan)
                fn = mod.functions.get(fname)
                assert fn is not None
                direct = _registrar_direct(meth)
                if direct is not None:
                    _fill_direct_sig(program, mod, cmod, fn, direct)
                    ep = fname
                else:
                    rq, rs = _registrar_types(cmod, meth, rep, dspan)
                    path = dexpr.args[0].value if dexpr.args and isinstance(dexpr.args[0], ast.Constant) \
                        and isinstance(dexpr.args[0].value, str) else ""
                    rq_local = _import_alias(mod, _origin_of(cmod, cmod, rq) or (cmod.name, rq))
                    rs_local = _import_alias(mod, _origin_of(cmod, cmod, rs) or (cmod.name, rs))
                    ep = _endpoint_for(program, mod, rep, fn, path, rq_local, rs_local)
                kws = [copy.deepcopy(k) for k in dexpr.keywords]
                if fname in mod.async_fns:
                    kws.append(ast.keyword(arg="is_async", value=ast.Constant(value=True)))
                reg = ast.Expr(value=ast.Call(
                    func=ast.Attribute(value=_name(xname), attr=target.attr, ctx=ast.Load()),
                    args=[copy.deepcopy(a) for a in dexpr.args] + [_name(ep)],
                    keywords=kws))
                ast.copy_location(reg, dexpr)
                ordered.append((dexpr.lineno, reg))
            mod.decorations = kept
            for st in mod.app_stmts:
                assert isinstance(st.func, ast.Attribute) and isinstance(st.func.value, ast.Name)
                if st.func.value.id == xname:
                    ordered.append((st.lineno, ast.copy_location(ast.Expr(value=copy.deepcopy(st)),
                                                                 st)))
            ordered.sort(key=lambda t: t[0])
            fbody.extend(s for _ln, s in ordered)
            fbody.append(ast.Return(value=_name(xname)))
            node = ast.FunctionDef(
                name=factory,
                args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                                   kw_defaults=[], kwarg=None, defaults=[]),
                body=fbody, decorator_list=[], returns=_name(cname))
            ast.copy_location(node, call)
            ast.fix_missing_locations(node)
            mod.functions[factory] = node
            rewrites.append((xname, factory))
        factories = {f for _x, f in rewrites}
        for xname, factory in rewrites:
            _rewrite_name_to_call(mod, xname, factory, skip={factory})
            for other in program.modules.values():
                for local, tgt in list(other.imports.items()):
                    if tgt == (mod.name, xname):
                        other.imports[local] = (mod.name, factory)
                        _rewrite_name_to_call(other, local, local, skip=set())
        for (cname, attr), synth in mod.class_attrs.items():
            factory = f"_serp_app_{synth}"
            _rewrite_attr_to_call(mod, cname, attr, factory)
            for other in program.modules.values():
                for local, tgt in list(other.imports.items()):
                    if tgt == (mod.name, cname):
                        other.imports[factory] = (mod.name, factory)
                        _rewrite_attr_to_call(other, local, attr, factory)
        del factories


def _rewrite_attr_to_call(mod: Module, cname: str, attr: str, factory: str) -> None:
    """Replace every load of the class attribute `cname.attr` inside functions/methods with
    a call to its binding factory (module-level `C.attr = D(...)`, D41)."""

    class Rewriter(ast.NodeTransformer):
        def visit_Attribute(self, node: ast.Attribute):
            """Swap a Load of `cname.attr` for the factory call."""
            if node.attr == attr and isinstance(node.value, ast.Name) \
                    and node.value.id == cname and isinstance(node.ctx, ast.Load):
                return ast.copy_location(
                    ast.Call(func=ast.copy_location(_name(factory), node), args=[], keywords=[]),
                    node)
            self.generic_visit(node)
            return node

    rw = Rewriter()
    for fn in list(mod.functions.values()):
        if fn.name != factory:
            rw.visit(fn)
    for cls in mod.classes.values():
        rw.visit(cls)


def _registrar_direct(meth: ast.FunctionDef) -> ast.expr | None:
    """The endpoint annotation of a registrar taking a 2-argument callable (middleware style,
    `Callable[[Rq, Callable[[Rq], Rs]], Rs]`): such decorated functions are passed as is."""
    for a in meth.args.args[1:]:
        ann = a.annotation
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                and ann.value.id == "Callable" and isinstance(ann.slice, ast.Tuple) \
                and len(ann.slice.elts) == 2 and isinstance(ann.slice.elts[0], ast.List) \
                and len(ann.slice.elts[0].elts) == 2:
            return ann
    return None


def _localize_ann(ann: ast.expr, cmod: Module, mod: Module) -> ast.expr:
    """Copy an annotation written in the registrar's module so its class names resolve in mod."""
    out = copy.deepcopy(ann)

    class Localizer(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            """Re-point class names of cmod at import aliases in mod."""
            if node.id in cmod.classes or node.id in cmod.imports:
                origin = _origin_of(cmod, cmod, node.id) or (cmod.name, node.id)
                return ast.copy_location(_name(_import_alias(mod, origin)), node)
            return node

    return Localizer().visit(out)


def _fill_direct_sig(program: Program, mod: Module, cmod: Module, fn: ast.FunctionDef,
                     ann: ast.expr) -> None:
    """Complete a middleware function's signature from the registrar's callable type:
    `(request: Request, call_next)` becomes `(request: Owned[Request], call_next: Callable[...])
    -> Response` so FastAPI-style middleware compiles unchanged."""
    assert isinstance(ann, ast.Subscript) and isinstance(ann.slice, ast.Tuple)
    params_t = ann.slice.elts[0]
    assert isinstance(params_t, ast.List)
    ps = fn.args.args
    if len(ps) == 2:
        p0 = ps[0]
        if p0.annotation is None:
            p0.annotation = _localize_ann(params_t.elts[0], cmod, mod)
        if not (isinstance(p0.annotation, ast.Subscript) and isinstance(p0.annotation.value, ast.Name)
                and p0.annotation.value.id in ("Owned", "Ref", "Mut")):
            p0.annotation = ast.Subscript(value=_name("Owned"), slice=p0.annotation, ctx=ast.Load())
        if ps[1].annotation is None:
            ps[1].annotation = _localize_ann(params_t.elts[1], cmod, mod)
    if fn.returns is None:
        fn.returns = _localize_ann(ann.slice.elts[1], cmod, mod)
    if len(ps) == 2:
        req_name, next_name = ps[0].arg, ps[1].arg

        class MoveIntoNext(ast.NodeTransformer):
            def visit_Call(self, node: ast.Call):
                """`call_next(request)` hands the request over: make the move explicit."""
                self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id == next_name \
                        and len(node.args) == 1 and isinstance(node.args[0], ast.Name) \
                        and node.args[0].id == req_name:
                    node.args[0] = ast.copy_location(
                        ast.Call(func=_name("move"), args=[node.args[0]], keywords=[]), node.args[0])
                return node

        for st in fn.body:
            MoveIntoNext().visit(st)
        mod.shim_imports.add("move")
    ast.fix_missing_locations(fn)
    mod.shim_imports.update({"Owned", "Callable"})


def _registrar_types(cmod: Module, meth: ast.FunctionDef, rep: Reporter,
                     span: Span) -> tuple[str, str]:
    """The (request, response) class names of a registrar's `endpoint: Callable[[Rq], Rs]`."""
    for a in meth.args.args[1:]:
        ann = a.annotation
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                and ann.value.id == "Callable" and isinstance(ann.slice, ast.Tuple) \
                and len(ann.slice.elts) == 2 and isinstance(ann.slice.elts[0], ast.List) \
                and len(ann.slice.elts[0].elts) == 1 \
                and isinstance(ann.slice.elts[0].elts[0], ast.Name) \
                and isinstance(ann.slice.elts[1], ast.Name):
            return ann.slice.elts[0].elts[0].id, ann.slice.elts[1].id
    rep.fatal("SE201", "unsupported-feature",
              f"@registrar method '{meth.name}' needs an endpoint parameter typed "
              f"Callable[[Request], Response]", span)


def _rewrite_name_to_call(mod: Module, xname: str, factory: str, skip: set[str]) -> None:
    """Replace every load of the module-level name `xname` inside functions/methods with
    a call to `factory()`."""

    class Rewriter(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            """Swap a Load of the bound name for the factory call."""
            if node.id == xname and isinstance(node.ctx, ast.Load):
                return ast.copy_location(
                    ast.Call(func=ast.copy_location(_name(factory), node), args=[], keywords=[]),
                    node)
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef):
            """Do not touch the factory (it declares the name locally)."""
            if node.name in skip:
                return node
            self.generic_visit(node)
            return node

    rw = Rewriter()
    for fn in list(mod.functions.values()):
        rw.visit(fn)
    for cls in mod.classes.values():
        rw.visit(cls)


def _rewrite_exception_ctors(program: Program) -> None:
    """`E(args...)` for an exception class with an `__init__` becomes
    `E(_serp_exmsg_E(args...))`, and `e.<attr>` inside `except E as e:` becomes
    `_serp_exattr_E_<attr>(str(e))` for the attributes `__init__` assigns
    (docs/DECISIONS.md D42)."""
    for mod in program.modules.values():
        table: dict[str, tuple[str, str]] = {}
        attrs: dict[str, tuple[str, str, list[str]]] = {}
        for ename, fname in mod.exc_inits.items():
            table[ename] = (mod.name, fname)
            if ename in mod.exc_attrs:
                attrs[ename] = (mod.name, ename, mod.exc_attrs[ename])
        for local, tgt in list(mod.imports.items()):
            sub = program.modules.get(tgt[0])
            if sub is not None and tgt[1] in sub.exc_inits:
                table[local] = (tgt[0], sub.exc_inits[tgt[1]])
                if tgt[1] in sub.exc_attrs:
                    attrs[local] = (tgt[0], tgt[1], sub.exc_attrs[tgt[1]])
        if not table:
            continue

        class Rewriter(ast.NodeTransformer):
            def visit_Call(self, node: ast.Call):
                """Wrap the constructor arguments in the message-factory call."""
                self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id in table \
                        and not (len(node.args) == 1 and not node.keywords
                                 and isinstance(node.args[0], ast.Call)
                                 and isinstance(node.args[0].func, ast.Name)
                                 and node.args[0].func.id.startswith("_serp_exmsg_")):
                    origin = table[node.func.id]
                    local = _import_alias(mod, origin)
                    inner = ast.Call(func=_name(local), args=node.args, keywords=node.keywords)
                    ast.copy_location(inner, node)
                    ast.fix_missing_locations(inner)
                    node.args = [inner]
                    node.keywords = []
                return node

            def visit_ExceptHandler(self, node: ast.ExceptHandler):
                """Route `e.<attr>` reads to the library's message getters."""
                self.generic_visit(node)
                if node.name is None or not isinstance(node.type, ast.Name) \
                        or node.type.id not in attrs:
                    return node
                emod, ename, names = attrs[node.type.id]
                bound = node.name

                class AttrRewriter(ast.NodeTransformer):
                    def visit_Attribute(self, a: ast.Attribute):
                        """`e.x` → `_serp_exattr_E_x(str(e))`."""
                        self.generic_visit(a)
                        if isinstance(a.value, ast.Name) and a.value.id == bound \
                                and isinstance(a.ctx, ast.Load) and a.attr in names:
                            getter = _import_alias(mod, (emod, f"_serp_exattr_{ename}_{a.attr}"))
                            call = ast.Call(
                                func=_name(getter),
                                args=[ast.Call(func=_name("str"), args=[_name(bound)],
                                               keywords=[])],
                                keywords=[])
                            return ast.copy_location(call, a)
                        return a

                node.body = [AttrRewriter().visit(s) for s in node.body]
                ast.fix_missing_locations(node)
                return node

        rw = Rewriter()
        for fn in list(mod.functions.values()):
            rw.visit(fn)
        for cls in mod.classes.values():
            rw.visit(cls)


def _check_name_collision(program: Program, new: Module, rep: Reporter) -> None:
    """Refuse two module names that mangle to the same generated identifier."""
    key = new.name.replace(".", "_")
    for existing in program.modules.values():
        if existing.name != new.name and existing.name.replace(".", "_") == key:
            rep.fatal("SE201", "unsupported-feature",
                      f"module names '{existing.name}' and '{new.name}' collide in "
                      f"generated code (both mangle to '{key}')",
                      Span(str(new.path), 1, 0))


def _report_foreign_import(rep: Reporter, mod: Module, mod_name: str, ctx) -> None:
    """Abort with SE213 for an unresolvable import, suggesting a serp-* equivalent when known."""
    span = _import_span(mod, mod_name)
    roots = [str(r) for r in ctx.searched_roots()]
    shown = ", ".join(roots[:3]) + (f", … (+{len(roots) - 3} more)" if len(roots) > 3 else "")
    alt = SERP_EQUIVALENTS.get(mod_name) or SERP_EQUIVALENTS.get(mod_name.split(".")[0])
    if alt is not None:
        hint = (f"use the Serpentine equivalent: run `serp add {alt[0]}` and write "
                f"`import {alt[1]} as {mod_name.split('.')[-1]}` (or `from {alt[1]} import ...`)")
    else:
        hint = ("native builds can import only your own modules and serp-* libraries "
                "(see docs/libraries.md); run under CPython to use other packages")
    rep.fatal("SE213", "foreign-import",
              f"import of '{mod_name}' does not resolve to a Serpentine module "
              f"(searched: {shown}) — the CPython interop boundary refuses foreign "
              f"imports in native builds (docs/guides/interop.md)", span, help=hint)


def _import_span(mod: Module, mod_name: str) -> Span:
    """Locate the import statement for mod_name for error reporting."""
    for node in mod.tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            target = getattr(node, "module", None)
            if target == mod_name or mod_name in names:
                return Span(str(mod.path), node.lineno, node.col_offset)
    return Span(str(mod.path), 1, 0)


_FLATTEN_SRC = '''
from serpentine import Owned, TypeVar
_SerpFlatT = TypeVar("_SerpFlatT")


def _serp_flatten(xss: Owned[list[list[_SerpFlatT]]]) -> list[_SerpFlatT]:
    """Concatenate a list of lists, moving the elements (multi-for comprehension support)."""
    rev: list[_SerpFlatT] = []
    while len(xss) > 0:
        xs: list[_SerpFlatT] = xss.pop()
        while len(xs) > 0:
            rev.append(xs.pop())
    rev.reverse()
    return rev
'''


def _desugar_comprehensions(tree: ast.Module) -> None:
    """Lower comprehension shapes the backends don't emit directly into ones they do:
    several `if` clauses on one `for` become one `and`, and every extra `for` clause turns
    `[e for a in A for b in B]` into `_serp_flatten([[e for b in B] for a in A])` (same
    element order and evaluation order as CPython). Set comprehensions go through set()."""
    used = [False]

    def merge_ifs(gens: list[ast.comprehension]) -> None:
        for g in gens:
            if len(g.ifs) > 1:
                g.ifs = [ast.copy_location(ast.BoolOp(op=ast.And(), values=list(g.ifs)), g.ifs[0])]

    def split(elt: ast.expr, gens: list[ast.comprehension], at: ast.AST) -> ast.expr:
        if len(gens) == 1:
            return ast.copy_location(ast.ListComp(elt=elt, generators=gens), at)
        used[0] = True
        inner = split(elt, gens[1:], at)
        outer = ast.copy_location(ast.ListComp(elt=inner, generators=[gens[0]]), at)
        return ast.copy_location(ast.Call(func=ast.Name(id="_serp_flatten", ctx=ast.Load()),
                                          args=[outer], keywords=[]), at)

    class Lower(ast.NodeTransformer):
        def visit_ListComp(self, node: ast.ListComp):
            """Multi-clause list comprehension → nested comprehension + flatten."""
            self.generic_visit(node)
            merge_ifs(node.generators)
            if len(node.generators) > 1:
                return split(node.elt, node.generators, node)
            return node

        def visit_SetComp(self, node: ast.SetComp):
            """Multi-clause set comprehension → set(flattened list)."""
            self.generic_visit(node)
            merge_ifs(node.generators)
            if len(node.generators) > 1:
                return ast.copy_location(ast.Call(func=ast.Name(id="set", ctx=ast.Load()),
                                                  args=[split(node.elt, node.generators, node)],
                                                  keywords=[]), node)
            return node

        def visit_DictComp(self, node: ast.DictComp):
            """Dict comprehensions: only the multi-`if` form is lowered."""
            self.generic_visit(node)
            merge_ifs(node.generators)
            return node

    Lower().visit(tree)
    if used[0]:
        helper = ast.parse(_FLATTEN_SRC).body
        for st in helper:
            ast.copy_location(st, tree.body[0] if tree.body else st)
            for sub in ast.walk(st):
                if hasattr(sub, "lineno"):
                    sub.lineno = getattr(tree.body[0], "lineno", 1) if tree.body else 1
                    sub.col_offset = 0
        at = 0
        while at < len(tree.body) and (
                (isinstance(tree.body[at], ast.Expr) and isinstance(tree.body[at].value, ast.Constant)
                 and isinstance(tree.body[at].value.value, str) and at == 0)
                or (isinstance(tree.body[at], ast.ImportFrom) and tree.body[at].module == "__future__")):
            at += 1
        tree.body[at:at] = helper
        ast.fix_missing_locations(tree)


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
    _rewrite_with_statements(tree)
    _desugar_comprehensions(tree)
    mod = Module(name=name, path=path, tree=tree)
    file = str(path)

    for i, node in enumerate(tree.body):
        if isinstance(node, ast.AsyncFunctionDef):
            fn = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                                 decorator_list=node.decorator_list,
                                 returns=node.returns, type_comment=None)
            ast.copy_location(fn, node)
            tree.body[i] = fn
            mod.async_fns.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for j, stmt in enumerate(node.body):
                if isinstance(stmt, ast.AsyncFunctionDef):
                    fn = ast.FunctionDef(name=stmt.name, args=stmt.args, body=stmt.body,
                                         decorator_list=stmt.decorator_list,
                                         returns=stmt.returns, type_comment=None)
                    ast.copy_location(fn, stmt)
                    node.body[j] = fn
                    mod.async_methods = True

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
            elif node.module == "typing":
                for alias in node.names:
                    if alias.asname or alias.name not in TYPING_NAMES:
                        rep.fatal("SE201", "unsupported-feature",
                                  f"'from typing import {alias.asname or alias.name}' is not "
                                  f"supported — the subset understands only "
                                  f"{', '.join(sorted(TYPING_NAMES))}", span)
                    mod.shim_imports.add(alias.name)
            elif node.module == "enum":
                for alias in node.names:
                    if alias.asname or alias.name not in ENUM_BASES:
                        rep.fatal("SE201", "unsupported-feature",
                                  f"'from enum import {alias.asname or alias.name}' is not "
                                  f"supported — only {', '.join(sorted(ENUM_BASES))}", span)
                    mod.shim_imports.add(alias.name)
            elif node.module in RTLIB_MODULES:
                for alias in node.names:
                    local = alias.asname or alias.name
                    fn = RTLIB_FUNCS.get((node.module, alias.name))
                    if fn is not None:
                        mod.rtlib_imports[local] = fn
                        continue
                    cv = RTLIB_CONSTS.get((node.module, alias.name))
                    if cv is not None:
                        mod.rtlib_consts[local] = cv
                        continue
                    rep.fatal("SE201", "unsupported-feature",
                              f"runtime library '{node.module}' has no member "
                              f"'{alias.name}'", span)
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
            if len(node.names) == 1 and node.names[0].name == "asyncio" and node.names[0].asname is None:
                mod.imports_asyncio = True
                for sub in ast.walk(tree):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                            and sub.value.id == "asyncio" and sub.attr not in AIO_CORE:
                        mod.imports.setdefault(_aio_local(sub.attr), ("serp_asyncio", sub.attr))
                continue
            for alias in node.names:
                if alias.name in ("sys", "asyncio", "serpentine", "typing", "enum", "dataclasses"):
                    rep.fatal("SE213", "foreign-import",
                              f"'import {alias.name}' is only supported as a bare 'import sys' / "
                              f"'import asyncio'; use 'from {alias.name} import ...'", span)
                mod.module_aliases[alias.asname or alias.name] = alias.name
            continue
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                for d in node.decorator_list:
                    if not isinstance(d, (ast.Name, ast.Call)):
                        rep.fatal("SE201", "unsupported-feature",
                                  "a decorator must be a function name or a call that "
                                  "returns a decorator", span)
                for a in node.args.args:
                    ann = a.annotation
                    if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                            and ann.value.id in ("Ref", "Mut"):
                        rep.fatal("SE201", "unsupported-feature",
                                  "decorated functions may not take Ref/Mut parameters — "
                                  "they are used as first-class values (by-value calls only)",
                                  span)
                for d in reversed(node.decorator_list):
                    mod.decorations.append((node.name, d))
                node.decorator_list = []
            mod.functions[node.name] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) \
                    and node.value.func.id not in ("TypeVar",):
                mod.app_bindings[node.target.id] = node.value
            else:
                mod.constants[node.target.id] = node
        elif _is_entry_guard(node):
            call = node.body[0]
            assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
            target = call.value
            if isinstance(target.func, ast.Attribute):
                target = target.args[0]
            assert isinstance(target, ast.Call) and isinstance(target.func, ast.Name)
            mod.entry_call = target.func.id
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
            if _is_enum_class(node):
                if node.bases[0].id not in mod.shim_imports:
                    rep.fatal("SE201", "unsupported-feature",
                              f"enum classes need 'from enum import {node.bases[0].id}'", span)
                _check_enum_body(node, rep, span)
                mod.enums[node.name] = node
                continue
            if _is_exception_class(node):
                mod.exceptions[node.name] = node.bases[0].id
                _lift_exception_init(mod, node, rep, span)
                continue
            deco = node.decorator_list
            plain_bases = [b for b in node.bases if not _is_generic_base(b)]
            if not deco and len(plain_bases) == 1 and isinstance(plain_bases[0], ast.Name) \
                    and not node.keywords:
                deco = [ast.Name(id="dataclass", ctx=ast.Load())]
                node.decorator_list = list(deco)
            if len(deco) == 1 and isinstance(deco[0], ast.Call) \
                    and isinstance(deco[0].func, ast.Name) and deco[0].func.id == "dataclass":
                if _dataclass_frozen(deco[0], rep, span):
                    mod.frozen_classes.add(node.name)
                deco = [ast.Name(id="dataclass", ctx=ast.Load())]
                node.decorator_list = list(deco)
            if not (len(deco) == 1 and isinstance(deco[0], ast.Name) and deco[0].id == "dataclass"):
                rep.fatal("SE201", "unsupported-feature",
                          "classes must carry exactly the @dataclass decorator "
                          "(from serpentine import dataclass) — a class inheriting a "
                          "@dataclass base may omit it", span,
                          help="write classes as `@dataclass` with annotated fields (an `__init__` "
                               "is allowed); single inheritance from another @dataclass works, but "
                               "super() calls and virtual dispatch are not supported "
                               "(docs/language/divergences.md)")
            if node.keywords or plain_bases:
                if not node.keywords and len(plain_bases) == 1 \
                        and isinstance(plain_bases[0], ast.Name):
                    mod.class_bases[node.name] = plain_bases[0].id
                    node.bases = [b for b in node.bases if _is_generic_base(b)]
                else:
                    rep.fatal("SE201", "unsupported-feature",
                              "class inheritance is single only: 'class C(Base)' with one "
                              "@dataclass base (or a Generic[...] base for generic classes)",
                              span)
            _collect_class_overloads(mod, node, rep, file)
            _collect_class_hooks(mod, node, rep, file)
            _collect_registrars(mod, node, rep, file)
            _lift_static_methods(mod, node)
            mod.classes[node.name] = node
        elif _is_typevar_decl(node):
            assert isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            tv_name = node.targets[0].id
            mod.typevars.add(tv_name)
            assert isinstance(node.value, ast.Call)
            for kw in node.value.keywords:
                assert kw.arg == "bound" and isinstance(kw.value, ast.Name)
                mod.typevar_bounds[tv_name] = kw.value.id
        elif _is_type_alias(node):
            assert isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            mod.type_aliases[node.targets[0].id] = _expand_alias_factory(
                node.value, rep, str(mod.path))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            mod.app_bindings[node.targets[0].id] = node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Attribute) \
                and isinstance(node.targets[0].value, ast.Name) \
                and node.targets[0].value.id in mod.classes \
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            synth = f"_serp_ca_{node.targets[0].value.id}_{node.targets[0].attr}"
            mod.app_bindings[synth] = node.value
            mod.class_attrs[(node.targets[0].value.id, node.targets[0].attr)] = synth
        elif isinstance(node, ast.Assign):
            rep.fatal("SE206", "mutable-global",
                      "module-level bindings must be annotated Copy-typed constants", span,
                      help="move script code into `def main() -> None:` and call it under "
                           "`if __name__ == \"__main__\":`; the module level may only hold "
                           "annotated constants such as `LIMIT: int = 10`")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) \
                and isinstance(node.value.func.value, ast.Name) \
                and node.value.func.value.id in mod.app_bindings:
            mod.app_stmts.append(node.value)
        else:
            rep.fatal("SE205", "module-level-statement",
                      "only imports, function definitions, classes, Copy constants, and the "
                      "entry guard are allowed at module level", span)
    if mod.module_aliases:
        _rewrite_module_attrs(mod, tree, rep)
    _fold_negative_literals(mod)
    if mod.rtlib_consts:
        _fold_rtlib_consts(mod, rep)
    return mod


def _dotted(e: ast.expr) -> str | None:
    """`a.b.c` text of a Name/Attribute chain (None for anything else)."""
    if isinstance(e, ast.Name):
        return e.id
    if isinstance(e, ast.Attribute):
        inner = _dotted(e.value)
        return None if inner is None else inner + "." + e.attr
    return None


def _rewrite_module_attrs(mod: Module, tree: ast.Module, rep: Reporter) -> None:
    """`import a.b [as c]`: every load of `a.b.x` (or `c.x`) becomes a synthesized local
    bound exactly like `from a.b import x` would bind it (rtlib members included)."""
    aliases = mod.module_aliases
    file = str(mod.path)

    class Rewriter(ast.NodeTransformer):
        def visit_Attribute(self, node: ast.Attribute):
            """Replace `<module path>.<member>` with the member's synthesized local name."""
            path = _dotted(node.value)
            if path is not None and path in aliases and isinstance(node.ctx, ast.Load):
                target = aliases[path]
                local = f"_serp_imp_{path.replace('.', '_')}__{node.attr}"
                if target in RTLIB_MODULES:
                    fn = RTLIB_FUNCS.get((target, node.attr))
                    cv = RTLIB_CONSTS.get((target, node.attr))
                    if fn is not None:
                        mod.rtlib_imports[local] = fn
                    elif cv is not None:
                        mod.rtlib_consts[local] = cv
                    else:
                        rep.fatal("SE201", "unsupported-feature",
                                  f"runtime library '{target}' has no member '{node.attr}'",
                                  Span(file, node.lineno, node.col_offset))
                else:
                    mod.imports[local] = (target, node.attr)
                return ast.copy_location(ast.Name(id=local, ctx=ast.Load()), node)
            self.generic_visit(node)
            return node

    Rewriter().visit(tree)


HOOK_DECOS = {"field_validator": "field", "model_validator": "model",
              "field_serializer": "serializer", "model_serializer": "modelser",
              "computed_field": "computed"}
HOOK_MODES = {"field": ("before", "after", "plain"), "model": ("before", "after"),
              "serializer": ("plain",), "modelser": ("plain",), "computed": ("plain",)}
HOOK_NAMED = {"field", "serializer"}


def _dataclass_frozen(call: ast.Call, rep: Reporter, span: Span) -> bool:
    """Read `@dataclass(frozen=...)`; every other dataclass argument is rejected."""
    if call.args:
        rep.fatal("SE201", "unsupported-feature",
                  "@dataclass(...) takes no positional arguments", span)
    frozen = False
    for kw in call.keywords:
        if kw.arg != "frozen" or not (isinstance(kw.value, ast.Constant)
                                      and isinstance(kw.value.value, bool)):
            rep.fatal("SE201", "unsupported-feature",
                      "@dataclass(...) accepts only 'frozen=True' or 'frozen=False'", span)
        frozen = bool(kw.value.value)
    return frozen


def _collect_class_overloads(mod: Module, node: ast.ClassDef, rep: Reporter, file: str) -> None:
    """Strip `@overload` method stubs from a class body and keep them as typed signatures
    (D40): the undecorated implementation stays the only method; the stubs only refine the
    call-site type by argument type."""
    stubs: dict[str, list[ast.FunctionDef]] = {}
    kept: list[ast.stmt] = []
    for st in node.body:
        is_stub = (isinstance(st, ast.FunctionDef) and len(st.decorator_list) == 1
                   and isinstance(st.decorator_list[0], ast.Name)
                   and st.decorator_list[0].id == "overload")
        if not is_stub:
            kept.append(st)
            continue
        assert isinstance(st, ast.FunctionDef)
        st.decorator_list = []
        stubs.setdefault(st.name, []).append(st)
    if not stubs:
        return
    span = Span(file, node.lineno, node.col_offset)
    impl_names = {st.name for st in kept if isinstance(st, ast.FunctionDef)}
    for name in stubs:
        if name not in impl_names:
            rep.fatal("SE201", "unsupported-feature",
                      f"@overload stubs for '{name}' need an undecorated implementation "
                      f"in the same class", span)
    node.body = kept
    mod.class_overloads[node.name] = stubs


def _collect_class_hooks(mod: Module, node: ast.ClassDef, rep: Reporter, file: str) -> None:
    """Record validator / serializer / computed-field methods as build-time class hooks."""
    hooks: list[dict] = []
    for st in node.body:
        if not isinstance(st, ast.FunctionDef):
            continue
        kept = []
        for d in st.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            kind = HOOK_DECOS.get(target.id) if isinstance(target, ast.Name) else None
            if kind is None:
                kept.append(d)
                continue
            span = Span(file, d.lineno, d.col_offset)
            fields_named: list[str] = []
            modes = HOOK_MODES[kind]
            mode = modes[0] if kind not in ("field", "model") else "after"
            if isinstance(d, ast.Call):
                for a in d.args:
                    if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                        rep.fatal("SE201", "unsupported-feature",
                                  f"@{target.id} arguments must be string literals", span)
                    fields_named.append(a.value)
                for kw in d.keywords:
                    if kw.arg != "mode" or not (isinstance(kw.value, ast.Constant)
                                                and isinstance(kw.value.value, str)):
                        rep.fatal("SE201", "unsupported-feature",
                                  f"@{target.id} accepts only "
                                  f"mode={'|'.join(repr(m) for m in modes)}", span)
                    mode = kw.value.value
            if mode not in modes:
                rep.fatal("SE201", "unsupported-feature",
                          f"@{target.id} mode must be "
                          f"{' or '.join(repr(m) for m in modes)}", span)
            if kind in HOOK_NAMED and not fields_named:
                rep.fatal("SE201", "unsupported-feature",
                          f"@{target.id} needs at least one field name", span)
            if kind not in HOOK_NAMED and fields_named:
                rep.fatal("SE201", "unsupported-feature",
                          f"@{target.id} takes no field names", span)
            hooks.append({"kind": kind, "mode": mode, "fields": fields_named,
                          "method": st.name})
        st.decorator_list = kept
    if hooks:
        mod.class_hooks[node.name] = hooks


def _collect_registrars(mod: Module, node: ast.ClassDef, rep: Reporter, file: str) -> None:
    """Strip `@registrar` from methods and record them (D41): `@X.m(args)` on a module function
    lowers to `X.m(args, <endpoint>)` inside the factory of the module-level binding X."""
    found: dict[str, ast.FunctionDef] = {}
    for st in node.body:
        if not isinstance(st, ast.FunctionDef):
            continue
        kept = []
        for d in st.decorator_list:
            if isinstance(d, ast.Name) and d.id == "registrar":
                if "registrar" not in mod.shim_imports:
                    rep.fatal("SE201", "unsupported-feature",
                              "@registrar needs 'from serpentine import registrar'",
                              Span(file, d.lineno, d.col_offset))
                found[st.name] = st
            else:
                kept.append(d)
        st.decorator_list = kept
    if found:
        mod.registrars[node.name] = found


def _lift_static_methods(mod: Module, node: ast.ClassDef) -> None:
    """Move @staticmethod/@classmethod defs out of a class body into module functions.

    A classmethod loses its `cls` parameter; the class it was declared on is
    recorded so the checker can bind `cls` and `Self` at build time.
    """
    statics: dict[str, str] = {}
    kept = []
    for st in node.body:
        deco = None
        if isinstance(st, ast.FunctionDef) and len(st.decorator_list) == 1 \
                and isinstance(st.decorator_list[0], ast.Name):
            deco = st.decorator_list[0].id
        if deco == "staticmethod":
            mangled = f"_static_{node.name}_{st.name}"
            statics[st.name] = mangled
            st.decorator_list = []
            st.name = mangled
            mod.functions[mangled] = st
        elif deco == "classmethod":
            mangled = f"_static_{node.name}_{st.name}"
            statics[st.name] = mangled
            st.decorator_list = []
            st.name = mangled
            if st.args.args and st.args.args[0].arg == "cls":
                st.args.args.pop(0)
            mod.functions[mangled] = st
            mod.cls_bound[mangled] = node.name
        else:
            kept.append(st)
    node.body = kept
    if statics:
        mod.class_statics[node.name] = statics


def _rewrite_with_statements(tree: ast.Module) -> None:
    """Rewrite `with <expr> as n:` (non-open) into `n = <expr>; n.__enter__(); try: ... finally: n.__exit__(...)`.

    File `with open(...)` keeps its dedicated RAII lowering. Under CPython the
    original source runs the real context-manager protocol; the rewrite is
    equivalent because __enter__ is required to end with `return self`, so the
    bound name is the object itself and any side effects (e.g. acquiring a lock)
    still run.
    """

    counter = [0]

    class WithRewriter(ast.NodeTransformer):
        def visit_With(self, node: ast.With):
            """Rewrite one user-object with-block into assign + try/finally."""
            return self._rewrite(node, "__enter__", "__exit__")

        def visit_AsyncWith(self, node: ast.AsyncWith):
            """`async with` follows the same lowering through __aenter__/__aexit__ (D45)."""
            return self._rewrite(node, "__aenter__", "__aexit__")

        def _rewrite(self, node, enter: str, exit_: str):
            """Shared with/async-with lowering."""
            self.generic_visit(node)
            if len(node.items) != 1:
                return node
            item = node.items[0]
            ctx = item.context_expr
            if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Name) \
                    and ctx.func.id == "open":
                return node
            if item.optional_vars is None and isinstance(ctx, ast.Name):
                tname = ctx.id
                assign = None
            elif item.optional_vars is None:
                counter[0] += 1
                tname = f"_serp_with_{counter[0]}"
                assign = ast.Assign(
                    targets=[ast.Name(id=tname, ctx=ast.Store())], value=ctx)
            elif isinstance(item.optional_vars, ast.Name):
                tname = item.optional_vars.id
                assign = ast.Assign(
                    targets=[ast.Name(id=tname, ctx=ast.Store())], value=ctx)
            else:
                return node
            enter_call = ast.Expr(value=ast.Call(
                func=ast.Attribute(value=ast.Name(id=tname, ctx=ast.Load()),
                                   attr=enter, ctx=ast.Load()),
                args=[], keywords=[]))
            enter_call.value._serp_with_enter = True
            exit_call = ast.Expr(value=ast.Call(
                func=ast.Attribute(value=ast.Name(id=tname, ctx=ast.Load()),
                                   attr=exit_, ctx=ast.Load()),
                args=[ast.Constant(value=None), ast.Constant(value=None),
                      ast.Constant(value=None)],
                keywords=[]))
            tryst = ast.Try(body=node.body, handlers=[], orelse=[],
                            finalbody=[exit_call])
            out = [enter_call, tryst] if assign is None else [assign, enter_call, tryst]
            for n in (enter_call, exit_call, tryst) + ((assign,) if assign is not None else ()):
                ast.copy_location(n, node)
            return out

    WithRewriter().visit(tree)
    ast.fix_missing_locations(tree)


def _fold_negative_literals(mod: Module) -> None:
    """Fold unary-minus number literals into plain constants (-1 -> Constant(-1))."""

    class NegFolder(ast.NodeTransformer):
        def visit_UnaryOp(self, node: ast.UnaryOp):
            """Rewrite USub over an int/float literal into a negative Constant."""
            self.generic_visit(node)
            if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) \
                    and isinstance(node.operand.value, (int, float)) \
                    and not isinstance(node.operand.value, bool):
                return ast.copy_location(ast.Constant(value=-node.operand.value), node)
            return node

    mod.tree = ast.fix_missing_locations(NegFolder().visit(mod.tree))


def _fold_rtlib_consts(mod: Module, rep: Reporter) -> None:
    """Replace loads of imported rtlib constants (pi, e, ...) with float literals."""

    consts = mod.rtlib_consts
    file = str(mod.path)

    class Folder(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if node.id in consts:
                if not isinstance(node.ctx, ast.Load):
                    rep.fatal("SE206", "mutable-global",
                              f"cannot assign to runtime-library constant '{node.id}'",
                              Span(file, node.lineno, node.col_offset))
                return ast.copy_location(ast.Constant(value=consts[node.id]), node)
            return node

    mod.tree = ast.fix_missing_locations(Folder().visit(mod.tree))


def _is_generic_base(node: ast.expr) -> bool:
    """Recognize `Generic[T, ...]` as the sole permitted class base."""
    return (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == "Generic")


def _is_protocol_class(node: ast.ClassDef) -> bool:
    """Recognize `class P(Protocol):` as a Tier-2 structural protocol."""
    return (len(node.bases) == 1 and isinstance(node.bases[0], ast.Name)
            and node.bases[0].id == "Protocol")


def _is_enum_class(node: ast.ClassDef) -> bool:
    """Recognize `class C(Enum):` with constant members as a C-like enum."""
    return (not node.decorator_list and not node.keywords and len(node.bases) == 1
            and isinstance(node.bases[0], ast.Name) and node.bases[0].id in ENUM_BASES)


def enum_members(node: ast.ClassDef) -> list[tuple[str, object]]:
    """The (name, constant value) members of an enum class, in source order."""
    out: list[tuple[str, object]] = []
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) \
                and isinstance(stmt.value, ast.Constant):
            out.append((stmt.targets[0].id, stmt.value.value))
    return out


def _check_enum_body(node: ast.ClassDef, rep: Reporter, span: Span) -> None:
    """Enum bodies are constant `NAME = <int|str>` members only."""
    members = enum_members(node)
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                and isinstance(stmt.value.value, str):
            continue
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) \
                and isinstance(stmt.value, ast.Constant) \
                and isinstance(stmt.value.value, (int, str)) \
                and not isinstance(stmt.value.value, bool):
            continue
        rep.fatal("SE201", "unsupported-feature",
                  f"enum '{node.name}' may only contain constant 'NAME = <int|str>' "
                  f"members — methods and computed members are not supported", span)
    if not members:
        rep.fatal("SE201", "unsupported-feature",
                  f"enum '{node.name}' declares no members", span)
    kinds = {type(v) for _, v in members}
    if len(kinds) != 1:
        rep.fatal("SE201", "unsupported-feature",
                  f"enum '{node.name}' mixes int and str member values", span)
    base = node.bases[0].id
    if base == "IntEnum" and kinds != {int}:
        rep.fatal("SE201", "unsupported-feature",
                  f"IntEnum '{node.name}' needs int members", span)
    if base == "StrEnum" and kinds != {str}:
        rep.fatal("SE201", "unsupported-feature",
                  f"StrEnum '{node.name}' needs str members", span)
    seen: set = set()
    for name, value in members:
        if value in seen:
            rep.fatal("SE201", "unsupported-feature",
                      f"enum '{node.name}' member '{name}' repeats a value — aliases "
                      f"are not supported", span)
        seen.add(value)


def _is_exception_class(node: ast.ClassDef) -> bool:
    """Recognize `class E(Base): pass` (single Name base) as an exception class; the body may
    also hold one `__init__` whose only statement is `super().__init__(<str expr>)` (D42)."""
    if node.decorator_list or node.keywords:
        return False
    if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
        return False
    return all(isinstance(s, ast.Pass)
               or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                   and isinstance(s.value.value, str))
               or _exc_init_message(s) is not None
               for s in node.body)


def _exc_init_message(st: ast.stmt) -> ast.expr | None:
    """The `<expr>` of an exception `__init__` body `[self.x = ...]* super().__init__(<expr>)`,
    else None."""
    if not (isinstance(st, ast.FunctionDef) and st.name == "__init__"
            and not st.decorator_list):
        return None
    body = [s for s in st.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))]
    if not body or not isinstance(body[-1], ast.Expr):
        return None
    for s in body[:-1]:
        if not (isinstance(s, ast.Assign) and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Attribute)
                and isinstance(s.targets[0].value, ast.Name)
                and s.targets[0].value.id == "self"):
            return None
    call = body[-1].value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "__init__" and isinstance(call.func.value, ast.Call)
            and isinstance(call.func.value.func, ast.Name)
            and call.func.value.func.id == "super" and not call.func.value.args
            and len(call.args) == 1 and not call.keywords):
        return None
    return call.args[0]


def _exc_init_attrs(st: ast.FunctionDef) -> list[str]:
    """The `self.<name>` attributes an exception `__init__` assigns (D42)."""
    out: list[str] = []
    for s in st.body:
        if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Attribute):
            out.append(s.targets[0].attr)
    return out


def _lift_exception_init(mod: Module, node: ast.ClassDef, rep: Reporter, span: Span) -> None:
    """Turn an exception class's `__init__` into the module function `_serp_exmsg_<E>(...) -> str`
    (D42): constructor calls `E(args...)` are rewritten to `E(_serp_exmsg_E(args...))`."""
    inits = [s for s in node.body if isinstance(s, ast.FunctionDef)]
    if not inits:
        return
    init = inits[0]
    msg = _exc_init_message(init)
    assert msg is not None
    args = init.args
    if not args.args or args.args[0].arg != "self" or args.args[0].annotation is not None \
            or args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs:
        rep.fatal("SE201", "unsupported-feature",
                  f"exception '{node.name}.__init__' must be "
                  f"'def __init__(self, <annotated params>) -> None' with the single "
                  f"statement super().__init__(<message>)", span)
    fname = f"_serp_exmsg_{node.name}"
    fn = ast.FunctionDef(
        name=fname,
        args=ast.arguments(posonlyargs=[], args=[copy.deepcopy(a) for a in args.args[1:]],
                           vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None,
                           defaults=[copy.deepcopy(d) for d in args.defaults]),
        body=[ast.Return(value=copy.deepcopy(msg))], decorator_list=[],
        returns=ast.Name(id="str", ctx=ast.Load()))
    ast.copy_location(fn, init)
    ast.fix_missing_locations(fn)
    mod.functions[fname] = fn
    mod.exc_inits[node.name] = fname
    attrs = _exc_init_attrs(init)
    if attrs:
        mod.exc_attrs[node.name] = attrs


ALIAS_CTORS = {"Annotated", "Optional", "Union", "list", "dict", "set", "frozenset", "tuple",
               "Callable", "Shared", "Weak"}

# Constrained-type factories: `Age = conint(gt=0)` is a *call* in type-alias position, which
# cannot fold on its own. Each desugars to the equivalent `Annotated[base, Field(...)]` form
# the rest of the pipeline already understands.
ALIAS_FACTORY_BASE = {"conint": "int", "confloat": "float", "constr": "str",
                      "conbytes": "bytes"}


def _alias_factory_call(v: ast.expr) -> bool:
    """True for `conint(...)`-style constrained-type factory calls."""
    return (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
            and (v.func.id in ALIAS_FACTORY_BASE or v.func.id == "conlist")
            and not v.args[1:])


def _expand_alias_factory(v: ast.expr, rep: Reporter, file: str) -> ast.expr:
    """Rewrite `conint(gt=0)` to `Annotated[int, Field(gt=0)]` (and conlist to list[T])."""
    if not _alias_factory_call(v):
        return v
    assert isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
    span = Span(file, v.lineno, v.col_offset)
    if v.func.id == "conlist":
        if len(v.args) != 1:
            rep.fatal("SE201", "unsupported-feature",
                      "conlist() takes the item type as its only positional argument", span)
        base: ast.expr = ast.Subscript(value=ast.Name(id="list", ctx=ast.Load()),
                                       slice=v.args[0], ctx=ast.Load())
    else:
        if v.args:
            rep.fatal("SE201", "unsupported-feature",
                      f"{v.func.id}() takes keyword constraints only", span)
        base = ast.Name(id=ALIAS_FACTORY_BASE[v.func.id], ctx=ast.Load())
    meta = ast.Call(func=ast.Name(id="Field", ctx=ast.Load()), args=[], keywords=v.keywords)
    out = ast.Subscript(value=ast.Name(id="Annotated", ctx=ast.Load()),
                        slice=ast.Tuple(elts=[base, meta], ctx=ast.Load()), ctx=ast.Load())
    return ast.fix_missing_locations(ast.copy_location(out, v))


def _is_type_alias(node: ast.stmt) -> bool:
    """Recognize a module-level type alias: `Name = list[int]` / `Annotated[...]` / `A | B`."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)):
        return False
    v = node.value
    if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name):
        return v.value.id in ALIAS_CTORS
    if _alias_factory_call(v):
        return True
    return isinstance(v, ast.BinOp) and isinstance(v.op, ast.BitOr)


def _expand_alias(node: ast.expr, aliases: dict[str, ast.expr], depth: int = 0) -> ast.expr:
    """A copy of a type expression with module-level type aliases substituted in."""
    if depth > 16:
        return node
    if isinstance(node, ast.Name):
        if node.id in aliases:
            return _expand_alias(copy.deepcopy(aliases[node.id]), aliases, depth + 1)
        return node
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        out = ast.BinOp(left=_expand_alias(node.left, aliases, depth + 1), op=node.op,
                        right=_expand_alias(node.right, aliases, depth + 1))
        return ast.fix_missing_locations(ast.copy_location(out, node))
    if isinstance(node, ast.List):
        out = ast.List(elts=[_expand_alias(e, aliases, depth + 1) for e in node.elts],
                       ctx=ast.Load())
        return ast.fix_missing_locations(ast.copy_location(out, node))
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        elts = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if node.value.id == "Annotated":
            head = _expand_alias(elts[0], aliases, depth + 1)
            extras = elts[1:]
            if isinstance(head, ast.Subscript) and isinstance(head.value, ast.Name) \
                    and head.value.id == "Annotated":
                inner = list(head.slice.elts) if isinstance(head.slice, ast.Tuple) \
                    else [head.slice]
                head, extras = inner[0], inner[1:] + extras
            new = [head] + extras
        else:
            new = [_expand_alias(e, aliases, depth + 1) for e in elts]
        sl: ast.expr = ast.Tuple(elts=new, ctx=ast.Load()) if len(new) > 1 else new[0]
        out = ast.Subscript(value=node.value, slice=ast.copy_location(sl, node.slice),
                            ctx=node.ctx)
        return ast.fix_missing_locations(ast.copy_location(out, node))
    return node


def resolve_reexports(modules: dict[str, Module]) -> None:
    """Flatten `from a import x` where `a` itself only re-imports `x`, so every import names the defining module."""
    def defines(mod: Module, name: str) -> bool:
        return (name in mod.functions or name in mod.classes or name in mod.constants
                or name in mod.enums or name in mod.protocols or name in mod.type_aliases
                or name in mod.exceptions or name in mod.class_statics
                or name in mod.rtlib_imports or name in mod.rtlib_consts)

    for mod in modules.values():
        for local, (omod, oname) in list(mod.imports.items()):
            seen: set[tuple[str, str]] = set()
            while (omod, oname) not in seen:
                seen.add((omod, oname))
                target = modules.get(omod)
                if target is None or defines(target, oname) or oname not in target.imports:
                    break
                omod, oname = target.imports[oname]
            if (omod, oname) != mod.imports[local]:
                target = modules.get(omod)
                if target is not None and oname in target.rtlib_consts:
                    mod.rtlib_consts[local] = target.rtlib_consts[oname]
                    del mod.imports[local]
                elif target is not None and oname in target.rtlib_imports:
                    mod.rtlib_imports[local] = target.rtlib_imports[oname]
                    del mod.imports[local]
                else:
                    mod.imports[local] = (omod, oname)


def expand_type_aliases(modules: dict[str, Module]) -> None:
    """Substitute every module-level type alias into the annotations that mention it."""
    own: dict[str, dict[str, ast.expr]] = {}
    for name, mod in modules.items():
        own[name] = {k: _expand_alias(v, mod.type_aliases)
                     for k, v in mod.type_aliases.items()}
    for name, mod in modules.items():
        table = dict(own[name])
        for local, (omod, oname) in mod.imports.items():
            if oname in own.get(omod, {}):
                table[local] = own[omod][oname]
        if not table:
            continue
        trees: list[ast.AST] = [*mod.functions.values(), *mod.classes.values(),
                                *mod.protocols.values(), *mod.constants.values()]
        for tree in trees:
            for n in ast.walk(tree):
                if isinstance(n, (ast.AnnAssign, ast.arg)) and n.annotation is not None:
                    n.annotation = _expand_alias(n.annotation, table)
                elif isinstance(n, ast.FunctionDef) and n.returns is not None:
                    n.returns = _expand_alias(n.returns, table)


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
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    call = stmt.value
    if isinstance(call.func, ast.Name) and not call.args:
        return True
    return (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "asyncio" and call.func.attr == "run"
            and len(call.args) == 1 and not call.keywords
            and isinstance(call.args[0], ast.Call)
            and isinstance(call.args[0].func, ast.Name) and not call.args[0].args)
