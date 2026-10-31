#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build the OpenCode CLI Node.js bundle for the iOS port.
#
# Upstream OpenCode v2 ships an official Node distribution path:
#   packages/cli/script/build-node.ts --bundle-only
# which produces `packages/cli/dist-node/opencode.mjs` plus `dist-node/assets/`
# using Vite, *without* needing a Node SEA (single executable application)
# build step. This script drives that path on a clean checkout of the pinned
# upstream commit, applies the port's patch series, stages the iOS artifact and
# runs host-Node smoke tests.
#
# IMPORTANT SCOPE NOTE
#   The smoke tests in this script run a *stock host Node.js* binary on the CI
#   runner. They prove the JavaScript bundle loads and the CLI starts; they are
#   NOT verification on an iPhone. Device execution is verified separately
#   (see docs/OPENCODE_BUILD.md and the final package report).
#
# Usage:
#   scripts/build-opencode-bundle.sh fetch      # shallow-fetch pinned upstream commit
#   scripts/build-opencode-bundle.sh patches    # apply patches/opencode/*.patch
#   scripts/build-opencode-bundle.sh install    # bun install --os=* --cpu=*
#   scripts/build-opencode-bundle.sh build      # Vite node bundle (--bundle-only)
#   scripts/build-opencode-bundle.sh stage      # stage dist/opencode-cli-node-ios
#   scripts/build-opencode-bundle.sh smoke      # host-Node smoke matrix
#   scripts/build-opencode-bundle.sh manifest   # bundle-manifest.json + SHA256SUMS
#   scripts/build-opencode-bundle.sh verify     # offline artifact verification
#   scripts/build-opencode-bundle.sh all        # fetch patches install build stage smoke manifest verify
#
# Environment:
#   OPENCODE_TARGET          Node target of the bundle (default: darwin-arm64).
#   OPENCODE_IOS             set to 1 for the iOS prelude/asset adaptation patch.
#   OPENCODE_UPSTREAM_DIR    upstream checkout (default: <repo>/upstream-src/opencode).
#   OPENCODE_ARTIFACT_DIR    staged artifact (default: <repo>/dist/opencode-cli-node-ios).
#   OPENCODE_BUILD_DIR       build metadata/logs (default: <repo>/dist/opencode-build).
#   OPENCODE_NODE_CACHE_DIR  downloaded stock Node runtimes (default: <repo>/dist/node-runtimes).
#   OPENCODE_NODE_MATRIX     host Node versions to smoke test
#                            (default: "22.9.0 24.22.2 26.4.0"; 22.9.0 is the runtime we ship).
#   OPENCODE_SMOKE_REQUIRED  version whose `--version`/`--help` MUST pass (default: 22.9.0).
#   PYTHON                   python3 interpreter used for JSON/manifest helpers (default: python3).
#   BUN                      bun executable (default: bun).
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${OPENCODE_UPSTREAM_DIR:-$ROOT/upstream-src/opencode}"
PATCHES_DIR="$ROOT/patches/opencode"
ARTIFACT_DIR="${OPENCODE_ARTIFACT_DIR:-$ROOT/dist/opencode-cli-node-ios}"
BUILD_DIR="${OPENCODE_BUILD_DIR:-$ROOT/dist/opencode-build}"
NODE_CACHE_DIR="${OPENCODE_NODE_CACHE_DIR:-$ROOT/dist/node-runtimes}"
TARGET="${OPENCODE_TARGET:-darwin-arm64}"
IOS="${OPENCODE_IOS:-1}"
NODE_MATRIX="${OPENCODE_NODE_MATRIX:-22.9.0 24.22.2 26.4.0}"
SMOKE_REQUIRED="${OPENCODE_SMOKE_REQUIRED:-22.9.0}"
PYTHON="${PYTHON:-python3}"
BUN="${BUN:-bun}"
ARTIFACT_NAME="opencode-cli-node-ios"

log() { printf '[build-opencode] %s\n' "$*"; }
die() { printf '[build-opencode] ERROR: %s\n' "$*" >&2; exit 1; }

