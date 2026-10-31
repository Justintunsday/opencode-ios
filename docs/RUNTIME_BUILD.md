# Runtime build: native iPhoneOS arm64 Node.js 22.9.0

Status: **CI build of the `node` CLI (full-icu) + static Mach-O audit.**
A no-Intl 22.9.0 build of this same source was **device-verified to run** on the
target iPhone (Node version/platform/arch/fs/child_process/TLS/sqlite all OK),
but the OpenCode CLI bundle was rejected by V8 because `Intl` was absent and
`\p{...}` Unicode property escapes were unsupported. This ICU-enabled rebuild is
the fix for that blocker; its own device verification is still pending.
GitHub-hosted macOS runners cannot execute iPhoneOS binaries, so all CI evidence
below is static.

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
| `node` | the CLI runtime, Mach-O `MH_EXECUTE`, arm64, platform IOS, minos <= 16.1.1, with full ICU linked in (ECMA-402/`Intl` + V8 `\p{...}` escapes), ad-hoc signed with ldid |
| `entitlements.plist` | the exact entitlement set used when signing |
| `runtime-manifest.json` | pins, build path, observed static facts, runtime policy (JIT/WASM/Intl/platform) |
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
| ECMA-402/Intl | `--with-intl=full-icu`; ICU 75 source + full data bundled in the pinned tree at `deps/icu-small` (`README-FULL-ICU.txt`, `source/data/in/icudt75l.dat.bz2`), statically linked (no download) |

Upstream repositories are never modified: CI applies the whole
`patches/nodejs-mobile/*.patch` series (in filename order) to a clean checkout of
the pinned commit and verifies the checkout SHA first.

