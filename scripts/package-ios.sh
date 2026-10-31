#!/usr/bin/env bash
# OpenCode iOS port — assemble the rootless iphoneos-arm64 .deb.
#
# Inputs are the artifacts of the upstream build workflows (never rebuilt here):
#   --runtime-dir   contents of the `ios-node-runtime` artifact
#                   (node, entitlements.plist, runtime-manifest.json, SHA256SUMS)
#   --opencode-dir  contents of the `opencode-cli-node-ios` artifact
#                   (opencode.mjs, assets/**, bundle-manifest.json, SHA256SUMS)
#   --ripgrep-dir   optional contents of the `ios-ripgrep` stretch artifact
#
# Output (in --out-dir, default dist/):
#   OpenCode-iOS-rootless.deb   rootless package for /var/jb
#   SHA256SUMS                  sha256 of the .deb
#   package-sources.json        provenance (runs, artifact hashes, upstream pins)
#   contents-manifest.json      path/mode/size/sha256 of the staged tree
#   deb-info.txt / deb-contents.txt (dpkg-deb output, not uploaded)
#
# scripts/validate-port.sh consumes contents-manifest.json + package-sources.json
# in --mode package to produce the final package-report.json.
#
# Examples:
#   scripts/package-ios.sh --runtime-dir .artifacts/runtime \
#       --opencode-dir .artifacts/opencode --out-dir dist
#   scripts/package-ios.sh ... --no-build   # stage only (local dry-run)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3}"

die() { echo "package-ios: error: $*" >&2; exit 1; }
warn() { echo "package-ios: warning: $*" >&2; }
info() { echo "==> $*"; }

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

RUNTIME_DIR=""
OPENCODE_DIR=""
RIPGREP_DIR=""
OUT_DIR="$ROOT/dist"
VERSION_ARG=""
MAINTAINER="OpenCode iOS port maintainers <opencode-ios-port@users.noreply.github.com>"
RUNTIME_RUN_ID=""
RUNTIME_RUN_URL=""
OPENCODE_RUN_ID=""
OPENCODE_RUN_URL=""
RIPGREP_RUN_ID=""
RIPGREP_RUN_URL=""
RUN_URL=""
COMMIT=""
SELF_TEST=0
NO_BUILD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --runtime-dir) RUNTIME_DIR="${2:-}"; shift 2 ;;
        --opencode-dir) OPENCODE_DIR="${2:-}"; shift 2 ;;
        --ripgrep-dir) RIPGREP_DIR="${2:-}"; shift 2 ;;
        --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
        --version) VERSION_ARG="${2:-}"; shift 2 ;;
        --maintainer) MAINTAINER="${2:-}"; shift 2 ;;
        --runtime-run-id) RUNTIME_RUN_ID="${2:-}"; shift 2 ;;
        --runtime-run-url) RUNTIME_RUN_URL="${2:-}"; shift 2 ;;
        --opencode-run-id) OPENCODE_RUN_ID="${2:-}"; shift 2 ;;
        --opencode-run-url) OPENCODE_RUN_URL="${2:-}"; shift 2 ;;
        --ripgrep-run-id) RIPGREP_RUN_ID="${2:-}"; shift 2 ;;
        --ripgrep-run-url) RIPGREP_RUN_URL="${2:-}"; shift 2 ;;
        --run-url) RUN_URL="${2:-}"; shift 2 ;;
        --commit) COMMIT="${2:-}"; shift 2 ;;
        --self-test) SELF_TEST=1; shift ;;
        --no-build) NO_BUILD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$RUNTIME_DIR" ] || die "--runtime-dir is required (contents of the ios-node-runtime artifact)"
[ -n "$OPENCODE_DIR" ] || die "--opencode-dir is required (contents of the opencode-cli-node-ios artifact)"
[ -d "$RUNTIME_DIR" ] || die "--runtime-dir not found: $RUNTIME_DIR"
[ -d "$OPENCODE_DIR" ] || die "--opencode-dir not found: $OPENCODE_DIR"
[ -n "$COMMIT" ] || COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"

