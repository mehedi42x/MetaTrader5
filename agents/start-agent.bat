@echo off
REM ---------------------------------------------------------------------------
REM  MT5 Web Console - Bridge agent launcher (Windows)
REM  Double-click once, or put a shortcut in shell:startup to survive reboots.
REM  Fill the two values below (both come from the web app: Bridge Agent tab).
REM ---------------------------------------------------------------------------
setlocal
set "MT5WEB_URL=https://YOUR-APP.onrender.com/ws/agent"
set "MT5WEB_KEY=paste-your-bridge-key-here"
set "MT5WEB_NAME=%COMPUTERNAME%"
REM Optional: pin a specific terminal install (leave empty to auto-detect)
set "MT5_TERMINAL_PATH="

cd /d "%~dp0"
where python >nul 2>nul || (echo [agent] python not found - install 64-bit Python 3.11-3.12 & pause & exit /b 1)

if not exist ".venv\Scripts\python.exe" (
  echo [agent] creating virtualenv + installing dependencies...
  python -m venv .venv || (echo [agent] venv failed & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r agent\requirements.txt
  if errorlevel 1 (echo [agent] pip install failed - check that this is 64-bit Windows Python & pause & exit /b 1)
)

if defined MT5_TERMINAL_PATH set "EXTRA=--terminal-path %MT5_TERMINAL_PATH%"
echo [agent] starting. Keep this window open.
".venv\Scripts\python.exe" agent\main.py --url "%MT5WEB_URL%" --key "%MT5WEB_KEY%" --name "%MT5WEB_NAME%" %EXTRA%
pause
