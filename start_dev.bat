@echo off
REM AIRA Social Media Agent - local dev launcher (cloudflared edition)
REM
REM Uses cloudflared instead of ngrok because the free ngrok tier injects a
REM browser-warning interstitial that Instagram's Graph API fetcher can't bypass.

setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

REM === ALWAYS PAUSE ON ANY EXIT ===
if "%1"=="" (
    cmd /k call "%~f0" __nested
    exit /b
)

set "PYTHON=C:\Users\lucas\anaconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe"
if not exist "%CLOUDFLARED%" (
    echo.
    echo ERROR: cloudflared not found at:
    echo   %CLOUDFLARED%
    echo Install from https://github.com/cloudflare/cloudflared/releases
    echo.
    goto :end
)

set "TUNNEL_LOG=%TEMP%\aira_cloudflared.log"
del "%TUNNEL_LOG%" 2>nul

echo === AIRA Social Media Agent - dev launcher ===
echo.
echo [1/4] Starting server.py in a new window...
start "AIRA server" cmd /k ""%PYTHON%" server.py"

echo [2/4] Starting cloudflared tunnel on port 10000...
start "AIRA cloudflared" cmd /k ""%CLOUDFLARED%" tunnel --url http://localhost:10000 --no-autoupdate --logfile "%TUNNEL_LOG%""

echo [3/4] Waiting up to 25s for cloudflared to publish a tunnel URL...
set "TUNNEL="
for /l %%n in (1,1,25) do (
    timeout /t 1 /nobreak >nul
    call :try_parse_tunnel
    if defined TUNNEL goto :got_tunnel
)

:got_tunnel
if not defined TUNNEL (
    echo.
    echo ERROR: could not detect cloudflared tunnel URL after 25s.
    echo Check the "AIRA cloudflared" window or:
    echo   %TUNNEL_LOG%
    echo.
    goto :end
)

echo Tunnel URL: !TUNNEL!
echo.
echo [4/4] Registering Telegram webhook + writing PUBLIC_BASE_URL...
"%PYTHON%" set_webhook.py !TUNNEL!
"%PYTHON%" tools\set_public_base_url.py !TUNNEL!

echo.
echo === Ready ===
echo   Tunnel:   !TUNNEL!
echo   Webhook:  !TUNNEL!/telegram/callback
echo   Media:    !TUNNEL!/media/^<post_id^>/^<n^>.jpg
echo.
echo Now message @aira_social_bot on Telegram with /start
echo.
echo Close the "AIRA server" and "AIRA cloudflared" windows to stop.
goto :end

:try_parse_tunnel
if not exist "%TUNNEL_LOG%" exit /b
for /f "usebackq tokens=*" %%i in (`"%PYTHON%" tools\parse_tunnel_url.py "%TUNNEL_LOG%"`) do set "TUNNEL=%%i"
exit /b

:end
echo.
pause
endlocal
