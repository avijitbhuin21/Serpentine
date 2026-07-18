"""`serp lsp` — a dependency-free Language Server Protocol server over stdio.

Implements the diagnostics slice of LSP 3.x: full-text document sync
(didOpen/didChange/didSave) re-runs the whole checker via the library API
(`serpentine_lang.api`) and publishes rustc-style diagnostics per file.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from .api import check_file
from .diagnostics import Diagnostic


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a resolved local filesystem path string."""
    parsed = urllib.parse.urlparse(uri)
    path = urllib.parse.unquote(parsed.path)
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return str(Path(path).resolve())


def _path_to_uri(path: str) -> str:
    """Convert a local filesystem path to a file:// URI."""
    return Path(path).resolve().as_uri()


def _to_lsp_diag(d: Diagnostic) -> dict:
    """Map one checker Diagnostic to an LSP Diagnostic dict."""
    line = max(0, d.span.line - 1)
    start = d.span.col
    end = d.span.end_col if d.span.end_col is not None else d.span.col + 1
    message = d.message
    if d.label:
        message += f"\n{d.label}"
    if d.help:
        message += f"\nhelp: {d.help}"
    related = []
    for (span, label) in d.secondary:
        related.append({
            "location": {
                "uri": _path_to_uri(span.file),
                "range": {
                    "start": {"line": max(0, span.line - 1), "character": span.col},
                    "end": {"line": max(0, span.line - 1),
                            "character": span.end_col if span.end_col is not None
                            else span.col + 1},
                },
            },
            "message": label,
        })
    out = {
        "range": {
            "start": {"line": line, "character": start},
            "end": {"line": line, "character": max(end, start + 1)},
        },
        "severity": 1,
        "code": d.code,
        "source": "serp",
        "message": message,
    }
    if related:
        out["relatedInformation"] = related
    return out


class LspServer:
    """A single-session LSP server speaking Content-Length framed JSON-RPC on stdio."""

    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self.buffers: dict[str, str] = {}          # resolved path -> live text
        self.published: set[str] = set()           # uris with non-empty diagnostics

    # ---------- framing ----------

    def _read_message(self) -> dict | None:
        headers = {}
        while True:
            line = self.stdin.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            key, _, value = line.partition(b":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get(b"content-length", b"0"))
        if length <= 0:
            return None
        body = self.stdin.read(length)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.stdout.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        self.stdout.write(body)
        self.stdout.flush()

    def _respond(self, msg_id, result) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---------- diagnostics ----------

    def _publish_for(self, path: str) -> None:
        """Re-check the program rooted at `path` and publish per-file diagnostics."""
        try:
            diags = check_file(path, overlay=dict(self.buffers))
        except Exception as exc:  # a checker bug must not kill the session
            self._notify("window/logMessage",
                         {"type": 1, "message": f"serp lsp internal error: {exc}"})
            return
        by_file: dict[str, list[dict]] = {}
        for d in diags:
            by_file.setdefault(str(Path(d.span.file).resolve()), []).append(_to_lsp_diag(d))
        new_published = set()
        for file, items in by_file.items():
            uri = _path_to_uri(file)
            self._notify("textDocument/publishDiagnostics",
                         {"uri": uri, "diagnostics": items})
            new_published.add(uri)
        entry_uri = _path_to_uri(path)
        if entry_uri not in new_published:
            self._notify("textDocument/publishDiagnostics",
                         {"uri": entry_uri, "diagnostics": []})
        for uri in self.published - new_published - {entry_uri}:
            self._notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
        self.published = new_published

    # ---------- request handling ----------

    def serve(self) -> int:
        """Run the read-dispatch loop until `exit` or EOF."""
        while True:
            msg = self._read_message()
            if msg is None:
                return 0
            method = msg.get("method", "")
            msg_id = msg.get("id")
            params = msg.get("params") or {}
            if method == "initialize":
                self._respond(msg_id, {
                    "capabilities": {"textDocumentSync": 1},
                    "serverInfo": {"name": "serp-lsp", "version": "0.1"},
                })
            elif method == "shutdown":
                self._respond(msg_id, None)
            elif method == "exit":
                return 0
            elif method in ("textDocument/didOpen", "textDocument/didChange",
                            "textDocument/didSave"):
                doc = params.get("textDocument", {})
                path = _uri_to_path(doc.get("uri", ""))
                if method == "textDocument/didOpen":
                    self.buffers[path] = doc.get("text", "")
                elif method == "textDocument/didChange":
                    changes = params.get("contentChanges", [])
                    if changes:
                        self.buffers[path] = changes[-1].get("text", "")
                else:
                    text = params.get("text")
                    if text is not None:
                        self.buffers[path] = text
                self._publish_for(path)
            elif method == "textDocument/didClose":
                doc = params.get("textDocument", {})
                self.buffers.pop(_uri_to_path(doc.get("uri", "")), None)
            elif msg_id is not None:
                self._respond(msg_id, None)


def serve_stdio() -> int:
    """Entry point for `serp lsp`."""
    return LspServer().serve()
