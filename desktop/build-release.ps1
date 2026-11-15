# Build the Windows release: portable folder + NSIS installer + portable zip.
#
# `tauri build` on its own would also work, but its bundled NSIS downloader
# times out on this network, so the installer is compiled here with a locally
# cached makensis instead. The portable folder layout is identical to what the
# installer produces, so both are just "exe + runtime/".
#
[CmdletBinding()]
param(
    [switch]$SkipRuntime,
    [switch]$SkipFrontend,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $here "src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
$version = $config.version
$dist = Join-Path $here "dist"
$appDir = Join-Path $dist "Quick-TakeApart"
$exeName = "Quick-TakeApart.exe"

function Step([string]$text) { Write-Host "`n=== $text" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 1. runtime
if (-not $SkipRuntime) {
    Step "Prepare runtime"
    $runtimeArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $here "prepare-runtime.ps1"))
    if ($SkipFrontend) { $runtimeArgs += "-SkipFrontend" }
    & powershell @runtimeArgs
    if ($LASTEXITCODE -ne 0) { throw "prepare-runtime.ps1 failed ($LASTEXITCODE)" }
}
if (-not (Test-Path -LiteralPath (Join-Path $here "src-tauri\runtime\server\serve.py"))) {
    throw "src-tauri/runtime is missing - run prepare-runtime.ps1 first (or drop -SkipRuntime)"
}

# ---------------------------------------------------------------- 2. exe
Step "Build release binary"
Push-Location $here
try {
    npx tauri build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "tauri build --no-bundle failed ($LASTEXITCODE)" }
} finally { Pop-Location }
$builtExe = Join-Path $here "src-tauri\target\release\quick-takeapart.exe"
if (-not (Test-Path -LiteralPath $builtExe)) { throw "release binary missing: $builtExe" }

# ---------------------------------------------------------------- 3. portable folder
Step "Assemble portable folder"
if (Test-Path -LiteralPath $appDir) { Remove-Item -LiteralPath $appDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Copy-Item -LiteralPath $builtExe -Destination (Join-Path $appDir $exeName)

$runtimeSrc = Join-Path $here "src-tauri\runtime"
$runtimeDst = Join-Path $appDir "runtime"
& robocopy $runtimeSrc $runtimeDst /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) copying runtime" }

# ---------------------------------------------------------------- 4. installer
Step "Compile NSIS installer"
$nsisHome = Join-Path $here ".tools\nsis"
$makensis = Join-Path $nsisHome "Bin\makensis.exe"
if (-not (Test-Path -LiteralPath $makensis)) {
    $zip = Join-Path $nsisHome "nsis.zip"
    New-Item -ItemType Directory -Force -Path $nsisHome | Out-Null
    Write-Host "fetching NSIS 3.13 into $nsisHome"
    curl.exe -L --ssl-no-revoke --retry 3 --connect-timeout 20 --max-time 600 -o $zip `
        "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.13/nsis-3.13.zip"
    if ($LASTEXITCODE -ne 0) {
        throw "cannot download NSIS. Put makensis.exe at $makensis (or drop nsis-3.13.zip next to this script) and re-run."
    }
    Expand-Archive -LiteralPath $zip -DestinationPath $nsisHome -Force
    $inner = Get-ChildItem -LiteralPath $nsisHome -Directory -Filter "nsis-3.13" | Select-Object -First 1
    if ($inner) {
        Get-ChildItem -LiteralPath $inner.FullName -Force | Move-Item -Destination $nsisHome -Force
        Remove-Item -LiteralPath $inner.FullName -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $makensis)) { throw "makensis.exe not found after extracting NSIS" }
}

& $makensis "/V2" "/DVERSION=$version" (Join-Path $here "installer.nsi")
if ($LASTEXITCODE -ne 0) { throw "makensis failed ($LASTEXITCODE)" }

# ---------------------------------------------------------------- 5. portable zip
if (-not $SkipZip) {
    Step "Zip portable build"
    $zipOut = Join-Path $dist ("Quick-TakeApart_{0}_x64-portable.zip" -f $version)
    if (Test-Path -LiteralPath $zipOut) { Remove-Item -LiteralPath $zipOut -Force }
    & tar.exe -a -c -f $zipOut -C $appDir "."
    if ($LASTEXITCODE -ne 0) {
        Write-Host "tar failed, falling back to Compress-Archive"
        Compress-Archive -Path (Join-Path $appDir "*") -DestinationPath $zipOut -CompressionLevel Optimal
    }
}

# ---------------------------------------------------------------- report
Step "Release artifacts"
Get-ChildItem -LiteralPath $dist -File | Where-Object { $_.Name -like "*.exe" -or $_.Name -like "*.zip" } |
    ForEach-Object { "{0,-52} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB) }
$folder = (Get-ChildItem -LiteralPath $appDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
"portable folder (Quick-TakeApart/)                    {0,8:N1} MB" -f $folder
