"""Dependency management: serp add / serp remove (PyPI source-library fetcher).

Serpentine libraries are source distributions on PyPI (docs/guides/packages.md §3):
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
PYPI_VERSION_JSON = "https://pypi.org/pypi/{name}/{version}/json"
ALLOWED_DEPS = {"serpentine-shim", "serpentine_shim"}


class PkgError(Exception):
    """Raised for any user-reportable add/remove failure."""


def _is_shim(name: str) -> bool:
    """True when a dependency name is the serpentine shim (always allowed)."""
    return normalize_dist_name(name) in {normalize_dist_name(d) for d in ALLOWED_DEPS}


def _version_key(v: str) -> tuple:
    """Sortable key for a PEP 440-ish version string (numeric-prefix tolerant)."""
    parts = []
    for piece in v.split("."):
        num = ""
        for ch in piece:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _parse_dep_specs(requires_dist: list[str] | None) -> list[tuple[str, str]]:
    """Parse requires_dist entries into (dist_name, version_spec) pairs, skipping extras."""
    import re
    out = []
    for r in requires_dist or []:
        if "extra ==" in r:
            continue
        head = r.split(";")[0].strip()
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*\(?\s*([^)]*?)\s*\)?$", head)
        if not m:
            continue
        out.append((m.group(1), m.group(2).strip()))
    return out


def _pick_version(meta: dict, name: str, spec: str) -> str:
    """Choose a concrete version for a dependency spec ('', '==x', or '>=x')."""
    latest = meta["info"]["version"]
    if not spec:
        return latest
    clauses = [c.strip() for c in spec.split(",") if c.strip()]
    exact = None
    minimum = None
    for c in clauses:
        if c.startswith("=="):
            exact = c[2:].strip()
        elif c.startswith(">="):
            minimum = c[2:].strip()
        else:
            raise PkgError(f"unsupported version specifier '{c}' for {name} — "
                           f"serp libraries should pin with == or >= (docs/guides/packages.md)")
    if exact is not None:
        return exact
    if minimum is not None and _version_key(latest) < _version_key(minimum):
        raise PkgError(f"{name}: latest version {latest} does not satisfy '>={minimum}'")
    return latest


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


def _pick_wheel(files: list | None, name: str, version: str) -> dict:
    """Choose the pure-Python wheel entry from a version's file list."""
    for f in files or []:
        if f["filename"].endswith("py3-none-any.whl") and not f.get("yanked", False):
            return f
    raise PkgError(
        f"{name}=={version} has no pure-Python wheel (py3-none-any) — a Serpentine "
        f"library must be a pure source distribution (docs/guides/packages.md)")


def _resolve_closure(root_name: str, root_spec: str) -> dict[str, dict]:
    """Resolve a dependency and its transitive serp-library closure against PyPI.

    Returns {normalized_name: {name, version, entry, requires, direct}}. Every
    transitive dependency must be the shim (skipped) or a serp-* library; exact-pin
    conflicts between requesters are refused."""
    resolved: dict[str, dict] = {}

    def visit(name: str, spec: str, direct: bool, via: str | None) -> str:
        meta = _fetch_json(PYPI_JSON.format(name=name))
        canonical = meta["info"]["name"]
        key = normalize_dist_name(canonical)
        version = _pick_version(meta, canonical, spec)
        if key in resolved:
            prev = resolved[key]
            if prev["version"] != version and "==" in spec:
                raise PkgError(
                    f"version conflict for {canonical}: {prev['version']} already "
                    f"resolved but {via or 'the command line'} requires {spec}")
            prev["direct"] = prev["direct"] or direct
            return canonical
        if version == meta["info"]["version"]:
            info, files = meta["info"], meta.get("releases", {}).get(version)
        else:
            vmeta = _fetch_json(PYPI_VERSION_JSON.format(name=canonical, version=version))
            info, files = vmeta["info"], vmeta.get("urls")
        if not files:
            raise PkgError(f"{canonical}=={version} not found on PyPI")
        entry = _pick_wheel(files, canonical, version)
        requires = []
        foreign = []
        for dep_name, dep_spec in _parse_dep_specs(info.get("requires_dist")):
            if _is_shim(dep_name):
                continue
            if not normalize_dist_name(dep_name).startswith("serp_"):
                foreign.append(dep_name)
                continue
            requires.append((dep_name, dep_spec))
        if foreign:
            raise PkgError(
                f"'{canonical}' is not a Serpentine library: it depends on "
                f"{', '.join(sorted(set(foreign)))} — serp libraries may only depend on "
                f"serpentine-shim and other serp-* libraries (docs/guides/packages.md §3); "
                f"foreign packages are refused at the interop boundary (docs/guides/interop.md)")
        resolved[key] = {"name": canonical, "version": version, "entry": entry,
                         "requires": [], "direct": direct}
        resolved[key]["requires"] = [
            visit(dep_name, dep_spec, direct=False, via=canonical)
            for dep_name, dep_spec in requires]
        return canonical

    visit(root_name, root_spec, direct=True, via=None)
    return resolved


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


