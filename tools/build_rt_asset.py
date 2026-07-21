"""Build the prebuilt Backend-B runtime release asset for this platform.

Run in CI on each OS after `pip install ./compiler`: builds the runtime via
the normal cache path, then zips {runtime lib, native-static-libs.txt,
serp_rt.bc, meta.json} as serp-rt-<version>-<platform>.zip in ./dist-rt.
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

from serpentine_lang.llvmbuild import (ensure_runtime, platform_tag, serp_version,
                                       sources_hash, _rustc, _rustc_version)


def main() -> int:
    """Build the runtime and package it as a release asset zip."""
    lib, _native, bc = ensure_runtime(verbose=True)
    cache = lib.parent
    out_dir = Path("dist-rt")
    out_dir.mkdir(exist_ok=True)
    name = f"serp-rt-{serp_version()}-{platform_tag()}.zip"
    out = out_dir / name
    meta = {
        "sources_sha256": sources_hash(),
        "rustc_version": _rustc_version(_rustc()),
        "platform_tag": platform_tag(),
        "serp_version": serp_version(),
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(lib, lib.name)
        zf.write(cache / "native-static-libs.txt", "native-static-libs.txt")
        zf.write(bc, "serp_rt.bc")
        zf.writestr("meta.json", json.dumps(meta, indent=2))
    print(f"built {out} ({out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