command -v "$PYTHON" >/dev/null 2>&1 || die "python3 is required (set PYTHON=...)"
[ -f "$ROOT/scripts/check_macho.py" ] || die "missing $ROOT/scripts/check_macho.py"
[ -f "$ROOT/packaging/rootless/control.in" ] || die "missing packaging/rootless/control.in"

# ------------------------------------------------------------------ helpers
sha256_of() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        "$PYTHON" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

find_first_file() {
    local dir="$1" name="$2" hit=""
    if [ -f "$dir/$name" ]; then
        printf '%s\n' "$dir/$name"
        return 0
    fi
    hit="$(find "$dir" -type f -name "$name" ! -path '*/.git/*' 2>/dev/null | head -n 1 || true)"
    if [ -n "$hit" ]; then
        printf '%s\n' "$hit"
    fi
    return 0
}

find_first_dir() {
    local dir="$1" name="$2" hit=""
    if [ -d "$dir/$name" ]; then
        printf '%s\n' "$dir/$name"
        return 0
    fi
    hit="$(find "$dir" -type d -name "$name" ! -path '*/.git/*' 2>/dev/null | head -n 1 || true)"
    if [ -n "$hit" ]; then
        printf '%s\n' "$hit"
    fi
    return 0
}

verify_artifact_sums() {
    local dir="$1" label="$2" sums="" base="" line="" expected="" file="" actual=""
    sums="$(find "$dir" -type f -name SHA256SUMS ! -path '*/.git/*' 2>/dev/null | head -n 1 || true)"
    if [ -z "$sums" ]; then
        warn "$label: no SHA256SUMS in artifact (recorded as absent in provenance)"
        return 0
    fi
    base="$(dirname "$sums")"
    while IFS= read -r line; do
        line="$(printf '%s' "$line" | tr -d '\r')"
        [ -n "$line" ] || continue
        case "$line" in \#*) continue ;; esac
        expected="${line%% *}"
        file="${line#* }"
        file="${file# }"
        file="${file#\*}"
        file="${file#./}"
        [ -f "$base/$file" ] || die "$label: SHA256SUMS references missing file: $file"
        actual="$(sha256_of "$base/$file")"
        if [ "$expected" != "$actual" ]; then
            die "$label: SHA256SUMS mismatch for $file (expected $expected, got $actual)"
        fi
    done < "$sums"
    info "$label: artifact SHA256SUMS verified ($sums)"
}

# --------------------------------------------------- locate artifact inputs
info "runtime artifact: $RUNTIME_DIR"
NODE_SRC="$(find_first_file "$RUNTIME_DIR" node)"
[ -n "$NODE_SRC" ] || die "ios-node-runtime artifact has no 'node' binary (expected: node, entitlements.plist, runtime-manifest.json, SHA256SUMS). Refusing to fabricate one."
ENTITLEMENTS_SRC="$(find_first_file "$RUNTIME_DIR" entitlements.xml)"
if [ -z "$ENTITLEMENTS_SRC" ]; then
    ENTITLEMENTS_SRC="$(find_first_file "$RUNTIME_DIR" entitlements.plist)"
fi
if [ -z "$ENTITLEMENTS_SRC" ]; then
    ENTITLEMENTS_SRC="$(find "$RUNTIME_DIR" -type f -iname '*entitlement*' ! -path '*/.git/*' 2>/dev/null | head -n 1 || true)"
fi
[ -n "$ENTITLEMENTS_SRC" ] || die "ios-node-runtime artifact has no entitlements plist (expected entitlements.plist)"
RUNTIME_MANIFEST_SRC="$(find_first_file "$RUNTIME_DIR" runtime-manifest.json)"
[ -n "$RUNTIME_MANIFEST_SRC" ] || die "ios-node-runtime artifact has no runtime-manifest.json"

info "opencode artifact: $OPENCODE_DIR"
OPENCODE_MJS_SRC="$(find_first_file "$OPENCODE_DIR" opencode.mjs)"
[ -n "$OPENCODE_MJS_SRC" ] || die "opencode-cli-node-ios artifact has no opencode.mjs (expected: opencode.mjs, assets/**, bundle-manifest.json, SHA256SUMS). Refusing to fabricate one."
MJS_DIR="$(dirname "$OPENCODE_MJS_SRC")"
if [ -d "$MJS_DIR/assets" ]; then
    ASSETS_SRC="$MJS_DIR/assets"
