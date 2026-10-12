"""md2pdf.health"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import os


# ───────────────────────────── سرور سلامت‌سنجی ─────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def _respond(self, with_body):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        if with_body:
            self.wfile.write(b"Bot is Running successfully on Back4App!")

    def do_GET(self):
        self._respond(True)

    def do_HEAD(self):
        self._respond(False)

    def log_message(self, *args):
        pass


def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()
