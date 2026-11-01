# Runtime build: native iPhoneOS arm64 Node.js 22.9.0

Status: **DEVICE-VERIFIED** (v6, run 41265520491, patches 0001..0006): the
native iPhoneOS arm64 Node.js 22.9.0 runtime works on the target iPhone
(iPhone SE 2, iOS 16.1.1, Dopamine rootless) with JIT, WebAssembly, full ICU
(Intl/`\p{...}`), `node:sqlite`, TLS/`fetch` and `process.platform === "ios"`,
signed with the 2-key entitlement set. Device-required launcher flag:
**`--single-threaded`** (the mprotect-based W^X model needs V8's background
compiler/marking threads off; without it JIT/fetch can SIGBUS - see §6.5).
The runtime is CI-built and statically audited in `build-runtime.yml`; the
device run above was performed on real hardware (raw results in §9 device
verification detail), not on a hosted runner.
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
| `node` | the CLI runtime, Mach-O `MH_EXECUTE`, arm64, platform IOS, minos <= 16.1.1, with JIT + WebAssembly enabled and full ICU linked in (ECMA-402/`Intl` + V8 `\p{...}` escapes), ad-hoc signed with ldid |
| `entitlements.plist` | the exact entitlement set used when signing |
| `runtime-manifest.json` | pins, build path, observed static facts, runtime policy (JIT/WASM/Intl/platform) and audit evidence |
| `SHA256SUMS` | sha256 over the three files above |
| `validation-report.txt` | human-readable copy of the static validation evidence |

The artifact contract is defined in `docs/COORDINATION.md`; `package-rootless.yml`
consumes this artifact and installs `node` under
`/var/jb/usr/lib/opencode/runtime/node`.

**Launcher requirement (device-verified):** invoke the runtime with
`--single-threaded` (and `--experimental-sqlite` if the CLI needs `node:sqlite`).
The iOS JIT memory model toggles code-page permissions process-wide with
`mprotect`, so V8's background compiler/marking threads must be disabled to avoid
`SIGBUS` while a write scope holds a code range writable (see §6.5). The generated
`runtime-manifest.json` records this in `runtime_policy.launcher.required_flags`
(`--single-threaded`, `--experimental-sqlite`) and in
`device_verification.launcher_flags`; the launcher in the rootless package must
pass them.

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
| ICU host tools | built as macOS host-toolset binaries by patch 0002 (needed to generate the ICU data file during the iOS cross build) |
| V8 JIT / WebAssembly | enabled: no `--v8-options=--jitless`; `v8_enable_webassembly=1` via patch 0003 (Node 22.9 `fetch()`/undici needs wasm llhttp) |
| V8 iOS JIT memory | patches 0005+0006: **no MAP_JIT / no RWX on iOS**; V8's `RwxMemoryWriteScope` is implemented over `mprotect` RW<->RX toggling of registered code ranges (`RegisterIOSCodeRange`), device-probed as the only working executable-memory mechanism on iOS 16.1.1 |

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

### `0004-ios-jit-write-protect.patch` (this repository, not PR #150)

Fixes the v3 device SIGBUS on any generated-code execution (§6.4). Three changes:

- `deps/v8/src/base/build_config.h`: `V8_HAS_PTHREAD_JIT_WRITE_PROTECT` is
  enabled for `V8_HOST_ARCH_ARM64 && (V8_OS_MACOS || V8_OS_IOS)`. PR #150 had
  reduced it to macOS only, so on the iOS device V8's `RwxMemoryWriteScope`
  compiled to no-ops while V8 still reserved code space with `MAP_JIT`.
- `deps/v8/src/base/platform/platform-ios.cc`: `SetJitWriteProtected()` now
  resolves `pthread_jit_write_protect_np` with `dlsym(RTLD_DEFAULT)` at runtime
  instead of a direct call. The public iPhoneOS SDK does not export the symbol at
  link time; on iOS 14+ (jailbroken devices, `dynamic-codesigning` entitlement)
  it exists in libsystem and is what JIT-runner apps use. If the symbol is
  missing the thunk safely no-ops.
- `tools/v8_gypfiles/v8.gyp`: `platform-ios.cc` added to the `OS=="ios"`
  sources (V8's GN build already compiles it for `is_ios`; the gyp port in
  nodejs-mobile omitted it, so `SetJitWriteProtected` was not even linked in
  before).

**Historical note:** patch 0004 was originally paired with enabling
`V8_HAS_PTHREAD_JIT_WRITE_PROTECT` on iOS and a 4-key JIT entitlement set (v4).
Device testing proved that path cannot work on iOS (see §6.4), so the shipped
memory model is patch 0005; 0004 is reduced to the link-safe
`platform-ios.cc`/gyp additions, which are compiled out while the macro stays 0.

### `0005-no-map-jit-on-ios.patch` (this repository, not PR #150)

One change in `deps/v8/src/base/platform/platform-posix.cc`: the `MAP_JIT` flag
is added for `kNoAccessWillJitLater` only on macOS, not iOS
(`#if defined(V8_OS_DARWIN) && !defined(V8_OS_IOS)`), so V8 gets ordinary
`PROT_NONE` reservations instead of MAP_JIT reservations.

### `0006-v8-mprotect-wx-on-ios.patch` (this repository, not PR #150)