else
    ASSETS_SRC="$(find_first_dir "$OPENCODE_DIR" assets)"
fi
[ -n "$ASSETS_SRC" ] || die "opencode-cli-node-ios artifact has no assets/ directory"
BUNDLE_MANIFEST_SRC=""
if [ -f "$MJS_DIR/bundle-manifest.json" ]; then
    BUNDLE_MANIFEST_SRC="$MJS_DIR/bundle-manifest.json"
else
    BUNDLE_MANIFEST_SRC="$(find_first_file "$OPENCODE_DIR" bundle-manifest.json)"
fi

RG_SRC=""
if [ -n "$RIPGREP_DIR" ]; then
    [ -d "$RIPGREP_DIR" ] || die "--ripgrep-dir not found: $RIPGREP_DIR"
    RG_SRC="$(find_first_file "$RIPGREP_DIR" rg)"
    if [ -z "$RG_SRC" ]; then
        warn "ios-ripgrep artifact has no 'rg' binary; optional ripgrep component skipped"
        RIPGREP_DIR=""
        RIPGREP_RUN_ID=""
        RIPGREP_RUN_URL=""
    fi
fi

verify_artifact_sums "$RUNTIME_DIR" "ios-node-runtime"
verify_artifact_sums "$OPENCODE_DIR" "opencode-cli-node-ios"
if [ -n "$RIPGREP_DIR" ]; then
    verify_artifact_sums "$RIPGREP_DIR" "ios-ripgrep"
fi

# ------------------------------------------------------------- preflight ---
info "preflight: Mach-O audit of the runtime"
"$PYTHON" "$ROOT/scripts/check_macho.py" "$NODE_SRC" --max-minos 16.1.1

NODE_SIZE="$(wc -c < "$NODE_SRC" | tr -d ' ')"
MJS_SIZE="$(wc -c < "$OPENCODE_MJS_SRC" | tr -d ' ')"
if [ "$SELF_TEST" = "0" ]; then
    [ "$NODE_SIZE" -ge 1000000 ] || die "runtime node is only $NODE_SIZE bytes; expected a real Node.js binary (placeholder?)"
    [ "$MJS_SIZE" -ge 50000 ] || die "opencode.mjs is only $MJS_SIZE bytes; expected the Vite node bundle (placeholder?)"
fi
if [ -n "$RG_SRC" ]; then
    info "preflight: Mach-O audit of the optional ripgrep"
    "$PYTHON" "$ROOT/scripts/check_macho.py" "$RG_SRC" --max-minos 16.1.1
fi

# ------------------------------------------------------------------ stage ---
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/opencode-ios-stage.XXXXXX")"
KEEP_STAGE=0
cleanup() {
    if [ "$KEEP_STAGE" = "1" ]; then
        echo "package-ios: staged tree kept at $STAGE" >&2
    else
        rm -rf "$STAGE"
    fi
}
trap cleanup EXIT INT TERM

mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/var/jb/usr/bin" \
         "$STAGE/var/jb/usr/lib/opencode/runtime" \
         "$STAGE/var/jb/usr/lib/opencode/cli/assets" \
         "$STAGE/var/jb/usr/share/doc/opencode"

info "staging rootless tree"
cp "$ROOT/packaging/rootless/usr/bin/opencode" "$STAGE/var/jb/usr/bin/opencode"
chmod 0755 "$STAGE/var/jb/usr/bin/opencode"

cp "$NODE_SRC" "$STAGE/var/jb/usr/lib/opencode/runtime/node"
chmod 0755 "$STAGE/var/jb/usr/lib/opencode/runtime/node"
cp "$ENTITLEMENTS_SRC" "$STAGE/var/jb/usr/lib/opencode/runtime/entitlements.xml"
chmod 0644 "$STAGE/var/jb/usr/lib/opencode/runtime/entitlements.xml"
cp "$RUNTIME_MANIFEST_SRC" "$STAGE/var/jb/usr/lib/opencode/runtime/runtime-manifest.json"
chmod 0644 "$STAGE/var/jb/usr/lib/opencode/runtime/runtime-manifest.json"

