"""Project manifests: serp.toml discovery, parsing, and import-root resolution.

A Serpentine project is marked by a `serp.toml` next to (or above) the entry
file (docs/guides/packages.md). The manifest declares the project name/version, its
source-distribution dependencies, and optional extra import roots. Import
resolution order (packages.md section 2): entry-file directory tree, declared
roots, then dependency-gated venv site-packages; anything else is refused at
the interop boundary (SE213).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Manifest:
    """A parsed serp.toml: identity, dependencies, and extra import roots."""

    path: Path
    name: str = ""
    version: str = "0.1.0"
    dependencies: dict[str, str] = field(default_factory=dict)
    roots: list[Path] = field(default_factory=list)

    @property
    def project_dir(self) -> Path:
        return self.path.parent


class ManifestError(Exception):
    """Raised when serp.toml exists but cannot be parsed or is malformed."""


def find_manifest(start_dir: Path) -> Path | None:
    """Walk up from start_dir to the filesystem root looking for serp.toml."""
    cur = start_dir.resolve()
    for d in (cur, *cur.parents):
        cand = d / "serp.toml"
        if cand.is_file():
            return cand
    return None


def load_manifest(path: Path) -> Manifest:
    """Parse one serp.toml; declared roots resolve relative to the manifest dir."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: manifest must be a TOML table")
    project = data.get("project", {})
    deps = data.get("dependencies", {})
    build = data.get("build", {})
    if not isinstance(project, dict) or not isinstance(deps, dict) or not isinstance(build, dict):
        raise ManifestError(f"{path}: [project], [dependencies], and [build] must be tables")
    roots = build.get("roots", [])
    if not (isinstance(roots, list) and all(isinstance(r, str) for r in roots)):
        raise ManifestError(f"{path}: build.roots must be a list of strings")
    m = Manifest(path=path.resolve(),
                 name=str(project.get("name", "")),
                 version=str(project.get("version", "0.1.0")),
                 dependencies={str(k): str(v) for k, v in deps.items()})
    m.roots = [(m.project_dir / r).resolve() for r in roots]
    return m


def normalize_dist_name(name: str) -> str:
    """Map a PyPI distribution name to its expected import root (PEP 503 + underscores)."""
    return name.lower().replace("-", "_").replace(".", "_")


def lock_dist_names(project_dir: Path) -> list[str]:
    """Read the distribution names pinned in serp.lock (direct + transitive)."""
    lock_path = project_dir / "serp.lock"
    if not lock_path.is_file():
        return []
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    return [str(p.get("name", "")) for p in data.get("package", []) if p.get("name")]


def venv_site_packages(project_dir: Path) -> Path | None:
    """Locate the project venv's site-packages (.venv next to serp.toml), if any."""
    venv = project_dir / ".venv"
    win = venv / "Lib" / "site-packages"
    if win.is_dir():
        return win
    lib = venv / "lib"
    if lib.is_dir():
        for d in sorted(lib.glob("python3*")):
            sp = d / "site-packages"
            if sp.is_dir():
                return sp
    return None


@dataclass
class ImportContext:
    """Everything needed to resolve a dotted module name to a source file."""

    entry_root: Path
    manifest: Manifest | None = None
    site_packages: Path | None = None

    def searched_roots(self) -> list[Path]:
        roots = [self.entry_root]
        if self.manifest:
            roots.extend(self.manifest.roots)
        return roots

    def resolve(self, mod_name: str) -> Path | None:
        """Resolve `a.b` to <root>/a/b.py per the packages.md resolution order."""
        rel = Path(*mod_name.split(".")).with_suffix(".py")
        for root in self.searched_roots():
            cand = root / rel
            if cand.is_file():
                return cand.resolve()
        if self.manifest and self.site_packages:
            top = mod_name.split(".")[0]
            dep_roots = {normalize_dist_name(d) for d in self.manifest.dependencies}
            dep_roots |= {normalize_dist_name(d)
                          for d in lock_dist_names(self.manifest.project_dir)}
            if top in dep_roots:
                cand = self.site_packages / rel
                if cand.is_file():
                    return cand.resolve()
        return None


def import_context(entry_dir: Path) -> ImportContext:
    """Build the resolution context for a program whose entry file lives in entry_dir."""
    ctx = ImportContext(entry_root=entry_dir.resolve())
    mpath = find_manifest(entry_dir)
    if mpath is not None:
        ctx.manifest = load_manifest(mpath)
        ctx.site_packages = venv_site_packages(ctx.manifest.project_dir)
    return ctx