pin() {
  # pin KEY -> value of KEY=... from UPSTREAM.lock (first match, comments ignored)
  [ -f "$ROOT/UPSTREAM.lock" ] || die "missing UPSTREAM.lock"
  awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ROOT/UPSTREAM.lock"
}

require_upstream() {
  [ -d "$UPSTREAM_DIR/packages/cli" ] || die "upstream checkout missing at $UPSTREAM_DIR (run: $0 fetch)"
}

require_bun() {
  command -v "$BUN" >/dev/null 2>&1 || die "bun not found (set BUN=/path/to/bun)"
}

require_python() {
  command -v "$PYTHON" >/dev/null 2>&1 || die "python3 not found (set PYTHON=/path/to/python3)"
}

# --- fetch -----------------------------------------------------------------
# Shallow-fetches exactly the pinned upstream commit. GitHub serves arbitrary
# commit SHAs to `git fetch --depth 1`; if that ever fails we fall back to the
# codeload tarball (the patch series only needs the work tree, not git history).
cmd_fetch() {
  local repo ref actual
  repo="$(pin OPENCODE_REPO)"
  ref="$(pin OPENCODE_REF)"
  [ -n "$repo" ] || die "OPENCODE_REPO missing from UPSTREAM.lock"
  [ -n "$ref" ] || die "OPENCODE_REF missing from UPSTREAM.lock"

  if [ -d "$UPSTREAM_DIR/.git" ] && [ "$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || true)" = "$ref" ] &&
    [ -z "$(git -C "$UPSTREAM_DIR" status --porcelain 2>/dev/null || true)" ]; then
    log "upstream checkout already at pinned commit $ref"
    return 0
  fi

  if [ -d "$UPSTREAM_DIR" ]; then
    log "removing stale upstream checkout at $UPSTREAM_DIR"
    rm -rf "$UPSTREAM_DIR"
  fi
  mkdir -p "$(dirname "$UPSTREAM_DIR")"

  log "shallow fetch of $repo @ $ref"
  if git init -q "$UPSTREAM_DIR" &&
    git -C "$UPSTREAM_DIR" remote add origin "$repo" &&
    git -C "$UPSTREAM_DIR" -c advice.detachedHead=false fetch --depth 1 --no-tags -q origin "$ref" &&
    git -C "$UPSTREAM_DIR" -c advice.detachedHead=false checkout -q FETCH_HEAD; then
    actual="$(git -C "$UPSTREAM_DIR" rev-parse HEAD)"
    [ "$actual" = "$ref" ] || die "fetched commit $actual does not match pinned $ref"
    log "upstream checkout ready ($(git -C "$UPSTREAM_DIR" log -1 --format='%h %s'))"
    return 0
  fi

  log "git fetch failed; falling back to codeload tarball"
  rm -rf "$UPSTREAM_DIR"
  mkdir -p "$UPSTREAM_DIR"
  local codeload
  codeload="$(printf '%s' "$repo" | sed -e 's#^https://github.com/#https://codeload.github.com/#' -e 's#\.git$##')/tar.gz/$ref"
  curl -fsSL "$codeload" | tar -xzf - -C "$UPSTREAM_DIR" --strip-components=1 ||
    die "failed to download upstream tarball from $codeload"
  log "upstream checkout ready (tarball, no git metadata)"
}

