#!/bin/bash
# Beacon on an Apple Silicon Mac: Bonsai + Argmax (WhisperKit, TTSKit), all on device.
# Start Bonsai first (Bonsai-demo: ./scripts/start_llama_server.sh, or LM Studio's local server).
set -e
cd "$(dirname "$0")"

if [ ! -x argmax-bridge/.build/release/argmax-bridge ]; then
  echo "Building the Argmax bridge (first time only, needs internet to fetch the SDK)..."
  (cd argmax-bridge && swift build -c release)
fi

export BEACON_SPEECH="${BEACON_SPEECH:-argmax}"
exec python3 server.py "$@"
