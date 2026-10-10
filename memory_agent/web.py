"""Minimal local web UI: stdlib HTTP server + one static page, no new deps.

Binds to 127.0.0.1 only. Host/Origin checks block DNS-rebinding and
cross-site requests from other web pages to this local server.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config
from .agent import MODES
from .conversations import DEFAULT_ID, ConversationManager
from .memory_store import Status

STATIC = Path(__file__).resolve().parent.parent / "static"
INDEX = STATIC / "index.html"
ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
MAX_BODY = 64 * 1024


def make_handler(agent, port):
    lock = threading.Lock()           # one Qdrant client, one request at a time
    conversations = ConversationManager(agent.history.path.parent / "conversations", agent.history)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        # -------------------------------------------------------- helpers
        def _send(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, {"error": "forbidden host"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in allowed_hosts}:
                self._send(403, {"error": "forbidden origin"})
                return False
            return True

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                return None
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return None
            return data if isinstance(data, dict) else None

        def _memory_id(self, path):
            prefix = "/api/memories/"
            return path[len(prefix):] if path.startswith(prefix) and len(path) > len(prefix) else None

        # -------------------------------------------------------- routes
        def do_GET(self):
            if not self._guard():
                return
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                asset = STATIC / path[len("/static/"):]
                ctype = ASSET_TYPES.get(asset.suffix)
                # whitelist: flat files directly inside static/, js/css only
                if ctype and asset.parent == STATIC and asset.is_file():
                    self._send(200, asset.read_bytes(), ctype)
                else:
                    self._send(404, {"error": "not found"})
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            elif path == "/api/memories":
                with lock:
                    try:
                        memories = agent.store.list()
                        self._send(200, {"count": len(memories), "memories": memories,
                                         "user_id": agent.store.user_id})
                    except Exception as exc:
                        self._send(500, {"error": str(exc)})
            elif path == "/api/status":
                with lock:
                    try:
                        self._send(200, {"ok": True, "local": True,
                                         "user_id": agent.store.user_id,
                                         "count": len(agent.store.list())})
                    except Exception as exc:
                        self._send(500, {"ok": False, "error": str(exc)})
            elif path == "/api/conversations":
                with lock:
                    self._send(200, {"conversations": conversations.list()})
            elif path == "/api/history":
                cid = parse_qs(urlparse(self.path).query).get("conversation_id", [DEFAULT_ID])[0]
                with lock:
                    history = conversations.get(cid) if conversations.valid(cid) else None
                    if history is None:
                        return self._send(404, {"error": "unknown conversation"})
                    self._send(200, {"conversation_id": cid, "messages": history.window(500)})
            elif path == "/api/settings":
                self._send(200, {"chat_model": config.CHAT_MODEL, "embed_model": config.EMBED_MODEL,
                                 "user_id": agent.store.user_id, "local": True, "telemetry": False})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if urlparse(self.path).path != "/api/chat":
                return self._send(404, {"error": "not found"})
            data = self._body()
            message = data.get("message") if data else None
            if not isinstance(message, str) or not message.strip():
                return self._send(400, {"error": "message must be a non-empty string"})
            mode = data.get("mode", "agent")
            if mode not in MODES:
                return self._send(400, {"error": f"mode must be one of {list(MODES)}"})
            # Omitted -> the original history (backward compatible); "new" -> a fresh chat.
            cid = data.get("conversation_id", DEFAULT_ID)
            if cid != "new" and not conversations.valid(cid):
                return self._send(400, {"error": "invalid conversation_id"})
            with lock:
                created = cid == "new"
                if created:
                    cid = conversations.new_id()
                history = conversations.get(cid, create=created)
                if history is None:
                    return self._send(404, {"error": "unknown conversation"})
                agent.use_history(history)
                reply = agent.handle(message, mode)
                if created:
                    conversations.discard_if_empty(cid)     # first send failed: no ghost chat
                saved = cid in conversations._open
            self._send(200, {"reply": reply.text, "action": reply.action,
                             "conversation_id": cid if saved else None})

        def do_PUT(self):
            if not self._guard():
                return
            memory_id = self._memory_id(urlparse(self.path).path)
            data = self._body()
            text = data.get("text") if data else None
            if not memory_id or not isinstance(text, str):
                return self._send(400, {"error": "need a memory id and text"})
            with lock:
                res = agent.store.update(memory_id, text)
            self._send(_code(res), {"status": res.status.value, "message": res.message})

        def do_DELETE(self):
            if not self._guard():
                return
            parsed = urlparse(self.path)
            memory_id = self._memory_id(parsed.path)
            confirmed = parse_qs(parsed.query).get("confirm") == ["yes"]
            if not memory_id:
                return self._send(400, {"error": "need a memory id"})
            with lock:
                res = agent.store.delete(memory_id, confirmed=confirmed)
            self._send(_code(res), {"status": res.status.value, "message": res.message})

    return Handler


def _code(res):
    return {Status.NOT_FOUND: 404, Status.INVALID: 400, Status.ERROR: 500}.get(res.status, 200)


def run_web(agent, port=8765):
    server = HTTPServer(("127.0.0.1", port), make_handler(agent, port))
    print(f"Web UI: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