Implements V8's `RwxMemoryWriteScope` over per-range `mprotect`, the only
executable-memory mechanism available on iOS 16.1.1 (§6.4):

- `build_config.h`: `V8_HAS_PTHREAD_JIT_WRITE_PROTECT=1` on iOS arm64 so the
  write-scope machinery is compiled in and `SetJitWriteProtected` is called.
- `platform.h` / `platform-ios.cc`: a `RegisterIOSCodeRange` registry plus
  `SetJitWriteProtected(0)` -> `mprotect(..., PROT_READ|PROT_WRITE)` and
  `SetJitWriteProtected(1)` -> `mprotect(..., PROT_READ|PROT_EXEC)` for every
  registered range. No MAP_JIT, no APRR (`pthread_jit_write_protect_np` is
  absent on the device).
- `code-range.cc`: never request RWX on iOS (the kernel drops PROT_EXEC). The
  code-range reservation stays PROT_NONE; the re-embedded builtins blob is
  committed RW, copied, then RX.
- `memory-allocator.cc`: commit chunk headers RW (never executed), guard pages
  PROT_NONE, code bodies RW and registered for scope toggling.
- `wasm-code-manager.cc`: register wasm code-space reservations; commit wasm code
  RW then RX instead of RWX.

Trade-off: `mprotect` is process-wide, so while a thread holds a write scope the
whole registered range is briefly non-executable (unlike the thread-local macOS
APRR model). Correctness first; per-page granularity is possible follow-up work
if the device shows contention issues.

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

The recipe no longer passes `--v8-options=--jitless`, and patch 0003 restores
upstream `v8_enable_webassembly=1`, so the runtime has a working V8 JIT **and**
WebAssembly. This is mandatory: Node 22.9's built-in `fetch()`/undici
instantiates a wasm llhttp parser during startup, so the earlier jitless/no-wasm
runtime died on device with `ReferenceError: WebAssembly is not defined` (see
§6.3). The device-verified 2-key entitlement set is sufficient for JIT/WASM on
this jailbroken iPhone.

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

The plist is the **device-verified 2-key set**:

```xml
<key>platform-application</key><true/>
<key>com.apple.private.security.no-sandbox</key><true/>
```

- It is device-verified for the shipped runtime policy: a JIT-enabled reference
  Node 18 binary (plain-mprotect W^X, no MAP_JIT) runs JIT + WebAssembly on the
  target iPhone with only these two keys.
- No JIT-specific keys are needed because the shipped iOS memory model does not
  use MAP_JIT (patch 0005). JIT entitlements were tried on the MAP_JIT variants
  and never fixed the abort, and `dynamic-codesigning` etc. can cause SIGKILL at
  load on this device.
- The CI sign step hard-requires exactly these two keys and rejects
  `dynamic-codesigning`, `allow-jit`, `allow-unsigned-executable-memory` and
  `disable-library-validation`, so an artifact cannot silently ship a different
  entitlement policy.

Earlier device entitlement matrix (v2 interpreted-only binary, iPhone SE 2,
iPhone12,8, iOS 16.1.1 20B101, Dopamine rootless + ElleKit 1.2, 2026-10-31),
which is why `platform-application` + `no-sandbox` are mandatory:

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
- **No JIT / executable-memory entitlements** are needed even though JIT and
  WebAssembly are enabled: a JIT-enabled community Node binary was device-tested
  on this exact iPhone with only the same two keys and JIT/WASM worked (device
  evidence in §6.3). They are deliberately omitted, and the CI sign step rejects
  them if they ever reappear in the signed entitlements.

v3/v4 device evidence with JIT+WASM enabled but the MAP_JIT-based memory paths:
**every** entitlement set tried (2-key, +`dynamic-codesigning`, +`allow-jit`,
4-key, 6-key, 9-key) still failed (v3 SIGBUS on generated code, v4
SIGTRAP/FatalProcessOOM in `CodeRange::InitReservation`). That proved the crashes
were V8 memory-permission bugs, not signing; patch 0005 removes MAP_JIT on iOS
and restores the 2-key policy.

If the device loader rejects the signature, re-sign on device with the bundled
`entitlements.plist` (see `scripts/ios-runtime/README.md`). This is a
jailbreak-rootless scenario; it is not a claim of stock-iOS/App-Store
compatibility.
## 6. Runtime policy (what the CLI engineer can rely on)

- **`process.platform === "ios"`.** `node.gyp` defines
  `NODE_PLATFORM="<(OS)"` for the executable and `libnode` targets;
  `configure.py` sets `OS=ios` for `--dest-os=ios`; `src/node_metadata.cc`
  initialises the metadata platform from `NODE_PLATFORM`. The runtime therefore
  reports `ios`, not `darwin`. This was confirmed **on device**
  (`process.platform === "ios"` for the 22.9.0 build) and is recorded in
  `runtime-manifest.json` → `runtime_policy.process_platform`.
- **JIT enabled (default V8 JIT), with iOS-specific memory handling and a
  launcher requirement.** The build does not pass `--v8-options=--jitless`. On
  iOS, V8 must not use `MAP_JIT` and must not request RWX pages; its write scopes
  toggle registered code ranges RW<->RX with `mprotect` (patches 0005+0006,
  §6.4). Because that toggle is process-wide, the launcher must pass
  `--single-threaded` (§6.5); device-verified with it: JIT loops, wasm, Intl and
  `fetch` all work.
