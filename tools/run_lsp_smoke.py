"""LSP smoke test: drive `serp lsp` over stdio and assert diagnostics round-trip."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BROKEN = '''\
def main() -> None:
    xs: list[int] = [1, 2, 3]
    ys = move(xs)
    print(len(xs))


if __name__ == "__main__":
    main()
'''

FIXED = '''\
def main() -> None:
    xs: list[int] = [1, 2, 3]
    print(len(xs))


if __name__ == "__main__":
    main()
'''


def send(proc, payload):
    """Write one Content-Length framed JSON-RPC message."""
    body = json.dumps(payload).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    proc.stdin.write(body)
    proc.stdin.flush()


def read_message(proc):
    """Read one framed JSON-RPC message from the server."""
    headers = {}
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        k, _, v = line.partition(b":")
        headers[k.strip().lower()] = v.strip()
    length = int(headers[b"content-length"])
    return json.loads(proc.stdout.read(length).decode("utf-8"))


def wait_for(proc, method):
    """Read messages until one with the given method arrives."""
    for _ in range(50):
        msg = read_message(proc)
        if msg is None:
            raise AssertionError("server closed the stream early")
        if msg.get("method") == method:
            return msg
        if "result" in msg or "error" in msg:
            continue
    raise AssertionError(f"never received {method}")


def main() -> int:
    """Run the scripted LSP session and report pass/fail."""
    tmp = Path(tempfile.mkdtemp(prefix="serp_lsp_")) / "buffer_test.py"
    tmp.write_text(BROKEN, encoding="utf-8")
    uri = tmp.resolve().as_uri()
    proc = subprocess.Popen(
        [sys.executable, "-m", "serpentine_lang.cli", "lsp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        init = read_message(proc)
        assert init and init["result"]["capabilities"]["textDocumentSync"] == 1, \
            f"bad initialize response: {init}"
        print("ok   initialize: textDocumentSync=1")

        send(proc, {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "python", "version": 1,
                             "text": BROKEN}}})
        pub = wait_for(proc, "textDocument/publishDiagnostics")
        diags = pub["params"]["diagnostics"]
        codes = [d["code"] for d in diags]
        assert "SE001" in codes, f"expected SE001 in {codes}"
        d0 = [d for d in diags if d["code"] == "SE001"][0]
        assert d0["range"]["start"]["line"] == 3, f"bad line: {d0['range']}"
        print(f"ok   didOpen: published {codes} at line {d0['range']['start']['line'] + 1}")

        send(proc, {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": FIXED}]}})
        pub2 = wait_for(proc, "textDocument/publishDiagnostics")
        assert pub2["params"]["diagnostics"] == [], \
            f"expected clean, got {pub2['params']['diagnostics']}"
        print("ok   didChange: diagnostics cleared on fixed buffer (unsaved overlay)")

        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}})
        send(proc, {"jsonrpc": "2.0", "method": "exit", "params": {}})
        proc.wait(timeout=10)
        print("ok   shutdown/exit: clean server termination")
        print("\nLSP smoke test passed")
        return 0
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
