#!/usr/bin/env python3
"""A fake OpenAI-compatible server for working on the UI without a model.

FOR DEVELOPMENT ONLY. It is not a language model and must not be used in the
demo: it just keyword-matches. Run:  python tests/mock_bonsai.py  (port 8080)
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))
from beacon.kb import KnowledgeBase  # noqa: E402

KB = KnowledgeBase()
MODEL = "Ternary-Bonsai-2-4B-PQ2_0.gguf (MOCK)"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = body["messages"][-1]["content"]
        time.sleep(0.6)
        if "handoff reports" in user:
            text = ("Situation: Adult hiker with a deep cut on the lower leg after a fall, heavy bleeding.\n"
                    "Timeline: Bleeding reported and pressure started at the first log entry; tourniquet step reached later.\n"
                    "Actions taken: Direct pressure with cloth, extra layers added, patient kept lying down and warm.\n"
                    "Unknown: Age, medical history, allergies, exact time of the fall.")
        else:
            said = re.search(r'The person says: "(.*)"', user, re.S).group(1)
            open_card = re.search(r"Open card: (\w+)", user).group(1)
            hits = KB.search(said, k=1)
            if open_card != "none" and (not hits or hits[0][1] < 6 or hits[0][0]["id"] == open_card):
                obj = {"card": open_card, "say": "Keep doing what the card says. You are doing well.", "note": ""}
            elif hits:
                c = hits[0][0]
                obj = {"card": c["id"], "say": "Okay, I hear you. Stay with me and I'll guide you through it.", "note": "Reported: " + said[:60]}
            else:
                obj = {"card": "none", "say": "I'm here. Is someone hurt, or are you in danger right now?", "note": ""}
            text = json.dumps(obj)
        self._send({"choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"completion_tokens": len(text) // 4}})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print("Mock model server on http://127.0.0.1:%d/v1  (development only)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
