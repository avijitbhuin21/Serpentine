"""Runtime no-op shim for the Serpentine ownership vocabulary.

Everything in this module is inert under CPython: the ownership wrappers are
``typing.Annotated`` aliases (invisible to type checkers and the runtime alike)
and ``move`` is the identity function. All semantics live in ``serp check``.
This API is part of the Serpentine language spec; treat changes as spec changes.
"""

import dataclasses as _dataclasses
from typing import Annotated, Callable, Generic, Protocol, TypeVar

__version__ = "0.9.2"

__all__ = ["Owned", "Ref", "Mut", "Shared", "Weak", "move", "native", "Callable",
           "dataclass", "TypeVar", "Generic", "Protocol", "share", "downgrade", "upgrade",
           "PyVal", "pyval_kind", "spawn", "JoinHandle", "Thread", "Timer",
           "fields_of", "fields_json", "fields_build", "fields_set", "Field",
           "ConfigDict", "field_validator", "model_validator", "hooks_json",
           "run_hook", "run_hook_self", "AfterValidator", "BeforeValidator",
           "Json", "SkipValidation", "Base64",
           "conint", "confloat", "constr", "conbytes", "conlist",
           "field_serializer", "model_serializer", "computed_field",
           "run_hook_get", "run_hook_val", "run_hook_info", "registrar", "block_on"]

T = TypeVar("T")


class _FieldInfo:
    """Carrier for the build-time field metadata declared by Field()."""

    def __init__(self, meta: dict):
        self.__serp_field_meta__ = meta

    def __repr__(self) -> str:
        return "Field(" + ", ".join(f"{k}={v!r}"
                                    for k, v in self.__serp_field_meta__.items()) + ")"


_MISSING = object()


def Field(default=_MISSING, **kwargs) -> _FieldInfo:
    """Declare build-time field metadata (default, constraints, aliases, docs)."""
    meta = dict(kwargs)
    if default is not _MISSING:
        meta["default"] = default
    return _FieldInfo(meta)


def _meta_value(v):
    """Normalize a metadata value the way the compiler folds it (functions by name)."""
    if isinstance(v, (staticmethod, classmethod)):
        v = v.__func__
    if callable(v) and not isinstance(v, type):
        return {"__fn__": v.__name__}
    if isinstance(v, (list, tuple)):
        return [_meta_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _meta_value(x) for k, x in v.items()}
    return v


def _annotated_entry(extra) -> dict:
    """Describe a non-Field `Annotated[...]` marker the way the compiler folds the call."""
    if _dataclasses.is_dataclass(extra):
        args = [getattr(extra, f.name) for f in _dataclasses.fields(extra)]
    else:
        args = list(vars(extra).values())
    return {"call": type(extra).__name__, "args": [_meta_value(a) for a in args]}


def _annotated_extras(cls) -> dict:
    """Per-field `Annotated[...]` extras, resolving string annotations when possible."""
    anns = dict(getattr(cls, "__annotations__", {}))
    if any(type(a) is str for a in anns.values()):
        import typing
        try:
            anns = typing.get_type_hints(cls, include_extras=True)
        except Exception:
            return {}
    return {n: getattr(a, "__metadata__", ()) for n, a in anns.items()}


def dataclass(cls=None, /, **kwargs):
    """Stdlib dataclass, plus empty list/dict field defaults become per-instance factories."""
    def wrap(c):
        meta = dict(getattr(c, "__serp_field_meta__", {}))
        for fname in getattr(c, "__annotations__", {}):
            val = c.__dict__.get(fname)
            if isinstance(val, (list, dict)) and not val:
                setattr(c, fname, _dataclasses.field(default_factory=type(val)))
                continue
            fmeta = getattr(val, "__serp_field_meta__", None)
            if fmeta is None:
                continue
            meta[fname] = dict(fmeta)
            factory = fmeta.get("default_factory")
            if factory is not None:
                setattr(c, fname, _dataclasses.field(default_factory=factory))
            elif "default" in fmeta:
                dv = fmeta["default"]
                if isinstance(dv, (list, dict, set)):
                    setattr(c, fname, _dataclasses.field(default_factory=lambda d=dv: type(d)(d)))
                else:
                    setattr(c, fname, dv)
            else:
                delattr(c, fname)
        for fname, extras in _annotated_extras(c).items():
            for extra in extras:
                fmeta = getattr(extra, "__serp_field_meta__", None)
                if fmeta is not None:
                    meta[fname] = {**dict(fmeta), **meta.get(fname, {})}
        out = _dataclasses.dataclass(c, **kwargs)
        if getattr(out, "__setattr__", None) is not object.__setattr__:
            _bypass_setattr_in_init(out)
        _splat_tuple_keys(out)
        if meta:
            out.__serp_field_meta__ = meta
        if getattr(out, "__parameters__", ()):
            out.__serp_orig_getitem__ = staticmethod(out.__class_getitem__)
            out.__class_getitem__ = classmethod(_parametrized)
        out.__init_subclass__ = classmethod(_auto_dataclass)
        return out
    return wrap if cls is None else wrap(cls)


