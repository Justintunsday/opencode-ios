# Runtime build: native iPhoneOS arm64 Node.js 22.9.0

Status: **CI build of the `node` CLI + static Mach-O audit.** Device execution is
**UNVERIFIED ON DEVICE** (GitHub-hosted macOS runners cannot run iPhoneOS binaries).

This document is the recipe, pin record and evidence log for
`.github/workflows/build-runtime.yml`, `scripts/build-ios-runtime.sh`,
`scripts/ios-runtime/**` and `patches/nodejs-mobile/**`. It is the source of
truth for how the runtime artifact `ios-node-runtime` is produced.

## 1. What the artifact is

`ios-node-runtime` is a **native iPhoneOS arm64 Node.js 22.9.0 `node`
executable**, built from the pinned nodejs-mobile source with the iPhoneOS SDK
(not the macOS SDK, not an Android binary, not the macOS `node` renamed):

| Artifact file | Meaning |
| --- | --- |
| `node` | the CLI runtime, Mach-O `MH_EXECUTE`, arm64, platform IOS, minos <= 16.1.1, ad-hoc signed with ldid |
| `entitlements.plist` | the exact entitlement set used when signing |
| `runtime-manifest.json` | pins, build path, observed static facts, runtime policy (JIT/WASM/platform) |
| `SHA256SUMS` | sha256 over the three files above |
| `validation-report.txt` | human-readable copy of the static validation evidence |

The artifact contract is defined in `docs/COORDINATION.md`; `package-rootless.yml`
consumes this artifact and installs `node` under
`/var/jb/usr/lib/opencode/runtime/node`.

## 2. Upstream pins

Taken from `UPSTREAM.lock` (do not float in CI; the workflow pins the commit and
verifies it after checkout):

| Item | Pin |
| --- | --- |
| nodejs-mobile source | `https://github.com/nodejs-mobile/nodejs-mobile` |
| nodejs-mobile branch | `update22-9-0` |
| nodejs-mobile commit | `106c51f95d55d1010de56a2ffd09bfb4ba819a47` |
| Node.js source version | `22.9.0` (from `src/node_version.h` in that commit) |
| build fixes | nodejs-mobile PR #150, head `36f2685a46e342f616b5d3c3178b5cbcda78fef7`, https://github.com/nodejs-mobile/nodejs-mobile/pull/150 |
| CI runner | `macos-15` |
| Xcode | `16.4` (`mobiledevops/xcode-select-version-action@v1`) |
| deployment target | nodejs-mobile's iOS default `IPHONEOS_DEPLOYMENT_TARGET=14.0` (<= device iOS 16.1.1) |

Upstream repositories are never modified: CI applies
`patches/nodejs-mobile/0001-ios-build-fixes.patch` to a clean checkout of the
pinned commit and verifies the checkout SHA first.

## 3. Patch series: `patches/nodejs-mobile/0001-ios-build-fixes.patch`

The full PR #150 diff was downloaded and its sha256 recorded in the patch header
(`728c77f3215d1b5995d100a4b99d46484c3961ef4e27b0a587d9c0decdb1ef79` for the raw
download used here). This repository keeps only the source/build hunks:

| PR #150 hunk | Kept? | Why |
| --- | --- | --- |
| `configure.py` — `v8_enable_webassembly = 0` | yes | required for the jitless iOS build; **WebAssembly is disabled in this runtime** |
| `deps/simdutf/simdutf.gyp`, `deps/uv/uv.gyp`, `node.gyp` — host-toolset `SDKROOT=macosx` | yes | Node 22 cross-build host tools were compiled against the iPhoneOS SDK and failed; needed for `node_js2c`/gyp host tools |
| `deps/v8/src/base/build_config.h` — drop `V8_HAS_PTHREAD_JIT_WRITE_PROTECT` on iOS | yes | API not available in the iOS SDK / incompatible with the mobile build |
| `src/compile_cache.cc`, `src/util.h` — `std::filesystem`/`u8string` fixes | yes | build fix for the iOS libc++ toolchain |
| `tools/v8_gypfiles/v8.gyp` — add abseil `crc_non_temporal_memcpy.cc` | yes | link fix for arm64 (simulator-related in the PR; harmless/needed for the lib set) |
| `tools/ios_framework_prepare.sh`, `tools/ios-framework/.../project.pbxproj` | yes | keeps nodejs-mobile's Node 22.9 static-library/framework tooling consistent (not used by this CLI build, which intentionally skips the framework) |
| `.github/workflows/build-mobile-ios.yml`, `.github/workflows/build-mobile.yml` | **no** | upstream CI workflows; this repository has its own workflow |
| `.gitignore` | **no** | upstream build-directory ignores, irrelevant here |
| `tools/android_build.sh` | **no** | Android-only compiler flags |

