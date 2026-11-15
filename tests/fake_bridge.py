#!/usr/bin/env python3
"""Stands in for the Swift argmax-bridge so the Python side and the browser
can be tested on a machine without Argmax. Same line protocol. TEST ONLY."""
import io, json, math, struct, sys, time, wave

def emit(o):
    sys.stdout.write("@@BEACON " + json.dumps(o) + "\n"); sys.stdout.flush()

print("some library logging that must be ignored", flush=True)
emit({"event": "status", "message": "Loading fake models"})
time.sleep(0.3)
emit({"event": "ready", "whisper": "fake", "tts": "fake", "voice": "fake"})
for line in sys.stdin:
    req = json.loads(line)
    if req["cmd"] == "transcribe":
        with wave.open(req["path"], "rb") as w:
            info = "%dHz %dch %dbit %.2fs" % (w.getframerate(), w.getnchannels(), w.getsampwidth() * 8, w.getnframes() / w.getframerate())
        sys.stderr.write("transcribe got " + info + "\n"); sys.stderr.flush()
        emit({"id": req["id"], "ok": True, "text": " [BLANK_AUDIO] My friend burned her hand on the camp stove.", "ms": 120})
    elif req["cmd"] == "speak":
        n = int(24000 * 0.35)
        with wave.open(req["out"], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(i * 0.12))) for i in range(n)))
        emit({"id": req["id"], "ok": True, "path": req["out"], "ms": 80, "seconds": 0.35})
    else:
        emit({"id": req["id"], "ok": False, "error": "unknown"})
