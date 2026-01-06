#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request


UI_PORT = int(os.environ.get("UI_PORT", "8002"))
BOM_PORT = int(os.environ.get("BOM_PORT", "8001"))
PROXY_PORT = int(os.environ.get("PORT", "10000"))

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def upstream_url(path):
    if path.startswith("/api/"):
        return f"http://127.0.0.1:{BOM_PORT}{path[len('/api'):] or '/'}"
    if path in ("/estimate", "/job-types", "/healthz"):
        return f"http://127.0.0.1:{BOM_PORT}{path}"
    return f"http://127.0.0.1:{UI_PORT}{path}"


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_OPTIONS(self):
        self._proxy()

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def _proxy(self):
        target = upstream_url(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        req = request.Request(target, data=body, headers=headers, method=self.command)
        try:
            with request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() in HOP_BY_HOP:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(resp.read())
        except error.HTTPError as exc:
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in HOP_BY_HOP:
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Proxy error: {exc}".encode("utf-8"))


def start_child(cmd, env=None):
    return subprocess.Popen(cmd, env=env)


def main():
    env = os.environ.copy()
    env.setdefault("BOM_API_URL", f"http://127.0.0.1:{BOM_PORT}")

    api_cmd = [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(BOM_PORT)]
    ui_cmd = [sys.executable, "-m", "uvicorn", "ui:app", "--host", "127.0.0.1", "--port", str(UI_PORT)]

    api_proc = start_child(api_cmd, env=env)
    ui_proc = start_child(ui_cmd, env=env)
    children = [api_proc, ui_proc]

    def shutdown(_signum=None, _frame=None):
        for proc in children:
            if proc.poll() is None:
                proc.terminate()
        for proc in children:
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        sys.exit(0)

    def monitor():
        while True:
            for proc in children:
                if proc.poll() is not None:
                    shutdown()
            threading.Event().wait(1)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=monitor, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    print(f"Proxy listening on 0.0.0.0:{PROXY_PORT} (UI->{UI_PORT}, BOM->{BOM_PORT})")
    server.serve_forever()


if __name__ == "__main__":
    main()
