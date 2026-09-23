[CmdletBinding()]
param()

$mvpRoot = Join-Path $PSScriptRoot 'mvp'
$port = 8000
$envFile = Join-Path $mvpRoot '.env'
if (Test-Path -LiteralPath $envFile) {
    $portLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*PORT\s*=\s*\d+\s*$' } | Select-Object -Last 1
    if ($portLine) { $port = [int](($portLine -split '=', 2)[1].Trim()) }
}

$listenerPids = @(netstat -ano -p tcp | ForEach-Object {
    if ($_ -match "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$") { [int]$Matches[1] }
} | Sort-Object -Unique)
foreach ($listenerPid in $listenerPids) {
    Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    Write-Host "Đã ngưng dev server trên cổng $port (PID $listenerPid)."
}

# Dọn đúng các judge container do CodeLit tạo nếu dev bị ngắt giữa lúc chấm.
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $containers = @(docker ps --quiet --filter 'name=^/codelit-' 2>$null)
    if ($containers.Count -gt 0) {
        docker rm --force $containers 2>$null | Out-Null
        Write-Host "Đã dọn $($containers.Count) judge container."
    }
}

Write-Host 'CodeLit đã ngưng.'
