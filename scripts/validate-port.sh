#!/usr/bin/env bash
# OpenCode iOS port — CI-runnable validation suite for the rootless .deb.
#
# Modes
#   package   validate a freshly assembled package (dist/): contents manifest +
#             package report are produced. Run by package-rootless.yml.
#   verify    validate a downloaded OpenCode-iOS-rootless artifact (test-port.yml);
#             no build happens here. Produces verification-report.{json,md}.
#   self-test scripts self-test with synthetic placeholder inputs.
#
# What runs (macOS CI runner or dev host):
#   * safe extraction of the .deb (pure-Python reader + dpkg-deb when present)
#   * repository checks: LF endings, shell syntax, no secrets, packaging layout,
#     workflow contract, factory unit tests
#   * package metadata/layout/permissions/maintainer-script checks, idempotency
#     execution against the extracted tree, launcher contract, docs, no junk
#   * Mach-O platform/arch/minOS, dylib linkage (otool), entitlements,
#     runtime/bundle manifest hash consistency, verbatim-copy provenance
#   * host Node.js 22.9.0 (nodejs.org, checksum pinned) CLI smoke: bundle
#     --version/--help and the packaged launcher with argument forwarding
#
# It DOES NOT and CANNOT execute anything on the iPhone: device-only tests are
# listed as "UNVERIFIED ON DEVICE" in the report.
#
# Usage:
#   scripts/validate-port.sh --deb dist/OpenCode-iOS-rootless.deb [options]
#     --mode package|verify|self-test      (default: verify)
#     --variant auto|node22|node18|node26  (default: auto, inferred)
#     --out-dir DIR                        (default: verification)
#     --artifact-dir DIR                   SHA256SUMS/package-report.json dir
#     --contents-manifest FILE             (package mode)
#     --sources FILE                       (package mode package-sources.json)
#     --package-report FILE                (verify mode, downloaded report)
#     --run-id ID / --run-url URL          provenance for the report
#     --expected-version X.Y.Z-1           override UPSTREAM.lock version
#     --skip-smoke / --skip-native-audit   local dry-run only (never used in CI)
#     --work-dir DIR / --keep-work
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3}"

die() { echo "validate-port: error: $*" >&2; exit 1; }
warn() { echo "validate-port: warning: $*" >&2; }
info() { echo "==> $*"; }
usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; }

DEB=""
MODE="verify"
VARIANT="auto"
OUT_DIR="$ROOT/verification"
ARTIFACT_DIR=""
CONTENTS_MANIFEST=""
SOURCES=""
PACKAGE_REPORT=""
RUN_ID=""
RUN_URL=""
EXPECTED_VERSION=""
EXPECTED_OPENCODE_VERSION=""
SKIP_SMOKE=0
SKIP_NATIVE=0
KEEP_WORK=0
WORK_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --deb) DEB="${2:-}"; shift 2 ;;
        --mode) MODE="${2:-}"; shift 2 ;;
        --variant) VARIANT="${2:-}"; shift 2 ;;
        --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
        --artifact-dir) ARTIFACT_DIR="${2:-}"; shift 2 ;;
        --contents-manifest) CONTENTS_MANIFEST="${2:-}"; shift 2 ;;
        --sources) SOURCES="${2:-}"; shift 2 ;;
        --package-report) PACKAGE_REPORT="${2:-}"; shift 2 ;;
        --run-id) RUN_ID="${2:-}"; shift 2 ;;
        --run-url) RUN_URL="${2:-}"; shift 2 ;;
        --expected-version) EXPECTED_VERSION="${2:-}"; shift 2 ;;
        --skip-smoke) SKIP_SMOKE=1; shift ;;
        --skip-native-audit) SKIP_NATIVE=1; shift ;;
        --work-dir) WORK_DIR="${2:-}"; shift 2 ;;
        --keep-work) KEEP_WORK=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$DEB" ] || die "--deb is required"
[ -f "$DEB" ] || die "package not found: $DEB"
DEB="$(cd "$(dirname "$DEB")" && pwd)/$(basename "$DEB")"
case "$MODE" in
    package|verify|self-test) : ;;
    *) die "invalid --mode '$MODE' (expected package, verify or self-test)" ;;
esac
case "$VARIANT" in
    auto|node22|node18|node26) : ;;
    *) die "invalid --variant '$VARIANT' (expected auto, node22, node18 or node26)" ;;
esac
[ -n "$ARTIFACT_DIR" ] || ARTIFACT_DIR="$(dirname "$DEB")"
[ -d "$ARTIFACT_DIR" ] || die "artifact dir not found: $ARTIFACT_DIR"
command -v "$PYTHON" >/dev/null 2>&1 || die "python3 is required (set PYTHON=...)"

