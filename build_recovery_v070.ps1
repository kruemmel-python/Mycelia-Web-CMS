$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Mycelia MCMS2 Recovery Runtime: v0.7.0 MinGW ===" -ForegroundColor Cyan
Write-Host "Dieser Build ersetzt KEINE produktive DLL." -ForegroundColor Yellow

$root = Join-Path $PSScriptRoot "recovery_legacy\v070_sdk"
$source = Join-Path $root "src\mycelia_core.c"
$noise = Join-Path $root "src\CipherCore_NoiseCtrl.c"
$include = Join-Path $root "include"
$srcInclude = Join-Path $root "src"
$cl = Join-Path $root "CL"
$outDir = Join-Path $PSScriptRoot "recovery_runtimes\v070_mingw"
$outDll = Join-Path $outDir "CC_OpenCl.dll"
$outLib = Join-Path $outDir "libCC_OpenCl.a"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

foreach ($required in @($source, $noise, (Join-Path $cl "libOpenCL.dll.a"))) {
  if (!(Test-Path $required)) { throw "Recovery-Quelle fehlt: $required" }
}

$candidates = @()
$cmd = Get-Command g++.exe -ErrorAction SilentlyContinue
if ($cmd) { $candidates += $cmd.Source }
$candidates += @(
  "C:\msys64\ucrt64\bin\g++.exe",
  "C:\msys64\mingw64\bin\g++.exe",
  "C:\msys64\clang64\bin\g++.exe"
)
$gpp = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $gpp) {
  throw "g++.exe fehlt. Für die historische v0.7.0-Runtime wird der ursprüngliche MinGW/MSYS2-Buildweg benötigt."
}
Write-Host "Historischer Compilerpfad: $gpp" -ForegroundColor Cyan

$args = @(
  "-std=c++17",
  "-O3",
  "-march=native",
  "-ffast-math",
  "-funroll-loops",
  "-fstrict-aliasing",
  "-DNDEBUG",
  "-DCL_TARGET_OPENCL_VERSION=120",
  "-DCL_FAST_OPTS",
  "-DMYCELIA_EXPORTS",
  "-shared",
  $source,
  $noise,
  "-o", $outDll,
  "-I$include",
  "-I$srcInclude",
  "-I$root",
  "-I$cl",
  "-L$cl",
  "-lOpenCL",
  "-Wl,--out-implib,$outLib",
  "-static-libstdc++",
  "-static-libgcc"
)

& $gpp @args
if ($LASTEXITCODE -ne 0 -or !(Test-Path $outDll)) {
  throw "Historische v0.7.0-Recovery-Runtime konnte nicht gebaut werden."
}

$hash = (Get-FileHash $outDll -Algorithm SHA256).Hash
Write-Host "Recovery-Runtime gebaut:" -ForegroundColor Green
Write-Host "  $outDll"
Write-Host "  SHA256: $hash"
Write-Host "Produktive vendor\CC_OpenCl.dll wurde NICHT verändert." -ForegroundColor Green
