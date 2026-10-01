$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Baue Mycelia Security SDK v2 mit Visual Studio (MSVC)..." -ForegroundColor Cyan

$root       = Join-Path $PSScriptRoot "third_party\Mycelia-Security-SDK_v2_secure"
$sourceCore = Join-Path $root "src\mycelia_core.c"
$sourceNoise= Join-Path $root "src\CipherCore_NoiseCtrl.c"
$includeDir = Join-Path $root "include"
$srcDir     = Join-Path $root "src"
$clDir      = Join-Path $root "CL"
$openclLib  = Join-Path $clDir "OpenCL.lib"
$objDir     = Join-Path $root "obj"
$binDir     = Join-Path $root "bin"
$libDir     = Join-Path $root "lib"
$outDll     = Join-Path $binDir "CC_OpenCl.dll"
$outLib     = Join-Path $libDir "CC_OpenCl.lib"
$vendorDll  = Join-Path $PSScriptRoot "vendor\CC_OpenCl.dll"
$prebuiltDll= Join-Path $PSScriptRoot "third_party\prebuilt\CC_OpenCl.dll"
$expectedPrebuiltSha256 = "dbea496fbd00e3a950927767e772c4aeb0ae651173936804b8c4d6ee3f404967"

$required = @(
    $sourceCore,
    $sourceNoise,
    (Join-Path $includeDir "mycelia.h"),
    $openclLib
)
foreach ($file in $required) {
    if (!(Test-Path $file)) { throw "Security-SDK Build-Datei fehlt: $file" }
}

New-Item -ItemType Directory -Force -Path $objDir, $binDir, $libDir, (Split-Path $vendorDll), (Split-Path $prebuiltDll) | Out-Null

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-Path $vswhere)) { throw "vswhere.exe wurde nicht gefunden. Visual Studio 2022 mit Desktopentwicklung C++ installieren." }

$vsPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (-not $vsPath) { throw "Visual Studio 2022 mit Desktopentwicklung C++ wurde nicht gefunden." }

$vsDevCmd = Join-Path $vsPath "Common7\Tools\VsDevCmd.bat"
if (!(Test-Path $vsDevCmd)) { throw "VsDevCmd.bat wurde nicht gefunden: $vsDevCmd" }

