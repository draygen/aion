# Launch Aion with GPU settings (NVIDIA)
# Usage: run from any PowerShell: pwsh -ExecutionPolicy Bypass -File C:\aion\launch-aion.ps1

# Maximize GPU offload for Ollama
$env:OLLAMA_NUM_GPU_LAYERS = 999
$env:OLLAMA_LOG_LEVEL = 'debug'

# Ensure we run from the project directory so data paths resolve
Set-Location -LiteralPath 'C:\aion'

Write-Host 'Starting Aion with GPU acceleration (OLLAMA_NUM_GPU_LAYERS=999)...'

# Start the REPL
py .\main.py

