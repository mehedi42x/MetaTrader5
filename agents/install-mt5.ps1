<#
.SYNOPSIS
  Installs MetaTrader 5 (and Python if missing) on a fresh Windows VPS, then
  prints the exact command to start the bridge agent.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-mt5.ps1 -Url https://my-app.onrender.com -Key abc123
#>
[CmdletBinding()]
param(
  [string]$Url = "",
  [string]$Key = "",
  [string]$Mt5Url = "https://download.mql5.com/cdn/web/metaquotes.ltd/mt5/mt5setup.exe",
  [switch]$SkipMt5
)
$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "[mt5-setup] $m" -ForegroundColor Cyan }

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Say "Python not found - installing Python 3.12 (x64, silent)"
  $tmp = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
  Invoke-WebRequest "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" -OutFile $tmp
  Start-Process $tmp -ArgumentList "/quiet","InstallAllUsers=1","PrependPath=1" -Wait
  Say "re-run this script so the new PATH is picked up"
  exit 0
}
Say "python: $((python --version) 2>&1)"

if (-not $SkipMt5) {
  $installed = Test-Path "C:\Program Files\MetaTrader 5\terminal64.exe"
  if ($installed) { Say "MetaTrader 5 already installed" }
  else {
    Say "downloading MetaTrader 5 installer"
    $exe = Join-Path $env:TEMP "mt5setup.exe"
    Invoke-WebRequest $Mt5Url -OutFile $exe
    Say "running silent install (MetaQuotes setup: mt5setup.exe /auto)"
    Start-Process $exe -ArgumentList "/auto" -Wait
  }
}

$repo = Split-Path -Parent $PSScriptRoot
Say "installing agent dependencies into $repo\agents\.venv"
Push-Location "$repo\agents"
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r agent\requirements.txt
Pop-Location

Say "done. start the agent with:"
Write-Host ("  cd {0}\agents ; .\.venv\Scripts\python.exe agent\main.py --url {1}/ws/agent --key {2}" -f $repo, $Url, $Key) -ForegroundColor Yellow
Say "or just double-click start-agent.bat after pasting the url + key into it"
