"""Build-time synthesis of the field-table helpers behind the LB1 intrinsics.

`fields_of` / `fields_json` / `fields_build` are lowered to ordinary Serpentine
functions generated from a class's build-time field table, so both backends
compile them like any other user code.
"""

import ast
import json

from .ptypes import (TBool, TBytes, TClass, TDict, TEnum, TFloat, TInt, TList, TNone,
                     TOptional, TPyVal, TSet, TStr, TTuple, TUnion, Type)

KIND_TAG = {TInt: "int", TFloat: "float", TBool: "bool", TStr: "str",
            TBytes: "bytes", TNone: "NoneType"}

PV_KIND = {TBool: "bool", TInt: "int", TFloat: "float", TStr: "str", TBytes: "bytes",
           TNone: "NoneType", TList: "list", TTuple: "list", TSet: "list",
           TDict: "dict", TClass: "dict"}


def _pv_kind(t: Type) -> str | None:
    """The PyVal kind a union member arrives as, or None if it cannot be carried."""
    for cls, kind in PV_KIND.items():
        if isinstance(t, cls):
            return kind
    return None


class FieldHelperGen:
    """Renders Serpentine source for one field-table helper function."""

    def __init__(self, tc) -> None:
        self.tc = tc
        self.n = 0

    def _tmp(self, prefix: str) -> str:
        """A fresh local name, unique across every generated helper."""
        self.n += 1
        return f"_{prefix}{self.n}"

    def ann(self, t: Type, mod) -> str:
        """Render a type as an annotation that resolves inside `mod`."""
        if isinstance(t, TOptional):
            return f"{self.ann(t.inner, mod)} | None"
        if isinstance(t, TUnion):
            return " | ".join(self.ann(m, mod) for m in t.members)
        if isinstance(t, TList):
            return f"list[{self.ann(t.elem, mod)}]"
        if isinstance(t, TSet):
            return f"set[{self.ann(t.elem, mod)}]"
        if isinstance(t, TEnum):
            for alias, known in self.tc._type_names(mod).items():
                if isinstance(known, TEnum) and (known.module, known.name) == (t.module, t.name):
                    return alias
            return t.name
        if isinstance(t, TDict):
            return f"dict[{self.ann(t.key, mod)}, {self.ann(t.value, mod)}]"
        if isinstance(t, TTuple):
            return f"tuple[{', '.join(self.ann(i, mod) for i in t.items)}]"
        if isinstance(t, TClass):
            args = f"[{', '.join(self.ann(a, mod) for a in t.args)}]" if t.args else ""
            for alias, known in self.tc._type_names(mod).items():
                if isinstance(known, TClass) and (known.module, known.name) == (t.module, t.name):
                    return alias + args
            return t.name + args
        return str(t)

    def _member_kind(self, t: Type) -> str | None:
        """The PyVal kind a union member arrives as, resolving enums to their value kind."""
        if isinstance(t, TEnum):
            info = self.tc.enums[(t.module, t.name)]
            return "int" if isinstance(info.value_type, TInt) else "str"
        return _pv_kind(t)

    def _disc_of(self, t: TUnion):
        """The discriminator of an all-model union, as resolved by the type checker."""
        return self.tc.union_discriminator(t)

    def _isinst(self, t: Type, mod) -> str:
        """The isinstance() class argument that selects union member t."""
        simple = {TBool: "bool", TInt: "int", TFloat: "float", TStr: "str", TBytes: "bytes",
                  TList: "list", TDict: "dict", TSet: "set", TTuple: "tuple"}
        for cls, nm in simple.items():
            if isinstance(t, cls):
                return nm
        if isinstance(t, TClass):
            return self.ann(TClass(t.module, t.name), mod)
        return self.ann(t, mod)

    def _lit(self, v) -> str:
        """Render a folded default value as Serpentine source."""
        if isinstance(v, (list, dict)):
            return "[]" if isinstance(v, list) else "{}"
        return repr(v)

    def source(self, kind: str, t: TClass, fname: str, schema: dict) -> str:
        """The full source of one helper function."""
        if kind == "json":
            return (f"def {fname}() -> str:\n"
                    f"    return {json.dumps(_dumps(schema))}\n")
        if kind == "hooks":
            return (f"def {fname}() -> str:\n"
                    f"    return {json.dumps(_dumps(schema))}\n")
        if kind in ("hook", "hookself", "hookget", "hookval", "hookinfo"):
            return self._hook_source(kind, t, fname, schema)
        if kind == "set":
            return self._set_source(t, fname)
        mod = self.tc.program.modules[t.module]
        info = self.tc.classes[(t.module, t.name)]
        ftypes = self.tc._inst_fields(t)
        cls = self.ann(t, mod)
        ctor = self.ann(TClass(t.module, t.name), mod)
        out: list[str] = []
        if kind == "dump":
            head = f"def {fname}(v: Ref[{cls}]) -> dict[str, PyVal]:\n"
            out.append('    _out: dict[str, PyVal] = {}')
            for f in info.field_order:
                ft = ftypes[f]
                expr = self._dump(f"v.{f}", ft, mod, out, "    ")
                out.append(f'    _out[{f!r}] = {expr}')
            out.append("    return _out")
            return head + "\n".join(out) + "\n"
        head = f"def {fname}(pv: PyVal) -> {cls}:\n"
        out.append('    if pyval_kind(pv) != "dict":')
        out.append(f'        raise TypeError("{t.name}: expected a dict, got " + pyval_kind(pv))')
        args: list[str] = []
        for f in info.field_order:
            ft = ftypes[f]
            if f in info.field_defaults:
                local = f"_a_{f}"
                dv = info.field_defaults[f]
                dl = "[]" if isinstance(dv, ast.List) else \
                    ("{}" if isinstance(dv, ast.Dict) else self._lit(dv.value))
                out.append(f"    {local}: {self.ann(ft, mod)} = {dl}")
                out.append(f"    if {f!r} in pv:")
                expr = self._build(f'pv[{f!r}]', ft, mod, out, "        ", f)
                out.append(f"        {local} = {_mv(expr, ft)}")
                args.append(f"{f}={_mv(local, ft)}")
            else:
                out.append(f"    if not ({f!r} in pv):")
                out.append(f'        raise TypeError("{t.name}: missing field {f!r}")')
                expr = self._build(f'pv[{f!r}]', ft, mod, out, "    ", f)
                args.append(f"{f}={_mv(expr, ft)}")
        out.append(f"    return {ctor}({', '.join(args)})")
        return head + "\n".join(out) + "\n"

    # ---------- by-name field write ----------

    def _set_source(self, t: TClass, fname: str) -> str:
        """A writer assigning one field of a class by name from a PyVal."""
        mod = self.tc.program.modules[t.module]
        info = self.tc.classes[(t.module, t.name)]
        ftypes = self.tc._inst_fields(t)
        cls = self.ann(t, mod)
        out: list[str] = []
        head = f"def {fname}(v: Mut[{cls}], name: str, pv: PyVal) -> None:\n"
        for i, f in enumerate(info.field_order):
            ft = ftypes[f]
            out.append(f"    {'if' if i == 0 else 'elif'} name == {f!r}:")
            expr = self._build("pv", ft, mod, out, "        ", f)
            out.append(f"        v.{f} = {_mv(expr, ft)}")
        out.append("    else:" if info.field_order else "    if True:")
        out.append(f'        raise ValueError("{t.name} has no field " + name)')
        return head + "\n".join(out) + "\n"

    # ---------- validator-hook dispatch ----------

    def _hook_source(self, kind: str, t: TClass, fname: str, schema: dict) -> str:
        """A dispatcher calling one of a class's hooks by name."""
        mod = self.tc.program.modules[t.module]
        cls = self.ann(t, mod)
        if kind in ("hook", "hookinfo"):
            want = 2 if kind == "hookinfo" else 1
            names = [h["method"] for h in schema["hooks"]
                     if (h["kind"] == "field" or h["mode"] == "before")
                     and h.get("args", 1) == want]
            sig = "name: str, v: PyVal, info: PyVal" if want == 2 else "name: str, v: PyVal"
            call = "v, info" if want == 2 else "v"
            out = [f"def {fname}({sig}) -> PyVal:"]
            for m in dict.fromkeys(names):
                out.append(f"    if name == {m!r}:")
                out.append(f"        return {cls}.{m}({call})")
            if want == 1:
                for f in dict.fromkeys(schema.get("funcs", [])):
                    out.append(f"    if name == {f!r}:")
                    out.append(f"        return {f}(v)")
            out.append("    return v")
            return "\n".join(out) + "\n"
        if kind == "hookval":
            names = [h["method"] for h in schema["hooks"] if h["kind"] == "serializer"]
            out = [f"def {fname}(v: Ref[{cls}], name: str, x: PyVal) -> PyVal:"]
            for m in dict.fromkeys(names):
                out.append(f"    if name == {m!r}:")
                out.append(f"        return v.{m}(x)")
            out.append("    return x")
            return "\n".join(out) + "\n"
        if kind == "hookget":
            props = self.tc.classes[(t.module, t.name)].properties
            names = [h["method"] for h in schema["hooks"]
                     if h["kind"] in ("modelser", "computed")]
            out = [f"def {fname}(v: Ref[{cls}], name: str) -> PyVal:"]
            for m in dict.fromkeys(names):
                out.append(f"    if name == {m!r}:")
                out.append(f"        return v.{m}" + ("" if m in props else "()"))
            out.append("    return None")
            return "\n".join(out) + "\n"
        names = [h["method"] for h in schema["hooks"]
                 if h["kind"] == "model" and h["mode"] == "after"]
        out = [f"def {fname}(v: Ref[{cls}], name: str) -> None:"]
        if not names:
            out.append("    pass")
        for m in dict.fromkeys(names):
            out.append(f"    if name == {m!r}:")
            out.append(f"        v.{m}()")
        return "\n".join(out) + "\n"

    # ---------- dump direction ----------

    def _dump(self, src: str, t: Type, mod, out: list[str], ind: str) -> str:
        """Emit lines producing a PyVal-coercible expression for `src` of type t."""
        if isinstance(t, TClass):
            helper = self.tc._need_field_helper(t, "dump", mod)
            return f"{helper}({src})"
        if self.tc._pyval_coercible(t):
            return src
        if isinstance(t, TOptional):
            p = self._tmp("p")
            out.append(f"{ind}{p}: PyVal = None")
            out.append(f"{ind}if {src} is not None:")
            inner = self._dump(src, t.inner, mod, out, ind + "    ")
            out.append(f"{ind}    {p} = {inner}")
            return p
        if isinstance(t, TUnion):
            p = self._tmp("p")
            out.append(f"{ind}{p}: PyVal = None")
            for m in t.members:
                if isinstance(m, TNone):
                    continue
                out.append(f"{ind}if isinstance({src}, {self._isinst(m, mod)}):")
                inner = self._dump(src, m, mod, out, ind + "    ")
                out.append(f"{ind}    {p} = {inner}")
            return p
        if isinstance(t, TEnum):
            return f"{src}.value"
        if isinstance(t, (TList, TSet)):
            lst, e = self._tmp("l"), self._tmp("e")
            out.append(f"{ind}{lst}: list[PyVal] = []")
            out.append(f"{ind}for {e} in {src}:")
            inner = self._dump(e, t.elem, mod, out, ind + "    ")
            out.append(f"{ind}    {lst}.append({inner})")
            return lst
        if isinstance(t, TDict):
            m, k, val = self._tmp("m"), self._tmp("k"), self._tmp("w")
            out.append(f"{ind}{m}: dict[str, PyVal] = {{}}")
            out.append(f"{ind}for {k}, {val} in {src}.items():")
            inner = self._dump(val, t.value, mod, out, ind + "    ")
            out.append(f"{ind}    {m}[{k}] = {inner}")
            return m
        if isinstance(t, TTuple):
            lst = self._tmp("t")
            out.append(f"{ind}{lst}: list[PyVal] = []")
            for i, it in enumerate(t.items):
                inner = self._dump(f"{src}[{i}]", it, mod, out, ind)
                out.append(f"{ind}{lst}.append({inner})")
            return lst
        raise AssertionError(f"undumpable field type {t}")

    # ---------- build direction ----------

    def _guard(self, pv: str, want: str, loc: str, out: list[str], ind: str,
               op: str = "!=") -> None:
        """Emit a strict PyVal kind guard for one field."""
        out.append(f'{ind}if pyval_kind({pv}) {op} "{want}":')
        out.append(f'{ind}    raise TypeError("field {loc!r} expects {want}, got "'
                   f" + pyval_kind({pv}))")

    def _build(self, pv: str, t: Type, mod, out: list[str], ind: str, loc: str) -> str:
        """Emit lines extracting a value of type t out of the PyVal expression `pv`."""
        if isinstance(t, TPyVal):
            return pv
        for cls, tag in KIND_TAG.items():
            if isinstance(t, cls):
                if isinstance(t, TFloat):
                    out.append(f'{ind}if pyval_kind({pv}) != "float" and '
                               f'pyval_kind({pv}) != "int":')
                    out.append(f'{ind}    raise TypeError("field {loc!r} expects float, got "'
                               f" + pyval_kind({pv}))")
                    return f"float({pv})"
                self._guard(pv, tag, loc, out, ind)
                return "None" if isinstance(t, TNone) else f"{tag}({pv})"
        if isinstance(t, TClass):
            self._guard(pv, "dict", loc, out, ind)
            helper = self.tc._need_field_helper(t, "build", mod)
            return f"{helper}({pv})"
        if isinstance(t, TOptional):
            o = self._tmp("o")
            out.append(f"{ind}{o}: {self.ann(t, mod)} = None")
            out.append(f'{ind}if pyval_kind({pv}) != "NoneType":')
            inner = self._build(pv, t.inner, mod, out, ind + "    ", loc)
            out.append(f"{ind}    {o} = {_mv(inner, t.inner)}")
            return o
        if isinstance(t, TUnion):
            u = self._tmp("u")
            ann = self.ann(t, mod)
            disc = self._disc_of(t)
            if disc is not None:
                dname, dvals = disc
                for i, m in enumerate(t.members):
                    assert isinstance(m, TClass)
                    lit = dvals[i]
                    conv = "str" if isinstance(lit, str) else "int"
                    cond = f'{conv}({pv}["{dname}"]) == {lit!r}'
                    out.append(f"{ind}{'if' if i == 0 else 'elif'} {cond}:")
                    helper = self.tc._need_field_helper(m, "build", mod)
                    out.append(f"{ind}    {f'{u}: {ann}' if i == 0 else u} = {helper}({pv})")
                out.append(f"{ind}else:")
                out.append(f'{ind}    raise TypeError("field {loc!r}: no {dname} matches "'
                           f' + str({pv}["{dname}"]))')
                return u
            first = True
            for i, m in enumerate(t.members):
                kind = self._member_kind(m)
                if kind is None:
                    raise AssertionError(f"unbuildable union member {m}")
                cond = f'pyval_kind({pv}) == "{kind}"'
                if isinstance(m, TFloat) and not any(isinstance(x, TInt) for x in t.members):
                    cond = f'({cond} or pyval_kind({pv}) == "int")'
                out.append(f"{ind}{'if' if i == 0 else 'elif'} {cond}:")
                decl = f"{u}: {ann}" if first else u
                first = False
                if isinstance(m, TNone):
                    out.append(f"{ind}    {decl} = None")
                    continue
                inner = self._build(pv, m, mod, out, ind + "    ", loc)
                out.append(f"{ind}    {decl} = {_mv(inner, m)}")
            out.append(f"{ind}else:")
            out.append(f'{ind}    raise TypeError("field {loc!r} expects {t}, got "'
                       f" + pyval_kind({pv}))")
            return u
        if isinstance(t, TEnum):
            info = self.tc.enums[(t.module, t.name)]
            tag = "int" if isinstance(info.value_type, TInt) else "str"
            self._guard(pv, tag, loc, out, ind)
            return f"{self.ann(t, mod)}({tag}({pv}))"
        if isinstance(t, TSet):
            self._guard(pv, "list", loc, out, ind)
            st, e = self._tmp("s"), self._tmp("e")
            out.append(f"{ind}{st}: {self.ann(t, mod)} = set()")
            out.append(f"{ind}for {e} in {pv}:")
            inner = self._build(e, t.elem, mod, out, ind + "    ", loc)
            out.append(f"{ind}    {st}.add({inner})")
            return st
        if isinstance(t, TList):
            self._guard(pv, "list", loc, out, ind)
            lst, e = self._tmp("l"), self._tmp("e")
            out.append(f"{ind}{lst}: {self.ann(t, mod)} = []")
            out.append(f"{ind}for {e} in {pv}:")
            inner = self._build(e, t.elem, mod, out, ind + "    ", loc)
            out.append(f"{ind}    {lst}.append({_mv(inner, t.elem)})")
            return lst
        if isinstance(t, TDict):
            self._guard(pv, "dict", loc, out, ind)
            m, k = self._tmp("m"), self._tmp("k")
            out.append(f"{ind}{m}: {self.ann(t, mod)} = {{}}")
            out.append(f"{ind}for {k} in {pv}:")
            inner = self._build(f"{pv}[{k}]", t.value, mod, out, ind + "    ", loc)
            out.append(f"{ind}    {m}[str({k})] = {_mv(inner, t.value)}")
            return m
        if isinstance(t, TTuple):
            self._guard(pv, "list", loc, out, ind)
            out.append(f"{ind}if len({pv}) != {len(t.items)}:")
            out.append(f'{ind}    raise TypeError("field {loc!r} expects '
                       f'{len(t.items)} items")')
            parts = [_mv(self._build(f"{pv}[{i}]", it, mod, out, ind, loc), it)
                     for i, it in enumerate(t.items)]
            tup = self._tmp("q")
            out.append(f"{ind}{tup}: {self.ann(t, mod)} = ({', '.join(parts)},)"
                       if len(t.items) == 1 else
                       f"{ind}{tup}: {self.ann(t, mod)} = ({', '.join(parts)})")
            return tup
        raise AssertionError(f"unbuildable field type {t}")


def _mv(expr: str, t: Type) -> str:
    """Wrap a non-Copy place in move() so the transfer is explicit."""
    if t.is_copy() or not expr.isidentifier():
        return expr
    return f"move({expr})"


def _dumps(schema: dict) -> str:
    """Serialize a build-time field table deterministically."""
    return json.dumps(schema, separators=(",", ":"))


def json_safe(v):
    """Coerce a folded metadata value into something JSON can carry."""
    from .ptypes import FnRef
    if isinstance(v, FnRef):
        return {"__fn__": v.name}
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return "nan" if v != v else ("inf" if v > 0 else "-inf")
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): json_safe(x) for k, x in v.items()}
    if isinstance(v, (str, int, bool, float)) or v is None:
        return v
    return str(v)
