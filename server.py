#!/usr/bin/env python3
"""Beacon: an offline emergency companion.

Run:  python server.py      then open http://127.0.0.1:8765

Standard library only. Everything it talks to is on this machine:
  - Bonsai, through a local OpenAI-compatible endpoint
  - Argmax WhisperKit + TTSKit, through the Swift bridge (Mac)
"""
import json
import mimetypes
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from beacon import config
from beacon.brain import Brain
from beacon.kb import KnowledgeBase
from beacon.llm import Bonsai
from beacon.speech import SpeechError, make_speech

for _stream in (sys.stdout, sys.stderr):  # never crash on a console that cannot print a character
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")

KB = KnowledgeBase()
BONSAI = Bonsai()
BRAIN = Brain(KB, BONSAI)
SPEECH = None  # created in main()


def status():
    sp = SPEECH.status()
    sp.setdefault("can_listen", sp.get("ready", False))
    library = [{"id": c["id"], "title": c["title"], "category": c["category"]} for c in KB.cards]
    return {"llm": BONSAI.status(), "speech": sp, "cards": len(KB.cards), "library": library, "state": BRAIN.state()}


class Handler(BaseHTTPRequestHandler):
    server_version = "Beacon/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        if "/api/status" in (args[0] if args else ""):
            return
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- helpers -----------------------------------------------------------
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json(self):
        raw = self._body()
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            return self._send(200, status())
        if path == "/":
            path = "/index.html"
        target = (config.WEB_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(config.WEB_DIR.resolve())) or not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/transcribe":
                wav = self._body()
                if len(wav) < 2000:
                    return self._send(200, {"text": "", "ms": 0, "engine": ""})
                return self._send(200, SPEECH.transcribe(wav))
            if path == "/api/turn":
                return self._send(200, BRAIN.turn(self._json().get("text", "")))
            if path == "/api/open":
                return self._send(200, BRAIN.open(self._json().get("id", "")))
            if path == "/api/step":
                return self._send(200, BRAIN.set_step(self._json().get("step", 0)))
            if path == "/api/tts":
                text = (self._json().get("text") or "").strip()
                if not text:
                    return self._send(400, {"error": "no text"})
                audio, info = SPEECH.speak(text)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(audio)))
                self.send_header("X-Beacon-Ms", str(info["ms"]))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(audio)
                return
            if path == "/api/handoff":
                return self._send(200, BRAIN.handoff())
            if path == "/api/reset":
                return self._send(200, BRAIN.reset())
            return self._send(404, {"error": "not found"})
        except SpeechError as e:
            return self._send(503, {"error": str(e)})
        except BrokenPipeError:
            return
        except Exception as e:  # never take the server down mid-emergency
            sys.stderr.write("  error on %s: %r\n" % (path, e))
            return self._send(500, {"error": str(e)})


def check():
    """python server.py --check : prove the model answers before you record."""
    print("")
    if not BONSAI.connect():
        print("  [FAIL] Bonsai: no local model server found (tried %s)" % ", ".join(config.LLM_CANDIDATES if not config.LLM_URL else [config.LLM_URL]))
        print("         Start it first, for example:  .\\scripts\\start_llama_server.ps1  in the Bonsai-demo folder")
        return 1
    st = BONSAI.status()
    print("  [ OK ] Bonsai endpoint: %s" % st["url"])
    print("  [%s] Model: %s" % (" OK " if st["is_bonsai"] else "WARN", st["model"]))
    for text in ["my friend fell and his leg is bleeding really badly", "we can't find the trail and my phone has no signal"]:
        out = BRAIN.turn(text)
        ok = out["route"] == "bonsai" and out["card"] is not None
        print("  [%s] \"%s\"" % (" OK " if ok else "FAIL", text))
        print("         -> card: %s   route: %s   %s" % (out["card"]["title"] if out["card"] else None, out["route"], ("%d ms" % out["llm"]["ms"]) if out["llm"] else ""))
        if out["say"]:
            print("         -> says: %s" % out["say"][0])
        BRAIN.reset()
    print("")
    return 0


def _warm_when_ready():
    import time
    for _ in range(600):
        if BONSAI.url or BONSAI.connect():
            BRAIN.warmup()
            return
        time.sleep(2)


def main():
    global SPEECH
    if "--check" in sys.argv:
        sys.exit(check())
    SPEECH = make_speech()
    BONSAI.connect()
    st = status()
    threading.Thread(target=_warm_when_ready, daemon=True).start()

    url = "http://%s:%d" % (config.HOST, config.PORT)
    print("")
    print("  Beacon is running at %s" % url)
    print("  Safety cards : %d" % st["cards"])
    if st["llm"]["ok"]:
        print("  Bonsai       : %s  (%s)" % (st["llm"]["model"], st["llm"]["url"]))
        if not st["llm"]["is_bonsai"]:
            print("                 warning: this model id does not contain 'bonsai'")
    else:
        print("  Bonsai       : NOT FOUND. Start the Bonsai server, Beacon will pick it up automatically.")
    print("  Speech in    : %s" % st["speech"]["stt"])
    print("  Speech out   : %s" % st["speech"]["tts"])
    if st["speech"]["message"] not in ("ready", ""):
        print("                 %s" % st["speech"]["message"])
    print("  Press Ctrl+C to stop.")
    print("")

    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    httpd.daemon_threads = True
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
