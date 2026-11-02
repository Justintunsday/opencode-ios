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
#   scripts/build-opencode-bundle.sh deps-patches  # patch installed @opentui/core (node26 only)
#   scripts/build-opencode-bundle.sh assetcheck    # OpenTUI iOS asset/resolver host check (node26)
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
#   OPENCODE_IOS_NODE26      set to 1 for the Node 26 + node:ffi variant (real TUI, Phase D).
#   OPENCODE_OPENTUI_IOS_DYLIB
#                            prebuilt iPhoneOS libopentui.dylib staged as a CLI asset; required
#                            when OPENCODE_IOS_NODE26=1 (from the opencode-ios `opentui-ios-renderer`
#                            artifact).
#   OPENCODE_OPENTUI_IOS_DYLIB_SHA256
#                            expected sha256 of that dylib (default: the Phase C green artifact pin).
#   OPENCODE_OPENTUI_IOS_ASSET_KEY
#                            asset key of the renderer (default
#                            @opentui/core-ios-arm64/libopentui.dylib).
#   NODE_BIN                 host node used by the OpenTUI iOS resolver check (default: node).
#   PYTHON                   python3 interpreter used for JSON/manifest helpers (default: python3).
#   BUN                      bun executable (default: bun).
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${OPENCODE_UPSTREAM_DIR:-$ROOT/upstream-src/opencode}"
PATCHES_DIR="$ROOT/patches/opencode"
# Two conditional variants share this script:
#   default        Node 22.9 iPhoneOS bundle  -> opencode-cli-node-ios
#   Node 18 hedge  Node 18 iPhoneOS fallback   -> opencode-cli-node18-ios
#                  (OPENCODE_IOS_NODE18=1; adds patch 0007 + the sql.js node:sqlite shim)
#   Node 26 / TUI  Node 26 node:ffi real-TUI    -> opencode-cli-node26-ios
#                  (OPENCODE_IOS_NODE26=1; stages the OpenTUI iPhoneOS renderer dylib asset and
#                   needs the FFI-enabled Node 26 iPhoneOS runtime)
NODE18="${OPENCODE_IOS_NODE18:-0}"
NODE26="${OPENCODE_IOS_NODE26:-0}"
if [ "$NODE18" = "1" ]; then
  DEFAULT_ARTIFACT="opencode-cli-node18-ios"
  DEFAULT_MATRIX="18.20.4 22.9.0"
  DEFAULT_REQUIRED="18.20.4"
elif [ "$NODE26" = "1" ]; then
  DEFAULT_ARTIFACT="opencode-cli-node26-ios"
  DEFAULT_MATRIX="26.13.0 24.22.2"
  DEFAULT_REQUIRED="26.13.0"
else
  DEFAULT_ARTIFACT="opencode-cli-node-ios"
  DEFAULT_MATRIX="22.9.0 24.22.2 26.4.0"
  DEFAULT_REQUIRED="22.9.0"
