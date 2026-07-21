"""Dependency management: serp add / serp remove (PyPI source-library fetcher).

Serpentine libraries are source distributions on PyPI (docs/packages.md §3):
pure-Python wheels whose only runtime dependency is the shim. `serp add`
resolves a distribution against PyPI's JSON API, downloads its wheel into a
content-addressed cache, records the exact pin in serp.toml + serp.lock, and
installs the wheel into the project venv so CPython dual-execution and the
compiler's site-packages resolution both see the same files.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .project import Manifest, find_manifest, load_manifest, normalize_dist_name

PYPI_JSON = "https://pypi.org/pypi/{name}/json"
ALLOWED_DEPS = {"serpentine-shim", "serpentine_shim"}


class PkgError(Exception):
    """Raised for any user-reportable add/remove failure."""


def _cache_dir() -> Path:
    """Per-user wheel cache (same base dir family as the runtime cache)."""
    import os
    if env := os.environ.get("SERP_PKG_CACHE"):
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "serp" / "pkg"


def _fetch_json(url: str) -> dict:
    """GET a JSON document with a serp User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": "serp-pkg/1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise PkgError(f"PyPI request failed for {url}: {exc}") from exc


def _pick_release(meta: dict, name: str, version: str | None) -> tuple[str, dict]:
    """Choose the wheel file entry for the requested (or latest) version."""
    if version is None:
        version = meta["info"]["version"]
    files = meta.get("releases", {}).get(version)
    if not files:
        raise PkgError(f"{name}=={version} not found on PyPI")
    for f in files:
        if f["filename"].endswith("py3-none-any.whl") and not f.get("yanked", False):
            return version, f
    raise PkgError(
        f"{name}=={version} has no pure-Python wheel (py3-none-any) — a Serpentine "
        f"library must be a pure source distribution (docs/packages.md)")


def _check_is_serp_library(meta: dict, name: str) -> None:
    """Refuse distributions with runtime dependencies beyond the shim."""
    requires = meta["info"].get("requires_dist") or []
    extras = []
    for r in requires:
        if "extra ==" in r:
            continue
        dep = r.split(";")[0].strip().split(" ")[0].split("[")[0]
        dep = dep.split("==")[0].split(">=")[0].split("<")[0].split("!")[0].split("~")[0]
        if normalize_dist_name(dep) not in {normalize_dist_name(d) for d in ALLOWED_DEPS}:
            extras.append(dep)
    if extras:
        raise PkgError(
            f"'{name}' is not a Serpentine library: it depends on {', '.join(sorted(set(extras)))} "
            f"— serp libraries may only depend on serpentine-shim (docs/packages.md §3); "
            f"foreign packages are refused at the interop boundary (docs/interop.md)")


def _download_wheel(entry: dict) -> Path:
    """Download the wheel into the cache (content-addressed), reusing hits."""
    sha = entry["digests"]["sha256"]
    dest = _cache_dir() / sha[:2] / entry["filename"]
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(entry["url"], headers={"User-Agent": "serp-pkg/1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception as exc:
        raise PkgError(f"download failed for {entry['url']}: {exc}") from exc
    if hashlib.sha256(data).hexdigest() != sha:
        raise PkgError(f"sha256 mismatch for {entry['filename']} — refusing to install")
    tmp = Path(tempfile.mktemp(dir=dest.parent))
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def _install_wheel(manifest: Manifest, wheel: Path) -> None:
    """Install a cached wheel, retrying from the system temp dir when the
    per-user cache is virtualized and invisible to child processes."""
    try:
        _venv_install(manifest, str(wheel))
    except PkgError:
        fallback = Path(tempfile.gettempdir()) / "serp" / "pkg" / wheel.name
        fallback.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wheel, fallback)
        _venv_install(manifest, str(fallback))


def _venv_install(manifest: Manifest, target: str) -> None:
    """Install (a wheel path or requirement string) into the project venv."""
    from .manage import _venv_python
    py = _venv_python(manifest.project_dir / ".venv")
    if not py.is_file():
        raise PkgError("no .venv in this project — run `serp init` first "
                       "(dual execution needs the library importable under CPython)")
    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", str(py), target] if uv
           else [str(py), "-m", "pip", "install", "--quiet", target])
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise PkgError(f"venv install failed:\n{proc.stderr.strip()}")


