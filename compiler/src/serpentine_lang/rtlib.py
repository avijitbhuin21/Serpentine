"""Runtime-backed library modules — the [R] path of docs/libraries.md.

A compiler-known whitelist mapping `from serp_math import sqrt` (and friends)
to runtime primitives: Backend A calls a prelude.rs function, Backend B calls
an `extern "C"` symbol in rt.rs. The PyPI packages (libs/serp-*) carry a pure
CPython delegate so the same file dual-runs; the native build never reads
those delegate sources — imports of these members are intercepted in the
frontend before file resolution.

Constants (serp_math.pi etc.) are folded into the AST as float literals at
load time, so every later stage sees an ordinary literal.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RtFn:
    """Signature + lowering info for one runtime-backed library function."""

    module: str
    name: str
    params: tuple[str, ...]   # 'f' = float (int coerces), 'i' = int, 's' = str, 'y' = bytes
    ret: str                  # 'f' | 'i' | 'b' | 'n' | 's' (str) | 'S' (list[str]) | 'y' (bytes)
    can_raise: bool
    rust: str                 # Backend-A prelude function name
    rt: str                   # Backend-B extern "C" symbol name


RTLIB_FUNCS: dict[tuple[str, str], RtFn] = {}
RTLIB_CONSTS: dict[tuple[str, str], float] = {}


def _fn(module: str, name: str, params: str, ret: str, can_raise: bool,
        rust: str, rt: str) -> None:
    """Register one runtime-backed function in the whitelist."""
    RTLIB_FUNCS[(module, name)] = RtFn(module, name, tuple(params), ret,
                                       can_raise, rust, rt)


_fn("serp_math_core", "c_sqrt", "f", "f", True, "serp_math_sqrt", "rt_math_sqrt")
_fn("serp_math_core", "c_sin", "f", "f", False, "serp_math_sin", "rt_math_sin")
_fn("serp_math_core", "c_cos", "f", "f", False, "serp_math_cos", "rt_math_cos")
_fn("serp_math_core", "c_tan", "f", "f", False, "serp_math_tan", "rt_math_tan")
_fn("serp_math_core", "c_log", "f", "f", True, "serp_math_log", "rt_math_log")
_fn("serp_math_core", "c_exp", "f", "f", True, "serp_math_exp", "rt_math_exp")
_fn("serp_math_core", "c_pow", "ff", "f", True, "serp_math_pow", "rt_math_pow")
_fn("serp_math_core", "c_floor", "f", "i", True, "serp_math_floor", "rt_math_floor")
_fn("serp_math_core", "c_ceil", "f", "i", True, "serp_math_ceil", "rt_math_ceil")
_fn("serp_math_core", "c_isnan", "f", "b", False, "serp_math_isnan", "rt_math_isnan")
_fn("serp_math_core", "c_isinf", "f", "b", False, "serp_math_isinf", "rt_math_isinf")
_fn("serp_math_core", "c_isfinite", "f", "b", False, "serp_math_isfinite", "rt_math_isfinite")
_fn("serp_math_core", "c_acos", "f", "f", True, "serp_math_acos", "rt_math_acos")
_fn("serp_math_core", "c_asin", "f", "f", True, "serp_math_asin", "rt_math_asin")
_fn("serp_math_core", "c_atan", "f", "f", False, "serp_math_atan", "rt_math_atan")
_fn("serp_math_core", "c_atan2", "ff", "f", False, "serp_math_atan2", "rt_math_atan2")
_fn("serp_math_core", "c_acosh", "f", "f", True, "serp_math_acosh", "rt_math_acosh")
_fn("serp_math_core", "c_asinh", "f", "f", False, "serp_math_asinh", "rt_math_asinh")
_fn("serp_math_core", "c_atanh", "f", "f", True, "serp_math_atanh", "rt_math_atanh")
_fn("serp_math_core", "c_cosh", "f", "f", True, "serp_math_cosh", "rt_math_cosh")
_fn("serp_math_core", "c_sinh", "f", "f", True, "serp_math_sinh", "rt_math_sinh")
_fn("serp_math_core", "c_tanh", "f", "f", False, "serp_math_tanh", "rt_math_tanh")
_fn("serp_math_core", "c_cbrt", "f", "f", False, "serp_math_cbrt", "rt_math_cbrt")
_fn("serp_math_core", "c_degrees", "f", "f", False, "serp_math_degrees", "rt_math_degrees")
_fn("serp_math_core", "c_radians", "f", "f", False, "serp_math_radians", "rt_math_radians")
_fn("serp_math_core", "c_exp2", "f", "f", True, "serp_math_exp2", "rt_math_exp2")
_fn("serp_math_core", "c_expm1", "f", "f", True, "serp_math_expm1", "rt_math_expm1")
_fn("serp_math_core", "c_fabs", "f", "f", False, "serp_math_fabs", "rt_math_fabs")
_fn("serp_math_core", "c_log10", "f", "f", True, "serp_math_log10", "rt_math_log10")
_fn("serp_math_core", "c_log2", "f", "f", True, "serp_math_log2", "rt_math_log2")
_fn("serp_math_core", "c_log1p", "f", "f", True, "serp_math_log1p", "rt_math_log1p")
_fn("serp_math_core", "c_copysign", "ff", "f", False, "serp_math_copysign", "rt_math_copysign")
_fn("serp_math_core", "c_fmod", "ff", "f", True, "serp_math_fmod", "rt_math_fmod")
_fn("serp_math_core", "c_ldexp", "fi", "f", True, "serp_math_ldexp", "rt_math_ldexp")
_fn("serp_math_core", "c_trunc", "f", "i", True, "serp_math_trunc", "rt_math_trunc")
_fn("serp_math_core", "c_hypot", "ff", "f", False, "serp_math_hypot", "rt_math_hypot")
_fn("serp_math_core", "c_nextafter", "ff", "f", False, "serp_math_nextafter", "rt_math_nextafter")
_fn("serp_math_core", "c_ulp", "f", "f", False, "serp_math_ulp", "rt_math_ulp")
_fn("serp_math_core", "c_factorial", "i", "i", True, "serp_math_factorial", "rt_math_factorial")
_fn("serp_math_core", "c_gcd", "ii", "i", True, "serp_math_gcd", "rt_math_gcd")
_fn("serp_math_core", "c_lcm", "ii", "i", True, "serp_math_lcm", "rt_math_lcm")
_fn("serp_math_core", "c_isqrt", "i", "i", True, "serp_math_isqrt", "rt_math_isqrt")
_fn("serp_math_core", "c_comb", "ii", "i", True, "serp_math_comb", "rt_math_comb")
_fn("serp_math_core", "c_perm", "ii", "i", True, "serp_math_perm", "rt_math_perm")
_fn("serp_math_core", "c_frexp_m", "f", "f", False, "serp_math_frexp_m", "rt_math_frexp_m")
_fn("serp_math_core", "c_frexp_e", "f", "i", False, "serp_math_frexp_e", "rt_math_frexp_e")
_fn("serp_math_core", "c_modf_frac", "f", "f", False, "serp_math_modf_frac", "rt_math_modf_frac")
_fn("serp_math_core", "c_modf_int", "f", "f", False, "serp_math_modf_int", "rt_math_modf_int")

_fn("serp_random_core", "mt_seed", "i", "n", False, "serp_rand_seed", "rt_rand_seed")
_fn("serp_random_core", "mt_seed_sys", "", "n", False, "serp_rand_seed_sys", "rt_rand_seed_sys")
_fn("serp_random_core", "mt_random", "", "f", False, "serp_rand_random", "rt_rand_random")
_fn("serp_random_core", "mt_getrandbits", "i", "i", True, "serp_rand_getrandbits", "rt_rand_getrandbits")
_fn("serp_random_core", "mt_randbelow", "i", "i", False, "serp_rand_randbelow", "rt_rand_randbelow")

_fn("serp_time", "time", "", "f", False, "serp_time_time", "rt_time_time")
_fn("serp_time", "monotonic", "", "f", False, "serp_time_monotonic", "rt_time_monotonic")
_fn("serp_time", "sleep", "f", "n", True, "serp_time_sleep", "rt_time_sleep")
_fn("serp_time", "time_ns", "", "i", False, "serp_time_time_ns", "rt_time_time_ns")
_fn("serp_time", "monotonic_ns", "", "i", False, "serp_time_monotonic_ns", "rt_time_monotonic_ns")
_fn("serp_time", "perf_counter", "", "f", False, "serp_time_perf_counter", "rt_time_perf_counter")
_fn("serp_time", "perf_counter_ns", "", "i", False, "serp_time_perf_counter_ns", "rt_time_perf_counter_ns")

_fn("serp_os_core", "getenv", "s", "s", False, "serp_os_getenv", "rt_os_getenv")
_fn("serp_os_core", "has_env", "s", "b", False, "serp_os_has_env", "rt_os_has_env")
_fn("serp_os_core", "setenv", "ss", "n", True, "serp_os_setenv", "rt_os_setenv")
_fn("serp_os_core", "unsetenv", "s", "n", True, "serp_os_unsetenv", "rt_os_unsetenv")
_fn("serp_os_core", "getcwd", "", "s", True, "serp_os_getcwd", "rt_os_getcwd")
_fn("serp_os_core", "chdir", "s", "n", True, "serp_os_chdir", "rt_os_chdir")
_fn("serp_os_core", "exists", "s", "b", False, "serp_os_exists", "rt_os_exists")
_fn("serp_os_core", "is_file", "s", "b", False, "serp_os_is_file", "rt_os_is_file")
_fn("serp_os_core", "is_dir", "s", "b", False, "serp_os_is_dir", "rt_os_is_dir")
_fn("serp_os_core", "mkdir", "s", "n", True, "serp_os_mkdir", "rt_os_mkdir")
_fn("serp_os_core", "rmdir", "s", "n", True, "serp_os_rmdir", "rt_os_rmdir")
_fn("serp_os_core", "remove", "s", "n", True, "serp_os_remove", "rt_os_remove")
_fn("serp_os_core", "listdir", "s", "S", True, "serp_os_listdir", "rt_os_listdir")

_fn("serp_hashlib_core", "h_sha256_hex", "y", "s", False, "serp_hash_sha256_y", "rt_hash_sha256_y")
_fn("serp_hashlib_core", "h_sha1_hex", "y", "s", False, "serp_hash_sha1_y", "rt_hash_sha1_y")
_fn("serp_hashlib_core", "h_md5_hex", "y", "s", False, "serp_hash_md5_y", "rt_hash_md5_y")

_fn("serp_uuid_core", "u4_str", "", "s", False, "serp_uuid4", "rt_uuid4")

_fn("serp_zlib_core", "z_crc32", "yi", "i", False, "serp_zlib_crc32_seeded", "rt_zlib_crc32_seeded")
_fn("serp_zlib_core", "z_adler32", "yi", "i", False, "serp_zlib_adler32_seeded", "rt_zlib_adler32_seeded")
_fn("serp_zlib_core", "z_compress", "yi", "y", True, "serp_zlib_compress", "rt_zlib_compress")
_fn("serp_zlib_core", "z_decompress", "y", "y", True, "serp_zlib_decompress", "rt_zlib_decompress")
_fn("serp_zlib_core", "z_deflate", "yi", "y", True, "serp_zlib_deflate", "rt_zlib_deflate")
_fn("serp_zlib_core", "z_inflate", "y", "y", True, "serp_zlib_inflate", "rt_zlib_inflate")
_fn("serp_zlib_core", "z_gzip_compress", "yi", "y", True, "serp_zlib_gzip_compress", "rt_zlib_gzip_compress")
_fn("serp_zlib_core", "z_gzip_decompress", "y", "y", True, "serp_zlib_gzip_decompress", "rt_zlib_gzip_decompress")

_fn("serp_sqlite_core", "connect", "s", "i", True, "serp_sqlite_open", "rt_sqlite_open")
_fn("serp_sqlite_core", "close", "i", "n", True, "serp_sqlite_close", "rt_sqlite_close")
_fn("serp_sqlite_core", "execute", "is", "n", True, "serp_sqlite_execute", "rt_sqlite_execute")
_fn("serp_sqlite_core", "changes", "i", "i", True, "serp_sqlite_changes", "rt_sqlite_changes")
_fn("serp_sqlite_core", "last_rowid", "i", "i", True, "serp_sqlite_last_rowid", "rt_sqlite_last_rowid")
_fn("serp_sqlite_core", "prepare", "is", "i", True, "serp_sqlite_prepare", "rt_sqlite_prepare")
_fn("serp_sqlite_core", "bind_int", "iii", "n", True, "serp_sqlite_bind_int", "rt_sqlite_bind_int")
_fn("serp_sqlite_core", "bind_float", "iif", "n", True, "serp_sqlite_bind_float", "rt_sqlite_bind_float")
_fn("serp_sqlite_core", "bind_text", "iis", "n", True, "serp_sqlite_bind_text", "rt_sqlite_bind_text")
_fn("serp_sqlite_core", "bind_blob", "iiy", "n", True, "serp_sqlite_bind_blob", "rt_sqlite_bind_blob")
_fn("serp_sqlite_core", "bind_null", "ii", "n", True, "serp_sqlite_bind_null", "rt_sqlite_bind_null")
_fn("serp_sqlite_core", "step", "i", "b", True, "serp_sqlite_step", "rt_sqlite_step")
_fn("serp_sqlite_core", "column_count", "i", "i", True, "serp_sqlite_column_count", "rt_sqlite_column_count")
_fn("serp_sqlite_core", "col_type", "ii", "i", True, "serp_sqlite_col_type", "rt_sqlite_col_type")
_fn("serp_sqlite_core", "col_int", "ii", "i", True, "serp_sqlite_col_int", "rt_sqlite_col_int")
_fn("serp_sqlite_core", "col_float", "ii", "f", True, "serp_sqlite_col_float", "rt_sqlite_col_float")
_fn("serp_sqlite_core", "col_text", "ii", "s", True, "serp_sqlite_col_text", "rt_sqlite_col_text")
_fn("serp_sqlite_core", "col_blob", "ii", "y", True, "serp_sqlite_col_blob", "rt_sqlite_col_blob")
_fn("serp_sqlite_core", "reset", "i", "n", True, "serp_sqlite_reset", "rt_sqlite_reset")
_fn("serp_sqlite_core", "finalize", "i", "n", True, "serp_sqlite_finalize", "rt_sqlite_finalize")

_fn("_serp_socket", "connect", "sii", "i", True, "serp_sock_connect", "rt_sock_connect")
_fn("_serp_socket", "tls_connect", "siii", "i", True, "serp_sock_tls_connect", "rt_sock_tls_connect")
_fn("_serp_socket", "listen", "si", "i", True, "serp_sock_listen", "rt_sock_listen")
_fn("_serp_socket", "accept", "i", "i", True, "serp_sock_accept", "rt_sock_accept")
_fn("_serp_socket", "send", "iy", "i", True, "serp_sock_send", "rt_sock_send")
_fn("_serp_socket", "recv", "ii", "y", True, "serp_sock_recv", "rt_sock_recv")
_fn("_serp_socket", "shutdown_write", "i", "n", True, "serp_sock_shutdown_write", "rt_sock_shutdown_write")
_fn("_serp_socket", "set_timeout", "ii", "n", True, "serp_sock_set_timeout", "rt_sock_set_timeout")
_fn("_serp_socket", "local_port", "i", "i", True, "serp_sock_local_port", "rt_sock_local_port")
_fn("_serp_socket", "close", "i", "n", True, "serp_sock_close", "rt_sock_close")
_fn("_serp_socket", "udp_bind", "si", "i", True, "serp_sock_udp_bind", "rt_sock_udp_bind")
_fn("_serp_socket", "udp_send_to", "iysi", "i", True, "serp_sock_udp_send_to", "rt_sock_udp_send_to")
_fn("_serp_socket", "udp_recv_from", "ii", "y", True, "serp_sock_udp_recv_from", "rt_sock_udp_recv_from")
_fn("_serp_socket", "udp_peer_host", "i", "s", True, "serp_sock_udp_peer_host", "rt_sock_udp_peer_host")
_fn("_serp_socket", "udp_peer_port", "i", "i", True, "serp_sock_udp_peer_port", "rt_sock_udp_peer_port")

_fn("serp_secrets_core", "s_token_hex", "i", "s", True, "serp_secrets_token_hex", "rt_secrets_token_hex")
_fn("serp_secrets_core", "s_token_urlsafe", "i", "s", True, "serp_secrets_token_urlsafe", "rt_secrets_token_urlsafe")
_fn("serp_secrets_core", "s_randbelow", "i", "i", True, "serp_secrets_randbelow", "rt_secrets_randbelow")
_fn("serp_secrets_core", "s_randbits", "i", "i", True, "serp_secrets_randbits", "rt_secrets_randbits")
_fn("serp_secrets_core", "s_token_bytes", "i", "y", True, "serp_secrets_token_bytes", "rt_secrets_token_bytes")

_fn("serp_log_core", "lg_set", "ss", "n", False, "serp_log_set", "rt_log_set")
_fn("serp_log_core", "lg_get", "s", "s", False, "serp_log_get", "rt_log_get")
_fn("serp_log_core", "lg_write_err", "s", "n", False, "serp_log_write_err", "rt_log_write_err")

RTLIB_CONSTS[("serp_math_core", "c_pi")] = math.pi
RTLIB_CONSTS[("serp_math_core", "c_e")] = math.e
RTLIB_CONSTS[("serp_math_core", "c_tau")] = math.tau
RTLIB_CONSTS[("serp_math_core", "c_inf")] = math.inf
RTLIB_CONSTS[("serp_math_core", "c_nan")] = math.nan

RTLIB_MODULES = ({m for m, _ in RTLIB_FUNCS} | {m for m, _ in RTLIB_CONSTS})
