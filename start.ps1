param(
  [string]$Project = ".",
  [int]$Port = 7741
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Quick-TakeApart quick start" -ForegroundColor Cyan

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "Node.js is required (for pyright and the web build)."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python is required."
}

if (-not (Test-Path "node_modules\pyright\langserver.index.js")) {
  Write-Host "Installing indexer dependencies..."
  npm ci --omit=dev
}

python -c "import anthropic" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing Python dependencies..."
  python -m pip install -r requirements.txt
}

if (-not (Test-Path "web\node_modules")) {
  Write-Host "Installing frontend dependencies..."
  npm --prefix web ci
}

Write-Host "Building frontend..."
npm --prefix web run build

Write-Host "Starting http://127.0.0.1:$Port/ for $Project"
python serve.py $Project --host 127.0.0.1 --port $Port
