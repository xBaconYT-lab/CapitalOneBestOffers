"""Serve the Best Offers site and keep the offer data fresh.

    python3 server.py            # http://localhost:8787
    PORT=9000 REFRESH_HOURS=12 python3 server.py

Data refreshes automatically when it is older than REFRESH_HOURS (default 6) –
both on page load and from a background timer – and on demand via the Refresh button.
"""
import json
import mimetypes
import os
import sys
import threading
import time
import datetime as dt
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

import scraper

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("PORT", "8787"))
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "6"))
FEED_CALLS = int(os.environ.get("FEED_CALLS", "8"))

_lock = threading.Lock()
_state = {"refreshing": False, "last_error": None, "last_attempt": None}


def _age_hours():
    if not os.path.exists(scraper.OFFERS_PATH):
        return None
    return (time.time() - os.path.getmtime(scraper.OFFERS_PATH)) / 3600.0


def refresh(force=False):
    """Run the scraper if data is missing/stale (or force). Returns True if a refresh ran."""
    age = _age_hours()
    if not force and age is not None and age < REFRESH_HOURS:
        return False
    with _lock:
        age = _age_hours()
        if not force and age is not None and age < REFRESH_HOURS:
            return False
        _state["refreshing"] = True
        _state["last_attempt"] = dt.datetime.now().isoformat(timespec="seconds")
        try:
            scraper.run(calls=FEED_CALLS, log=lambda *a, **k: print("[scraper]", *a))
            _state["last_error"] = None
        except Exception as exc:
            _state["last_error"] = str(exc)
            print("[scraper] FAILED:", exc)
        finally:
            _state["refreshing"] = False
    return True


def background_loop():
    while True:
        try:
            refresh()
        except Exception as exc:
            print("[background]", exc)
        time.sleep(1800)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC, **kwargs)

    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}")

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/offers":
            refresh()
            return self._send_offers()
        if path == "/api/status":
            return self._json({"age_hours": _age_hours(), "refresh_hours": REFRESH_HOURS, **_state})
        if path == "/api/history":
            names = sorted(n[:-5] for n in os.listdir(scraper.HISTORY_DIR)) if os.path.isdir(scraper.HISTORY_DIR) else []
            return self._json({"days": names})
        if path.startswith("/api/history/"):
            day = os.path.basename(path)
            target = os.path.join(scraper.HISTORY_DIR, f"{day}.json")
            if not os.path.exists(target):
                return self._json({"error": "no data for that day"}, 404)
            with open(target, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path.startswith("/data/") and path.endswith(".json"):
            target = os.path.join(scraper.DATA_DIR, os.path.basename(path))
            if not os.path.exists(target):
                return self._json({"error": "not found"}, 404)
            with open(target, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        if path == "/config.json":
            with open(os.path.join(HERE, "config.json"), "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path == "/":
            self.path = "/index.html"
        elif path.startswith("/static/"):
            self.path = path[len("/static"):]
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/refresh":
            refresh(force=True)
            return self._send_offers()
        return self._json({"error": "not found"}, 404)

    def _send_offers(self):
        if not os.path.exists(scraper.OFFERS_PATH):
            return self._json({"error": _state["last_error"] or "no data yet", "offers": [], **_state}, 503)
        with open(scraper.OFFERS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["status"] = {"age_hours": _age_hours(), "refresh_hours": REFRESH_HOURS, **_state}
        return self._json(data)

    def end_headers(self):
        if self.path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)  # show logs promptly when piped
    except Exception:
        pass
    mimetypes.add_type("application/javascript", ".js")
    threading.Thread(target=background_loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Capital One Best Offers → http://localhost:{PORT}  (refresh every {REFRESH_HOURS:g}h)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
