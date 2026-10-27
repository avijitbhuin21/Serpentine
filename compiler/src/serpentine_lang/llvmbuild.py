"""Backend B build pipeline: cached runtime library + object emission + native link.

Runtime strategy (archived checklist Phase 5.0, docs/decisions.md): prelude.rs + rt.rs are
compiled ONCE per (source hash, rustc version, target) into a cached Rust
library; Backend-B objects link against it. Two platform link paths:

- Windows (MSVC): runtime is an rlib; the final link compiles a 3-line Rust stub
  with `--extern serp_rt` and passes the LLVM object via `-C link-arg` (MSVC
  link.exe resolves symbols order-independently). rustc handles all linker and
  CRT discovery.
- Unix: runtime is a staticlib; the LLVM module defines `main` itself and we
  link with the system C driver: `cc prog.o libserp_rt.a <native-static-libs>`.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).parent
RT_SOURCES = [PKG / "prelude.rs", PKG / "rt.rs"]

STUB_RS = """\
extern crate serp_rt;
extern "C" { fn serp_entry(); }
fn main() {
    let t = std::thread::Builder::new().name("main".into()).stack_size(256 << 20)
        .spawn(|| unsafe { serp_entry() }).expect("spawn main thread");
    if t.join().is_err() { std::process::exit(101); }
}
"""

STUB_RS_BARE = """\
extern "C" { fn serp_entry(); }
fn main() {
    let t = std::thread::Builder::new().name("main".into()).stack_size(256 << 20)
        .spawn(|| unsafe { serp_entry() }).expect("spawn main thread");
    if t.join().is_err() { std::process::exit(101); }
}
"""


class LLVMBuildError(Exception):
    """Backend-B build failure (toolchain missing or link error)."""


def llvmlite_missing() -> str | None:
    """Return a user-facing message when llvmlite cannot be imported, else None."""
    import importlib.util
    if importlib.util.find_spec("llvmlite") is not None:
        return None
    return ("serp: the default LLVM backend needs the 'llvmlite' package, which is missing from "
            "this environment. Reinstall with `pip install -U serpentine-lang`, or build with "
            "`--backend rust` (needs only rustc).")


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise LLVMBuildError(f"{what} failed:\n{proc.stderr}")
    return proc


def _rustc() -> str:
    rustc = shutil.which("rustc")
    if rustc is None:
        raise LLVMBuildError("rustc not found on PATH (needed once to build the "
                             "Backend-B runtime library) — install Rust from https://rustup.rs")
    return rustc


def _cache_root() -> Path:
    import os
    override = os.environ.get("SERP_RT_CACHE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".cache"
    return base / "serp" / "rt"


def _fallback_cache_root() -> Path:
    """Sandboxes may virtualize per-user dirs so child processes can't see our
    writes; the system temp dir is visible to every process."""
    return Path(tempfile.gettempdir()) / "serp" / "rt"


def _extra_flags() -> list[str]:
    """Extra rustc flags from SERP_RUSTC_FLAGS (sanitizer builds); part of the runtime cache key."""
    return os.environ.get("SERP_RUSTC_FLAGS", "").split()


def runtime_key(rustc: str) -> str:
    """Cache key: runtime sources + rustc version identify the artifact."""
    h = hashlib.sha256()
    for src in RT_SOURCES:
        h.update(src.read_bytes())
    h.update(STUB_RS.encode())
    h.update(STUB_RS_BARE.encode())
    ver = subprocess.run([rustc, "--version"], capture_output=True, text=True).stdout
    h.update(ver.encode())
    h.update(sys.platform.encode())
    h.update(" ".join(_extra_flags()).encode())
    return h.hexdigest()[:16]


RELEASE_URL = ("https://github.com/avijitbhuin21/Serpentine/releases/download/"
               "v{version}/serp-rt-{version}-{tag}.zip")


def sources_hash() -> str:
    """Hash of the runtime sources alone (rustc-independent)."""
    h = hashlib.sha256()
    for src in RT_SOURCES:
        h.update(src.read_bytes())
    return h.hexdigest()


def platform_tag() -> str:
    """Platform identifier used in prebuilt runtime asset names."""
    import platform
    mach = platform.machine().lower()
    mach = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(mach, mach)
    osname = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    return f"{osname}-{mach}"


def serp_version() -> str:
    """Installed serpentine-lang version (asset names are tied to releases)."""
    try:
        from importlib.metadata import version
        return version("serpentine-lang")
    except Exception:
        from . import __version__
        return __version__


def _rustc_version(rustc: str) -> str:
    return subprocess.run([rustc, "--version"], capture_output=True,
                          text=True).stdout.strip()


def _try_prebuilt(rustc: str | None, verbose: bool) -> tuple[Path, list[str], Path] | None:
    """Reuse or download the prebuilt runtime for this release + platform.

    The asset is trusted only when its runtime-source hash matches the local
    sources; on Windows the rlib additionally requires the same rustc version
    (rlib metadata is rustc-version-specific)."""
    dirname = f"prebuilt-{serp_version()}-{platform_tag()}"
    roots = (_cache_root(), _fallback_cache_root())
    for root in roots:
        if _prebuilt_valid(root / dirname, rustc):
            hit = _runtime_hit(root / dirname)
            if hit is not None:
                return hit
    url = RELEASE_URL.format(version=serp_version(), tag=platform_tag())
    import io
    import urllib.request
    import zipfile
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "serp-rt/1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception:
        return None
    for root in roots:
        cache = root / dirname
        try:
            cache.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(cache)
        except OSError:
            continue
        if _prebuilt_valid(cache, rustc):
            hit = _runtime_hit(cache)
            if hit is not None:
                if verbose:
                    print(f"serp: using prebuilt runtime (downloaded to {cache})",
                          file=sys.stderr)
                return hit
        return None
    return None


def _prebuilt_valid(cache: Path, rustc: str | None) -> bool:
    """Check a prebuilt runtime dir's metadata against the local environment."""
    import json
    meta_file = cache / "meta.json"
    if not meta_file.is_file():
        return False
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if meta.get("sources_sha256") != sources_hash():
        return False
    if sys.platform == "win32":
        if rustc is None or meta.get("rustc_version") != _rustc_version(rustc):
            return False
    return True


