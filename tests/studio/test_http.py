from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from qitos.studio.http import make_handler


class _Service:
    agents = {"demo": type("Agent", (), {
        "public_dict": lambda self: {"id": "demo", "name": "Demo", "description": ""}
    })()}

    def __init__(self):
        self.started = 0

    def list_sessions(self):
        return []

    def start(self, agent_id, task):
        self.started += 1
        return {"id": "launch-1", "agent_id": agent_id, "task": task}


def test_local_http_requires_cookie_csrf_and_origin_for_launch(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><head></head><body>Studio</body></html>")
    service = _Service()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, tmp_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        page = conn.getresponse()
        body = page.read().decode()
        assert page.status == 200
        assert "Studio" in body
        cookie = page.getheader("Set-Cookie").split(";", 1)[0]
        csrf = body.split('name="studio-csrf" content="')[1].split('"', 1)[0]
        conn.close()

        def post(headers):
            request = http.client.HTTPConnection("127.0.0.1", port)
            request.request("POST", "/api/sessions", json.dumps({
                "agent_id": "demo", "task": "hello"
            }), {"Content-Type": "application/json", **headers})
            response = request.getresponse()
            result = (response.status, json.loads(response.read()))
            request.close()
            return result

        assert post({})[0] == 403
        assert post({"Cookie": cookie, "X-Studio-CSRF": csrf,
                     "Origin": "https://evil.example"})[0] == 403
        status, payload = post({"Cookie": cookie, "X-Studio-CSRF": csrf,
                                "Origin": f"http://127.0.0.1:{port}"})
        assert status == 201
        assert payload["id"] == "launch-1"
        assert service.started == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