def _splat_tuple_keys(cls) -> None:
    """Mirror the compiler (D43): `x[a, b]` reaches a multi-parameter `__getitem__` /
    `__setitem__` as separate arguments, so a tuple key is splatted under CPython."""
    for name, extra in (("__getitem__", 0), ("__setitem__", 1)):
        fn = cls.__dict__.get(name)
        code = getattr(fn, "__code__", None)
        if code is None or code.co_argcount < 3 + extra:
            continue

        def make(impl, extra=extra):
            if extra == 0:
                def __getitem__(self, key):
                    if isinstance(key, tuple):
                        return impl(self, *key)
                    return impl(self, key)
                return __getitem__

            def __setitem__(self, key, value):
                if isinstance(key, tuple):
                    return impl(self, *key, value)
                return impl(self, key, value)
            return __setitem__
        setattr(cls, name, make(fn))


def _parametrized(cls, item):
    """Make `Model[int]` a concrete subclass so classmethods see the bound type arguments."""
    import typing
    args = item if isinstance(item, tuple) else (item,)
    params = getattr(cls, "__parameters__", ())
    if len(args) != len(params) or any(isinstance(a, typing.TypeVar) for a in args):
        return cls.__serp_orig_getitem__(item)
    cache = cls.__dict__.get("__serp_param_cache__")
    if cache is None:
        cache = {}
        setattr(cls, "__serp_param_cache__", cache)
    if args in cache:
        return cache[args]
    sub = dict(zip(params, args))
    hints = typing.get_type_hints(cls, include_extras=True)
    ann = {f.name: _subst_ann(hints.get(f.name, f.type), sub)
           for f in _dataclasses.fields(cls)}
    made = type(cls.__name__, (cls,), {"__annotations__": ann, "__serp_type_args__": args})
    made.__parameters__ = ()
    cache[args] = made
    return made


def _bypass_setattr_in_init(cls) -> None:
    """Mirror the compiler: construction (and __post_init__) writes fields directly."""
    real_init, user_setattr = cls.__init__, cls.__setattr__

    def __init__(self, *args, **kwargs):
        self.__dict__["_serp_initing"] = True
        try:
            real_init(self, *args, **kwargs)
        finally:
            self.__dict__.pop("_serp_initing", None)

    def __setattr__(self, name, value):
        if self.__dict__.get("_serp_initing"):
            object.__setattr__(self, name, value)
        else:
            user_setattr(self, name, value)

    cls.__init__ = __init__
    cls.__setattr__ = __setattr__


def _auto_dataclass(cls, **kwargs) -> None:
    """Mirror the compiler's rule that a class inheriting a dataclass base is one too."""
    for base in cls.__mro__[1:]:
        if base is object:
            break
        hook = base.__dict__.get("__init_subclass__")
        if hook is None or getattr(hook, "__func__", None) is _auto_dataclass:
            continue
        hook.__get__(None, cls)(**kwargs)
        break
    frozen = any(getattr(base, "__dataclass_params__", None) is not None
                 and base.__dataclass_params__.frozen for base in cls.__mro__[1:])
    dataclass(cls, frozen=True) if frozen else dataclass(cls)


Owned = Annotated[T, "serpentine:owned"]
Ref = Annotated[T, "serpentine:ref"]
Mut = Annotated[T, "serpentine:mut"]
Shared = Annotated[T, "serpentine:shared"]
Weak = Annotated[T, "serpentine:weak"]


def move(x: T) -> T:
    """Mark an ownership transfer; at runtime, return the value unchanged."""
    return x


def native(f: Callable[..., T]) -> Callable[..., T]:
    """Mark a function for native compilation; at runtime, an identity decorator."""
    return f


_SCALARS = {int: "int", str: "str", float: "float", bool: "bool"}


def _strip_owned(ann):
    """Unwrap `Owned[T]`/`Ref[T]`/`Mut[T]` (Annotated aliases) down to T."""
    import typing
    while typing.get_origin(ann) is Annotated:
        ann = typing.get_args(ann)[0]
    return ann


def _optional_scalar(ann):
    """The scalar kind name of `T | None` / `Optional[T]` for scalar T, else None."""
    import types
    import typing
    if typing.get_origin(ann) in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(members) == 1 and members[0] in _SCALARS:
            return _SCALARS[members[0]]
    return None