- **WebAssembly enabled.** `v8_enable_webassembly=1` (patch 0003 restores upstream
  behaviour). This is **required**, not optional: Node 22.9's built-in
  `fetch()`/undici instantiates a wasm llhttp parser at startup, so a no-wasm
  runtime cannot run the CLI at all (§6.3).
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

Corroboration on the same device: the community reference Node 18.20.4 iOS
binary reports `{"ver":"v18.20.4","icu":"74.2","intl":"object"}`, i.e. an
ICU-enabled Node runs on this exact hardware/jailbreak. (That reference binary
was built *on-device*, which is why it embeds ICU; our cross-compiled build links
the frozen ICU statically instead.) Measured size impact: the `node` binary grew
from 60,598,384 bytes (no Intl) to **97,286,800 bytes** with full ICU (+36.7 MB);
expect ~+10 MB on the compressed `.deb` and ~150 MB installed total, fine on the
target device.

### 6.2 ICU audit heuristic (important for maintainers)

Node builds ICU with `visibility=hidden`, so ICU symbols are **local** in the
final Mach-O (and some link configurations strip the symbol table). A
global-symbol lookup like `nm -gU` can therefore find nothing even when ICU is
present. CI's audit is deliberately multi-signal and fails only if the build
config denies i18n or every signal indicates absence:

1. `config.gypi` reports `'v8_enable_i18n_support': 1` (hard requirement), and
2. at least one of: `nm` (default, local symbols included) finds ICU symbols;
   `strings -a` finds an `ICU <major>.<minor>` version string; `strings -a` finds
   the `icudt<major>` data name; the `node` binary grew past 70 MB (the no-Intl
   baseline was 60,598,384 bytes).

All signals are written to `icu-evidence-<stage>.txt` in the artifact.

One more CI hazard worth knowing: `nm <binary> | grep -q ...` is **flaky under
`set -o pipefail`** - `grep -q` exits on the first match, `nm` then dies with
SIGPIPE (exit 141), and the pipeline reports failure even though the pattern was
found. The first full-ICU run failed its audit for exactly this reason (the build
had ICU). The script now writes `nm` output to `nm-symbols-<stage>.txt` first and
greps that file, so every signal check is pipeline-free.

### 6.3 Why WebAssembly is required (device evidence)

The first ICU-enabled (but jitless/no-wasm) 22.9.0 runtime started on the target
iPhone, but every CLI command failed during startup:

```
node:internal/deps/undici/undici:5578
    mod = await WebAssembly.compile(llhttpWasmData || require_llhttp_wasm());
ReferenceError: WebAssembly is not defined
    at lazyllhttp ... at lib/global.js
```

Node 22.9's built-in `fetch()`/`undici` instantiates a wasm llhttp parser as soon
as the HTTP stack is touched, which the OpenCode bundle does at module load. No
CLI patch can work around a missing `WebAssembly` global. Precedent packages are
no guide here: they run simple JS, not the undici stack.

Same-device proof that JIT+WASM is allowed: a JIT-enabled community Node 18
binary, re-signed with only the 2-key entitlement set, runs on this iPhone
(`typeof WebAssembly === "object"`, `new WebAssembly.Module(...)` succeeds, a JIT
loop executes). Therefore the runtime now ships with JIT + WebAssembly enabled
and the 2-key entitlements are kept unchanged.

### 6.4 iOS JIT memory handling: the v3 SIGBUS and patch 0004

v3 (JIT + WebAssembly enabled) started on the device (`node --version` worked)
but **any** generated JS/wasm code execution crashed:

```
EXC_BAD_ACCESS / SIGBUS (exit code 138), KERN_PROTECTION_FAILURE
faulting region: Memory Tag 255 ... [208K] rw-/rwx  (max rwx, current rw-)
```

i.e. the CPU jumped into a JIT code page that V8 had left read-write and never
flipped to executable. Re-signing the same binary with 2-key,
+`dynamic-codesigning`, +`allow-jit`, a 6-key and a 9-key set all still trapped,
so it was independent of entitlements.

Root cause (V8 12.4 in the pinned tree):

- `OS::Allocate(kNoAccessWillJitLater)` reserves code space with `MAP_JIT` under
  `V8_OS_DARWIN` (which includes iOS).
- Flipping `MAP_JIT` pages between writable and executable goes through the
  `RwxMemoryWriteScope` machinery, which compiles to **no-ops** unless
  `V8_HAS_PTHREAD_JIT_WRITE_PROTECT == 1`.
- PR #150 had reduced that macro to macOS only, so on the iOS device the scope
  was a no-op: pages stayed `rw-` while V8 executed them -> SIGBUS.
- `platform-ios.cc` already had an iOS `SetJitWriteProtected` implementation, but
  it direct-called `pthread_jit_write_protect_np`, which the public iPhoneOS SDK
  does not export at link time, and `v8.gyp` did not even compile that file for
  `OS=="ios"`.

v4 tried the macOS model instead: patch 0004 enabled
`V8_HAS_PTHREAD_JIT_WRITE_PROTECT` on iOS (so `RwxMemoryWriteScope` would not be
compiled out) and resolved `pthread_jit_write_protect_np` via `dlsym`. That also
fails on the device, earlier and differently:

