#!/usr/bin/env bash
# Build the macOS release: .app (ad-hoc signed) + .dmg + .zip.
#
# Windows uses build-release.ps1 + a locally cached makensis because Tauri's own
# NSIS download times out. On macOS the bundler only needs hdiutil for the dmg,
# but an unsigned .app is killed by Gatekeeper on Apple Silicon, so the bundle is
# assembled from a signed --bundles app build and the dmg is made here.
#
# Usage:  bash build-release.mac.sh [--skip-runtime] [--skip-frontend]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$REPO/desktop"
DIST="$DESKTOP/dist"
SKIP_RUNTIME=0
RUNTIME_ARGS=""

for arg in "$@"; do
    case "$arg" in
        --skip-runtime) SKIP_RUNTIME=1 ;;
        --skip-frontend) RUNTIME_ARGS="--skip-frontend" ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\n=== %s\n' "$1"; }
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' \
    "$DESKTOP/src-tauri/tauri.conf.json")"
ARCH="$(uname -m)"

# ---------------------------------------------------------------- 1. runtime
if [[ "$SKIP_RUNTIME" -eq 0 ]]; then
    step "Prepare runtime"
    bash "$DESKTOP/prepare-runtime.mac.sh" $RUNTIME_ARGS
fi
[[ -f "$DESKTOP/src-tauri/runtime/server/serve.py" ]] \
    || fail "src-tauri/runtime is missing - run prepare-runtime.mac.sh first (or drop --skip-runtime)"

# ---------------------------------------------------------------- 2. app bundle
step "Build .app"
if [[ ! -d "$DESKTOP/node_modules" ]]; then
    ( cd "$DESKTOP" && npm install )
fi
( cd "$DESKTOP" && npx tauri build --bundles app )

APP="$DESKTOP/src-tauri/target/release/bundle/macos/Quick-TakeApart.app"
[[ -d "$APP" ]] || fail "app bundle missing: $APP"
[[ -f "$APP/Contents/Resources/runtime/server/serve.py" ]] \
    || fail "runtime was not embedded into the app bundle (Contents/Resources/runtime)"

# ---------------------------------------------------------------- 3. ad-hoc sign
step "Ad-hoc sign"
# Gatekeeper needs at least an ad-hoc signature on arm64; a real Developer ID
# certificate can be passed through QTA_SIGN_ID instead.
SIGN_ID="${QTA_SIGN_ID:--}"
xattr -cr "$APP"
codesign --force --deep --sign "$SIGN_ID" "$APP"
codesign --verify --deep --strict "$APP" && echo "  verified with identity: $SIGN_ID"

# ---------------------------------------------------------------- 4. dmg + zip
step "Package dmg + zip"
mkdir -p "$DIST"
STAGE="$(mktemp -d)"
ditto "$APP" "$STAGE/Quick-TakeApart.app"
ln -s /Applications "$STAGE/Applications"

DMG="$DIST/Quick-TakeApart_${VERSION}_${ARCH}-macos.dmg"
ZIP="$DIST/Quick-TakeApart_${VERSION}_${ARCH}-macos.zip"
rm -f "$DMG" "$ZIP"
hdiutil create -quiet -volname "Quick-TakeApart" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
rm -rf "$STAGE"

# ---------------------------------------------------------------- report
step "Release artifacts"
for f in "$DMG" "$ZIP"; do
    printf '%-56s %8s\n' "$(basename "$f")" "$(du -h "$f" | awk '{print $1}')"
done
printf '%-56s %8s\n' "Quick-TakeApart.app" "$(du -sh "$APP" | awk '{print $1}')"