def _dump_result(r):
    """`model_dump()` for models, `fields_of` for plain dataclasses, identity otherwise."""
    if hasattr(r, "model_dump"):
        return r.model_dump()
    if _dataclasses.is_dataclass(r):
        return fields_of(r)
    if isinstance(r, list):
        return [_dump_result(x) for x in r]
    return r


def _param_plan(fn, path_names):
    """The D41 extraction plan for fn's parameters (recursing into `Depends(g)`)."""
    import inspect
    import typing
    hints = typing.get_type_hints(fn, include_extras=True)
    plan = []
    for p in inspect.signature(fn).parameters.values():
        ann = _strip_owned(hints.get(p.name))
        opt = _optional_scalar(ann)
        dep = getattr(p.default, "dependency", None)
        if dep is not None and callable(dep):
            plan.append(("dep", p.name, dep, _param_plan(dep, path_names)))
        elif ann in _SCALARS:
            kind = _SCALARS[ann]
            if p.name in path_names:
                plan.append(("path", p.name, kind, None))
            else:
                has = p.default is not inspect.Parameter.empty
                plan.append(("query", p.name, kind, (p.default if has else None, has)))
        elif opt is not None:
            plan.append(("opt", p.name, opt, None))
        elif getattr(ann, "__name__", "") == "BackgroundTasks":
            plan.append(("bg", p.name, ann, None))
        elif hasattr(ann, "model_validate_json_errors"):
            plan.append(("body", p.name, ann, None))
        else:
            raise TypeError(f"route handler parameter '{p.name}' is not injectable")
    return plan


def _run_plan(plan, req):
    """Execute an extraction plan; returns (kwargs, None) or (None, error response)."""
    kwargs = {}
    for how, name, kind, extra in plan:
        if how == "path":
            kwargs[name] = getattr(req, f"_serp_path_{kind}")(name)
        elif how == "query":
            kwargs[name] = getattr(req, f"_serp_query_{kind}")(name, extra[0], extra[1])
        elif how == "opt":
            kwargs[name] = getattr(req, f"_serp_query_opt_{kind}")(name)
        elif how == "bg":
            kwargs[name] = kind()
        elif how == "dep":
            sub, err = _run_plan(extra, req)
            if err is not None:
                return None, err
            kwargs[name] = kind(**sub)
        else:
            errs = kind.model_validate_json_errors(req._serp_body())
            if len(errs) > 0:
                return None, req._serp_validation_error(errs)
            kwargs[name] = kind.model_validate_json(req._serp_body())
    return kwargs, None


def _make_endpoint(fn, path: str, rq, rs):
    """Build the `(request) -> response` endpoint the compiler synthesizes for a handler.

    Mirrors the D41 conventions exactly: `{name}` path segments come from
    `req._serp_path_<kind>`, scalar parameters from `req._serp_query_<kind>` (or the
    `_opt_` variant for `T | None`), classes with `model_validate_json` from the JSON body,
    `Depends(g)` from g's own injected call, and any non-response return value goes through
    `req._serp_respond_json`.
    """
    import inspect
    import typing
    hints = typing.get_type_hints(fn, include_extras=True)
    params = list(inspect.signature(fn).parameters.values())
    ret = _strip_owned(hints.get("return"))
    if len(params) == 1 and _strip_owned(hints.get(params[0].name)) is rq and ret is rs:
        return fn
    path_names = [s[1:-1] for s in path.split("/") if s.startswith("{") and s.endswith("}")]
    plan = _param_plan(fn, path_names)

    if inspect.iscoroutinefunction(fn):
        async def aendpoint(req):
            """The synthesized request → response adapter (coroutine handler)."""
            kwargs, err = _run_plan(plan, req)
            if err is not None:
                return err
            r = await fn(**kwargs)
            if not (ret is rs and ret is not None):
                r = req._serp_respond_json(_dump_result(r))
            return _attach_background(r, kwargs)

        aendpoint.__name__ = f"_serp_ep_{fn.__name__}"
        return aendpoint

    def endpoint(req):
        """The synthesized request → response adapter."""
        kwargs, err = _run_plan(plan, req)
        if err is not None:
            return err
        r = fn(**kwargs)
        if not (ret is rs and ret is not None):
            r = req._serp_respond_json(_dump_result(r))
        return _attach_background(r, kwargs)

    endpoint.__name__ = f"_serp_ep_{fn.__name__}"
    return endpoint


def _attach_background(resp, kwargs):
    """Move an injected BackgroundTasks' tasks onto the response (run after it is sent)."""
    for v in kwargs.values():
        if type(v).__name__ == "BackgroundTasks":
            resp.background = list(v.tasks)
    return resp