```
EXC_BREAKPOINT / SIGTRAP (exit code 133)
V8::FatalProcessOutOfMemory <- v8::internal::Heap::SetUp <- Isolate::Init
reason: CodeRange::InitReservation -> SetPermissions(base, 128MB, kReadWriteExecute) denied
```

iOS 16 denies RWX `mprotect` on a MAP_JIT reservation, so V8 aborts during
isolate startup; full 9-key entitlements do not change that.

**v5 (shipped): do not use MAP_JIT on iOS.** Patch 0005 skips `MAP_JIT` for iOS
in `platform-posix.cc`; V8 then uses ordinary `PROT_NONE` reservations and plain
`mprotect` W^X (kReadWrite to write, kReadExecute to run) for JIT and wasm code -
exactly the V8 10.2 / Node 18 memory model. The reference JIT-enabled Node 18
binary runs JIT + WebAssembly on this exact iPhone with the 2-key entitlement
set, which is why the shipped runtime reverts to `V8_HAS_PTHREAD_JIT_WRITE_PROTECT
= 0` on iOS, no MAP_JIT, and the 2-key plist. CI hard-gates that the
`platform-posix.cc` guard is present and that the linked binary does NOT contain
the `pthread_jit_write_protect_np` string (i.e. the MAP_JIT path is really off).

#### Device memory-permission probe (definitive, iPhone SE 2 / iOS 16.1.1)

A diagnostic iPhoneOS arm64 probe executable (CI artifact `ios-jit-probe`,
ldid-signed with the 2-key set, run as uid 501 on the device) measured the
kernel's memory-permission behaviour directly. This is why v5 is the only viable
model on this hardware:

```
plain_then_mprotect_rwx: mmap=ok mprotect=0 errno=0          <- plain mapping mprotect RWX SUCCEEDS
mmap_jit_rwx: FAIL errno=22                                  <- MAP_JIT mmap denied (EINVAL)
plain_write_rx_exec: mprotect_rx=0 exec=0 errno=0            <- W^X write->RX->execute WORKS
mapjit_reserve_mprotect_rwx_exec: mprotect=-1 exec=-1 errno=22 <- MAP_JIT reservation unusable
pthread_jit_write_protect_np: absent                         <- APRR toggle API absent on iOS 16.1.1 device
```

So on this device: ordinary (non-MAP_JIT) mappings support the W^X
write->RX->execute sequence, while MAP_JIT reservations and the
`pthread_jit_write_protect_np` toggle are unavailable. (An earlier probe also
showed that requesting RWX silently drops PROT_EXEC, hence no RWX requests
anywhere on iOS.) This confirms no entitlement set can make the v3/v4 MAP_JIT
paths work (full 9-key also failed), and it dictates the v6 design.

**v5 (no MAP_JIT, but no write-scope implementation either)** removed MAP_JIT
(patch 0005) but left `V8_HAS_PTHREAD_JIT_WRITE_PROTECT=0`, so the write scopes
were no-ops and V8 still requested RWX code pages in places - which loses
PROT_EXEC on iOS.

**v6 (shipped design, patches 0005+0006)**: V8's `RwxMemoryWriteScope` machinery
is compiled in (`V8_HAS_PTHREAD_JIT_WRITE_PROTECT=1` on iOS arm64) and
`SetJitWriteProtected` is implemented with `mprotect` over ranges registered via
`RegisterIOSCodeRange` (JS code chunks + wasm code spaces). Every write scope
toggles RW (writing) / RX (executing); no RWX permission is ever requested and
MAP_JIT is never used. CI hard-gates the source call sites and that the linked
binary contains `RegisterIOSCodeRange` (and does not reference the absent
`pthread_jit_write_protect_np`).

### 6.5 Launcher requirements (device-verified)

The shipped v6 runtime is **device-verified to work** when the launcher passes:

```
--single-threaded [--experimental-sqlite]
```

Observed on the target iPhone (iPhone SE 2, iOS 16.1.1, Dopamine rootless,
2-key-signed runtime, node sha256 `cf707ebe...`):

- **default (multithreaded):** `--version` OK, plain JS OK, wasm
  compile+instantiate OK, `Intl`/ICU 75/`\p{L}` OK - but a JIT loop and built-in
  `fetch` each trap with `SIGBUS` (exit 138). Rationale: the mprotect
  whole-range toggle is process-wide while macOS' APRR (used upstream) is
  per-thread, so a background compiler/marking thread can execute code from a
  range that another thread temporarily made RW.
- **`--single-threaded` (or `--no-concurrent-recompilation`):** JIT loop rc=0,
  `fetch("https://...")` rc=0 (HTTP 200), wasm OK - no further crashes. No
  entitlement changes were needed.
- Full OpenCode CLI matrix on device with the Node 22 bundle + `--single-threaded`
  + `--experimental-sqlite`: `--version`, `--help` (now complete: full ICU makes
  `Intl.Segmenter` work), `debug paths`, `debug config`, `models`, `auth list`,
  `session list` (native `node:sqlite` DB with WAL) - all rc=0. A mock-provider
  end-to-end agent turn rc=0 executed the shell tool on the device (marker file
  written, git version captured) and the mock saw `GET /api/v1/models` plus
  three chat completions with `toolResult=true`.

