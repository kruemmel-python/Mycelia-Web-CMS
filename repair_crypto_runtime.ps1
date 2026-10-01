$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$prebuilt = Join-Path $PSScriptRoot "third_party\prebuilt\CC_OpenCl.dll"
$vendor   = Join-Path $PSScriptRoot "vendor\CC_OpenCl.dll"
$expected = "dbea496fbd00e3a950927767e772c4aeb0ae651173936804b8c4d6ee3f404967"

if (!(Test-Path $prebuilt)) { throw "Pinned Security-Runtime fehlt: $prebuilt" }
$actual = (Get-FileHash -Algorithm SHA256 $prebuilt).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "Falsche pinned Security-Runtime. Erwartet $expected, gefunden $actual"
}

New-Item -ItemType Directory -Force -Path (Split-Path $vendor) | Out-Null
Copy-Item $prebuilt $vendor -Force
$installed = (Get-FileHash -Algorithm SHA256 $vendor).Hash.ToLowerInvariant()
if ($installed -ne $expected) { throw "Runtime-Reparatur fehlgeschlagen: SHA256 stimmt nach Kopieren nicht." }

Write-Host "Mycelia Crypto-Runtime wurde auf die persistenzkompatible Version zurueckgesetzt." -ForegroundColor Green
Write-Host "SHA256: $installed" -ForegroundColor Green
Write-Host "Jetzt .\start.ps1 ausfuehren." -ForegroundColor Cyan
