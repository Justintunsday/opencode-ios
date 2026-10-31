# Running a large Node.js CLI natively on ARM64 jailbroken iOS 16 (Dopamine rootless, ellekit)

Research date: 2026-10-31. Target: native arm64, **no emulation, no remote execution**.

## 0. Bottom line

A native ARM64 `node` CLI on jailbroken iOS is **not hypothetical — it already exists and ships**.
Two independent, verifiable routes:

| Route | What you get | Effort | Confidence |
|---|---|---|---|
| **A. Use the existing prebuilt** `imcynic/nodejs-ios` | Real Node **18.20.4** `iphoneos-arm64` `.deb`; verified Mach-O ARM64 `MH_EXECUTE`, min iOS 13.0, SDK 16.2 | minutes | High (binary inspected byte-level) |
| **B. Build `out/Release/node` yourself** from `nodejs-mobile` source | Same Node 18.20.4, binary you control/sign | ~1–2 h on a macOS runner | High (upstream CI recipe + CI timings) |
| C. Reuse Procursus `nodejs` recipe (Node 17.0.1 / 16.13.0 from `1Conan/node`) | Older Node, but a documented in-tree iOS CLI build | medium | Medium — **package is not currently published** (verified) |
| D. Bun / Deno | **Not viable on iOS 16** | — | High |

Key correction to a common premise: **nodejs-mobile's own release artifacts contain no CLI at all** — but its **source tree does build one** (`out/Release/node`). That distinction is the crux of this report.

---

## 1. nodejs-mobile — versions, build scripts, CLI vs framework, releases

