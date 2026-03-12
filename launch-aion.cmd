@echo off
title 🧠 Launching Aion - VS Code + Ollama
echo =================================================
echo 🚀 AION DEV BOOTUP STARTING...
echo =================================================

REM === ENVIRONMENT SETTINGS ===
set OLLAMA_NUM_GPU_LAYERS=999
set OLLAMA_LOG_LEVEL=debug

REM === START OLLAMA MODEL IN NEW CMD WINDOW ===
start "Ollama - Mistral" cmd /k ollama run mistral

REM === WAIT FOR MODEL TO SPIN UP ===
timeout /t 3 enul

REM === OPEN VS CODE (REAL ONE) TO AION PROJECT ===
echo Opening Visual Studio Code in C:\aion...
start "" code "C:\aion"

REM === OPTIONAL: AUDIO CONFIRMATION ===
powershell -c "Add-Type -AssemblyName System.Speech;$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer;$speak.Speak('Aion is online and ready.')"

echo =================================================
echo ✅ Aion development environment is fully live.
echo =================================================
