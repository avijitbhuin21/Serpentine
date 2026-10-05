"""Network TLS check: Fang (native, both TLS stacks) must refuse bad certificates and accept good ones."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "libs" / "serp-fang" / "tls_check" / "probe.py"
EXPECT = {
    "https://badssl.com/": "status 200",
    "https://expired.badssl.com/": "OSError certificate verify failed",
    "https://self-signed.badssl.com/": "OSError certificate verify failed",
    "https://wrong.host.badssl.com/": "OSError certificate verify failed",
    "https://untrusted-root.badssl.com/": "OSError certificate verify failed",
    "https://self-signed.badssl.com/ (verify=False)": "status 200",
}


def verdicts(stdout: str) -> dict[str, str]:
    """Map each probe line's case to its verdict."""
    out = {}
    for line in stdout.splitlines():
        if " -> " in line:
            case, _, verdict = line.partition(" -> ")
            out[case.strip()] = verdict.strip()
    return out


def main() -> int:
    """Build the probe natively, run it, and compare every verdict to EXPECT."""
    exe = Path(tempfile.mkdtemp(prefix="serp_tls_")) / ("probe" + (".exe" if sys.platform == "win32" else ""))
    b = subprocess.run([sys.executable, "-m", "serpentine_lang.cli", "build", str(PROBE), "-o", str(exe)],
                       capture_output=True, text=True, cwd=PROBE.parent)
    if b.returncode != 0:
        print("FAIL build\n" + (b.stderr or b.stdout)[-3000:])
        return 1
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=180)
    got = verdicts(r.stdout)
    if len(got) < len(EXPECT):
        print(f"probe exit code {r.returncode}; stdout tail: {r.stdout[-800:]!r}")
        print("probe stderr tail:\n" + r.stderr[-3000:])
    bad = 0
    for case, want in EXPECT.items():
        have = got.get(case, "<missing>")
        ok = have == want
        bad += 0 if ok else 1
        print(("ok  " if ok else "FAIL"), case, "->", have, "" if ok else f"(want {want})")
    print(f"tls check ({sys.platform}): {len(EXPECT) - bad}/{len(EXPECT)} cases as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
