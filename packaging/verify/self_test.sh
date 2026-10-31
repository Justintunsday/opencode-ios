#!/usr/bin/env bash
# OpenCode iOS port — scripts self-test (CI bring-up ONLY, never a package).
#
# Builds synthetic placeholder inputs on the runner so the packaging and
# validation scripts can be exercised end-to-end before the real upstream
# build artifacts exist:
#   * a tiny iPhoneOS arm64 Mach-O executable (compiled from C with the
#     iPhoneOS SDK) standing in for the Node runtime / ripgrep,
#   * a synthetic "opencode.mjs" that answers --version/--help,
#   * entitlements/manifest/SHA256SUMS fixtures,
#   * negative tests for the packaging error paths.
#
# The resulting .deb is clearly marked as a self-test placeholder by
# scripts/package-ios.sh --self-test and is NEVER uploaded as
# OpenCode-iOS-rootless. Workflows must treat a self-test run as non-production.
#
# Usage: packaging/verify/self_test.sh [--work-dir DIR]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-python3}"

WORK_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --work-dir) WORK_DIR="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "self_test: unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "$WORK_DIR" ] || WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opencode-self-test.XXXXXX")"
mkdir -p "$WORK_DIR"

die() { echo "self_test: error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

command -v xcrun >/dev/null 2>&1 || die "xcrun is required (run on the macOS CI runner)"
SDK_PATH="$(xcrun --sdk iphoneos --show-sdk-path 2>/dev/null)" \
    || die "iPhoneOS SDK not available (is Xcode installed on this runner?)"
info "iPhoneOS SDK: $SDK_PATH"

# ---------------------------------------------------------- tiny iOS Mach-O
cat > "$WORK_DIR/tiny.c" <<'EOF'
int main(void) { return 0; }
EOF
info "compiling synthetic iPhoneOS arm64 Mach-O placeholders"
xcrun --sdk iphoneos clang -target arm64-apple-ios15.0 -isysroot "$SDK_PATH" \
    -O0 -o "$WORK_DIR/node" "$WORK_DIR/tiny.c"
cp "$WORK_DIR/node" "$WORK_DIR/rg"

# ------------------------------------------------------------- fixtures ----
python3_fixture() {
    "$PYTHON" "$ROOT/packaging/verify/port_verify.py" fixture \
        --out-dir "$WORK_DIR" --node "$WORK_DIR/node"
}
python3_fixture
for required in \
    "$WORK_DIR/artifacts/runtime/node" \
    "$WORK_DIR/artifacts/runtime/entitlements.plist" \
    "$WORK_DIR/artifacts/runtime/runtime-manifest.json" \
    "$WORK_DIR/artifacts/runtime/SHA256SUMS" \
    "$WORK_DIR/artifacts/opencode/opencode.mjs" \
    "$WORK_DIR/artifacts/opencode/assets/self-test-placeholder.bin" \
    "$WORK_DIR/artifacts/opencode/bundle-manifest.json" \
    "$WORK_DIR/artifacts/opencode/SHA256SUMS" \
    "$WORK_DIR/artifacts/ripgrep/rg" \
    "$WORK_DIR/artifacts/ripgrep/SHA256SUMS"; do
    [ -f "$required" ] || die "fixture missing $required"
done
info "fixtures created under $WORK_DIR/artifacts"

# ---------------------------------------------------- negative error paths -
EMPTY="$WORK_DIR/empty-artifacts"
mkdir -p "$EMPTY/runtime" "$EMPTY/opencode"
NEG_LOG="$WORK_DIR/negative.log"

expect_failure_with_message() {
    local description="$1" expected="$2"
    shift 2
    if "$@" >"$NEG_LOG" 2>&1; then
        die "negative test '$description' unexpectedly succeeded"
    fi
    if ! grep -Fq "$expected" "$NEG_LOG"; then
        echo "--- negative test output ---" >&2
        cat "$NEG_LOG" >&2
        die "negative test '$description' failed without the expected message: $expected"
    fi
    info "negative test PASS: $description"
}

expect_failure_with_message \
    "package-ios rejects an artifact without the runtime node binary" \
    "no 'node' binary" \
    bash "$ROOT/scripts/package-ios.sh" \
        --runtime-dir "$EMPTY/runtime" \
        --opencode-dir "$WORK_DIR/artifacts/opencode" \
        --out-dir "$WORK_DIR/negative-out"

expect_failure_with_message \
    "package-ios rejects an artifact without opencode.mjs" \
    "no opencode.mjs" \
    bash "$ROOT/scripts/package-ios.sh" \
        --runtime-dir "$WORK_DIR/artifacts/runtime" \
        --opencode-dir "$EMPTY/opencode" \
        --out-dir "$WORK_DIR/negative-out"

# A >32-byte non-Mach-O file: check_macho must reject it as not Mach-O.
printf 'this is definitely not a Mach-O executable, just some text padding %s\n' \
    '0123456789012345678901234567890123456789' > "$WORK_DIR/not-a-macho.txt"
expect_failure_with_message \
    "check_macho rejects a non-Mach-O file" \
    "Not a thin little-endian arm64 Mach-O executable" \
    "$PYTHON" "$ROOT/scripts/check_macho.py" "$WORK_DIR/not-a-macho.txt" --max-minos 16.1.1

info "scripts self-test fixtures and negative tests PASSED"
info "self-test work dir: $WORK_DIR"
echo "SELF_TEST_FIXTURES_OK"
