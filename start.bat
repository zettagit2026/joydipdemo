@echo off
REM CEMA cUAS - Windows launcher.
REM Requires Docker Desktop for Windows.

cd /d "%~dp0"

where docker >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Docker is not installed or not in PATH.
  echo     Install Docker Desktop from https://www.docker.com/products/docker-desktop
  pause
  exit /b 1
)

echo ===============================================
echo  CEMA cUAS - Counter-UAS Operator Console
echo  Booting MongoDB + FastAPI + React (Nginx)...
echo ===============================================

docker compose up --build -d
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Docker Compose failed. Ensure Docker Desktop is running.
  pause
  exit /b 1
)

echo.
echo [OK] Stack is up.
echo     Frontend  : http://localhost:3000
echo     Backend   : http://localhost:8001/api/
echo     Login     : operator@cema.mil / cema@2026
echo.
echo Stop with:  stop.bat   (or docker compose down)
pause