def ensure_runtime(verbose: bool = False) -> tuple[Path, list[str], Path]:
    """Build (or reuse) the cached runtime artifacts.

    Resolution order: local rustc-keyed cache, prebuilt release asset
    (download-on-first-use), local rustc build, in that order.

    Returns (library path, extra native link args for the Unix cc link,
    runtime LLVM bitcode path for release-mode cross-runtime inlining)."""
    rustc = shutil.which("rustc")
    if rustc is not None:
        key = runtime_key(rustc)
        for root in (_cache_root(), _fallback_cache_root()):
            hit = _runtime_hit(root / key)
            if hit is not None:
                return hit
    hit = _try_prebuilt(rustc, verbose) if not _extra_flags() else None
    if hit is not None:
        return hit
    if rustc is None:
        raise LLVMBuildError(
            "rustc not found on PATH and no prebuilt runtime is available for "
            f"serpentine-lang {serp_version()} on {platform_tag()} — install Rust "
            "(https://rustup.rs) to build the runtime locally")
    try:
        return _ensure_runtime_at(_cache_root() / key, rustc, verbose)
    except LLVMBuildError as exc:
        # The Microsoft Store Python virtualizes writes under %LOCALAPPDATA%, so rustc
        # (outside the sandbox) can't see files Python just wrote there.
        if "couldn't read" not in str(exc) and "couldn't find file" not in str(exc):
            raise
        return _ensure_runtime_at(_fallback_cache_root() / key, rustc, verbose)


def _win_runtime_syslibs() -> list[str]:
    """Windows system .libs the runtime's #[link] attributes require.

    The prebuilt runtime ships no native-static-libs list, and merging the
    runtime bitcode into the program object drops the rlib's link metadata, so
    the names are recovered from the runtime sources themselves."""
    import re
    names: list[str] = []
    for src in RT_SOURCES:
        try:
            text = src.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.finditer(r'#\[link\(name\s*=\s*"([^"]+)"', text):
            lib = f"{m.group(1)}.lib"
            if lib not in names:
                names.append(lib)
    skip = {"dl.lib"}
    return [n for n in names if n not in skip]


def _runtime_hit(cache: Path) -> tuple[Path, list[str], Path] | None:
    is_win = sys.platform == "win32"
    lib = cache / ("libserp_rt.rlib" if is_win else "libserp_rt.a")
    libs_file = cache / "native-static-libs.txt"
    bc = cache / "serp_rt.bc"
    if lib.exists() and libs_file.exists() and bc.exists():
        return lib, libs_file.read_text().split(), bc
    return None


