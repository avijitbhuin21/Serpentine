"""Backend B: typed AST -> LLVM IR via llvmlite — full language (CHECKLIST Phase 5.1).

Mirrors Backend A's semantics exactly (rustgen.py is the reference): same typed
AST input, same CPython-parity runtime behavior, byte-identical stdout. Values
are lowered as:

  int/float/bool          -> i64 / double / i1 (SSA)
  Shared/Weak/file        -> i8* handles (refcount box / SerpFile box)
  str                     -> [3 x i64] opaque SStr blob (runtime-managed, SSO)
  list[T] / dict[K,V]     -> {i8*, i64, i64} raw buffer (dict = list of K,V pairs)
  tuple/class/Optional    -> LLVM structs by value in allocas
  exceptions              -> {SStr, SStr} error values; calls return {i1 err, T}

All type-directed clone/drop/eq/cmp/repr logic is EMITTED per type; the cached
runtime library (prelude.rs + rt.rs) only provides monomorphic primitives.
Drops use per-local drop flags and a single per-function exit/cleanup block, so
scope-exit and unwind-path drops share one mechanism (SIR's drop discipline).
"""

import ast

from llvmlite import ir

from .frontend import Module
from .ptypes import (Type, TBool, TClass, TDict, TExc, TFile, TFloat, TInt, TList, TNone,
                     TOptional, TShared, TStr, TTuple, TWeak, mangle_type, subst_type)
from .typecheck import FuncSig, TIterObj, TypeChecker

I64 = ir.IntType(64)
I32 = ir.IntType(32)
I8 = ir.IntType(8)
I1 = ir.IntType(1)
F64 = ir.DoubleType()
VOID = ir.VoidType()
I8P = I8.as_pointer()

SSTR = ir.ArrayType(I64, 3)                       # opaque SStr blob
SSTRP = SSTR.as_pointer()
SLIST = ir.LiteralStructType([I8P, I64, I64])     # {data, len, cap}
SLISTP = SLIST.as_pointer()
SERR = ir.LiteralStructType([SSTR, SSTR])         # {kind, msg}
SERRP = SERR.as_pointer()

OVERFLOW_MSG = "Serpentine int operation overflowed 64 bits"

SCALARS = (TInt, TFloat, TBool)


class LLVMUnsupported(Exception):
    """The program uses a feature Backend B cannot lower (should not happen for
    checker-accepted programs; kept as a safety valve)."""


def needs_clone(t: Type) -> bool:
    """Copy-semantics types whose copies are not bitwise (mirror rustgen)."""
    if isinstance(t, (TStr, TShared, TWeak, TExc)):
        return True
    if isinstance(t, TTuple):
        return any(needs_clone(i) for i in t.items)
    if isinstance(t, TOptional):
        return needs_clone(t.inner)
    return False


class V:
    """An evaluated expression: SSA scalar or pointer-to-aggregate."""

    __slots__ = ("ty", "ssa", "ptr", "owned")

    def __init__(self, ty: Type, ssa=None, ptr=None, owned=False):
        self.ty = ty
        self.ssa = ssa
        self.ptr = ptr
        self.owned = owned


# Runtime ABI: name -> (return type, [arg types]).
RT_SIGS = {
    "rt_raise": (VOID, [SSTRP, SSTRP]),
    "rt_raise_static": (VOID, [I8P, I64, I8P, I64]),
    "rt_err_take": (VOID, [SERRP]),
    "rt_err_reraise": (VOID, [SERRP]),
    "rt_err_matches": (I8, [SERRP, I8P, I64]),
    "rt_err_msg": (VOID, [SERRP, SSTRP]),
    "rt_err_repr": (VOID, [SERRP, SSTRP]),
    "rt_abort_pending": (VOID, []),
    "rt_str_new": (VOID, [I8P, I64, SSTRP]),
    "rt_str_clone": (VOID, [SSTRP, SSTRP]),
    "rt_str_drop": (VOID, [SSTRP]),
    "rt_str_concat": (VOID, [SSTRP, SSTRP, SSTRP]),
    "rt_str_repeat": (VOID, [SSTRP, I64, SSTRP]),
    "rt_str_eq": (I8, [SSTRP, SSTRP]),
    "rt_str_cmp": (I32, [SSTRP, SSTRP]),
    "rt_str_len": (I64, [SSTRP]),
    "rt_str_is_empty": (I8, [SSTRP]),
    "rt_str_contains": (I8, [SSTRP, SSTRP]),
    "rt_str_startswith": (I8, [SSTRP, SSTRP]),
    "rt_str_endswith": (I8, [SSTRP, SSTRP]),
    "rt_str_find": (I64, [SSTRP, SSTRP]),
    "rt_str_replace": (VOID, [SSTRP, SSTRP, SSTRP, SSTRP]),
    "rt_str_strip": (VOID, [SSTRP, SSTRP]),
    "rt_str_lstrip": (VOID, [SSTRP, SSTRP]),
    "rt_str_rstrip": (VOID, [SSTRP, SSTRP]),
    "rt_str_upper": (VOID, [SSTRP, SSTRP]),
    "rt_str_lower": (VOID, [SSTRP, SSTRP]),
    "rt_str_split": (I8, [SSTRP, SSTRP, SLISTP]),
    "rt_str_split_ws": (VOID, [SSTRP, SLISTP]),
    "rt_str_chars": (VOID, [SSTRP, SLISTP]),
    "rt_str_join": (VOID, [SSTRP, SLISTP, SSTRP]),
    "rt_str_index": (I8, [SSTRP, I64, SSTRP]),
    "rt_str_slice": (VOID, [SSTRP, I64, I8, I64, I8, SSTRP]),
    "rt_str_ord": (I8, [SSTRP, I64.as_pointer()]),
    "rt_str_chr": (I8, [I64, SSTRP]),
    "rt_str_parse_i64": (I8, [SSTRP, I64.as_pointer()]),
    "rt_str_parse_f64": (I8, [SSTRP, F64.as_pointer()]),
    "rt_sb_new": (I8P, []),
    "rt_sb_push_bytes": (VOID, [I8P, I8P, I64]),
    "rt_sb_push_str": (VOID, [I8P, SSTRP]),
    "rt_sb_push_repr_str": (VOID, [I8P, SSTRP]),
    "rt_sb_push_i64": (VOID, [I8P, I64]),
    "rt_sb_push_f64": (VOID, [I8P, F64]),
    "rt_sb_push_f64_prec": (VOID, [I8P, F64, I64]),
    "rt_sb_push_padded": (VOID, [I8P, SSTRP, I8, I64]),
    "rt_sb_finish": (VOID, [I8P, SSTRP]),
    "rt_list_grow": (VOID, [SLISTP, I64, I64]),
    "rt_list_free": (VOID, [SLISTP, I64]),
    "rt_list_remove": (VOID, [SLISTP, I64, I64]),
    "rt_list_insert": (VOID, [SLISTP, I64, I64, I8P]),
    "rt_list_reverse": (VOID, [SLISTP, I64]),
    "rt_shared_alloc": (I8P, [I64]),
    "rt_shared_free": (VOID, [I8P, I64]),
    "rt_file_open": (I8, [SSTRP, SSTRP, I8P.as_pointer()]),
    "rt_file_read": (I8, [I8P, SSTRP]),
    "rt_file_write": (I8, [I8P, SSTRP, I64.as_pointer()]),
    "rt_file_close": (VOID, [I8P]),
    "rt_file_drop": (VOID, [I8P]),
    "rt_print": (VOID, [SSTRP]),
    "rt_print_empty": (VOID, []),
    "rt_input": (I8, [SSTRP]),
    "rt_argv": (VOID, [SLISTP]),
    "rt_exit": (VOID, [I64]),
    "rt_round0": (I8, [F64, I64.as_pointer()]),
    "rt_round_n": (F64, [F64, I64]),
    "rt_int_from_f64": (I8, [F64, I64.as_pointer()]),
    "rt_f64_floormod": (I8, [F64, F64, I8, F64.as_pointer()]),
}

CMPFN = ir.FunctionType(I32, [I8P, I8P])


