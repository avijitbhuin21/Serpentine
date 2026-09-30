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
import re

from llvmlite import ir

from .frontend import Module, exc_handler_names
from .ptypes import (NONE, Type, TBool, TByteArray, TBytes, TClass, TDict, TEnum, TExc, TFile,
                     TFloat,
                     TFunc, TInt, TJoin, TList, TNone, TOptional, TPyVal, TSet, TShared, TStr, TThread,
                     TTuple, TUnion, TWeak, mangle_type, subst_type, union_slot, walk_types)
from .typecheck import FuncSig, Param, TIterObj, TypeChecker

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
SFUNC = ir.LiteralStructType([I8P, I8P])          # closure {fn, env}
DTORTY = ir.FunctionType(VOID, [I8P])             # closure-env destructor

OVERFLOW_MSG = "Serpentine int operation overflowed 64 bits"

SCALARS = (TInt, TFloat, TBool, TEnum)


def _tykey(t: Type) -> str:
    """A mangling key that keeps same-named classes from different modules apart."""
    parts = [mangle_type(t)]
    for s in walk_types(t):
        if isinstance(s, (TClass, TEnum)):
            parts.append(f"{s.module}_{s.name}")
    return re.sub(r"[^A-Za-z0-9]+", "_", "__".join(parts)).strip("_")


class LLVMUnsupported(Exception):
    """The program uses a feature Backend B cannot lower (should not happen for
    checker-accepted programs; kept as a safety valve)."""