Trade-off of `--single-threaded`: V8 runs without its background
compiler/marking/GC helper threads, so optimization throughput is lower and GC
may be less concurrent; functionally the CLI works (matrix above). Per-page
mprotect granularity is possible future work if the requirement proves too
costly, but it is not needed for the shipped runtime.

### 6.6 Interactive interface on iOS (device-verified constraint)

The CLI's interactive modes (`opencode`, `opencode mini`) run on an iOS TTY. A
full OpenTUI TUI is **not possible on this runtime**, and porting OpenTUI does
not change that (verified facts, 2026-11-01):

- `@opentui/core` 0.8.0's Node binding loads its native Zig core through Node
  **`>= 26.4.0` `--experimental-ffi` / `node:ffi`**, and native renderer packages
  exist only for darwin/linux/win32.
- The device-verified runtime is **Node 22.9.0**, which has no
  `--experimental-ffi` and no `node:ffi` (device-confirmed: `bad option:
  --experimental-ffi`).

Therefore iOS gets a **pure-JS, line-based interactive REPL** for `opencode` /
`opencode mini` on TTYs (streaming assistant text, tool activity lines,
`/new` `/exit` `/help`, Ctrl-C cancels the current turn, session continuity),
while non-TTY invocations keep the existing guidance output. This is a
CLI-bundle change only: no runtime or launcher change and no rebuild is needed.

**Future work (not planned now):** a real TUI would need a Node 26+ iPhoneOS
runtime: a nodejs-mobile Node 26 branch, a V8 14 port, and re-doing the
`0001..0006` build-fix/W^X patch series against that V8 (plus the same device
memory-model work). Only then could OpenTUI's FFI binding be revisited.

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
- **Packager capability-gate compatibility:** `package-rootless.yml` inspects
  `runtime-manifest.json` (`packaging/verify/port_verify.py
  _check_runtime_profile`) and rejects runtimes whose profile cannot run the CLI.
  The generated manifest must therefore keep `runtime_policy.webassembly` and
  `runtime_policy.v8_jit` strings starting with `enabled:` and free of the words
  `disabled`/`jitless`, declare `build.configure_flags` with
  `--with-intl=full-icu` and without `--v8-options=--jitless`, and set
  `runtime_policy.intl.mode=full-icu` + `icu_version`. The package step now
  hard-fails on any drift via an inline `check_manifest_profile_gate`; this was
  the reason a v3 run was cancelled and re-pushed (see §9).
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
Device execution remains **UNVERIFIED ON DEVICE**. Note that the Rust
`aarch64-apple-ios` link emits the legacy `LC_VERSION_MIN_IPHONEOS` load command
instead of `LC_BUILD_VERSION`, so the vtool check accepts either; the strict
platform/arch/minos validation is done by `scripts/check_macho.py`.