fi
ARTIFACT_DIR="${OPENCODE_ARTIFACT_DIR:-$ROOT/dist/$DEFAULT_ARTIFACT}"
BUILD_DIR="${OPENCODE_BUILD_DIR:-$ROOT/dist/opencode-build}"
NODE_CACHE_DIR="${OPENCODE_NODE_CACHE_DIR:-$ROOT/dist/node-runtimes}"
TARGET="${OPENCODE_TARGET:-darwin-arm64}"
IOS="${OPENCODE_IOS:-1}"
NODE_MATRIX="${OPENCODE_NODE_MATRIX:-$DEFAULT_MATRIX}"
SMOKE_REQUIRED="${OPENCODE_SMOKE_REQUIRED:-$DEFAULT_REQUIRED}"
PYTHON="${PYTHON:-python3}"
BUN="${BUN:-bun}"
ARTIFACT_NAME="${OPENCODE_ARTIFACT_NAME:-$DEFAULT_ARTIFACT}"
# Node 18 fallback sqlite: pinned sql.js (MIT) release from the npm registry. Version, tarball
# sha256 and the two staged files are pinned so the artifact is reproducible and auditable.
SQLJS_VERSION="1.15.2"
SQLJS_TARBALL_SHA256="74fbdd373ad7eb2bbe74c7807581c1c39e424ee53ed95042a02208cbc96d72fd"
SQLJS_JS_SHA256="b46d4bddfdde8a787fc4764bd0a405cdfdf96fbd77e6a4e95446106826ecfa47"
SQLJS_WASM_SHA256="0dfeecda2070b36da0cd4f6afa250af9453de528a983770f85b13d5d6b667572"
# Node 26 (Phase D real-TUI) variant: the OpenTUI iPhoneOS renderer dylib shipped in the CLI
# assets. Pinned to the Phase C green build (opencode-ios `opentui-ios-renderer` run 41313921358);
# the workflow downloads that artifact and this script verifies the sha256 + Mach-O before use.
OPENTUI_IOS_ASSET_KEY="${OPENCODE_OPENTUI_IOS_ASSET_KEY:-@opentui/core-ios-arm64/libopentui.dylib}"
OPENTUI_IOS_DYLIB="${OPENCODE_OPENTUI_IOS_DYLIB:-}"
OPENTUI_IOS_DYLIB_SHA256="${OPENCODE_OPENTUI_IOS_DYLIB_SHA256:-954289152cc182780a81ca7199ceeec04ee8c55c334f85710e0ff192f4817638}"
NODE_BIN="${NODE_BIN:-node}"

log() { printf '[build-opencode] %s\n' "$*"; }
die() { printf '[build-opencode] ERROR: %s\n' "$*" >&2; exit 1; }

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

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

require_node() {
  command -v "$NODE_BIN" >/dev/null 2>&1 || die "host node not found (set NODE_BIN=/path/to/node)"
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

# --- Node 18 fallback sqlite assets ----------------------------------------
# Downloads the pinned sql.js release (MIT) and stages the two files the shim needs.
# The Node 18 runtime has no node:sqlite; the patch series maps it to this shim.
prepare_node18_sqljs() {
  [ "$NODE18" = "1" ] || return 0
  local downloads="$BUILD_DIR/downloads"
  local tarball="$downloads/sql.js-$SQLJS_VERSION.tgz"
  local target="$BUILD_DIR/node18-sqlite"
  mkdir -p "$downloads"
  if [ ! -f "$tarball" ]; then
    log "fetching sql.js $SQLJS_VERSION (MIT) for the Node 18 node:sqlite shim"
    curl -fsSL "https://registry.npmjs.org/sql.js/-/sql.js-$SQLJS_VERSION.tgz" -o "$tarball" ||
      die "failed to download sql.js $SQLJS_VERSION"
  fi
  local actual
  actual="$(sha256_file "$tarball")"
  [ "$actual" = "$SQLJS_TARBALL_SHA256" ] ||
    die "sql.js tarball checksum mismatch (expected $SQLJS_TARBALL_SHA256, got $actual)"
  if [ ! -f "$target/sql-wasm.js" ] || [ ! -f "$target/sql-wasm.wasm" ]; then
    rm -rf "$target"
    mkdir -p "$target"
    tar -xzf "$tarball" -C "$target" --strip-components=1 \
      "package/dist/sql-wasm.js" "package/dist/sql-wasm.wasm" || die "failed to extract sql.js assets"
    mv "$target/dist/sql-wasm.js" "$target/sql-wasm.js"
    mv "$target/dist/sql-wasm.wasm" "$target/sql-wasm.wasm"
    rmdir "$target/dist" 2>/dev/null || true
  fi
  [ "$(sha256_file "$target/sql-wasm.js")" = "$SQLJS_JS_SHA256" ] || die "sql-wasm.js checksum mismatch"
  [ "$(sha256_file "$target/sql-wasm.wasm")" = "$SQLJS_WASM_SHA256" ] || die "sql-wasm.wasm checksum mismatch"
  export OPENCODE_IOS_NODE18=1
  export OPENCODE_NODE18_SQLJS_DIR="$target"
  export OPENCODE_NODE18_SQLITE_SHIM="$ROOT/src/opencode-ios/node18-sqlite-shim.mjs"
  [ -f "$OPENCODE_NODE18_SQLITE_SHIM" ] || die "missing Node 18 sqlite shim: $OPENCODE_NODE18_SQLITE_SHIM"
}

# --- node_modules dependency patches (node26 variant only) -------------------
# The OpenTUI FFI loader lives in the *published* @opentui/core 0.8.0 package, so its iOS native
# asset support is patched after `bun install` (patches/opencode/node-modules/). The patch adds
# the ios target to NATIVE_FILE_NAMES and resolves the renderer source/OTUI_ASSET_ROOT key.
# Locate the installed @opentui/core package. bun's node_modules layout depends on the
# linker/version: hoisted (`node_modules/@opentui/core`) or isolated
# (`node_modules/.bun/@opentui+core@<v>/node_modules/@opentui/core`), so find the real path.
resolve_opentui_core() {
  local found
  found="$(find "$UPSTREAM_DIR" -type f -path '*/node_modules/@opentui/core/package.json' 2>/dev/null |
    grep -v '/node_modules/@opentui/core/node_modules/' | head -n 1 || true)"
  if [ -z "$found" ]; then
    log "node_modules layout (for diagnosis):"
    find "$UPSTREAM_DIR" -maxdepth 4 -type d -name node_modules 2>/dev/null | sed -n '1,10p' >&2 || true
    die "installed @opentui/core not found under $UPSTREAM_DIR (run: $0 install)"
  fi
  dirname "$found"
}

