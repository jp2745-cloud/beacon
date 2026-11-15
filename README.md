# Beacon

**The emergency companion that works when the internet doesn't.**

Hold the space bar, say what is happening ("my friend cut his leg and it won't stop bleeding"), and Beacon finds the right safety card and talks you through it one step at a time, hands-free. Speech recognition, the language model and the voice all run on the laptop. Turn Wi-Fi off and nothing changes.

Built for the Cornell Commons Local AI Hackathon, theme **RECREATE**: voice assistants and first-aid apps already exist, but they need a connection, and emergencies are exactly when you lose it. A trail with no signal, an earthquake that takes the cell network down, a blackout.

## What it does

- **Understands a panicked sentence.** You don't pick from a menu. Bonsai reads what you said, chooses one of 16 safety cards, and answers in one calm line.
- **Reads vetted steps aloud, one at a time.** Say "next", "repeat" or "go back" while your hands are busy.
- **Answers follow-up questions from the card.** "Can I put ice on it?" gets an answer grounded in the open card's text.
- **Built-in tools where a step needs them.** A 110-per-minute beat for CPR compressions, countdown timers for "press for ten minutes".
- **Keeps a timestamped incident log** and has Bonsai turn it into a four-line handoff report for responders.
- **Shows its work.** The side panel shows how long each on-device stage took, and how many turns were answered without waking the model at all.

## How Bonsai and Argmax are used

| Stage | Runs on | What it does |
|---|---|---|
| Speech to text | **Argmax WhisperKit** | Transcribes push-to-talk audio on the Neural Engine |
| Understanding | **Bonsai 2** (2B, 4B or 9B) | Triage: picks the card, writes the spoken reply, extracts facts for the log |
| Follow-up answers | **Bonsai 2** | Answers questions using only the open card's text |
| Handoff report | **Bonsai 2** | Summarises the incident log for responders |
| Text to speech | **Argmax TTSKit** | Speaks every line, sentence by sentence |

```
 microphone ──► browser UI ──► Python server ──► Swift bridge ──► Argmax WhisperKit
                    ▲               │
                    │               ├─ rules ─────────────► "next / repeat / back"   (no model)
                    │               ├─ fast path ─────────► "not breathing" → CPR    (no model)
                    │               └─ Bonsai 2 ──────────► card + reply + log note
                    │               │        (local OpenAI-compatible endpoint)
                    │               ▼
                    └── audio ◄── Swift bridge ──► Argmax TTSKit
```

Argmax's SDK is Swift-only, so `argmax-bridge/` is a small Swift program that keeps WhisperKit and TTSKit loaded and talks to the Python server over a line-based JSON protocol. This is the "simple Swift server, interface via Python" route from the hackathon's technical notes.

## Design decisions

**The model never writes first-aid steps.** Steps come word for word from `kb/protocols.json`. Bonsai routes, reassures and answers from the card text. A small model that hallucinates a dose is dangerous; a small model that picks between sixteen cards is reliable.

**Right-sized inference.** "Next" does not need a language model, so it never reaches one: a handful of regular expressions handle step navigation. An unmistakable life-threat phrase such as "he's not breathing" opens the CPR card immediately instead of waiting for generation. Card lookup uses keyword matching rather than an embedding model. Bonsai is only called when a sentence actually needs understanding, and the fixed part of its prompt is warmed into the server's prompt cache at start-up so each request only processes the new sentence. The interface counts model calls against rule-handled turns so the saving is visible.

**It degrades instead of failing.** If the model server goes away, Beacon still opens the best keyword match and says so.

## Run it on an Apple Silicon Mac

Requirements: macOS 15 or later, Xcode 16 or later (for `swift build`), Python 3 (ships with the Xcode command line tools). Do these steps once while online; afterwards everything runs with Wi-Fi off.

