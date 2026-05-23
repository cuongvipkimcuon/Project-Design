# Build DG House (Windows)
# Output: dist/DG House/DG House.exe

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Building DG House (onedir)..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm "DG House.spec"

$out = Join-Path $PSScriptRoot "dist\DG House"
$exe = Join-Path $out "DG House.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed: exe not found."
}

Copy-Item -Force ".env.example" (Join-Path $out ".env.example")
if (Test-Path ".env") {
    Copy-Item -Force ".env" (Join-Path $out ".env")
    Write-Host "Copied .env to dist" -ForegroundColor Yellow
}

$zip = Join-Path $PSScriptRoot "dist\DG-House-v1.0-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip -Force

Write-Host ""
Write-Host "Done:" -ForegroundColor Green
Write-Host "  Folder: $out"
Write-Host "  Zip:    $zip"
Write-Host ""
Write-Host "Deploy: copy .env next to DG House.exe (see .env.example)"