cp "$OPENCODE_MJS_SRC" "$STAGE/var/jb/usr/lib/opencode/cli/opencode.mjs"
chmod 0644 "$STAGE/var/jb/usr/lib/opencode/cli/opencode.mjs"
cp -R "$ASSETS_SRC"/. "$STAGE/var/jb/usr/lib/opencode/cli/assets/"
find "$STAGE/var/jb/usr/lib/opencode/cli/assets" -type d -exec chmod 0755 {} \;
find "$STAGE/var/jb/usr/lib/opencode/cli/assets" -type f -exec chmod 0644 {} \;
if [ -n "$BUNDLE_MANIFEST_SRC" ]; then
    cp "$BUNDLE_MANIFEST_SRC" "$STAGE/var/jb/usr/lib/opencode/cli/bundle-manifest.json"
    chmod 0644 "$STAGE/var/jb/usr/lib/opencode/cli/bundle-manifest.json"
else
    warn "opencode-cli-node-ios artifact has no bundle-manifest.json; provenance recorded without it"
fi
if [ -n "$RG_SRC" ]; then
    cp "$RG_SRC" "$STAGE/var/jb/usr/bin/rg"
    chmod 0755 "$STAGE/var/jb/usr/bin/rg"
fi

for maintenance in postinst prerm postrm; do
    cp "$ROOT/packaging/rootless/$maintenance" "$STAGE/DEBIAN/$maintenance"
    chmod 0755 "$STAGE/DEBIAN/$maintenance"
done

# Packaged documentation (Debian policy: /usr/share/doc/<pkg>).
copy_doc() {
    local src="$1" dest="$2" mode="$3"
    [ -f "$src" ] || die "missing packaged doc source: $src"
    cp "$src" "$dest"
    chmod "$mode" "$dest"
}
copy_doc "$ROOT/README.md" "$STAGE/var/jb/usr/share/doc/opencode/README.md" 0644
copy_doc "$ROOT/LICENSE" "$STAGE/var/jb/usr/share/doc/opencode/LICENSE" 0644
copy_doc "$ROOT/packaging/rootless/usr/share/doc/opencode/copyright" \
    "$STAGE/var/jb/usr/share/doc/opencode/copyright" 0644
copy_doc "$ROOT/docs/VERIFICATION.md" "$STAGE/var/jb/usr/share/doc/opencode/VERIFICATION.md" 0644
copy_doc "$ROOT/docs/INSTALL.md" "$STAGE/var/jb/usr/share/doc/opencode/INSTALL.md" 0644
if [ -f "$ROOT/docs/KNOWN_LIMITATIONS.md" ]; then
    copy_doc "$ROOT/docs/KNOWN_LIMITATIONS.md" \
        "$STAGE/var/jb/usr/share/doc/opencode/KNOWN_LIMITATIONS.md" 0644
fi
copy_doc "$ROOT/packaging/rootless/usr/share/doc/opencode/device-smoke.sh" \
    "$STAGE/var/jb/usr/share/doc/opencode/device-smoke.sh" 0755

# --------------------------------------------------------------- control ---
LOCK_VERSION="$(awk -F= '$1 == "OPENCODE_VERSION" { print $2; exit }' "$ROOT/UPSTREAM.lock" 2>/dev/null || true)"
if [ -n "$VERSION_ARG" ]; then
    VERSION="$VERSION_ARG"
elif [ -n "$LOCK_VERSION" ]; then
    VERSION="${LOCK_VERSION}-1"
else
    die "cannot determine package version: UPSTREAM.lock has no OPENCODE_VERSION and --version was not given"
fi
case "$VERSION" in
    [0-9]*.[0-9]*.[0-9]*-[0-9]*) : ;;
    *) die "invalid package version '$VERSION' (expected e.g. 2.2.5-1 from UPSTREAM.lock)" ;;
esac

TOTAL_KB="$(du -sk "$STAGE" | awk '{print $1}')"
DEBIAN_KB="$(du -sk "$STAGE/DEBIAN" | awk '{print $1}')"
INSTALLED_SIZE=$((TOTAL_KB - DEBIAN_KB))
[ "$INSTALLED_SIZE" -ge 1 ] || INSTALLED_SIZE=1

