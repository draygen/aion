@echo off
cd /d %~dp0
if exist "%SystemRoot%\py.exe" (
    py -m pip install -r requirements.txt
) else (
    python -m pip install -r requirements.txt
)
echo.
echo =========================
echo AION DEPLOYED IN C:\aion
echo Run: py main.py
echo =========================
pause
