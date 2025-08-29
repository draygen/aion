@echo off
SETLOCAL ENABLEEXTENSIONS

REM ——— ✅ Point to actual working Python 3.11 path
set "PYTHON_EXE=C:\users\drayg\appdata\programs\python\python311"
set "VENV_DIR=%cd%\mistralenv"

REM ——— ✅ Add Python to PATH temporarily
set "PATH=%~dp0;%PATH%"

REM ——————————————————————————————
REM Step 2: Create virtual environment
echo Creating virtualenv...
"%PYTHON_EXE%" -m venv "%VENV_DIR%"
call "%VENV_DIR%\Scripts\activate.bat"

REM ——————————————————————————————
REM Step 3: Upgrade pip and tools
python -m pip install --upgrade pip setuptools wheel

REM ——————————————————————————————
REM Step 4: Install Git silently if missing
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Git not found. Installing Git for Windows...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/Git-2.44.0-64-bit.exe' -OutFile 'git-installer.exe'"
    start /wait git-installer.exe /VERYSILENT /NORESTART /NOCANCEL /SP- /NOICONS /DIR=\"%ProgramFiles%\Git\"
    set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
    del git-installer.exe
)

REM ——————————————————————————————
REM Step 5: Install PyTorch w/ CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

REM ——————————————————————————————
REM Step 6: Install HuggingFace tools
pip install transformers datasets accelerate huggingface-hub

REM ——————————————————————————————
REM Step 7: Install bitsandbytes with CUDA
pip install git+https://github.com/TimDettmers/bitsandbytes.git

REM ——————————————————————————————
REM Step 8: Login to HuggingFace
echo.
echo ====== HUGGINGFACE LOGIN ======
echo Paste your token below:
huggingface-cli login

REM ——————————————————————————————
REM Step 9: Run training script
echo.
echo ====== RUNNING TRAIN SCRIPT ======
python trainllm.py

REM ——————————————————————————————
REM Done
pause
