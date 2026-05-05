#!/usr/bin/env python3
"""Wedding photo votes API server.
GET  /votes          → {filename: {up: N, down: N}, ...}
POST /vote           → body: {"photo": "01_SIN.jpg", "action": "up"|"down"}
"""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8765
ALLOWED_ORIGIN = "https://qkaTlehdrnf.github.io"
DB_PATH = Path(__file__).parent / "votes.db"

_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS votes "
        "(photo TEXT PRIMARY KEY, up INTEGER DEFAULT 0, down INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ip_votes "
        "(ip TEXT, photo TEXT, PRIMARY KEY(ip, photo))"
    )
    conn.commit()
    return conn


def client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or handler.client_address[0]


class VotesHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _cors(self):
        origin = self.headers.get("Origin", "")
        allowed = origin in (ALLOWED_ORIGIN, "http://localhost", "") or origin.startswith("http://localhost")
        self.send_header("Access-Control-Allow-Origin", origin if allowed else ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path != "/votes":
            self.send_response(404)
            self.end_headers()
            return
        ip = client_ip(self)
        with _lock:
            conn = get_db()
            rows = conn.execute("SELECT photo, up, down FROM votes").fetchall()
            my = conn.execute("SELECT photo FROM ip_votes WHERE ip=?", (ip,)).fetchall()
            conn.close()
        data = {r[0]: {"up": r[1], "down": r[2]} for r in rows}
        data["my_votes"] = [r[0] for r in my]
        body = json.dumps(data).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/vote":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
            photo = str(payload["photo"])
            action = str(payload["action"])
            assert action in ("up", "down")
        except Exception:
            self.send_response(400)
            self._cors()
            self.end_headers()
            return
        ip = client_ip(self)
        with _lock:
            conn = get_db()
            already = conn.execute(
                "SELECT 1 FROM ip_votes WHERE ip=? AND photo=?", (ip, photo)
            ).fetchone()
            if already:
                row = conn.execute("SELECT up, down FROM votes WHERE photo=?", (photo,)).fetchone()
                conn.close()
                body = json.dumps({"up": row[0] if row else 0, "already_voted": True}).encode()
            else:
                conn.execute("INSERT OR IGNORE INTO ip_votes(ip, photo) VALUES(?,?)", (ip, photo))
                conn.execute(
                    "INSERT INTO votes(photo, up, down) VALUES(?,0,0) "
                    "ON CONFLICT(photo) DO NOTHING",
                    (photo,),
                )
                conn.execute(f"UPDATE votes SET {action} = {action} + 1 WHERE photo = ?", (photo,))
                conn.commit()
                row = conn.execute("SELECT up, down FROM votes WHERE photo=?", (photo,)).fetchone()
                conn.close()
                body = json.dumps({"up": row[0], "already_voted": False}).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), VotesHandler)
    print(f"Votes server running on port {PORT}")
    server.serve_forever()
