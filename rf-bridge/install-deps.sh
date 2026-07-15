#!/usr/bin/env bash
# CEMA cUAS RF Bridge — one-time host install (Debian/Ubuntu).
# Installs: HackRF tools + libraries, Python venv, Python deps, udev rules.
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "==> apt: hackrf + libhackrf-dev + libusb + python venv"
sudo apt-get update
sudo apt-get install -y \
    hackrf libhackrf-dev libhackrf0 \
    libusb-1.0-0-dev pkg-config \
    python3-venv python3-pip

echo "==> udev: allow non-root access to /dev/ttyUSB* and HackRF"
sudo usermod -a -G dialout,plugdev "$USER" || true

# HackRF udev rules ship with the package; nothing to install by hand.

echo "==> python venv"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> configuration file"
if [ ! -f ".env" ]; then
    cp env.example .env
    echo "    Created .env from env.example — edit it if needed."
fi

echo
echo "==> Sanity checks"
if command -v hackrf_info >/dev/null; then
    hackrf_info || true
else
    echo "!! hackrf_info missing — apt install may have failed."
fi
if [ -e /dev/ttyUSB0 ]; then
    echo "   /dev/ttyUSB0 present."
else
    echo "!! /dev/ttyUSB0 missing — is the FPV telemetry radio plugged in?"
fi

echo
echo "==> DONE."
echo "    You may need to log out and back in for the 'dialout' group to take effect."
echo "    Then run:   ./run.sh   or   ./run.sh scanner   or   ./run.sh bridge"