def _ensure_runtime_at(cache: Path, rustc: str, verbose: bool) -> tuple[Path, list[str], Path]:
    is_win = sys.platform == "win32"
    lib = cache / ("libserp_rt.rlib" if is_win else "libserp_rt.a")
    libs_file = cache / "native-static-libs.txt"
    bc = cache / "serp_rt.bc"
    hit = _runtime_hit(cache)
    if hit is not None:
        return hit
    cache.mkdir(parents=True, exist_ok=True)
    combined = cache / "serp_rt.rs"
    combined.write_text("\n".join(s.read_text(encoding="utf-8") for s in RT_SOURCES),
                        encoding="utf-8")
    if verbose:
        import sys as _s
        print(f"serp: building Backend-B runtime (one-time, cached at {cache})",
              file=_s.stderr)
    crate_type = "rlib" if is_win else "staticlib"
    cmd = [rustc, "--edition", "2021", "--crate-type", crate_type,
           "--crate-name", "serp_rt", "-C", "opt-level=3",
           "--print", "native-static-libs",
           "-o", str(lib), str(combined)] + _extra_flags()
    proc = _run(cmd, "runtime library build (rustc)")
    native = []
    for line in proc.stderr.splitlines():
        if "native-static-libs:" in line:
            native = line.split("native-static-libs:", 1)[1].split()
    libs_file.write_text(" ".join(native))
    _run([rustc, "--edition", "2021", "--crate-type", "rlib",
          "--crate-name", "serp_rt", "-C", "opt-level=3",
          "-C", "codegen-units=1", "--emit", f"llvm-bc={bc}", str(combined)] + _extra_flags(),
         "runtime bitcode build (rustc)")
    return lib, native, bc


