"""Runtime settings. Everything can be overridden with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = os.environ.get("BEACON_HOST", "127.0.0.1")
PORT = int(os.environ.get("BEACON_PORT", "8765"))

# --- Bonsai (any OpenAI-compatible local endpoint) -------------------------
# Leave BEACON_LLM_URL empty to auto-detect one of the usual local servers.
LLM_URL = os.environ.get("BEACON_LLM_URL", "").rstrip("/")
LLM_CANDIDATES = [
    "http://127.0.0.1:8080/v1",  # PrismML Bonsai-demo llama-server
    "http://127.0.0.1:8081/v1",  # PrismML Bonsai-demo mlx-vlm server
    "http://127.0.0.1:1234/v1",  # LM Studio local server
]
LLM_MODEL = os.environ.get("BEACON_LLM_MODEL", "")  # empty = first model the server lists
LLM_TIMEOUT = float(os.environ.get("BEACON_LLM_TIMEOUT", "90"))
# PrismML's "thinking off" sampling profile for the Bonsai 2 small models,
# with a slightly lower temperature because we want a decision, not prose.
LLM_SAMPLING = {
    "temperature": float(os.environ.get("BEACON_LLM_TEMPERATURE", "0.5")),
    "top_p": 0.8,
    "top_k": 20,
    "min_p": 0,
    "presence_penalty": 1.5,
    "repeat_penalty": 1.0,
    "repeat_last_n": 64,
}

# --- Speech ----------------------------------------------------------------
# auto      : Argmax bridge if it has been built (Mac), else the dev fallback
# argmax    : Argmax WhisperKit + TTSKit through the Swift bridge (Mac)
# argmax-cli: Argmax's own command line tool, one process per request (Mac, plan B)
# fallback  : faster-whisper if installed + the browser's built-in voice (Windows/Linux dev)
SPEECH = os.environ.get("BEACON_SPEECH", "auto").lower()
BRIDGE_BIN = os.environ.get(
    "BEACON_BRIDGE_BIN",
    str(ROOT / "argmax-bridge" / ".build" / "release" / "argmax-bridge"),
)
ARGMAX_CLI = os.environ.get("BEACON_ARGMAX_CLI", "argmax-cli")
WHISPER_MODEL = os.environ.get("BEACON_WHISPER_MODEL", "small.en")
TTS_MODEL = os.environ.get("BEACON_TTS_MODEL", "0.6b")
TTS_VOICE = os.environ.get("BEACON_TTS_VOICE", "serena")
FALLBACK_WHISPER_MODEL = os.environ.get("BEACON_FALLBACK_WHISPER_MODEL", "base.en")

KB_PATH = ROOT / "kb" / "protocols.json"
WEB_DIR = ROOT / "web"