class LLVMGen:
    """Whole-program LLVM IR generator (full language)."""

    def __init__(self, tc: TypeChecker, define_c_main: bool = True):
        import llvmlite.binding as llvm
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
        self.tc = tc
        self.define_c_main = define_c_main
        self.module = ir.Module(name="serpentine")
        self.module.triple = llvm.get_default_triple()
        tm = llvm.Target.from_triple(self.module.triple).create_target_machine(
            codemodel="default")
        self.td = tm.target_data
        self.module.data_layout = str(self.td)
        self.rt: dict[str, ir.Function] = {}
        self.strings: dict[str, ir.GlobalVariable] = {}
        self.funcs: dict[tuple[str, str], ir.Function] = {}
        self.helpers: dict[tuple, ir.Function] = {}
        self.class_types: dict[str, ir.Type] = {}
        self._size_cache: dict[str, int] = {}
        self.di_files: dict[str, object] = {}
        self.di_cu = None
        self._setup_debug_info()

    # ---------- infrastructure ----------

    def _setup_debug_info(self) -> None:
        """Source-line mapping: DICompileUnit + per-module DIFiles + module flags
        so native stack traces / debuggers resolve to .py lines."""
        import sys as _sys
        entry = self.tc.program.entry
        main_file = self._di_file(str(entry.path))
        self.di_cu = self.module.add_debug_info("DICompileUnit", {
            "language": ir.DIToken("DW_LANG_C99"),
            "file": main_file,
            "producer": "serpentine (Backend B)",
            "runtimeVersion": 0,
            "isOptimized": False,
            "emissionKind": ir.DIToken("LineTablesOnly"),
        }, is_distinct=True)
        self.module.add_named_metadata("llvm.dbg.cu", self.di_cu)
        self.module.add_named_metadata(
            "llvm.module.flags",
            self.module.add_metadata([ir.IntType(32)(2), "Debug Info Version",
                                      ir.IntType(32)(3)]))
        if _sys.platform == "win32":
            self.module.add_named_metadata(
                "llvm.module.flags",
                self.module.add_metadata([ir.IntType(32)(2), "CodeView",
                                          ir.IntType(32)(1)]))
        else:
            self.module.add_named_metadata(
                "llvm.module.flags",
                self.module.add_metadata([ir.IntType(32)(2), "Dwarf Version",
                                          ir.IntType(32)(4)]))

    def _di_file(self, path: str):
        if path not in self.di_files:
            import os
            self.di_files[path] = self.module.add_debug_info("DIFile", {
                "filename": os.path.basename(path),
                "directory": os.path.dirname(path) or ".",
            })
        return self.di_files[path]

    def _di_subprogram(self, name: str, path: str, line: int):
        f = self._di_file(path)
        sub_ty = self.module.add_debug_info("DISubroutineType", {"types":
                                            self.module.add_metadata([None])})
        return self.module.add_debug_info("DISubprogram", {
            "name": name,
            "file": f,
            "line": line,
            "unit": self.di_cu,
            "scopeLine": line,
            "type": sub_ty,
            "spFlags": ir.DIToken("DISPFlagDefinition"),
        }, is_distinct=True)

    def _set_line(self, node) -> None:
        """Tag subsequently-emitted instructions with the statement's .py line."""
        if self.di_sub is None or not hasattr(node, "lineno"):
            return
        loc = self.module.add_debug_info("DILocation", {
            "line": node.lineno,
            "column": max(getattr(node, "col_offset", 0) + 1, 1),
            "scope": self.di_sub,
        })
        self.b.debug_metadata = loc

    def _rt(self, name: str) -> ir.Function:
        if name not in self.rt:
            ret, args = RT_SIGS[name]
            self.rt[name] = ir.Function(self.module, ir.FunctionType(ret, args), name=name)
        return self.rt[name]

    def _intrinsic(self, name: str, ret, argtys) -> ir.Function:
        if name in self.module.globals:
            return self.module.globals[name]
        return ir.Function(self.module, ir.FunctionType(ret, argtys), name=name)

    def _cstr(self, text: str):
        """(i8* pointer constant, byte length) of an interned string constant."""
        data = text.encode("utf-8")
        if text not in self.strings:
            ty = ir.ArrayType(I8, max(len(data), 1))
            gv = ir.GlobalVariable(self.module, ty, name=f".str{len(self.strings)}")
            gv.linkage = "internal"
            gv.global_constant = True
            gv.initializer = ir.Constant(ty, bytearray(data) if data else bytearray(b"\x00"))
            self.strings[text] = gv
        gv = self.strings[text]
        p = gv.gep([ir.Constant(I32, 0), ir.Constant(I32, 0)])
        return p, len(data)

    def _lty(self, t: Type) -> ir.Type:
        """LLVM storage type for a Serpentine type."""
        if isinstance(t, TInt):
            return I64
        if isinstance(t, TFloat):
            return F64
        if isinstance(t, TBool):
            return I1
        if isinstance(t, TNone):
            return I1                                  # dummy zero-ish slot
        if isinstance(t, TStr):
            return SSTR
        if isinstance(t, (TList, TDict)):
            return SLIST
        if isinstance(t, TTuple):
            return ir.LiteralStructType([self._lty(i) for i in t.items])
        if isinstance(t, TOptional):
            return ir.LiteralStructType([I1, self._lty(t.inner)])
        if isinstance(t, TClass):
            key = mangle_type(t)
            if key not in self.class_types:
                info = self.tc.classes[(t.module, t.name)]
                sub = dict(zip(info.typevars, t.args))
                self.class_types[key] = ir.LiteralStructType(
                    [self._lty(subst_type(info.fields[f], sub)) for f in info.field_order])
            return self.class_types[key]
        if isinstance(t, (TShared, TWeak, TFile)):
            return I8P
        if isinstance(t, TExc):
            return SERR
        if isinstance(t, TIterObj):
            return ir.LiteralStructType([SLISTP, I64])
        raise LLVMUnsupported(f"no LLVM type for {t}")

    def _is_agg(self, t: Type) -> bool:
        return isinstance(t, (TStr, TList, TDict, TTuple, TOptional, TClass, TExc, TIterObj))

    def _sizeof(self, t: Type) -> int:
        key = mangle_type(t)
        if key not in self._size_cache:
            self._size_cache[key] = self._lty(t).get_abi_size(self.td)
        return self._size_cache[key]

    def _droppable(self, t: Type) -> bool:
        if isinstance(t, (TStr, TList, TDict, TShared, TWeak, TExc, TFile)):
            return True
        if isinstance(t, TTuple):
            return any(self._droppable(i) for i in t.items)
        if isinstance(t, TOptional):
            return self._droppable(t.inner)
        if isinstance(t, TClass):
            info = self.tc.classes[(t.module, t.name)]
            sub = dict(zip(info.typevars, t.args))
            return any(self._droppable(subst_type(info.fields[f], sub))
                       for f in info.field_order)
        return False

    def _elem_of(self, t: Type) -> Type:
        """The raw element type stored in a list/dict buffer."""
        if isinstance(t, TList):
            return t.elem
        assert isinstance(t, TDict)
        return TTuple((t.key, t.value))

    def _entry_alloca(self, lty: ir.Type, name: str = "") -> ir.Value:
        """Allocate in the alloca-only entry block (never inside loops)."""
        b = ir.IRBuilder(self.entry_block)
        b.position_at_end(self.entry_block)
        return b.alloca(lty, name=name)

    def _temp(self, t: Type, register: bool = True) -> V:
        """An owned temp slot for an aggregate value, dropped at statement end
        unless consumed."""
        ptr = self._entry_alloca(self._lty(t))
        v = V(t, ptr=ptr, owned=True)
        if register:
            self.stmt_temps.append(v)
        return v

    def _consume(self, v: V) -> None:
        if v in self.stmt_temps:
            self.stmt_temps.remove(v)

    def _register_temp_ssa(self, t: Type, ssa) -> V:
        v = V(t, ssa=ssa, owned=True)
        self.stmt_temps.append(v)
        return v

    def _elem_ptr(self, b: ir.IRBuilder, listptr, elem_t: Type, idx):
        """Pointer to element idx of a list/dict buffer."""
        data = b.load(b.gep(listptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        esize = ir.Constant(I64, self._sizeof(elem_t))
        off = b.mul(idx, esize)
        raw = b.gep(data, [off])
        return b.bitcast(raw, self._lty(elem_t).as_pointer())

    def _list_len(self, b: ir.IRBuilder, listptr):
        return b.load(b.gep(listptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))

    def _set_list_len(self, b: ir.IRBuilder, listptr, n):
        b.store(n, b.gep(listptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))

    # ---------- type-directed drop / clone / eq / cmp / repr ----------

    def _helper(self, kind: str, t: Type, argtys, retty, emit_body) -> ir.Function:
        """Get-or-emit a per-type helper function; safe under recursion."""
        key = (kind, mangle_type(t))
        if key in self.helpers:
            return self.helpers[key]
        fn = ir.Function(self.module, ir.FunctionType(retty, argtys),
                         name=f"{kind}_{mangle_type(t)}")
        fn.linkage = "internal"
        self.helpers[key] = fn
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        emit_body(b, fn)
        return fn

    # ----- drop -----

    def _drop(self, b: ir.IRBuilder, t: Type, v: V) -> None:
        """Emit a drop of an owned value (ptr for aggregates, ssa for handles)."""
        if not self._droppable(t):
            return
        if isinstance(t, TStr):
            b.call(self._rt("rt_str_drop"), [v.ptr])
            return
        if isinstance(t, TFile):
            b.call(self._rt("rt_file_drop"), [v.ssa])
            return
        if isinstance(t, TShared):
            b.call(self._shared_drop_fn(t.inner), [v.ssa])
            return
        if isinstance(t, TWeak):
            b.call(self._weak_drop_fn(t.inner), [v.ssa])
            return
        if isinstance(t, TExc):
            k = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            m = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            b.call(self._rt("rt_str_drop"), [k])
            b.call(self._rt("rt_str_drop"), [m])
            return
        if isinstance(t, (TList, TDict)):
            b.call(self._drop_fn(t), [v.ptr])
            return
        if isinstance(t, TTuple):
            for i, it in enumerate(t.items):
                if self._droppable(it):
                    p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                    self._drop(b, it, self._as_v(b, it, p))
            return
        if isinstance(t, TOptional):
            has = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            with b.if_then(has):
                p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                self._drop(b, t.inner, self._as_v(b, t.inner, p))
            return
        if isinstance(t, TClass):
            info = self.tc.classes[(t.module, t.name)]
            sub = dict(zip(info.typevars, t.args))
            for i, f in enumerate(info.field_order):
                ft = subst_type(info.fields[f], sub)
                if self._droppable(ft):
                    p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                    self._drop(b, ft, self._as_v(b, ft, p))
            return
        raise LLVMUnsupported(f"drop of {t}")

    def _as_v(self, b: ir.IRBuilder, t: Type, ptr) -> V:
        """View a storage pointer as a V (loading handles/scalars)."""
        if self._is_agg(t):
            return V(t, ptr=ptr)
        return V(t, ssa=b.load(ptr))

    def _drop_fn(self, t: Type) -> ir.Function:
        """void drop_T(T*) for list/dict buffers (elements + buffer)."""
        elem = self._elem_of(t)

        def body(b, fn):
            lst = fn.args[0]
            if self._droppable(elem):
                n = self._list_len(b, lst)
                idx = b.alloca(I64)
                b.store(ir.Constant(I64, 0), idx)
                head = fn.append_basic_block("head")
                loop = fn.append_basic_block("loop")
                done = fn.append_basic_block("done")
                b.branch(head)
                b.position_at_end(head)
                i = b.load(idx)
                b.cbranch(b.icmp_signed("<", i, n), loop, done)
                b.position_at_end(loop)
                p = self._elem_ptr(b, lst, elem, i)
                self._drop(b, elem, self._as_v(b, elem, p))
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                b.branch(head)
                b.position_at_end(done)
            b.call(self._rt("rt_list_free"), [lst, ir.Constant(I64, self._sizeof(elem))])
            b.ret_void()

        lp = self._lty(t).as_pointer()
        return self._helper("drop", t, [lp], VOID, body)

    def _shared_drop_fn(self, inner: Type) -> ir.Function:
        def body(b, fn):
            h = fn.args[0]
            strongp = b.bitcast(h, I64.as_pointer())
            strong = b.sub(b.load(strongp), ir.Constant(I64, 1))
            b.store(strong, strongp)
            dead = b.icmp_signed("==", strong, ir.Constant(I64, 0))
            with b.if_then(dead):
                payload = b.bitcast(b.gep(h, [ir.Constant(I64, 24)]),
                                    self._lty(inner).as_pointer())
                self._drop(b, inner, self._as_v(b, inner, payload))
                weakp = b.gep(b.bitcast(h, I64.as_pointer()), [ir.Constant(I64, 1)])
                weak = b.sub(b.load(weakp), ir.Constant(I64, 1))
                b.store(weak, weakp)
                gone = b.icmp_signed("==", weak, ir.Constant(I64, 0))
                with b.if_then(gone):
                    b.call(self._rt("rt_shared_free"),
                           [h, ir.Constant(I64, self._sizeof(inner))])
            b.ret_void()

        return self._helper("dropsh", TShared(inner), [I8P], VOID, body)

    def _weak_drop_fn(self, inner: Type) -> ir.Function:
        def body(b, fn):
            h = fn.args[0]
            weakp = b.gep(b.bitcast(h, I64.as_pointer()), [ir.Constant(I64, 1)])
            weak = b.sub(b.load(weakp), ir.Constant(I64, 1))
            b.store(weak, weakp)
            gone = b.icmp_signed("==", weak, ir.Constant(I64, 0))
            with b.if_then(gone):
                b.call(self._rt("rt_shared_free"),
                       [h, ir.Constant(I64, self._sizeof(inner))])
            b.ret_void()

        return self._helper("dropwk", TWeak(inner), [I8P], VOID, body)

    # ----- clone -----

    def _clone_scalar(self, b: ir.IRBuilder, t: Type, ssa):
        """Clone a handle scalar (Shared/Weak): bump the refcount."""
        if isinstance(t, TShared):
            p = b.bitcast(ssa, I64.as_pointer())
            b.store(b.add(b.load(p), ir.Constant(I64, 1)), p)
            return ssa
        if isinstance(t, TWeak):
            p = b.gep(b.bitcast(ssa, I64.as_pointer()), [ir.Constant(I64, 1)])
            b.store(b.add(b.load(p), ir.Constant(I64, 1)), p)
            return ssa
        return ssa

    def _clone_into(self, b: ir.IRBuilder, t: Type, src_ptr, dst_ptr) -> None:
        """Clone the aggregate at src_ptr into dst_ptr (deep, type-directed)."""
        if isinstance(t, TStr):
            b.call(self._rt("rt_str_clone"), [src_ptr, dst_ptr])
            return
        if isinstance(t, TExc):
            for i in (0, 1):
                s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                b.call(self._rt("rt_str_clone"), [s, d])
            return
        if isinstance(t, (TList, TDict)):
            b.call(self._clone_fn(t), [src_ptr, dst_ptr])
            return
        if isinstance(t, TTuple):
            for i, it in enumerate(t.items):
                s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                self._clone_any(b, it, s, d)
            return
        if isinstance(t, TOptional):
            hs = b.load(b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            b.store(hs, b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            payload_d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            b.store(ir.Constant(self._lty(t.inner), None), payload_d)
            with b.if_then(hs):
                s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                self._clone_any(b, t.inner, s, payload_d)
            return
        if isinstance(t, TClass):
            info = self.tc.classes[(t.module, t.name)]
            sub = dict(zip(info.typevars, t.args))
            for i, f in enumerate(info.field_order):
                ft = subst_type(info.fields[f], sub)
                s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                self._clone_any(b, ft, s, d)
            return
        raise LLVMUnsupported(f"clone of {t}")

    def _clone_any(self, b: ir.IRBuilder, t: Type, src_ptr, dst_ptr) -> None:
        """Clone between storage slots for ANY type (bitwise for plain scalars)."""
        if self._is_agg(t):
            self._clone_into(b, t, src_ptr, dst_ptr)
            return
        val = b.load(src_ptr)
        if isinstance(t, (TShared, TWeak)):
            val = self._clone_scalar(b, t, val)
        b.store(val, dst_ptr)

    def _clone_fn(self, t: Type) -> ir.Function:
        """void clone_T(T* src, T* dst) for list/dict buffers."""
        elem = self._elem_of(t)

        def body(b, fn):
            src, dst = fn.args
            n = self._list_len(b, src)
            b.store(ir.Constant(SLIST, None), dst)
            with b.if_then(b.icmp_signed(">", n, ir.Constant(I64, 0))):
                b.call(self._rt("rt_list_grow"),
                       [dst, ir.Constant(I64, self._sizeof(elem)), n])
                idx = b.alloca(I64)
                b.store(ir.Constant(I64, 0), idx)
                head = fn.append_basic_block("head")
                loop = fn.append_basic_block("loop")
                done = fn.append_basic_block("done")
                b.branch(head)
                b.position_at_end(head)
                i = b.load(idx)
                b.cbranch(b.icmp_signed("<", i, n), loop, done)
                b.position_at_end(loop)
                sp = self._elem_ptr(b, src, elem, i)
                dp = self._elem_ptr(b, dst, elem, i)
                self._clone_any(b, elem, sp, dp)
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                b.branch(head)
                b.position_at_end(done)
                self._set_list_len(b, dst, n)
            b.ret_void()

        lp = self._lty(t).as_pointer()
        return self._helper("clone", t, [lp, lp], VOID, body)

    # ----- eq -----

    def _eq_vals(self, b: ir.IRBuilder, t: Type, a: V, c: V):
        """i1 equality between two values of type t."""
        if isinstance(t, TInt):
            return b.icmp_signed("==", a.ssa, c.ssa)
        if isinstance(t, TBool):
            return b.icmp_unsigned("==", a.ssa, c.ssa)
        if isinstance(t, TFloat):
            return b.fcmp_ordered("==", a.ssa, c.ssa)
        if isinstance(t, TStr):
            r = b.call(self._rt("rt_str_eq"), [a.ptr, c.ptr])
            return b.trunc(r, I1)
        if isinstance(t, TNone):
            return ir.Constant(I1, 1)
        if isinstance(t, TShared):
            inner = t.inner
            ap = b.bitcast(b.gep(a.ssa, [ir.Constant(I64, 24)]),
                           self._lty(inner).as_pointer())
            cp = b.bitcast(b.gep(c.ssa, [ir.Constant(I64, 24)]),
                           self._lty(inner).as_pointer())
            return b.call(self._eq_fn(inner), [ap, cp])
        if self._is_agg(t):
            return b.call(self._eq_fn(t), [a.ptr, c.ptr])
        raise LLVMUnsupported(f"equality on {t}")

    def _eq_fn(self, t: Type) -> ir.Function:
        lp = self._lty(t).as_pointer()

        def body(b, fn):
            ap, cp = fn.args
            if isinstance(t, (TList, TDict)):
                self._emit_eq_list_body(b, fn, t, ap, cp)
                return
            result = ir.Constant(I1, 1)
            if isinstance(t, TTuple):
                parts = [(i, it) for i, it in enumerate(t.items)]
            elif isinstance(t, TClass):
                info = self.tc.classes[(t.module, t.name)]
                sub = dict(zip(info.typevars, t.args))
                parts = [(i, subst_type(info.fields[f], sub))
                         for i, f in enumerate(info.field_order)]
            elif isinstance(t, TOptional):
                ha = b.load(b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                hc = b.load(b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                same = b.icmp_unsigned("==", ha, hc)
                out = b.alloca(I1)
                b.store(same, out)
                both = b.and_(ha, hc)
                with b.if_then(both):
                    pa = b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                    pc = b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                    e = self._eq_vals(b, t.inner, self._as_v(b, t.inner, pa),
                                      self._as_v(b, t.inner, pc))
                    b.store(e, out)
                b.ret(b.load(out))
                return
            else:
                raise LLVMUnsupported(f"eq fn for {t}")
            for i, it in parts:
                pa = b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                pc = b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                e = self._eq_vals(b, it, self._as_v(b, it, pa), self._as_v(b, it, pc))
                result = b.and_(result, e)
            b.ret(result)

        return self._helper("eq", t, [lp, lp], I1, body)

    def _emit_eq_list_body(self, b, fn, t, ap, cp) -> None:
        """List eq: elementwise in order. Dict eq: same len + every entry of a
        found in c with equal value (order-insensitive, mirrors prelude)."""
        elem = self._elem_of(t)
        na = self._list_len(b, ap)
        nc = self._list_len(b, cp)
        neq = fn.append_basic_block("neq")
        scan = fn.append_basic_block("scan")
        b.cbranch(b.icmp_signed("==", na, nc), scan, neq)
        b.position_at_end(neq)
        b.ret(ir.Constant(I1, 0))
        b.position_at_end(scan)
        idx = b.alloca(I64)
        b.store(ir.Constant(I64, 0), idx)
        head = fn.append_basic_block("head")
        loop = fn.append_basic_block("loop")
        ok = fn.append_basic_block("ok")
        b.branch(head)
        b.position_at_end(head)
        i = b.load(idx)
        b.cbranch(b.icmp_signed("<", i, na), loop, ok)
        b.position_at_end(loop)
        pa = self._elem_ptr(b, ap, elem, i)
        if isinstance(t, TList):
            pc = self._elem_ptr(b, cp, elem, i)
            e = self._eq_vals(b, elem, self._as_v(b, elem, pa), self._as_v(b, elem, pc))
            b.store(b.add(i, ir.Constant(I64, 1)), idx)
            b.cbranch(e, head, neq)
        else:
            assert isinstance(t, TDict)
            kt, vt = t.key, t.value
            ka = b.gep(pa, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            va = b.gep(pa, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            found = b.alloca(I1)
            b.store(ir.Constant(I1, 0), found)
            jdx = b.alloca(I64)
            b.store(ir.Constant(I64, 0), jdx)
            ihead = fn.append_basic_block("ihead")
            iloop = fn.append_basic_block("iloop")
            idone = fn.append_basic_block("idone")
            b.branch(ihead)
            b.position_at_end(ihead)
            j = b.load(jdx)
            b.cbranch(b.icmp_signed("<", j, nc), iloop, idone)
            b.position_at_end(iloop)
            pc = self._elem_ptr(b, cp, elem, j)
            kc = b.gep(pc, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            vc = b.gep(pc, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            keq = self._eq_vals(b, kt, self._as_v(b, kt, ka), self._as_v(b, kt, kc))
            veq = self._eq_vals(b, vt, self._as_v(b, vt, va), self._as_v(b, vt, vc))
            hit = b.and_(keq, veq)
            b.store(b.or_(b.load(found), hit), found)
            b.store(b.add(j, ir.Constant(I64, 1)), jdx)
            b.branch(ihead)
            b.position_at_end(idone)
            b.store(b.add(i, ir.Constant(I64, 1)), idx)
            b.cbranch(b.load(found), head, neq)
        b.position_at_end(ok)
        b.ret(ir.Constant(I1, 1))

    # ----- ordering (sort / sorted / min / max) -----

    def _cmp_fn(self, t: Type) -> ir.Function:
        """i32 cmp_T(i8*, i8*): -1/0/1, PartialOrd-with-Equal-fallback parity."""

        def body(b, fn):
            ap = b.bitcast(fn.args[0], self._lty(t).as_pointer())
            cp = b.bitcast(fn.args[1], self._lty(t).as_pointer())
            r = self._cmp_ptrs(b, t, ap, cp)
            b.ret(r)

        return self._helper("cmp", t, [I8P, I8P], I32, body)

    def _cmp_ptrs(self, b: ir.IRBuilder, t: Type, ap, cp):
        if isinstance(t, TStr):
            return b.call(self._rt("rt_str_cmp"), [ap, cp])
        if isinstance(t, (TInt, TBool)):
            a = b.load(ap)
            c = b.load(cp)
            if isinstance(t, TBool):
                a = b.zext(a, I64)
                c = b.zext(c, I64)
            lt = b.icmp_signed("<", a, c)
            gt = b.icmp_signed(">", a, c)
            r = b.select(lt, ir.Constant(I32, -1), ir.Constant(I32, 1))
            return b.select(b.or_(lt, gt), r, ir.Constant(I32, 0))
        if isinstance(t, TFloat):
            a = b.load(ap)
            c = b.load(cp)
            lt = b.fcmp_ordered("<", a, c)
            gt = b.fcmp_ordered(">", a, c)
            r = b.select(lt, ir.Constant(I32, -1), ir.Constant(I32, 1))
            return b.select(b.or_(lt, gt), r, ir.Constant(I32, 0))
        if isinstance(t, TTuple):
            out = b.alloca(I32)
            b.store(ir.Constant(I32, 0), out)
            blocks = []
            fn = b.function
            done = fn.append_basic_block("cmp.done")
            for i, it in enumerate(t.items):
                pa = b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                pc = b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                r = self._cmp_ptrs(b, it, pa, pc)
                b.store(r, out)
                nz = b.icmp_signed("!=", r, ir.Constant(I32, 0))
                nxt = fn.append_basic_block(f"cmp.n{i}")
                b.cbranch(nz, done, nxt)
                b.position_at_end(nxt)
            b.branch(done)
            b.position_at_end(done)
            return b.load(out)
        raise LLVMUnsupported(f"ordering on {t}")

    # ----- repr / py_str -----

    def _push_bytes(self, b: ir.IRBuilder, sb, text: str) -> None:
        p, n = self._cstr(text)
        b.call(self._rt("rt_sb_push_bytes"), [sb, p, ir.Constant(I64, n)])

    def _push(self, b: ir.IRBuilder, t: Type, v: V, sb, as_repr: bool) -> None:
        """Append py_str/py_repr of v to string-builder sb (CPython parity)."""
        if isinstance(t, TInt):
            b.call(self._rt("rt_sb_push_i64"), [sb, v.ssa])
            return
        if isinstance(t, TFloat):
            b.call(self._rt("rt_sb_push_f64"), [sb, v.ssa])
            return
        if isinstance(t, TBool):
            tp, tn = self._cstr("True")
            fp, fn_ = self._cstr("False")
            p = b.select(v.ssa, tp, fp)
            n = b.select(v.ssa, ir.Constant(I64, tn), ir.Constant(I64, fn_))
            b.call(self._rt("rt_sb_push_bytes"), [sb, p, n])
            return
        if isinstance(t, TNone):
            self._push_bytes(b, sb, "None")
            return
        if isinstance(t, TStr):
            fn = "rt_sb_push_repr_str" if as_repr else "rt_sb_push_str"
            b.call(self._rt(fn), [sb, v.ptr])
            return
        if isinstance(t, TExc):
            tmp = b.alloca(SSTR)
            fn = "rt_err_repr" if as_repr else "rt_err_msg"
            b.call(self._rt(fn), [v.ptr, tmp])
            b.call(self._rt("rt_sb_push_str"), [sb, tmp])
            b.call(self._rt("rt_str_drop"), [tmp])
            return
        if isinstance(t, TOptional):
            has = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            fnc = b.function
            some = fnc.append_basic_block("opt.some")
            none = fnc.append_basic_block("opt.none")
            join = fnc.append_basic_block("opt.join")
            b.cbranch(has, some, none)
            b.position_at_end(some)
            p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            self._push(b, t.inner, self._as_v(b, t.inner, p), sb, as_repr)
            b.branch(join)
            b.position_at_end(none)
            self._push_bytes(b, sb, "None")
            b.branch(join)
            b.position_at_end(join)
            return
        if isinstance(t, TShared):
            payload = b.bitcast(b.gep(v.ssa, [ir.Constant(I64, 24)]),
                                self._lty(t.inner).as_pointer())
            self._push(b, t.inner, self._as_v(b, t.inner, payload), sb, as_repr)
            return
        if isinstance(t, TWeak):
            self._push_bytes(b, sb, "<weak>")
            return
        if isinstance(t, (TList, TDict, TTuple, TClass)):
            b.call(self._repr_fn(t), [sb, v.ptr])
            return
        raise LLVMUnsupported(f"print of {t}")

    def _repr_fn(self, t: Type) -> ir.Function:
        """void repr_T(i8* sb, T* v): container/class repr (always repr inside)."""
        lp = self._lty(t).as_pointer()

        def body(b, fn):
            sb, vp = fn.args
            if isinstance(t, (TList, TDict)):
                elem = self._elem_of(t)
                is_dict = isinstance(t, TDict)
                self._push_bytes(b, sb, "{" if is_dict else "[")
                n = self._list_len(b, vp)
                idx = b.alloca(I64)
                b.store(ir.Constant(I64, 0), idx)
                head = fn.append_basic_block("head")
                loop = fn.append_basic_block("loop")
                done = fn.append_basic_block("done")
                b.branch(head)
                b.position_at_end(head)
                i = b.load(idx)
                b.cbranch(b.icmp_signed("<", i, n), loop, done)
                b.position_at_end(loop)
                first = b.icmp_signed("==", i, ir.Constant(I64, 0))
                with b.if_then(b.not_(first)):
                    self._push_bytes(b, sb, ", ")
                p = self._elem_ptr(b, vp, elem, i)
                if is_dict:
                    kp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
                    vp2 = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                    self._push(b, t.key, self._as_v(b, t.key, kp), sb, True)
                    self._push_bytes(b, sb, ": ")
                    self._push(b, t.value, self._as_v(b, t.value, vp2), sb, True)
                else:
                    self._push(b, elem, self._as_v(b, elem, p), sb, True)
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                b.branch(head)
                b.position_at_end(done)
                self._push_bytes(b, sb, "}" if is_dict else "]")
                b.ret_void()
                return
            if isinstance(t, TTuple):
                self._push_bytes(b, sb, "(")
                for i, it in enumerate(t.items):
                    if i:
                        self._push_bytes(b, sb, ", ")
                    p = b.gep(vp, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                    self._push(b, it, self._as_v(b, it, p), sb, True)
                if len(t.items) == 1:
                    self._push_bytes(b, sb, ",")
                self._push_bytes(b, sb, ")")
                b.ret_void()
                return
            assert isinstance(t, TClass)
            info = self.tc.classes[(t.module, t.name)]
            sub = dict(zip(info.typevars, t.args))
            self._push_bytes(b, sb, f"{info.name}(")
            for i, f in enumerate(info.field_order):
                if i:
                    self._push_bytes(b, sb, ", ")
                self._push_bytes(b, sb, f"{f}=")
                ft = subst_type(info.fields[f], sub)
                p = b.gep(vp, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                self._push(b, ft, self._as_v(b, ft, p), sb, True)
            self._push_bytes(b, sb, ")")
            b.ret_void()

        return self._helper("repr", t, [I8P, lp], VOID, body)

    # ---------- program ----------

    def _sanitize(self, name: str) -> str:
        import re
        return re.sub(r"[^0-9A-Za-z_]", "_", name)

    def generate(self) -> ir.Module:
        """Emit every checked function, helpers, and the entry point."""
        sigs = [s for (m, n), s in self.tc.sigs.items()
                if not s.is_template and (s.module, s.name) in self.tc.facts]
        for sig in sigs:
            self._declare_function(sig)
        for sig in sigs:
            self._emit_function(sig)
        entry = self.tc.program.entry
        if entry.entry_call is None:
            raise LLVMUnsupported("no entry point")
        se = ir.Function(self.module, ir.FunctionType(VOID, []), name="serp_entry")
        b = ir.IRBuilder(se.append_basic_block("entry"))
        res = b.call(self.funcs[(entry.name, entry.entry_call)], [])
        errbit = res if isinstance(res.type, ir.IntType) and res.type.width == 1 \
            else b.extract_value(res, 0)
        with b.if_then(errbit):
            b.call(self._rt("rt_abort_pending"), [])
            b.unreachable()
        b.ret_void()
        if self.define_c_main:
            mn = ir.Function(self.module, ir.FunctionType(I32, []), name="main")
            mb = ir.IRBuilder(mn.append_basic_block("entry"))
            mb.call(se, [])
            mb.ret(ir.Constant(I32, 0))
        return self.module

    def _fnty(self, sig: FuncSig) -> ir.FunctionType:
        argtys = []
        for p in sig.params:
            if p.conv in ("ref", "mut"):
                argtys.append(self._lty(p.typ).as_pointer())
            else:
                argtys.append(self._lty(p.typ))
        if isinstance(sig.ret, TNone):
            retty = I1
        else:
            retty = ir.LiteralStructType([I1, self._lty(sig.ret)])
        return ir.FunctionType(retty, argtys)

    def _declare_function(self, sig: FuncSig) -> None:
        name = self._sanitize(f"f_{sig.module}_{sig.name}")
        fn = ir.Function(self.module, self._fnty(sig), name=name)
        fn.linkage = "internal"
        self.funcs[(sig.module, sig.name)] = fn

    def _loop_bound_names(self, fn: ast.FunctionDef) -> set[str]:
        names = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.For):
                targets = [node.target] if isinstance(node.target, ast.Name) \
                    else list(node.target.elts)
                for t in targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            if isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        names.add(item.optional_vars.id)
        return names

    def _emit_function(self, sig: FuncSig) -> None:
        fn = self.funcs[(sig.module, sig.name)]
        self.fn = fn
        self.sig = sig
        self.mod: Module = self.tc.program.modules[sig.module]
        self.facts = self.tc.facts[(sig.module, sig.name)]
        self.entry_block = fn.append_basic_block("entry")
        self.body_block = fn.append_basic_block("body")
        self.b = ir.IRBuilder(self.body_block)
        self.bindings: dict[str, dict] = {}
        self.func_drops: list[dict] = []
        self.try_ctx: list[dict] = []
        self.cur_exc: list = []
        self.loop_stack: list[tuple] = []
        self.stmt_temps: list[V] = []
        self.active_borrows: list[tuple] = []
        self.try_counter = 0
        self.raise_blocks: dict = {}

        self.errflag_slot = self._entry_alloca(I1, name="errflag")
        self.b.store(ir.Constant(I1, 0), self.errflag_slot)
        if not isinstance(sig.ret, TNone):
            self.ret_slot = self._entry_alloca(self._lty(sig.ret), name="retval")
            self.b.store(ir.Constant(self._lty(sig.ret), None), self.ret_slot)
        else:
            self.ret_slot = None
        self.exit_block = fn.append_basic_block("func.exit")
        self.err_return_block = fn.append_basic_block("func.err")

        loop_bound = self._loop_bound_names(sig.node)
        param_names = {p.name for p in sig.params}
        for name, t in self.facts.locals.items():
            if name in param_names or name in loop_bound:
                continue
            self._make_binding(name, t)
        for p, arg in zip(sig.params, fn.args):
            arg.name = f"a_{p.name}"
            if p.conv in ("ref", "mut"):
                slot = self._entry_alloca(self._lty(p.typ).as_pointer(), name=f"v_{p.name}")
                self.b.store(arg, slot)
                self.bindings[p.name] = {"ptr": slot, "ty": p.typ, "ref": True,
                                         "flag": None}
            else:
                bind = self._make_binding(p.name, p.typ)
                self.b.store(arg, bind["ptr"])
                if bind["flag"] is not None:
                    self.b.store(ir.Constant(I1, 1), bind["flag"])

        body = sig.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        self._emit_block(body)
        if not self.b.block.is_terminated:
            self.b.store(ir.Constant(I1, 0), self.errflag_slot)
            self.b.branch(self.exit_block)

        b = ir.IRBuilder(self.err_return_block)
        b.store(ir.Constant(I1, 1), self.errflag_slot)
        b.branch(self.exit_block)
        eb = ir.IRBuilder(self.entry_block)
        eb.position_at_end(self.entry_block)
        eb.branch(self.body_block)

        b = ir.IRBuilder(self.exit_block)
        for bind in reversed(self.func_drops):
            flagged = b.load(bind["flag"])
            with b.if_then(flagged):
                self._drop(b, bind["ty"], self._as_v(b, bind["ty"], bind["ptr"]))
        flag = b.load(self.errflag_slot)
        if isinstance(sig.ret, TNone):
            b.ret(flag)
        else:
            res = ir.Constant(ir.LiteralStructType([I1, self._lty(sig.ret)]), None)
            res = b.insert_value(res, flag, 0)
            res = b.insert_value(res, b.load(self.ret_slot), 1)
            b.ret(res)

    def _make_binding(self, name: str, t: Type) -> dict:
        slot = self._entry_alloca(self._lty(t), name=f"v_{name}")
        flag = None
        if self._droppable(t):
            flag = self._entry_alloca(I1, name=f"init_{name}")
            eb = ir.IRBuilder(self.entry_block)
            eb.position_at_end(self.entry_block)
            eb.store(ir.Constant(I1, 0), flag)
        bind = {"ptr": slot, "ty": t, "ref": False, "flag": flag}
        self.bindings[name] = bind
        if flag is not None:
            self.func_drops.append(bind)
        return bind

    # ---------- statement plumbing ----------

    def _err_target(self):
        if self.try_ctx:
            return self.try_ctx[-1]["block"]
        return self.err_return_block

    def _release_borrows(self, b: ir.IRBuilder, downto: int = 0) -> None:
        for handle, kind in reversed(self.active_borrows[downto:]):
            bp = b.gep(b.bitcast(handle, I64.as_pointer()), [ir.Constant(I64, 2)])
            if kind == "mut":
                b.store(ir.Constant(I64, 0), bp)
            else:
                b.store(b.sub(b.load(bp), ir.Constant(I64, 1)), bp)

    def _check_err(self, errbit) -> None:
        """Branch to the current error target when errbit is set."""
        bad = self.fn.append_basic_block("err")
        ok = self.fn.append_basic_block("ok")
        self.b.cbranch(errbit, bad, ok)
        self.b.position_at_end(bad)
        self._release_borrows(self.b)
        self.b.branch(self._err_target())
        self.b.position_at_end(ok)

    def _check_err_i8(self, status) -> None:
        self._check_err(self.b.icmp_signed("!=", status, ir.Constant(I8, 0)))

    def _raise_static(self, kind: str, msg: str) -> None:
        """Set a static error pending and take the error edge."""
        kp, kl = self._cstr(kind)
        mp, ml = self._cstr(msg)
        self.b.call(self._rt("rt_raise_static"),
                    [kp, ir.Constant(I64, kl), mp, ir.Constant(I64, ml)])
        self._release_borrows(self.b)
        self.b.branch(self._err_target())
        cont = self.fn.append_basic_block("cont")
        self.b.position_at_end(cont)

    def _cond_raise_static(self, cond, kind: str, msg: str) -> None:
        ok = self.fn.append_basic_block("ok")
        if not self.active_borrows:
            key = (kind, msg, self._err_target().name)
            bad = self.raise_blocks.get(key)
            if bad is None:
                bad = self.fn.append_basic_block("raise")
                b = ir.IRBuilder(bad)
                kp, kl = self._cstr(kind)
                mp, ml = self._cstr(msg)
                b.call(self._rt("rt_raise_static"),
                       [kp, ir.Constant(I64, kl), mp, ir.Constant(I64, ml)])
                b.branch(self._err_target())
                self.raise_blocks[key] = bad
            self.b.cbranch(cond, bad, ok)
            self.b.position_at_end(ok)
            return
        bad = self.fn.append_basic_block("raise")
        self.b.cbranch(cond, bad, ok)
        self.b.position_at_end(bad)
        kp, kl = self._cstr(kind)
        mp, ml = self._cstr(msg)
        self.b.call(self._rt("rt_raise_static"),
                    [kp, ir.Constant(I64, kl), mp, ir.Constant(I64, ml)])
        self._release_borrows(self.b)
        self.b.branch(self._err_target())
        self.b.position_at_end(ok)

    def _drain(self, mark_t: int, mark_b: int) -> None:
        """Statement-end cleanup: drop unconsumed temps, release borrows."""
        for v in reversed(self.stmt_temps[mark_t:]):
            self._drop(self.b, v.ty, v)
        del self.stmt_temps[mark_t:]
        self._release_borrows(self.b, mark_b)
        del self.active_borrows[mark_b:]

    def _emit_block(self, stmts: list[ast.stmt]) -> None:
        saved = dict(self.bindings)
        for s in stmts:
            if self.b.block.is_terminated:
                break
            self._emit_stmt(s)
        self.bindings = saved

    def _emit_stmt(self, s: ast.stmt) -> None:
        mark_t = len(self.stmt_temps)
        mark_b = len(self.active_borrows)
        self._stmt_inner(s)
        if self.b.block.is_terminated:
            del self.stmt_temps[mark_t:]
            del self.active_borrows[mark_b:]
        else:
            self._drain(mark_t, mark_b)

    def _stmt_inner(self, s: ast.stmt) -> None:
        if isinstance(s, ast.Pass):
            return
        if isinstance(s, (ast.Assign, ast.AnnAssign)):
            self._emit_assign(s)
            return
        if isinstance(s, ast.AugAssign):
            self._emit_augassign(s)
            return
        if isinstance(s, ast.Return):
            self._emit_return(s)
            return
        if isinstance(s, ast.Expr):
            self._emit_expr_stmt(s.value)
            return
        if isinstance(s, ast.If):
            self._emit_if(s)
            return
        if isinstance(s, ast.While):
            self._emit_while(s)
            return
        if isinstance(s, ast.For):
            self._emit_for(s)
            return
        if isinstance(s, ast.With):
            self._emit_with(s)
            return
        if isinstance(s, ast.Try):
            self._emit_try(s)
            return
        if isinstance(s, ast.Raise):
            self._emit_raise(s)
            return
        if isinstance(s, ast.Break):
            self._drain_for_jump()
            self.b.branch(self.loop_stack[-1][1])
            return
        if isinstance(s, ast.Continue):
            self._drain_for_jump()
            self.b.branch(self.loop_stack[-1][0])
            return
        raise LLVMUnsupported(f"statement {type(s).__name__}")

    def _drain_for_jump(self) -> None:
        """break/continue/return: release this statement's borrows (none expected)."""
        self._release_borrows(self.b)

    def _emit_return(self, s: ast.Return) -> None:
        if s.value is not None and not isinstance(self.sig.ret, TNone):
            v = self._coerce(self._expr(s.value, "val", expect=self.sig.ret),
                             self.sig.ret)
            self._store_into(self.ret_slot, v)
        mark = 0
        for tv in reversed(self.stmt_temps):
            self._drop(self.b, tv.ty, tv)
        del self.stmt_temps[:]
        self._release_borrows(self.b)
        del self.active_borrows[:]
        self.b.store(ir.Constant(I1, 0), self.errflag_slot)
        self.b.branch(self.exit_block)

    def _store_into(self, dst_ptr, v: V) -> None:
        """Move an owned value into a storage slot (consuming the temp)."""
        if self._is_agg(v.ty):
            self.b.store(self.b.load(v.ptr), dst_ptr)
        else:
            self.b.store(v.ssa, dst_ptr)
        self._consume(v)

    def _emit_expr_stmt(self, e: ast.expr) -> None:
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "print":
            self._emit_print(e)
            return
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) \
                and isinstance(e.func.value, ast.Name) and e.func.value.id == "sys" \
                and e.func.attr == "exit" and self.mod.imports_sys:
            code = self._expr(e.args[0], "val").ssa if e.args else ir.Constant(I64, 0)
            self.b.call(self._rt("rt_exit"), [code])
            self.b.unreachable()
            dead = self.fn.append_basic_block("dead")
            self.b.position_at_end(dead)
            return
        self._expr(e, "val")

    def _emit_print(self, e: ast.Call) -> None:
        if not e.args:
            self.b.call(self._rt("rt_print_empty"), [])
            return
        sb = self.b.call(self._rt("rt_sb_new"), [])
        for i, a in enumerate(e.args):
            if i:
                self._push_bytes(self.b, sb, " ")
            v = self._expr(a, "ref")
            self._push(self.b, self._t(a), v, sb, as_repr=False)
        out = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_sb_finish"), [sb, out])
        self.b.call(self._rt("rt_print"), [out])
        self.b.call(self._rt("rt_str_drop"), [out])

    def _emit_assign(self, stmt) -> None:
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
        assert stmt.value is not None
        bind = self.tc.elem_borrow_binds.get(id(stmt))
        if bind is not None:
            name, _root = bind
            v = self._expr(stmt.value, "ref")
            t = self._t(stmt.value)
            slot = self._entry_alloca(self._lty(t).as_pointer(), name=f"v_{name}")
            self.b.store(v.ptr, slot)
            self.bindings[name] = {"ptr": slot, "ty": t, "ref": True, "flag": None}
            return
        ibind = self.tc.iter_binds.get(id(stmt))
        if ibind is not None:
            name, _root = ibind
            assert isinstance(stmt.value, ast.Call)
            seq = self._expr(stmt.value.args[0], "ref")
            it_t = TIterObj(self._t(stmt.value.args[0]).elem)
            slot = self._entry_alloca(self._lty(it_t), name=f"v_{name}")
            self.b.store(seq.ptr, self.b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            self.b.store(ir.Constant(I64, 0),
                         self.b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
            self.bindings[name] = {"ptr": slot, "ty": it_t, "ref": False, "flag": None}
            return
        if isinstance(target, ast.Name):
            bind = self.bindings[target.id]
            v = self._coerce(self._expr(stmt.value, "val", expect=bind["ty"]), bind["ty"])
            self._drop_flagged(bind)
            self._store_into(bind["ptr"], v)
            if bind["flag"] is not None:
                self.b.store(ir.Constant(I1, 1), bind["flag"])
            return
        if isinstance(target, ast.Subscript):
            cont_t = self._t(target.value)
            shared = isinstance(cont_t, TShared)
            inner = cont_t.inner if shared else cont_t
            if isinstance(inner, TList):
                elem = inner.elem
                v = self._coerce(self._expr(stmt.value, "val", expect=elem), elem)
                recv = self._recv(target.value, True)
                idx = self._expr(target.slice, "val").ssa
                j = self._norm_index(recv.ptr, idx, "list assignment index out of range")
                p = self._elem_ptr(self.b, recv.ptr, elem, j)
                if self._droppable(elem):
                    self._drop(self.b, elem, self._as_v(self.b, elem, p))
                self._store_into(p, v)
                return
            assert isinstance(inner, TDict)
            v = self._coerce(self._expr(stmt.value, "val", expect=inner.value), inner.value)
            recv = self._recv(target.value, True)
            k = self._expr(target.slice, "val")
            self._dict_set(recv.ptr, inner, k, v)
            return
        if isinstance(target, ast.Attribute):
            base_t = self._t(target.value)
            ft = self._t(target)
            v = self._coerce(self._expr(stmt.value, "val", expect=ft), ft)
            if isinstance(base_t, TShared):
                payload = self._borrow(self._expr(target.value, "val").ssa, mut=True,
                                       inner=base_t.inner)
                p = self._field_ptr(payload, base_t.inner, target.attr)
            else:
                p = self._field_ptr(self._place(target.value, mut=True),
                                    base_t, target.attr)
            if self._droppable(ft):
                self._drop(self.b, ft, self._as_v(self.b, ft, p))
            self._store_into(p, v)
            return
        raise LLVMUnsupported("unsupported assignment target")

    def _drop_flagged(self, bind: dict) -> None:
        if bind["flag"] is None:
            return
        flagged = self.b.load(bind["flag"])
        with self.b.if_then(flagged):
            self._drop(self.b, bind["ty"], self._as_v(self.b, bind["ty"], bind["ptr"]))
        self.b.store(ir.Constant(I1, 0), bind["flag"])

    def _emit_augassign(self, stmt: ast.AugAssign) -> None:
        rt = self._t(stmt.value)
        if isinstance(stmt.target, ast.Name):
            bind = self.bindings[stmt.target.id]
            cur = self._expr(stmt.target, "val")
            rhs = self._expr(stmt.value, "val")
            res = self._binop(stmt.op, cur, rhs)
            res = self._coerce(res, bind["ty"])
            self._drop_flagged(bind)
            self._store_into(bind["ptr"], res)
            if bind["flag"] is not None:
                self.b.store(ir.Constant(I1, 1), bind["flag"])
            return
        t = self._t(stmt.target)
        rhs = self._expr(stmt.value, "val")
        p = self._place(stmt.target, mut=True)
        cur = self._as_v(self.b, t, p)
        if isinstance(t, TStr):
            cur = V(t, ptr=p)
        res = self._binop(stmt.op, cur, rhs)
        if self._droppable(t):
            self._drop(self.b, t, self._as_v(self.b, t, p))
        self._store_into(p, self._coerce(res, t))

    def _emit_if(self, s: ast.If) -> None:
        mark_t = len(self.stmt_temps)
        mark_b = len(self.active_borrows)
        cond = self._expr(s.test, "val").ssa
        self._drain(mark_t, mark_b)
        then_b = self.fn.append_basic_block("then")
        else_b = self.fn.append_basic_block("else") if s.orelse else None
        join = self.fn.append_basic_block("join")
        self.b.cbranch(cond, then_b, else_b or join)
        self.b.position_at_end(then_b)
        self._emit_block(s.body)
        if not self.b.block.is_terminated:
            self.b.branch(join)
        if else_b is not None:
            self.b.position_at_end(else_b)
            self._emit_block(s.orelse)
            if not self.b.block.is_terminated:
                self.b.branch(join)
        self.b.position_at_end(join)

    def _emit_while(self, s: ast.While) -> None:
        head = self.fn.append_basic_block("while.head")
        body = self.fn.append_basic_block("while.body")
        exit_b = self.fn.append_basic_block("while.exit")
        self.b.branch(head)
        self.b.position_at_end(head)
        mark_t = len(self.stmt_temps)
        mark_b = len(self.active_borrows)
        cond = self._expr(s.test, "val").ssa
        self._drain(mark_t, mark_b)
        self.b.cbranch(cond, body, exit_b)
        self.b.position_at_end(body)
        self.loop_stack.append((head, exit_b))
        self._emit_block(s.body)
        self.loop_stack.pop()
        if not self.b.block.is_terminated:
            self.b.branch(head)
        self.b.position_at_end(exit_b)

    def _emit_with(self, s: ast.With) -> None:
        item = s.items[0]
        assert isinstance(item.optional_vars, ast.Name)
        name = item.optional_vars.id
        mark_t = len(self.stmt_temps)
        mark_b = len(self.active_borrows)
        ctx = self._expr(item.context_expr, "val")
        self._consume(ctx)
        self._drain(mark_t, mark_b)
        saved = dict(self.bindings)
        bind = self._make_binding(name, TFile())
        self.b.store(ctx.ssa, bind["ptr"])
        self.b.store(ir.Constant(I1, 1), bind["flag"])
        self._emit_block(s.body)
        self.bindings = saved
        if not self.b.block.is_terminated:
            self._drop_flagged(bind)

    def _emit_raise(self, s: ast.Raise) -> None:
        if s.exc is None:
            cur = self.cur_exc[-1]
            self.b.call(self._rt("rt_err_reraise"), [cur])
            self._release_borrows(self.b)
            self.b.branch(self._err_target())
            dead = self.fn.append_basic_block("dead")
            self.b.position_at_end(dead)
            return
        e = s.exc
        if isinstance(e, ast.Name):
            self._do_raise(e.id, None)
            return
        assert isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
        kind = e.func.id
        if not e.args:
            self._do_raise(kind, None)
            return
        arg = e.args[0]
        argt = self._t(arg)
        sb = self.b.call(self._rt("rt_sb_new"), [])
        v = self._expr(arg, "ref")
        self._push(self.b, argt, v, sb, as_repr=(kind == "KeyError"))
        msg = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_sb_finish"), [sb, msg])
        self._do_raise(kind, msg)

    def _do_raise(self, kind: str, msg_ptr) -> None:
        kp, kl = self._cstr(kind)
        if msg_ptr is None:
            mp, ml = self._cstr("")
            self.b.call(self._rt("rt_raise_static"),
                        [kp, ir.Constant(I64, kl), mp, ir.Constant(I64, ml)])
        else:
            ktmp = self._entry_alloca(SSTR)
            self.b.call(self._rt("rt_str_new"), [kp, ir.Constant(I64, kl), ktmp])
            self.b.call(self._rt("rt_raise"), [ktmp, msg_ptr])
            self.b.call(self._rt("rt_str_drop"), [ktmp])
            self.b.call(self._rt("rt_str_drop"), [msg_ptr])
        for v in reversed(self.stmt_temps):
            self._drop(self.b, v.ty, v)
        del self.stmt_temps[:]
        self._release_borrows(self.b)
        del self.active_borrows[:]
        self.b.branch(self._err_target())
        dead = self.fn.append_basic_block("dead")
        self.b.position_at_end(dead)

    def _emit_try(self, s: ast.Try) -> None:
        self.try_counter += 1
        exc_set = self._entry_alloca(I1)
        self.b.store(ir.Constant(I1, 0), exc_set)
        exc = self._entry_alloca(SERR)
        rexc_set = self._entry_alloca(I1)
        self.b.store(ir.Constant(I1, 0), rexc_set)
        rexc = self._entry_alloca(SERR)

        catch = self.fn.append_basic_block("try.catch")
        join = self.fn.append_basic_block("try.join")
        self.try_ctx.append({"block": catch})
        self._emit_block(s.body)
        self.try_ctx.pop()
        if not self.b.block.is_terminated:
            self.b.branch(join)
        b = ir.IRBuilder(catch)
        b.call(self._rt("rt_err_take"), [exc])
        b.store(ir.Constant(I1, 1), exc_set)
        b.branch(join)
        self.b.position_at_end(join)

        if s.handlers:
            hcatch = self.fn.append_basic_block("hnd.catch")
            hjoin = self.fn.append_basic_block("hnd.join")
            was_set = self.b.load(exc_set)
            dispatch = self.fn.append_basic_block("hnd.dispatch")
            self.b.cbranch(was_set, dispatch, hjoin)
            self.b.position_at_end(dispatch)
            for h in s.handlers:
                classes = ["Exception"] if h.type is None else (
                    [h.type.id] if isinstance(h.type, ast.Name)
                    else [el.id for el in h.type.elts if isinstance(el, ast.Name)])
                cond = ir.Constant(I1, 0)
                for c in classes:
                    cp, cl = self._cstr(c)
                    m = self.b.call(self._rt("rt_err_matches"),
                                    [exc, cp, ir.Constant(I64, cl)])
                    cond = self.b.or_(cond, self.b.trunc(m, I1))
                hbody = self.fn.append_basic_block("hnd.body")
                hnext = self.fn.append_basic_block("hnd.next")
                self.b.cbranch(cond, hbody, hnext)
                self.b.position_at_end(hbody)
                self.b.store(ir.Constant(I1, 0), exc_set)
                if h.name:
                    bind = self.bindings[h.name]
                    self._drop_flagged(bind)
                    self._clone_into(self.b, TExc(), exc, bind["ptr"])
                    if bind["flag"] is not None:
                        self.b.store(ir.Constant(I1, 1), bind["flag"])
                self.try_ctx.append({"block": hcatch})
                self.cur_exc.append(exc)
                self._emit_block(h.body)
                self.cur_exc.pop()
                self.try_ctx.pop()
                if not self.b.block.is_terminated:
                    self.b.branch(hjoin)
                self.b.position_at_end(hnext)
            self.b.branch(hjoin)
            b = ir.IRBuilder(hcatch)
            b.call(self._rt("rt_err_take"), [rexc])
            b.store(ir.Constant(I1, 1), rexc_set)
            b.branch(hjoin)
            self.b.position_at_end(hjoin)

        if s.finalbody:
            self._emit_block(s.finalbody)

        for slot, setflag in ((rexc, rexc_set), (exc, exc_set)):
            is_set = self.b.load(setflag)
            bad = self.fn.append_basic_block("reprop")
            cont = self.fn.append_basic_block("cont")
            self.b.cbranch(is_set, bad, cont)
            self.b.position_at_end(bad)
            self.b.call(self._rt("rt_err_reraise"), [slot])
            self._drop(self.b, TExc(), V(TExc(), ptr=slot))
            self._release_borrows(self.b)
            self.b.branch(self._err_target())
            self.b.position_at_end(cont)

    # ---------- loops (for + comprehensions) ----------

    def _emit_for(self, s: ast.For) -> None:
        kind = self.tc.loop_iter_kind.get(id(s), "list")
        targets = [s.target] if isinstance(s.target, ast.Name) else list(s.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        self._loop(s.iter, kind, names, lambda: self._emit_block(s.body))

    def _bind_loop_scalar(self, name: str, t: Type):
        slot = self._entry_alloca(self._lty(t), name=f"v_{name}")
        self.bindings[name] = {"ptr": slot, "ty": t, "ref": False, "flag": None}
        return slot

    def _bind_loop_ref(self, name: str, t: Type):
        slot = self._entry_alloca(self._lty(t).as_pointer(), name=f"v_{name}")
        self.bindings[name] = {"ptr": slot, "ty": t, "ref": True, "flag": None}
        return slot

    def _bind_elem(self, name: str, t: Type, elem_ptr) -> None:
        if isinstance(t, SCALARS):
            self.b.store(self.b.load(elem_ptr), self.bindings[name]["ptr"])
        else:
            self.b.store(elem_ptr, self.bindings[name]["ptr"])

    def _make_loop_binding(self, name: str, t: Type) -> None:
        if isinstance(t, SCALARS):
            self._bind_loop_scalar(name, t)
        else:
            self._bind_loop_ref(name, t)

    def _loop(self, iter_node: ast.expr, kind: str, names: list[str], emit_body) -> None:
        """Shared loop skeleton for for-statements and comprehensions."""
        saved_bindings = dict(self.bindings)
        mark_t = len(self.stmt_temps)
        head = self.fn.append_basic_block("for.head")
        body = self.fn.append_basic_block("for.body")
        incr = self.fn.append_basic_block("for.incr")
        exitc = self.fn.append_basic_block("for.exitc")
        after = self.fn.append_basic_block("for.after")

        idx = self._entry_alloca(I64, "for.idx")
        self.b.store(ir.Constant(I64, 0), idx)
        zero = ir.Constant(I64, 0)
        one = ir.Constant(I64, 1)
        step = one
        bind_elem = None

        if kind == "range":
            assert isinstance(iter_node, ast.Call)
            args = [self._expr(a, "val").ssa for a in iter_node.args]
            if len(args) == 1:
                start, stop = zero, args[0]
            elif len(args) == 2:
                start, stop = args
            else:
                start, stop, step = args
                self._cond_raise_static(
                    self.b.icmp_signed("==", step, zero),
                    "ValueError", "range() arg 3 must not be zero")
            self.b.store(start, idx)
            var = self._bind_loop_scalar(names[0], TInt())

            def cond(b, i):
                pos = b.icmp_signed(">", step, zero)
                return b.select(pos, b.icmp_signed("<", i, stop),
                                b.icmp_signed(">", i, stop))

            def bind_elem(i):
                self.b.store(i, var)
        else:
            if kind in ("keys", "values", "items"):
                assert isinstance(iter_node, ast.Call) \
                    and isinstance(iter_node.func, ast.Attribute)
                seq = self._expr(iter_node.func.value, "ref")
                dt = self._t(iter_node.func.value)
                elem_t = self._elem_of(dt)
            elif kind in ("enumerate", "zip", "reversed"):
                assert isinstance(iter_node, ast.Call)
                seq = self._expr(iter_node.args[0], "ref")
                lt = self._t(iter_node.args[0])
                elem_t = lt.elem if isinstance(lt, TList) else TStr()
                if isinstance(lt, TStr):
                    seq = self._chars_temp(seq)
            elif kind == "str":
                src = self._expr(iter_node, "ref")
                seq = self._chars_temp(src)
                elem_t = TStr()
            else:
                seq = self._expr(iter_node, "ref")
                it_t = self._t(iter_node)
                if isinstance(it_t, TStr):
                    seq = self._chars_temp(seq)
                    elem_t = TStr()
                else:
                    assert isinstance(it_t, TList), f"cannot iterate {it_t}"
                    elem_t = it_t.elem
            n = self._list_len(self.b, seq.ptr)
            seq2 = None
            n2 = None
            if kind == "zip":
                seq2 = self._expr(iter_node.args[1], "ref")
                lt2 = self._t(iter_node.args[1])
                if isinstance(lt2, TStr):
                    seq2 = self._chars_temp(seq2)
                    elem2_t = TStr()
                else:
                    elem2_t = lt2.elem
                n2 = self._list_len(self.b, seq2.ptr)

            if kind == "enumerate":
                ivar = self._bind_loop_scalar(names[0], TInt())
                self._make_loop_binding(names[1], elem_t)
            elif kind == "zip":
                self._make_loop_binding(names[0], elem_t)
                self._make_loop_binding(names[1], elem2_t)
            elif kind == "items":
                self._make_loop_binding(names[0], elem_t.items[0])
                self._make_loop_binding(names[1], elem_t.items[1])
            elif kind == "keys":
                self._make_loop_binding(names[0], elem_t.items[0])
            elif kind == "values":
                self._make_loop_binding(names[0], elem_t.items[1])
            else:
                self._make_loop_binding(names[0], elem_t)

            def cond(b, i):
                c = b.icmp_signed("<", i, n)
                if n2 is not None:
                    c = b.and_(c, b.icmp_signed("<", i, n2))
                return c

            def bind_elem(i):
                j = i
                if kind == "reversed":
                    j = self.b.sub(self.b.sub(n, one), i)
                p = self._elem_ptr(self.b, seq.ptr, elem_t, j)
                if kind == "enumerate":
                    self.b.store(i, ivar)
                    self._bind_elem(names[1], elem_t, p)
                elif kind == "zip":
                    self._bind_elem(names[0], elem_t, p)
                    p2 = self._elem_ptr(self.b, seq2.ptr, elem2_t, j)
                    self._bind_elem(names[1], elem2_t, p2)
                elif kind in ("keys", "values", "items"):
                    kp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
                    vp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                    if kind == "keys":
                        self._bind_elem(names[0], elem_t.items[0], kp)
                    elif kind == "values":
                        self._bind_elem(names[0], elem_t.items[1], vp)
                    else:
                        self._bind_elem(names[0], elem_t.items[0], kp)
                        self._bind_elem(names[1], elem_t.items[1], vp)
                else:
                    self._bind_elem(names[0], elem_t, p)

        # temps created while evaluating the iterable live for the whole loop
        loop_temps = self.stmt_temps[mark_t:]
        del self.stmt_temps[mark_t:]

        self.b.branch(head)
        self.b.position_at_end(head)
        i = self.b.load(idx)
        self.b.cbranch(cond(self.b, i), body, exitc)
        self.b.position_at_end(body)
        bind_elem(i)
        self.loop_stack.append((incr, exitc))
        emit_body()
        self.loop_stack.pop()
        if not self.b.block.is_terminated:
            self.b.branch(incr)
        self.b.position_at_end(incr)
        if kind == "range":
            self.b.store(self.b.add(self.b.load(idx), step), idx)
        else:
            self.b.store(self.b.add(self.b.load(idx), one), idx)
        self.b.branch(head)
        self.b.position_at_end(exitc)
        for v in reversed(loop_temps):
            self._drop(self.b, v.ty, v)
        self.b.branch(after)
        self.b.position_at_end(after)
        self.bindings = saved_bindings

    def _chars_temp(self, strv: V) -> V:
        """Materialize a string's characters as an owned temp list[str]."""
        tmp = self._temp(TList(TStr()))
        self.b.call(self._rt("rt_str_chars"), [strv.ptr, tmp.ptr])
        return tmp

    # ---------- expressions ----------

    def _t(self, node: ast.expr) -> Type:
        t = self.tc.expr_types.get(id(node))
        if t is None:
            raise LLVMUnsupported(f"untyped expression {type(node).__name__}")
        return t

    def _coerce(self, v: V, dst: Type) -> V:
        src = v.ty
        if isinstance(dst, TOptional) and isinstance(src, TNone):
            tmp = self._temp(dst)
            self.b.store(ir.Constant(self._lty(dst), None), tmp.ptr)
            return tmp
        if isinstance(dst, TOptional) and not isinstance(src, (TOptional, TNone)):
            inner = self._coerce(v, dst.inner)
            tmp = self._temp(dst)
            self.b.store(ir.Constant(I1, 1),
                         self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            payload = self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            self._store_into(payload, inner)
            return tmp
        if isinstance(dst, TFloat) and isinstance(src, TInt):
            return V(dst, ssa=self.b.sitofp(v.ssa, F64))
        return v

    def _expr(self, node: ast.expr, mode: str, expect: Type | None = None) -> V:
        if isinstance(node, (ast.ListComp, ast.DictComp)):
            return self._comp_expr(node)
        if isinstance(node, ast.Constant):
            return self._const(node)
        if isinstance(node, ast.Name):
            return self._name(node, mode)
        if isinstance(node, ast.Subscript):
            return self._subscript(node, mode)
        if isinstance(node, ast.List):
            t = self._t(node)
            assert isinstance(t, TList)
            tmp = self._temp(t)
            self.b.store(ir.Constant(SLIST, None), tmp.ptr)
            for e in node.elts:
                ev = self._coerce(self._expr(e, "val", expect=t.elem), t.elem)
                self._list_push(tmp.ptr, t.elem, ev)
            return tmp
        if isinstance(node, ast.Dict):
            t = self._t(node)
            assert isinstance(t, TDict)
            tmp = self._temp(t)
            self.b.store(ir.Constant(SLIST, None), tmp.ptr)
            for k, v in zip(node.keys, node.values):
                assert k is not None
                kv = self._expr(k, "val")
                vv = self._coerce(self._expr(v, "val", expect=t.value), t.value)
                self._dict_set(tmp.ptr, t, kv, vv)
            return tmp
        if isinstance(node, ast.Tuple):
            t = self._t(node)
            assert isinstance(t, TTuple)
            tmp = self._temp(t)
            for i, e in enumerate(node.elts):
                ev = self._coerce(self._expr(e, "val", expect=t.items[i]), t.items[i])
                p = self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                self._store_into(p, ev)
            return tmp
        if isinstance(node, ast.JoinedStr):
            return self._fstring(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node)
        if isinstance(node, ast.BinOp):
            l = self._expr(node.left, "val")
            r = self._expr(node.right, "val")
            return self._binop(node.op, l, r)
        if isinstance(node, ast.BoolOp):
            return self._boolop(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.IfExp):
            return self._ifexp(node)
        if isinstance(node, ast.Call):
            return self._call(node, mode)
        if isinstance(node, ast.Attribute):
            return self._attribute(node, mode)
        if isinstance(node, ast.Lambda):
            raise LLVMUnsupported("bare lambda")
        raise LLVMUnsupported(f"expression {type(node).__name__}")

    def _const(self, node: ast.Constant) -> V:
        v = node.value
        if isinstance(v, bool):
            return V(TBool(), ssa=ir.Constant(I1, int(v)))
        if isinstance(v, int):
            return V(TInt(), ssa=ir.Constant(I64, v))
        if isinstance(v, float):
            return V(TFloat(), ssa=ir.Constant(F64, v))
        if isinstance(v, str):
            tmp = self._temp(TStr())
            p, n = self._cstr(v)
            self.b.call(self._rt("rt_str_new"), [p, ir.Constant(I64, n), tmp.ptr])
            return tmp
        if v is None:
            return V(TNone(), ssa=ir.Constant(I1, 0))
        raise LLVMUnsupported(f"literal {v!r}")

    def _name(self, node: ast.Name, mode: str) -> V:
        name = node.id
        bind = self.bindings.get(name)
        if bind is None:
            const = self.tc.constants.get((self.mod.name, name))
            if const is not None:
                cnode = self.mod.constants[name].value
                assert isinstance(cnode, ast.Constant)
                self.tc.expr_types[id(cnode)] = const
                return self._const(cnode)
            raise LLVMUnsupported(f"unknown name {name}")
        t = bind["ty"]
        ptr = bind["ptr"]
        if bind["ref"]:
            ptr = self.b.load(ptr)
        narrowed = id(node) in self.tc.narrowed_uses
        if narrowed:
            assert isinstance(t, TOptional)
            inner = t.inner
            payload = self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            return self._read_place(inner, payload, mode,
                                    moveable=(bind["flag"] if not bind["ref"] else None))
        return self._read_place(t, ptr, mode,
                                moveable=(bind["flag"] if not bind["ref"] else None))

    def _read_place(self, t: Type, ptr, mode: str, moveable=None) -> V:
        """Read a storage location in the requested mode with Copy/move parity."""
        if mode in ("ref", "mut"):
            if self._is_agg(t):
                return V(t, ptr=ptr)
            return V(t, ssa=self.b.load(ptr), ptr=ptr)
        # mode == 'val'
        if isinstance(t, SCALARS) or isinstance(t, TNone):
            return V(t, ssa=self.b.load(ptr))
        if isinstance(t, (TShared, TWeak)):
            return V(t, ssa=self._clone_scalar(self.b, t, self.b.load(ptr)))
        if isinstance(t, TFile):
            if moveable is not None:
                self.b.store(ir.Constant(I1, 0), moveable)
            return V(t, ssa=self.b.load(ptr), owned=True)
        if needs_clone(t) or t.is_copy():
            tmp = self._temp(t)
            self._clone_into(self.b, t, ptr, tmp.ptr)
            return tmp
        # non-Copy aggregate: a move — copy out and neutralize the source so
        # later drops of the containing place (partial moves) are no-ops
        tmp = self._temp(t)
        self.b.store(self.b.load(ptr), tmp.ptr)
        self.b.store(ir.Constant(self._lty(t), None), ptr)
        if moveable is not None:
            self.b.store(ir.Constant(I1, 0), moveable)
        return tmp

    def _place(self, e: ast.expr, mut: bool):
        """Pointer to an lvalue path (mirrors rustgen._place)."""
        if isinstance(e, ast.Name):
            bind = self.bindings[e.id]
            ptr = bind["ptr"]
            if bind["ref"]:
                ptr = self.b.load(ptr)
            if id(e) in self.tc.narrowed_uses:
                ptr = self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            return ptr
        if isinstance(e, ast.Attribute):
            base_t = self._t(e.value)
            if isinstance(base_t, TShared):
                h = self._expr(e.value, "ref").ssa
                payload = self._borrow(h, mut, base_t.inner)
                return self._field_ptr(payload, base_t.inner, e.attr)
            p = self._field_ptr(self._place(e.value, mut), base_t, e.attr)
            if id(e) in self.tc.narrowed_uses:
                p = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            return p
        if isinstance(e, ast.Subscript):
            base_t = self._t(e.value)
            shared = isinstance(base_t, TShared)
            inner = base_t.inner if shared else base_t
            recv = self._recv(e.value, mut)
            idx = self._expr(e.slice, "val")
            if isinstance(inner, TList):
                j = self._norm_index(recv.ptr, idx.ssa, "list index out of range")
                return self._elem_ptr(self.b, recv.ptr, inner.elem, j)
            assert isinstance(inner, TDict)
            return self._dict_lookup(recv.ptr, inner, idx)
        raise LLVMUnsupported("unsupported place expression")

    def _field_ptr(self, base_ptr, t: TClass, attr: str):
        info = self.tc.classes[(t.module, t.name)]
        i = info.field_order.index(attr)
        return self.b.gep(base_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])

    def _field_type(self, t: TClass, attr: str) -> Type:
        info = self.tc.classes[(t.module, t.name)]
        sub = dict(zip(info.typevars, t.args))
        return subst_type(info.fields[attr], sub)

    def _attribute(self, node: ast.Attribute, mode: str) -> V:
        if isinstance(node.value, ast.Name) and node.value.id == "sys" \
                and self.mod.imports_sys:
            if node.attr == "argv":
                tmp = self._temp(TList(TStr()))
                self.b.call(self._rt("rt_argv"), [tmp.ptr])
                return tmp
            raise LLVMUnsupported(f"sys.{node.attr}")
        t = self._t(node)
        base_t = self._t(node.value)
        narrowed = id(node) in self.tc.narrowed_uses
        if isinstance(base_t, TShared):
            h = self._expr(node.value, "ref").ssa
            payload = self._borrow(h, mode == "mut", base_t.inner)
            p = self._field_ptr(payload, base_t.inner, node.attr)
            ft = self._field_type(base_t.inner, node.attr)
            if narrowed:
                p = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                ft = ft.inner
            return self._read_place(ft, p, mode)
        p = self._field_ptr(self._place(node.value, mut=(mode == "mut")),
                            base_t, node.attr)
        ft = self._field_type(base_t, node.attr)
        if narrowed:
            assert isinstance(ft, TOptional)
            p = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            ft = ft.inner
        return self._read_place(ft, p, mode)

    def _borrow(self, handle, mut: bool, inner: Type):
        """Runtime-borrow a Shared box; released at statement end."""
        bp = self.b.gep(self.b.bitcast(handle, I64.as_pointer()), [ir.Constant(I64, 2)])
        state = self.b.load(bp)
        if mut:
            busy = self.b.icmp_signed("!=", state, ir.Constant(I64, 0))
            self._cond_raise_static(busy, "RuntimeError",
                                    "Shared value is already borrowed")
            self.b.store(ir.Constant(I64, -1), bp)
            self.active_borrows.append((handle, "mut"))
        else:
            busy = self.b.icmp_signed("==", state, ir.Constant(I64, -1))
            self._cond_raise_static(busy, "RuntimeError",
                                    "Shared value is already mutably borrowed")
            self.b.store(self.b.add(self.b.load(bp), ir.Constant(I64, 1)), bp)
            self.active_borrows.append((handle, "ref"))
        return self.b.bitcast(self.b.gep(handle, [ir.Constant(I64, 24)]),
                              self._lty(inner).as_pointer())

    def _recv(self, recv: ast.expr, want_mut: bool) -> V:
        """A method/subscript receiver, borrowing through Shared handles."""
        rt = self._t(recv)
        if isinstance(rt, TShared):
            h = self._expr(recv, "ref").ssa
            payload = self._borrow(h, want_mut, rt.inner)
            return V(rt.inner, ptr=payload)
        return self._expr(recv, "mut" if want_mut else "ref")

    def _norm_index(self, listptr, idx, msg: str):
        """Normalize a (possibly negative) index with an IndexError bounds check."""
        n = self._list_len(self.b, listptr)
        neg = self.b.icmp_signed("<", idx, ir.Constant(I64, 0))
        j = self.b.select(neg, self.b.add(idx, n), idx)
        bad = self.b.or_(self.b.icmp_signed("<", j, ir.Constant(I64, 0)),
                         self.b.icmp_signed(">=", j, n))
        self._cond_raise_static(bad, "IndexError", msg)
        return j

    def _subscript(self, node: ast.Subscript, mode: str) -> V:
        base_t = self._t(node.value)
        inner0 = base_t.inner if isinstance(base_t, TShared) else base_t
        if isinstance(inner0, TStr):
            recv = self._recv(node.value, False)
            if isinstance(node.slice, ast.Slice):
                lo = node.slice.lower
                hi = node.slice.upper
                lov = self._expr(lo, "val").ssa if lo is not None else ir.Constant(I64, 0)
                hiv = self._expr(hi, "val").ssa if hi is not None else ir.Constant(I64, 0)
                tmp = self._temp(TStr())
                self.b.call(self._rt("rt_str_slice"),
                            [recv.ptr, lov, ir.Constant(I8, 1 if lo is not None else 0),
                             hiv, ir.Constant(I8, 1 if hi is not None else 0), tmp.ptr])
                return tmp
            idx = self._expr(node.slice, "val").ssa
            tmp = self._temp(TStr())
            st = self.b.call(self._rt("rt_str_index"), [recv.ptr, idx, tmp.ptr])
            self._check_err_i8(st)
            return tmp
        if isinstance(inner0, TTuple):
            assert isinstance(node.slice, ast.Constant)
            i = node.slice.value
            recv = self._expr(node.value, "ref")
            p = self.b.gep(recv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
            return self._read_place(inner0.items[i], p, mode)
        recv = self._recv(node.value, mode == "mut")
        idx = self._expr(node.slice, "val")
        if isinstance(inner0, TList):
            j = self._norm_index(recv.ptr, idx.ssa, "list index out of range")
            p = self._elem_ptr(self.b, recv.ptr, inner0.elem, j)
            return self._read_place(inner0.elem, p, mode)
        assert isinstance(inner0, TDict)
        p = self._dict_lookup(recv.ptr, inner0, idx)
        return self._read_place(inner0.value, p, mode)

    # ---------- dict primitives (scan-based, insertion-ordered) ----------

    def _dict_scan(self, dictptr, t: TDict, key: V):
        """Return (found i1, value ptr) scanning for key (no error)."""
        elem = self._elem_of(t)
        found = self._entry_alloca(I1)
        vptr = self._entry_alloca(self._lty(t.value).as_pointer())
        self.b.store(ir.Constant(I1, 0), found)
        n = self._list_len(self.b, dictptr)
        idx = self._entry_alloca(I64)
        self.b.store(ir.Constant(I64, 0), idx)
        head = self.fn.append_basic_block("dscan.head")
        loop = self.fn.append_basic_block("dscan.loop")
        hit = self.fn.append_basic_block("dscan.hit")
        done = self.fn.append_basic_block("dscan.done")
        self.b.branch(head)
        self.b.position_at_end(head)
        i = self.b.load(idx)
        self.b.cbranch(self.b.icmp_signed("<", i, n), loop, done)
        self.b.position_at_end(loop)
        p = self._elem_ptr(self.b, dictptr, elem, i)
        kp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
        keq = self._eq_vals(self.b, t.key, self._as_v(self.b, t.key, kp), key)
        self.b.store(self.b.add(i, ir.Constant(I64, 1)), idx)
        self.b.cbranch(keq, hit, head)
        self.b.position_at_end(hit)
        self.b.store(ir.Constant(I1, 1), found)
        self.b.store(self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)]), vptr)
        self.b.branch(done)
        self.b.position_at_end(done)
        return self.b.load(found), self.b.load(vptr)

    def _raise_keyerror(self, t: TDict, key: V) -> None:
        sb = self.b.call(self._rt("rt_sb_new"), [])
        self._push(self.b, t.key, key, sb, as_repr=True)
        msg = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_sb_finish"), [sb, msg])
        kp, kl = self._cstr("KeyError")
        ktmp = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_str_new"), [kp, ir.Constant(I64, kl), ktmp])
        self.b.call(self._rt("rt_raise"), [ktmp, msg])
        self.b.call(self._rt("rt_str_drop"), [ktmp])
        self.b.call(self._rt("rt_str_drop"), [msg])
        self._release_borrows(self.b)
        self.b.branch(self._err_target())

    def _dict_lookup(self, dictptr, t: TDict, key: V):
        """Value pointer for key; raises KeyError when missing."""
        found, vptr = self._dict_scan(dictptr, t, key)
        miss = self.fn.append_basic_block("dget.miss")
        ok = self.fn.append_basic_block("dget.ok")
        self.b.cbranch(found, ok, miss)
        self.b.position_at_end(miss)
        self._raise_keyerror(t, key)
        self.b.position_at_end(ok)
        return vptr

    def _dict_set(self, dictptr, t: TDict, key: V, val: V) -> None:
        """d[k] = v with insertion-order preservation (consumes key and val)."""
        found, vptr = self._dict_scan(dictptr, t, key)
        hit = self.fn.append_basic_block("dset.hit")
        miss = self.fn.append_basic_block("dset.miss")
        done = self.fn.append_basic_block("dset.done")
        self.b.cbranch(found, hit, miss)
        self.b.position_at_end(hit)
        if self._droppable(t.value):
            self._drop(self.b, t.value, self._as_v(self.b, t.value, vptr))
        if self._is_agg(t.value):
            self.b.store(self.b.load(val.ptr), vptr)
        else:
            self.b.store(val.ssa, vptr)
        if self._droppable(t.key):
            self._drop(self.b, t.key, key)
        self.b.branch(done)
        self.b.position_at_end(miss)
        elem = self._elem_of(t)
        n = self._list_len(self.b, dictptr)
        cap = self.b.load(self.b.gep(dictptr, [ir.Constant(I32, 0), ir.Constant(I32, 2)]))
        full = self.b.icmp_signed("==", n, cap)
        with self.b.if_then(full):
            self.b.call(self._rt("rt_list_grow"),
                        [dictptr, ir.Constant(I64, self._sizeof(elem)),
                         self.b.add(n, ir.Constant(I64, 1))])
        p = self._elem_ptr(self.b, dictptr, elem, n)
        kp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
        vp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
        if self._is_agg(t.key):
            self.b.store(self.b.load(key.ptr), kp)
        else:
            self.b.store(key.ssa, kp)
        if self._is_agg(t.value):
            self.b.store(self.b.load(val.ptr), vp)
        else:
            self.b.store(val.ssa, vp)
        self._set_list_len(self.b, dictptr, self.b.add(n, ir.Constant(I64, 1)))
        self.b.branch(done)
        self.b.position_at_end(done)
        self._consume(key)
        self._consume(val)

    def _list_push(self, listptr, elem_t: Type, val: V) -> None:
        """Append an owned value to a list (consumes val)."""
        n = self._list_len(self.b, listptr)
        cap = self.b.load(self.b.gep(listptr, [ir.Constant(I32, 0), ir.Constant(I32, 2)]))
        full = self.b.icmp_signed("==", n, cap)
        with self.b.if_then(full):
            self.b.call(self._rt("rt_list_grow"),
                        [listptr, ir.Constant(I64, self._sizeof(elem_t)),
                         self.b.add(n, ir.Constant(I64, 1))])
        p = self._elem_ptr(self.b, listptr, elem_t, n)
        self._store_into(p, val)
        self._set_list_len(self.b, listptr, self.b.add(n, ir.Constant(I64, 1)))

    # ---------- operators ----------

    def _simple_loop(self, n, body) -> None:
        """for i in 0..n: body(i) — a raw counted loop."""
        idx = self._entry_alloca(I64)
        self.b.store(ir.Constant(I64, 0), idx)
        head = self.fn.append_basic_block("sl.head")
        loop = self.fn.append_basic_block("sl.loop")
        done = self.fn.append_basic_block("sl.done")
        self.b.branch(head)
        self.b.position_at_end(head)
        i = self.b.load(idx)
        self.b.cbranch(self.b.icmp_signed("<", i, n), loop, done)
        self.b.position_at_end(loop)
        body(i)
        self.b.store(self.b.add(i, ir.Constant(I64, 1)), idx)
        self.b.branch(head)
        self.b.position_at_end(done)

    def _checked_arith(self, intrinsic: str, l, r):
        fn = self._intrinsic(f"{intrinsic}.i64",
                             ir.LiteralStructType([I64, I1]), [I64, I64])
        res = self.b.call(fn, [l, r])
        val = self.b.extract_value(res, 0)
        ovf = self.b.extract_value(res, 1)
        self._cond_raise_static(ovf, "OverflowError", OVERFLOW_MSG)
        return val

    def _binop(self, op: ast.operator, l: V, r: V) -> V:
        lt, rt = l.ty, r.ty
        if isinstance(lt, TStr) and isinstance(rt, TStr) and isinstance(op, ast.Add):
            tmp = self._temp(TStr())
            self.b.call(self._rt("rt_str_concat"), [l.ptr, r.ptr, tmp.ptr])
            return tmp
        both_int = isinstance(lt, TInt) and isinstance(rt, TInt)
        zero = ir.Constant(I64, 0)
        if both_int and not isinstance(op, ast.Div):
            if isinstance(op, ast.Add):
                return V(TInt(), ssa=self._checked_arith("llvm.sadd.with.overflow",
                                                         l.ssa, r.ssa))
            if isinstance(op, ast.Sub):
                return V(TInt(), ssa=self._checked_arith("llvm.ssub.with.overflow",
                                                         l.ssa, r.ssa))
            if isinstance(op, ast.Mult):
                return V(TInt(), ssa=self._checked_arith("llvm.smul.with.overflow",
                                                         l.ssa, r.ssa))
            if isinstance(op, (ast.FloorDiv, ast.Mod)):
                self._cond_raise_static(
                    self.b.icmp_signed("==", r.ssa, zero),
                    "ZeroDivisionError", "integer division or modulo by zero")
                minv = ir.Constant(I64, -(2 ** 63))
                ovf = self.b.and_(self.b.icmp_signed("==", l.ssa, minv),
                                  self.b.icmp_signed("==", r.ssa, ir.Constant(I64, -1)))
                self._cond_raise_static(ovf, "OverflowError", OVERFLOW_MSG)
                q = self.b.sdiv(l.ssa, r.ssa)
                rem = self.b.srem(l.ssa, r.ssa)
                nz = self.b.icmp_signed("!=", rem, zero)
                diff = self.b.xor(self.b.icmp_signed("<", l.ssa, zero),
                                  self.b.icmp_signed("<", r.ssa, zero))
                adj = self.b.and_(nz, diff)
                if isinstance(op, ast.FloorDiv):
                    qm1 = self.b.sub(q, ir.Constant(I64, 1))
                    return V(TInt(), ssa=self.b.select(adj, qm1, q))
                remb = self.b.add(rem, r.ssa)
                return V(TInt(), ssa=self.b.select(adj, remb, rem))
            if isinstance(op, ast.Pow):
                return V(TInt(), ssa=self._ipow(l.ssa, r.ssa))
            raise LLVMUnsupported(f"int operator {type(op).__name__}")
        lf = self.b.sitofp(l.ssa, F64) if isinstance(lt, TInt) else l.ssa
        rf = self.b.sitofp(r.ssa, F64) if isinstance(rt, TInt) else r.ssa
        fzero = ir.Constant(F64, 0.0)
        if isinstance(op, ast.Add):
            return V(TFloat(), ssa=self.b.fadd(lf, rf))
        if isinstance(op, ast.Sub):
            return V(TFloat(), ssa=self.b.fsub(lf, rf))
        if isinstance(op, ast.Mult):
            return V(TFloat(), ssa=self.b.fmul(lf, rf))
        if isinstance(op, ast.Div):
            msg = "division by zero" if both_int else "float division by zero"
            self._cond_raise_static(self.b.fcmp_ordered("==", rf, fzero),
                                    "ZeroDivisionError", msg)
            return V(TFloat(), ssa=self.b.fdiv(lf, rf))
        if isinstance(op, (ast.FloorDiv, ast.Mod)):
            out = self._entry_alloca(F64)
            st = self.b.call(self._rt("rt_f64_floormod"),
                             [lf, rf, ir.Constant(I8, 1 if isinstance(op, ast.Mod) else 0),
                              out])
            self._check_err_i8(st)
            return V(TFloat(), ssa=self.b.load(out))
        if isinstance(op, ast.Pow):
            powf = self._intrinsic("llvm.pow.f64", F64, [F64, F64])
            return V(TFloat(), ssa=self.b.call(powf, [lf, rf]))
        raise LLVMUnsupported(f"float operator {type(op).__name__}")

    def _ipow(self, base, exp):
        b = self.b
        zero = ir.Constant(I64, 0)
        self._cond_raise_static(
            b.icmp_signed("<", exp, zero), "OverflowError",
            "Serpentine Tier-0 int ** requires a non-negative exponent")
        res_slot = self._entry_alloca(I64)
        base_slot = self._entry_alloca(I64)
        exp_slot = self._entry_alloca(I64)
        b.store(ir.Constant(I64, 1), res_slot)
        b.store(base, base_slot)
        b.store(exp, exp_slot)
        head = self.fn.append_basic_block("pow.head")
        body = self.fn.append_basic_block("pow.body")
        exit_b = self.fn.append_basic_block("pow.exit")
        b.branch(head)
        b.position_at_end(head)
        e = b.load(exp_slot)
        b.cbranch(b.icmp_signed(">", e, zero), body, exit_b)
        b.position_at_end(body)
        e = b.load(exp_slot)
        odd = b.trunc(b.and_(e, ir.Constant(I64, 1)), I1)
        cur = b.load(res_slot)
        mul = self._checked_arith("llvm.smul.with.overflow", cur, b.load(base_slot))
        b.store(b.select(odd, mul, cur), res_slot)
        e2 = b.ashr(e, ir.Constant(I64, 1))
        b.store(e2, exp_slot)
        sq_needed = b.icmp_signed(">", e2, zero)
        cur_base = b.load(base_slot)
        sq_block = self.fn.append_basic_block("pow.sq")
        cont = self.fn.append_basic_block("pow.cont")
        b.cbranch(sq_needed, sq_block, cont)
        b.position_at_end(sq_block)
        sq = self._checked_arith("llvm.smul.with.overflow", cur_base, cur_base)
        b.store(sq, base_slot)
        b.branch(cont)
        b.position_at_end(cont)
        b.branch(head)
        b.position_at_end(exit_b)
        return b.load(res_slot)

    def _unary(self, node: ast.UnaryOp) -> V:
        t = self._t(node.operand)
        if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            v = node.operand.value
            if isinstance(v, int) and not isinstance(v, bool):
                return V(TInt(), ssa=ir.Constant(I64, -v))
            if isinstance(v, float):
                return V(TFloat(), ssa=ir.Constant(F64, -v))
        v = self._expr(node.operand, "val")
        if isinstance(node.op, ast.Not):
            return V(TBool(), ssa=self.b.not_(v.ssa))
        if isinstance(node.op, ast.USub):
            if isinstance(t, TInt):
                return V(TInt(), ssa=self._checked_arith(
                    "llvm.ssub.with.overflow", ir.Constant(I64, 0), v.ssa))
            return V(TFloat(), ssa=self.b.fneg(v.ssa))
        if isinstance(node.op, ast.UAdd):
            return v
        raise LLVMUnsupported("unary operator")

    def _boolop(self, e: ast.BoolOp) -> V:
        result = self._entry_alloca(I1)
        end = self.fn.append_basic_block("bool.end")
        is_and = isinstance(e.op, ast.And)
        for i, operand in enumerate(e.values):
            mark_t = len(self.stmt_temps)
            mark_b = len(self.active_borrows)
            v = self._expr(operand, "val").ssa
            self.b.store(v, result)
            self._drain(mark_t, mark_b)
            if i == len(e.values) - 1:
                self.b.branch(end)
            else:
                nxt = self.fn.append_basic_block("bool.next")
                if is_and:
                    self.b.cbranch(v, nxt, end)
                else:
                    self.b.cbranch(v, end, nxt)
                self.b.position_at_end(nxt)
        self.b.position_at_end(end)
        return V(TBool(), ssa=self.b.load(result))

    def _cmp_pair(self, op: ast.cmpop, l: V, r: V):
        lt, rt = l.ty, r.ty
        if isinstance(op, (ast.Eq, ast.NotEq)):
            e = self._eq_vals(self.b, lt if not isinstance(lt, TNone) else rt, l, r)
            return self.b.not_(e) if isinstance(op, ast.NotEq) else e
        table = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
        sym = table[type(op)]
        if isinstance(lt, TStr):
            c = self.b.call(self._rt("rt_str_cmp"), [l.ptr, r.ptr])
            return self.b.icmp_signed(sym, c, ir.Constant(I32, 0))
        if isinstance(lt, TTuple):
            cf = self._cmp_fn(lt)
            c = self.b.call(cf, [self.b.bitcast(l.ptr, I8P), self.b.bitcast(r.ptr, I8P)])
            return self.b.icmp_signed(sym, c, ir.Constant(I32, 0))
        if isinstance(lt, TFloat) or isinstance(rt, TFloat):
            lf = self.b.sitofp(l.ssa, F64) if isinstance(lt, TInt) else l.ssa
            rf = self.b.sitofp(r.ssa, F64) if isinstance(rt, TInt) else r.ssa
            return self.b.fcmp_ordered(sym, lf, rf)
        return self.b.icmp_signed(sym, l.ssa, r.ssa)

    def _compare(self, e: ast.Compare) -> V:
        op0 = e.ops[0]
        if isinstance(op0, (ast.Is, ast.IsNot)):
            v = self._expr(e.left, "ref")
            has = self.b.load(self.b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            r = self.b.not_(has) if isinstance(op0, ast.Is) else has
            return V(TBool(), ssa=r)
        if isinstance(op0, (ast.In, ast.NotIn)):
            ct = self._t(e.comparators[0])
            if isinstance(ct, TShared):
                recv = self._recv(e.comparators[0], False)
                ct = ct.inner
            else:
                recv = self._expr(e.comparators[0], "ref")
            needle_t = self._t(e.left)
            needle = self._expr(e.left, "ref" if self._is_agg(needle_t) else "val")
            if isinstance(ct, TStr):
                r = self.b.call(self._rt("rt_str_contains"), [recv.ptr, needle.ptr])
                res = self.b.trunc(r, I1)
            elif isinstance(ct, TDict):
                found, _ = self._dict_scan(recv.ptr, ct, needle)
                res = found
            else:
                assert isinstance(ct, TList)
                elem = ct.elem
                out = self._entry_alloca(I1)
                self.b.store(ir.Constant(I1, 0), out)
                n = self._list_len(self.b, recv.ptr)

                def body(i):
                    p = self._elem_ptr(self.b, recv.ptr, elem, i)
                    eq = self._eq_vals(self.b, elem, self._as_v(self.b, elem, p), needle)
                    self.b.store(self.b.or_(self.b.load(out), eq), out)

                self._simple_loop(n, body)
                res = self.b.load(out)
            if isinstance(op0, ast.NotIn):
                res = self.b.not_(res)
            return V(TBool(), ssa=res)
        operands = [e.left] + list(e.comparators)
        vals = []
        for o in operands:
            t = self._t(o)
            vals.append(self._expr(o, "ref" if self._is_agg(t) else "val"))
        acc = None
        for i, op in enumerate(e.ops):
            c = self._cmp_pair(op, vals[i], vals[i + 1])
            acc = c if acc is None else self.b.and_(acc, c)
        return V(TBool(), ssa=acc)

    def _ifexp(self, node: ast.IfExp) -> V:
        t = self._t(node)
        cond = self._expr(node.test, "val").ssa
        agg = self._is_agg(t)
        if agg:
            out = self._temp(t)
        else:
            out = self._entry_alloca(self._lty(t))
        then_b = self.fn.append_basic_block("tern.then")
        else_b = self.fn.append_basic_block("tern.else")
        end = self.fn.append_basic_block("tern.end")
        self.b.cbranch(cond, then_b, else_b)
        for blk, sub in ((then_b, node.body), (else_b, node.orelse)):
            self.b.position_at_end(blk)
            mark_t = len(self.stmt_temps)
            mark_b = len(self.active_borrows)
            v = self._coerce(self._expr(sub, "val", expect=t), t)
            if agg:
                self._consume(out)          # keep out alive across the drain
                self._store_into(out.ptr, v)
                self._drain(mark_t, mark_b)
                self.stmt_temps.append(out)
            else:
                self.b.store(v.ssa, out)
                self._drain(mark_t, mark_b)
            self.b.branch(end)
        self.b.position_at_end(end)
        if agg:
            return out
        return V(t, ssa=self.b.load(out))

    def _fstring(self, node: ast.JoinedStr) -> V:
        import re
        sb = self.b.call(self._rt("rt_sb_new"), [])
        for part in node.values:
            if isinstance(part, ast.Constant):
                self._push_bytes(self.b, sb, str(part.value))
                continue
            assert isinstance(part, ast.FormattedValue)
            spec = ""
            if part.format_spec is not None:
                assert isinstance(part.format_spec, ast.JoinedStr)
                spec = "".join(str(c.value) for c in part.format_spec.values
                               if isinstance(c, ast.Constant))
            t = self._t(part.value)
            if part.conversion == 114:      # !r
                v = self._expr(part.value, "ref")
                self._push(self.b, t, v, sb, as_repr=True)
            elif spec == "" or spec == "d":
                v = self._expr(part.value, "ref")
                self._push(self.b, t, v, sb, as_repr=False)
            elif re.fullmatch(r"\.(\d+)f", spec):
                v = self._expr(part.value, "val")
                x = v.ssa if isinstance(t, TFloat) else self.b.sitofp(v.ssa, F64)
                self.b.call(self._rt("rt_sb_push_f64_prec"),
                            [sb, x, ir.Constant(I64, int(spec[1:-1]))])
            elif re.fullmatch(r"[<>^]\d+", spec):
                inner_sb = self.b.call(self._rt("rt_sb_new"), [])
                v = self._expr(part.value, "ref")
                self._push(self.b, t, v, sb=inner_sb, as_repr=False)
                tmp = self._entry_alloca(SSTR)
                self.b.call(self._rt("rt_sb_finish"), [inner_sb, tmp])
                self.b.call(self._rt("rt_sb_push_padded"),
                            [sb, tmp, ir.Constant(I8, ord(spec[0])),
                             ir.Constant(I64, int(spec[1:]))])
                self.b.call(self._rt("rt_str_drop"), [tmp])
            else:
                raise LLVMUnsupported(f"f-string format spec '{spec}'")
        out = self._temp(TStr())
        self.b.call(self._rt("rt_sb_finish"), [sb, out.ptr])
        return out

    def _comp_expr(self, node) -> V:
        kind = self.tc.loop_iter_kind[id(node)]
        gen = node.generators[0]
        targets = [gen.target] if isinstance(gen.target, ast.Name) \
            else list(gen.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        t = self._t(node)
        out = self._temp(t)
        self.b.store(ir.Constant(SLIST, None), out.ptr)

        def emit_item():
            mark_t = len(self.stmt_temps)
            mark_b = len(self.active_borrows)
            self._consume(out)
            if isinstance(node, ast.DictComp):
                kv = self._expr(node.key, "val")
                vv = self._coerce(self._expr(node.value, "val", expect=t.value), t.value)
                self._dict_set(out.ptr, t, kv, vv)
            else:
                ev = self._coerce(self._expr(node.elt, "val", expect=t.elem), t.elem)
                self._list_push(out.ptr, t.elem, ev)
            self._drain(mark_t, mark_b)
            self.stmt_temps.append(out)

        def emit_body():
            if gen.ifs:
                mark_t = len(self.stmt_temps)
                mark_b = len(self.active_borrows)
                cond = self._expr(gen.ifs[0], "val").ssa
                self._drain(mark_t, mark_b)
                then_b = self.fn.append_basic_block("comp.then")
                skip = self.fn.append_basic_block("comp.skip")
                self.b.cbranch(cond, then_b, skip)
                self.b.position_at_end(then_b)
                emit_item()
                self.b.branch(skip)
                self.b.position_at_end(skip)
            else:
                emit_item()

        self._loop(gen.iter, kind, names, emit_body)
        return out

    # ---------- calls ----------

    def _call(self, node: ast.Call, mode: str) -> V:
        if isinstance(node.func, ast.Attribute):
            return self._method_call(node)
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if id(node) in self.tc.move_calls:
            return self._expr(node.args[0], mode)
        if id(node) in self.tc.ctor_calls:
            return self._ctor_call(node)
        if name == "share":
            inner = self._t(node).inner
            payload = self._expr(node.args[0], "val", expect=inner)
            h = self.b.call(self._rt("rt_shared_alloc"),
                            [ir.Constant(I64, self._sizeof(inner))])
            p = self.b.bitcast(self.b.gep(h, [ir.Constant(I64, 24)]),
                               self._lty(inner).as_pointer())
            self._store_into(p, payload)
            return self._register_temp_ssa(TShared(inner), h)
        if name == "downgrade":
            s = self._expr(node.args[0], "ref").ssa
            t = self._t(node)
            wp = self.b.gep(self.b.bitcast(s, I64.as_pointer()), [ir.Constant(I64, 1)])
            self.b.store(self.b.add(self.b.load(wp), ir.Constant(I64, 1)), wp)
            return self._register_temp_ssa(t, s)
        if name == "upgrade":
            w = self._expr(node.args[0], "ref").ssa
            t = self._t(node)          # Optional[Shared[T]]
            assert isinstance(t, TOptional)
            out = self._temp(t)
            self.b.store(ir.Constant(self._lty(t), None), out.ptr)
            sp = self.b.bitcast(w, I64.as_pointer())
            alive = self.b.icmp_signed(">", self.b.load(sp), ir.Constant(I64, 0))
            with self.b.if_then(alive):
                self.b.store(self.b.add(self.b.load(sp), ir.Constant(I64, 1)), sp)
                self.b.store(ir.Constant(I1, 1),
                             self.b.gep(out.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                self.b.store(w, self.b.gep(out.ptr,
                                           [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
            return out
        if name == "open":
            path = self._expr(node.args[0], "ref")
            if len(node.args) > 1:
                fmode = self._expr(node.args[1], "ref")
            else:
                fmode = self._const(ast.Constant(value="r"))
                self.tc.expr_types[id(node)] = self._t(node)
            hslot = self._entry_alloca(I8P)
            st = self.b.call(self._rt("rt_file_open"), [path.ptr, fmode.ptr, hslot])
            self._check_err_i8(st)
            return self._register_temp_ssa(TFile(), self.b.load(hslot))
        target = self.tc.call_targets.get(id(node))
        if target is not None:
            return self._user_call(node, self.tc.sigs[target])
        sig = self.tc._resolve_callee(self.mod, name)
        if sig is not None:
            return self._user_call(node, sig)
        return self._builtin(node, name)

    def _ctor_call(self, node: ast.Call) -> V:
        cmod, cname, args = self.tc.ctor_calls[id(node)]
        t = TClass(cmod, cname, args)
        info = self.tc.classes[(cmod, cname)]
        sub = dict(zip(info.typevars, args))
        tmp = self._temp(t)
        for i, (arg, fname) in enumerate(zip(node.args, info.field_order)):
            ft = subst_type(info.fields[fname], sub)
            v = self._coerce(self._expr(arg, "val", expect=ft), ft)
            p = self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
            self._store_into(p, v)
        return tmp

    def _arg_value(self, a: ast.expr, p) -> ir.Value:
        """Evaluate one call argument per the parameter's convention."""
        if p.conv in ("ref", "mut"):
            v = self._expr(a, p.conv)
            if self._is_agg(p.typ):
                return v.ptr
            if v.ptr is not None:
                return v.ptr
            slot = self._entry_alloca(self._lty(p.typ))
            self.b.store(v.ssa, slot)
            return slot
        v = self._coerce(self._expr(a, "val", expect=p.typ), p.typ)
        if self._is_agg(p.typ):
            out = self.b.load(v.ptr)
            self._consume(v)
            return out
        self._consume(v)
        return v.ssa

    def _default_arg(self, p) -> ir.Value:
        c = p.default
        assert isinstance(c, ast.Constant)
        self.tc.expr_types[id(c)] = {bool: TBool(), int: TInt(), float: TFloat(),
                                     str: TStr()}.get(type(c.value), TNone())
        v = self._coerce(self._const(c), p.typ)
        if self._is_agg(p.typ):
            out = self.b.load(v.ptr)
            self._consume(v)
            return out
        self._consume(v)
        return v.ssa

    def _finish_call(self, fn, args, ret: Type) -> V:
        res = self.b.call(fn, args)
        if isinstance(ret, TNone):
            self._check_err(res)
            return V(TNone(), ssa=ir.Constant(I1, 0))
        err = self.b.extract_value(res, 0)
        self._check_err(err)
        val = self.b.extract_value(res, 1)
        if self._is_agg(ret):
            tmp = self._temp(ret)
            self.b.store(val, tmp.ptr)
            return tmp
        if isinstance(ret, (TShared, TWeak, TFile)):
            return self._register_temp_ssa(ret, val)
        return V(ret, ssa=val)

    def _user_call(self, node: ast.Call, sig: FuncSig, self_arg=None) -> V:
        args = [] if self_arg is None else [self_arg]
        params = sig.params[1:] if self_arg is not None else sig.params
        for a, p in zip(node.args, params):
            args.append(self._arg_value(a, p))
        for p in params[len(node.args):]:
            args.append(self._default_arg(p))
        return self._finish_call(self.funcs[(sig.module, sig.name)], args, sig.ret)

    def _method_call(self, node: ast.Call) -> V:
        assert isinstance(node.func, ast.Attribute)
        recv = node.func.value
        method = node.func.attr
        rt = self._t(recv)
        inner = rt.inner if isinstance(rt, TShared) else rt
        args = node.args
        if isinstance(inner, TClass):
            target = self.tc.call_targets[id(node)]
            sig = self.tc.sigs[target]
            conv0 = sig.params[0].conv
            if conv0 == "owned":
                v = self._expr(recv, "val")
                self_arg = self.b.load(v.ptr)
                self._consume(v)
            else:
                self_arg = self._recv(recv, conv0 == "mut").ptr
            return self._user_call(node, sig, self_arg=self_arg)
        if isinstance(inner, TFile):
            h = self._expr(recv, "ref").ssa
            if method == "read":
                tmp = self._temp(TStr())
                st = self.b.call(self._rt("rt_file_read"), [h, tmp.ptr])
                self._check_err_i8(st)
                return tmp
            if method == "write":
                s = self._expr(args[0], "ref")
                out = self._entry_alloca(I64)
                st = self.b.call(self._rt("rt_file_write"), [h, s.ptr, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=self.b.load(out))
            if method == "close":
                self.b.call(self._rt("rt_file_close"), [h])
                return V(TNone(), ssa=ir.Constant(I1, 0))
            raise LLVMUnsupported(f"file method {method}")
        if isinstance(inner, TList):
            return self._list_method(node, rt, inner, method, args)
        if isinstance(inner, TDict):
            return self._dict_method(node, rt, inner, method, args)
        if isinstance(inner, TStr):
            return self._str_method(node, rt, method, args)
        raise LLVMUnsupported(f"method '{method}' on {rt}")

    def _list_method(self, node, rt, t: TList, method: str, args) -> V:
        elem = t.elem
        esize = ir.Constant(I64, self._sizeof(elem))
        none = V(TNone(), ssa=ir.Constant(I1, 0))
        if method == "append":
            v = self._coerce(self._expr(args[0], "val", expect=elem), elem)
            recv = self._recv(node.func.value, True)
            self._list_push(recv.ptr, elem, v)
            return none
        if method == "insert":
            i = self._expr(args[0], "val").ssa
            v = self._coerce(self._expr(args[1], "val", expect=elem), elem)
            recv = self._recv(node.func.value, True)
            n = self._list_len(self.b, recv.ptr)
            neg = self.b.icmp_signed("<", i, ir.Constant(I64, 0))
            j = self.b.select(neg, self.b.add(i, n), i)
            j = self.b.select(self.b.icmp_signed("<", j, ir.Constant(I64, 0)),
                              ir.Constant(I64, 0), j)
            j = self.b.select(self.b.icmp_signed(">", j, n), n, j)
            src = self._entry_alloca(self._lty(elem))
            self._store_into(src, v)
            self.b.call(self._rt("rt_list_insert"),
                        [recv.ptr, esize, j, self.b.bitcast(src, I8P)])
            return none
        if method == "pop":
            recv = self._recv(node.func.value, True)
            n = self._list_len(self.b, recv.ptr)
            empty = self.b.icmp_signed("==", n, ir.Constant(I64, 0))
            self._cond_raise_static(empty, "IndexError", "pop from empty list")
            if args:
                i = self._expr(args[0], "val").ssa
                j = self._norm_index(recv.ptr, i, "pop index out of range")
            else:
                j = self.b.sub(n, ir.Constant(I64, 1))
            p = self._elem_ptr(self.b, recv.ptr, elem, j)
            if self._is_agg(elem):
                out = self._temp(elem)
                self.b.store(self.b.load(p), out.ptr)
            else:
                out = V(elem, ssa=self.b.load(p))
                if isinstance(elem, (TShared, TWeak, TFile)):
                    out = self._register_temp_ssa(elem, out.ssa)
            self.b.call(self._rt("rt_list_remove"), [recv.ptr, esize, j])
            return out
        if method == "extend":
            other = self._expr(args[0], "ref")
            recv = self._recv(node.func.value, True)
            n = self._list_len(self.b, other.ptr)

            def body(i):
                p = self._elem_ptr(self.b, other.ptr, elem, i)
                v = self._read_place(elem, p, "val")
                self._list_push(recv.ptr, elem, v)

            self._simple_loop(n, body)
            return none
        if method == "clear":
            recv = self._recv(node.func.value, True)
            if self._droppable(elem):
                n = self._list_len(self.b, recv.ptr)

                def body(i):
                    p = self._elem_ptr(self.b, recv.ptr, elem, i)
                    self._drop(self.b, elem, self._as_v(self.b, elem, p))

                self._simple_loop(n, body)
            self._set_list_len(self.b, recv.ptr, ir.Constant(I64, 0))
            return none
        if method == "reverse":
            recv = self._recv(node.func.value, True)
            self.b.call(self._rt("rt_list_reverse"), [recv.ptr, esize])
            return none
        if method == "sort":
            recv = self._recv(node.func.value, True)
            self._sort_list(recv.ptr, elem)
            return none
        raise LLVMUnsupported(f"list method {method}")

    def _sort_list(self, listptr, elem: Type) -> None:
        cmp = self._cmp_fn(elem)
        self.b.call(self._rt_sort(), [listptr, ir.Constant(I64, self._sizeof(elem)), cmp])

    def _rt_sort(self) -> ir.Function:
        if "rt_list_sort" not in self.rt:
            fnty = ir.FunctionType(VOID, [SLISTP, I64, CMPFN.as_pointer()])
            self.rt["rt_list_sort"] = ir.Function(self.module, fnty, name="rt_list_sort")
        return self.rt["rt_list_sort"]

    def _dict_method(self, node, rt, t: TDict, method: str, args) -> V:
        if method == "get":
            recv = self._recv(node.func.value, False)
            k = self._expr(args[0], "val")
            found, vptr = self._dict_scan(recv.ptr, t, k)
            out_t = TOptional(t.value)
            out = self._temp(out_t)
            self.b.store(ir.Constant(self._lty(out_t), None), out.ptr)
            with self.b.if_then(found):
                self.b.store(ir.Constant(I1, 1),
                             self.b.gep(out.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                payload = self.b.gep(out.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                self._clone_any(self.b, t.value, vptr, payload)
            if self._droppable(t.key):
                self._drop(self.b, t.key, k)
            self._consume(k)
            return out
        if method == "pop":
            recv = self._recv(node.func.value, True)
            k = self._expr(args[0], "val")
            elem = self._elem_of(t)
            found, vptr = self._dict_scan(recv.ptr, t, k)
            miss = self.fn.append_basic_block("dpop.miss")
            hit = self.fn.append_basic_block("dpop.hit")
            self.b.cbranch(found, hit, miss)
            self.b.position_at_end(miss)
            self._raise_keyerror(t, k)
            self.b.position_at_end(hit)
            # vptr points into the pair; recover the pair pointer to remove it
            out = self._temp(t.value) if self._is_agg(t.value) else None
            n = self._list_len(self.b, recv.ptr)
            idx_out = self._entry_alloca(I64)

            def body(i):
                p = self._elem_ptr(self.b, recv.ptr, elem, i)
                kp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
                keq = self._eq_vals(self.b, t.key, self._as_v(self.b, t.key, kp), k)
                with self.b.if_then(keq):
                    self.b.store(i, idx_out)

            self._simple_loop(n, body)
            j = self.b.load(idx_out)
            p = self._elem_ptr(self.b, recv.ptr, elem, j)
            kp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            vp = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            if out is not None:
                self.b.store(self.b.load(vp), out.ptr)
            else:
                out = V(t.value, ssa=self.b.load(vp))
                if isinstance(t.value, (TShared, TWeak)):
                    out = self._register_temp_ssa(t.value, out.ssa)
            if self._droppable(t.key):
                self._drop(self.b, t.key, self._as_v(self.b, t.key, kp))
            self.b.call(self._rt("rt_list_remove"),
                        [recv.ptr, ir.Constant(I64, self._sizeof(elem)), j])
            if self._droppable(t.key):
                self._drop(self.b, t.key, k)
            self._consume(k)
            return out
        raise LLVMUnsupported(f"dict method {method}")

    STR_RT = {"strip": "rt_str_strip", "lstrip": "rt_str_lstrip", "rstrip": "rt_str_rstrip",
              "upper": "rt_str_upper", "lower": "rt_str_lower", "replace": "rt_str_replace"}

    def _str_method(self, node, rt, method: str, args) -> V:
        recv = self._recv(node.func.value, False)
        if method in self.STR_RT:
            argvs = [self._expr(a, "ref").ptr for a in args]
            tmp = self._temp(TStr())
            self.b.call(self._rt(self.STR_RT[method]), [recv.ptr] + argvs + [tmp.ptr])
            return tmp
        if method in ("startswith", "endswith"):
            a = self._expr(args[0], "ref")
            r = self.b.call(self._rt(f"rt_str_{method}"), [recv.ptr, a.ptr])
            return V(TBool(), ssa=self.b.trunc(r, I1))
        if method == "find":
            a = self._expr(args[0], "ref")
            return V(TInt(), ssa=self.b.call(self._rt("rt_str_find"), [recv.ptr, a.ptr]))
        if method == "split":
            tmp = self._temp(TList(TStr()))
            if args:
                sep = self._expr(args[0], "ref")
                st = self.b.call(self._rt("rt_str_split"), [recv.ptr, sep.ptr, tmp.ptr])
                self._check_err_i8(st)
            else:
                self.b.call(self._rt("rt_str_split_ws"), [recv.ptr, tmp.ptr])
            return tmp
        if method == "join":
            lst = self._expr(args[0], "ref")
            tmp = self._temp(TStr())
            self.b.call(self._rt("rt_str_join"), [recv.ptr, lst.ptr, tmp.ptr])
            return tmp
        raise LLVMUnsupported(f"str method {method}")

    # ---------- builtins ----------

    def _builtin(self, node: ast.Call, name: str) -> V:
        b = self.b
        args = node.args
        if name == "len":
            t = self._t(args[0])
            if isinstance(t, TShared):
                recv = self._recv(args[0], False)
                t = t.inner
            else:
                recv = self._expr(args[0], "ref")
            if isinstance(t, (TList, TDict)):
                return V(TInt(), ssa=self._list_len(b, recv.ptr))
            return V(TInt(), ssa=b.call(self._rt("rt_str_len"), [recv.ptr]))
        if name == "sum":
            t = self._t(args[0])
            assert isinstance(t, TList)
            recv = self._expr(args[0], "ref")
            n = self._list_len(b, recv.ptr)
            acc = self._entry_alloca(self._lty(t.elem))
            b.store(ir.Constant(self._lty(t.elem), 0 if isinstance(t.elem, TInt) else 0.0),
                    acc)

            def body(i):
                p = self._elem_ptr(b, recv.ptr, t.elem, i)
                x = b.load(p)
                if isinstance(t.elem, TInt):
                    b.store(self._checked_arith("llvm.sadd.with.overflow",
                                                b.load(acc), x), acc)
                else:
                    b.store(b.fadd(b.load(acc), x), acc)

            self._simple_loop(n, body)
            return V(t.elem, ssa=b.load(acc))
        if name in ("min", "max"):
            return self._minmax(node, name)
        if name == "abs":
            t = self._t(args[0])
            v = self._expr(args[0], "val")
            if isinstance(t, TInt):
                neg = self._checked_arith("llvm.ssub.with.overflow",
                                          ir.Constant(I64, 0), v.ssa)
                r = b.select(b.icmp_signed("<", v.ssa, ir.Constant(I64, 0)), neg, v.ssa)
                return V(TInt(), ssa=r)
            fabs = self._intrinsic("llvm.fabs.f64", F64, [F64])
            return V(TFloat(), ssa=b.call(fabs, [v.ssa]))
        if name == "str":
            t = self._t(args[0])
            sb = b.call(self._rt("rt_sb_new"), [])
            v = self._expr(args[0], "ref")
            self._push(b, t, v, sb, as_repr=False)
            out = self._temp(TStr())
            b.call(self._rt("rt_sb_finish"), [sb, out.ptr])
            return out
        if name == "int":
            t = self._t(args[0])
            if isinstance(t, TStr):
                v = self._expr(args[0], "ref")
                out = self._entry_alloca(I64)
                st = b.call(self._rt("rt_str_parse_i64"), [v.ptr, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=b.load(out))
            v = self._expr(args[0], "val")
            if isinstance(t, TFloat):
                out = self._entry_alloca(I64)
                st = b.call(self._rt("rt_int_from_f64"), [v.ssa, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=b.load(out))
            if isinstance(t, TBool):
                return V(TInt(), ssa=b.zext(v.ssa, I64))
            return v
        if name == "float":
            t = self._t(args[0])
            if isinstance(t, TStr):
                v = self._expr(args[0], "ref")
                out = self._entry_alloca(F64)
                st = b.call(self._rt("rt_str_parse_f64"), [v.ptr, out])
                self._check_err_i8(st)
                return V(TFloat(), ssa=b.load(out))
            v = self._expr(args[0], "val")
            if isinstance(t, TInt):
                return V(TFloat(), ssa=b.sitofp(v.ssa, F64))
            return v
        if name == "bool":
            t = self._t(args[0])
            if isinstance(t, TStr):
                v = self._expr(args[0], "ref")
                r = b.call(self._rt("rt_str_is_empty"), [v.ptr])
                return V(TBool(), ssa=b.not_(b.trunc(r, I1)))
            v = self._expr(args[0], "val")
            if isinstance(t, TInt):
                return V(TBool(), ssa=b.icmp_signed("!=", v.ssa, ir.Constant(I64, 0)))
            if isinstance(t, TFloat):
                return V(TBool(), ssa=b.fcmp_ordered("!=", v.ssa, ir.Constant(F64, 0.0)))
            return v
        if name == "next":
            assert isinstance(args[0], ast.Name)
            bind = self.bindings[args[0].id]
            it_t = bind["ty"]
            assert isinstance(it_t, TIterObj)
            elem = it_t.elem
            lst = b.load(b.gep(bind["ptr"], [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            ip = b.gep(bind["ptr"], [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            i = b.load(ip)
            n = self._list_len(b, lst)
            done = b.icmp_signed(">=", i, n)
            self._cond_raise_static(done, "StopIteration", "")
            p = self._elem_ptr(b, lst, elem, i)
            b.store(b.add(i, ir.Constant(I64, 1)), ip)
            return self._read_place(elem, p, "val")
        if name == "sorted":
            return self._sorted(node)
        if name == "round":
            t0 = self._t(args[0])
            if isinstance(t0, TInt):
                return self._expr(args[0], "val")
            v = self._expr(args[0], "val")
            if len(args) == 1:
                out = self._entry_alloca(I64)
                st = b.call(self._rt("rt_round0"), [v.ssa, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=b.load(out))
            nv = self._expr(args[1], "val")
            return V(TFloat(), ssa=b.call(self._rt("rt_round_n"), [v.ssa, nv.ssa]))
        if name == "ord":
            v = self._expr(args[0], "ref")
            out = self._entry_alloca(I64)
            st = b.call(self._rt("rt_str_ord"), [v.ptr, out])
            self._check_err_i8(st)
            return V(TInt(), ssa=b.load(out))
        if name == "chr":
            v = self._expr(args[0], "val")
            tmp = self._temp(TStr())
            st = b.call(self._rt("rt_str_chr"), [v.ssa, tmp.ptr])
            self._check_err_i8(st)
            return tmp
        if name == "input":
            tmp = self._temp(TStr())
            st = b.call(self._rt("rt_input"), [tmp.ptr])
            self._check_err_i8(st)
            return tmp
        raise LLVMUnsupported(f"builtin '{name}'")

    def _minmax(self, node: ast.Call, name: str) -> V:
        b = self.b
        args = node.args
        if len(args) == 1:
            t = self._t(args[0])
            assert isinstance(t, TList)
            elem = t.elem
            recv = self._expr(args[0], "ref")
            n = self._list_len(b, recv.ptr)
            empty = b.icmp_signed("==", n, ir.Constant(I64, 0))
            self._cond_raise_static(empty, "ValueError",
                                    f"{name}() iterable argument is empty")
            best = self._entry_alloca(self._lty(elem).as_pointer())
            b.store(self._elem_ptr(b, recv.ptr, elem, ir.Constant(I64, 0)), best)

            def body(i):
                p = self._elem_ptr(b, recv.ptr, elem, i)
                cur = self._as_v(b, elem, p)
                bst = self._as_v(b, elem, b.load(best))
                op = ast.Lt() if name == "min" else ast.Gt()
                better = self._cmp_pair(op, cur, bst)
                with b.if_then(better):
                    b.store(p, best)

            self._simple_loop(n, body)
            return self._read_place(elem, b.load(best), "val")
        lt = self._t(args[0])
        l = self._expr(args[0], "ref" if self._is_agg(lt) else "val")
        r = self._expr(args[1], "ref" if self._is_agg(lt) else "val")
        op = ast.Lt() if name == "min" else ast.Gt()
        pick_r = self._cmp_pair(op, r, l)
        if isinstance(lt, TStr):
            out = self._temp(TStr())
            chosen = b.select(pick_r, r.ptr, l.ptr)
            b.call(self._rt("rt_str_clone"), [chosen, out.ptr])
            return out
        res = b.select(pick_r, r.ssa, l.ssa)
        return V(lt, ssa=res)

    def _sorted(self, node: ast.Call) -> V:
        b = self.b
        t = self._t(node)
        assert isinstance(t, TList)
        elem = t.elem
        seq = self._expr(node.args[0], "ref")
        key = next((kw.value for kw in node.keywords if kw.arg == "key"), None)
        if key is None:
            out = self._temp(t)
            self.b.call(self._clone_fn(t), [seq.ptr, out.ptr])
            self._sort_list(out.ptr, elem)
            return out
        assert isinstance(key, ast.Lambda)
        pname = key.args.args[0].arg
        kt = self._t(key.body)
        pair_t = TTuple((kt, elem))
        pairs = self._temp(TList(pair_t))
        b.store(ir.Constant(SLIST, None), pairs.ptr)
        n = self._list_len(b, seq.ptr)
        saved_bindings = dict(self.bindings)
        pslot = self._bind_loop_ref(pname, elem) if not isinstance(elem, SCALARS) \
            else self._bind_loop_scalar(pname, elem)

        def build(i):
            self._consume(pairs)
            mark_t = len(self.stmt_temps)
            mark_b = len(self.active_borrows)
            ep = self._elem_ptr(b, seq.ptr, elem, i)
            self._bind_elem(pname, elem, ep)
            kv = self._coerce(self._expr(key.body, "val"), kt)
            pv = self._temp(pair_t)
            kp = b.gep(pv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            self._store_into(kp, kv)
            vp = b.gep(pv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            self._clone_any(b, elem, ep, vp)
            self._list_push(pairs.ptr, pair_t, pv)
            self._drain(mark_t, mark_b)
            self.stmt_temps.append(pairs)

        self._simple_loop(n, build)
        self.bindings = saved_bindings

        def keycmp_body(cb, fn):
            ap = cb.bitcast(fn.args[0], self._lty(pair_t).as_pointer())
            cp = cb.bitcast(fn.args[1], self._lty(pair_t).as_pointer())
            ka = cb.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            kc = cb.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            cb.ret(self._cmp_ptrs(cb, kt, ka, kc))

        cmp = self._helper("cmpk", pair_t, [I8P, I8P], I32, keycmp_body)
        b.call(self._rt_sort(), [pairs.ptr, ir.Constant(I64, self._sizeof(pair_t)), cmp])

        out = self._temp(t)
        b.store(ir.Constant(SLIST, None), out.ptr)
        n2 = self._list_len(b, pairs.ptr)

        def extract(i):
            self._consume(out)
            p = self._elem_ptr(b, pairs.ptr, pair_t, i)
            kp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
            vp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            if self._droppable(kt):
                self._drop(b, kt, self._as_v(b, kt, kp))
            if self._is_agg(elem):
                ev = V(elem, ptr=vp, owned=True)
            else:
                ev = V(elem, ssa=b.load(vp), owned=True)
            self._list_push(out.ptr, elem, ev)
            self.stmt_temps.append(out)

        self._simple_loop(n2, extract)
        # pair elements were moved out; free the raw buffer only
        self.b.call(self._rt("rt_list_free"),
                    [pairs.ptr, ir.Constant(I64, self._sizeof(pair_t))])
        self._consume(pairs)
        return out


def generate_llvm(tc: TypeChecker, define_c_main: bool | None = None) -> str:
    """Generate textual LLVM IR for a checked program."""
    import sys
    if define_c_main is None:
        define_c_main = sys.platform != "win32"
    return str(LLVMGen(tc, define_c_main=define_c_main).generate())


def build_llvm_native(tc: TypeChecker, out_path, debug: bool = False,
                      debuginfo: bool = False) -> None:
    """Compile a checked program to a native binary via the LLVM backend."""
    from .llvmbuild import build_native
    build_native(generate_llvm(tc), out_path, debug, debuginfo=debuginfo)


def run_llvm(tc: TypeChecker, debug: bool = True) -> int:
    """AOT-compile to a temp binary and run it (used by `serp llvm`)."""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="serp_llvm_run_") as td:
        exe = Path(td) / ("prog.exe" if sys.platform == "win32" else "prog")
        build_llvm_native(tc, exe, debug=debug)
        proc = subprocess.run([str(exe)])
        return proc.returncode
