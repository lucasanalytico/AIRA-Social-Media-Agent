@echo off
REM AIRA Social Media Agent — dev launcher.
REM Delegates to tools\dev_launcher.py to avoid cmd's quote/parenthesis quirks.

cd /d "%~dp0"

set "PYTHON=C:\Users\lucas\anaconda3\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" tools\dev_launcher.py
echo.
pause
