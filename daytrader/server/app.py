"""Approval and portfolio server. Standard library only.

Clients (the Dynamic Island's Trading package, the Android app) use:

    GET  /api/health                        no auth; is the server up
    GET  /api/state                         full snapshot: P&L, positions, approvals, trades
    GET  /api/events                        Server-Sent Events stream (proposal, proposal_update,
                                            position_opened, position_closed, tick, killed, feed, alert)
    POST /api/proposals/<id>/approve        body {"device": "island" | "android"}
    POST /api/proposals/<id>/reject         body {"device": ...}
    POST /api/kill                          body {"reason": "...", "flatten": false}

Every /api route except /health needs the token: header "Authorization:
Bearer <token>" (or ?token=<token> for EventSource clients that cannot set
headers). The token is created on first start in state/api_token and is the
only thing a device needs. Broker keys never leave this machine.

By default the server listens on 127.0.0.1 only. To reach it from your phone,
bind it to your Tailscale address (--host 100.x.y.z), never to 0.0.0.0 on a
public network.
"""

from __future__ import annotations

import hmac
import json
import os
import queue
import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..engine import Engine

PROPOSAL_ROUTE = re.compile(r"^/api/proposals/([0-9a-f]{8})/(approve|reject)$")
MAX_BODY = 16 * 1024


def load_or_create_token(state_dir: str = "state") -> str:
    path = Path(state_dir) / "api_token"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token)
    os.chmod(path, 0o600)
    return token


class ApprovalServer:
    def __init__(self, engine: Engine, token: str, host: str = "127.0.0.1", port: int = 8765):
        self.engine = engine
        self.token = token
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.httpd.server_address[:2]

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(self):
        engine, token = self.engine, self.token

        class Handler(BaseHTTPRequestHandler):
            server_version = "daytrader"
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # keep the console quiet
                pass

            # ---- helpers ----------------------------------------------
            def _json(self, code: int, obj: dict) -> None:
                body = json.dumps(obj, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                given = ""
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    given = auth[7:].strip()
                else:
                    given = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                return bool(given) and hmac.compare_digest(given.encode(), token.encode())

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0:
                    return {}
                if n > MAX_BODY:
                    raise ValueError("body too large")
                data = json.loads(self.rfile.read(n).decode() or "{}")
                if not isinstance(data, dict):
                    raise ValueError("body must be a JSON object")
                return data

            # ---- routes -----------------------------------------------
            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/api/health":
                    return self._json(200, {"ok": True, "mode": engine.cfg.mode})
                if not self._authorized():
                    return self._json(401, {"ok": False, "error": "missing or wrong token"})
                if path == "/api/state":
                    return self._json(200, engine.state())
                if path == "/api/events":
                    return self._events()
                self._json(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                if not self._authorized():
                    return self._json(401, {"ok": False, "error": "missing or wrong token"})
                try:
                    body = self._body()
                except (ValueError, json.JSONDecodeError) as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                device = str(body.get("device", "unknown"))[:32]
                m = PROPOSAL_ROUTE.match(path)
                if m:
                    pid, action = m.groups()
                    res = engine.approve(pid, by=device) if action == "approve" else engine.reject(pid, by=device)
                    code = 200 if res.get("ok") or "proposal" in res else 404
                    return self._json(code, res)
                if path == "/api/kill":
                    reason = str(body.get("reason") or f"stopped from {device}")[:200]
                    return self._json(200, engine.kill(reason, flatten=bool(body.get("flatten")), by=device))
                self._json(404, {"ok": False, "error": "not found"})

            def _events(self):
                q: queue.Queue = queue.Queue(maxsize=1000)

                def listener(ev):
                    try:
                        q.put_nowait(ev)
                    except queue.Full:
                        pass

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                engine.subscribe(listener)
                try:
                    self._send_event({"type": "state", "data": engine.state()})
                    while True:
                        try:
                            ev = q.get(timeout=15)
                            self._send_event(ev)
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    engine.unsubscribe(listener)

            def _send_event(self, ev: dict) -> None:
                data = json.dumps(ev, default=str)
                self.wfile.write(f"event: {ev['type']}\ndata: {data}\n\n".encode())
                self.wfile.flush()

        return Handler
