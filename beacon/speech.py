"""Speech in and out.

On the Mac, both directions go through Argmax's on-device models:
WhisperKit for speech-to-text and TTSKit for text-to-speech, reached through
the small Swift program in argmax-bridge/ (Argmax's SDK is Swift-only).

On Windows or Linux there is no Argmax, so a development fallback keeps the
rest of the app usable: faster-whisper for speech-to-text if it is installed,
and the browser's built-in offline voice for text-to-speech.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import config

_TAGS = re.compile(r"<\|[^|]*\|>|\[[A-Z_ ]+\]|\([a-z ]+\)")
_MARK = "@@BEACON "


def clean_transcript(text):
    text = _TAGS.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


class SpeechError(Exception):
    pass


# ---------------------------------------------------------------------------
# Argmax through the Swift bridge (models stay loaded between requests)
# ---------------------------------------------------------------------------
class ArgmaxBridge:
    name = "argmax"

    def __init__(self):
        self.proc = None
        self.ready = False
        self.message = "starting"
        self.error = None
        self.info = {}
        self._pending = {}
        self._next_id = 0
        self._lock = threading.Lock()
        self._io = threading.Lock()
        self._tmp = tempfile.mkdtemp(prefix="beacon-")
        self._start()

    def _start(self):
        cmd = [config.BRIDGE_BIN, "--whisper", config.WHISPER_MODEL, "--tts", config.TTS_MODEL, "--voice", config.TTS_VOICE]
        self._errlog = open(os.path.join(self._tmp, "bridge.log"), "w")
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._errlog, text=True, bufsize=1, encoding="utf-8", errors="replace"
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            if not line.startswith(_MARK):
                continue  # library logging, ignore
            try:
                msg = json.loads(line[len(_MARK):])
            except Exception:
                continue
            ev = msg.get("event")
            if ev == "status":
                self.message = msg.get("message", "")
            elif ev == "ready":
                self.info = msg
                self.ready = True
                self.message = "ready"
            elif ev == "fatal":
                self.error = msg.get("message", "bridge failed")
            elif "id" in msg:
                q = self._pending.pop(msg["id"], None)
                if q is not None:
                    q.put(msg)
        if not self.ready and not self.error:
            self.error = "bridge exited before it was ready (see %s)" % os.path.join(self._tmp, "bridge.log")
        self.ready = False

    def _call(self, payload, timeout):
        if self.error:
            raise SpeechError(self.error)
        if not self.ready:
            raise SpeechError("Argmax models are still loading: %s" % self.message)
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            q = queue.Queue()
            self._pending[rid] = q
        payload = dict(payload, id=rid)
        with self._io:
            try:
                self.proc.stdin.write(json.dumps(payload) + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                raise SpeechError("bridge is not running: %s" % e)
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            self._pending.pop(rid, None)
            raise SpeechError("Argmax timed out")
        if not msg.get("ok"):
            raise SpeechError(msg.get("error", "Argmax request failed"))
        return msg

    def status(self):
        has_tts = bool(self.info.get("tts")) or not self.ready
        return {
            "provider": "argmax",
            "ready": self.ready,
            "message": self.error or self.info.get("note") or self.message,
            "stt": "Argmax WhisperKit %s" % config.WHISPER_MODEL,
            "tts": ("Argmax TTSKit %s" % config.TTS_MODEL) if has_tts else "system voice (TTSKit did not load)",
            "tts_mode": "server" if has_tts else "browser",
            "tts_ok": has_tts,
            "error": self.error,
        }

    def transcribe(self, wav_bytes):
        path = os.path.join(self._tmp, "in-%d.wav" % int(time.time() * 1000))
        with open(path, "wb") as f:
            f.write(wav_bytes)
        t0 = time.time()
        try:
            msg = self._call({"cmd": "transcribe", "path": path}, timeout=120)
        finally:
            _unlink(path)
        return {"text": clean_transcript(msg.get("text", "")), "ms": int((time.time() - t0) * 1000), "engine": self.status()["stt"]}

    def speak(self, text):
        out = os.path.join(self._tmp, "out-%d.wav" % int(time.time() * 1000))
        t0 = time.time()
        msg = self._call({"cmd": "speak", "text": text, "out": out}, timeout=180)
        path = msg.get("path", out)
        try:
            with open(path, "rb") as f:
                data = f.read()
        finally:
            _unlink(path)
        return data, {"ms": int((time.time() - t0) * 1000), "engine": self.status()["tts"]}


# ---------------------------------------------------------------------------
# Argmax through its own CLI (plan B on the Mac: slower, reloads models per call)
# ---------------------------------------------------------------------------
class ArgmaxCLI:
    name = "argmax-cli"

    def __init__(self):
        self.bin = shutil.which(config.ARGMAX_CLI) or config.ARGMAX_CLI
        self._tmp = tempfile.mkdtemp(prefix="beacon-")

    def status(self):
        ok = bool(shutil.which(self.bin) or os.path.exists(self.bin))
        return {
            "provider": "argmax-cli",
            "ready": ok,
            "message": "ready" if ok else "argmax-cli not found (set BEACON_ARGMAX_CLI)",
            "stt": "Argmax WhisperKit %s (CLI)" % config.WHISPER_MODEL,
            "tts": "Argmax TTSKit %s (CLI)" % config.TTS_MODEL,
            "tts_mode": "server",
            "error": None if ok else "argmax-cli not found",
        }

    def transcribe(self, wav_bytes):
        path = os.path.join(self._tmp, "in-%d.wav" % int(time.time() * 1000))
        with open(path, "wb") as f:
            f.write(wav_bytes)
        t0 = time.time()
        try:
            r = subprocess.run(
                [self.bin, "transcribe", "--audio-path", path, "--model", config.WHISPER_MODEL, "--language", "en",
                 "--skip-special-tokens", "--without-timestamps"],
                capture_output=True, text=True, timeout=180,
            )
        finally:
            _unlink(path)
        if r.returncode != 0:
            raise SpeechError((r.stderr or r.stdout)[-300:])
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        return {"text": clean_transcript(lines[-1] if lines else ""), "ms": int((time.time() - t0) * 1000), "engine": self.status()["stt"]}

    def speak(self, text):
        base = os.path.join(self._tmp, "out-%d" % int(time.time() * 1000))
        t0 = time.time()
        r = subprocess.run(
            [self.bin, "tts", "--text", text, "--model", config.TTS_MODEL, "--speaker", config.TTS_VOICE,
             "--output-path", base, "--output-format", "wav"],
            capture_output=True, text=True, timeout=240,
        )
        if r.returncode != 0 or not os.path.exists(base + ".wav"):
            raise SpeechError((r.stderr or r.stdout)[-300:])
        with open(base + ".wav", "rb") as f:
            data = f.read()
        _unlink(base + ".wav")
        return data, {"ms": int((time.time() - t0) * 1000), "engine": self.status()["tts"]}


# ---------------------------------------------------------------------------
# Development fallback (Windows / Linux)
# ---------------------------------------------------------------------------
class Fallback:
    name = "fallback"

    def __init__(self):
        self._model = None
        self._load_error = None
        self._loading = False
        try:
            import faster_whisper  # noqa: F401
            self.has_whisper = True
        except Exception:
            self.has_whisper = False
        if self.has_whisper:
            threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        self._loading = True
        try:
            from faster_whisper import WhisperModel
            # CPU + int8 works on every laptop; base.en is fast enough for short commands.
            self._model = WhisperModel(config.FALLBACK_WHISPER_MODEL, device="cpu", compute_type="int8")
        except Exception as e:
            self._load_error = str(e)
        self._loading = False

    def status(self):
        if not self.has_whisper:
            stt, ready, msg = "typing only", True, "Speech-to-text is off: run  pip install faster-whisper  to talk on this machine"
        elif self._load_error:
            stt, ready, msg = "typing only", True, "faster-whisper failed to load: %s" % self._load_error
        elif self._model is None:
            stt, ready, msg = "faster-whisper %s" % config.FALLBACK_WHISPER_MODEL, False, "loading speech model"
        else:
            stt, ready, msg = "faster-whisper %s" % config.FALLBACK_WHISPER_MODEL, True, "ready"
        return {
            "provider": "fallback",
            "ready": ready,
            "message": msg,
            "stt": stt,
            "tts": "browser voice",
            "tts_mode": "browser",
            "can_listen": self._model is not None,
            "error": None,
        }

    def transcribe(self, wav_bytes):
        if self._model is None:
            raise SpeechError(self.status()["message"])
        import io
        t0 = time.time()
        segments, _ = self._model.transcribe(io.BytesIO(wav_bytes), language="en", beam_size=1, vad_filter=False)
        text = " ".join(s.text for s in segments)
        return {"text": clean_transcript(text), "ms": int((time.time() - t0) * 1000), "engine": self.status()["stt"]}

    def speak(self, text):
        raise SpeechError("text-to-speech runs in the browser in fallback mode")


def _unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def make_speech():
    mode = config.SPEECH
    if mode == "auto":
        mode = "argmax" if (sys.platform == "darwin" and os.path.exists(config.BRIDGE_BIN)) else "fallback"
    if mode == "argmax":
        if not os.path.exists(config.BRIDGE_BIN):
            raise SystemExit("Argmax bridge not built. Run:  cd argmax-bridge && swift build -c release")
        return ArgmaxBridge()
    if mode == "argmax-cli":
        return ArgmaxCLI()
    return Fallback()