Green build evidence (run 41193603642): `ios-ripgrep` contains `rg` 6,624,992
bytes sha256 `6cc1cea8bc1dbe159f026419d50e404eda6ee1556808e8bbefb37cde9e121b7b`,
Mach-O arm64 platform IOS, ldid ad-hoc signed (no entitlements), with
`ripgrep-manifest.json` and `SHA256SUMS`.

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
| [41178496308](https://github.com/Justintunsday/opencode-ios/actions/runs/41178496308) | `08b4557` | **failure (audit heuristic, build OK)** | ICU rebuild with `--with-intl=full-icu`: configure accepted the canned ICU 75 source (`Using floating patch tools/icu/patches/75/.../genccode.c`); `make -j3` ran 06:58:45Z -> 08:18Z and produced `out/Release/node` with ICU static libraries linked; **the run then failed only in CI's ICU symbol audit** (`ERROR: binary does not appear to contain ICU symbols`), because ICU is compiled with `visibility=hidden` and the symbols are local in the final binary while the audit used a global-symbol-style grep. Fixed by the multi-signal audit described in §6.2. The `out/Release` tree was cached (failed-run cache save) so the rerun is incremental. |
| [41184686029](https://github.com/Justintunsday/opencode-ios/actions/runs/41184686029) | `e803c8b` | **success** (ICU artifact) | exact `out/Release` cache hit from the failed run, so `make` was incremental (run 08:27:57Z -> 08:39:01Z); ICU audit passed with 4/4 signals; **node 97,286,800 bytes, sha256 `790cb43296dbed51a6375d82eca5a5a178808ca9fb3fecbabbd2daf547adaac2`**; `v8_enable_i18n_support=1`, `icu_small=false`, ICU 75; `nm` local symbols `_icudt75_dat`, `_u_strToUpper_75`, `_u_getPropertyEnum_75`; otool -L still only `/usr/lib/libSystem.B.dylib` + `/usr/lib/libc++.1.dylib`; 2-key entitlement signature. The optional `ios-ripgrep` job failed in that run only on the too-strict `platform IOS` vtool grep (the binary uses the legacy `LC_VERSION_MIN_IPHONEOS` command; `check_macho.py` had PASSed); job-level `continue-on-error` kept the run/artifact-consumption green, and §8 has the fix. |
| [41185874714](https://github.com/Justintunsday/opencode-ios/actions/runs/41185874714) | `72da8ac` | cancelled | ICU-audit SIGPIPE/`pipefail` hardening + ripgrep vtool fix; cancelled on 2026-10-31 to free the macOS runner for the v3 (JIT+wasm) rebuild. The hardening is on `main` and ships with v3. |
| [41193511671](https://github.com/Justintunsday/opencode-ios/actions/runs/41193511671) | `1df4b27` | cancelled (manifest wording) | first v3 dispatch (JIT+wasm). Cancelled ~2 min in, before any compile, because `runtime_policy.v8_jit` still contained the string `--v8-options=--jitless`; the packager capability gate fails any policy text containing `jitless` (§7), so the artifact could never be packaged. Replaced by `c20bf63` below; the binary build inputs were unchanged. |
| 41205805269 | `b47963a` | failure (marker check) | first v4 push: `require_patched_source` still looked for the PR#150 comment line that patch 0004 replaces, so normalize-cache aborted before build; fixed in `dfbc093` with one stable marker per patch (0001..0004) |
| [41207449703](https://github.com/Justintunsday/opencode-ios/actions/runs/41207449703) | `dfbc093` | **success (v4)** | runtime v4: patches 0001..0004, JIT+WebAssembly+full-icu, iOS JIT W^X fix. `make` 14:06Z -> ~16:05Z (~119 min; build_config.h is a V8-wide header so the macro change recompiled most V8/node sources even with the cache). Both jobs success incl. optional `ios-ripgrep`. **node 106,842,032 bytes sha256 `48eecd595ad94c433dafc5573bd528f4a947c7fe5e57f59cedd139890839ec66`**. Static gates: check_macho PASS iPhoneOS arm64 minos 14.0; vtool platform IOS; otool -L only libSystem/libc++; ICU 3/4 signals; WebAssembly 2/3 signals; new hard gate "binary references pthread_jit_write_protect_np" PASS; signed entitlements exactly the tentative 4-key set (platform-application + no-sandbox + dynamic-codesigning + allow-unsigned-executable-memory); packager-gate manifest self-check PASS. |
| [41193603642](https://github.com/Justintunsday/opencode-ios/actions/runs/41193603642) | `c20bf63` | **success (v3 candidate)** | **runtime v3: JIT + WebAssembly enabled.** Patch 0003 restores `v8_enable_webassembly`, `--v8-options=--jitless` removed, full-icu/2-key entitlements unchanged; adds a V8 WebAssembly audit (config + no-`--jitless` + nm/strings signals), gate-compatible manifest policy text with iPhone SE 2 device evidence, and an inline `check_manifest_profile_gate` (printed *"runtime-manifest.json capability profile is packager-gate compatible"*). Cold rebuild 10:45:16Z -> 12:40Z (~115 min on 3 vCPU with wasm+ICU); both jobs success, including optional `ios-ripgrep` (rg sha256 `6cc1cea8...`). **node 106,822,656 bytes sha256 `5808d7027cdfcbb138668243fd61b221efcc810e67d5411da15b432a6f4c1876`**; `[signed] WebAssembly present: enabled (2/3 signals); JIT enabled (no --jitless)`; `[signed] ICU present: full-icu statically linked (3/4 signals)`; otool -L still only libSystem/libc++; 2-key signature revalidated. This is the artifact handed to device verification (expected: `process.versions.icu` ~75.x, `typeof Intl==="object"`, `\p{L}` works, `typeof WebAssembly==="object"`, built-in fetch initialises). |

### Device verdicts for the CI-green builds (device evidence, 2026-10-31)

The v6 artifact is device-verified (see detail below and §6.5); the table records
how each CI-green build fared on the real iPhone and which patch it forced.

| Build | Device result |
| --- | --- |
| v2 no-Intl (run 41171982508) | runs (`node --version`, `process.platform=="ios"`, fs/sqlite/TLS/child_process OK), but CLI rejected: `Intl` undefined + `\p{...}` regexp `SyntaxError`. Drove patch 0002 / full-icu. |
| ICU build (run 41184686029) | runs, ICU present, but CLI rejected: `ReferenceError: WebAssembly is not defined` from Node `fetch`/undici wasm llhttp. Drove patch 0003 / JIT+wasm. |
| v3 (run 41193603642) | starts; `--version` OK; **any JS/wasm code execution traps with SIGBUS (138) / EXC_BAD_ACCESS**, regardless of entitlement set. Drove patch 0004 (iOS JIT W^X). |
| v4 (run 41205805269) | **CI failure before build**: the workflow's patch-series marker check (`require_patched_source`) still looked for the old PR#150 comment line that patch 0004 replaces in `build_config.h`, so normalize-cache aborted. Fixed in `dfbc093` (one stable marker per patch 0001..0004), re-run as 41207449703. |
| v4 (run 41207449703) | **device-rejected**: node 106,842,032 bytes sha256 `48eecd59...`, 4-key signed, MAP_JIT + `V8_HAS_PTHREAD_JIT_WRITE_PROTECT=1`. Device: EXC_BREAKPOINT / SIGTRAP (exit 133), `v8::base::OS::Abort` <- `FatalOOM` <- `V8::FatalProcessOutOfMemory` <- `Heap::SetUp`; exact site `CodeRange::InitReservation` (src/heap/code-range.cc) doing `SetPermissions(base, 128MB, kReadWriteExecute)` on the MAP_JIT code range. Full 9-key entitlements also fail. Device probe then proved `mmap(MAP_JIT)` is denied (EINVAL) and `pthread_jit_write_protect_np` is absent on iOS 16.1.1. Drove patch 0005 (no MAP_JIT on iOS). |
| v5 (run 41219489179) | **device-rejected**: no MAP_JIT (patch 0005) but the write-scope machinery was still compiled out, so V8 requested RWX code pages and iOS dropped PROT_EXEC -> same SIGBUS/trap class as v3. Confirmed by the device memory matrix; drove patch 0006. |
| **v6 (run [41265520491](https://github.com/Justintunsday/opencode-ios/actions/runs/41265520491))** | **DEVICE-VERIFIED WORKS** (with `--single-threaded`). CI: patches 0001..0006; V8's write scopes implemented over mprotect RW<->RX toggling of registered code ranges (JS code chunks + wasm spaces), no MAP_JIT, no RWX requests, 2-key entitlements. `make` 02:35Z -> ~04:10Z (~95 min, restored cache + V8-wide rebuild). **node 106,842,800 bytes sha256 `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`**, 2-key signed (ldid -e verified). CI audits: check_macho PASS iPhoneOS arm64 minos 14.0; otool -L only libSystem/libc++; ICU 3/4 signals; WebAssembly 2/3; `[signed] JIT memory model OK: mprotect RW<->RX toggling over registered code ranges, no MAP_JIT, no RWX requests, 2-key entitlements`; packager-gate self-check PASS; optional `ios-ripgrep` green. Device: 2-key signature accepted; default multithreaded runs `--version`/plain JS/wasm/Intl but SIGBUS (138) on JIT loop + `fetch`; with `--single-threaded` (or `--no-concurrent-recompilation`) JIT loop rc=0, `fetch` rc=0 HTTP 200, wasm OK; full CLI matrix rc=0 including `--help` (Intl.Segmenter), `session list` on native node:sqlite (WAL), and a mock-provider agent turn whose shell tool executed on the iPhone. `process.platform === "ios"` device-confirmed. See §6.5 and the detail below. |

| [41273024931](https://github.com/Justintunsday/opencode-ios/actions/runs/41273024931) | `c33a079` | **success (cached guidance rerun)** | runtime build files changed only for documentation/manifest guidance; exact `out/Release` cache hit + no-op make reproduced the same binary: **node 106,842,800 bytes sha256 `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`** (the device-verified sha). Manifest now records `device_status: DEVICE-VERIFIED (runtime; launcher must pass --single-threaded)`, a `device_verification` block (verified, verified_sha256, device, launcher_flags, evidence) and `runtime_policy.launcher.required_flags = ["--single-threaded","--experimental-sqlite"]` (with optional `--no-concurrent-recompilation`). This is the run packagers should resolve for the Node 22 runtime; optional `ios-ripgrep` also green. |

### v6 device verification detail (2026-11-01)

Raw device evidence for the v6 runtime (artifact from run 41265520491, node
sha256 `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`,
2-key ldid signature accepted by the loader, uid 501 `mobile`):

| Check | Result |
| --- | --- |
| `node --version` / plain JS | rc=0 (`v22.9.0`) |
| `process.platform` / `process.arch` | `ios` / `arm64` (device-confirmed) |
| ICU / `Intl` / `\p{L}` | ICU 75; `typeof Intl === "object"`; `\p{L}` test true; `Intl.Segmenter` works |
| WebAssembly | compile + instantiate minimal module OK |
| JIT loop, default threads | **SIGBUS (138)** (background compiler/marking thread race) |
| JIT loop, `--single-threaded` | rc=0 |
| `fetch("https://...")`, default threads | **SIGBUS (138)** |
| `fetch("https://...")`, `--single-threaded` | rc=0, HTTP 200 |
| `node:sqlite` (native, `--experimental-sqlite`) | works; DB with WAL |
| OpenCode CLI matrix (`--version`, `--help`, `debug paths`, `debug config`, `models`, `auth list`, `session list`) with Node22 bundle + `--single-threaded` + `--experimental-sqlite` | all rc=0; full `--help` works (full-ICU fixes `Intl.Segmenter`) |
| Mock-provider end-to-end agent turn | rc=0; shell tool executed on device, marker file written (`opencode-ios-e2e-ok`, user `mobile`, `git version 2.39.1`); mock saw `GET /api/v1/models` + 3 chat completions with `toolResult=true` |

Conclusion: the runtime is device-functional; the launcher MUST pass
`--single-threaded` (§6.5). No entitlement changes were required (2-key set
accepted for JIT+wasm+fetch).

| [41291057088](https://github.com/Justintunsday/opencode-ios/actions/runs/41291057088) | `1cb50e4` | **success (cold-record rerun)** | workflow_dispatch on main after the corrupt build cache was deleted: clean cold build (~115 min), all audits and signing passed, both artifacts (`ios-node-runtime`, `ios-ripgrep`) uploaded. Cold rebuild is not bit-reproducible: node **106,842,800 bytes sha256 `692ee8a991d723c81d3d48d39e950efd1f97487c21a838327f7ba5f4e854b408`** (differs from the device-verified `cf707ebe…`). The manifest correctly reports `device_status: UNVERIFIED ON DEVICE (binary differs from the device-verified build)` with `device_verification.verified=false`, so the device-verification claim is never applied to a different binary; launcher flags stay declared. For packaging, the pinned device-verified runtime remains **41273024931 / node `cf707ebe…`**. This run makes the latest build-runtime run on main green (the earlier red run 41285699804 was the corrupt-cache incident below). |

### Related fallback runtime: Node 18 (build-runtime-node18.yml)

A separate `build-runtime-node18.yml` / `scripts/build-ios-runtime-node18.sh`
builds a Node 18.20.4 / V8 10.2 fallback runtime (`ios-node18-runtime`,
documented as the alternative, **UNVERIFIED ON DEVICE**; node22+v6 is primary).
Latest green run: [41285669688](https://github.com/Justintunsday/opencode-ios/actions/runs/41285669688)
- node 81,511,888 bytes sha256 `74e1c5c3ca1e8d5c1430552706cf21151941dfd6fa97a759345aea98aa247bea`,
2-key signed, iPhoneOS arm64 minOS 13.0, manifest now packager-gate-correct
(vtool-derived `min_ios_from_vtool`, no otool header in `linked_dylibs`,
`v8_jit`/`webassembly` "enabled:" text without forbidden words, runtime-manifest
uploaded). Node 18 builds are not bit-reproducible (same inputs produced
`467511b5…`, `1f29f7fb…`, `74e1c5c3…`), so always package the SHA256SUMS of the
chosen run.

### Cache incident (2026-11-01, node22 build cache)

A docs-only rerun (41285699804) failed because the 16.14 GiB `out/Release`
action cache had become corrupt in the cache store: gtar reported "Illegal byte
sequence" and extracted only partially (runner disk was fine), after which the
normalize step ran against a corrupted checkout. The workflow now deletes any
partially extracted `nodejs-mobile/out/Release` when `cache-hit != "true"` and
falls back to a clean cold build; the corrupt 16.14 GiB cache entry (and a stale
22 MB leftover) were deleted, returning the repository to ~7.5 GiB of the 10 GiB
action-cache budget. This does not affect the device-verified artifact/package:
run 41273024931 and the published `.deb` are unchanged.

## 9.1 Downstream consumption (packaging integration)

The v3 runtime artifact was consumed end-to-end by `package-rootless.yml`:

| Fact | Value |
| --- | --- |
| package run | [41202900005](https://github.com/Justintunsday/opencode-ios/actions/runs/41202900005) - **success** |
| resolved runtime run | 41193603642, artifact `ios-node-runtime`, head `c20bf63` |
| resolved optional ripgrep | 41193603642, artifact `ios-ripgrep` |
| resolved CLI run | 41192939688, artifact `opencode-cli-node-ios` |
| packager capability gate | `Runtime build/capability profile is usable by the CLI` - **PASS** (this is the gate that rejects no-ICU / no-wasm / jitless runtimes) |
| package artifact | `OpenCode-iOS-rootless` 52,953,183 bytes (.deb + SHA256SUMS + package-report.json) |

The **v6** runtime (device-verified with `--single-threaded`) was then packaged:

| Fact | Value |
| --- | --- |
| package run | [41274221353](https://github.com/Justintunsday/opencode-ios/actions/runs/41274221353) - **success** |
| resolved runtime run | 41273024931 (head `c33a079`), node sha256 `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce` (the device-verified sha) |
| resolved CLI run | 41273112229, artifact `opencode-cli-node-ios` |
| CI package validation | 47 PASS / 0 FAIL / 1 SKIP; `runtime.build-profile` PASS; `runtime.entitlements-policy` PASS; launcher checks PASS (version/help/args-forwarded); `ios-jit-shim` not shipped (normal launch) |
| verification/toolchain | port-verification 41274218225 success; toolchain smoke 41274218101 success |

Earlier iterations (v3/v4/v5) were all rejected on device (SIGBUS / SIGTRAP / RWX
requests, §6.4). The packaged `.deb` from 41274221353 then passed packaged device
acceptance: installation, `--single-threaded` launcher path, full CLI matrix and
an E2E agent turn (release v2.2.5-ios.2 device-verified; subsequent releases
v2.2.5-ios.3+ are built from the same device-verified v6 runtime). The runtime
manifest declares the launcher flags and the device-verified binary sha
(`device_verification` block) so packagers can gate on it.

## 10. Limitations / unresolved issues

1. **Device-verified with a launcher flag** - v6 is device-verified on the
   target iPhone but ONLY with `--single-threaded` (or
   `--no-concurrent-recompilation`); the launcher must pass it (§6.5). The
   packaged `.deb` still needs its own device acceptance pass (install, launcher
   flag, CLI matrix).
2. **JIT + WebAssembly enabled; iOS JIT memory model is patches 0005+0006** -
   see §6.3/§6.4/§6.5. Device probing proved MAP_JIT and
   `pthread_jit_write_protect_np` are unavailable on iOS 16.1.1 and only explicit
   mprotect W^X works, so V8's write scopes toggle registered ranges RW<->RX with
   no RWX requests. Trade-off: the process-wide toggle requires
   `--single-threaded` (no V8 background compiler/marking threads; lower
   optimization throughput, functionally fine). Per-page mprotect granularity is
   possible future work if this becomes a bottleneck.
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