def needs_clone(t: Type) -> bool:
    """Copy-semantics types whose copies are not bitwise (mirror rustgen)."""
    if isinstance(t, (TStr, TShared, TWeak, TExc, TFunc, TBytes, TPyVal)):
        return True
    if isinstance(t, TTuple):
        return any(needs_clone(i) for i in t.items)
    if isinstance(t, TOptional):
        return needs_clone(t.inner)
    if isinstance(t, TUnion):
        return any(needs_clone(m) for m in t.members)
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
    "rt_buf_alloc": (I8P, [I64]),
    "rt_buf_free": (VOID, [I8P, I64]),
    "rt_str_send": (I8P, [SSTRP]),
    "rt_str_recv": (VOID, [I8P, SSTRP]),
    "rt_bytes_send": (I8P, [I8P]),
    "rt_bytes_recv": (I8P, [I8P]),
    "rt_box_ok": (I8P, [I64]),
    "rt_box_err": (I8P, []),
    "rt_thread_spawn": (I8P, [I8P, I8P]),
    "rt_thread_join": (I8, [I8P, I64.as_pointer()]),
    "rt_thread_drop": (VOID, [I8P]),
    "rt_task_spawn": (I8P, [I8P, I8P]),
    "rt_task_await": (I8, [I8P, I64.as_pointer()]),
    "rt_task_done": (I8, [I8P]),
    "rt_task_drop": (VOID, [I8P]),
    "rt_aio_sleep": (I8, [F64]),
    "rt_aio_current": (I64, []),
    "rt_aio_park": (I8, []),
    "rt_aio_wake": (I8, [I64]),
    "rt_aio_wait_fd": (I8, [I64, I64, I64, I8.as_pointer()]),
    "rt_aio_running": (I8, []),
    "rt_aio_ev_new": (I64, []),
    "rt_aio_ev_set": (I8, [I64]),
    "rt_aio_ev_clear": (I8, [I64]),
    "rt_aio_ev_is_set": (I8, [I64, I8.as_pointer()]),
    "rt_aio_ev_wait": (I8, [I64, I8.as_pointer()]),
    "rt_aio_lock_new": (I64, []),
    "rt_aio_lock_acquire": (I8, [I64, I8.as_pointer()]),
    "rt_aio_lock_release": (I8, [I64]),
    "rt_aio_lock_locked": (I8, [I64, I8.as_pointer()]),
    "rt_aio_sem_new": (I8, [I64, I64.as_pointer()]),
    "rt_aio_sem_acquire": (I8, [I64, I8.as_pointer()]),
    "rt_aio_sem_release": (I8, [I64, I64, I64]),
    "rt_aio_sem_locked": (I8, [I64, I8.as_pointer()]),
    "rt_aio_sem_value": (I8, [I64, I64.as_pointer()]),
    "rt_aio_q_new": (I64, [I64]),
    "rt_aio_q_put": (I8, [I64, I8P, I64, I8.as_pointer()]),
    "rt_aio_q_get": (I8, [I64, I64, I8.as_pointer()]),
    "rt_aio_q_qsize": (I8, [I64, I64.as_pointer()]),
    "rt_aio_q_maxsize": (I8, [I64, I64.as_pointer()]),
    "rt_aio_q_task_done": (I8, [I64]),
    "rt_aio_q_join": (I8, [I64]),
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
    "rt_math_sqrt": (I8, [F64, F64.as_pointer()]),
    "rt_math_sin": (F64, [F64]),
    "rt_math_cos": (F64, [F64]),
    "rt_math_tan": (F64, [F64]),
    "rt_math_log": (I8, [F64, F64.as_pointer()]),
    "rt_math_exp": (I8, [F64, F64.as_pointer()]),
    "rt_math_pow": (I8, [F64, F64, F64.as_pointer()]),
    "rt_math_floor": (I8, [F64, I64.as_pointer()]),
    "rt_math_ceil": (I8, [F64, I64.as_pointer()]),
    "rt_math_isnan": (I8, [F64]),
    "rt_math_isinf": (I8, [F64]),
    "rt_math_isfinite": (I8, [F64]),
    "rt_math_acos": (I8, [F64, F64.as_pointer()]),
    "rt_math_asin": (I8, [F64, F64.as_pointer()]),
    "rt_math_atan": (F64, [F64]),
    "rt_math_atan2": (F64, [F64, F64]),
    "rt_math_acosh": (I8, [F64, F64.as_pointer()]),
    "rt_math_asinh": (F64, [F64]),
    "rt_math_atanh": (I8, [F64, F64.as_pointer()]),
    "rt_math_cosh": (I8, [F64, F64.as_pointer()]),
    "rt_math_sinh": (I8, [F64, F64.as_pointer()]),
    "rt_math_tanh": (F64, [F64]),
    "rt_math_cbrt": (F64, [F64]),
    "rt_math_degrees": (F64, [F64]),
    "rt_math_radians": (F64, [F64]),
    "rt_math_exp2": (I8, [F64, F64.as_pointer()]),
    "rt_math_expm1": (I8, [F64, F64.as_pointer()]),
    "rt_math_fabs": (F64, [F64]),
    "rt_math_log10": (I8, [F64, F64.as_pointer()]),
    "rt_math_log2": (I8, [F64, F64.as_pointer()]),
    "rt_math_log1p": (I8, [F64, F64.as_pointer()]),
    "rt_math_copysign": (F64, [F64, F64]),
    "rt_math_fmod": (I8, [F64, F64, F64.as_pointer()]),
    "rt_math_ldexp": (I8, [F64, I64, F64.as_pointer()]),
    "rt_math_trunc": (I8, [F64, I64.as_pointer()]),
    "rt_math_hypot": (F64, [F64, F64]),
    "rt_math_nextafter": (F64, [F64, F64]),
    "rt_math_ulp": (F64, [F64]),
    "rt_math_factorial": (I8, [I64, I64.as_pointer()]),
    "rt_math_gcd": (I8, [I64, I64, I64.as_pointer()]),
    "rt_math_lcm": (I8, [I64, I64, I64.as_pointer()]),
    "rt_math_isqrt": (I8, [I64, I64.as_pointer()]),
    "rt_math_comb": (I8, [I64, I64, I64.as_pointer()]),
    "rt_math_perm": (I8, [I64, I64, I64.as_pointer()]),
    "rt_math_frexp_m": (F64, [F64]),
    "rt_math_frexp_e": (I64, [F64]),
    "rt_math_modf_frac": (F64, [F64]),
    "rt_math_modf_int": (F64, [F64]),
    "rt_rand_seed": (VOID, [I64]),
    "rt_rand_seed_sys": (VOID, []),
    "rt_rand_random": (F64, []),
    "rt_rand_getrandbits": (I8, [I64, I64.as_pointer()]),
    "rt_rand_randbelow": (I64, [I64]),
    "rt_time_time": (F64, []),
    "rt_time_monotonic": (F64, []),
    "rt_time_sleep": (I8, [F64]),
    "rt_time_time_ns": (I64, []),
    "rt_time_monotonic_ns": (I64, []),
    "rt_time_perf_counter": (F64, []),
    "rt_time_perf_counter_ns": (I64, []),
    "rt_os_getenv": (VOID, [SSTRP, SSTRP]),
    "rt_log_set": (VOID, [SSTRP, SSTRP]),
    "rt_log_get": (VOID, [SSTRP, SSTRP]),
    "rt_log_write_err": (VOID, [SSTRP]),
    "rt_os_has_env": (I8, [SSTRP]),
    "rt_os_setenv": (I8, [SSTRP, SSTRP]),
    "rt_os_unsetenv": (I8, [SSTRP]),
    "rt_os_getcwd": (I8, [SSTRP]),
    "rt_os_chdir": (I8, [SSTRP]),
    "rt_os_exists": (I8, [SSTRP]),
    "rt_os_is_file": (I8, [SSTRP]),
    "rt_os_is_dir": (I8, [SSTRP]),
    "rt_os_mkdir": (I8, [SSTRP]),
    "rt_os_rmdir": (I8, [SSTRP]),
    "rt_os_remove": (I8, [SSTRP]),
    "rt_os_listdir": (I8, [SSTRP, SLISTP]),
    "rt_hash_sha256": (VOID, [SSTRP, SSTRP]),
    "rt_hash_sha1": (VOID, [SSTRP, SSTRP]),
    "rt_hash_md5": (VOID, [SSTRP, SSTRP]),
    "rt_hash_sha256_y": (VOID, [I8P, SSTRP]),
    "rt_hash_sha1_y": (VOID, [I8P, SSTRP]),
    "rt_hash_md5_y": (VOID, [I8P, SSTRP]),
    "rt_uuid4": (VOID, [SSTRP]),
    "rt_secrets_token_hex": (I8, [I64, SSTRP]),
    "rt_secrets_randbits": (I8, [I64, I64.as_pointer()]),
    "rt_secrets_token_bytes": (I8, [I64, I8P.as_pointer()]),
    "rt_secrets_token_urlsafe": (I8, [I64, SSTRP]),
    "rt_secrets_randbelow": (I8, [I64, I64.as_pointer()]),
    "rt_zlib_crc32": (I64, [I8P]),
    "rt_zlib_crc32_seeded": (I64, [I8P, I64]),
    "rt_zlib_adler32_seeded": (I64, [I8P, I64]),
    "rt_zlib_adler32": (I64, [I8P]),
    "rt_zlib_compress": (I8, [I8P, I64, I8P.as_pointer()]),
    "rt_zlib_decompress": (I8, [I8P, I8P.as_pointer()]),
    "rt_zlib_deflate": (I8, [I8P, I64, I8P.as_pointer()]),
    "rt_zlib_inflate": (I8, [I8P, I8P.as_pointer()]),
    "rt_zlib_gzip_compress": (I8, [I8P, I64, I8P.as_pointer()]),
    "rt_zlib_gzip_decompress": (I8, [I8P, I8P.as_pointer()]),
    "rt_sqlite_open": (I8, [SSTRP, I64.as_pointer()]),
    "rt_sqlite_close": (I8, [I64]),
    "rt_sqlite_execute": (I8, [I64, SSTRP]),
    "rt_sqlite_changes": (I8, [I64, I64.as_pointer()]),
    "rt_sqlite_last_rowid": (I8, [I64, I64.as_pointer()]),
    "rt_sqlite_prepare": (I8, [I64, SSTRP, I64.as_pointer()]),
    "rt_sqlite_bind_int": (I8, [I64, I64, I64]),
    "rt_sqlite_bind_float": (I8, [I64, I64, F64]),
    "rt_sqlite_bind_text": (I8, [I64, I64, SSTRP]),
    "rt_sqlite_bind_blob": (I8, [I64, I64, I8P]),
    "rt_sqlite_bind_null": (I8, [I64, I64]),
    "rt_sqlite_step": (I8, [I64, I8.as_pointer()]),
    "rt_sqlite_column_count": (I8, [I64, I64.as_pointer()]),
    "rt_sqlite_col_type": (I8, [I64, I64, I64.as_pointer()]),
    "rt_sqlite_col_int": (I8, [I64, I64, I64.as_pointer()]),
    "rt_sqlite_col_float": (I8, [I64, I64, F64.as_pointer()]),
    "rt_sqlite_col_text": (I8, [I64, I64, SSTRP]),
    "rt_sqlite_col_blob": (I8, [I64, I64, I8P.as_pointer()]),
    "rt_sqlite_reset": (I8, [I64]),
    "rt_sqlite_finalize": (I8, [I64]),
    "rt_sp_spawn": (I8, [SSTRP, SSTRP, SSTRP, I64, I64.as_pointer()]),
    "rt_sp_pid": (I8, [I64, I64.as_pointer()]),
    "rt_sp_communicate": (I8, [I64, I8P, I64, I64, I8.as_pointer()]),
    "rt_sp_wait": (I8, [I64, I64, I8.as_pointer()]),
    "rt_sp_poll": (I8, [I64, I8.as_pointer()]),
    "rt_sp_returncode": (I8, [I64, I64.as_pointer()]),
    "rt_sp_stdout": (I8, [I64, I8P.as_pointer()]),
    "rt_sp_stderr": (I8, [I64, I8P.as_pointer()]),
    "rt_sp_kill": (I8, [I64]),
    "rt_sp_terminate": (I8, [I64]),
    "rt_sp_free": (I8, [I64]),
    "rt_thread_new": (I8P, [I8P, I8P, SSTRP, I64, I8, I64, SSTRP]),
    "rt_thread_start": (I8, [I8P]),
    "rt_thread_join_t": (I8, [I8P, I64]),
    "rt_thread_alive": (I8, [I8P]),
    "rt_thread_name": (VOID, [I8P, SSTRP]),
    "rt_thread_set_name": (VOID, [I8P, SSTRP]),
    "rt_thread_ident": (I64, [I8P]),
    "rt_thread_daemon": (I8, [I8P]),
    "rt_thread_cancel": (VOID, [I8P]),
    "rt_thread_free": (VOID, [I8P]),
    "rt_threads_join_all": (VOID, []),
    "rt_th_ident": (I64, []),
    "rt_th_name": (VOID, [SSTRP]),
    "rt_th_active_count": (I64, []),
    "rt_th_main_ident": (I64, []),
    "rt_tls_set": (VOID, [SSTRP, I8P]),
    "rt_tls_get": (VOID, [SSTRP, I8P.as_pointer()]),
    "rt_tls_has": (I8, [SSTRP]),
    "rt_tls_del": (I8, [SSTRP]),
    "rt_lock_new": (I64, []),
    "rt_lock_acquire": (I8, [I64, I64, I64, I8.as_pointer()]),
    "rt_lock_release": (I8, [I64, I64]),
    "rt_lock_locked": (I8, [I64, I8.as_pointer()]),
    "rt_lock_owned": (I8, [I64, I8.as_pointer()]),
    "rt_event_new": (I64, []),
    "rt_event_set": (I8, [I64]),
    "rt_event_clear": (I8, [I64]),
    "rt_event_is_set": (I8, [I64, I8.as_pointer()]),
    "rt_event_wait": (I8, [I64, I64, I8.as_pointer()]),
    "rt_sem_new": (I8, [I64, I64.as_pointer()]),
    "rt_sem_acquire": (I8, [I64, I64, I8.as_pointer()]),
    "rt_sem_release": (I8, [I64, I64]),
    "rt_sem_value": (I8, [I64, I64.as_pointer()]),
    "rt_cond_new": (I64, []),
    "rt_cond_wait": (I8, [I64, I64, I64, I8.as_pointer()]),
    "rt_cond_notify": (I8, [I64, I64]),
    "rt_barrier_new": (I8, [I64, I64.as_pointer()]),
    "rt_barrier_wait": (I8, [I64, I64, I64.as_pointer()]),
    "rt_barrier_reset": (I8, [I64]),
    "rt_barrier_abort": (I8, [I64]),
    "rt_barrier_parties": (I8, [I64, I64.as_pointer()]),
    "rt_barrier_n_waiting": (I8, [I64, I64.as_pointer()]),
    "rt_barrier_broken": (I8, [I64, I8.as_pointer()]),
    "rt_q_new": (I64, [I64, I64]),
    "rt_q_put": (I8, [I64, I8P, I64, I64, I8.as_pointer()]),
    "rt_q_get": (I8, [I64, I64, I64, I8.as_pointer()]),
    "rt_q_last": (VOID, [I8P.as_pointer()]),
    "rt_q_qsize": (I8, [I64, I64.as_pointer()]),
    "rt_q_task_done": (I8, [I64]),
    "rt_q_join": (I8, [I64]),
    "rt_sock_connect": (I8, [SSTRP, I64, I64, I64.as_pointer()]),
    "rt_sock_tls_connect": (I8, [SSTRP, I64, I64, I64, I64.as_pointer()]),
    "rt_sock_listen": (I8, [SSTRP, I64, I64.as_pointer()]),
    "rt_sock_accept": (I8, [I64, I64.as_pointer()]),
    "rt_sock_send": (I8, [I64, I8P, I64.as_pointer()]),
    "rt_sock_send_all": (I8, [I64, I8P, I64, I64.as_pointer()]),
    "rt_sock_recv": (I8, [I64, I64, I8P.as_pointer()]),
    "rt_sock_shutdown_write": (I8, [I64]),
    "rt_sock_set_timeout": (I8, [I64, I64]),
    "rt_sock_set_nonblocking": (I8, [I64]),
    "rt_sock_set_async": (I8, [I64]),
    "rt_sock_accept_nb": (I8, [I64, I64.as_pointer()]),
    "rt_sock_poll_ready": (I8, [I8P, I64, I8P.as_pointer()]),
    "rt_sock_local_port": (I8, [I64, I64.as_pointer()]),
    "rt_sock_close": (I8, [I64]),
    "rt_sock_udp_bind": (I8, [SSTRP, I64, I64.as_pointer()]),
    "rt_sock_udp_send_to": (I8, [I64, I8P, SSTRP, I64, I64.as_pointer()]),
    "rt_sock_udp_recv_from": (I8, [I64, I64, I8P.as_pointer()]),
    "rt_sock_udp_peer_host": (I8, [I64, SSTRP]),
    "rt_sock_udp_peer_port": (I8, [I64, I64.as_pointer()]),
    "rt_bytes_new": (I8P, [I8P, I64]),
    "rt_pyval_none": (I8P, []),
    "rt_pyval_bool": (I8P, [I8]),
    "rt_pyval_int": (I8P, [I64]),
    "rt_pyval_float": (I8P, [F64]),
    "rt_pyval_str": (I8P, [SSTRP]),
    "rt_pyval_bytes": (I8P, [I8P]),
    "rt_pyval_list_new": (I8P, []),
    "rt_pyval_list_push": (VOID, [I8P, I8P]),
    "rt_pyval_dict_new": (I8P, []),
        "rt_pyval_dict_set": (VOID, [I8P, SSTRP, I8P]),
        "rt_pyval_dict_set_pv": (VOID, [I8P, I8P, I8P]),
    "rt_pyval_clone": (VOID, [I8P]),
    "rt_pyval_drop": (VOID, [I8P]),
    "rt_pyval_kind": (VOID, [I8P, SSTRP]),
    "rt_pyval_json": (I8, [I8P, I8, I8, SSTRP]),
    "rt_pyval_truthy": (I8, [I8P]),
    "rt_pyval_eq": (I8, [I8P, I8P]),
    "rt_pyval_len": (I8, [I8P, I64.as_pointer()]),
    "rt_pyval_getitem_i": (I8, [I8P, I64, I8P.as_pointer()]),
    "rt_pyval_getitem_s": (I8, [I8P, SSTRP, I8P.as_pointer()]),
    "rt_pyval_getitem_v": (I8, [I8P, I8P, I8P.as_pointer()]),
    "rt_pyval_contains": (I8, [I8P, I8P, I8.as_pointer()]),
    "rt_pyval_iter": (I8, [I8P, SLISTP]),
    "rt_pyval_to_int": (I8, [I8P, I64.as_pointer()]),
    "rt_pyval_to_float": (I8, [I8P, F64.as_pointer()]),
    "rt_pyval_to_bytes": (I8, [I8P, I8P.as_pointer()]),
    "rt_pyval_str_of": (VOID, [I8P, SSTRP]),
    "rt_pyval_repr": (VOID, [I8P, SSTRP]),
    "rt_bytes_clone": (VOID, [I8P]),
    "rt_bytes_drop": (VOID, [I8P]),
    "rt_bytes_len": (I64, [I8P]),
    "rt_bytes_index": (I8, [I8P, I64, I64.as_pointer()]),
    "rt_bytes_slice": (I8P, [I8P, I64, I8, I64, I8]),
    "rt_bytes_concat": (I8P, [I8P, I8P]),
    "rt_bytes_repeat": (I8P, [I8P, I64]),
    "rt_bytes_eq": (I8, [I8P, I8P]),
    "rt_bytes_cmp": (I32, [I8P, I8P]),
    "rt_bytes_contains": (I8, [I8P, I8P]),
    "rt_bytes_find": (I64, [I8P, I8P]),
    "rt_bytes_count": (I64, [I8P, I8P]),
    "rt_bytes_startswith": (I8, [I8P, I8P]),
    "rt_bytes_endswith": (I8, [I8P, I8P]),
    "rt_bytes_replace": (I8P, [I8P, I8P, I8P]),
    "rt_bytes_strip": (I8P, [I8P]),
    "rt_bytes_lstrip": (I8P, [I8P]),
    "rt_bytes_rstrip": (I8P, [I8P]),
    "rt_bytes_upper": (I8P, [I8P]),
    "rt_bytes_lower": (I8P, [I8P]),
    "rt_bytes_hex": (VOID, [I8P, SSTRP]),
    "rt_bytes_decode": (I8, [I8P, SSTRP]),
    "rt_bytes_fromhex": (I8, [SSTRP, I8P.as_pointer()]),
    "rt_str_encode": (I8P, [SSTRP]),
    "rt_bytes_from_ints": (I8, [SLISTP, I8P.as_pointer()]),
    "rt_bytes_zeros": (I8, [I64, I8P.as_pointer()]),
    "rt_bytes_split": (I8, [I8P, I8P, SLISTP]),
    "rt_bytes_split_ws": (VOID, [I8P, SLISTP]),
    "rt_bytes_join": (I8P, [I8P, SLISTP]),
    "rt_bytes_ints": (VOID, [I8P, SLISTP]),
    "rt_bytes_repr": (VOID, [I8P, SSTRP]),
    "rt_ba_push": (I8, [SLISTP, I64]),
    "rt_ba_extend_b": (VOID, [SLISTP, I8P]),
    "rt_ba_extend_a": (VOID, [SLISTP, SLISTP]),
    "rt_ba_get": (I8, [SLISTP, I64, I64.as_pointer()]),
    "rt_ba_set": (I8, [SLISTP, I64, I64]),
    "rt_ba_slice": (VOID, [SLISTP, I64, I8, I64, I8, SLISTP]),
    "rt_ba_to_bytes": (I8P, [SLISTP]),
    "rt_ba_from_bytes": (VOID, [I8P, SLISTP]),
    "rt_ba_from_ints": (I8, [SLISTP, SLISTP]),
    "rt_ba_zeros": (I8, [I64, SLISTP]),
    "rt_ba_eq": (I8, [SLISTP, SLISTP]),
    "rt_ba_clone": (VOID, [SLISTP, SLISTP]),
    "rt_ba_hex": (VOID, [SLISTP, SSTRP]),
    "rt_ba_decode": (I8, [SLISTP, SSTRP]),
    "rt_ba_repr": (VOID, [SLISTP, SSTRP]),
    "rt_ba_ints": (VOID, [SLISTP, SLISTP]),
    "rt_file_read_bytes": (I8, [I8P, I8P.as_pointer()]),
    "rt_file_write_bytes": (I8, [I8P, I8P, I64.as_pointer()]),
    "rt_file_write_ba": (I8, [I8P, SLISTP, I64.as_pointer()]),
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
        self.pending_lambdas: list[dict] = []
        self.thread_wrappers: dict = {}
        self.lambda_counter = 0
        self.thunks: dict[tuple, ir.Function] = {}
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

    def _cbytes(self, data: bytes):
        """(i8* pointer constant, byte length) of an interned raw-bytes constant."""
        key = "\x00bytes:" + data.hex()
        if key not in self.strings:
            ty = ir.ArrayType(I8, max(len(data), 1))
            gv = ir.GlobalVariable(self.module, ty, name=f".bytes{len(self.strings)}")
            gv.linkage = "internal"
            gv.global_constant = True
            gv.initializer = ir.Constant(ty, bytearray(data) if data else bytearray(b"\x00"))
            self.strings[key] = gv
        gv = self.strings[key]
        p = gv.gep([ir.Constant(I32, 0), ir.Constant(I32, 0)])
        return p, len(data)

    def _lty(self, t: Type) -> ir.Type:
        """LLVM storage type for a Serpentine type."""
        if isinstance(t, TInt):
            return I64
        if isinstance(t, TEnum):
            return I64                                 # member ordinal
        if isinstance(t, TFloat):
            return F64
        if isinstance(t, TBool):
            return I1
        if isinstance(t, TNone):
            return I1                                  # dummy zero-ish slot
        if isinstance(t, TStr):
            return SSTR
        if isinstance(t, (TList, TDict, TSet)):
            return SLIST
        if isinstance(t, TTuple):
            return ir.LiteralStructType([self._lty(i) for i in t.items])
        if isinstance(t, TOptional):
            return ir.LiteralStructType([I1, self._lty(t.inner)])
        if isinstance(t, TUnion):
            return ir.LiteralStructType([I8] + [self._lty(m) for m in t.members])
        if isinstance(t, TClass):
            key = _tykey(t)
            if key not in self.class_types:
                info = self.tc.classes[(t.module, t.name)]
                sub = dict(zip(info.typevars, t.args))
                self.class_types[key] = ir.LiteralStructType(
                    [self._lty(subst_type(info.fields[f], sub)) for f in info.field_order])
            return self.class_types[key]
        if isinstance(t, (TShared, TWeak, TFile, TBytes, TPyVal, TJoin, TThread)):
            return I8P
        if isinstance(t, TByteArray):
            return SLIST
        if isinstance(t, TExc):
            return SERR
        if isinstance(t, TFunc):
            return SFUNC
        if isinstance(t, TIterObj):
            return ir.LiteralStructType([SLISTP, I64])
        raise LLVMUnsupported(f"no LLVM type for {t}")

    def _is_agg(self, t: Type) -> bool:
        return isinstance(t, (TStr, TList, TDict, TSet, TTuple, TOptional, TClass, TExc,
                              TIterObj, TFunc, TByteArray, TUnion))

    def _sizeof(self, t: Type) -> int:
        key = _tykey(t)
        if key not in self._size_cache:
            self._size_cache[key] = self._lty(t).get_abi_size(self.td)
        return self._size_cache[key]

    def _droppable(self, t: Type) -> bool:
        if isinstance(t, (TStr, TList, TDict, TSet, TShared, TWeak, TExc, TFile, TFunc,
                          TBytes, TByteArray, TPyVal, TJoin, TThread)):
            return True
        if isinstance(t, TTuple):
            return any(self._droppable(i) for i in t.items)
        if isinstance(t, TOptional):
            return self._droppable(t.inner)
        if isinstance(t, TUnion):
            return any(self._droppable(m) for m in t.members)
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
        if isinstance(t, TSet):
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
        key = (kind, _tykey(t))
        if key in self.helpers:
            return self.helpers[key]
        fn = ir.Function(self.module, ir.FunctionType(retty, argtys),
                         name=f"{kind}_{_tykey(t)}")
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
        if isinstance(t, TJoin):
            b.call(self._rt("rt_task_drop" if t.task else "rt_thread_drop"), [v.ssa])
            return
        if isinstance(t, TThread):
            b.call(self._rt("rt_thread_free"), [v.ssa])
            return
        if isinstance(t, TShared):
            b.call(self._shared_drop_fn(t.inner), [v.ssa])
            return
        if isinstance(t, TBytes):
            b.call(self._rt("rt_bytes_drop"), [v.ssa])
            return
        if isinstance(t, TPyVal):
            b.call(self._rt("rt_pyval_drop"), [v.ssa])
            return
        if isinstance(t, TByteArray):
            b.call(self._rt("rt_list_free"), [v.ptr, ir.Constant(I64, 1)])
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
        if isinstance(t, TFunc):
            env = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
            nonnull = b.icmp_unsigned("!=", env, ir.Constant(I8P, None))
            with b.if_then(nonnull):
                rcp = b.bitcast(env, I64.as_pointer())
                rc = b.sub(b.load(rcp), ir.Constant(I64, 1))
                b.store(rc, rcp)
                dead = b.icmp_signed("==", rc, ir.Constant(I64, 0))
                with b.if_then(dead):
                    dpp = b.bitcast(b.gep(env, [ir.Constant(I64, 8)]),
                                    DTORTY.as_pointer().as_pointer())
                    b.call(b.load(dpp), [env])
            return
        if isinstance(t, (TList, TDict, TSet)):
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
        if isinstance(t, TUnion):
            tag = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            for i, m in enumerate(t.members):
                if not self._droppable(m):
                    continue
                with b.if_then(b.icmp_unsigned("==", tag, ir.Constant(I8, i))):
                    p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                    self._drop(b, m, self._as_v(b, m, p))
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
        """Clone a handle scalar (Shared/Weak/bytes): bump the refcount."""
        if isinstance(t, TShared):
            p = b.bitcast(ssa, I64.as_pointer())
            b.store(b.add(b.load(p), ir.Constant(I64, 1)), p)
            return ssa
        if isinstance(t, TWeak):
            p = b.gep(b.bitcast(ssa, I64.as_pointer()), [ir.Constant(I64, 1)])
            b.store(b.add(b.load(p), ir.Constant(I64, 1)), p)
            return ssa
        if isinstance(t, TBytes):
            b.call(self._rt("rt_bytes_clone"), [ssa])
            return ssa
        if isinstance(t, TPyVal):
            b.call(self._rt("rt_pyval_clone"), [ssa])
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
        if isinstance(t, TFunc):
            for i in (0, 1):
                s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i)])
                b.store(b.load(s), d)
            env = b.load(b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
            nonnull = b.icmp_unsigned("!=", env, ir.Constant(I8P, None))
            with b.if_then(nonnull):
                rcp = b.bitcast(env, I64.as_pointer())
                b.store(b.add(b.load(rcp), ir.Constant(I64, 1)), rcp)
            return
        if isinstance(t, TByteArray):
            b.call(self._rt("rt_ba_clone"), [src_ptr, dst_ptr])
            return
        if isinstance(t, (TList, TDict, TSet)):
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
        if isinstance(t, TUnion):
            b.store(ir.Constant(self._lty(t), None), dst_ptr)
            tag = b.load(b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            b.store(tag, b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            for i, m in enumerate(t.members):
                with b.if_then(b.icmp_unsigned("==", tag, ir.Constant(I8, i))):
                    s = b.gep(src_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                    d = b.gep(dst_ptr, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                    self._clone_any(b, m, s, d)
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
        if isinstance(t, (TShared, TWeak, TPyVal, TBytes)):
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
        if isinstance(t, (TInt, TEnum)):
            return b.icmp_signed("==", a.ssa, c.ssa)
        if isinstance(t, TBool):
            return b.icmp_unsigned("==", a.ssa, c.ssa)
        if isinstance(t, TFloat):
            return b.fcmp_ordered("==", a.ssa, c.ssa)
        if isinstance(t, TStr):
            r = b.call(self._rt("rt_str_eq"), [a.ptr, c.ptr])
            return b.trunc(r, I1)
        if isinstance(t, TBytes):
            r = b.call(self._rt("rt_bytes_eq"), [a.ssa, c.ssa])
            return b.trunc(r, I1)
        if isinstance(t, TPyVal):
            r = b.call(self._rt("rt_pyval_eq"), [a.ssa, c.ssa])
            return b.trunc(r, I1)
        if isinstance(t, TByteArray):
            r = b.call(self._rt("rt_ba_eq"), [a.ptr, c.ptr])
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
            if isinstance(t, (TList, TDict, TSet)):
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
            elif isinstance(t, TUnion):
                ta = b.load(b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                tcg = b.load(b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                same = b.icmp_unsigned("==", ta, tcg)
                out = b.alloca(I1)
                b.store(same, out)
                with b.if_then(same):
                    for i, m in enumerate(t.members):
                        with b.if_then(b.icmp_unsigned("==", ta, ir.Constant(I8, i))):
                            pa = b.gep(ap, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                            pc = b.gep(cp, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                            e = self._eq_vals(b, m, self._as_v(b, m, pa),
                                              self._as_v(b, m, pc))
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
        elif isinstance(t, TSet):
            found = b.alloca(I1)
            b.store(ir.Constant(I1, 0), found)
            jdx = b.alloca(I64)
            b.store(ir.Constant(I64, 0), jdx)
            shead = fn.append_basic_block("shead")
            sloop = fn.append_basic_block("sloop")
            sdone = fn.append_basic_block("sdone")
            b.branch(shead)
            b.position_at_end(shead)
            j = b.load(jdx)
            b.cbranch(b.icmp_signed("<", j, nc), sloop, sdone)
            b.position_at_end(sloop)
            pc = self._elem_ptr(b, cp, elem, j)
            hit = self._eq_vals(b, elem, self._as_v(b, elem, pa), self._as_v(b, elem, pc))
            b.store(b.or_(b.load(found), hit), found)
            b.store(b.add(j, ir.Constant(I64, 1)), jdx)
            b.branch(shead)
            b.position_at_end(sdone)
            b.store(b.add(i, ir.Constant(I64, 1)), idx)
            b.cbranch(b.load(found), head, neq)
        else:
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
        if isinstance(t, TBytes):
            return b.call(self._rt("rt_bytes_cmp"), [b.load(ap), b.load(cp)])
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

    @staticmethod
    def _enum_text(info, member: str, value, as_repr: bool) -> str:
        """CPython's str()/repr() text for one enum member (constant per member)."""
        if as_repr:
            return f"<{info.name}.{member}: {value!r}>"
        if info.base == "IntEnum":
            return str(value)
        if info.base == "StrEnum":
            return str(value)
        return f"{info.name}.{member}"

    def _select_cstr(self, b: ir.IRBuilder, texts: list[str], idx):
        """(i8*, i64) of the text chosen by a 0-based runtime index."""
        consts = [self._cstr(s) for s in texts]
        p, n = consts[0][0], ir.Constant(I64, consts[0][1])
        for i, (pi, ni) in enumerate(consts[1:], start=1):
            hit = b.icmp_signed("==", idx, ir.Constant(I64, i))
            p = b.select(hit, pi, p)
            n = b.select(hit, ir.Constant(I64, ni), n)
        return p, n

    def _push(self, b: ir.IRBuilder, t: Type, v: V, sb, as_repr: bool) -> None:
        """Append py_str/py_repr of v to string-builder sb (CPython parity)."""
        if isinstance(t, TEnum):
            info = self.tc.enums[(t.module, t.name)]
            texts = [self._enum_text(info, m, val, as_repr) for m, val in info.members]
            p, n = self._select_cstr(b, texts, v.ssa)
            b.call(self._rt("rt_sb_push_bytes"), [sb, p, n])
            return
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
        if isinstance(t, TUnion):
            tag = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            fnc = b.function
            ujoin = fnc.append_basic_block("uni.join")
            for i, m in enumerate(t.members):
                hit = b.icmp_unsigned("==", tag, ir.Constant(I8, i))
                blk = fnc.append_basic_block(f"uni.m{i}")
                nxt = fnc.append_basic_block(f"uni.n{i}")
                b.cbranch(hit, blk, nxt)
                b.position_at_end(blk)
                p = b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, i + 1)])
                self._push(b, m, self._as_v(b, m, p), sb, as_repr)
                b.branch(ujoin)
                b.position_at_end(nxt)
            b.branch(ujoin)
            b.position_at_end(ujoin)
            return
        if isinstance(t, TShared):
            payload = b.bitcast(b.gep(v.ssa, [ir.Constant(I64, 24)]),
                                self._lty(t.inner).as_pointer())
            self._push(b, t.inner, self._as_v(b, t.inner, payload), sb, as_repr)
            return
        if isinstance(t, TWeak):
            self._push_bytes(b, sb, "<weak>")
            return
        if isinstance(t, TBytes):
            tmp = b.alloca(SSTR)
            b.call(self._rt("rt_bytes_repr"), [v.ssa, tmp])
            b.call(self._rt("rt_sb_push_str"), [sb, tmp])
            b.call(self._rt("rt_str_drop"), [tmp])
            return
        if isinstance(t, TPyVal):
            tmp = b.alloca(SSTR)
            fn2 = "rt_pyval_repr" if as_repr else "rt_pyval_str_of"
            b.call(self._rt(fn2), [v.ssa, tmp])
            b.call(self._rt("rt_sb_push_str"), [sb, tmp])
            b.call(self._rt("rt_str_drop"), [tmp])
            return
        if isinstance(t, TByteArray):
            tmp = b.alloca(SSTR)
            b.call(self._rt("rt_ba_repr"), [v.ptr, tmp])
            b.call(self._rt("rt_sb_push_str"), [sb, tmp])
            b.call(self._rt("rt_str_drop"), [tmp])
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
            if isinstance(t, (TList, TDict, TSet)):
                elem = self._elem_of(t)
                is_dict = isinstance(t, TDict)
                is_set = isinstance(t, TSet)
                n = self._list_len(b, vp)
                if is_set:
                    empty = fn.append_basic_block("set.empty")
                    nonempty = fn.append_basic_block("set.nonempty")
                    b.cbranch(b.icmp_signed("==", n, ir.Constant(I64, 0)), empty, nonempty)
                    b.position_at_end(empty)
                    self._push_bytes(b, sb, "set()")
                    b.ret_void()
                    b.position_at_end(nonempty)
                self._push_bytes(b, sb, "[" if isinstance(t, TList) else "{")
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
                self._push_bytes(b, sb, "]" if isinstance(t, TList) else "}")
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
            msig = self.tc.sigs.get((t.module, f"{t.name}.__repr__"))
            if msig is not None and not msig.is_template and not info.typevars:
                res = b.call(self.funcs[(t.module, msig.name)], [vp])
                err = b.extract_value(res, 0)
                with b.if_then(err):
                    b.call(self._rt("rt_abort_pending"), [])
                    b.unreachable()
                tmp = b.alloca(SSTR)
                b.store(b.extract_value(res, 1), tmp)
                b.call(self._rt("rt_sb_push_str"), [sb, tmp])
                b.call(self._rt("rt_str_drop"), [tmp])
                b.ret_void()
                return
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
        while self.pending_lambdas:
            self._emit_lambda_fn(self.pending_lambdas.pop(0))
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
        b.call(self._rt("rt_threads_join_all"), [])
        b.ret_void()
        if self.define_c_main:
            mn = ir.Function(self.module, ir.FunctionType(I32, []), name="main")
            mb = ir.IRBuilder(mn.append_basic_block("entry"))
            mb.call(se, [])
            mb.ret(ir.Constant(I32, 0))
        return self.module

    def _closure_fnty(self, ft: TFunc) -> ir.FunctionType:
        """The LLVM function type behind a Callable value (env first, then params)."""
        retty = I1 if isinstance(ft.ret, TNone) else \
            ir.LiteralStructType([I1, self._lty(ft.ret)])
        return ir.FunctionType(retty, [I8P] + [self._lty(p) for p in ft.params])

    def _func_thunk(self, key: tuple[str, str], ft: TFunc) -> ir.Function:
        """An env-discarding forwarder so a module function fits the closure ABI."""
        tkey = (key, mangle_type(ft))
        if tkey in self.thunks:
            return self.thunks[tkey]
        name = self._sanitize(f"thunk_{key[0]}_{key[1]}_{mangle_type(ft)}")
        fn = ir.Function(self.module, self._closure_fnty(ft), name=name)
        fn.linkage = "internal"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        res = b.call(self.funcs[key], list(fn.args)[1:])
        b.ret(res)
        self.thunks[tkey] = fn
        return fn

    def _lambda_value(self, node: ast.Lambda) -> V:
        """Materialize a capturing lambda: heap env {rc, dtor, caps...} + fn ptr."""
        ft = self._t(node)
        assert isinstance(ft, TFunc)
        caps = self.tc.lambda_caps.get(id(node), [])
        n = self.lambda_counter
        self.lambda_counter += 1
        envty = ir.LiteralStructType([I64, I8P] + [self._lty(t) for _, t in caps])
        fn = ir.Function(self.module, self._closure_fnty(ft), name=f"lam_{n}")
        fn.linkage = "internal"
        dtor = ir.Function(self.module, DTORTY, name=f"lam_dtor_{n}")
        dtor.linkage = "internal"
        self.pending_lambdas.append({"node": node, "ft": ft, "caps": caps, "fn": fn,
                                     "dtor": dtor, "envty": envty, "mod": self.mod})
        b = self.b
        size = envty.get_abi_size(self.td)
        envp = b.call(self._rt("rt_shared_alloc"), [ir.Constant(I64, size)])
        tenv = b.bitcast(envp, envty.as_pointer())
        b.store(ir.Constant(I64, 1),
                b.gep(tenv, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        b.store(b.bitcast(dtor, I8P),
                b.gep(tenv, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        for i, (cname, ct) in enumerate(caps):
            bind = self.bindings[cname]
            src = bind["ptr"]
            if bind["ref"]:
                src = b.load(src)
            dst = b.gep(tenv, [ir.Constant(I32, 0), ir.Constant(I32, 2 + i)])
            self._clone_any(b, ct, src, dst)
        tmp = self._temp(ft)
        b.store(b.bitcast(fn, I8P),
                b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        b.store(envp, b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        return tmp

    def _func_value_call(self, node: ast.Call, ft: TFunc) -> V:
        """Call through a Callable value: unpack {fn, env} and dispatch."""
        fv = self._expr(node.func, "ref")
        fnp = self.b.load(self.b.gep(fv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        envp = self.b.load(self.b.gep(fv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        fnc = self.b.bitcast(fnp, self._closure_fnty(ft).as_pointer())
        args = [envp]
        for a, pt in zip(node.args, ft.params):
            args.append(self._arg_value(a, Param(name="", conv="copy", typ=pt)))
        return self._finish_call(fnc, args, ft.ret)

    def _emit_lambda_fn(self, rec: dict) -> None:
        """Emit a deferred lambda body as its own internal function."""
        fn, ft, caps, lnode, envty = rec["fn"], rec["ft"], rec["caps"], rec["node"], rec["envty"]
        self.fn = fn
        self.mod = rec["mod"]
        self.sig = FuncSig(module=self.mod.name, name=fn.name,
                           params=[Param(name=a.arg, conv="copy", typ=pt)
                                   for a, pt in zip(lnode.args.args, ft.params)],
                           ret=ft.ret, node=lnode)
        self.entry_block = fn.append_basic_block("entry")
        self.body_block = fn.append_basic_block("body")
        self.b = ir.IRBuilder(self.body_block)
        self.bindings = {}
        self.func_drops = []
        self.try_ctx = []
        self.cur_exc = []
        self.loop_stack = []
        self.stmt_temps = []
        self.active_borrows = []
        self.try_counter = 0
        self.raise_blocks = {}
        self.di_sub = None
        self.errflag_slot = self._entry_alloca(I1, name="errflag")
        self.b.store(ir.Constant(I1, 0), self.errflag_slot)
        if not isinstance(ft.ret, TNone):
            self.ret_slot = self._entry_alloca(self._lty(ft.ret), name="retval")
            self.b.store(ir.Constant(self._lty(ft.ret), None), self.ret_slot)
        else:
            self.ret_slot = None
        self.exit_block = fn.append_basic_block("func.exit")
        self.err_return_block = fn.append_basic_block("func.err")

        tenv = self.b.bitcast(fn.args[0], envty.as_pointer())
        for i, (cname, ct) in enumerate(caps):
            p = self.b.gep(tenv, [ir.Constant(I32, 0), ir.Constant(I32, 2 + i)])
            self.bindings[cname] = {"ptr": p, "ty": ct, "ref": False, "flag": None}
        for a, pt, arg in zip(lnode.args.args, ft.params, list(fn.args)[1:]):
            arg.name = f"a_{a.arg}"
            bind = self._make_binding(a.arg, pt)
            self.b.store(arg, bind["ptr"])
            if bind["flag"] is not None:
                self.b.store(ir.Constant(I1, 1), bind["flag"])

        ret = ast.Return(value=lnode.body)
        ast.copy_location(ret, lnode.body)
        ast.fix_missing_locations(ret)
        self._emit_stmt(ret)
        if not self.b.block.is_terminated:
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
        if isinstance(ft.ret, TNone):
            b.ret(flag)
        else:
            res = ir.Constant(ir.LiteralStructType([I1, self._lty(ft.ret)]), None)
            res = b.insert_value(res, flag, 0)
            res = b.insert_value(res, b.load(self.ret_slot), 1)
            b.ret(res)

        db = ir.IRBuilder(rec["dtor"].append_basic_block("entry"))
        denv = db.bitcast(rec["dtor"].args[0], envty.as_pointer())
        for i, (cname, ct) in enumerate(caps):
            if self._droppable(ct):
                p = db.gep(denv, [ir.Constant(I32, 0), ir.Constant(I32, 2 + i)])
                self._drop(db, ct, self._as_v(db, ct, p))
        db.call(self._rt("rt_shared_free"),
                [rec["dtor"].args[0], ir.Constant(I64, envty.get_abi_size(self.td))])
        db.ret_void()

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
            if isinstance(node, ast.For) and id(node) not in self.tc.for_lowered:
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
            self._emit_pending_finals()
            if self.b.block.is_terminated:
                return
            self._drain_for_jump()
            self.b.branch(self.loop_stack[-1][1])
            return
        if isinstance(s, ast.Continue):
            self._emit_pending_finals()
            if self.b.block.is_terminated:
                return
            self._drain_for_jump()
            self.b.branch(self.loop_stack[-1][0])
            return
        raise LLVMUnsupported(f"statement {type(s).__name__}")

    def _emit_pending_finals(self) -> None:
        """Run the finally bodies of every try a break/continue leaves, innermost first."""
        depth = self.loop_stack[-1][2] if len(self.loop_stack[-1]) > 2 else len(self.try_ctx)
        saved = self.try_ctx
        for i in range(len(saved) - 1, depth - 1, -1):
            fin = saved[i].get("final")
            if not fin:
                continue
            self.try_ctx = saved[:i]
            self._emit_block(fin)
            if self.b.block.is_terminated:
                break
        self.try_ctx = saved

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
        oc = self.tc.op_calls.get(id(stmt))
        if oc is not None:
            self._call(oc, "val")
            return
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
            if isinstance(inner, TByteArray):
                recv = self._recv(target.value, True)
                idx = self._expr(target.slice, "val").ssa
                v = self._expr(stmt.value, "val").ssa
                st = self.b.call(self._rt("rt_ba_set"), [recv.ptr, idx, v])
                self._check_err_i8(st)
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

    def _cond_i1(self, test: ast.expr):
        """Evaluate a condition to i1, applying PyVal truthiness."""
        v = self._expr(test, "val")
        if isinstance(v.ty, TPyVal):
            r = self.b.call(self._rt("rt_pyval_truthy"), [v.ssa])
            return self.b.trunc(r, I1)
        return v.ssa

    def _emit_if(self, s: ast.If) -> None:
        mark_t = len(self.stmt_temps)
        mark_b = len(self.active_borrows)
        cond = self._cond_i1(s.test)
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
        cond = self._cond_i1(s.test)
        self._drain(mark_t, mark_b)
        self.b.cbranch(cond, body, exit_b)
        self.b.position_at_end(body)
        self.loop_stack.append((head, exit_b, len(self.try_ctx)))
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
        self.try_ctx.append({"block": catch, "final": s.finalbody})
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
                named = ["Exception"] if h.type is None else (
                    [h.type.id] if isinstance(h.type, ast.Name)
                    else [el.id for el in h.type.elts if isinstance(el, ast.Name)])
                classes: list[str] = []
                for c in named:
                    classes += [n for n in exc_handler_names(c, self.tc.user_exc)
                                if n not in classes]
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
                self.try_ctx.append({"block": hcatch, "final": s.finalbody})
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
        lowered = self.tc.for_lowered.get(id(s))
        if lowered is not None:
            for name in self.tc.for_lowered_names.get(id(s), []):
                if name not in self.bindings:
                    self._make_binding(name, self.facts.locals[name])
            for st in lowered:
                self._emit_stmt(st)
            return
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
            elif kind in ("bytes", "bytearray"):
                src = self._expr(iter_node, "ref")
                tmp = self._temp(TList(TInt()))
                self.b.store(ir.Constant(SLIST, None), tmp.ptr)
                if kind == "bytes":
                    self.b.call(self._rt("rt_bytes_ints"), [src.ssa, tmp.ptr])
                else:
                    self.b.call(self._rt("rt_ba_ints"), [src.ptr, tmp.ptr])
                seq = tmp
                elem_t = TInt()
            elif kind == "pyval":
                src = self._expr(iter_node, "ref")
                tmp = self._temp(TList(TPyVal()))
                self.b.store(ir.Constant(SLIST, None), tmp.ptr)
                st = self.b.call(self._rt("rt_pyval_iter"), [src.ssa, tmp.ptr])
                self._check_err_i8(st)
                seq = tmp
                elem_t = TPyVal()
            else:
                seq = self._expr(iter_node, "ref")
                it_t = self._t(iter_node)
                if isinstance(it_t, TStr):
                    seq = self._chars_temp(seq)
                    elem_t = TStr()
                else:
                    assert isinstance(it_t, (TList, TSet)), f"cannot iterate {it_t}"
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
        self.loop_stack.append((incr, exitc, len(self.try_ctx)))
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
        if isinstance(dst, TUnion) and not isinstance(src, TUnion):
            slot = union_slot(src, dst)
            if slot is None:
                raise LLVMUnsupported(f"cannot widen {src} into {dst}")
            inner = self._coerce(v, dst.members[slot])
            tmp = self._temp(dst)
            self.b.store(ir.Constant(self._lty(dst), None), tmp.ptr)
            self.b.store(ir.Constant(I8, slot),
                         self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            payload = self.b.gep(tmp.ptr,
                                 [ir.Constant(I32, 0), ir.Constant(I32, slot + 1)])
            self._store_into(payload, inner)
            return tmp
        if isinstance(dst, TFloat) and isinstance(src, TInt):
            return V(dst, ssa=self.b.sitofp(v.ssa, F64))
        if isinstance(dst, TPyVal) and not isinstance(src, TPyVal):
            if isinstance(src, TNone):
                h = self.b.call(self._rt("rt_pyval_none"), [])
                return self._register_temp_ssa(dst, h)
            if v.ptr is not None:
                p = v.ptr
            else:
                p = self._entry_alloca(self._lty(src))
                self.b.store(v.ssa, p)
            h = self.b.call(self._pyval_from_fn(src), [p])
            return self._register_temp_ssa(TPyVal(), h)
        return v

    def _pyval_from_fn(self, t: Type) -> ir.Function:
        """i8* topyval_T(T*): convert a typed storage slot into a fresh PyVal."""

        def body(b, fn):
            src = fn.args[0]
            if isinstance(t, TBool):
                b.ret(b.call(self._rt("rt_pyval_bool"), [b.zext(b.load(src), I8)]))
                return
            if isinstance(t, TInt):
                b.ret(b.call(self._rt("rt_pyval_int"), [b.load(src)]))
                return
            if isinstance(t, TFloat):
                b.ret(b.call(self._rt("rt_pyval_float"), [b.load(src)]))
                return
            if isinstance(t, TStr):
                b.ret(b.call(self._rt("rt_pyval_str"), [src]))
                return
            if isinstance(t, TBytes):
                b.ret(b.call(self._rt("rt_pyval_bytes"), [b.load(src)]))
                return
            if isinstance(t, TList):
                h = b.call(self._rt("rt_pyval_list_new"), [])
                n = self._list_len(b, src)
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
                p = self._elem_ptr(b, src, t.elem, i)
                eh = b.call(self._pyval_from_fn(t.elem), [p])
                b.call(self._rt("rt_pyval_list_push"), [h, eh])
                b.call(self._rt("rt_pyval_drop"), [eh])
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                b.branch(head)
                b.position_at_end(done)
                b.ret(h)
                return
            if isinstance(t, TDict):
                elem = self._elem_of(t)
                h = b.call(self._rt("rt_pyval_dict_new"), [])
                n = self._list_len(b, src)
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
                p = self._elem_ptr(b, src, elem, i)
                kp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 0)])
                vp = b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                kh = b.call(self._pyval_from_fn(t.key), [kp])
                eh = b.call(self._pyval_from_fn(t.value), [vp])
                b.call(self._rt("rt_pyval_dict_set_pv"), [h, kh, eh])
                b.call(self._rt("rt_pyval_drop"), [eh])
                b.call(self._rt("rt_pyval_drop"), [kh])
                b.store(b.add(i, ir.Constant(I64, 1)), idx)
                b.branch(head)
                b.position_at_end(done)
                b.ret(h)
                return
            if isinstance(t, TPyVal):
                v0 = b.load(src)
                b.call(self._rt("rt_pyval_clone"), [v0])
                b.ret(v0)
                return
            raise LLVMUnsupported(f"cannot convert {t} to PyVal")

        return self._helper("topyval", t, [self._lty(t).as_pointer()], I8P, body)

    def _expr(self, node: ast.expr, mode: str, expect: Type | None = None) -> V:
        et = self.tc.expr_types.get(id(node))
        if mode == "val" and isinstance(expect, TPyVal) and et is not None \
                and not isinstance(et, TPyVal) \
                and isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            mode = "ref"
        oc = self.tc.op_calls.get(id(node))
        if oc is not None:
            return self._expr(oc, mode)
        if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)):
            return self._comp_expr(node, expect)
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
        if isinstance(node, ast.Set):
            t = self._t(node)
            assert isinstance(t, TSet)
            tmp = self._temp(t)
            self.b.store(ir.Constant(SLIST, None), tmp.ptr)
            for e in node.elts:
                ev = self._coerce(self._expr(e, "val", expect=t.elem), t.elem)
                self._set_add(tmp.ptr, t.elem, ev)
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
            nc = getattr(node, "_narrow", None)
            if nc is not None:
                ut, mt = nc
                uv = self._call(node, "val")
                slot = union_slot(mt, ut)
                p = self.b.gep(uv.ptr, [ir.Constant(I32, 0), ir.Constant(I32, slot + 1)])
                if mode != "val" or not self._is_agg(mt):
                    return self._read_place(mt, p, mode)
                # Bitwise move of the live member; the union temp then holds nothing that
                # needs dropping, so it must not be dropped at statement end.
                tmp = self._temp(mt)
                self.b.store(self.b.load(p), tmp.ptr)
                self._consume(uv)
                return tmp
            return self._call(node, mode)
        if isinstance(node, ast.Attribute):
            return self._attribute(node, mode)
        if isinstance(node, ast.Lambda):
            return self._lambda_value(node)
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
        if isinstance(v, bytes):
            p, n = self._cbytes(v)
            h = self.b.call(self._rt("rt_bytes_new"), [p, ir.Constant(I64, n)])
            return self._register_temp_ssa(TBytes(), h)
        if v is None:
            return V(TNone(), ssa=ir.Constant(I1, 0))
        raise LLVMUnsupported(f"literal {v!r}")

    def _name(self, node: ast.Name, mode: str) -> V:
        name = node.id
        fref = self.tc.func_value_refs.get(id(node))
        if fref is not None:
            ft = self._t(node)
            assert isinstance(ft, TFunc)
            thunk = self._func_thunk(fref, ft)
            tmp = self._temp(ft)
            self.b.store(self.b.bitcast(thunk, I8P),
                         self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            self.b.store(ir.Constant(I8P, None),
                         self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
            return tmp
        bind = self.bindings.get(name)
        if bind is None:
            cmod, cname = self.mod.name, name
            if (cmod, cname) not in self.tc.constants and name in self.mod.imports:
                cmod, cname = self.mod.imports[name]
            const = self.tc.constants.get((cmod, cname))
            if const is not None:
                cnode = self.tc.program.modules[cmod].constants[cname].value
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
            slot = self.tc.narrow_variant.get(id(node))
            if slot is not None:
                assert isinstance(t, TUnion)
                member = t.members[slot]
                payload = self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, slot + 1)])
                return self._read_place(member, payload, mode,
                                        moveable=(bind["flag"] if not bind["ref"] else None),
                                        borrowed=bind["ref"])
            assert isinstance(t, TOptional)
            inner = t.inner
            payload = self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
            return self._read_place(inner, payload, mode,
                                    moveable=(bind["flag"] if not bind["ref"] else None),
                                    borrowed=bind["ref"])
        return self._read_place(t, ptr, mode,
                                moveable=(bind["flag"] if not bind["ref"] else None),
                                borrowed=bind["ref"])

    def _read_place(self, t: Type, ptr, mode: str, moveable=None, borrowed: bool = False) -> V:
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
        if isinstance(t, (TBytes, TPyVal)):
            return self._register_temp_ssa(
                t, self._clone_scalar(self.b, t, self.b.load(ptr)))
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
        if borrowed:
            tmp = self._temp(t)
            self._clone_into(self.b, t, ptr, tmp.ptr)
            return tmp
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
                slot = self.tc.narrow_variant.get(id(e))
                idx = 1 if slot is None else slot + 1
                ptr = self.b.gep(ptr, [ir.Constant(I32, 0), ir.Constant(I32, idx)])
            return ptr
        if isinstance(e, ast.Attribute):
            base_t = self._t(e.value)
            if isinstance(base_t, TShared):
                h = self._expr(e.value, "ref").ssa
                payload = self._borrow(h, mut, base_t.inner)
                return self._field_ptr(payload, base_t.inner, e.attr)
            p = self._field_ptr(self._place(e.value, mut), base_t, e.attr)
            if id(e) in self.tc.narrowed_uses:
                slot = self.tc.narrow_variant.get(id(e))
                idx = 1 if slot is None else slot + 1
                p = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, idx)])
            return p
        if isinstance(e, ast.Subscript) and id(e) not in self.tc.op_calls:
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
        if isinstance(e, (ast.Subscript, ast.Call, ast.BinOp, ast.UnaryOp, ast.Compare)):
            v = self._expr(e, "val")
            if v.ptr is not None:
                return v.ptr
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
        member = self.tc.enum_members.get(id(node))
        if member is not None:
            emod, ename, mname = member
            info = self.tc.enums[(emod, ename)]
            idx = [m for m, _ in info.members].index(mname)
            return V(TEnum(emod, ename), ssa=ir.Constant(I64, idx))
        if isinstance(self._t(node.value), TEnum):
            return self._enum_attr(node)
        if isinstance(self._t(node.value), TThread):
            h = self._expr(node.value, "ref").ssa
            if node.attr == "name":
                tmp = self._temp(TStr())
                self.b.call(self._rt("rt_thread_name"), [h, tmp.ptr])
                return tmp
            if node.attr == "ident":
                idv = self.b.call(self._rt("rt_thread_ident"), [h])
                tmp = self._temp(TOptional(TInt()))
                has = self.b.icmp_signed("!=", idv, ir.Constant(I64, 0))
                self.b.store(has, self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                self.b.store(idv, self.b.gep(tmp.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
                return tmp
            d = self.b.call(self._rt("rt_thread_daemon"), [h])
            return V(TBool(), ssa=self.b.trunc(d, I1))
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
            slot = self.tc.narrow_variant.get(id(node))
            if slot is not None:
                assert isinstance(ft, TUnion)
                p = self.b.gep(p, [ir.Constant(I32, 0), ir.Constant(I32, slot + 1)])
                ft = ft.members[slot]
                return self._read_place(ft, p, mode)
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
        if isinstance(inner0, TBytes):
            recv = self._expr(node.value, "ref")
            if isinstance(node.slice, ast.Slice):
                lo = node.slice.lower
                hi = node.slice.upper
                lov = self._expr(lo, "val").ssa if lo is not None else ir.Constant(I64, 0)
                hiv = self._expr(hi, "val").ssa if hi is not None else ir.Constant(I64, 0)
                h = self.b.call(self._rt("rt_bytes_slice"),
                                [recv.ssa, lov, ir.Constant(I8, 1 if lo is not None else 0),
                                 hiv, ir.Constant(I8, 1 if hi is not None else 0)])
                return self._register_temp_ssa(TBytes(), h)
            idx = self._expr(node.slice, "val").ssa
            out = self._entry_alloca(I64)
            st = self.b.call(self._rt("rt_bytes_index"), [recv.ssa, idx, out])
            self._check_err_i8(st)
            return V(TInt(), ssa=self.b.load(out))
        if isinstance(inner0, TByteArray):
            recv = self._recv(node.value, False)
            if isinstance(node.slice, ast.Slice):
                lo = node.slice.lower
                hi = node.slice.upper
                lov = self._expr(lo, "val").ssa if lo is not None else ir.Constant(I64, 0)
                hiv = self._expr(hi, "val").ssa if hi is not None else ir.Constant(I64, 0)
                tmp = self._temp(TByteArray())
                self.b.call(self._rt("rt_ba_slice"),
                            [recv.ptr, lov, ir.Constant(I8, 1 if lo is not None else 0),
                             hiv, ir.Constant(I8, 1 if hi is not None else 0), tmp.ptr])
                return tmp
            idx = self._expr(node.slice, "val").ssa
            out = self._entry_alloca(I64)
            st = self.b.call(self._rt("rt_ba_get"), [recv.ptr, idx, out])
            self._check_err_i8(st)
            return V(TInt(), ssa=self.b.load(out))
        if isinstance(inner0, TPyVal):
            recv = self._expr(node.value, "ref")
            idx_t = self._t(node.slice)
            out = self._entry_alloca(I8P)
            if isinstance(idx_t, TStr):
                idx = self._expr(node.slice, "ref")
                st = self.b.call(self._rt("rt_pyval_getitem_s"), [recv.ssa, idx.ptr, out])
            elif isinstance(idx_t, TPyVal):
                idx = self._expr(node.slice, "ref")
                st = self.b.call(self._rt("rt_pyval_getitem_v"), [recv.ssa, idx.ssa, out])
            elif isinstance(idx_t, (TFloat, TBool)):
                idx = self._expr(node.slice, "val")
                if isinstance(idx_t, TFloat):
                    kh = self.b.call(self._rt("rt_pyval_float"), [idx.ssa])
                else:
                    kh = self.b.call(self._rt("rt_pyval_bool"), [self.b.zext(idx.ssa, I8)])
                st = self.b.call(self._rt("rt_pyval_getitem_v"), [recv.ssa, kh, out])
                self.b.call(self._rt("rt_pyval_drop"), [kh])
            else:
                idx = self._expr(node.slice, "val")
                st = self.b.call(self._rt("rt_pyval_getitem_i"), [recv.ssa, idx.ssa, out])
            self._check_err_i8(st)
            return self._register_temp_ssa(TPyVal(), self.b.load(out))
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

    # ---------- set primitives (scan-based, insertion-ordered) ----------

    def _set_scan(self, setptr, elem_t: Type, val: V):
        """Return (found i1, index i64) for val in a set buffer."""
        found = self._entry_alloca(I1)
        pos = self._entry_alloca(I64)
        self.b.store(ir.Constant(I1, 0), found)
        self.b.store(ir.Constant(I64, 0), pos)
        n = self._list_len(self.b, setptr)

        def body(i):
            p = self._elem_ptr(self.b, setptr, elem_t, i)
            eq = self._eq_vals(self.b, elem_t, self._as_v(self.b, elem_t, p), val)
            with self.b.if_then(eq):
                self.b.store(ir.Constant(I1, 1), found)
                self.b.store(i, pos)

        self._simple_loop(n, body)
        return self.b.load(found), self.b.load(pos)

    def _set_add(self, setptr, elem_t: Type, val: V) -> None:
        """Insert val into a set unless it is already present (consumes val)."""
        found, _ = self._set_scan(setptr, elem_t, val)
        hit = self.fn.append_basic_block("sadd.hit")
        miss = self.fn.append_basic_block("sadd.miss")
        done = self.fn.append_basic_block("sadd.done")
        self.b.cbranch(found, hit, miss)
        self.b.position_at_end(hit)
        if self._droppable(elem_t):
            self._drop(self.b, elem_t, val)
        self.b.branch(done)
        self.b.position_at_end(miss)
        self._list_push(setptr, elem_t, val)
        self.b.branch(done)
        self.b.position_at_end(done)
        self._consume(val)

    def _set_each(self, setptr, elem_t: Type, body) -> None:
        """Call body(elem_ptr) for every element of a set buffer."""
        n = self._list_len(self.b, setptr)
        self._simple_loop(n, lambda i: body(self._elem_ptr(self.b, setptr, elem_t, i)))

    def _set_contains_ptr(self, setptr, elem_t: Type, srcptr) -> ir.Value:
        """i1: does the set contain the value stored at srcptr?"""
        found, _ = self._set_scan(setptr, elem_t, self._as_v(self.b, elem_t, srcptr))
        return found

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
        if isinstance(lt, TBytes) and isinstance(rt, TBytes) and isinstance(op, ast.Add):
            h = self.b.call(self._rt("rt_bytes_concat"), [l.ssa, r.ssa])
            return self._register_temp_ssa(TBytes(), h)
        if isinstance(op, ast.Mult) and isinstance(lt, TBytes) and isinstance(rt, TInt):
            h = self.b.call(self._rt("rt_bytes_repeat"), [l.ssa, r.ssa])
            return self._register_temp_ssa(TBytes(), h)
        if isinstance(op, ast.Mult) and isinstance(lt, TInt) and isinstance(rt, TBytes):
            h = self.b.call(self._rt("rt_bytes_repeat"), [r.ssa, l.ssa])
            return self._register_temp_ssa(TBytes(), h)
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
            if isinstance(t, TPyVal):
                r = self.b.call(self._rt("rt_pyval_truthy"), [v.ssa])
                return V(TBool(), ssa=self.b.not_(self.b.trunc(r, I1)))
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
        if isinstance(lt, TBytes):
            c = self.b.call(self._rt("rt_bytes_cmp"), [l.ssa, r.ssa])
            return self.b.icmp_signed(sym, c, ir.Constant(I32, 0))
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
            lt = self._t(e.left)
            v = self._expr(e.left, "ref")
            if isinstance(lt, TPyVal):
                kind = self._temp(TStr())
                self.b.call(self._rt("rt_pyval_kind"), [v.ssa, kind.ptr])
                none = self._temp(TStr())
                p, n = self._cstr("NoneType")
                self.b.call(self._rt("rt_str_new"), [p, ir.Constant(I64, n), none.ptr])
                hit = self.b.icmp_unsigned("!=", self.b.call(self._rt("rt_str_eq"),
                                                              [kind.ptr, none.ptr]),
                                           ir.Constant(I8, 0))
                r = hit if isinstance(op0, ast.Is) else self.b.not_(hit)
                return V(TBool(), ssa=r)
            if isinstance(lt, TUnion):
                slot = union_slot(NONE, lt)
                tag = self.b.load(self.b.gep(v.ptr,
                                             [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                hit = self.b.icmp_unsigned("==", tag, ir.Constant(I8, slot))
                r = hit if isinstance(op0, ast.Is) else self.b.not_(hit)
                return V(TBool(), ssa=r)
            has = self.b.load(self.b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            r = self.b.not_(has) if isinstance(op0, ast.Is) else has
            return V(TBool(), ssa=r)
        if isinstance(op0, (ast.In, ast.NotIn)):
            ct = self._t(e.comparators[0])
            if isinstance(ct, TPyVal):
                recv = self._expr(e.comparators[0], "ref")
                needle = self._coerce(self._expr(e.left, "val", expect=TPyVal()),
                                      TPyVal())
                out = self._entry_alloca(I8)
                st = self.b.call(self._rt("rt_pyval_contains"),
                                 [recv.ssa, needle.ssa, out])
                self._check_err_i8(st)
                res = self.b.trunc(self.b.load(out), I1)
                if isinstance(op0, ast.NotIn):
                    res = self.b.not_(res)
                return V(TBool(), ssa=res)
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
            elif isinstance(ct, TBytes):
                r = self.b.call(self._rt("rt_bytes_contains"), [recv.ssa, needle.ssa])
                res = self.b.trunc(r, I1)
            elif isinstance(ct, TDict):
                found, _ = self._dict_scan(recv.ptr, ct, needle)
                res = found
            else:
                assert isinstance(ct, (TList, TSet))
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
        if any(isinstance(self._t(o), TPyVal) for o in operands):
            pvals = [self._coerce(self._expr(o, "val", expect=TPyVal()), TPyVal())
                     for o in operands]
            acc = None
            for i, op in enumerate(e.ops):
                r = self.b.call(self._rt("rt_pyval_eq"),
                                [pvals[i].ssa, pvals[i + 1].ssa])
                c = self.b.trunc(r, I1)
                if isinstance(op, ast.NotEq):
                    c = self.b.not_(c)
                acc = c if acc is None else self.b.and_(acc, c)
            return V(TBool(), ssa=acc)
        vals = []
        opt_t = next((self._t(o) for o in operands if isinstance(self._t(o), TOptional)), None)
        for o in operands:
            t = self._t(o)
            v = self._expr(o, "ref" if self._is_agg(t) else "val")
            if opt_t is not None and not isinstance(t, TOptional):
                v = self._coerce(v, opt_t)
            vals.append(v)
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
            self._consume(out)
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
                self._store_into(out.ptr, v)
                self._drain(mark_t, mark_b)
            else:
                self.b.store(v.ssa, out)
                self._drain(mark_t, mark_b)
            self.b.branch(end)
        self.b.position_at_end(end)
        if agg:
            self.stmt_temps.append(out)
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

    def _comp_expr(self, node, expect: Type | None = None) -> V:
        kind = self.tc.loop_iter_kind[id(node)]
        gen = node.generators[0]
        targets = [gen.target] if isinstance(gen.target, ast.Name) \
            else list(gen.target.elts)
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        t = self._t(node)
        if expect is not None and type(expect) is type(t) and expect != t:
            t = expect
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
            elif isinstance(node, ast.SetComp):
                ev = self._coerce(self._expr(node.elt, "val", expect=t.elem), t.elem)
                self._set_add(out.ptr, t.elem, ev)
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
        ftv = self.tc.expr_types.get(id(node.func))
        if isinstance(ftv, TFunc):
            return self._func_value_call(node, ftv)
        if isinstance(node.func, ast.Attribute):
            return self._method_call(node)
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if id(node) in self.tc.move_calls:
            return self._expr(node.args[0], mode)
        chk = self.tc.isinstance_checks.get(id(node))
        if chk is not None:
            declared, member = chk
            assert isinstance(declared, TUnion)
            v = self._expr(node.args[0], "ref")
            tag = self.b.load(self.b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
            slot = union_slot(member, declared)
            return V(TBool(), ssa=self.b.icmp_unsigned("==", tag, ir.Constant(I8, slot)))
        if id(node) in self.tc.ctor_calls:
            return self._ctor_call(node)
        if id(node) in self.tc.enum_calls:
            return self._enum_lookup(node)
        if id(node) in self.tc.spawn_calls:
            return self._spawn_call(node)
        if id(node) in self.tc.thread_calls:
            return self._thread_call(node)
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
        if name == "pyval_kind":
            v = self._expr(node.args[0], "ref")
            tmp = self._temp(TStr())
            self.b.call(self._rt("rt_pyval_kind"), [v.ssa, tmp.ptr])
            return tmp
        if name == "pyval_json":
            v = self._expr(node.args[0], "ref")
            ea = self._expr(node.args[1], "val").ssa
            cp = self._expr(node.args[2], "val").ssa
            tmp = self._temp(TStr())
            st = self.b.call(self._rt("rt_pyval_json"),
                             [v.ssa, self.b.zext(ea, I8), self.b.zext(cp, I8), tmp.ptr])
            self._check_err_i8(st)
            return tmp
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
        if name in self.mod.rtlib_imports:
            return self._rtlib_call(node, self.mod.rtlib_imports[name])
        target = self.tc.call_targets.get(id(node))
        if target is not None:
            return self._user_call(node, self.tc.sigs[target])
        sig = self.tc._resolve_callee(self.mod, name)
        if sig is not None:
            return self._user_call(node, sig)
        return self._builtin(node, name)

    def _send_words(self, t: Type) -> int:
        """How many 8-byte env words a Send argument of type t occupies."""
        if isinstance(t, TClass):
            info = self.tc.classes[(t.module, t.name)]
            return max(len(info.field_order), 1)
        return 1

    def _pack_send_env(self, args: list[ast.expr], sig):
        """Copy Send arguments into a fresh heap buffer of 8-byte words (D9 by-copy boundary)."""
        b = self.b
        n = max(sum(self._send_words(p.typ) for p in sig.params), 1)
        env = b.call(self._rt("rt_buf_alloc"), [ir.Constant(I64, 8 * n)])
        envw = b.bitcast(env, I64.as_pointer())
        off = 0
        for a, p in zip(args, sig.params):
            if isinstance(p.typ, TClass):
                v = self._expr(a, "ref")
                info = self.tc.classes[(p.typ.module, p.typ.name)]
                for j, f in enumerate(info.field_order):
                    fv = b.load(b.gep(v.ptr, [ir.Constant(I32, 0), ir.Constant(I32, j)]))
                    ft = info.fields[f]
                    if isinstance(ft, TFloat):
                        w = b.bitcast(fv, I64)
                    elif isinstance(ft, TBool):
                        w = b.zext(fv, I64)
                    else:
                        w = fv
                    b.store(w, b.gep(envw, [ir.Constant(I64, off + j)]))
                off += self._send_words(p.typ)
                continue
            slot = b.gep(envw, [ir.Constant(I64, off)])
            off += 1
            if isinstance(p.typ, TStr):
                v = self._expr(a, "ref")
                tmp = self._temp(TStr())
                b.call(self._rt("rt_str_clone"), [v.ptr, tmp.ptr])
                w = b.ptrtoint(b.call(self._rt("rt_str_send"), [tmp.ptr]), I64)
                self._consume(tmp)
            elif isinstance(p.typ, TBytes):
                h0 = self._expr(a, "ref").ssa
                b.call(self._rt("rt_bytes_clone"), [h0])
                w = b.ptrtoint(b.call(self._rt("rt_bytes_send"), [h0]), I64)
            else:
                v = self._coerce(self._expr(a, "val", expect=p.typ), p.typ)
                if isinstance(p.typ, TFloat):
                    w = b.bitcast(v.ssa, I64)
                elif isinstance(p.typ, TBool):
                    w = b.zext(v.ssa, I64)
                else:
                    w = v.ssa
            b.store(w, slot)
        return env

    def _spawn_call(self, node: ast.Call) -> V:
        """Lower spawn(f, args...): pack Send args into a buffer, start the thread."""
        key = self.tc.spawn_calls[id(node)]
        sig = self.tc.sigs[key]
        env = self._pack_send_env(node.args[1:], sig)
        wrapper = self._thread_wrapper(key, sig)
        task = self._t(node).task
        h = self.b.call(self._rt("rt_task_spawn" if task else "rt_thread_spawn"),
                        [self.b.bitcast(wrapper, I8P), env])
        return self._register_temp_ssa(TJoin(sig.ret, task=task), h)

    def _thread_call(self, node: ast.Call) -> V:
        """Lower Thread(target=..)/Timer(..): pack args now, run at start()."""
        info = self.tc.thread_calls[id(node)]
        key = info["target"]
        sig = self.tc.sigs[key]
        b = self.b
        env = self._pack_send_env(info["args"], sig)
        wrapper = self._thread_wrapper(key, sig)
        if info["name"] is not None:
            name = self._expr(info["name"], "ref")
            name_ptr, has_name = name.ptr, ir.Constant(I64, 1)
        else:
            name_ptr, has_name = ir.Constant(SSTRP, None), ir.Constant(I64, 0)
        daemon = ir.Constant(I8, 0)
        if info["daemon"] is not None:
            daemon = b.zext(self._expr(info["daemon"], "val").ssa, I8)
        delay = ir.Constant(I64, 0)
        if info["interval"] is not None:
            iv = self._coerce(self._expr(info["interval"], "val", expect=TFloat()), TFloat())
            delay = b.fptosi(b.fmul(iv.ssa, ir.Constant(F64, 1000.0)), I64)
        target = self._temp(TStr())
        p, n = self._cstr("" if info["timer"] else key[1])
        b.call(self._rt("rt_str_new"), [p, ir.Constant(I64, n), target.ptr])
        h = b.call(self._rt("rt_thread_new"),
                   [b.bitcast(wrapper, I8P), env, name_ptr, has_name, daemon, delay, target.ptr])
        return self._register_temp_ssa(TThread(), h)

    def _thread_wrapper(self, key: tuple[str, str], sig) -> ir.Function:
        """The extern-ABI entry a spawned thread runs: unpack env, call, box result."""
        if key in self.thread_wrappers:
            return self.thread_wrappers[key]
        fn = ir.Function(self.module, ir.FunctionType(I8P, [I8P]),
                         name=self._sanitize(f"tw_{key[0]}_{key[1]}"))
        fn.linkage = "internal"
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        envw = b.bitcast(fn.args[0], I64.as_pointer())
        args = []
        off = 0
        for p in sig.params:
            if isinstance(p.typ, TClass):
                info = self.tc.classes[(p.typ.module, p.typ.name)]
                slot = b.alloca(self._lty(p.typ))
                for j, f in enumerate(info.field_order):
                    w = b.load(b.gep(envw, [ir.Constant(I64, off + j)]))
                    ft = info.fields[f]
                    if isinstance(ft, TFloat):
                        fv = b.bitcast(w, F64)
                    elif isinstance(ft, TBool):
                        fv = b.trunc(w, self._lty(TBool()))
                    else:
                        fv = w
                    b.store(fv, b.gep(slot, [ir.Constant(I32, 0), ir.Constant(I32, j)]))
                args.append(b.load(slot))
                off += self._send_words(p.typ)
                continue
            w = b.load(b.gep(envw, [ir.Constant(I64, off)]))
            off += 1
            if isinstance(p.typ, TStr):
                slot = b.alloca(self._lty(TStr()))
                b.call(self._rt("rt_str_recv"), [b.inttoptr(w, I8P), slot])
                args.append(b.load(slot))
            elif isinstance(p.typ, TBytes):
                args.append(b.call(self._rt("rt_bytes_recv"), [b.inttoptr(w, I8P)]))
            elif isinstance(p.typ, TFloat):
                args.append(b.bitcast(w, F64))
            elif isinstance(p.typ, TBool):
                args.append(b.trunc(w, self._lty(TBool())))
            else:
                args.append(w)
        n = max(sum(self._send_words(p.typ) for p in sig.params), 1)
        b.call(self._rt("rt_buf_free"), [fn.args[0], ir.Constant(I64, 8 * n)])
        res = b.call(self.funcs[key], args)
        errbit = res if isinstance(sig.ret, TNone) else b.extract_value(res, 0)
        okb = fn.append_basic_block("ok")
        errb = fn.append_basic_block("err")
        b.cbranch(errbit, errb, okb)
        b.position_at_end(errb)
        b.ret(b.call(self._rt("rt_box_err"), []))
        b.position_at_end(okb)
        if isinstance(sig.ret, TNone):
            w = ir.Constant(I64, 0)
        else:
            val = b.extract_value(res, 1)
            if isinstance(sig.ret, TStr):
                slot2 = b.alloca(self._lty(TStr()))
                b.store(val, slot2)
                w = b.ptrtoint(b.call(self._rt("rt_str_send"), [slot2]), I64)
            elif isinstance(sig.ret, TBytes):
                w = b.ptrtoint(b.call(self._rt("rt_bytes_send"), [val]), I64)
            elif isinstance(sig.ret, TFloat):
                w = b.bitcast(val, I64)
            elif isinstance(sig.ret, TBool):
                w = b.zext(val, I64)
            else:
                w = val
        b.ret(b.call(self._rt("rt_box_ok"), [w]))
        self.thread_wrappers[key] = fn
        return fn

    def _rtlib_call(self, node: ast.Call, rf) -> V:
        """Lower a runtime-backed library call (rtlib.py) to its rt.rs extern."""
        b = self.b
        args = []
        for a, p in zip(node.args, rf.params):
            if p == "s":
                v = self._expr(a, "ref")
                args.append(v.ptr)
                continue
            if p == "y":
                v = self._expr(a, "ref")
                args.append(v.ssa)
                continue
            if p == "p":
                v = self._coerce(self._expr(a, "val", expect=TPyVal()), TPyVal())
                args.append(v.ssa)
                continue
            pt = TFloat() if p == "f" else TInt()
            v = self._coerce(self._expr(a, "val", expect=pt), pt)
            args.append(v.ssa)
        if rf.ret in ("y", "p"):
            out = self._entry_alloca(I8P)
            if rf.can_raise:
                st = b.call(self._rt(rf.rt), args + [out])
                self._check_err_i8(st)
            else:
                b.call(self._rt(rf.rt), args + [out])
            return self._register_temp_ssa(TBytes() if rf.ret == "y" else TPyVal(), b.load(out))
        if rf.ret in ("s", "S"):
            tmp = self._temp(TStr() if rf.ret == "s" else TList(TStr()))
            if rf.can_raise:
                st = b.call(self._rt(rf.rt), args + [tmp.ptr])
                self._check_err_i8(st)
            else:
                b.call(self._rt(rf.rt), args + [tmp.ptr])
            return tmp
        if rf.can_raise:
            if rf.ret == "n":
                st = b.call(self._rt(rf.rt), args)
                self._check_err_i8(st)
                return V(TNone(), ssa=ir.Constant(I1, 0))
            if rf.ret == "b":
                slot = self._entry_alloca(I8)
                st = b.call(self._rt(rf.rt), args + [slot])
                self._check_err_i8(st)
                return V(TBool(), ssa=b.trunc(b.load(slot), I1))
            slot = self._entry_alloca(F64 if rf.ret == "f" else I64)
            st = b.call(self._rt(rf.rt), args + [slot])
            self._check_err_i8(st)
            return V(TFloat() if rf.ret == "f" else TInt(), ssa=b.load(slot))
        r = b.call(self._rt(rf.rt), args)
        if rf.ret == "n":
            return V(TNone(), ssa=ir.Constant(I1, 0))
        if rf.ret == "b":
            return V(TBool(), ssa=b.trunc(r, I1))
        return V(TFloat() if rf.ret == "f" else TInt(), ssa=r)

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
        if not info.typevars:
            psig = self.tc.sigs.get((cmod, f"{cname}.__post_init__"))
            if psig is not None:
                self._finish_call(self.funcs[(cmod, psig.name)], [tmp.ptr], TNone())
        return tmp

    def _str_from_texts(self, texts: list[str], idx) -> V:
        """A str temp holding texts[idx], chosen at runtime."""
        p, n = self._select_cstr(self.b, texts, idx)
        tmp = self._temp(TStr())
        self.b.call(self._rt("rt_str_new"), [p, n, tmp.ptr])
        return tmp

    def _enum_attr(self, node: ast.Attribute) -> V:
        """Lower `member.value` / `member.name` on an enum value."""
        t = self._t(node.value)
        info = self.tc.enums[(t.module, t.name)]
        idx = self._expr(node.value, "val").ssa
        if node.attr == "name":
            return self._str_from_texts([m for m, _ in info.members], idx)
        if isinstance(info.value_type, TStr):
            return self._str_from_texts([str(v) for _, v in info.members], idx)
        res = ir.Constant(I64, int(info.members[0][1]))
        for i, (_, val) in enumerate(info.members[1:], start=1):
            hit = self.b.icmp_signed("==", idx, ir.Constant(I64, i))
            res = self.b.select(hit, ir.Constant(I64, int(val)), res)
        return V(TInt(), ssa=res)

    def _enum_lookup(self, node: ast.Call) -> V:
        """Lower `Color(value)`: value -> ordinal, ValueError when unmatched."""
        key = self.tc.enum_calls[id(node)]
        info = self.tc.enums[key]
        arg = self._expr(node.args[0], "val")
        found = ir.Constant(I64, -1)
        for i, (_, val) in enumerate(info.members):
            if isinstance(info.value_type, TStr):
                lit = self._temp(TStr())
                p, n = self._cstr(str(val))
                self.b.call(self._rt("rt_str_new"), [p, ir.Constant(I64, n), lit.ptr])
                hit = self.b.trunc(self.b.call(self._rt("rt_str_eq"), [arg.ptr, lit.ptr]), I1)
            else:
                hit = self.b.icmp_signed("==", arg.ssa, ir.Constant(I64, int(val)))
            found = self.b.select(hit, ir.Constant(I64, i), found)
        bad = self.fn.append_basic_block("enum_bad")
        ok = self.fn.append_basic_block("enum_ok")
        self.b.cbranch(self.b.icmp_signed("<", found, ir.Constant(I64, 0)), bad, ok)
        self.b.position_at_end(bad)
        sb = self.b.call(self._rt("rt_sb_new"), [])
        self._push(self.b, arg.ty, arg, sb, as_repr=True)
        self._push_bytes(self.b, sb, f" is not a valid {info.name}")
        msg = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_sb_finish"), [sb, msg])
        kp, kl = self._cstr("ValueError")
        ktmp = self._entry_alloca(SSTR)
        self.b.call(self._rt("rt_str_new"), [kp, ir.Constant(I64, kl), ktmp])
        self.b.call(self._rt("rt_raise"), [ktmp, msg])
        self.b.call(self._rt("rt_str_drop"), [ktmp])
        self.b.call(self._rt("rt_str_drop"), [msg])
        self._release_borrows(self.b)
        self.b.branch(self._err_target())
        self.b.position_at_end(ok)
        return V(TEnum(*key), ssa=found)

    def _arg_value(self, a: ast.expr, p) -> ir.Value:
        """Evaluate one call argument per the parameter's convention."""
        if p.conv in ("ref", "mut"):
            at = self.tc.expr_types.get(id(a))
            if isinstance(p.typ, TUnion) and at is not None and not isinstance(at, TUnion):
                if p.conv == "ref" and self._is_agg(at) and not at.is_copy() \
                        and isinstance(a, (ast.Name, ast.Attribute, ast.Subscript)):
                    src = self._expr(a, "ref")
                    tmp = self._temp(at)
                    self._clone_into(self.b, at, src.ptr, tmp.ptr)
                    return self._coerce(tmp, p.typ).ptr
                return self._coerce(self._expr(a, "val", expect=p.typ), p.typ).ptr
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
        if isinstance(ret, (TShared, TWeak, TFile, TBytes, TPyVal)):
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
            binary = isinstance(inner, TFile) and inner.binary
            if method == "read":
                if binary:
                    out = self._entry_alloca(I8P)
                    st = self.b.call(self._rt("rt_file_read_bytes"), [h, out])
                    self._check_err_i8(st)
                    return self._register_temp_ssa(TBytes(), self.b.load(out))
                tmp = self._temp(TStr())
                st = self.b.call(self._rt("rt_file_read"), [h, tmp.ptr])
                self._check_err_i8(st)
                return tmp
            if method == "write":
                out = self._entry_alloca(I64)
                if binary:
                    at = self._t(args[0])
                    v = self._expr(args[0], "ref")
                    if isinstance(at, TBytes):
                        st = self.b.call(self._rt("rt_file_write_bytes"), [h, v.ssa, out])
                    else:
                        st = self.b.call(self._rt("rt_file_write_ba"), [h, v.ptr, out])
                else:
                    s = self._expr(args[0], "ref")
                    st = self.b.call(self._rt("rt_file_write"), [h, s.ptr, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=self.b.load(out))
            if method == "close":
                self.b.call(self._rt("rt_file_close"), [h])
                return V(TNone(), ssa=ir.Constant(I1, 0))
            raise LLVMUnsupported(f"file method {method}")
        if isinstance(inner, TThread):
            h = self._expr(recv, "ref").ssa
            if method == "start":
                st = self.b.call(self._rt("rt_thread_start"), [h])
                self._check_err_i8(st)
                return V(TNone(), ssa=ir.Constant(I1, 0))
            if method == "join":
                ms = ir.Constant(I64, -1)
                if node.args and not (isinstance(node.args[0], ast.Constant)
                                      and node.args[0].value is None):
                    at = self._t(node.args[0])
                    if isinstance(at, TOptional):
                        ov = self._expr(node.args[0], "ref")
                        has = self.b.load(self.b.gep(ov.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
                        pv = self.b.load(self.b.gep(ov.ptr, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
                        fv = pv if isinstance(at.inner, TFloat) else self.b.sitofp(pv, F64)
                        msv = self.b.fptosi(self.b.fmul(fv, ir.Constant(F64, 1000.0)), I64)
                        ms = self.b.select(has, msv, ir.Constant(I64, -1))
                    else:
                        tv = self._coerce(self._expr(node.args[0], "val", expect=TFloat()), TFloat())
                        ms = self.b.fptosi(self.b.fmul(tv.ssa, ir.Constant(F64, 1000.0)), I64)
                st = self.b.call(self._rt("rt_thread_join_t"), [h, ms])
                self._check_err_i8(st)
                return V(TNone(), ssa=ir.Constant(I1, 0))
            if method == "is_alive":
                r = self.b.call(self._rt("rt_thread_alive"), [h])
                return V(TBool(), ssa=self.b.trunc(r, I1))
            if method == "cancel":
                self.b.call(self._rt("rt_thread_cancel"), [h])
                return V(TNone(), ssa=ir.Constant(I1, 0))
            raise LLVMUnsupported(f"Thread method {method}")
        if isinstance(inner, TJoin):
            h = self._expr(recv, "ref").ssa
            if inner.task and method == "done":
                r = self.b.call(self._rt("rt_task_done"), [h])
                return V(TBool(), ssa=self.b.trunc(r, I1))
            out = self._entry_alloca(I64)
            st = self.b.call(self._rt("rt_task_await" if inner.task else "rt_thread_join"), [h, out])
            self._check_err_i8(st)
            w = self.b.load(out)
            jr = inner.ret
            if isinstance(jr, TStr):
                tmp = self._temp(TStr())
                self.b.call(self._rt("rt_str_recv"), [self.b.inttoptr(w, I8P), tmp.ptr])
                return tmp
            if isinstance(jr, TBytes):
                return self._register_temp_ssa(
                    TBytes(), self.b.call(self._rt("rt_bytes_recv"),
                                          [self.b.inttoptr(w, I8P)]))
            if isinstance(jr, TFloat):
                return V(TFloat(), ssa=self.b.bitcast(w, F64))
            if isinstance(jr, TBool):
                return V(TBool(), ssa=self.b.trunc(w, self._lty(TBool())))
            if isinstance(jr, TNone):
                return V(TNone(), ssa=ir.Constant(I1, 0))
            return V(TInt(), ssa=w)
        if isinstance(inner, TBytes):
            return self._bytes_method(node, method, args)
        if isinstance(inner, TByteArray):
            return self._bytearray_method(node, method, args)
        if isinstance(inner, TList):
            return self._list_method(node, rt, inner, method, args)
        if isinstance(inner, TSet):
            return self._set_method(node, rt, inner, method, args)
        if isinstance(inner, TDict):
            return self._dict_method(node, rt, inner, method, args)
        if isinstance(inner, TStr):
            return self._str_method(node, rt, method, args)
        raise LLVMUnsupported(f"method '{method}' on {rt}")

    BYTES_H = {"strip": "rt_bytes_strip", "lstrip": "rt_bytes_lstrip",
               "rstrip": "rt_bytes_rstrip", "upper": "rt_bytes_upper",
               "lower": "rt_bytes_lower"}
    BYTES_I = {"find": "rt_bytes_find", "count": "rt_bytes_count"}
    BYTES_B = {"startswith": "rt_bytes_startswith", "endswith": "rt_bytes_endswith"}

    def _bytes_method(self, node: ast.Call, method: str, args) -> V:
        """Lower a method call on an immutable bytes value."""
        if method == "fromhex":
            s = self._expr(args[0], "ref")
            out = self._entry_alloca(I8P)
            st = self.b.call(self._rt("rt_bytes_fromhex"), [s.ptr, out])
            self._check_err_i8(st)
            return self._register_temp_ssa(TBytes(), self.b.load(out))
        h = self._expr(node.func.value, "ref").ssa
        if method in self.BYTES_H:
            r = self.b.call(self._rt(self.BYTES_H[method]), [h])
            return self._register_temp_ssa(TBytes(), r)
        if method in self.BYTES_I:
            a = self._expr(args[0], "ref").ssa
            return V(TInt(), ssa=self.b.call(self._rt(self.BYTES_I[method]), [h, a]))
        if method in self.BYTES_B:
            a = self._expr(args[0], "ref").ssa
            r = self.b.call(self._rt(self.BYTES_B[method]), [h, a])
            return V(TBool(), ssa=self.b.trunc(r, I1))
        if method == "replace":
            a = self._expr(args[0], "ref").ssa
            c = self._expr(args[1], "ref").ssa
            r = self.b.call(self._rt("rt_bytes_replace"), [h, a, c])
            return self._register_temp_ssa(TBytes(), r)
        if method == "split":
            tmp = self._temp(TList(TBytes()))
            self.b.store(ir.Constant(SLIST, None), tmp.ptr)
            if args:
                sep = self._expr(args[0], "ref").ssa
                st = self.b.call(self._rt("rt_bytes_split"), [h, sep, tmp.ptr])
                self._check_err_i8(st)
            else:
                self.b.call(self._rt("rt_bytes_split_ws"), [h, tmp.ptr])
            return tmp
        if method == "join":
            items = self._expr(args[0], "ref")
            r = self.b.call(self._rt("rt_bytes_join"), [h, items.ptr])
            return self._register_temp_ssa(TBytes(), r)
        if method == "hex":
            tmp = self._temp(TStr())
            self.b.call(self._rt("rt_bytes_hex"), [h, tmp.ptr])
            return tmp
        if method == "decode":
            tmp = self._temp(TStr())
            st = self.b.call(self._rt("rt_bytes_decode"), [h, tmp.ptr])
            self._check_err_i8(st)
            return tmp
        raise LLVMUnsupported(f"bytes method {method}")

    def _bytearray_method(self, node: ast.Call, method: str, args) -> V:
        """Lower a method call on a mutable bytearray."""
        none = V(TNone(), ssa=ir.Constant(I1, 0))
        if method == "append":
            recv = self._recv(node.func.value, True)
            v = self._expr(args[0], "val").ssa
            st = self.b.call(self._rt("rt_ba_push"), [recv.ptr, v])
            self._check_err_i8(st)
            return none
        if method == "extend":
            recv = self._recv(node.func.value, True)
            at = self._t(args[0])
            v = self._expr(args[0], "ref")
            if isinstance(at, TBytes):
                self.b.call(self._rt("rt_ba_extend_b"), [recv.ptr, v.ssa])
            else:
                self.b.call(self._rt("rt_ba_extend_a"), [recv.ptr, v.ptr])
            return none
        recv = self._recv(node.func.value, False)
        if method == "hex":
            tmp = self._temp(TStr())
            self.b.call(self._rt("rt_ba_hex"), [recv.ptr, tmp.ptr])
            return tmp
        if method == "decode":
            tmp = self._temp(TStr())
            st = self.b.call(self._rt("rt_ba_decode"), [recv.ptr, tmp.ptr])
            self._check_err_i8(st)
            return tmp
        raise LLVMUnsupported(f"bytearray method {method}")

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

    def _set_method(self, node, rt, t: TSet, method: str, args) -> V:
        """Emit a Tier-2 set method call."""
        elem = t.elem
        esize = ir.Constant(I64, self._sizeof(elem))
        none = V(TNone(), ssa=ir.Constant(I1, 0))
        if method == "add":
            v = self._coerce(self._expr(args[0], "val", expect=elem), elem)
            recv = self._recv(node.func.value, True)
            self._set_add(recv.ptr, elem, v)
            return none
        if method in ("discard", "remove"):
            v = self._coerce(self._expr(args[0], "val", expect=elem), elem)
            recv = self._recv(node.func.value, True)
            found, pos = self._set_scan(recv.ptr, elem, v)
            hit = self.fn.append_basic_block("srem.hit")
            miss = self.fn.append_basic_block("srem.miss")
            done = self.fn.append_basic_block("srem.done")
            self.b.cbranch(found, hit, miss)
            self.b.position_at_end(hit)
            p = self._elem_ptr(self.b, recv.ptr, elem, pos)
            if self._droppable(elem):
                self._drop(self.b, elem, self._as_v(self.b, elem, p))
            self.b.call(self._rt("rt_list_remove"), [recv.ptr, esize, pos])
            self.b.branch(done)
            self.b.position_at_end(miss)
            if method == "remove":
                self._raise_key_repr(elem, v)
            else:
                self.b.branch(done)
            self.b.position_at_end(done)
            if self._droppable(elem):
                self._drop(self.b, elem, v)
            self._consume(v)
            return none
        if method == "clear":
            recv = self._recv(node.func.value, True)
            if self._droppable(elem):
                self._set_each(recv.ptr, elem,
                               lambda p: self._drop(self.b, elem, self._as_v(self.b, elem, p)))
            self._set_list_len(self.b, recv.ptr, ir.Constant(I64, 0))
            return none
        if method == "pop":
            recv = self._recv(node.func.value, True)
            n = self._list_len(self.b, recv.ptr)
            self._cond_raise_static(self.b.icmp_signed("==", n, ir.Constant(I64, 0)),
                                    "KeyError", "pop from an empty set")
            p = self._elem_ptr(self.b, recv.ptr, elem, ir.Constant(I64, 0))
            if self._is_agg(elem):
                out = self._temp(elem)
                self.b.store(self.b.load(p), out.ptr)
            else:
                out = V(elem, ssa=self.b.load(p))
            self.b.call(self._rt("rt_list_remove"), [recv.ptr, esize, ir.Constant(I64, 0)])
            return out
        if method in ("update", "difference_update", "intersection_update"):
            other = self._expr(args[0], "ref")
            recv = self._recv(node.func.value, True)
            if method == "update":
                self._set_each(other.ptr, elem,
                               lambda p: self._set_add(recv.ptr, elem,
                                                       self._read_place(elem, p, "val")))
                return none
            keep = self._temp(t, register=False)
            self.b.store(ir.Constant(SLIST, None), keep.ptr)

            def sift(p):
                inn = self._set_contains_ptr(other.ptr, elem, p)
                cond = self.b.not_(inn) if method == "difference_update" else inn
                yes = self.fn.append_basic_block("supd.keep")
                no = self.fn.append_basic_block("supd.skip")
                self.b.cbranch(cond, yes, no)
                self.b.position_at_end(yes)
                self._list_push(keep.ptr, elem, self._as_v(self.b, elem, p))
                self.b.branch(no)
                self.b.position_at_end(no)
                with self.b.if_then(self.b.not_(cond)):
                    if self._droppable(elem):
                        self._drop(self.b, elem, self._as_v(self.b, elem, p))

            self._set_each(recv.ptr, elem, sift)
            self.b.call(self._rt("rt_list_free"), [recv.ptr, esize])
            self.b.store(self.b.load(keep.ptr), recv.ptr)
            return none
        if method in ("union", "intersection", "difference", "symmetric_difference"):
            recv = self._recv(node.func.value, False)
            other = self._expr(args[0], "ref")
            out = self._temp(t)
            self.b.store(ir.Constant(SLIST, None), out.ptr)

            def take_left(p):
                if method == "union":
                    cond = None
                else:
                    inn = self._set_contains_ptr(other.ptr, elem, p)
                    cond = inn if method == "intersection" else self.b.not_(inn)
                if cond is None:
                    self._set_add(out.ptr, elem, self._read_place(elem, p, "val"))
                else:
                    with self.b.if_then(cond):
                        self._set_add(out.ptr, elem, self._read_place(elem, p, "val"))

            self._set_each(recv.ptr, elem, take_left)
            if method in ("union", "symmetric_difference"):
                def take_right(p):
                    if method == "union":
                        self._set_add(out.ptr, elem, self._read_place(elem, p, "val"))
                    else:
                        with self.b.if_then(self.b.not_(
                                self._set_contains_ptr(recv.ptr, elem, p))):
                            self._set_add(out.ptr, elem, self._read_place(elem, p, "val"))

                self._set_each(other.ptr, elem, take_right)
            return out
        if method in ("issubset", "issuperset", "isdisjoint"):
            recv = self._recv(node.func.value, False)
            other = self._expr(args[0], "ref")
            acc = self._entry_alloca(I1)
            self.b.store(ir.Constant(I1, method != "isdisjoint"), acc)
            src, dst = (recv, other) if method != "issuperset" else (other, recv)

            def scan(p):
                inn = self._set_contains_ptr(dst.ptr, elem, p)
                if method == "isdisjoint":
                    self.b.store(self.b.or_(self.b.load(acc), inn), acc)
                else:
                    self.b.store(self.b.and_(self.b.load(acc), inn), acc)

            self._set_each(src.ptr, elem, scan)
            r = self.b.load(acc)
            if method == "isdisjoint":
                r = self.b.not_(r)
            return V(TBool(), ssa=r)
        if method == "copy":
            recv = self._recv(node.func.value, False)
            out = self._temp(t)
            self.b.call(self._clone_fn(t), [recv.ptr, out.ptr])
            return out
        raise LLVMUnsupported(f"set method {method}")

    def _raise_key_repr(self, t: Type, key: V) -> None:
        """raise KeyError(repr(key)) — CPython's message for set.remove misses."""
        sb = self.b.call(self._rt("rt_sb_new"), [])
        self._push(self.b, t, key, sb, as_repr=True)
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
        if method == "encode":
            r = self.b.call(self._rt("rt_str_encode"), [recv.ptr])
            return self._register_temp_ssa(TBytes(), r)
        raise LLVMUnsupported(f"str method {method}")

    # ---------- builtins ----------

    def _builtin(self, node: ast.Call, name: str) -> V:
        b = self.b
        args = node.args
        if name in ("set", "frozenset"):
            t = self._t(node)
            assert isinstance(t, TSet)
            out = self._temp(t)
            self.b.store(ir.Constant(SLIST, None), out.ptr)
            if args:
                src = self._expr(args[0], "ref")
                st = self._t(args[0])
                if isinstance(st, TShared):
                    src = self._recv(args[0], False)
                    st = st.inner
                n = self._list_len(self.b, src.ptr)

                def body(i):
                    p = self._elem_ptr(self.b, src.ptr, t.elem, i)
                    self._set_add(out.ptr, t.elem, self._read_place(t.elem, p, "val"))

                self._simple_loop(n, body)
            return out
        if name == "len":
            t = self._t(args[0])
            if isinstance(t, TShared):
                recv = self._recv(args[0], False)
                t = t.inner
            else:
                recv = self._expr(args[0], "ref")
            if isinstance(t, (TList, TDict, TSet, TByteArray)):
                return V(TInt(), ssa=self._list_len(b, recv.ptr))
            if isinstance(t, TBytes):
                return V(TInt(), ssa=b.call(self._rt("rt_bytes_len"), [recv.ssa]))
            if isinstance(t, TPyVal):
                out = self._entry_alloca(I64)
                st = b.call(self._rt("rt_pyval_len"), [recv.ssa, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=b.load(out))
            return V(TInt(), ssa=b.call(self._rt("rt_str_len"), [recv.ptr]))
        if name in ("bytes", "bytearray"):
            is_b = name == "bytes"
            if not args:
                if is_b:
                    p, n = self._cbytes(b"")
                    h = b.call(self._rt("rt_bytes_new"), [p, ir.Constant(I64, 0)])
                    return self._register_temp_ssa(TBytes(), h)
                tmp = self._temp(TByteArray())
                b.store(ir.Constant(SLIST, None), tmp.ptr)
                return tmp
            t0 = self._t(args[0])
            if is_b and isinstance(t0, TPyVal):
                v = self._expr(args[0], "ref")
                out = self._entry_alloca(I8P)
                st = b.call(self._rt("rt_pyval_to_bytes"), [v.ssa, out])
                self._check_err_i8(st)
                return self._register_temp_ssa(TBytes(), b.load(out))
            if isinstance(t0, TInt):
                nval = self._expr(args[0], "val").ssa
                if is_b:
                    out = self._entry_alloca(I8P)
                    st = b.call(self._rt("rt_bytes_zeros"), [nval, out])
                    self._check_err_i8(st)
                    return self._register_temp_ssa(TBytes(), b.load(out))
                tmp = self._temp(TByteArray())
                b.store(ir.Constant(SLIST, None), tmp.ptr)
                st = b.call(self._rt("rt_ba_zeros"), [nval, tmp.ptr])
                self._check_err_i8(st)
                return tmp
            if isinstance(t0, TList):
                xs = self._expr(args[0], "ref")
                if is_b:
                    out = self._entry_alloca(I8P)
                    st = b.call(self._rt("rt_bytes_from_ints"), [xs.ptr, out])
                    self._check_err_i8(st)
                    return self._register_temp_ssa(TBytes(), b.load(out))
                tmp = self._temp(TByteArray())
                b.store(ir.Constant(SLIST, None), tmp.ptr)
                st = b.call(self._rt("rt_ba_from_ints"), [xs.ptr, tmp.ptr])
                self._check_err_i8(st)
                return tmp
            if isinstance(t0, TBytes):
                if is_b:
                    return self._expr(args[0], "val")
                src = self._expr(args[0], "ref")
                tmp = self._temp(TByteArray())
                b.store(ir.Constant(SLIST, None), tmp.ptr)
                b.call(self._rt("rt_ba_from_bytes"), [src.ssa, tmp.ptr])
                return tmp
            src = self._expr(args[0], "ref")
            if is_b:
                h = b.call(self._rt("rt_ba_to_bytes"), [src.ptr])
                return self._register_temp_ssa(TBytes(), h)
            tmp = self._temp(TByteArray())
            b.store(ir.Constant(SLIST, None), tmp.ptr)
            b.call(self._rt("rt_ba_clone"), [src.ptr, tmp.ptr])
            return tmp
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
            if isinstance(t, TPyVal):
                v = self._expr(args[0], "ref")
                out = self._entry_alloca(I64)
                st = b.call(self._rt("rt_pyval_to_int"), [v.ssa, out])
                self._check_err_i8(st)
                return V(TInt(), ssa=b.load(out))
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
            if isinstance(t, TPyVal):
                v = self._expr(args[0], "ref")
                out = self._entry_alloca(F64)
                st = b.call(self._rt("rt_pyval_to_float"), [v.ssa, out])
                self._check_err_i8(st)
                return V(TFloat(), ssa=b.load(out))
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
            if isinstance(t, TPyVal):
                v = self._expr(args[0], "ref")
                r = b.call(self._rt("rt_pyval_truthy"), [v.ssa])
                return V(TBool(), ssa=b.trunc(r, I1))
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