The patch applies cleanly (`git apply --check`) to the pinned commit; verification
is repeated in CI before every build (see §6, step "Verify pinned commit and
apply nodejs-mobile build fixes").

## 4. Build recipe

Key decision: **do not pass `--enable-static`**. nodejs-mobile's
`tools/ios_framework_prepare.sh arm64` uses `--enable-static`, and
`configure.py` then sets gyp's `node_target_type=static_library` — that build
produces static libraries for the `NodeMobile.framework` but no CLI executable.
The same source builds a standalone `out/Release/node` when configured as an
executable. `scripts/build-ios-runtime.sh` therefore reproduces the
nodejs-mobile iOS recipe minus `--enable-static`:

```sh
export GYP_DEFINES="target_arch=arm64 host_os=mac target_os=ios"
./configure \
  --dest-os=ios \
  --dest-cpu=arm64 \
  --with-intl=none \
  --cross-compiling \
  --openssl-no-asm \
  --v8-options=--jitless \
  --without-node-code-cache \
  --without-node-snapshot
make -j"$(sysctl -n hw.ncpu)"          # -> out/Release/node
```

`./configure` also generates the gyp makefiles for the iPhoneOS SDK (this is the
fast ~1–2 min gate that catches patch/flag/toolchain errors before the 40–90 min
compile). Python 3.12 + setuptools venv is required because the bundled node-gyp
still imports `distutils`, removed in Python 3.12
(nodejs-mobile/node-gyp#2869 workaround); the workflow shadows `python3.13` in
the venv so `configure`'s newest-python preference still sees setuptools.

`make` builds with the iPhoneOS SDK because nodejs-mobile's bundled gyp
(`tools/gyp/pylib/gyp/generator/make.py`, flavor `make-ios`) emulates the Xcode
SDK settings from the `OS=="ios"` blocks in `common.gypi`
(`SDKROOT=iphoneos`, `-isysroot <iPhoneOS.sdk>`, `-miphoneos-version-min=14.0`,
`-arch arm64`).

### Fallback link path (safety net)

If `out/Release/node` is missing after `make` (or `make` failed while all static
libraries were already built), `scripts/build-ios-runtime.sh package` falls back
to re-running the recorded `node` link command with macOS-only flags removed
(`-Wl,-no_pie`) and iOS system frameworks appended
(`-framework CoreFoundation -framework Foundation -framework Security`), using
`scripts/ios-runtime/node_main.cc` (`node::Start(argc, argv)`, the same UNIX
entry point as Node's `src/node_main.cc`). The chosen path is recorded as
`build.build_path` in `runtime-manifest.json` (`make-executable` or
`fallback-link`). In CI the normal executable path is expected; the fallback
exists so a late link failure still yields a testable runtime.

## 5. Signing and entitlements

`ldid -S<scripts/ios-runtime/entitlements.plist> node` (ad-hoc signing, required
for jailbroken iOS to load the binary from `/var/jb`). Statically validation is
re-run **after** signing because signing adds a `LC_CODE_SIGNATURE` load command.

Entitlements carried by the artifact, and why:

| Entitlement | Why it is present |
| --- | --- |
| `com.apple.security.cs.allow-jit` | would permit V8 JIT on a jailbroken device; **not required by the shipped `--jitless` runtime**, kept so a future non-jitless build only needs a rebuild, not a signing-policy change |
| `com.apple.security.cs.allow-unsigned-executable-memory` | same: future JIT/WASM experimentation; not needed while jitless |
| `com.apple.security.cs.disable-library-validation` | lets the runtime load ad-hoc-signed / unsigned native addons built on-device (rootless jailbreak context) |
| `dynamic-codesigning` | jailbreak-scoped code-signing allowance used by the precedent Node-for-iOS packages |

Why this set and not more: the runtime in this artifact executes no JIT and no
WebAssembly (§6), so none of these are needed for the shipped configuration. The
set is deliberately limited to the four precedented entitlements; it is not a
claim of stock-iOS/App-Store compatibility. On a jailbroken device ldid
signatures with these entitlements are honoured; if the loader rejects the
signature, re-sign on device with the bundled `entitlements.plist` (see
`scripts/ios-runtime/README.md`).

## 6. Runtime policy (what the CLI engineer can rely on)

- **`process.platform === "ios"`.** `node.gyp` defines
  `NODE_PLATFORM="<(OS)"` for the executable and `libnode` targets;
  `configure.py` sets `OS=ios` for `--dest-os=ios`; `src/node_metadata.cc`
  initialises the metadata platform from `NODE_PLATFORM`. The runtime therefore
  reports `ios`, not `darwin`. This is a static/source-level determination
  (CI cannot execute the binary) and is recorded in
  `runtime-manifest.json` → `runtime_policy.process_platform`.
- **No JIT.** Built with `--v8-options=--jitless` (compiled into the binary as
  `NODE_V8_OPTIONS="--jitless"`). All JavaScript runs through V8's interpreter.
  Precedent packages (imcynic's Node 18/22 iOS `.deb`) also run
  JIT-disabled; JIT entitlement behaviour cannot be tested on hosted CI.
- **No WebAssembly.** PR #150 forces `v8_enable_webassembly=0`; `WebAssembly`
  is unavailable. The CLI port must degrade WASM-dependent features
  (tree-sitter / photon paths) instead of crashing.
- **Node 22.9.0 CLI flags:** `--experimental-sqlite` and
  `--experimental-vm-modules` exist in this version (needed for `node:sqlite`);
  `--use-system-ca` and `--experimental-ffi` **do not exist** in 22.9.0 — the
  launcher wrapper must not pass them (verified against
  `src/node_options.cc` in the pinned tree).
- **No snapshot, no code cache** (`--without-node-snapshot`,
  `--without-node-code-cache`), which is the supported configuration for a
  cross-compiled iOS Node.
- Static build: the only dynamic dependencies are iOS system
  libraries/frameworks (`/usr/lib/*`, `/System/Library/Frameworks/*`), audited
  from `otool -L`; no `/opt/homebrew`, `/usr/local`, macOS-only frameworks or
  `@rpath` dependencies are allowed.

## 7. CI design (performance and debuggability)

- `macos-15` + Xcode 16.4, `timeout-minutes: 360` on the build job.
- `workflow_dispatch` (with `cache_epoch` input to invalidate the cache) and
  push triggers limited to this runtime's paths.
- `permissions: contents: read`; `concurrency` group with
  `cancel-in-progress: false` so a second push cannot kill a running 1h build.
- Cheap failures stay cheap: checkout + patch apply + disk cleanup + configure
  (gyp generation) all run before the long `make`.
- Aggressive caching: `actions/cache/restore` + `actions/cache/save` for
  `nodejs-mobile/out/Release`, keyed on Node version + nodejs-mobile commit +
  Xcode version + patch sha256 + `cache_epoch`, with a prefix `restore-keys`
  fallback so a failed run's partially built tree makes the next run
  incremental. The cache is saved even when the job fails
  (`if: always()`, `continue-on-error: true`) and the save step is skipped on
  an exact cache hit. `mozilla-actions/sccache-action@v0.0.6` is enabled for
  parity with the upstream nodejs-mobile recipe.
- The final validation/signing/packaging steps run on a cache hit too (only the
  compile is skipped).
- CI cannot execute iOS binaries; therefore **no workflow claims device
  execution**. The device test checklist lives in
  `scripts/ios-runtime/README.md`.

## 8. CI run log / evidence

This section records the actual GitHub Actions runs for this workflow. Every
entry links the run and states the exact failure/fix; nothing here is
fabricated.

| Run | Status | Notes |
| --- | --- | --- |
| _filled in as the build-debug loop progresses_ | | |

## 9. Limitations / unresolved issues

1. **UNVERIFIED ON DEVICE** — the runtime has not been executed on the target
   iPhone by this pipeline. All CI validation is static. Device execution must
   be performed per `scripts/ios-runtime/README.md` before the runtime is called
   working.
2. **No JIT / no WebAssembly** — see §6. CPU-bound JS will be slower; WASM
   features must be feature-detected by the CLI.
3. **Signing is ldid ad-hoc with the entitlement set above** — behaviour under
   Dopamine/ElleKit loader is expected to match the precedent packages but is
   device-verified only after the device test.
4. **Patch is a subset of PR #150** — the omitted workflow/gitignore/android
   hunks are not needed here; if nodejs-mobile merges PR #150 upstream, this
   repository should re-pin and drop the patch.
5. **First cold CI build is long (40–90 min)** — subsequent runs use the
   `out/Release` cache; a patch change intentionally misses the exact cache key
   but can reuse the previous tree via the prefix restore key.

## 10. Local reproduction

```sh
# macOS with Xcode 16.4, from a clone of this port repository:
git clone --depth 1 https://github.com/nodejs-mobile/nodejs-mobile.git nodejs-mobile
git -C nodejs-mobile fetch --depth 1 origin 106c51f95d55d1010de56a2ffd09bfb4ba819a47
git -C nodejs-mobile checkout FETCH_HEAD
git -C nodejs-mobile apply "$PWD/patches/nodejs-mobile/0001-ios-build-fixes.patch"

python3.12 -m venv .venv && . .venv/bin/activate && pip install setuptools
bash scripts/build-ios-runtime.sh all

# verify the produced artifact:
python3 scripts/check_macho.py dist/ios-node-runtime/node --max-minos 16.1.1
xcrun otool -L dist/ios-node-runtime/node
ldid -e dist/ios-node-runtime/node
```