def block_on(value):
    """Run a coroutine to completion when no event loop is running (identity otherwise).

    Natively `async def` handlers are plain functions, so the compiler erases this
    call; under CPython it lets synchronous dispatch (TestClient, blocking servers)
    call `async def` route handlers (D45).
    """
    import asyncio
    import inspect
    if not inspect.iscoroutine(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError("block_on() cannot run a coroutine inside a running event loop — "
                       "use the async dispatch path (serve_conn)")


def registrar(method):
    """Turn `obj.m(args...)` into a decorator: `@obj.m(args...)` on `f` calls
    `m(obj, args..., endpoint, **kw)` with the D41-synthesized endpoint and returns f."""
    import collections.abc
    import functools
    import inspect
    import typing

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if any(callable(a) and not isinstance(a, type) for a in args):
            return method(self, *args, **kwargs)
        hints = typing.get_type_hints(method)
        rq = rs = None
        direct = False
        for h in hints.values():
            if typing.get_origin(h) is collections.abc.Callable:
                cargs = typing.get_args(h)
                if len(cargs) == 2 and isinstance(cargs[0], list) and len(cargs[0]) == 1:
                    rq, rs = _strip_owned(cargs[0][0]), cargs[1]
                if len(cargs) == 2 and isinstance(cargs[0], list) and len(cargs[0]) == 2:
                    direct = True
        path = args[0] if args and isinstance(args[0], str) else ""
        takes_async = "is_async" in inspect.signature(method).parameters

        def deco(fn):
            if direct:
                method(self, *args, fn, **kwargs)
                return fn
            extra = dict(kwargs)
            if takes_async and inspect.iscoroutinefunction(fn):
                extra["is_async"] = True
            method(self, *args, _make_endpoint(fn, path, rq, rs), **extra)
            return fn
        return deco
    return wrapper


def share(x: T) -> T:
    """Wrap a value in a refcounted Shared handle; at runtime, identity."""
    return x


def downgrade(x: T) -> T:
    """Create a Weak handle from a Shared one; at runtime, identity."""
    return x


def upgrade(x: T) -> T:
    """Recover a Shared handle from a Weak one (None if dropped); at runtime, identity.

    Under CPython the referent is always alive (the handle keeps it alive), so this
    never returns None — observing the difference means relying on destruction
    timing, which is documented divergence D2.
    """
    return x


PyVal = object
"""Boxed dynamic value annotation; under CPython, values are the real objects."""


def pyval_kind(x) -> str:
    """Kind tag of a dynamic value: the Python type name ('int', 'str', 'list', ...)."""
    return type(x).__name__


def pyval_json(x, ensure_ascii: bool, compact: bool) -> str:
    """Serialize a dynamic value to JSON text; the native build uses a runtime primitive."""
    import json as _json
    return _json.dumps(x, ensure_ascii=ensure_ascii,
                       separators=((",", ":") if compact else (", ", ": ")))


class JoinHandle(Generic[T]):
    """Handle to a spawned thread; join() returns its result (or re-raises), once."""

    def __init__(self, thread, box):
        self._thread = thread
        self._box = box

    def join(self) -> T:
        """Wait for the thread; return its result or re-raise its exception."""
        if self._thread is None:
            raise ValueError("thread already joined")
        self._thread.join()
        self._thread = None
        exc, val = self._box
        if exc is not None:
            raise exc
        return val


def spawn(f, *args):
    """Run f(*args) on a new thread; returns a JoinHandle for its result."""
    import threading

    box = [None, None]

    def run():
        try:
            box[1] = f(*args)
        except BaseException as e:
            box[0] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return JoinHandle(t, box)


import threading as _threading

Thread = _threading.Thread
Timer = _threading.Timer


def _dump_value(v):
    """Recursive half of fields_of: models become dicts, tuples become lists."""
    import enum as _enum
    if isinstance(v, _enum.Enum):
        return v.value
    if _dataclasses.is_dataclass(v) and not isinstance(v, type):
        return fields_of(v)
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_dump_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _dump_value(x) for k, x in v.items()}
    return v


def fields_of(obj) -> dict:
    """The field table of a dataclass instance as plain values (nested models inlined)."""
    return {f.name: _dump_value(getattr(obj, f.name))
            for f in _dataclasses.fields(obj)}


_SCALARS = {int: "int", float: "float", bool: "bool", str: "str", bytes: "bytes",
            type(None): "NoneType"}


def _ann_str(ann) -> str:
    """The compiler's canonical spelling of an annotation (orders union members)."""
    import typing
    if ann is type(None):
        return "None"
    if isinstance(ann, type) and ann in _SCALARS:
        return _SCALARS[ann]
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    if origin in (list, typing.List):
        return f"list[{_ann_str(args[0])}]"
    if origin in (set, frozenset, typing.Set, typing.FrozenSet):
        return f"set[{_ann_str(args[0])}]"
    if origin in (dict, typing.Dict):
        return f"dict[{_ann_str(args[0])}, {_ann_str(args[1])}]"
    if origin in (tuple, typing.Tuple):
        return "tuple[" + ", ".join(_ann_str(a) for a in args) + "]"
    if origin is not None and args:
        return f"{getattr(origin, '__name__', origin)}[" \
               + ", ".join(_ann_str(a) for a in args) + "]"
    return getattr(ann, "__name__", str(ann))