if [ -z "$EXPECTED_VERSION" ]; then
    LOCK_VERSION="$(awk -F= '$1 == "OPENCODE_VERSION" { print $2; exit }' "$ROOT/UPSTREAM.lock" 2>/dev/null || true)"
    if [ -n "$LOCK_VERSION" ]; then
        EXPECTED_VERSION="${LOCK_VERSION}-1"
        EXPECTED_OPENCODE_VERSION="$LOCK_VERSION"
    fi
fi
if [ -z "$EXPECTED_OPENCODE_VERSION" ]; then
    EXPECTED_OPENCODE_VERSION="$(awk -F= '$1 == "OPENCODE_VERSION" { print $2; exit }' "$ROOT/UPSTREAM.lock" 2>/dev/null || true)"
fi

# In verify mode, automatically cross-check the package-report.json that the
# packaging workflow shipped in the same artifact (if the caller did not pass one).
if [ -z "$PACKAGE_REPORT" ] && [ -f "$ARTIFACT_DIR/package-report.json" ] && [ "$MODE" = "verify" ]; then
    PACKAGE_REPORT="$ARTIFACT_DIR/package-report.json"
fi

WORK_DIR="${WORK_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/opencode-port-verify.$$}"
mkdir -p "$WORK_DIR"
EXTRACT_DIR="$WORK_DIR/extract"
cleanup() {
    if [ "$KEEP_WORK" = "1" ]; then
        info "work dir kept: $WORK_DIR"
    else
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT INT TERM

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/check-results.json" "$OUT_DIR/verification-report.json" \
      "$OUT_DIR/verification-report.md" "$OUT_DIR/host-smoke.json" \
      "$OUT_DIR/extract-manifest.json" "$OUT_DIR/unittest.log" \
      "$OUT_DIR/deb-info.txt" "$OUT_DIR/deb-contents.txt"
if [ "$MODE" = "package" ] || [ "$MODE" = "self-test" ]; then
    rm -f "$OUT_DIR/package-report.json"
fi

info "validate-port mode=$MODE"
info "package: $DEB ($(wc -c < "$DEB" | tr -d ' ') bytes)"
info "repository: $ROOT"
info "python: $("$PYTHON" --version 2>&1)"
info "work dir: $WORK_DIR"

# ------------------------------------------------------ dpkg-deb (if any) ---
if command -v dpkg-deb >/dev/null 2>&1; then
    info "dpkg-deb: $(dpkg-deb --version | head -n 1)"
    dpkg-deb --info "$DEB" > "$OUT_DIR/deb-info.txt"
    dpkg-deb --contents "$DEB" > "$OUT_DIR/deb-contents.txt" || warn "dpkg-deb --contents failed"
else
    warn "dpkg-deb not available; using the pure-Python reader (install dpkg for the extra metadata dump)"
fi

# --------------------------------------------------------------- extract ---
info "extracting package (safe pure-Python reader)"
rm -rf "$EXTRACT_DIR"
EXTRACT_RC=0
"$PYTHON" "$ROOT/packaging/verify/port_verify.py" extract \
    --deb "$DEB" \
    --dest "$EXTRACT_DIR" \
    --out "$OUT_DIR/extract-manifest.json" || EXTRACT_RC=$?
if [ "$EXTRACT_RC" -ne 0 ]; then
    warn "package extraction failed (rc=$EXTRACT_RC); the verification report will record this"
fi

# ------------------------------------------------------- variant inference ---
# The package variant is inferred from provenance/package-report/runtime manifest
# unless --variant was given explicitly.
infer_variant() {
    local candidate_file value
    if [ "$VARIANT" != "auto" ]; then
        printf '%s' "$VARIANT"
        return 0
    fi
    for candidate_file in "$SOURCES" "$PACKAGE_REPORT" \
            "$EXTRACT_DIR/var/jb/usr/lib/opencode/runtime/runtime-manifest.json"; do
        [ -n "$candidate_file" ] && [ -f "$candidate_file" ] || continue
        value="$("$PYTHON" -c 'import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
print(data.get("variant") or data.get("runtime_kind") or data.get("node_version") or "")' \
            "$candidate_file" 2>/dev/null || true)"
        case "$value" in
            *18*) printf 'node18'; return 0 ;;
            *22*) printf 'node22'; return 0 ;;
        esac
    done
    printf 'node22'
}
PKG_VARIANT="$(infer_variant)"
case "$PKG_VARIANT" in
    node18)
        SMOKE_NODE_VERSION="18.20.4"
        SMOKE_NODE_FLAGS="--no-warnings"
        ;;
    *)
        SMOKE_NODE_VERSION="22.9.0"
        SMOKE_NODE_FLAGS=""
        ;;
esac
info "variant: $PKG_VARIANT (host smoke Node $SMOKE_NODE_VERSION)"

# ------------------------------------------------------------ host smoke ---
EXTRACT_PREFIX="$EXTRACT_DIR/var/jb"
BUNDLE_DIR="$EXTRACT_PREFIX/usr/lib/opencode/cli"
LAUNCHER="$EXTRACT_PREFIX/usr/bin/opencode"
SMOKE_OUT="$OUT_DIR/host-smoke.json"
SMOKE_RC=0
if [ "$EXTRACT_RC" -ne 0 ]; then
    warn "host smoke skipped because the package could not be extracted"
