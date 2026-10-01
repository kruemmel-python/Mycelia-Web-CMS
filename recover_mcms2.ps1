param(
  [switch]$Migrate,
  [switch]$SkipLegacyBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (!(Test-Path ".env")) { throw ".env fehlt." }
if (!(Test-Path ".venv\Scripts\python.exe")) { throw ".venv fehlt. Zuerst .\install.ps1 ausführen." }
if (!(Test-Path "runtime\myceliadb-server.exe")) { throw "MyceliaDB Runtime fehlt. Zuerst .\install.ps1 ausführen." }

Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], 'Process')
  }
}

if (-not $SkipLegacyBuild) {
  $legacyCandidate = Join-Path $PSScriptRoot "recovery_runtimes\v070_mingw\CC_OpenCl.dll"
  if (!(Test-Path $legacyCandidate)) {
    Write-Host "Baue historischen v0.7.0-Recovery-Kandidaten..." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\build_recovery_v070.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Recovery-Runtime-Build fehlgeschlagen." }
  }
}

if ($Migrate) {
  Write-Host "" 
  Write-Host "ACHTUNG: Migration schreibt nur dann MCMS3, wenn ALLE Legacy-Datensätze erfolgreich gelesen werden." -ForegroundColor Yellow
  Write-Host "Vor dem ersten Schreibzugriff wird automatisch ein historisches Backup erstellt." -ForegroundColor Yellow
  $confirm = Read-Host "Zum Fortfahren exakt MIGRATE eingeben"
  if ($confirm -ne "MIGRATE") {
    Write-Host "Migration abgebrochen. Keine Daten verändert." -ForegroundColor Yellow
    exit 1
  }
}

$tokenBytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
$env:MYCELIA_DB_AUTH_TOKEN = -join ($tokenBytes | ForEach-Object { $_.ToString("x2") })
$backupRoot = (Resolve-Path "data\backups").Path
$env:MYCELIA_DB_STORAGE_ROOT = $backupRoot

$dbHost = if ($env:MYCELIA_DB_HOST) { $env:MYCELIA_DB_HOST } else { "127.0.0.1" }
$dbPort = if ($env:MYCELIA_DB_PORT) { [int]$env:MYCELIA_DB_PORT } else { 4555 }

function Test-Port([string]$HostName, [int]$Port) {
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    if (!$iar.AsyncWaitHandle.WaitOne(250)) { $client.Close(); return $false }
    $client.EndConnect($iar); $client.Close(); return $true
  } catch { return $false }
}

function Test-MyceliaReady([string]$HostName, [int]$Port, [string]$Token) {
  $client = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    if (!$iar.AsyncWaitHandle.WaitOne(500)) { return $false }
    $client.EndConnect($iar)
    $client.ReceiveTimeout = 1500
    $client.SendTimeout = 1500
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
    $writer = New-Object System.IO.StreamWriter($stream, (New-Object System.Text.UTF8Encoding($false)), 4096, $true)
    $writer.NewLine = "`n"
    $writer.AutoFlush = $true
    if ($reader.ReadLine() -ne "MYCELIADB ENTERPRISE SECURE AUTH_REQUIRED") { return $false }
    $writer.WriteLine("AUTH $Token")
    if ($reader.ReadLine() -ne "OK AUTH") { return $false }
    $writer.WriteLine("PING")
    return ($reader.ReadLine() -like "*snapshot=V2 manual_nodes=1 erase_node=1*")
  } catch { return $false } finally { if ($client) { $client.Close() } }
}

if (Test-Port $dbHost $dbPort) {
  throw "Port $dbPort ist bereits belegt. CMS/DB zuerst mit Ctrl+C beenden. Recovery verbindet sich nie mit einer fremden Instanz."
}

$dbExe = Join-Path $PSScriptRoot "runtime\myceliadb-server.exe"
$dbProcess = $null
try {
  Write-Host "Starte isolierte MyceliaDB für Recovery..." -ForegroundColor Cyan
  $dbProcess = Start-Process -FilePath $dbExe -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Minimized
  $ready = $false
  for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 250
    if ($dbProcess.HasExited) { throw "MyceliaDB wurde beendet. Exit-Code: $($dbProcess.ExitCode)" }
    if (Test-MyceliaReady $dbHost $dbPort $env:MYCELIA_DB_AUTH_TOKEN) { $ready = $true; break }
  }
  if (!$ready) { throw "MyceliaDB wurde für Recovery nicht bereit." }

  $args = @("tools\recover_mcms2.py")
  if ($Migrate) { $args += "--migrate" }
  & ".\.venv\Scripts\python.exe" @args
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    Write-Host "Recovery beendet mit Exit-Code $code. Siehe data\recovery\ für den Report." -ForegroundColor Yellow
    exit $code
  }
} finally {
  if ($dbProcess -and !$dbProcess.HasExited) { Stop-Process -Id $dbProcess.Id -Force }
}