# --- patches ---------------------------------------------------------------
cmd_patches() {
  require_upstream
  shopt -s nullglob
  local patches=("$PATCHES_DIR"/*.patch)
  shopt -u nullglob
  if [ ${#patches[@]} -eq 0 ]; then
    log "no patch files in $PATCHES_DIR (stock upstream build)"
    return 0
  fi
  local patch
  for patch in "${patches[@]}"; do
    log "applying $(basename "$patch")"
    if ! git -C "$UPSTREAM_DIR" apply --whitespace=nowarn "$patch"; then
      die "failed to apply $(basename "$patch") — patch series must apply cleanly to pinned commit $(pin OPENCODE_REF)"
    fi
  done
  log "applied ${#patches[@]} patch(es)"
}

# --- install ---------------------------------------------------------------
cmd_install() {
  require_upstream
  require_bun
  [ -f "$UPSTREAM_DIR/package.json" ] || die "upstream package.json missing"
  log "bun $(command -v "$BUN") install --os=* --cpu=* (full platform asset set for asset collection)"
  (cd "$UPSTREAM_DIR" && "$BUN" install --os='*' --cpu='*')
}

# --- build -----------------------------------------------------------------
cmd_build() {
  require_upstream
  require_bun
  local cli="$UPSTREAM_DIR/packages/cli"
  [ -d "$cli/node_modules" ] || [ -d "$UPSTREAM_DIR/node_modules" ] ||
    die "upstream dependencies are not installed (run: $0 install)"

  # The upstream script refuses to run outside its pinned Bun version and
  # derives the version/channel from these variables; the iOS port always
  # builds from the UPSTREAM.lock pins, never from the local git branch.
  export OPENCODE_TARGET="$TARGET"
  export OPENCODE_IOS="$IOS"
  export OPENCODE_VERSION="${OPENCODE_VERSION:-$(pin OPENCODE_VERSION)}"
  export OPENCODE_CHANNEL="${OPENCODE_CHANNEL:-latest}"
  log "building cli-node target=$TARGET OPENCODE_IOS=$IOS OPENCODE_VERSION=$OPENCODE_VERSION channel=$OPENCODE_CHANNEL"

  (cd "$cli" && "$BUN" run script/build-node.ts --bundle-only --skip-install)

  [ -f "$cli/dist-node/opencode.mjs" ] || die "build did not produce packages/cli/dist-node/opencode.mjs"
  [ -f "$cli/dist-node/assets/app-archive.bin" ] || die "build did not produce dist-node/assets/app-archive.bin"
  local size assets
  size="$(wc -c <"$cli/dist-node/opencode.mjs" | tr -d ' ')"
  assets="$(find "$cli/dist-node/assets" -type f | wc -l | tr -d ' ')"
  log "bundle built: opencode.mjs ${size} bytes, ${assets} asset file(s)"

  mkdir -p "$BUILD_DIR"
  {
    echo "ARTIFACT_NAME=$ARTIFACT_NAME"
    echo "TARGET=$TARGET"
    echo "OPENCODE_IOS=$IOS"
    echo "UPSTREAM_REPO=$(pin OPENCODE_REPO)"
    echo "UPSTREAM_COMMIT=$(pin OPENCODE_REF)"
    echo "UPSTREAM_VERSION=$(pin OPENCODE_VERSION)"
    echo "OPENCODE_VERSION=$OPENCODE_VERSION"
    echo "OPENCODE_CHANNEL=$OPENCODE_CHANNEL"
    echo "BUN_VERSION=$("$BUN" --version)"
    echo "BUILD_HOST_OS=$(uname -s 2>/dev/null || echo unknown)"
    echo "BUILD_HOST_ARCH=$(uname -m 2>/dev/null || echo unknown)"
    echo "BUILD_HOST_NODE=$(node --version 2>/dev/null || echo unavailable)"
    echo "BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ -n "${GITHUB_RUN_ID:-}" ]; then
      echo "GITHUB_REPOSITORY=$GITHUB_REPOSITORY"
      echo "GITHUB_RUN_ID=$GITHUB_RUN_ID"
      echo "GITHUB_SHA=$GITHUB_SHA"
      echo "RUNNER_OS=${RUNNER_OS:-}"
      echo "RUNNER_ARCH=${RUNNER_ARCH:-}"
    fi
  } >"$BUILD_DIR/build-info.env"
  cp -f "$cli/dist-node/opencode.mjs" "$BUILD_DIR/opencode.mjs"
}

# --- stage -----------------------------------------------------------------
# Copies the bundle + assets into the artifact directory exactly as the build
# produced them. Asset inclusion/exclusion for iOS is decided by the patched
# upstream asset collector (patches/opencode/), not by post-hoc filtering here,
# so the manifest always describes the true build output.
cmd_stage() {
  local cli="$UPSTREAM_DIR/packages/cli"
  [ -f "$cli/dist-node/opencode.mjs" ] || die "no build output (run: $0 build)"
  log "staging artifact $ARTIFACT_DIR"
  rm -rf "$ARTIFACT_DIR"
  mkdir -p "$ARTIFACT_DIR"
  cp -p "$cli/dist-node/opencode.mjs" "$ARTIFACT_DIR/opencode.mjs"
  chmod 0644 "$ARTIFACT_DIR/opencode.mjs"
  cp -Rp "$cli/dist-node/assets" "$ARTIFACT_DIR/assets"
  log "staged $(find "$ARTIFACT_DIR/assets" -type f | wc -l | tr -d ' ') asset file(s), \
$(du -sk "$ARTIFACT_DIR" | awk '{print $1}') KiB"
}

# --- smoke -----------------------------------------------------------------
cmd_smoke() {
  require_python
  [ -f "$ARTIFACT_DIR/opencode.mjs" ] || die "artifact not staged (run: $0 stage)"
  mkdir -p "$BUILD_DIR" "$NODE_CACHE_DIR"
  log "host-Node smoke matrix: $NODE_MATRIX (required: $SMOKE_REQUIRED)"
  # shellcheck disable=SC2086 # intentional word splitting of the version list
  "$PYTHON" "$ROOT/src/opencode-ios/host_smoke.py" \
    --bundle-dir "$ARTIFACT_DIR" \
    --cache-dir "$NODE_CACHE_DIR" \
    --report "$BUILD_DIR/smoke-report.json" \
    --versions $NODE_MATRIX \
    --require-version "$SMOKE_REQUIRED"
  log "smoke report: $BUILD_DIR/smoke-report.json"
}

# --- manifest --------------------------------------------------------------
cmd_manifest() {
  require_python
  [ -f "$ARTIFACT_DIR/opencode.mjs" ] || die "artifact not staged (run: $0 stage)"
  [ -d "$ARTIFACT_DIR/assets" ] || die "artifact assets missing (run: $0 stage)"
  local smoke="$BUILD_DIR/smoke-report.json"
  [ -f "$smoke" ] || die "smoke report missing (run: $0 smoke)"
  log "writing bundle-manifest.json + SHA256SUMS"
  "$PYTHON" "$ROOT/src/opencode-ios/bundle_manifest.py" \
    --artifact-dir "$ARTIFACT_DIR" \
    --build-info "$BUILD_DIR/build-info.env" \
    --smoke-report "$smoke" \
    --patches-dir "$PATCHES_DIR" \
    --upstream-lock "$ROOT/UPSTREAM.lock"
}

cmd_verify() {
  require_python
  "$PYTHON" "$ROOT/src/opencode-ios/bundle_manifest.py" \
    --artifact-dir "$ARTIFACT_DIR" \
    --build-info "$BUILD_DIR/build-info.env" \
    --patches-dir "$PATCHES_DIR" \
    --upstream-lock "$ROOT/UPSTREAM.lock" \
    --verify-only
  log "artifact verified"
}

cmd_all() {
  cmd_fetch
  cmd_patches
  cmd_install
  cmd_build
  cmd_stage
  cmd_smoke
  cmd_manifest
  cmd_verify
}

main() {
  local command="${1:-}"
  shift || true
  case "$command" in
    fetch) cmd_fetch "$@" ;;
    patches) cmd_patches "$@" ;;
    install) cmd_install "$@" ;;
    build) cmd_build "$@" ;;
    stage) cmd_stage "$@" ;;
    smoke) cmd_smoke "$@" ;;
    manifest) cmd_manifest "$@" ;;
    verify) cmd_verify "$@" ;;
    all) cmd_all "$@" ;;
    *)
      printf 'usage: %s <fetch|patches|install|build|stage|smoke|manifest|verify|all>\n' "$0" >&2
      exit 2
      ;;
  esac
}

main "$@"
