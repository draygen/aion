@echo off
echo === ACTIVATE VENV ===
call data\mistralenv\Scripts\activate

echo === RUN TRAIN SCRIPT ===
python trainllm.py

pause
