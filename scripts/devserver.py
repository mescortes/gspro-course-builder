"""Static file server for the viewer that also accepts POST /shot?name=<file>.png (canvas captures -> build/shots)."""
import http.server, os, sys, urllib.parse, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build" / "shots"

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        name = q.get("name", ["shot.png"])[0]
        if u.path != "/shot" or not re.fullmatch(r"[\w\-.]+\.(png|jpg)", name):
            self.send_response(400); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        SHOTS.mkdir(parents=True, exist_ok=True)
        (SHOTS / name).write_bytes(data)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
