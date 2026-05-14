@echo off
REM AIRA Social Media Agent — local dev launcher
REM   1. Starts server.py in a new window
REM   2. Starts ngrok tunnel in a new window
REM   3. Waits, grabs the public URL from ngrok's local API
REM   4. Registers the Telegram webhook

setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

set "PYTHON=C:\Users\lucas\anaconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo === AIRA Social Media Agent — dev launcher ===
echo.
echo [1/4] Starting server.py in a new window...
start "AIRA server" cmd /k ""%PYTHON%" server.py"

echo [2/4] Starting ngrok tunnel on port 10000...
start "AIRA ngrok" cmd /k "ngrok http 10000"

echo [3/4] Waiting 5s for ngrok to come up...
timeout /t 5 /nobreak >nul

echo [4/4] Querying ngrok local API for tunnel URL...
for /f "delims=" %%i in ('%PYTHON% -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels')); print([t['public_url'] for t in d['tunnels'] if t['public_url'].startswith('https')][0])"') do set "TUNNEL=%%i"

if "!TUNNEL!"=="" (
    echo ERROR: could not detect ngrok tunnel URL. Is ngrok running?
    pause
    exit /b 1
)

echo Tunnel URL: !TUNNEL!
echo.
echo Registering Telegram webhook...
"%PYTHON%" set_webhook.py !TUNNEL!

echo.
echo === Ready ===
echo   Tunnel:   !TUNNEL!
echo   Webhook:  !TUNNEL!/telegram/callback
echo.
echo Now message @aira_social_bot on Telegram with /start
echo.
echo Close the "AIRA server" and "AIRA ngrok" windows to stop.
pause