cmd_deps_patches() {
  [ "$NODE26" = "1" ] || {
    log "no node_modules dependency patches for this variant"
    return 0
  }
  require_upstream
  local core prefix patch
  core="$(resolve_opentui_core)"
  # git-apply prefix such that "<prefix>/node_modules/@opentui/core/<file>" is the real path
  prefix="$(cd "$core" && cd ../../.. && pwd)"
  prefix="${prefix#"$UPSTREAM_DIR"/}"
  shopt -s nullglob
  local patches=("$PATCHES_DIR"/node-modules/*.patch)
  shopt -u nullglob
  [ ${#patches[@]} -gt 0 ] || die "missing node-modules patches in $PATCHES_DIR/node-modules"
  for patch in "${patches[@]}"; do
    if [ -n "$prefix" ] && [ "$prefix" != "." ] &&
      git -C "$UPSTREAM_DIR" apply --directory="$prefix" --reverse --check "$patch" >/dev/null 2>&1; then
      log "dependency patch already applied: $(basename "$patch")"
      continue
    fi
    if [ -z "$prefix" ] || [ "$prefix" = "." ] &&
      git -C "$UPSTREAM_DIR" apply --reverse --check "$patch" >/dev/null 2>&1; then
      log "dependency patch already applied: $(basename "$patch")"
      continue
    fi
    log "applying dependency patch $(basename "$patch") (core: $core)"
    if [ -n "$prefix" ] && [ "$prefix" != "." ]; then
      git -C "$UPSTREAM_DIR" apply --whitespace=nowarn --directory="$prefix" "$patch" ||
        die "failed to apply dependency patch $(basename "$patch")"
    else
      git -C "$UPSTREAM_DIR" apply --whitespace=nowarn "$patch" ||
        die "failed to apply dependency patch $(basename "$patch")"
    fi
  done
  grep -q 'ios: "libopentui.dylib"' "$core/node-assets.js" ||
    die "dependency patch marker missing from node-assets.js"
  grep -q 'OPENCODE_IOS === "1"' "$core/chunk-node-y0w0hq5m.js" ||
    die "dependency patch marker missing from the runtime FFI chunk"
  log "applied ${#patches[@]} dependency patch(es) to @opentui/core ($core)"
}

# --- OpenTUI iPhoneOS renderer asset (node26 variant only) ------------------
prepare_opentui_ios_dylib() {
  [ "$NODE26" = "1" ] || return 0
  require_python
  [ -n "$OPENTUI_IOS_DYLIB" ] ||
    die "OPENCODE_IOS_NODE26=1 requires OPENCODE_OPENTUI_IOS_DYLIB (the prebuilt libopentui.dylib)"
  [ -f "$OPENTUI_IOS_DYLIB" ] || die "OpenTUI iOS dylib not found: $OPENTUI_IOS_DYLIB"
  local actual
  actual="$(sha256_file "$OPENTUI_IOS_DYLIB")"
  [ "$actual" = "$OPENTUI_IOS_DYLIB_SHA256" ] ||
    die "OpenTUI iOS dylib sha256 mismatch (expected $OPENTUI_IOS_DYLIB_SHA256, got $actual)"
  "$PYTHON" "$ROOT/scripts/check_macho.py" "$OPENTUI_IOS_DYLIB" --kind dylib --max-minos 16.1.1 ||
    die "OpenTUI iOS dylib Mach-O audit failed"
  export OPENCODE_IOS_NODE26=1
  export OPENCODE_OPENTUI_IOS_DYLIB="$OPENTUI_IOS_DYLIB"
  export OPENCODE_OPENTUI_IOS_DYLIB_SHA256="$actual"
  log "OpenTUI iOS renderer dylib OK: $OPENTUI_IOS_DYLIB ($(wc -c <"$OPENTUI_IOS_DYLIB" | tr -d ' ') bytes, sha256 $actual)"
}

# --- build -----------------------------------------------------------------
cmd_build() {
  require_upstream
  require_bun
  local cli="$UPSTREAM_DIR/packages/cli"
  [ -d "$cli/node_modules" ] || [ -d "$UPSTREAM_DIR/node_modules" ] ||
    die "upstream dependencies are not installed (run: $0 install)"

  mkdir -p "$BUILD_DIR"
  prepare_node18_sqljs
  prepare_opentui_ios_dylib

  # The upstream script refuses to run outside its pinned Bun version and
  # derives the version/channel from these variables; the iOS port always
  # builds from the UPSTREAM.lock pins, never from the local git branch.
  export OPENCODE_TARGET="$TARGET"
  export OPENCODE_IOS="$IOS"
  export OPENCODE_VERSION="${OPENCODE_VERSION:-$(pin OPENCODE_VERSION)}"
  export OPENCODE_CHANNEL="${OPENCODE_CHANNEL:-latest}"
  log "building cli-node target=$TARGET OPENCODE_IOS=$IOS OPENCODE_IOS_NODE18=$NODE18 OPENCODE_VERSION=$OPENCODE_VERSION channel=$OPENCODE_CHANNEL"

  (cd "$cli" && "$BUN" run script/build-node.ts --bundle-only --skip-install)

  [ -f "$cli/dist-node/opencode.mjs" ] || die "build did not produce packages/cli/dist-node/opencode.mjs"
  [ -f "$cli/dist-node/assets/app-archive.bin" ] || die "build did not produce dist-node/assets/app-archive.bin"
  if [ "$NODE18" = "1" ]; then
    [ -f "$cli/dist-node/assets/node18-sqlite/sql-wasm.js" ] || die "build did not stage node18-sqlite/sql-wasm.js"
    [ -f "$cli/dist-node/assets/node18-sqlite/sql-wasm.wasm" ] || die "build did not stage node18-sqlite/sql-wasm.wasm"
  fi
  local size assets
  size="$(wc -c <"$cli/dist-node/opencode.mjs" | tr -d ' ')"
  assets="$(find "$cli/dist-node/assets" -type f | wc -l | tr -d ' ')"
  log "bundle built: opencode.mjs ${size} bytes, ${assets} asset file(s)"

  mkdir -p "$BUILD_DIR"
  {
    echo "ARTIFACT_NAME=$ARTIFACT_NAME"
    echo "TARGET=$TARGET"
    echo "OPENCODE_IOS=$IOS"
    echo "NODE18_VARIANT=$NODE18"
    echo "NODE26_VARIANT=$NODE26"
    if [ "$NODE18" = "1" ]; then
      echo "SQLJS_VERSION=$SQLJS_VERSION"
      echo "SQLJS_TARBALL_SHA256=$SQLJS_TARBALL_SHA256"
    fi
    if [ "$NODE26" = "1" ]; then
      echo "RUNTIME_NODE_VERSION=26.13.0"
      echo "OPENCODE_OPENTUI_IOS_DYLIB=$OPENTUI_IOS_DYLIB"
      echo "OPENCODE_OPENTUI_IOS_DYLIB_SHA256=$OPENTUI_IOS_DYLIB_SHA256"
      echo "OPENCODE_OPENTUI_IOS_ASSET_KEY=$OPENTUI_IOS_ASSET_KEY"
    fi
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
  if [ "$NODE26" = "1" ]; then
    local staged="$ARTIFACT_DIR/assets/$OPENTUI_IOS_ASSET_KEY"
    [ -f "$staged" ] || die "staged artifact is missing the OpenTUI iOS renderer asset: $OPENTUI_IOS_ASSET_KEY"
    [ "$(sha256_file "$staged")" = "$OPENTUI_IOS_DYLIB_SHA256" ] ||
      die "staged OpenTUI iOS renderer asset sha256 mismatch: $OPENTUI_IOS_ASSET_KEY"
    log "staged OpenTUI iOS renderer asset: $OPENTUI_IOS_ASSET_KEY"
  fi
  log "staged $(find "$ARTIFACT_DIR/assets" -type f | wc -l | tr -d ' ') asset file(s), \
$(du -sk "$ARTIFACT_DIR" | awk '{print $1}') KiB"
}

# --- OpenTUI iOS resolver/asset check (node26 variant only) -----------------
# Host-Node unit check for the dependency patch: the patched build-time resolver must map the
# iOS native asset target to @opentui/core-ios-arm64/libopentui.dylib (with process.platform
# stubbed to "ios"), and the staged asset must exist at the OTUI_ASSET_ROOT-relative key.
cmd_assetcheck() {
  [ "$NODE26" = "1" ] || return 0
  require_node
  [ -f "$ARTIFACT_DIR/assets/$OPENTUI_IOS_ASSET_KEY" ] ||
    die "staged artifact is missing $OPENTUI_IOS_ASSET_KEY (run: $0 stage)"
  local core
  core="$(resolve_opentui_core)"
  "$NODE_BIN" "$ROOT/src/opencode-ios/opentui_ios_asset_check.mjs" \
    --core "$core/node-assets.js" \
    --artifact-dir "$ARTIFACT_DIR" \
    --asset-key "$OPENTUI_IOS_ASSET_KEY" \
    --dylib "$OPENTUI_IOS_DYLIB" \
    --expected-sha256 "$OPENTUI_IOS_DYLIB_SHA256" \
    --bundle "$ARTIFACT_DIR/opencode.mjs"
}

# --- smoke -----------------------------------------------------------------
cmd_smoke() {
  require_python
  [ -f "$ARTIFACT_DIR/opencode.mjs" ] || die "artifact not staged (run: $0 stage)"
  mkdir -p "$BUILD_DIR" "$NODE_CACHE_DIR"
  log "host-Node smoke matrix: $NODE_MATRIX (required: $SMOKE_REQUIRED)"
  local -a versions
  read -r -a versions <<<"$NODE_MATRIX"
  local -a smoke_args=(
    --bundle-dir "$ARTIFACT_DIR"
    --cache-dir "$NODE_CACHE_DIR"
    --report "$BUILD_DIR/smoke-report.json"
    --versions "${versions[@]}"
    --require-version "$SMOKE_REQUIRED"
  )
  # Some local host environments have an unwritable system temp dir; CI does not.
  if [ -n "${OPENCODE_SMOKE_WORK_ROOT:-}" ]; then
    smoke_args+=(--work-root "$OPENCODE_SMOKE_WORK_ROOT")
  fi
  "$PYTHON" "$ROOT/src/opencode-ios/host_smoke.py" "${smoke_args[@]}"
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
  cmd_deps_patches
  cmd_build
  cmd_stage
  cmd_assetcheck
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
    deps-patches) cmd_deps_patches "$@" ;;
    assetcheck) cmd_assetcheck "$@" ;;
    smoke) cmd_smoke "$@" ;;
    manifest) cmd_manifest "$@" ;;
    verify) cmd_verify "$@" ;;
    all) cmd_all "$@" ;;
    *)
      printf 'usage: %s <fetch|patches|install|deps-patches|build|stage|assetcheck|smoke|manifest|verify|all>\n' "$0" >&2
      exit 2
      ;;
  esac
}

main "$@"