def _win_fastlink_setup(cache: Path, rustc: str) -> dict | None:
    """One-time (cached) capture of a direct link.exe command template.

    rustc's stub link costs ~0.2s per build; capturing the linker path and the
    std rlib list once lets debug builds invoke link.exe directly (~0.02s).
    Returns None when the environment doesn't match expectations (the caller
    falls back to the rustc-driven link)."""
    import json
    meta = cache / "fastlink.json"
    if meta.exists():
        info = json.loads(meta.read_text())
        if all(Path(o).exists() for o in info.get("stub_objs", [])):
            return info
    try:
        stub = cache / "stub_bare.rs"
        stub.write_text(STUB_RS_BARE, encoding="utf-8")
        proc = subprocess.run(
            [rustc, "--edition", "2021", "--print", "link-args",
             "-C", "opt-level=0", "-C", "save-temps",
             "-o", str(cache / "stub_probe.exe"), str(stub)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(cache))
        line = proc.stdout.strip().splitlines()[0]
        import shlex
        args = [a.strip('"') for a in shlex.split(line, posix=False)]
        linker = args[0].replace("\\\\", "\\")
        if "link.exe" not in linker.lower():
            return None
        # save-temps leaves the stub's codegen objects (incl. the allocator
        # shim) next to the output; they replace rustc's temp objects
        stub_objs = sorted(str(p) for p in cache.glob("stub_probe*.rcgu.o"))
        if not stub_objs:
            return None
        rlibs = [a.replace("\\\\", "\\") for a in args[1:] if a.endswith(".rlib")]
        libs = [a for a in args[1:] if a.endswith(".lib") or a.startswith("/defaultlib:")]
        # MSVC + Windows SDK lib dirs from the standard layout
        msvc_lib = Path(linker).parents[3] / "lib" / "x64"
        libpaths = [str(msvc_lib)]
        import os
        kits = Path(os.environ.get("ProgramFiles(x86)",
                                   r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "Lib"
        if kits.exists():
            best = sorted(kits.iterdir())[-1]
            libpaths += [str(best / "um" / "x64"), str(best / "ucrt" / "x64")]
        if not msvc_lib.exists():
            return None
        info = {"linker": linker, "stub_objs": stub_objs, "rlibs": rlibs,
                "libs": libs, "libpaths": libpaths}
        meta.write_text(json.dumps(info))
        return info
    except Exception:
        return None


def _win_fastlink(obj: Path, out: Path, debuginfo: bool, lib: Path,
                  runtime_merged: bool, native: list[str] | None = None) -> bool:
    """Try the direct link.exe path; returns False to fall back to rustc."""
    rustc = _rustc()
    cache = lib.parent
    info = _win_fastlink_setup(cache, rustc)
    if info is None:
        return False
    cmd = [info["linker"], "/NOLOGO", "/STACK:16777216"] + info["stub_objs"] + [str(obj)]
    if not runtime_merged:
        cmd.append(str(lib))
    cmd += info["rlibs"] + info["libs"] + list(native or [])
    cmd += [f"/LIBPATH:{p}" for p in info["libpaths"]]
    cmd += ["/NXCOMPAT", f"/OUT:{out}"]
    if debuginfo:
        cmd.append("/DEBUG")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return proc.returncode == 0


def emit_object(ir_text: str, out_obj: Path, opt: int) -> bool:
    """Compile LLVM IR text to a native object file via llvmlite.

    In release mode the cached runtime BITCODE is linked into the program
    module and internalized first, so LLVM can inline runtime primitives into
    hot loops (poor man's cross-language LTO). Returns True when the runtime
    was merged in (the final link must then omit the runtime library — the
    object is runtime-complete and rustc's merge-functions aliases would
    otherwise collide)."""
    import llvmlite.binding as llvm

    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    mod = llvm.parse_assembly(ir_text)
    mod.verify()
    merged = False
    # std::thread code in the runtime bitcode carries module-level inline asm,
    # which llvmlite's MC layer cannot emit — thread-using programs link the
    # runtime as a plain library instead (user code still gets full O3).
    wants_lto = opt > 0 and "rt_thread_spawn" not in ir_text \
        and "rt_task_spawn" not in ir_text and "rt_thread_new" not in ir_text
    if wants_lto:
        try:
            _, _, bc = ensure_runtime(verbose=True)
            rt_mod = llvm.parse_bitcode(bc.read_bytes())
            rt_fns = [f.name for f in rt_mod.functions if not f.is_declaration]
            rt_globals = [g.name for g in rt_mod.global_variables]
            mod.link_in(rt_mod)
            for name in rt_fns:
                try:
                    mod.get_function(name).linkage = "internal"
                except NameError:
                    pass
            for name in rt_globals:
                try:
                    mod.get_global_variable(name).linkage = "internal"
                except NameError:
                    pass
            merged = True
        except Exception as exc:                      # pragma: no cover — fallback
            print(f"serp: runtime bitcode inlining unavailable ({exc}); "
                  f"linking runtime as a plain library", file=sys.stderr)
    target = llvm.Target.from_default_triple()
    reloc = "pic" if sys.platform != "win32" else "default"
    tm = target.create_target_machine(opt=opt, reloc=reloc, codemodel="default")
    if opt > 0:
        pto = llvm.create_pipeline_tuning_options(speed_level=opt)
        pb = llvm.create_pass_builder(tm, pto)
        mpm = pb.getModulePassManager()
        mpm.run(mod, pb)
    out_obj.write_bytes(tm.emit_object(mod))
    return merged


def link(obj: Path, out: Path, debug: bool, runtime_merged: bool = False,
         debuginfo: bool = False) -> None:
    """Link the emitted object against the cached runtime into a native binary."""
    lib, native, _bc = ensure_runtime(verbose=True)
    if sys.platform == "win32":
        native = list(native) + [n for n in _win_runtime_syslibs() if n not in native]
        if not _extra_flags() and _win_fastlink(obj, out, debuginfo, lib, runtime_merged, native):
            return
        rustc = _rustc()
        with tempfile.TemporaryDirectory(prefix="serp_link_") as td:
            stub = Path(td) / "stub.rs"
            stub_src = STUB_RS_BARE if runtime_merged else STUB_RS
            stub.write_text(stub_src, encoding="utf-8")
            cmd = [rustc, "--edition", "2021", "-C", "opt-level=0",
                   "-C", f"link-arg={obj}",
                   "-C", "link-arg=/STACK:16777216",
                   "-o", str(out), str(stub)] + _extra_flags()
            if not runtime_merged:
                cmd[5:5] = ["--extern", f"serp_rt={lib}"]
            else:
                # merging the runtime bitcode into prog.obj drops the rlib's
                # #[link] metadata, so the system libs it needs must be explicit
                for nl in native:
                    cmd[5:5] = ["-C", f"link-arg={nl}"]
            if debuginfo:
                cmd[3:3] = ["-C", "debuginfo=2"]
            _run(cmd, "final link (rustc stub)")
        return
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        raise LLVMBuildError("no C linker driver (cc/clang/gcc) found on PATH")
    cmd = [cc, str(obj), str(lib), "-o", str(out)] + native
    if debuginfo:
        cmd.append("-g")
    _run(cmd, "final link (cc)")


def build_native(ir_text: str, out: Path, debug: bool, debuginfo: bool = False) -> None:
    """Full Backend-B build: IR -> object -> linked native binary."""
    opt = 0 if debug else 3
    with tempfile.TemporaryDirectory(prefix="serp_obj_") as td:
        obj = Path(td) / ("prog.obj" if sys.platform == "win32" else "prog.o")
        merged = emit_object(ir_text, obj, opt)
        link(obj, out, debug, runtime_merged=merged, debuginfo=debuginfo)
