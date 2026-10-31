#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/opencode-ios-smoke"
if [[ ! -f "$APP" ]]; then echo 'Run scripts/build-ios-smoke.sh first' >&2; exit 1; fi
command -v dpkg-deb >/dev/null || { echo 'dpkg-deb missing' >&2; exit 1; }
python3 "$ROOT/scripts/check_macho.py" "$APP" --max-minos 16.1.1
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/DEBIAN" "$STAGE/var/jb/usr/bin" "$ROOT/dist"
cp "$APP" "$STAGE/var/jb/usr/bin/opencode-ios-smoke"
chmod 0755 "$STAGE/var/jb/usr/bin/opencode-ios-smoke"
cat > "$STAGE/DEBIAN/control" <<'CTRL'
Package: dev.opencode.ios.toolchain-probe
Name: OpenCode iOS toolchain probe (NOT OpenCode)
Version: 0.0.1
Architecture: iphoneos-arm64
Maintainer: OpenCode iOS porting research
Section: Utilities
Description: Probe for iPhoneOS ARM64 toolchain and rootless installation; this is NOT OpenCode CLI.
CTRL
dpkg-deb --build --root-owner-group "$STAGE" "$ROOT/dist/opencode-ios-toolchain-probe_0.0.1_iphoneos-arm64.deb"
shasum -a 256 "$ROOT/dist/opencode-ios-toolchain-probe_0.0.1_iphoneos-arm64.deb" > "$ROOT/dist/SHA256SUMS"
