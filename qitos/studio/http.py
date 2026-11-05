"""Loopback HTTP presentation and command boundary for Studio."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import time
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from .service import StudioError, StudioService


_SESSION = re.compile(r"^/api/sessions/([0-9a-f-]{36})(?:/(events|stream|resume))?$")


def make_handler(service: StudioService, static_root: Path) -> type[BaseHTTPRequestHandler]:
    """Create a handler with one process-scoped cookie and CSRF token."""
    root = static_root.resolve()
    cookie_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)

    class StudioHandler(BaseHTTPRequestHandler):
        server_version = "QitOSStudio"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Do not log URLs, tasks, tokens, or user-agent text.
            _ = fmt, args

        def _host_valid(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"

        def _cookie_valid(self) -> bool:
            parts = self.headers.get("Cookie", "").split(";")
            value = next((part.strip().split("=", 1)[1] for part in parts
                          if part.strip().startswith("studio_session=")), "")
            return secrets.compare_digest(value, cookie_token)

        def _authorized_write(self) -> bool:
            return (
                self._cookie_valid()
                and secrets.compare_digest(self.headers.get("X-Studio-CSRF", ""), csrf_token)
                and self.headers.get("Origin") == f"http://127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"
            )

        def _send(self, status: int, body: bytes, content_type: str,
                  *, set_cookie: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; "
                             "script-src 'self'; style-src 'self'; img-src 'self' data:; "
                             "base-uri 'none'; frame-ancestors 'none'")
            if set_cookie:
                self.send_header(
                    "Set-Cookie", f"studio_session={cookie_token}; HttpOnly; SameSite=Strict; Path=/",
                )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _error(self, status: int, code: str) -> None:
            self._json(status, {"error_code": code})

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_valid():
                self._error(403, "host_rejected")
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/" or (not path.startswith("/api/") and "." not in path):
                index = root / "index.html"
                if not index.is_file():
                    self._error(503, "studio_assets_missing")
                    return
                page = index.read_text(encoding="utf-8").replace(
                    "</head>", f'<meta name="studio-csrf" content="{csrf_token}"></head>', 1,
                )
                self._send(200, page.encode(), "text/html; charset=utf-8", set_cookie=True)
                return
            if path.startswith("/assets/") or path == "/favicon.svg":
                asset = (root / path.lstrip("/")).resolve()
                if not asset.is_relative_to(root) or not asset.is_file():
                    self._error(404, "asset_not_found")
                    return
                mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
                self._send(200, asset.read_bytes(), mime)
                return
            if not self._cookie_valid():
                self._error(403, "session_required")
                return
            try:
                if path == "/api/agents":
                    self._json(200, [agent.public_dict() for agent in service.agents.values()])
                elif path == "/api/sessions":
                    self._json(200, service.list_sessions())
                else:
                    match = _SESSION.fullmatch(path)
                    if match is None:
                        self._error(404, "route_not_found")
                        return
                    launch_id, subroute = match.groups()
                    if subroute is None:
                        self._json(200, service.get_session(launch_id))
                    elif subroute == "events":
                        qs = parse_qs(parsed.query)
                        self._json(200, service.events(
                            launch_id, after=int(qs.get("after", ["0"])[0]),
                            limit=min(int(qs.get("limit", ["100"])[0]), 256),
                        ))
                    elif subroute == "stream":
                        self._stream(launch_id, parsed.query)
                    else:
                        self._error(405, "method_not_allowed")
            except (StudioError, ValueError) as exc:
                code = str(exc) if isinstance(exc, StudioError) else "invalid_query"
                self._error(409 if isinstance(exc, StudioError) else 400, code)

        def _stream(self, launch_id: str, query: str) -> None:
            try:
                after = int(parse_qs(query).get("after", ["0"])[0])
                service.get_session(launch_id)
            except (ValueError, StudioError):
                self._error(400, "stream_request_invalid")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                for _ in range(60):
                    page = service.events(launch_id, after=after, limit=100)
                    for record in page["records"]:
                        after = max(after, int(record.get("sequence") or 0))
                        self.wfile.write((
                            "id: " + str(after) + "\n"
                            + "data: " + json.dumps(record, ensure_ascii=False) + "\n\n"
                        ).encode())
                    self.wfile.flush()
                    if service.get_session(launch_id)["status"] not in {"queued", "running"}:
                        return
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError, StudioError):
                return

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_valid() or not self._authorized_write():
                self._error(403, "write_not_authorized")
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            try:
                if path == "/api/sessions":
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 2 or size > 20_000 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                        raise StudioError("request_invalid")
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict) or set(body) != {"agent_id", "task"}:
                        raise StudioError("request_invalid")
                    self._json(201, service.start(body["agent_id"], body["task"]))
                    return
                match = _SESSION.fullmatch(path)
                if match and match.group(2) == "resume":
                    self._json(202, service.resume(match.group(1)))
                    return
                self._error(404, "route_not_found")
            except (StudioError, ValueError, json.JSONDecodeError) as exc:
                code = str(exc) if isinstance(exc, StudioError) else "request_invalid"
                self._error(400 if code == "request_invalid" else 409, code)

    return StudioHandler


def serve(service: StudioService, static_root: Path, port: int = 8766,
          *, open_browser: bool = True) -> None:
    """Bind the only supported listener: local IPv4 loopback."""
    with ThreadingHTTPServer(("127.0.0.1", port), make_handler(service, static_root)) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"QitOS Studio: {url}")
        if open_browser:
            import webbrowser
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
