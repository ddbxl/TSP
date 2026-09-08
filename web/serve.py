"""Serve the browser build on http://localhost:8000 for local testing.

    python web/serve.py

Copies src/tsp/core.py in as tsp_core.py first, matching what the GitHub Pages
workflow does, so the page runs the same engine here as in production.
"""

from __future__ import annotations

import functools
import http.server
import shutil
import socketserver
import sys
import webbrowser
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
PORT = 8000


def stage() -> None:
    for source, staged in (
        (ROOT / "src" / "tsp" / "core.py", "tsp_core.py"),
        (ROOT / "src" / "tsp" / "office.py", "tsp_office.py"),
    ):
        if not source.is_file():
            sys.exit(f"engine missing at {source}")
        shutil.copy2(source, WEB / staged)

    # bridge.py already lives in web/, so only the engine needs staging.
    for name in ("icon.svg", "favicon.png"):
        source = ROOT / "assets" / name
        if source.is_file():
            shutil.copy2(source, WEB / name)
    print(f"staged tsp_core.py from {engine.relative_to(ROOT)}")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".mjs": "text/javascript",
    }

    def end_headers(self) -> None:
        # Stop the browser caching the engine between edits.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        if "404" in (fmt % args):
            super().log_message(fmt, *args)


def main() -> int:
    stage()
    handler = functools.partial(Handler, directory=str(WEB))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), handler) as server:
        url = f"http://localhost:{PORT}"
        print(f"serving {WEB} at {url}\nctrl-c to stop")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
