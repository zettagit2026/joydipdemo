#!/usr/bin/env bash
# CEMA cUAS — Linux / macOS launcher.
# Requires Docker Desktop or Docker Engine + docker compose v2.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[!] Docker is not installed. Install it from https://www.docker.com/products/docker-desktop"
  exit 1
fi

echo "==============================================="
echo " CEMA cUAS — Counter-UAS Operator Console"
echo " Booting MongoDB + FastAPI + React (Nginx)..."
echo "==============================================="

docker compose up --build -d

echo
echo "[✓] Stack is up."
echo "    Frontend  : http://localhost:3000"
echo "    Backend   : http://localhost:8001/api/"
echo "    Login     : operator@cema.mil / cema@2026"
echo
echo "Stop with:  ./stop.sh   (or docker compose down)"
