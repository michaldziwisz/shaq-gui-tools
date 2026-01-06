$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install --upgrade pyinstaller wxPython
.\.venv\Scripts\python -m pip install -e .

if (-not (Test-Path "vendor/ffmpeg/ffmpeg.exe") -or -not (Test-Path "vendor/ffmpeg/ffprobe.exe")) {
  .\.venv\Scripts\python fetch_ffmpeg_windows.py
}

.\.venv\Scripts\python -m PyInstaller --noconfirm --clean shaqfilegui.spec
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "OK: dist\\shaqfilegui.exe"
