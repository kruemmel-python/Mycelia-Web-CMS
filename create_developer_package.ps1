param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "dist")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$packageName = "Mycelia-WebCMS_v0_8_0-developer"
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
$zipPath = Join-Path $outputRoot ($packageName + ".zip")
$hashPath = $zipPath + ".sha256"
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$tempBase = Join-Path ([IO.Path]::GetTempPath()) ("mycelia-dev-package-" + [guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $tempBase $packageName
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$rootFiles = @(
    ".env.example",
    ".gitignore",
    "LICENSE",
    "README.md",
    "DEVELOPER_README.md",
    "RELEASE_NOTES_v0.8.0.md",
    "ERROR_HANDLING_HARDENING.md",
    "MCMS3_RECOVERY_MIGRATION.md",
    "requirements.txt",
    "requirements-dev.txt",
    "run.py",
    "install.ps1",
    "start.ps1",
    "build_security_sdk.ps1",
    "build_native_db.ps1",
    "build_recovery_v070.ps1",
    "recover_mcms2.ps1",
    "repair_crypto_runtime.ps1",
    "create_developer_package.ps1"
)

function Test-DeveloperFile([string]$RelativePath) {
    $rel = $RelativePath.Replace('\', '/')

    if ($rel -match '(^|/)(__pycache__|\.pytest_cache|build_vs2022|bin|obj)(/|$)') { return $false }
    if ($rel -match '\.(pyc|pyo|tmp)$') { return $false }

    # Security SDK lib/ is generated. OpenCL libraries under CL/ remain part
    # of the source/build dependency set.
    if ($rel -like 'third_party/Mycelia-Security-SDK_v2_secure/lib/*') { return $false }

    # Developer documentation is Markdown. PDFs and screenshots in docs/ are
    # local content examples and are not required to compile the product.
    if ($rel -like 'docs/*' -and [IO.Path]::GetExtension($rel) -ne '.md') { return $false }
    if ($rel -like 'docs/CodeDump_*.md') { return $false }

    return $true
}

try {
    foreach ($name in $rootFiles) {
        $source = Join-Path $projectRoot $name
        if (!(Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Erforderliche Entwicklerdatei fehlt: $name"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $stageRoot $name)
    }

    foreach ($directory in @('cms', 'static', 'templates', 'tests', 'tools', 'third_party', 'recovery_legacy', 'docs')) {
        $sourceDir = Join-Path $projectRoot $directory
        if (!(Test-Path -LiteralPath $sourceDir -PathType Container)) {
            throw "Erforderliches Quellverzeichnis fehlt: $directory"
        }
        Get-ChildItem -LiteralPath $sourceDir -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($projectRoot.Length + 1)
            if (!(Test-DeveloperFile $relative)) { return }
            $destination = Join-Path $stageRoot $relative
            $destinationDir = Split-Path -Parent $destination
            New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination
        }
    }

    $requiredPackageFiles = @(
        'install.ps1',
        '.env.example',
        'cms/app.py',
        'third_party/Mycelia-Security-SDK_v2_secure/src/mycelia_core.c',
        'third_party/MyceliaDB_Enterprise_Studio_v0_2_secure/CMakeLists.txt',
        'third_party/prebuilt/CC_OpenCl.dll',
        'third_party/prebuilt/mycelia_gpu_envelope.dll'
    )
    foreach ($required in $requiredPackageFiles) {
        if (!(Test-Path -LiteralPath (Join-Path $stageRoot $required) -PathType Leaf)) {
            throw "Paketprüfung fehlgeschlagen, Datei fehlt: $required"
        }
    }

    $forbidden = Get-ChildItem -LiteralPath $stageRoot -Recurse -Force | Where-Object {
        $_.Name -eq '.env' -or
        $_.Name -eq '.venv' -or
        $_.Name -eq 'CMakeCache.txt' -or
        $_.FullName -match '[\\/](data|runtime|vendor|dist|build_vs2022|__pycache__|\.pytest_cache)([\\/]|$)'
    }
    if ($forbidden) {
        throw "Paketprüfung fand verbotene Laufzeitdatei: $($forbidden[0].FullName)"
    }

    $manifestLines = Get-ChildItem -LiteralPath $stageRoot -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($stageRoot.Length + 1).Replace('\', '/')
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $relative"
        }
    $manifestLines | Set-Content -LiteralPath (Join-Path $stageRoot 'PACKAGE_MANIFEST_SHA256.txt') -Encoding UTF8

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    [IO.Compression.ZipFile]::CreateFromDirectory($tempBase, $zipPath, [IO.Compression.CompressionLevel]::Optimal, $false)

    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$zipHash  $([IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $hashPath -Encoding ASCII

    $entryCount = ([IO.Compression.ZipFile]::OpenRead($zipPath)).Entries.Count
    Write-Host "Developer-Paket erstellt:" -ForegroundColor Green
    Write-Host "  $zipPath"
    Write-Host "  Dateien: $entryCount"
    Write-Host "  SHA256: $zipHash"
    Write-Host "  Pruefsumme: $hashPath"
}
finally {
    if (Test-Path -LiteralPath $tempBase) {
        Remove-Item -LiteralPath $tempBase -Recurse -Force
    }
}