Repo: [`nodejs-mobile/nodejs-mobile`](https://github.com/nodejs-mobile/nodejs-mobile) — "Full-fledged Node.js on Android and iOS".
Metadata (via `gh api`, 2026-10-31): **888 stars, 177 forks, 46 open issues, not archived**, default branch `main`.

### 1.1 Releases — prebuilt assets are framework-only (verified)

`gh release list` shows the release line stops at **v18.20.4 (2024-10-07)**:

| Tag | Date |
|---|---|
| v18.20.4 | 2024-10-07 |
| v18.17.3 | 2024-09-23 |
| v18.17.2 | 2023-10-17 |
| v18.17.1 | 2023-10-13 |
| v16.17.1 | 2023-02-21 |
| v16.17.0 | 2023-01-26 |

The iOS asset `nodejs-mobile-v18.20.4-ios.zip` is **51,492,431 bytes** (7,560 downloads). I downloaded and enumerated it: **536 entries**, and the complete top level is:

```
NodeMobile.xcframework/Info.plist
NodeMobile.xcframework/ios-arm64/NodeMobile.framework/{Headers,Info.plist,Modules,NodeMobile}
NodeMobile.xcframework/ios-arm64_x86_64-simulator/NodeMobile.framework/{...}
include/node/**            (headers only)
```

* `ios-arm64` framework binary: **54,959,120 bytes**
* simulator slice: **115,463,536 bytes**
* **There is no `bin/`, no `node` executable, no CLI.** It is a static framework + headers. Confirmed.

Release notes confirm scope: iOS assets are `iPhone arm64`, `Simulator arm64`, `Simulator x86_64`. Embedded versions: `node 18.20.4`, `v8 10.2.154.26-node.37`, `modules 108`, `napi 9`, `openssl 3.0.13+quic`, `uv 1.44.2`.

### 1.2 The iOS build script — exact recipe

[`doc_mobile/BUILDING.md`](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/doc_mobile/BUILDING.md) documents only the framework path. The real flags are in [`tools/ios_framework_prepare.sh`](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/tools/ios_framework_prepare.sh), `build_for_arm64_device()`:

```sh
GYP_DEFINES="target_arch=arm64 host_os=mac target_os=ios"
./configure \
  --dest-os=ios \
  --dest-cpu=arm64 \
  --with-intl=none \
  --cross-compiling \
  --enable-static \
  --openssl-no-asm \
  --v8-options=--jitless \
  --without-node-code-cache \
  --without-node-snapshot
make -j$(getconf _NPROCESSORS_ONLN)
```

Then it copies only `lib*.a` into `tools/ios-framework/NodeMobile.xcodeproj` and `xcodebuild`s the framework.

**Two facts that matter:**

1. `--v8-options=--jitless` — the *default* nodejs-mobile iOS framework is built **with V8 JIT disabled at configure time**. This is why the framework needs no JIT entitlement.
2. `make` still builds the `node` executable at `out/Release/node`. The script just doesn't package it. Independent confirmation that `out/Release/node` is the artifact:
   * Procursus [`makefiles/nodejs.mk`](https://github.com/ProcursusTeam/Procursus/blob/main/makefiles/nodejs.mk): `cp -a $(BUILD_WORK)/nodejs/out/Release/node $(BUILD_STAGE)/nodejs/.../bin`
   * `imcynic/nodejs-ios` [`build-deb.sh`](https://github.com/imcynic/nodejs-ios/blob/main/build-deb.sh) explicitly probes `$SCRIPT_DIR/../nodejs-mobile/out/Release/node`
   * `configure.py` in nodejs-mobile genuinely supports the target: `if options.dest_os == 'ios': o['variables']['OS'] = 'ios'` (`--dest-os=ios` is a real option)

### 1.3 macOS build requirements

* Xcode 11+ (upstream CI pins **Xcode 15.2** on `macos-13` and **15.4** on `macos-14`), Command Line Tools, CMake.
* Python 3.12 + `setuptools` in a venv — required workaround because 3.12 dropped `distutils` ([node-gyp#2869](https://github.com/nodejs/node-gyp/issues/2869)); upstream CI does exactly `python3.12 -m venv . && pip install setuptools`.

### 1.4 Maintenance status (relevant risk)

Last release **2024-10-07**; last real commit **2025-11-13** (`tools: update android builds to use 16kb page size (#154)`); repo `pushed_at` 2026-04-30 (branch/CI churn, not releases). Effectively **dormant, pinned to Node 18.20.4** — and Node 18 reached end-of-life **2025-04-30**, so the only iOS-native Node is an EOL line. No Node 20/22 iOS port exists upstream.

---

## 2. Existing prebuilt ARM64 iOS `node` binaries — yes, one real one

### 2.1 `imcynic/nodejs-ios` — the concrete hit ✅

[`imcynic/nodejs-ios`](https://github.com/imcynic/nodejs-ios) — "Node.js 18 for jailbroken iOS - Cydia/Sileo repo". Created/pushed **2026-01-26**, 9 stars, no license file.

Repo root contains an actual package: **`nodejs_18.20.4-1_iphoneos-arm64.deb`, 12,945,620 bytes**. I downloaded it, unpacked the `ar`/`data.tar.xz`, and verified the payload:

```
/var/jb/usr/local/bin/node                 292 B   (zsh wrapper script)
/var/jb/usr/local/lib/nodejs/node       74,215,568 B  (the real binary)
/var/jb/usr/local/lib/nodejs/entitlements.xml  733 B
```

**Binary verification (byte-level, done locally):**

| Property | Value |
|---|---|
| Magic | `cf fa ed fe 0c 00 00 01` → Mach-O 64-bit |
| `cputype` | `0x0100000C` = **CPU_TYPE_ARM64** (native, not emulated) |
| `filetype` | `2` = **MH_EXECUTE** → standalone CLI executable |
| `LC_BUILD_VERSION` | **platform=iOS, minOS=13.0.0, sdk=16.2.0** |
| Linked dylibs | `/usr/lib/libc++.1.dylib`, `/usr/lib/libSystem.B.dylib` — **only stock system paths**, no `/var/jb` deps → rootless-friendly |
| Version strings | `v18.20.4`; V8 `10.2.154.26` (identical V8 to nodejs-mobile 18.20.4) |

So: **iOS 16 is inside the minOS/SDK window** (min 13.0, built against 16.2 SDK).

**Provenance — it was built ON the device.** The binary embeds 2,972 strings containing `nodejs-mobile`; sampling them gives build paths like:

```
/private/var/mobile/nodejs-mobile/out/$(BUILDTYPE)/obj.target/deps/openssl/...
/private/var/mobile/nodejs-mobile/out/../deps/base64/base64/lib/arch/neon64/
```

`/private/var/mobile/` is the iPhone's own home directory. So this was **not** cross-compiled on a Mac — the nodejs-mobile tree was cloned to the device and built there with an on-device toolchain. One string is a source-level patch marker, confirming the source is nodejs-mobile (not stock Node):

```
const nodePath = process.env.NODE_PATH; // nodejs-mobile patch
```

**JIT posture of this binary.** V8 flag names are stored in the binary without the `--` prefix; counts: `sparkplug` 29, `maglev` 43, `liftoff` 43, `jitless` 9, `single_threaded` 10, `wasm_tier_up` 10, `baseline_batch_compilation` 18. Presence of Sparkplug/Maglev means **the JIT tiers are compiled IN** — this is *not* a `--jitless` build. It is made safe by entitlements + runtime flags instead.

The shipped wrapper `/var/jb/usr/local/bin/node`:

```sh
#!/var/jb/usr/bin/zsh
NODE_BIN="/var/jb/usr/local/lib/nodejs/node"
V8_FLAGS="--no-wasm-code-gc --no-opt --no-sparkplug --single-threaded --liftoff --no-wasm-tier-up"
exec "$NODE_BIN" $V8_FLAGS "$@"
```

and the shipped `entitlements.xml`:

```xml
platform-application                              true
com.apple.private.security.no-sandbox             true
get-task-allow                                    true
com.apple.private.cs.debugger                     true
dynamic-codesigning                               true
com.apple.private.skip-library-validation         true
com.apple.security.cs.allow-jit                   true
com.apple.security.cs.allow-unsigned-executable-memory  true
com.apple.security.cs.disable-library-validation   true
```

Package metadata: `Depends: firmware (>= 15.0), zsh, ldid`; `Installed-Size: 72496`; repo at `https://imcynic.github.io/nodejs-ios/`. README documents `dpkg -i`, `node --version`, REPL use, and re-signing via `ldid -S/var/jb/usr/local/lib/nodejs/entitlements.xml .../node`.

### 2.2 `imcynic/claude-code-ios` — proof it is production-usable

[`imcynic/claude-code-ios`](https://github.com/imcynic/claude-code-ios) (18 stars, 2026-01-26) ships **`claude-code_2.1.19-1_iphoneos-arm64.deb` (28,699,968 B)**. Package description: *"Includes Node.js 18.20.4 runtime with iOS-optimized V8 flags."* Files: `/var/jb/usr/local/bin/claude`, `/var/jb/usr/local/lib/claude-code/` (Node runtime + the CLI), plus a home-screen app. This is a large real-world Node CLI running natively on jailbroken iOS — strong existence proof for the parent's use case.

### 2.3 `1Conan/node` — the other iOS-patched Node fork

[`1Conan/node`](https://github.com/1Conan/node) — *"Node.js for jailbroken (soon non jbed) iOS (with linux building)"*. Only **2 stars**, last push **2022-10-03**, no GitHub releases. But it has real iOS tags: **`v16.12.0-ios`, `v16.13.0-ios`, `v16.13.1-ios`, `v16.14.0-ios`, `v17.0.1-ios`, `v17.2.0-ios`, `v17.6.0-ios`**. This is the source Procursus consumes. Max Node = **17.6.0** (Node 17 was never LTS).

### 2.4 Procursus — a `nodejs` build recipe exists, but the package is NOT published ⚠️

Procursus is the bootstrap Dopamine uses. [`makefiles/nodejs.mk`](https://github.com/ProcursusTeam/Procursus/blob/main/makefiles/nodejs.mk) builds a genuine CLI:

* `nodejs` **17.0.1** and `nodejs-lts` **16.13.0**
* sources: `github.com/1Conan/node` tag archives (`node-v17.0.1-ios`)
* flags: `--dest-os=ios --dest-cpu=$(MEMO_ARCH) --cross-compiling --without-npm --shared --shared-zlib --shared-libuv --shared-brotli --shared-nghttp2 --shared-cares --with-intl=full-icu --download=all`
* installs `out/Release/node` into `$(MEMO_PREFIX)/bin`; splits `libnode102` (dylib) + `libnode-dev` + `nodejs`
* signs with `general.xml`

**However — I checked the live repo index and the package is absent.** `https://apt.procurs.us/dists/iphoneos-arm64-rootless/1800/main/binary-iphoneos-arm64/Packages` (1,403,916 B, **1,367 packages**) contains **no `nodejs` package**. The only trace is `npm 8.1.1` with `Depends: nodejs` — an **unresolvable dependency** in that snapshot. The `testing` component (103 packages) also has no node. So: *build recipe exists upstream, distributable `.deb` does not.* Do not plan on `apt install nodejs` from Procursus.

Note also: Procursus signs with [`build_misc/entitlements/general.xml`](https://github.com/ProcursusTeam/Procursus/blob/main/build_misc/entitlements/general.xml), which contains `platform-application`, `com.apple.private.security.no-container`, `com.apple.private.skip-library-validation` and a very long list of `com.apple.private.security.storage.*` / `com.apple.rootless.storage.*` — but **no `dynamic-codesigning` and no `com.apple.security.cs.allow-jit`**. So Procursus' nodejs would run without JIT entitlement (interesting contrast with imcynic's approach; unverified whether V8 degrades or crashes there).

### 2.5 Negative results (searched, found nothing)

`gh search repos` for `"node.js ios jailbreak"`, `"node ios arm64"`, `"nodejs deb iphoneos-arm64"`, and `gh search code` for `"iphoneos-arm64 nodejs"` all returned **zero** further candidates. "NewTerm" is a terminal emulator, not a Node provider. There is no Sileo/Cydia community node package beyond the above.

---

## 3. Alternatives — maturity assessment

| Runtime | iOS status | Verdict |
|---|---|---|
| **nodejs-mobile (V8)** | iOS arm64 framework + buildable CLI; Node 18.20.4 | ✅ **only mature option** |
| **QuickJS** | [`quickjs-ios/quickjs-ios`](https://github.com/quickjs-ios/quickjs-ios) — "QuickJS iOS Bridge", **34 stars**. No Node compat layer, no `fs`/`net`/npm semantics | ❌ not Node-compatible |
| **Hermes** | No iOS-targeted standalone runtime project found (repo search empty). Hermes is a React Native engine shipped as a library; no Node API surface | ❌ not applicable |
| **Deno** | No iOS target. [`denoland/deno#6607`](https://github.com/denoland/deno/issues/6607) "iOS support" **CLOSED** (2023-06-06); `#21842` "Executable for Android and iOS" **CLOSED** (2024-03-01) | ❌ |
| **Bun** | No official target; unofficial interpreter-only port (see §4) | ❌ for iOS 16 |
| **JSC-based Node shims** | No mature project exists. JSC has no Node/libuv bindings; nodejs-mobile deliberately uses V8, and its FAQ states Node cannot run in a WebView because "Node.js uses a libuv event loop at its core, which is different than the event loop in the WebView" | ❌ |

---

## 4. Bun — official cross-compile targets and iOS feasibility

### 4.1 Official targets — no iOS ✅ verified

From [`docs/compiler/executables.mdx`](https://github.com/oven-sh/bun/blob/main/docs/compiler/executables.mdx) (raw fetch, 45,203 chars), the complete `bun build --compile --target=` set is exactly nine:

```
bun-linux-x64            bun-linux-arm64
bun-linux-x64-musl       bun-linux-arm64-musl
bun-linux-x64-baseline-musl
bun-windows-x64          bun-windows-arm64
bun-darwin-x64           bun-darwin-arm64
```

No `bun-ios-*`, no `bun-android-*`. `gh search code` for `"bun-ios"` in `oven-sh/bun` returned 0.

### 4.2 Official position on iOS

* [`oven-sh/bun#339`](https://github.com/oven-sh/bun/issues/339) "How to build for the mobile platform?" — **CLOSED**. Electroid, 2022-11-01: *"it's going to be a while before we have an official path to embedding bun on iOS. It is possible, but might require a lot of work."* Electroid, 2023-10-24: *"We will **not** be officially supporting Android/iOS for the foreseeable future."*
* [`oven-sh/bun#21237`](https://github.com/oven-sh/bun/issues/21237) "feat: mobile compiling support" — **OPEN**, created 2025-07-20, last updated 2026-07-01, 7 comments, linked to Linear `ENG-19708`. In 2026 the thread notes Bun is being rewritten in Rust (comment claim, unverified here).

### 4.3 The unofficial port (real, but wrong shape for this task)

Comment by **dannote** on #21237, 2026-02-11, claims a working iOS port:

> iOS Device (arm64) — using **C_LOOP interpreter** … Disabled JIT (not available on iOS devices) … Disabled WebAssembly (requires JIT) … Disabled SamplingProfiler … Performance: **~10x slower** than JIT

Verified independently:

* [`dannote/bun`](https://github.com/dannote/bun) — **fork** of oven-sh/bun, **3 stars**, last push **2026-02-11**. Branch `ios-port`, HEAD `a3f7a71a950b81109c39a755dca3a018ea121e1c` (2026-02-11), commit adds `docs/guides/runtime/ios-embedding.mdx`, `scripts/ios-test.sh`, `test/ios/example-app/`.
* [`dannote/pi-ios`](https://github.com/dannote/pi-ios) — **48 stars**, Swift, last push **2026-02-21**. README: *"Runs Bun's JavaScript engine directly on iOS using JSC's C_LOOP interpreter"*, GPU terminal via Ghostty, **Requires iOS 17.0+**, *"~600ms cold start, full npm package support"*, *"No JIT: JavaScript runs in interpreter mode (~10x slower than JIT)"*, *"No WebAssembly"*. Its build instructions require building **WebKit/JSC from source** with `-DENABLE_JIT=OFF -DENABLE_C_LOOP=ON -DENABLE_WEBASSEMBLY=OFF -DENABLE_SAMPLING_PROFILER=OFF`, then `dannote/bun` `-b ios-port` with `cmake/toolchains/ios-device.cmake`, then a patched Ghostty.

**Assessment:** Bun-on-iOS is an *embedding* (C API `bun_start` / `bun_eval`), not a `bun` CLI; it is **iOS 17+**, so it **cannot target iOS 16**; it is an unsupported 3-star fork of a fork; and it is ~10× slower. **Not a candidate.**

---

## 5. JIT on jailbroken iOS with ellekit / ldid entitlements

### 5.1 The authoritative constraint

Saagar Jha, *[Jailed Just-in-Time Compilation on iOS](https://saagarjha.com/blog/2020/02/23/jailed-just-in-time-compilation-on-ios/)* (2020-02-23):

> "Just-in-time compilation on iOS normally requires applications to possess the **dynamic-codesigning** entitlement, a privilege that Apple uniquely awards to system processes that require the high-performance tiers of JavaScriptCore."
>
> "…mmap (or its Mach VM equivalents) will only allow these kinds of mappings if the process requesting them possesses the **dynamic-codesigning** entitlement and passes the **MAP_JIT** flag."

He also documents the non-jailbreak workaround: `ptrace(PT_TRACE_ME)` sets `CS_DEBUGGED`, which *"disables code signing validation"*, enabling a W^X (flip permissions) JIT without the entitlement — **but his 6/24/20 update says iOS 14 broke this trick.** Also: without `dynamic-codesigning` you don't get "jumbo VA spaces", limiting the JIT's address space.

### 5.2 What ellekit actually is — **it is not a JIT enabler** ❗

[`tealbathingsuit/ellekit`](https://github.com/tealbathingsuit/ellekit) README, verbatim:

> "A C function hooker that patches memory pages directly / An Objective-C function hooker / An arm64 assembler / **A JIT inline assembly implementation for Swift** / A Substrate and libhooker API reimplementation"
>
> Requirements: "A arm64 device running the XNU kernel". Tested: iOS 15-27 (arm64), iOS 15-17 (arm64e). **Used by Dopamine**, palera1n, meowbrek2.

"The JIT inline assembly implementation for Swift" is an *assembler that runs in-process for hooking* — not a general JIT entitlement grant. **Adding ellekit does not make V8 JIT work.** It is already present in Dopamine; it changes nothing about `dynamic-codesigning`. Plan for entitlements, not tweaks.

### 5.3 What each project does about JIT

| Project | JIT decision |
|---|---|
| nodejs-mobile **framework** | `--v8-options=--jitless` at configure time → **V8 built with JIT off**. No entitlement needed. Costs a lot of throughput. |
| `imcynic/nodejs-ios` **CLI** | JIT **compiled in** (Sparkplug/Maglev/Liftoff present) → signed with `dynamic-codesigning` + `com.apple.security.cs.allow-jit` + `platform-application` + `no-sandbox`; **then disables optimizing tiers at runtime**: `--no-opt --no-sparkplug --single-threaded`, keeping `--liftoff` for WASM. README: "expect 2-5x slower". |
| Procursus `nodejs` | JIT compiled in, signed with `general.xml` which has **no** `dynamic-codesigning` / `allow-jit` — relies on `platform-application` + jailbreak AMFI relaxation. Behavior unverified. |
| Bun iOS port | JSC built `ENABLE_JIT=OFF ENABLE_C_LOOP=ON` → interpreter only. |

**Practical read:** on a Dopamine rootless device, an unsandboxed `platform-application` binary signed with `ldid` *can* carry `dynamic-codesigning`; this is exactly the mechanism the two shipping packages use. But the safest configuration for a large CLI — and the one a real product chose — is to **disable the optimizing tiers** and accept interpreter-ish speed, because that removes dependence on JIT-entitlement behavior entirely.

---

## 6. Build economics: size, time on a GitHub macOS runner, caching

### 6.1 Measured CI timings (hard data)

From `gh api repos/nodejs-mobile/nodejs-mobile/actions/workflows/build-mobile.yml/runs` — only 3 runs exist; latest completed run **19427311085** (2025-11-17, `success`). Per-job durations:

| Job | Runner | Duration |
|---|---|---|
| **build-ios (macos-13, arm64 device, Xcode 15.2)** | `macos-13` (Intel) | **125.8 min** |
| build-ios (macos-13, x64-simulator, 15.2) | `macos-13` (Intel) | 110.0 min |
| build-ios (macos-14, arm64-simulator, 15.4) | `macos-14` (Apple Silicon) | **56.2 min** |
| combine-ios (macos-14, 15.4) | `macos-14` | 1.7 min |
| build-android (×3) | `ubuntu-22.04` | 58.7–62.4 min |
| **whole workflow wall clock** | — | **122.8 / 127.6 / 148.2 min** |

**Interpretation (labeled inference):** the 125.8 min arm64-device figure is on an **Intel** `macos-13`. The arm64-*simulator* build on Apple-Silicon `macos-14` took 56.2 min for the same compiler work at the same target arch. So **a device-arm64 build on `macos-14`/`macos-15` should land near ~1 h**, versus ~2 h on Intel. Budget 1–2.5 h per cold build; these runs also had sccache configured (see below), so treat them as warm-ish.

### 6.2 Caching — already solved upstream

`.github/workflows/build-mobile.yml` sets:

```yaml
env:
  SCCACHE_GHA_ENABLED: 'true'
steps:
  - uses: mozilla-actions/sccache-action@v0.0.6
```

So **sccache with the GitHub Actions cache backend is the established mechanism** for exactly this build — upstream uses it for both Android and iOS jobs (commit `tools: update sccache-action in GHA`). Additional levers: `actions/cache` on `out/Release`/`out_ios_*`, and building **only** the arm64-device slice (the default script builds 3 slices — device arm64 + sim arm64 + sim x64 — which is where ~2/3 of upstream's CI time goes).

Note for cost: on GitHub-hosted runners macOS minutes bill at a **10× multiplier** on private repos (Actions is free for public repos). A 126-min macOS job ≈ 1,260 billed minutes.

### 6.3 Artifact sizes

* nodejs-mobile iOS zip (framework + headers): **51.5 MB** compressed; device framework binary **55.0 MB**.
* `node` CLI binary (stripped? no — 71 MB, built on-device): **74,215,568 B**; compressed `.deb`: **12.9 MB**.
* Claude Code iOS bundle including that Node runtime + CLI: `.deb` **28.7 MB**, installed **~142 MB**.
* A large CLI's own JS + `node_modules` sits on top of the ~71 MB runtime, so plan on **100–250 MB installed**.

---

## 7. Recommendation for the parent

**Fastest viable path (low risk, minutes):**
Vendor `nodejs_18.20.4-1_iphoneos-arm64.deb` from `imcynic/nodejs-ios`, or reproduce its layout: install to `/var/jb/usr/local/lib/nodejs/node` + a zsh wrapper in `/var/jb/usr/local/bin`, `ldid -S entitlements.xml` with `dynamic-codesigning`, `platform-application`, `no-sandbox`, `allow-jit`. Verified: native ARM64 `MH_EXECUTE`, min iOS 13.0, links only `/usr/lib/libSystem.B.dylib` + `libc++.1.dylib`, so it is rootless-clean on iOS 16.

**Recommended path (reproducible, you control the binary):**
Build from `nodejs-mobile` on a **`macos-14`+ runner**, arm64-device slice only:

```sh
GYP_DEFINES="target_arch=arm64 host_os=mac target_os=ios"
./configure --dest-os=ios --dest-cpu=arm64 --with-intl=none --cross-compiling \
            --enable-static --openssl-no-asm --without-node-code-cache --without-node-snapshot
make -j$(sysctl -n hw.ncpu)
# -> out/Release/node   (the CLI; the framework script simply doesn't package it)
```

Decide JIT policy explicitly:
* **Portable / no-entitlement-dependent:** add `--v8-options=--jitless` (nodejs-mobile's own default) — no JIT entitlement needed, slowest.
* **Faster:** omit `--jitless`, sign with `dynamic-codesigning` + `allow-jit`, and ship the `--no-opt --no-sparkplug --single-threaded --liftoff` wrapper as imcynic does.
Then cache with sccache + `SCCACHE_GHA_ENABLED=true` (upstream precedent) to make rebuilds cheap.

**Do not pursue:** Bun (`bun build --compile` has no iOS target; the only port is an iOS 17+ interpreter-only embedding fork), Deno (no iOS target, issues closed), QuickJS/Hermes (not Node-compatible), JSC shims (none exist), ellekit as a JIT enabler (it isn't one).

---

## 8. What I verified vs. what is inferred

**Verified directly (byte-level / API / HTTP):**
framework-only contents of the nodejs-mobile zip (536 entries enumerated); the `imcynic` `.deb` payload sizes; Mach-O magic, `cputype`, `filetype`, `LC_BUILD_VERSION`, dylib list, and embedded `v18.20.4` / V8 `10.2.154.26`; presence of Sparkplug/Maglev/Liftoff flag names; on-device build paths `/private/var/mobile/nodejs-mobile/...`; entitlements XML contents; wrapper script contents; release/tag/issue states and dates; CI job durations; absence of `nodejs` from the live Procursus rootless index (1,367 packages parsed).

**Inferred / not directly tested (labeled):**
* Whether the `imcynic` binary actually **executes** on iOS 16 Dopamine — I cannot run arm64 Mach-O on this Windows x64 host. Supported indirectly by minOS 13.0/SDK 16.2, the package's install docs, and the fact that `claude-code-ios` ships the same runtime in a real product.
* Estimated ~1 h for an arm64-device build on `macos-14` (extrapolated from the 56.2 min arm64-simulator job, not measured).
* Whether Procursus' JIT-entitlement-free `nodejs` would run V8 JIT successfully (moot — the package isn't published).
* Runtime behavior of `child_process.spawn` / `process.exit` in this exact CLI. nodejs-mobile's [FAQ](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/doc_mobile/FAQ.md) lists them as unsupported **for the embedded sandboxed framework** (App Store constraints), which should *not* apply to an unsandboxed jailbreak CLI — but this is untested here.

## 9. Adversarial check against the actual target CLI (opencode-style SEA bundle)

The workspace already contains the CLI's Node distribution logic (`research/upstream/`), so I checked the runtime findings against it. This materially changes the recommendation.

`research/upstream/target.ts` hard-restricts targets and requires **per-platform native addons**:

```ts
const platforms = ["darwin", "linux", "win32"] as const   // iOS not a target
nodePtyPackage      = `@lydell/node-pty-${targetPlatform}-${targetArch}`
parcelWatcherPackage= `@parcel/watcher-${targetPlatform}-${targetArch}`
fffPackage          = `@ff-labs/fff-bin-${targetPlatform}-${targetArch}`
fffFfiPackage       = `@yuuang/ffi-rs-${targetPlatform}-${targetArch}`
photonWasmAsset     = "@silvia-odwyer/photon-node/photon_rs_bg.wasm"
nodeExecArgv        = ["--experimental-ffi", "--use-system-ca", "--disable-warning=ExperimentalWarning"]
```

`research/upstream/node-assets.ts` shows the CLI ships as a **Node SEA** ("SEA embeds only the assets explicitly listed in its build configuration") with every native addon staged as an embedded asset and extracted to real paths at startup.

Implications, in order of severity:

1. **`--experimental-ffi` is a Node 26-era feature.** Node's FFI docs live under `nodejs.org/ffi/` (e.g. *DynamicLibrary | Node.js 26.12.0 Documentation*). Node **18.20.4 — the newest Node with any public iOS patch set — does not have it.** So the stock bundle cannot run on any currently-portable iOS Node. Verify the exact minimum version before planning, but this looks like a hard blocker requiring code changes (feature-gate the FFI path off on iOS).
2. **Four native addons have no iOS builds.** `@lydell/node-pty`, `@parcel/watcher`, `@ff-labs/fff-bin`, `@yuuang/ffi-rs` are all published only for darwin/linux/win32. Each needs a fresh arm64-iOS cross-compile: node-pty (`forkpty` — restricted on iOS), @parcel/watcher (FSEvents — plausible), ffi-rs (libffi — plausible), fff-bin (prebuilt blob). This is a **larger effort than getting `node` itself**, and it needs a real iOS toolchain per addon, not just a `node` binary.
3. **SEA injection still works in principle:** take an iOS-arm64 `node`, `postject` the SEA blob, then `ldid -S` with the entitlements from §2.1. Signing must happen *after* injection.
4. **`photon_rs_bg.wasm`** needs WebAssembly → Liftoff baseline compiler → executable memory → `dynamic-codesigning` entitlement (or `--jitless` + no WASM, which loses the feature).

**Revised recommendation:** treat "get `node` onto iOS" as **solved** (§2/§7) and re-scope the real work as (a) reconciling the Node major version requirement, and (b) cross-compiling or stubbing the native addons. A pragmatic iOS build would likely: strip `--experimental-ffi`/`ffi-rs`, replace `node-pty` with a pure-JS/pipe PTY path, drop or defer `@parcel/watcher` in favour of polling, and drop the WASM photon dependency — then run on the Node 18.20.4 arm64 binary from §2.1/§7.

## 10. Primary sources

* https://github.com/nodejs-mobile/nodejs-mobile — releases, `tools/ios_framework_prepare.sh`, `doc_mobile/BUILDING.md`, `doc_mobile/FAQ.md`, `.github/workflows/build-mobile.yml`
* https://github.com/imcynic/nodejs-ios — `nodejs_18.20.4-1_iphoneos-arm64.deb`, `README.md`, `Packages`, `build-deb.sh`
* https://github.com/imcynic/claude-code-ios — bundled Node 18.20.4 runtime
* https://github.com/1Conan/node — `v16.12.0-ios` … `v17.6.0-ios`
* https://github.com/ProcursusTeam/Procursus — `makefiles/nodejs.mk`, `build_info/nodejs.control`, `build_misc/entitlements/general.xml`
* https://apt.procurs.us/dists/iphoneos-arm64-rootless/1800/main/binary-iphoneos-arm64/Packages — live index (no nodejs)
* https://github.com/oven-sh/bun — `docs/compiler/executables.mdx`, issues #339, #21237
* https://github.com/dannote/bun (branch `ios-port`), https://github.com/dannote/pi-ios
* https://github.com/denoland/deno/issues/6607, #21842
* https://saagarjha.com/blog/2020/02/23/jailed-just-in-time-compilation-on-ios/
* https://github.com/tealbathingsuit/ellekit
* https://github.com/opa334/Dopamine
