from http.server import BaseHTTPRequestHandler
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typhoon_bot import main as run_bot


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            run_bot()
            body = b"OK"
            status = 200
        except Exception as e:
            body = str(e).encode()
            status = 500

        self.send_response(status)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()