# Import the VS x64 build environment into this PowerShell process.
$envLines = & cmd.exe /d /s /c "`"$vsDevCmd`" -no_logo -arch=x64 -host_arch=x64 >nul && set"
if ($LASTEXITCODE -ne 0) { throw "Visual-Studio-Buildumgebung konnte nicht initialisiert werden." }
foreach ($line in $envLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}

$cl = (Get-Command cl.exe -ErrorAction Stop).Source
$link = (Get-Command link.exe -ErrorAction Stop).Source
Write-Host "Compiler: $cl"

$coreObj  = Join-Path $objDir "mycelia_core.obj"
$noiseObj = Join-Path $objDir "CipherCore_NoiseCtrl.obj"
$nonce = "{0}_{1}" -f $PID, ([DateTime]::UtcNow.Ticks)
$tmpDll = Join-Path $binDir "CC_OpenCl.$nonce.tmp.dll"
$tmpLib = Join-Path $libDir "CC_OpenCl.$nonce.tmp.lib"
$tmpExp = [System.IO.Path]::ChangeExtension($tmpLib, ".exp")

$common = @(
    "/nologo",
    "/c",
    "/TP",
    "/O2",
    "/EHsc",
    "/MD",
    "/DNDEBUG",
    "/DCL_TARGET_OPENCL_VERSION=120",
    "/DCL_FAST_OPTS",
    "/DMYCELIA_EXPORTS",
    "/I$includeDir",
    "/I$srcDir",
    "/I$root",
    "/I$clDir"
)

Write-Host "Kompiliere C/C++ Quellen..." -ForegroundColor DarkCyan
& $cl @common "/Fo$coreObj" $sourceCore
if ($LASTEXITCODE -ne 0 -or !(Test-Path $coreObj)) { throw "Kompilierung von mycelia_core.c fehlgeschlagen." }

& $cl @common "/Fo$noiseObj" $sourceNoise
if ($LASTEXITCODE -ne 0 -or !(Test-Path $noiseObj)) { throw "Kompilierung von CipherCore_NoiseCtrl.c fehlgeschlagen." }

Write-Host "Linke $outDll..." -ForegroundColor DarkCyan
& $link "/nologo" "/DLL" "/OUT:$tmpDll" "/IMPLIB:$tmpLib" $coreObj $noiseObj $openclLib
if ($LASTEXITCODE -ne 0 -or !(Test-Path $tmpDll)) { throw "Linken des Mycelia Security SDK v2 fehlgeschlagen." }

# Verify the freshly built DLL before it replaces any runtime copy.
$verify = @'
import ctypes, pathlib, sys
p = pathlib.Path(sys.argv[1]).resolve()
lib = ctypes.WinDLL(str(p))
try:
    f = lib.myc_get_security_capabilities
except AttributeError as exc:
    raise SystemExit("256-Bit-Key-ABI fehlt") from exc
f.restype = ctypes.c_char_p
caps = (f() or b"").decode("ascii", "replace")
if "key256=1" not in caps or "hmac_sha256_stream=1" not in caps:
    raise SystemExit("Security Capability fehlt: " + caps)
print(caps)
'@
$verifyPath = Join-Path $env:TEMP "mycelia_verify_security_sdk_$PID.py"
Set-Content -Path $verifyPath -Value $verify -Encoding UTF8
& py -3.12 $verifyPath $tmpDll
if ($LASTEXITCODE -ne 0) {
    Remove-Item $verifyPath -Force -ErrorAction SilentlyContinue
    throw "Security SDK ABI-Verifikation fehlgeschlagen."
}

# Replace final artifacts only after compile, link and ABI verification succeeded.
Move-Item $tmpDll $outDll -Force
Move-Item $tmpLib $outLib -Force
if (Test-Path $tmpExp) {
    Move-Item $tmpExp (Join-Path $libDir "CC_OpenCl.exp") -Force
}
# IMPORTANT PERSISTENCE CONTRACT:
# `third_party\prebuilt\CC_OpenCl.dll` is the immutable crypto-compatibility
# runtime for persisted MCMS1/MCMS2 records.  Recompiling the same C/C++ source
# with another compiler/toolchain can change the GPU-derived byte stream and
# therefore must NEVER silently replace the runtime that encrypted existing
# data.  The freshly built DLL above is retained in `bin` for source/ABI
# verification only.  Production uses the pinned, shipped compatibility DLL.
if (!(Test-Path $prebuiltDll)) {
    throw "Pinned Security-Runtime fehlt: $prebuiltDll"
}

# Verify the pinned runtime separately before installing it.
& py -3.12 $verifyPath $prebuiltDll
if ($LASTEXITCODE -ne 0) {
    Remove-Item $verifyPath -Force -ErrorAction SilentlyContinue
    throw "Pinned Security-Runtime ist nicht ABI-kompatibel."
}
Remove-Item $verifyPath -Force -ErrorAction SilentlyContinue

$prebuiltHash = (Get-FileHash -Algorithm SHA256 $prebuiltDll).Hash.ToLowerInvariant()
if ($prebuiltHash -ne $expectedPrebuiltSha256) {
    throw "Pinned Security-Runtime hat einen unerwarteten SHA256-Wert. Persistenzschutz verweigert Installation."
}

# A running CMS has this DLL loaded and Windows then prevents replacing it.
# Re-installation is still safe when the already installed file is byte-for-
# byte the pinned persistence runtime. Only copy when it is missing/different;
# a different locked runtime must continue to fail closed.
$vendorAlreadyPinned = $false
if (Test-Path $vendorDll) {
    $vendorHash = (Get-FileHash -Algorithm SHA256 $vendorDll).Hash.ToLowerInvariant()
    $vendorAlreadyPinned = $vendorHash -eq $prebuiltHash
}
if ($vendorAlreadyPinned) {
    Write-Host "Produktive Persistenz-Runtime bereits korrekt installiert; Kopieren uebersprungen." -ForegroundColor DarkGreen
} else {
    Copy-Item $prebuiltDll $vendorDll -Force
    $installedHash = (Get-FileHash -Algorithm SHA256 $vendorDll).Hash.ToLowerInvariant()
    if ($installedHash -ne $prebuiltHash) {
        throw "Installierte Security-Runtime stimmt nicht mit der gepinnten Runtime ueberein."
    }
}
Write-Host "Security SDK Build/ABI-Pruefung erfolgreich." -ForegroundColor Green
Write-Host "Persistenz-Runtime gepinnt: $prebuiltHash" -ForegroundColor Green
Write-Host "Produktiv installiert: $vendorDll" -ForegroundColor Green