elif [ "$SKIP_SMOKE" = "1" ]; then
    warn "host Node.js smoke test skipped (--skip-smoke; local dry-run only)"
else
    info "host-runtime CLI smoke test (pinned Node.js $SMOKE_NODE_VERSION, variant $PKG_VARIANT)"
    set -- bash "$ROOT/scripts/smoke-bundle-host.sh" \
        --bundle-dir "$BUNDLE_DIR" \
        --work-dir "$WORK_DIR/host-node" \
        --node-version "$SMOKE_NODE_VERSION" \
        --variant "$PKG_VARIANT" \
        --output "$SMOKE_OUT"
    if [ -n "$SMOKE_NODE_FLAGS" ]; then
        set -- "$@" --node-flags "$SMOKE_NODE_FLAGS"
    fi
    if [ -f "$LAUNCHER" ]; then
        set -- "$@" --launcher "$LAUNCHER" --prefix "$EXTRACT_PREFIX"
    fi
    if [ -n "$EXPECTED_OPENCODE_VERSION" ]; then
        set -- "$@" --expected-version "$EXPECTED_OPENCODE_VERSION"
    fi
    "$@" || SMOKE_RC=$?
    if [ "$SMOKE_RC" -ne 0 ]; then
        warn "host smoke test reported failures (recorded in the verification report)"
    fi
fi

# ---------------------------------------------------------------- verify ---
info "running verification suite"
set -- "$PYTHON" "$ROOT/packaging/verify/port_verify.py" verify \
    --deb "$DEB" \
    --mode "$MODE" \
    --out-dir "$OUT_DIR" \
    --repo-root "$ROOT" \
    --artifact-dir "$ARTIFACT_DIR" \
    --variant "$PKG_VARIANT"
if [ "$EXTRACT_RC" -eq 0 ] && [ -d "$EXTRACT_DIR" ]; then
    set -- "$@" --extract-dir "$EXTRACT_DIR"
fi
if [ -n "$CONTENTS_MANIFEST" ]; then
    [ -f "$CONTENTS_MANIFEST" ] || die "contents manifest not found: $CONTENTS_MANIFEST"
    set -- "$@" --contents-manifest "$CONTENTS_MANIFEST"
fi
if [ -n "$SOURCES" ]; then
    [ -f "$SOURCES" ] || die "sources JSON not found: $SOURCES"
    set -- "$@" --sources "$SOURCES"
fi
if [ -n "$PACKAGE_REPORT" ]; then
    [ -f "$PACKAGE_REPORT" ] || die "package report not found: $PACKAGE_REPORT"
    set -- "$@" --package-report "$PACKAGE_REPORT"
fi
if [ "$SKIP_SMOKE" = "1" ]; then
    set -- "$@" --skip-smoke
elif [ -f "$SMOKE_OUT" ]; then
    set -- "$@" --host-smoke-json "$SMOKE_OUT"
fi
if [ "$SKIP_NATIVE" = "1" ]; then
    set -- "$@" --skip-native-audit
fi
if [ -n "$RUN_ID" ]; then
    set -- "$@" --run-id "$RUN_ID"
fi
if [ -n "$RUN_URL" ]; then
    set -- "$@" --run-url "$RUN_URL"
fi
if [ -n "$EXPECTED_VERSION" ]; then
    set -- "$@" --expected-version "$EXPECTED_VERSION"
fi
VERIFY_RC=0
"$@" || VERIFY_RC=$?

# ------------------------------------------------------------- reporting ---
if [ -f "$OUT_DIR/verification-report.md" ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    cat "$OUT_DIR/verification-report.md" >> "$GITHUB_STEP_SUMMARY"
fi

echo ""
if [ -f "$OUT_DIR/verification-report.json" ]; then
    SUMMARY_LINE="$("$PYTHON" - "$OUT_DIR/verification-report.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    report = json.load(handle)
summary = report["summary"]
print(
    "CI status: {ci_status} | device: {device} | passed={passed} failed={failed} skipped={skipped}".format(
        ci_status=summary["ci_status"],
        device=summary["device_status"],
        passed=summary["passed"],
        failed=summary["failed"],
        skipped=summary["skipped"],
    )
)
PY
)"
    echo "validate-port: $SUMMARY_LINE"
    echo "validate-port: report $OUT_DIR/verification-report.md"
fi

#[ -n "${GITHUB_STEP_SUMMARY:-}" ] && ... handled above
if [ "$VERIFY_RC" -ne 0 ]; then
    echo "validate-port: FAILED (see report above)" >&2
    exit "$VERIFY_RC"
fi
info "validation PASSED (device execution remains UNVERIFIED ON DEVICE)"
exit 0
