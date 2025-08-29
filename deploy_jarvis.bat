@echo off
cd /d %~dp0
if exist "%SystemRoot%\py.exe" (
    py -m pip install -r requirements.txt
) else (
    python -m pip install -r requirements.txt
)
echo.
echo =========================
echo JARVIS DEPLOYED IN C:\jarvis
echo Run: py main.py
echo =========================
pause