def _union_members(args) -> list:
    """Flatten, dedupe and canonically order the members of a union annotation."""
    import typing
    import types as _types
    flat: list = []
    for a in args:
        parts = typing.get_args(a) \
            if typing.get_origin(a) is typing.Union \
            or isinstance(a, getattr(_types, "UnionType", ())) else (a,)
        for p in parts:
            if p not in flat:
                flat.append(p)
    flat.sort(key=_ann_str)
    return flat


def _type_schema(ann, seen=()) -> dict:
    """Describe one annotation the way the compiler's build-time field table does."""
    import typing
    if type(ann) is str:
        raise TypeError("fields_json needs resolved annotations")
    if getattr(ann, "__metadata__", None) is not None:
        return _type_schema(ann.__origin__, seen)
    if ann is object:
        return {"k": "PyVal"}
    if ann in _SCALARS:
        return {"k": "none" if ann is type(None) else _SCALARS[ann]}
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    import types as _types
    if origin is typing.Union or isinstance(ann, getattr(_types, "UnionType", ())):
        members = _union_members(args)
        rest = [a for a in members if a is not type(None)]
        if len(members) == 2 and len(rest) == 1:
            return {"k": "optional", "inner": _type_schema(rest[0], seen)}
        return {"k": "union", "members": [_type_schema(m, seen) for m in members]}
    if origin in (list, typing.List):
        return {"k": "list", "elem": _type_schema(args[0], seen)}
    if origin in (set, frozenset, typing.Set, typing.FrozenSet):
        return {"k": "set", "elem": _type_schema(args[0], seen)}
    if origin in (dict, typing.Dict):
        return {"k": "dict", "key": {"k": "str"}, "value": _type_schema(args[1], seen)}
    if origin in (tuple, typing.Tuple):
        return {"k": "tuple", "items": [_type_schema(a, seen) for a in args]}
    if _dataclasses.is_dataclass(ann):
        return _class_schema(ann, seen)
    import enum as _enum
    if isinstance(ann, type) and issubclass(ann, _enum.Enum):
        members = list(ann.__members__.items())
        return {"k": "enum", "class": ann.__name__,
                "base": "int" if isinstance(members[0][1].value, int) else "str",
                "members": [n for n, _m in members],
                "values": [m.value for _n, m in members]}
    return {"k": "PyVal"}


def _generic_parts(cls):
    """Split a possibly parameterized class into its origin class and typevar bindings."""
    import typing
    origin = typing.get_origin(cls)
    if origin is not None and _dataclasses.is_dataclass(origin):
        return origin, dict(zip(getattr(origin, "__parameters__", ()), typing.get_args(cls)))
    return cls, {}


def _subst_ann(ann, sub):
    """Replace the typevars in an annotation with a generic class's type arguments."""
    import typing
    if not sub:
        return ann
    if isinstance(ann, typing.TypeVar):
        return sub.get(ann, ann)
    params = getattr(ann, "__parameters__", ())
    if params:
        return ann[tuple(sub.get(p, p) for p in params)]
    return ann


def _class_schema(cls, seen=()) -> dict:
    """The build-time field table of a dataclass, mirroring the compiler's shape."""
    import typing
    cls, sub = _generic_parts(cls)
    if cls in seen:
        return {"k": "model", "class": cls.__name__, "cycle": True, "fields": []}
    seen = seen + (cls,)
    hints = typing.get_type_hints(cls, include_extras=True)
    meta = getattr(cls, "__serp_field_meta__", {})
    out = []
    for f in _dataclasses.fields(cls):
        ann = _subst_ann(hints.get(f.name, f.type), sub)
        entry = {"name": f.name, "type": _type_schema(ann, seen)}
        has_default = f.default is not _dataclasses.MISSING \
            or f.default_factory is not _dataclasses.MISSING
        entry["has_default"] = has_default
        if has_default:
            dv = f.default if f.default is not _dataclasses.MISSING else f.default_factory()
            if isinstance(dv, bytes):
                del entry["has_default"]
                entry["has_default"] = True
                entry["default_hex"] = dv.hex()
            elif isinstance(dv, float) and (dv != dv or dv in (float("inf"), float("-inf"))):
                entry["default_special"] = "nan" if dv != dv else \
                    ("inf" if dv > 0 else "-inf")
            else:
                entry["default"] = dv
        fmeta = dict(meta.get(f.name, {}))
        marks: list = []
        for extra in getattr(ann, "__metadata__", ()):
            em = getattr(extra, "__serp_field_meta__", None)
            if em is not None:
                fmeta = {**dict(em), **fmeta}
            elif not isinstance(extra, (str, int, float, bool, bytes)) and extra is not None:
                marks.append(_annotated_entry(extra))
        fmeta = {k: v for k, v in fmeta.items()
                 if k not in ("default", "default_factory")}
        fmeta = {k: _meta_value(v) for k, v in fmeta.items()}
        if marks:
            fmeta["annotated"] = marks + list(fmeta.get("annotated", []))
        if fmeta:
            entry["meta"] = fmeta
        out.append(entry)
    return {"k": "model", "class": cls.__name__, "fields": out,
            "config": _class_config(cls)}


