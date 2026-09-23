[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$mvpRoot = Join-Path $projectRoot 'mvp'
$venvPython = Join-Path $mvpRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
$server = Join-Path $mvpRoot 'server.py'

if (-not (Test-Path -LiteralPath $server)) {
    throw "Không tìm thấy server: $server"
}

try {
    Write-Host 'Dev đang chạy. Nhấn Ctrl+C để ngưng và dọn tiến trình.'
    Push-Location $mvpRoot
    & $python $server
}
finally {
    Pop-Location -ErrorAction SilentlyContinue
    & (Join-Path $projectRoot 'stop.ps1')
}
