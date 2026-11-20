#!/usr/bin/env bash
# Assemble the macOS runtime that the Tauri bundle ships with.
# Mirrors prepare-runtime.ps1, which does the same job on Windows:
#
#   desktop/src-tauri/runtime/
#     server/            serve.py + engine/ + web/dist + node_modules/pyright
#     node/node          copied from the local node installation
#     python/            python-build-standalone CPython + site-packages/anthropic
#
# Usage:  bash prepare-runtime.mac.sh [--skip-frontend]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$REPO/desktop/src-tauri/runtime"
SERVER="$RUNTIME/server"
SKIP_FRONTEND=0
[[ "${1:-}" == "--skip-frontend" ]] && SKIP_FRONTEND=1

step() { printf '\n=== %s\n' "$1"; }
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

PY_VERSION="${QTA_PYTHON_VERSION:-3.13}"

# ---------------------------------------------------------------- frontend
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
    step "Building frontend (web/dist)"
    if [[ ! -d "$REPO/web/node_modules" ]]; then
        ( cd "$REPO/web" && npm install )
    fi
    ( cd "$REPO/web" && npm run build )
fi
[[ -f "$REPO/web/dist/index.html" ]] || fail "web/dist/index.html missing - frontend build produced nothing"

# ---------------------------------------------------------------- reset
step "Reset runtime"
rm -rf "$RUNTIME"
mkdir -p "$SERVER" "$RUNTIME/node" "$RUNTIME/python"

# ---------------------------------------------------------------- server sources
step "Server sources"
cp "$REPO/serve.py" "$SERVER/serve.py"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$REPO/engine" "$SERVER/"
mkdir -p "$SERVER/web"
rsync -a "$REPO/web/dist" "$SERVER/web/"

step "pyright language server"
[[ -f "$REPO/node_modules/pyright/langserver.index.js" ]] \
    || fail "node_modules/pyright/langserver.index.js missing - run 'npm install' in the repo root"
mkdir -p "$SERVER/node_modules"
rsync -a --exclude '.bin' "$REPO/node_modules/pyright" "$SERVER/node_modules/"

# ---------------------------------------------------------------- node
step "Node runtime"
NODE_BIN="$(command -v node || true)"
[[ -n "$NODE_BIN" ]] || fail "node not found on PATH - install Node 20+ first"
cp "$(readlink -f "$NODE_BIN" 2>/dev/null || echo "$NODE_BIN")" "$RUNTIME/node/node"
chmod +x "$RUNTIME/node/node"

# ---------------------------------------------------------------- python
step "CPython runtime (python-build-standalone)"
ARCH="$(uname -m)"
# python-build-standalone names Apple Silicon aarch64, not arm64.
case "$ARCH" in
    arm64)  PY_ARCH="aarch64" ;;
    x86_64) PY_ARCH="x86_64" ;;
    *)      PY_ARCH="$ARCH" ;;
esac
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Resolve the newest standalone build for this arch/major.minor instead of pinning a URL
# that would rot: the release assets are named cpython-<ver>+<date>-<arch>-apple-darwin-*.tar.gz.
curl -fsSL --retry 3 --connect-timeout 20 -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" \
    -o "$TMP/rel.json"

PY_URL="$(python3 - "$TMP/rel.json" "$PY_VERSION" "$PY_ARCH" <<'PY'
import json, sys
path, version, arch = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(path, encoding="utf-8"))
for asset in data.get("assets", []):
    name = asset["name"]
    if not name.startswith(f"cpython-{version}"):
        continue
    if f"-{arch}-apple-darwin-install_only" not in name:
        continue
    if not name.endswith(".tar.gz"):
        continue
    print(asset["browser_download_url"])
    break
PY
)"
[[ -n "$PY_URL" ]] || fail "no python-build-standalone asset for $PY_VERSION / $PY_ARCH"

echo "  $PY_URL"
curl -fsSL --retry 3 --connect-timeout 20 "$PY_URL" -o "$TMP/python.tar.gz"
tar -xzf "$TMP/python.tar.gz" -C "$TMP"
[[ -d "$TMP/python" ]] || fail "unexpected archive layout: no python/ directory"
mv "$TMP/python"/* "$RUNTIME/python/"

PY="$RUNTIME/python/bin/python3"
[[ -x "$PY" ]] || fail "bundled interpreter missing at $PY"

step "Python dependencies (anthropic)"
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade >/dev/null
"$PY" -m pip install --quiet --disable-pip-version-check --target "$SITE" anthropic

# ---------------------------------------------------------------- verify
step "Verify"
"$PY" -c "import anthropic, ssl, asyncio; print('python ok', anthropic.__version__)"
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "  WARNING: bundled python has no tkinter - the in-app folder picker will report"
    echo "           '系统文件夹选择器不可用'; typing a path or dragging a folder still works."
fi
"$RUNTIME/node/node" --version

for required in "server/serve.py" "server/web/dist/index.html" "server/node_modules/pyright/langserver.index.js"; do
    [[ -f "$RUNTIME/$required" ]] || fail "missing $required"
done

SIZE="$(du -sh "$RUNTIME" | awk '{print $1}')"
printf '\nruntime ready: %s (%s)\n' "$RUNTIME" "$SIZE"
