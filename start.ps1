$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (!(Test-Path "runtime\.snapshot-v3-secure") -or !(Test-Path "runtime\myceliadb-server.exe")) {
  throw "Gehärtete MyceliaDB V2 Runtime fehlt. Zuerst .\install.ps1 ausführen."
}
if (!(Test-Path ".venv\Scripts\python.exe") -or !(Test-Path ".env")) {
  throw "Installation unvollständig. Zuerst .\install.ps1 ausführen."
}

Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], 'Process')
  }
}

# Per-start database capability token: never written to disk. Both child
# processes inherit it; unrelated local processes do not know it.
$tokenBytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
$env:MYCELIA_DB_AUTH_TOKEN = -join ($tokenBytes | ForEach-Object { $_.ToString("x2") })
$backupRoot = (Resolve-Path "data\backups").Path
$env:MYCELIA_DB_STORAGE_ROOT = $backupRoot

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
    $banner = $reader.ReadLine()
    if ($banner -ne "MYCELIADB ENTERPRISE SECURE AUTH_REQUIRED") { return $false }
    $writer.WriteLine("AUTH $Token")
    if ($reader.ReadLine() -ne "OK AUTH") { return $false }
    $writer.WriteLine("PING")
    $pong = $reader.ReadLine()
    return $pong -like "*snapshot=V2 manual_nodes=1 erase_node=1*"
  } catch {
    return $false
  } finally {
    if ($client) { $client.Close() }
  }
}

$dbExe = Join-Path $PSScriptRoot "runtime\myceliadb-server.exe"
$dbStartedHere = $false
$dbProcess = $null

if (Test-Port "127.0.0.1" 4555) {
  throw "Port 4555 ist bereits belegt. Aus Sicherheitsgründen verbindet sich das CMS nie mit einer fremden/vorher gestarteten DB-Instanz."
}

Write-Host "Starte gehärtete MyceliaDB V2..." -ForegroundColor Cyan
$dbProcess = Start-Process -FilePath $dbExe -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Minimized
$dbStartedHere = $true
$ready = $false
for ($i = 0; $i -lt 80; $i++) {
  Start-Sleep -Milliseconds 250
  if ($dbProcess.HasExited) { throw "MyceliaDB wurde beendet. Exit-Code: $($dbProcess.ExitCode)" }
  if (Test-MyceliaReady "127.0.0.1" 4555 $env:MYCELIA_DB_AUTH_TOKEN) { $ready = $true; break }
}
if (!$ready) {
  if ($dbProcess -and !$dbProcess.HasExited) { Stop-Process -Id $dbProcess.Id -Force }
  throw "MyceliaDB wurde nicht vollständig bereit (AUTH + PING + ERASE_NODE Capability)."
}

Write-Host "MyceliaDB V2 bereit: 127.0.0.1:4555" -ForegroundColor Green
Write-Host "Mycelia WebCMS: http://127.0.0.1:8088/cms" -ForegroundColor Green

try {
  .\.venv\Scripts\python.exe run.py
} finally {
  if ($dbStartedHere -and $dbProcess -and !$dbProcess.HasExited) { Stop-Process -Id $dbProcess.Id }
}