def _class_config(cls) -> dict:
    """Build-time class metadata: plain dict class attributes (e.g. `model_config`)."""
    names = {f.name for f in _dataclasses.fields(cls)}
    cfg: dict = {}
    for klass in reversed(cls.__mro__):
        for name, value in vars(klass).items():
            if name.startswith("_") or name in names or not isinstance(value, dict):
                continue
            cfg[name] = {str(k): _meta_value(v) for k, v in value.items()}
    return cfg


def fields_json(cls) -> str:
    """The build-time field table of a model class as a JSON string."""
    import json
    if not isinstance(cls, type) and _generic_parts(cls)[0] is cls:
        cls = type(cls)
    return json.dumps(_class_schema(cls), separators=(",", ":"))


def _spec_kind(spec) -> str:
    """The runtime type name a field-table spec node accepts."""
    k = spec["k"]
    if k in ("none", "NoneType"):
        return "NoneType"
    if k in ("model", "dict"):
        return "dict"
    if k in ("tuple", "set"):
        return "list"
    if k == "enum":
        return spec["base"]
    return k


def _build_value(spec, v, loc: str):
    """Recursive half of fields_build: strict extraction of one field value."""
    k = spec["k"]
    got = type(v).__name__
    if k == "PyVal":
        return v
    if k == "optional":
        return None if v is None else _build_value(spec["inner"], v, loc)
    if k == "float":
        if got not in ("float", "int"):
            raise TypeError(f"field {loc!r} expects float, got {got}")
        return float(v)
    if k in ("int", "bool", "str", "bytes"):
        if got != k:
            raise TypeError(f"field {loc!r} expects {k}, got {got}")
        return v
    if k in ("NoneType", "none"):
        if v is not None:
            raise TypeError(f"field {loc!r} expects NoneType, got {got}")
        return None
    if k == "union":
        members = spec["members"]
        picked = _disc_member(members, v)
        if picked is not None:
            return _build_value(picked, v, loc)
        has_int = any(m["k"] == "int" for m in members)
        for m in members:
            want = _spec_kind(m)
            if got == want or (m["k"] == "float" and not has_int and got == "int"):
                return _build_value(m, v, loc)
        names = " | ".join(_spec_kind(m) for m in members)
        raise TypeError(f"field {loc!r} expects {names}, got {got}")
    if k == "list":
        if got != "list":
            raise TypeError(f"field {loc!r} expects list, got {got}")
        return [_build_value(spec["elem"], x, loc) for x in v]
    if k == "set":
        if got not in ("list", "set"):
            raise TypeError(f"field {loc!r} expects list, got {got}")
        return {_build_value(spec["elem"], x, loc) for x in v}
    if k == "dict":
        if got != "dict":
            raise TypeError(f"field {loc!r} expects dict, got {got}")
        return {str(x): _build_value(spec["value"], y, loc) for x, y in v.items()}
    if k == "tuple":
        if got != "list":
            raise TypeError(f"field {loc!r} expects list, got {got}")
        if len(v) != len(spec["items"]):
            raise TypeError(f"field {loc!r} expects {len(spec['items'])} items")
        return tuple(_build_value(s, x, loc) for s, x in zip(spec["items"], v))
    if k == "enum":
        want = spec["base"]
        if got != want:
            raise TypeError(f"field {loc!r} expects {want}, got {got}")
        return _MODEL_REGISTRY[spec["class"]](v)
    if k == "model":
        if got != "dict":
            raise TypeError(f"field {loc!r} expects dict, got {got}")
        return _build_model(spec, v)
    return v


def _default_tag(spec, name):
    """The constant str/int default of field `name` in a model spec, else None."""
    for f in spec.get("fields", ()):
        if f["name"] == name and f.get("has_default") and "default" in f:
            d = f["default"]
            if isinstance(d, str) or (isinstance(d, int) and not isinstance(d, bool)):
                return str(d)
    return None