def _install_wheels(manifest: Manifest, wheels: list[Path]) -> None:
    """Install cached wheels, retrying from the system temp dir when the
    per-user cache is virtualized and invisible to child processes."""
    try:
        _venv_install(manifest, [str(w) for w in wheels])
    except PkgError:
        targets = []
        for wheel in wheels:
            fallback = Path(tempfile.gettempdir()) / "serp" / "pkg" / wheel.name
            fallback.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wheel, fallback)
            targets.append(str(fallback))
        _venv_install(manifest, targets)


def _venv_install(manifest: Manifest, targets: list[str]) -> None:
    """Install wheel paths (or requirement strings) into the project venv."""
    from .manage import _venv_python
    py = _venv_python(manifest.project_dir / ".venv")
    if not py.is_file():
        raise PkgError("no .venv in this project — run `serp init` first "
                       "(dual execution needs the library importable under CPython)")
    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", str(py), *targets] if uv
           else [str(py), "-m", "pip", "install", "--quiet", *targets])
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
    """Read serp.lock into {name: {version, sha256, filename, requires, direct}}."""
    import tomllib
    lock_path = manifest.project_dir / "serp.lock"
    if not lock_path.is_file():
        return {}
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    lock = {}
    for p in data.get("package", []):
        p.setdefault("requires", [])
        p.setdefault("direct", True)
        lock[p["name"]] = p
    return lock


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
                  f'direct = {"true" if p.get("direct", True) else "false"}',
                  "requires = [" + ", ".join(f'"{r}"' for r in sorted(p.get("requires", []))) + "]",
                  ""]
    (manifest.project_dir / "serp.lock").write_text("\n".join(lines), encoding="utf-8")


def _load_project_manifest() -> Manifest:
    """Locate and parse the enclosing project's serp.toml."""
    mpath = find_manifest(Path.cwd())
    if mpath is None:
        raise PkgError("no serp.toml found — run `serp init` first")
    return load_manifest(mpath)


def cmd_add(args: argparse.Namespace) -> int:
    """serp add: fetch a Serpentine library (+ its serp-lib closure) and pin it."""
    try:
        manifest = _load_project_manifest()
        name, _, version = args.package.partition("==")
        spec = f"=={version.strip()}" if version.strip() else ""
        closure = _resolve_closure(name.strip(), spec)
        wheels = {key: _download_wheel(p["entry"]) for key, p in closure.items()}
        _install_wheels(manifest, list(wheels.values()))
        root = next(p for p in closure.values() if p["direct"])
        canonical, pinned = root["name"], root["version"]
        manifest.dependencies[canonical] = f"=={pinned}"
        _write_manifest(manifest)
        lock = _read_lock(manifest)
        for p in closure.values():
            prev = lock.get(p["name"], {})
            lock[p["name"]] = {"name": p["name"], "version": p["version"],
                               "sha256": p["entry"]["digests"]["sha256"],
                               "filename": p["entry"]["filename"],
                               "requires": p["requires"],
                               "direct": p["direct"] or prev.get("direct", False)}
        _write_lock(manifest, lock)
    except PkgError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 1
    extra = [p["name"] for p in closure.values() if not p["direct"]]
    via = f" (+ {', '.join(sorted(extra))})" if extra else ""
    print(f"serp: added {canonical}=={pinned}{via} (import root "
          f"'{normalize_dist_name(canonical)}'); pinned in serp.toml + serp.lock")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """serp remove: drop a dependency + newly-orphaned transitive deps."""
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
        keep: set[str] = set()
        frontier = [d for d in manifest.dependencies]
        by_norm = {normalize_dist_name(n): n for n in lock}
        while frontier:
            cur = by_norm.get(normalize_dist_name(frontier.pop()))
            if cur is None or cur in keep:
                continue
            keep.add(cur)
            frontier.extend(lock[cur].get("requires", []))
        orphans = [n for n in lock if n not in keep]
        for n in orphans:
            lock.pop(n)
        _write_lock(manifest, lock)
        _venv_uninstall(manifest, key)
        for n in orphans:
            _venv_uninstall(manifest, n)
    except PkgError as exc:
        print(f"serp: {exc}", file=sys.stderr)
        return 1
    gone = ", ".join([key] + sorted(orphans))
    print(f"serp: removed {gone}")
    return 0


def register(sub) -> None:
    """Attach the dependency subcommands to the serp argument parser."""
    p_add = sub.add_parser("add", help="add a Serpentine library dependency from PyPI")
    p_add.add_argument("package", help="distribution name, optionally name==version")
    p_add.set_defaults(func=cmd_add)

    p_rem = sub.add_parser("remove", help="remove a dependency")
    p_rem.add_argument("package")
    p_rem.set_defaults(func=cmd_remove)
