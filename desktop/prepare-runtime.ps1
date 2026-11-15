# Assemble the runtime that the Tauri bundle ships with.
#
#   desktop/src-tauri/runtime/
#     server/            serve.py + engine/ + web/dist + node_modules/pyright
#     node/node.exe      portable Node, needed for pyright's language server
#     python/            CPython (with tkinter) + site-packages holding `anthropic`
#
# Everything is copied from this machine: nodejs.org / python.org are not
# reachable here, while npm and PyPI are.
#
[CmdletBinding()]
param(
    [string]$PythonSource = "C:\Users\lilex\AppData\Local\Programs\Python\Python313",
    [string]$NodeExe = "",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repo = Split-Path -Parent $here
$runtime = Join-Path (Join-Path $here "src-tauri") "runtime"
$server = Join-Path $runtime "server"

function Step([string]$text) { Write-Host "`n=== $text" -ForegroundColor Cyan }

function Copy-Tree([string]$src, [string]$dst, [string[]]$excludeDir = @(), [string[]]$excludeFile = @()) {
    $roboArgs = @($src, $dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($excludeDir.Count) { $roboArgs += "/XD"; $roboArgs += $excludeDir }
    if ($excludeFile.Count) { $roboArgs += "/XF"; $roboArgs += $excludeFile }
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE): $src -> $dst" }
}

# ---------------------------------------------------------------- frontend
if (-not $SkipFrontend) {
    Step "Building frontend (web/dist)"
    Push-Location (Join-Path $repo "web")
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "web build failed ($LASTEXITCODE)" }
    } finally { Pop-Location }
}

$dist = Join-Path (Join-Path $repo "web") "dist"
if (-not (Test-Path -LiteralPath (Join-Path $dist "index.html"))) {
    throw "web/dist/index.html missing - frontend build did not produce output"
}

# ---------------------------------------------------------------- reset
Step "Reset runtime"
if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
New-Item -ItemType Directory -Force -Path $server, (Join-Path $runtime "node"), (Join-Path $runtime "python") | Out-Null

# ---------------------------------------------------------------- server
Step "Server sources"
Copy-Item -LiteralPath (Join-Path $repo "serve.py") -Destination $server
Copy-Tree (Join-Path $repo "engine") (Join-Path $server "engine") @("__pycache__") @("*.pyc")
New-Item -ItemType Directory -Force -Path (Join-Path $server "web") | Out-Null
Copy-Tree $dist (Join-Path $server "web\dist")

Step "pyright language server"
$pyrightSrc = Join-Path (Join-Path $repo "node_modules") "pyright"
if (-not (Test-Path -LiteralPath (Join-Path $pyrightSrc "langserver.index.js"))) {
    throw "node_modules/pyright/langserver.index.js missing - run npm install in the repo root"
}
Copy-Tree $pyrightSrc (Join-Path $server "node_modules\pyright") @(".bin")

# ---------------------------------------------------------------- node
Step "Node runtime"
if (-not $NodeExe) {
    $NodeExe = (Get-Command node -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $NodeExe)) { throw "node.exe not found at $NodeExe" }
Copy-Item -LiteralPath $NodeExe -Destination (Join-Path $runtime "node\node.exe")

# ---------------------------------------------------------------- python
Step "CPython runtime"
$pyDst = Join-Path $runtime "python"
foreach ($file in "python.exe", "pythonw.exe", "python313.dll", "vcruntime140.dll", "vcruntime140_1.dll") {
    $src = Join-Path $PythonSource $file
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $pyDst }
}
Copy-Tree (Join-Path $PythonSource "DLLs") (Join-Path $pyDst "DLLs") @("__pycache__") @("*.pyc")
Copy-Tree (Join-Path $PythonSource "Lib") (Join-Path $pyDst "Lib") `
    @("site-packages", "test", "idlelib", "turtledemo", "lib2to3", "ensurepip", "tkinter\tests") @("*.pyc")
if (Test-Path -LiteralPath (Join-Path $PythonSource "tcl")) {
    Copy-Tree (Join-Path $PythonSource "tcl") (Join-Path $pyDst "tcl") @("demos", "tzdata")
}
New-Item -ItemType Directory -Force -Path (Join-Path $pyDst "Lib\site-packages") | Out-Null

Step "Python dependencies (anthropic)"
& (Join-Path $PythonSource "python.exe") -m pip install --quiet --disable-pip-version-check `
    --only-binary=:all: --target (Join-Path $pyDst "Lib\site-packages") anthropic
if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }

# ---------------------------------------------------------------- verify
Step "Verify"
& (Join-Path $pyDst "python.exe") -c "import anthropic, tkinter, ssl, asyncio; print('python ok', anthropic.__version__, tkinter.TkVersion)"
if ($LASTEXITCODE -ne 0) { throw "bundled python cannot import anthropic/tkinter" }

& (Join-Path $runtime "node\node.exe") --version
if ($LASTEXITCODE -ne 0) { throw "bundled node.exe does not run" }

foreach ($required in "server\serve.py", "server\web\dist\index.html", "server\node_modules\pyright\langserver.index.js") {
    if (-not (Test-Path -LiteralPath (Join-Path $runtime $required))) { throw "missing $required" }
}

$size = (Get-ChildItem -LiteralPath $runtime -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("`nruntime ready: {0} ({1:N1} MB)" -f $runtime, $size) -ForegroundColor Green