def _disc_member(members, v):
    """The all-model union member whose discriminator default matches v's tag, else None."""
    if not isinstance(v, dict) or len(members) < 2:
        return None
    if any(m.get("k") != "model" for m in members):
        return None
    for f in members[0].get("fields", ()):
        name = f["name"]
        tags = [_default_tag(m, name) for m in members]
        if any(t is None for t in tags) or len(set(tags)) != len(tags):
            continue
        if name not in v:
            return None
        want = str(v[name])
        for m, t in zip(members, tags):
            if t == want:
                return m
        return None
    return None


def _build_model(spec, data):
    """Construct a model from a validated dict, driven by a field-table spec."""
    import json
    cls = _MODEL_REGISTRY[spec["class"]]
    if spec.get("cycle"):
        spec = json.loads(fields_json(cls))
    kwargs = {}
    for f in spec["fields"]:
        name = f["name"]
        if name in data:
            kwargs[name] = _build_value(f["type"], data[name], name)
        elif not f["has_default"]:
            raise TypeError(f"{spec['class']}: missing field {name!r}")
    return cls(**kwargs)


_MODEL_REGISTRY: dict = {}


def fields_set(obj, name: str, value) -> None:
    """Write one field of a model instance by name, mirroring the compiler's strict coercion."""
    import json
    cls = type(obj)
    spec = json.loads(fields_json(cls))
    _register_models(cls)
    for f in spec["fields"]:
        if f["name"] == name:
            object.__setattr__(obj, name, _build_value(f["type"], value, name))
            return
    raise ValueError(f"{cls.__name__} has no field " + name)


def fields_build(cls, data):
    """Construct an instance of a model class from a plain dict of values."""
    import json
    origin = _generic_parts(cls)[0]
    if not isinstance(cls, type) and origin is cls:
        cls = origin = type(cls)
    if type(data).__name__ != "dict":
        raise TypeError(f"{origin.__name__}: expected a dict, got {type(data).__name__}")
    spec = json.loads(fields_json(cls))
    _register_models(origin)
    return _build_model(spec, data)


def _register_models(cls) -> None:
    """Make a model class (and its nested models) findable by name during a build."""
    import enum as _enum
    import typing
    if _MODEL_REGISTRY.get(cls.__name__) is cls:
        return
    _MODEL_REGISTRY[cls.__name__] = cls
    for ann in typing.get_type_hints(cls, include_extras=True).values():
        for part in (ann,) + typing.get_args(ann):
            base = getattr(part, "__origin__", part)
            if isinstance(base, type) and (_dataclasses.is_dataclass(base)
                                           or issubclass(base, _enum.Enum)):
                _register_models(base)
            for sub in typing.get_args(part):
                if isinstance(sub, type) and _dataclasses.is_dataclass(sub):
                    _register_models(sub)


def ConfigDict(**kwargs) -> dict:
    """Build-time model configuration, read out of a class body."""
    return dict(kwargs)


class AfterValidator:
    """`Annotated[T, AfterValidator(f)]` — run f on the value after type validation."""

    def __init__(self, func):
        self.func = func


class BeforeValidator:
    """`Annotated[T, BeforeValidator(f)]` — run f on the raw input before validation."""

    def __init__(self, func):
        self.func = func


class Json:
    """`Annotated[T, Json()]` — a marker: parse the field's JSON text before validating T."""


class SkipValidation:
    """`Annotated[T, SkipValidation()]` — a marker: pass the field's value through unchecked."""


class Base64:
    """`Annotated[bytes, Base64()]` — a marker: the field travels as base64 text."""


def conint(**kwargs):
    """pydantic's `conint(...)`: sugar for `Annotated[int, Field(...)]`."""
    return Annotated[int, Field(**kwargs)]


def confloat(**kwargs):
    """pydantic's `confloat(...)`: sugar for `Annotated[float, Field(...)]`."""
    return Annotated[float, Field(**kwargs)]


def constr(**kwargs):
    """pydantic's `constr(...)`: sugar for `Annotated[str, Field(...)]`."""
    return Annotated[str, Field(**kwargs)]


def conbytes(**kwargs):
    """pydantic's `conbytes(...)`: sugar for `Annotated[bytes, Field(...)]`."""
    return Annotated[bytes, Field(**kwargs)]


def conlist(item, **kwargs):
    """pydantic's `conlist(T, ...)`: sugar for `Annotated[list[T], Field(...)]`."""
    return Annotated[list[item], Field(**kwargs)]


def _mark_hook(fn, hook: dict):
    """Tag a (possibly wrapped) function as a build-time hook and return it unchanged."""
    target = fn
    if isinstance(fn, (classmethod, staticmethod)):
        target = fn.__func__
    elif isinstance(fn, property):
        target = fn.fget
    hook = dict(hook)
    hook["method"] = target.__name__
    classy = hook["kind"] == "field" or (hook["kind"] == "model" and hook["mode"] == "before")
    hook["args"] = max(target.__code__.co_argcount - 1, 1) if classy else 1
    target.__serp_hook__ = hook
    return fn


