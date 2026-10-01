$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Mycelia WebCMS v0.8.0 Identity & Inventory Hardened Installer ===" -ForegroundColor Green

if (!(Get-Command py -ErrorAction SilentlyContinue)) {
  throw "Python Launcher fehlt. Python 3.12 x64 installieren."
}
py -3.12 -c "import struct,sys; assert sys.version_info[:2] == (3,12), sys.version; assert struct.calcsize('P') == 8, 'Python muss x64 sein'"

$required = @(
  "third_party\Mycelia-Security-SDK_v2_secure\src\mycelia_core.c",
  "third_party\Mycelia-Security-SDK_v2_secure\include\mycelia.h",
  "third_party\prebuilt\mycelia_gpu_envelope.dll",
  "third_party\MyceliaDB_Enterprise_Studio_v0_2_secure\src\server\MyceliaEngine.cpp"
)
foreach ($file in $required) {
  if (!(Test-Path $file)) { throw "Sicherheitsrelevante Datei fehlt: $file" }
}

if (!(Test-Path ".\build_security_sdk.ps1")) { throw "Installationspaket unvollstaendig: build_security_sdk.ps1 fehlt." }
if (!(Test-Path ".\build_native_db.ps1")) { throw "Installationspaket unvollstaendig: build_native_db.ps1 fehlt." }

# Build the security core from the shipped Mycelia Security SDK source.
# New installations fail closed if the 256-bit ABI cannot be built/verified.
& powershell -ExecutionPolicy Bypass -File .\build_security_sdk.ps1
if ($LASTEXITCODE -ne 0) { throw "Mycelia Security SDK v2 konnte nicht gebaut werden." }

# Build the database core from the audited source shipped with this CMS.
& powershell -ExecutionPolicy Bypass -File .\build_native_db.ps1
if ($LASTEXITCODE -ne 0) { throw "Native MyceliaDB V2 konnte nicht gebaut werden." }

if (!(Test-Path ".venv\Scripts\python.exe")) { py -3.12 -m venv .venv }
$oldPipConfigFile = $env:PIP_CONFIG_FILE
try {
  $env:PIP_CONFIG_FILE = "NUL"
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt
}
finally {
  if ($null -eq $oldPipConfigFile) { Remove-Item Env:PIP_CONFIG_FILE -ErrorAction SilentlyContinue }
  else { $env:PIP_CONFIG_FILE = $oldPipConfigFile }
}

if (!(Test-Path ".env")) {
  .\.venv\Scripts\python.exe tools\setup.py
} else {
  $hashLine = Get-Content .env | Where-Object { $_ -like 'MYCELIA_CMS_ADMIN_PASSWORD_HASH=*' } | Select-Object -First 1
  if (-not $hashLine -or $hashLine -notmatch '^MYCELIA_CMS_ADMIN_PASSWORD_HASH=\$argon2id\$') {
    Write-Host "Bestehende Konfiguration wird auf Argon2id gehärtet." -ForegroundColor Yellow
    .\.venv\Scripts\python.exe tools\setup.py --force-password
  }
}

New-Item -ItemType Directory -Force -Path "data\backups" | Out-Null
New-Item -ItemType Directory -Force -Path "data\audit" | Out-Null

# Restrict local secrets and backups to the current account, SYSTEM and local Administrators.
# If ACL hardening cannot be applied, installation fails instead of silently weakening security.
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls ".env" /inheritance:r | Out-Null
& icacls ".env" /grant:r "${currentUser}:F" "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ACL-Härtung fehlgeschlagen: .env" }

& icacls "data" /inheritance:r | Out-Null
& icacls "data" /grant:r "${currentUser}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ACL-Härtung fehlgeschlagen: data" }

Write-Host ""
Write-Host "Installation abgeschlossen. Sicherheitsmodus: FAIL-CLOSED." -ForegroundColor Green
Write-Host "Start: .\start.ps1"
Write-Host "CMS:   http://127.0.0.1:8088/cms"