## 3. Patch series: `patches/nodejs-mobile/`

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
is repeated in CI before every build (see §7, step "Verify pinned commit and
apply nodejs-mobile build fixes").

### `0002-icu-host-toolset-macos.patch` (this repository, not PR #150)

PR #150 only targeted `--with-intl=none` builds, where no ICU host tools are
built. The runtime now needs ICU (see §6), so `make` must build **and immediately
execute** the ICU host-toolset tools (`genccode`, `icupkg`, `genrb`,
`iculslocs` from `tools/icu/icu-generic.gyp`) to generate the ICU data file.
With gyp flavor `ios`, `common.gypi`'s `OS=="ios"` target_defaults also stamp the
iPhoneOS SDK/arch onto those `#host` targets, so they would be iPhoneOS binaries
that the runner cannot execute. Patch 0002 adds one `_toolset=="host"`
`target_conditions` entry to the `OS=="ios"` block of `common.gypi` that restores
`SDKROOT=macosx` (+ `-mmacosx-version-min=10.15`, clears the iPhoneOS flags) for
every host-toolset target. This is the same treatment PR #150 applied per-target
to `node.gyp`, `deps/uv/uv.gyp` and `deps/simdutf/simdutf.gyp`; V8's
`tools/v8_gypfiles/toolchain.gypi` already had it. Only the build-time tools are
macOS binaries; the shipped runtime still targets iPhoneOS arm64.

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
  --with-intl=full-icu \
  --cross-compiling \
  --openssl-no-asm \
  --v8-options=--jitless \
  --without-node-code-cache \
  --without-node-snapshot
make -j"$(sysctl -n hw.ncpu)"          # -> out/Release/node
```

`./configure` also generates the gyp makefiles for the iPhoneOS SDK (this is the
fast gate - measured 3 s to generate the makefiles in the first green run - that
catches patch/flag/toolchain errors before the long compile; the measured cold
`make -j3` was 76m38s without ICU and is expected to be ~95-115 min with ICU). Python 3.12 + setuptools venv is required because the bundled node-gyp
still imports `distutils`, removed in Python 3.12
(nodejs-mobile/node-gyp#2869 workaround); the workflow shadows `python3.13` in
the venv so `configure`'s newest-python preference still sees setuptools.

`make` builds with the iPhoneOS SDK because nodejs-mobile's bundled gyp
(`tools/gyp/pylib/gyp/generator/make.py`, flavor `make-ios`) emulates the Xcode
SDK settings from the `OS=="ios"` blocks in `common.gypi`
(`SDKROOT=iphoneos`, `-isysroot <iPhoneOS.sdk>`, `-miphoneos-version-min=14.0`,
`-arch arm64`). ICU is enabled via `--with-intl=full-icu`: configure unpacks the
bundled `icudt75l.dat.bz2` into `deps/icu-tmp/`, compiles ICU's `common`+`i18n`
sources for the iPhoneOS target, and `genccode` (a macOS host tool, see §3
patch 0002) emits the full data as a C array that is statically linked into
`node`. That is why `otool -L` stays at `/usr/lib/libSystem` +
`/usr/lib/libc++`: there is no dynamic ICU dependency.

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

## 5. Signing and entitlements (device-verified minimal set)

`ldid -S<scripts/ios-runtime/entitlements.plist> node` (ad-hoc signing, required
for jailbroken iOS to load a binary from `/var/jb`). Static validation is re-run
**after** signing because signing adds a `LC_CODE_SIGNATURE` load command, and
the signed binary's entitlement set is checked for exactly the two required keys.

The entitlement set shipped in `scripts/ios-runtime/entitlements.plist` is
exactly:

```xml
<key>platform-application</key><true/>
<key>com.apple.private.security.no-sandbox</key><true/>
```

This set is **device-verified**, not assumed. On the target device (iPhone SE 2,
iPhone12,8, iOS 16.1.1 20B101, Dopamine rootless + ElleKit 1.2, 2026-10-31) an
existing iPhoneOS Node binary was re-signed with each candidate set and run:

| Entitlement set | Device result |
| --- | --- |
| `platform-application` + `com.apple.private.security.no-sandbox` | **RUNS** (`node --version` OK, exit 0) |
| `platform-application` only | SIGKILL (exit 137) |
| `platform-application` + `dynamic-codesigning` | SIGKILL (exit 137) |
| `platform-application` + `dynamic-codesigning` + `allow-jit` + `allow-unsigned-executable-memory` + `disable-library-validation` (previous 4-key set) | SIGKILL (exit 137) |
| previous 4-key set alone (without `platform-application`) | SIGKILL (exit 137) |
| full 9-key test set (adds `get-task-allow`, `com.apple.private.cs.debugger`, `com.apple.private.skip-library-validation`, ...) | RUNS (but not minimal) |

> The earlier 4-key JIT/executable-memory set (`com.apple.security.cs.allow-jit`,
> `...allow-unsigned-executable-memory`, `...disable-library-validation`,
> `dynamic-codesigning`) is **wrong for this artifact**: it is SIGKILLed by the
> loader (exit 137) even together with `platform-application`. It was replaced
> before the final artifact; only the two-key set above ships.

Why exactly these two keys:

- `platform-application` - marks the binary as a platform-scoped tool so the
  jailbroken iOS loader treats it as a first-class executable (required; without
  it the process is killed before `main`).
- `com.apple.private.security.no-sandbox` - the runtime needs the jailbroken
  filesystem layout (`/var/jb/...`, user home, child processes); the sandbox
  otherwise kills it.
- **No JIT / executable-memory entitlements** are needed because this runtime is
  built `--jitless` and without WebAssembly. They are deliberately omitted, and
  the CI sign step rejects them if they ever reappear in the signed
  entitlements.

If the device loader rejects the signature, re-sign on device with the bundled
`entitlements.plist` (see `scripts/ios-runtime/README.md`). This is a
jailbreak-rootless scenario; it is not a claim of stock-iOS/App-Store
compatibility.
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
- **Intl / ECMA-402 support IS present (full-icu).** This is mandatory, not
  optional: the CLI bundle uses `Intl.Segmenter`/`DateTimeFormat`/`NumberFormat`
  and 196 `\p{...}` regexp property escapes. The earlier `--with-intl=none`
  runtime started fine on the device but the bundle failed to even parse:
  `SyntaxError: Invalid regular expression:
  /[\p{Mark}\p{Control}\p{Default_Ignorable_Code_Point}]/gu:
  Invalid property name in character class` (device-rejected; see §6.1).
  `full-icu` (not `small-icu`) is used because small-icu trims the ICU
  break-iterator data (`tools/icu/icu_small.json`: `brkitr: none`) and Node's
  small-icu + `Intl.Segmenter` is a known crash class (nodejs/node#51752).
  CI hard-gates this: `config.gypi` must report `v8_enable_i18n_support=1` and
  the binary must contain ICU symbols (`icudt75_dat` / `u_strToUpper`).
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

### 6.1 Why ICU is required (device evidence)

On the target device (iPhone SE 2, iOS 16.1.1, Dopamine rootless, signed with the
2-key entitlement set), the first `--with-intl=none` 22.9.0 build was verified to
run `node` itself (`node --version` -> `v22.9.0`, `process.platform` -> `ios`,
`process.arch` -> `arm64`, V8 `12.4.254.21-node.19`, OpenSSL `3.0.13+quic`,
`node:sqlite` OK, fs OK, TLS OK, child_process OK, startup fast), but the
OpenCode CLI bundle could not be evaluated:

```
SyntaxError: Invalid regular expression:
/[\p{Mark}\p{Control}\p{Default_Ignorable_Code_Point}]/gu:
Invalid property name in character class
```

`Intl` was `undefined` in that build (no ICU data) and V8 rejects `\p{...}` when
compiled without ICU Unicode property data. No CLI-side patch can fix a regexp
syntax error raised before module evaluation, so the runtime had to be rebuilt
with ICU. That is the `--with-intl=full-icu` configuration of this document.

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
  Xcode version + patch-series sha256 + `cache_epoch`, with a prefix
  `restore-keys` fallback so a failed run's partially built tree makes the next
  run incremental. The cache is saved even when the job fails
  (`if: always()`, `continue-on-error: true`) and the save step is skipped on an
  exact cache hit. Only build inputs are in the key: signing-only files
  (`entitlements.plist`) do not invalidate the compiled tree.
  `mozilla-actions/sccache-action@v0.0.6` is enabled for parity with the
  upstream nodejs-mobile recipe.
- mtime + build-input fingerprint normalization: a fresh `git` checkout stamps
  every source file with "now", newer than any cached `.o`, which would force a
  full rebuild despite the cache. `scripts/build-ios-runtime.sh
  normalize-cache` stamps the pristine tree to 2000-01-01 and then compares the
  current build-inputs fingerprint (patch-series sha256 + configure-flag sha256,
  stored in the cached tree by `configure`) against the cached one: identical ->
  keep objects (fast no-op make), patch changed -> re-stamp only the files the
  patch rewrote (incremental rebuild), configure flags changed -> stamp
  everything to now (correct full rebuild). On an exact cache-key hit nothing is
  rebuilt.
- The final validation/signing/packaging steps run on a cache hit too (only the
  compile is skipped).
- CI cannot execute iOS binaries; therefore **no workflow claims device
  execution**. The device test checklist lives in
  `scripts/ios-runtime/README.md`.

## 8. Optional stretch artifact: `ios-ripgrep`

After the runtime job succeeds, the workflow also has an **optional** `ripgrep`
job (job-level `continue-on-error: true`, so it can never fail the required
runtime run). It cross-compiles pinned `ripgrep` 14.1.1 from crates.io with the
Rust `aarch64-apple-ios` target and default features disabled (the `pcre2`
default feature is a C dependency and is not cross-built; the Rust regex engine
is used instead), ldid-signs the binary (ad-hoc, no entitlements needed), and
uploads `ios-ripgrep` (`rg`, `ripgrep-manifest.json`, `SHA256SUMS`, static
validation evidence). `package-rootless.yml` consumes it when present and
installs `/var/jb/usr/bin/rg`; when absent the package is built without it.
Device execution remains **UNVERIFIED ON DEVICE**.

## 9. CI run log / evidence

This section records the actual GitHub Actions runs for this workflow. Every
entry links the run and states the exact failure/fix; nothing here is
fabricated.

The cancelled pending runs `41172259089` and `41172408512` were superseded in the
workflow's concurrency queue by newer commits on the same branch (GitHub keeps
only one pending run per group); they are not failures.

| Run | Commit | Status | Evidence / notes |
| --- | --- | --- | --- |
| [41171982508](https://github.com/Justintunsday/opencode-ios/actions/runs/41171982508) | `6cf042d` | **success** (first cold build) | configure gate 05:21:43Z -> 05:21:46Z; `make -j3` 05:21:46Z -> 06:38:24Z (**76m38s** cold, 3 vCPU `macos-15`); build path `make-executable` (`out/Release/node` produced by the normal executable target, `make` exit 0); node 60,598,384 bytes sha256 `53fc2a2237bc6954ef6f780c4d0031fbe67f9b257966f6672c9d7e6ec1201b78`; check_macho PASS iPhoneOS arm64 minos 14.0.0; otool -L only `/usr/lib/libSystem.B.dylib` + `/usr/lib/libc++.1.dylib`; cache saved (`ios-node-22.9.0-...-e1-<patch hash>`, ~3 min). Signed with the (now superseded) 4-key JIT entitlement set - see run 41173373500 for the corrected signing. |
| [41173373500](https://github.com/Justintunsday/opencode-ios/actions/runs/41173373500) | `e7fe917` | cancelled | was re-running from cache with the device-verified 2-key entitlement set; cancelled on 2026-10-31 because device testing showed the no-ICU runtime cannot parse the CLI bundle (missing `Intl`/`\p{}`). No artifact was consumed. |
| [41178496308](https://github.com/Justintunsday/opencode-ios/actions/runs/41178496308) | `08b4557` | run dispatched 06:54:57Z | ICU rebuild: `--with-intl=full-icu` (canned ICU 75 from `deps/icu-small`), patch 0002 (macOS SDK for ICU host tools during the iOS cross build), cache epoch 2 (cold, configure flags changed), ICU symbol/`v8_enable_i18n_support=1` hard gates, optional `ios-ripgrep` job. This is the artifact that fixes the CLI-blocking device failure recorded in §6.1. |

## 10. Limitations / unresolved issues

1. **ICU rebuild not yet device-verified** - the no-Intl 22.9.0 build was
   device-verified to run and its only CLI blocker was the missing
   `Intl`/`\p{}` support; the `--with-intl=full-icu` artifact is pending its own
   device run. All CI validation is static.
2. **No JIT / no WebAssembly** - see §6. CPU-bound JS will be slower; WASM
   features must be feature-detected by the CLI.
3. **Signing is ldid ad-hoc with the device-verified 2-key set**
   (`platform-application` + `com.apple.private.security.no-sandbox`). The
   entitlement requirement itself was verified on the target device (the old
   4-key JIT set is SIGKILLed). Re-sign the downloaded artifact on the device if
   needed (`scripts/ios-runtime/README.md`).
4. **Patch is a subset of PR #150** — the omitted workflow/gitignore/android
   hunks are not needed here; if nodejs-mobile merges PR #150 upstream, this
   repository should re-pin and drop the patch.
5. **First cold CI build is long (40–90 min)** — subsequent runs use the
   `out/Release` cache; a patch change intentionally misses the exact cache key
   but can reuse the previous tree via the prefix restore key.

## 11. Local reproduction

```sh
# macOS with Xcode 16.4, from a clone of this port repository:
git clone --depth 1 https://github.com/nodejs-mobile/nodejs-mobile.git nodejs-mobile
git -C nodejs-mobile fetch --depth 1 origin 106c51f95d55d1010de56a2ffd09bfb4ba819a47
git -C nodejs-mobile checkout FETCH_HEAD
for p in "$PWD"/patches/nodejs-mobile/*.patch; do git -C nodejs-mobile apply "$p"; done

python3.12 -m venv .venv && . .venv/bin/activate && pip install setuptools
bash scripts/build-ios-runtime.sh all

# verify the produced artifact:
python3 scripts/check_macho.py dist/ios-node-runtime/node --max-minos 16.1.1
xcrun otool -L dist/ios-node-runtime/node
ldid -e dist/ios-node-runtime/node
```