def _hook_ret(fn) -> dict:
    """The schema of a computed field's return annotation, resolved late like field types."""
    import typing
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}
    return _type_schema(hints.get("return", object))


def field_validator(*fields: str, mode: str = "after"):
    """Register a classmethod as a per-field validator (mode 'before' or 'after')."""
    def deco(fn):
        return _mark_hook(fn, {"kind": "field", "mode": mode, "fields": list(fields)})
    return deco


def model_validator(mode: str = "after"):
    """Register a whole-model validator ('before' on the input, 'after' on the instance)."""
    def deco(fn):
        return _mark_hook(fn, {"kind": "model", "mode": mode, "fields": []})
    return deco


def field_serializer(*fields: str, mode: str = "plain"):
    """Register an instance method as the serializer of one or more fields."""
    def deco(fn):
        return _mark_hook(fn, {"kind": "serializer", "mode": mode, "fields": list(fields)})
    return deco


def model_serializer(mode="plain"):
    """Register an instance method producing the whole serialized model."""
    if callable(mode):
        return _mark_hook(mode, {"kind": "modelser", "mode": "plain", "fields": []})

    def deco(fn):
        return _mark_hook(fn, {"kind": "modelser", "mode": mode, "fields": []})
    return deco


def computed_field(fn):
    """Register a property (or no-argument method) as an extra dumped field."""
    return _mark_hook(fn, {"kind": "computed", "mode": "plain", "fields": []})


def _class_hooks(cls) -> list:
    """A model class's hooks: base-first, redefined ones moved to the end."""
    order: list = []
    seen: dict = {}
    funcs: dict = {}
    for klass in reversed(cls.__mro__):
        for name, value in vars(klass).items():
            fn = value
            if isinstance(value, (classmethod, staticmethod)):
                fn = value.__func__
            elif isinstance(value, property):
                fn = value.fget
            hook = getattr(fn, "__serp_hook__", None)
            if hook is None:
                continue
            if name in order:
                order.remove(name)
            order.append(name)
            seen[name] = hook
            funcs[name] = fn
    out: list = []
    for n in order:
        h = seen[n]
        rec = {"kind": h["kind"], "mode": h["mode"], "args": h["args"],
               "fields": list(h["fields"]), "method": h["method"]}
        if h["kind"] == "computed":
            rec["ret"] = _hook_ret(funcs[n])
        out.append(rec)
    return out


def _meta_funcs(cls) -> list:
    """Function names referenced from a class's build-time metadata, in compiler order."""
    import json
    out: list = []

    def walk(v) -> None:
        if isinstance(v, dict):
            if list(v) == ["__fn__"]:
                if v["__fn__"] not in out:
                    out.append(v["__fn__"])
                return
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    schema = json.loads(fields_json(cls))
    for f in schema["fields"]:
        walk(f.get("meta", {}))
    walk(schema.get("config", {}))
    return [n for n in out if _module_func(cls, n) is not None]


def _module_func(cls, name: str):
    """A module-level function of the class's defining module, or None."""
    import sys
    mod = sys.modules.get(getattr(cls, "__module__", ""))
    fn = getattr(mod, name, None)
    return fn if callable(fn) and not isinstance(fn, type) else None


def hooks_json(cls) -> str:
    """The build-time validator-hook table of a model class as a JSON string."""
    import json
    if not isinstance(cls, type):
        cls = type(cls)
    return json.dumps({"class": cls.__name__, "hooks": _class_hooks(cls),
                       "funcs": _meta_funcs(cls)}, separators=(",", ":"))


def run_hook(cls, name: str, v):
    """Call one validator hook or metadata function by name; unknown names pass through."""
    if not isinstance(cls, type):
        cls = type(cls)
    fn = getattr(cls, name, None)
    if fn is None:
        fn = _module_func(cls, name)
    return v if fn is None else fn(v)


def run_hook_self(obj, name: str) -> None:
    """Call one instance validator hook by name."""
    fn = getattr(obj, name, None)
    if fn is not None:
        fn()


def run_hook_get(obj, name: str):
    """Read one no-argument instance hook (computed field or model serializer)."""
    got = getattr(obj, name, None)
    if got is None:
        return None
    return got() if callable(got) else got


def run_hook_val(obj, name: str, v):
    """Call one instance hook that transforms a value (a field serializer)."""
    fn = getattr(obj, name, None)
    return v if fn is None else fn(v)


def run_hook_info(cls, name: str, v, info):
    """Call one two-argument validator hook by name (value plus ValidationInfo)."""
    if not isinstance(cls, type):
        cls = type(cls)
    fn = getattr(cls, name, None)
    return v if fn is None else fn(v, info)
