#!/usr/bin/env bash
# Start the RF bridge workers.
#   ./run.sh          → both scanner + mavlink bridge (foreground)
#   ./run.sh scanner  → only HackRF sweep worker
#   ./run.sh bridge   → only MAVLink serial bridge
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "!! .venv missing. Run ./install-deps.sh first."
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

MODE="${1:-both}"

case "$MODE" in
    scanner)
        exec python hackrf_scanner.py
        ;;
    bridge)
        exec python mavlink_bridge.py
        ;;
    both)
        python hackrf_scanner.py & SCANNER_PID=$!
        python mavlink_bridge.py & BRIDGE_PID=$!
        trap "kill $SCANNER_PID $BRIDGE_PID 2>/dev/null || true" INT TERM
        wait
        ;;
    *)
        echo "Usage: $0 [scanner|bridge|both]"
        exit 1
        ;;
esac
