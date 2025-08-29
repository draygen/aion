# ------------------------------------------------------------------
# Final JARVIS Prep Script (VMDK → QCOW2 → shrink → IMG)
# Requires: GParted has already shrunk filesystem inside the VM
# ------------------------------------------------------------------

$vmDir        = "C:\Users\drayg\Documents\Virtual Machines\KaliLinux"
$qemuPath     = "C:\qemu\qemu-img.exe"
$sourceVMDK   = "$vmDir\KaliLinux-merged.vmdk"
$qcowOutput   = "$vmDir\KaliLinux.qcow2"
$resizedCap   = "100G"
$finalIMG     = "$vmDir\kali-jarvis.img"

Write-Host ""
Write-Host "Step 1: Converting VMDK → QCOW2..." -ForegroundColor Cyan
& "$qemuPath" convert -p -O qcow2 "$sourceVMDK" "$qcowOutput"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Step 1 failed: VMDK → QCOW2 conversion failed."
    exit 1
}

Write-Host ""
Write-Host "Step 2: Shrinking QCOW2 to $resizedCap..." -ForegroundColor Yellow
& "$qemuPath" resize --shrink "$qcowOutput" $resizedCap
if ($LASTEXITCODE -ne 0) {
    Write-Error "Step 2 failed: Resize failed. Did you shrink the filesystem inside the VM using GParted?"
    exit 1
}

Write-Host ""
Write-Host "Step 3: Converting QCOW2 → IMG (raw)..." -ForegroundColor Green
& "$qemuPath" convert -p -O raw "$qcowOutput" "$finalIMG"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Step 3 failed: QCOW2 → IMG conversion failed."
    exit 1
}

Write-Host ""
Write-Host "✅ Done! Final bootable IMG saved at:" -ForegroundColor Cyan
Write-Host "$finalIMG" -ForegroundColor Magenta
Write-Host ""
Write-Host "➡ Flash it using Rufus in DD Image mode." -ForegroundColor Yellow
