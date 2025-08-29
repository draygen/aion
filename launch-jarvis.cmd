@echo off
title 🧠 Launching Jarvis - VS Code + Ollama
echo =================================================
echo 🚀 JARVIS DEV BOOTUP STARTING...
echo =================================================

REM === ENVIRONMENT SETTINGS ===
set OLLAMA_NUM_GPU_LAYERS=999
set OLLAMA_LOG_LEVEL=debug

REM === START OLLAMA MODEL IN NEW CMD WINDOW ===
start "Ollama - Mistral" cmd /k ollama run mistral

REM === WAIT FOR MODEL TO SPIN UP ===
timeout /t 3 enul

REM === OPEN VS CODE (REAL ONE) TO JARVIS PROJECT ===
echo Opening Visual Studio Code in C:\jarvis...
start "" code "C:\jarvis"

REM === OPTIONAL: AUDIO CONFIRMATION ===
powershell -c "Add-Type -AssemblyName System.Speech;$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer;$speak.Speak('Jarvis is online and ready.')"

echo =================================================
echo ✅ Jarvis development environment is fully live.
echo =================================================
