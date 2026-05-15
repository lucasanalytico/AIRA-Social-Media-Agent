@echo off
REM AIRA Social Media Agent - local dev launcher (cloudflared edition)
REM
REM Uses cloudflared instead of ngrok because the free ngrok tier injects a
REM browser-warning interstitial that Instagram's Graph API fetcher can't bypass
REM when it tries to download /media/<post_id>/<n>.jpg. cloudflared serves raw.

setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

set "PYTHON=C:\Users\lucas\anaconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe"
if not exist "%CLOUDFLARED%" (
    echo ERROR: cloudflared not found at %CLOUDFLARED%
    echo Install from https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
)

set "TUNNEL_LOG=%TEMP%\aira_cloudflared.log"
del "%TUNNEL_LOG%" 2>nul

echo === AIRA Social Media Agent - dev launcher ===
echo.
echo [1/4] Starting server.py in a new window...
start "AIRA server" cmd /k ""%PYTHON%" server.py"

echo [2/4] Starting cloudflared tunnel on port 10000...
start "AIRA cloudflared" cmd /k ""%CLOUDFLARED%" tunnel --url http://localhost:10000 --no-autoupdate --logfile "%TUNNEL_LOG%""

echo [3/4] Waiting up to 20s for cloudflared to publish a tunnel URL...
set "TUNNEL="
for /l %%n in (1,1,20) do (
    timeout /t 1 /nobreak >nul
    if exist "%TUNNEL_LOG%" (
        for /f "tokens=*" %%i in ('%PYTHON% -c "import re,sys; m=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', open(r'%TUNNEL_LOG%').read()); print(m.group(0) if m else '')"') do (
            if not "%%i"=="" set "TUNNEL=%%i"
        )
    )
    if defined TUNNEL goto :got_tunnel
)

:got_tunnel
if not defined TUNNEL (
    echo ERROR: could not detect cloudflared tunnel URL after 20s.
    echo Check the AIRA cloudflared window or %TUNNEL_LOG%.
    pause
    exit /b 1
)

echo Tunnel URL: !TUNNEL!
echo.
echo [4/4] Registering Telegram webhook + writing PUBLIC_BASE_URL...
"%PYTHON%" set_webhook.py !TUNNEL!
"%PYTHON%" -c "import re,pathlib; p=pathlib.Path('.env'); t=p.read_text(); t=re.sub(r'^PUBLIC_BASE_URL=.*', 'PUBLIC_BASE_URL=!TUNNEL!', t, flags=re.M); p.write_text(t); print('PUBLIC_BASE_URL set to !TUNNEL!')"

echo.
echo === Ready ===
echo   Tunnel:   !TUNNEL!
echo   Webhook:  !TUNNEL!/telegram/callback
echo   Media:    !TUNNEL!/media/^<post_id^>/^<n^>.jpg
echo.
echo Now message @aira_social_bot on Telegram with /start
echo.
echo Close the "AIRA server" and "AIRA cloudflared" windows to stop.
pause