def _venv_uninstall(manifest: Manifest, name: str) -> None:
    """Uninstall a distribution from the project venv."""
    from .manage import _venv_python
    py = _venv_python(manifest.project_dir / ".venv")
    if not py.is_file():
        return
    uv = shutil.which("uv")
    cmd = ([uv, "pip", "uninstall", "--python", str(py), name] if uv
           else [str(py), "-m", "pip", "uninstall", "-y", "--quiet", name])
    subprocess.run(cmd, capture_output=True)


def _write_manifest(manifest: Manifest) -> None:
    """Re-serialize serp.toml from the (simple, flat) manifest schema."""
    lines = ["[project]", f'name = "{manifest.name}"', f'version = "{manifest.version}"', ""]
    lines.append("[dependencies]")
    for dep, spec in sorted(manifest.dependencies.items()):
        lines.append(f'{dep} = "{spec}"')
    if manifest.roots:
        lines += ["", "[build]"]
        rels = []
        for r in manifest.roots:
            try:
                rels.append(r.relative_to(manifest.project_dir).as_posix())
            except ValueError:
                rels.append(str(r))
        lines.append("roots = [" + ", ".join(f'"{r}"' for r in rels) + "]")
    manifest.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_lock(manifest: Manifest) -> dict[str, dict]:
    """Read serp.lock into {name: {version, sha256, filename}}."""
    import tomllib
    lock_path = manifest.project_dir / "serp.lock"
    if not lock_path.is_file():
        return {}
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    return {p["name"]: p for p in data.get("package", [])}


def _write_lock(manifest: Manifest, lock: dict[str, dict]) -> None:
    """Write serp.lock (sorted, reproducible)."""
    lines = ["# generated by serp add -- do not edit by hand", ""]
    for name in sorted(lock):
        p = lock[name]
        lines += ["[[package]]",
                  f'name = "{p["name"]}"',
                  f'version = "{p["version"]}"',
                  f'sha256 = "{p["sha256"]}"',
                  f'filename = "{p["filename"]}"',
                  ""]
    (manifest.project_dir / "serp.lock").write_text("\n".join(lines), encoding="utf-8")


def _load_project_manifest() -> Manifest:
    """Locate and parse the enclosing project's serp.toml."""
    mpath = find_manifest(Path.cwd())
    if mpath is None:
        raise PkgError("no serp.toml found — run `serp init` first")
    return load_manifest(mpath)


def cmd_add(args: argparse.Namespace) -> int:
    """serp add: fetch a Serpentine library from PyPI and pin it."""
    try:
        manifest = _load_project_manifest()
        name, _, version = args.package.partition("==")
        name = name.strip()
        meta = _fetch_json(PYPI_JSON.format(name=name))
        canonical = meta["info"]["name"]
        _check_is_serp_library(meta, canonical)
        version, entry = _pick_release(meta, canonical, version.strip() or None)
        wheel = _download_wheel(entry)
        _install_wheel(manifest, wheel)
        manifest.dependencies[canonical] = f"=={version}"
        _write_manifest(manifest)
        lock = _read_lock(manifest)
        lock[canonical] = {"name": canonical, "version": version,
                           "sha256": entry["digests"]["sha256"],
                           "filename": entry["filename"]}
        _write_lock(manifest, lock)
    except PkgError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 1
    print(f"serp: added {canonical}=={version} (import root "
          f"'{normalize_dist_name(canonical)}'); pinned in serp.toml + serp.lock")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """serp remove: drop a dependency from the manifest, lock, and venv."""
    try:
        manifest = _load_project_manifest()
        key = next((d for d in manifest.dependencies
                    if normalize_dist_name(d) == normalize_dist_name(args.package)), None)
        if key is None:
            print(f"serp: '{args.package}' is not a dependency of this project", file=sys.stderr)
            return 1
        del manifest.dependencies[key]
        _write_manifest(manifest)
        lock = _read_lock(manifest)
        lock.pop(key, None)
        _write_lock(manifest, lock)
        _venv_uninstall(manifest, key)
    except PkgError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 1
    print(f"serp: removed {key}")
    return 0


def register(sub) -> None:
    """Attach the dependency subcommands to the serp argument parser."""
    p_add = sub.add_parser("add", help="add a Serpentine library dependency from PyPI")
    p_add.add_argument("package", help="distribution name, optionally name==version")
    p_add.set_defaults(func=cmd_add)

    p_rem = sub.add_parser("remove", help="remove a dependency")
    p_rem.add_argument("package")
    p_rem.set_defaults(func=cmd_remove)
