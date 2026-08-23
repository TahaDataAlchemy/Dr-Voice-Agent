@echo off
REM One-shot dev launcher: API in a new window (port 8000), Next.js dev server in THIS window (port 3000).
cd /d "%~dp0"
start "patient-voice-agent API :8000" cmd /k "uv run python main.py -d"
cd frontend
echo.
echo   Dashboard: http://localhost:3000/app     API docs: http://localhost:8000/docs
echo.
npm run dev
