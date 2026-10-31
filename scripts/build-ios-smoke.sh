#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/dist"
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
xcrun --sdk iphoneos clang \
  -arch arm64 -target arm64-apple-ios16.0 -isysroot "$SDK" \
  -O2 -Wall -Wextra -Werror \
  "$ROOT/src/ios_smoke.c" -o "$ROOT/dist/opencode-ios-smoke"
python3 "$ROOT/scripts/check_macho.py" "$ROOT/dist/opencode-ios-smoke" --max-minos 16.1.1
xcrun otool -L "$ROOT/dist/opencode-ios-smoke"
if command -v ldid >/dev/null 2>&1; then
  ldid -S "$ROOT/dist/opencode-ios-smoke"
else
  echo 'Warning: ldid unavailable; ad-hoc signing with codesign (device test still required)'
  codesign -f -s - "$ROOT/dist/opencode-ios-smoke"
fi
python3 "$ROOT/scripts/check_macho.py" "$ROOT/dist/opencode-ios-smoke" --max-minos 16.1.1
