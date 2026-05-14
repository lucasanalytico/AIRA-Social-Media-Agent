@echo off
REM Kill the AIRA dev windows + delete the Telegram webhook so polling can be reused elsewhere.

set "PYTHON=C:\Users\lucas\anaconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo Stopping AIRA server + ngrok windows...
taskkill /FI "WINDOWTITLE eq AIRA server*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AIRA ngrok*" /T /F >nul 2>&1
taskkill /IM ngrok.exe /F >nul 2>&1

echo Deleting Telegram webhook...
"%PYTHON%" -c "import os; from dotenv import load_dotenv" 2>nul || (
  REM No python-dotenv? Use the inline loader from set_webhook.py instead.
)
"%PYTHON%" -c "import os, requests; [os.environ.setdefault(k.strip(), v.strip()) for line in open('.env') for k,_,v in [line.strip().partition('=')] if k and not k.startswith('#')]; t=os.environ['TELEGRAM_BOT_TOKEN']; print(requests.post(f'https://api.telegram.org/bot{t}/deleteWebhook').json())"

echo Done.
pause
