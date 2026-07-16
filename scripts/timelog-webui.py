#!/usr/bin/env python
"""Local web UI for the time-tracking ledger — no API, no tokens.

Reads ~/.claude/time-tracking/timelog.jsonl (+ pricing.json) straight off disk and
serves a single-page report app in your browser. Because it never calls the model,
you can leave it open and watch usage even while your account is completely idle
(the whole point: checking your usage shouldn't itself consume usage).

Run:
    python timelog-webui.py [--port 8787] [--ledger PATH] [--no-open]
Then open http://localhost:8787  (bound to localhost only).

All aggregation happens client-side, so queries are flexible without touching this
server. The server just hands the browser the raw ledger rows + pricing on /api/data,
re-read fresh on every request so a page refresh always shows the live file.
"""
import sys, os, json, time, http.server, socketserver, urllib.parse, webbrowser

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".claude", "time-tracking", "timelog.jsonl")
PRICING = os.path.join(HOME, ".claude", "time-tracking", "pricing.json")
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8787
OPEN = True

args = sys.argv[1:]
i = 0
while i < len(args):
    a = args[i]
    if a == "--port" and i + 1 < len(args):
        PORT = int(args[i + 1]); i += 2
    elif a == "--ledger" and i + 1 < len(args):
        LEDGER = os.path.abspath(args[i + 1]); i += 2
    elif a == "--no-open":
        OPEN = False; i += 1
    else:
        i += 1


def load_rows():
    out = []
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def load_pricing():
    try:
        return json.load(open(PRICING, encoding="utf-8"))
    except Exception:
        return {}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "timelog-webui.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                # Frontend page not installed (yet) — stay useful anyway.
                self._send(200, (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>timelog web UI</title>"
                    "<body style='font-family:system-ui;max-width:40em;margin:3em auto'>"
                    "<h1>timelog web UI</h1>"
                    "<p><code>timelog-webui.html</code> isn't installed next to the "
                    "server yet, but the data endpoint works:</p>"
                    "<p><a href='/api/data'>/api/data</a> — raw ledger rows + pricing "
                    "as JSON, re-read fresh on every request.</p>"
                    "<p>No model, no tokens: this server only reads the local ledger "
                    "file.</p></body>"), "text/html; charset=utf-8")
        elif path == "/api/data":
            payload = json.dumps({
                "rows": load_rows(),
                "pricing": load_pricing(),
                "now": int(time.time()),
                "tz": time.strftime("%z"),
                "ledger": LEDGER,
            })
            self._send(200, payload, "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def log_message(self, *a):
        pass  # keep the console quiet


def main():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}"
        print(f"timelog web UI  ->  {url}")
        print(f"  ledger: {LEDGER}")
        print("  (Ctrl-C to stop; reads the ledger fresh on every request — no API, no tokens)")
        if OPEN:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
