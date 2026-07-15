@echo off
cd /d "%~dp0"
docker compose down
echo [OK] CEMA cUAS stopped.
pause
