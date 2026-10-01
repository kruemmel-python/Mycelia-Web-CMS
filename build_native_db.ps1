$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$sourceDir = Join-Path $PSScriptRoot "third_party\MyceliaDB_Enterprise_Studio_v0_2_secure"
# Keep generated files outside the deeply nested source tree. Apart from
# separating source/build cleanly, this avoids MSVC/CMake failures caused by
# Windows path-length limits after extracting the developer ZIP.
$buildDir  = Join-Path $PSScriptRoot "build\myceliadb-vs2022"
$runtimeDir = Join-Path $PSScriptRoot "runtime"
$targetExe = Join-Path $runtimeDir "myceliadb-server.exe"

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = $null
if (Test-Path $vswhere) {
    $vsPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
}
if (-not $vsPath) { throw "Visual Studio 2022 mit Desktopentwicklung C++ wurde nicht gefunden." }

$cmake = Join-Path $vsPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if (!(Test-Path $cmake)) {
    $cmd = Get-Command cmake -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "CMake wurde nicht gefunden." }
    $cmake = $cmd.Source
}

Write-Host "Baue MyceliaDB Secure Snapshot V2 mit VS2022..." -ForegroundColor Cyan
# CMake caches absolute source/build paths. The project is commonly copied or
# upgraded from an older Mycelia-WebCMS directory, so a shipped/copied cache
# must never be reused. --fresh removes only CMake's generated cache data in
# this dedicated build directory and preserves all source files.
& $cmake --fresh -S $sourceDir -B $buildDir -G "Visual Studio 17 2022" -A x64
if ($LASTEXITCODE -ne 0) { throw "CMake-Konfiguration fehlgeschlagen." }
& $cmake --build $buildDir --config Release --target myceliadb-server
if ($LASTEXITCODE -ne 0) { throw "MyceliaDB-Build fehlgeschlagen." }

$candidates = @(
    (Join-Path $buildDir "bin\Release\myceliadb-server.exe"),
    (Join-Path $buildDir "bin\myceliadb-server.exe")
)
$builtExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $builtExe) { throw "Gebautes myceliadb-server.exe wurde nicht gefunden." }

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$runtimeCurrent = $false
if (Test-Path $targetExe) {
    $builtHash = (Get-FileHash -Algorithm SHA256 $builtExe).Hash
    $targetHash = (Get-FileHash -Algorithm SHA256 $targetExe).Hash
    $runtimeCurrent = $builtHash -eq $targetHash
}
if ($runtimeCurrent) {
    Write-Host "MyceliaDB Runtime bereits aktuell; Kopieren uebersprungen." -ForegroundColor DarkGreen
} else {
    Copy-Item $builtExe $targetExe -Force
}
Set-Content -Path (Join-Path $runtimeDir ".snapshot-v3-secure") -Value "MyceliaDB V3 CMS persistence + ERASE_NODE / VS2022"
Write-Host "MyceliaDB V2 Runtime installiert: $targetExe" -ForegroundColor Green