sed -e "s|@VERSION@|$VERSION|g" \
    -e "s|@MAINTAINER@|$MAINTAINER|g" \
    -e "s|@INSTALLED_SIZE@|$INSTALLED_SIZE|g" \
    "$ROOT/packaging/rootless/control.in" > "$STAGE/DEBIAN/control"
chmod 0644 "$STAGE/DEBIAN/control"
if grep -q '@[A-Z_]*@' "$STAGE/DEBIAN/control"; then
    die "unsubstituted placeholder remains in DEBIAN/control"
fi
info "control: Package=opencode Version=$VERSION Architecture=iphoneos-arm64 Installed-Size=$INSTALLED_SIZE"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/SHA256SUMS" "$OUT_DIR/package-sources.json" \
      "$OUT_DIR/contents-manifest.json" "$OUT_DIR/package-report.json"

info "writing contents manifest"
"$PYTHON" "$ROOT/packaging/verify/port_verify.py" manifest \
    --root "$STAGE" \
    --out "$OUT_DIR/contents-manifest.json" \
    --label "OpenCode-iOS-rootless staged tree"

if [ "$NO_BUILD" = "1" ]; then
    KEEP_STAGE=1
    info "--no-build: staged tree only (no .deb produced)"
    exit 0
fi

# ------------------------------------------------------------------- build --
command -v dpkg-deb >/dev/null 2>&1 \
    || die "dpkg-deb not found; install dpkg (macOS: brew install dpkg; Debian/Ubuntu: apt-get install dpkg)"
DEB_PATH="$OUT_DIR/OpenCode-iOS-rootless.deb"
info "building $DEB_PATH"
dpkg-deb -Zxz --root-owner-group --build "$STAGE" "$DEB_PATH"
[ -f "$DEB_PATH" ] || die "dpkg-deb did not produce $DEB_PATH"
dpkg-deb --info "$DEB_PATH" > "$OUT_DIR/deb-info.txt"
dpkg-deb --contents "$DEB_PATH" > "$OUT_DIR/deb-contents.txt"

DEB_SHA="$(sha256_of "$DEB_PATH")"
printf '%s  %s\n' "$DEB_SHA" "OpenCode-iOS-rootless.deb" > "$OUT_DIR/SHA256SUMS"
DEB_SIZE="$(wc -c < "$DEB_PATH" | tr -d ' ')"
info "deb: $DEB_PATH ($DEB_SIZE bytes, sha256 $DEB_SHA)"

info "writing provenance"
set -- "$PYTHON" "$ROOT/packaging/verify/port_verify.py" sources \
    --lock "$ROOT/UPSTREAM.lock" \
    --out "$OUT_DIR/package-sources.json" \
    --repository "${GITHUB_REPOSITORY:-Justintunsday/opencode-ios}" \
    --commit "$COMMIT" \
    --run-id "${GITHUB_RUN_ID:-}" \
    --run-url "$RUN_URL" \
    --runtime-dir "$RUNTIME_DIR" \
    --runtime-run-id "$RUNTIME_RUN_ID" \
    --runtime-run-url "$RUNTIME_RUN_URL" \
    --opencode-dir "$OPENCODE_DIR" \
    --opencode-run-id "$OPENCODE_RUN_ID" \
    --opencode-run-url "$OPENCODE_RUN_URL"
if [ -n "$RIPGREP_DIR" ]; then
    set -- "$@" --ripgrep-dir "$RIPGREP_DIR" \
        --ripgrep-run-id "$RIPGREP_RUN_ID" \
        --ripgrep-run-url "$RIPGREP_RUN_URL"
fi
if [ "$SELF_TEST" = "1" ]; then
    set -- "$@" --self-test
fi
"$@"

info "package assembled: $DEB_PATH"
echo "  SHA256SUMS: $OUT_DIR/SHA256SUMS"
echo "  sources:    $OUT_DIR/package-sources.json"
echo "  manifest:   $OUT_DIR/contents-manifest.json"