```bash
# 1. Bonsai, using PrismML's demo repo (llama.cpp on Metal)
git clone https://github.com/PrismML-Eng/Bonsai-demo.git
cd Bonsai-demo
BONSAI_MODEL=4B ./setup.sh
BONSAI_MODEL=4B BONSAI_THINKING=0 ./scripts/start_llama_server.sh     # serves http://localhost:8080

# 2. Beacon, in a second terminal
cd beacon
bash start_mac.sh     # builds the Argmax bridge the first time, then opens http://127.0.0.1:8765
```

The first launch downloads the Whisper `small.en` model and the TTSKit 0.6B voice model. Wait until the top-right pill reads "Argmax WhisperKit and TTSKit", then turn Wi-Fi off. The first pill switches to "Wi-Fi off. Running on this laptop".

Any OpenAI-compatible local endpoint serving Bonsai works. Beacon checks ports 8080 (llama-server), 8081 (PrismML's mlx-vlm server) and 1234 (LM Studio) by itself, or set `BEACON_LLM_URL`.

Check the model before recording a demo:

```bash
python3 server.py --check
```

## Develop on Windows or Linux

Argmax needs Apple Silicon, so on other machines Beacon runs in development mode: Bonsai is real, speech uses stand-ins (faster-whisper if installed, plus the browser's offline voice). The interface says "Development voice, not Argmax" so the two are never confused.

```powershell
# Bonsai (PowerShell)
git clone https://github.com/PrismML-Eng/Bonsai-demo.git
cd Bonsai-demo
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:BONSAI_MODEL = "4B"
$env:BONSAI_THINKING = "0"
.\setup.ps1
.\scripts\start_llama_server.ps1

# Beacon (second window)
pip install faster-whisper      # optional: lets you talk instead of type
python server.py
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `BEACON_LLM_URL` | auto-detect | Base URL of the Bonsai endpoint, for example `http://127.0.0.1:1234/v1` |
| `BEACON_LLM_MODEL` | first model listed | Model id to request |
| `BEACON_SPEECH` | `auto` | `argmax`, `argmax-cli` or `fallback` |
| `BEACON_WHISPER_MODEL` | `small.en` | WhisperKit model |
| `BEACON_TTS_MODEL` | `0.6b` | TTSKit model (`0.6b` or `1.7b`) |
| `BEACON_TTS_VOICE` | `serena` | TTSKit voice |
| `BEACON_PORT` | `8765` | Port for the interface |

## Tests

```bash
python -m unittest discover -s tests -v
```

Fourteen offline tests cover routing, the rule and fast paths, card switching, containment of bad model output, and behaviour when the model is unreachable. `tests/mock_bonsai.py` and `tests/fake_bridge.py` are stand-ins for working on the interface without the real models. They are not used at run time.

## Layout

```
server.py                 HTTP server (Python standard library only)
beacon/brain.py           routing: rules, fast path, Bonsai prompt, handoff report
beacon/llm.py             client for the local Bonsai endpoint
beacon/kb.py              safety cards and keyword retrieval
beacon/speech.py          Argmax bridge client and the development fallback
argmax-bridge/            Swift program wrapping WhisperKit and TTSKit
kb/protocols.json         the 16 safety cards
web/                      interface (no frameworks, no CDN, fonts bundled)
```

## Limits

- Beacon is a hackathon prototype, not a medical device. The cards follow public guidance from the American Red Cross, American Heart Association, CDC, Ready.gov and the US Forest Service, but they have not been medically reviewed. In a real emergency, call emergency services whenever you can.
- English only for now. Whisper, Bonsai and TTSKit all handle other languages, so multilingual cards are the obvious next step.
- Push-to-talk rather than always listening, by choice: it is predictable in a noisy place and it never records by accident.

## Credits

- [Bonsai 2](https://github.com/PrismML-Eng/Bonsai-demo) by PrismML, [Argmax Open-Source SDK](https://github.com/argmaxinc/argmax-oss-swift) (WhisperKit, TTSKit) by Argmax.
- Fonts: Barlow Condensed and Atkinson Hyperlegible, both under the SIL Open Font License (see `web/fonts/`).
- Code written with help from an AI coding assistant (Claude).
