# OpenTUI iPhoneOS renderer build (Phase C prep)

Status: **build feasibility only — NOT device-verified.** This workflow cross-compiles the
native Zig core of OpenTUI for iPhoneOS arm64 so the real TUI has a renderer to load once the
iPhoneOS Node.js runtime can execute `node:ffi` (Node >= 26.4). Loading the library, shipping it
as a CLI asset and the device test are Phase D work.

## Why this exists

The iPhoneOS CLI currently falls back to a line REPL because OpenTUI's Node binding loads its
Zig native core (`libopentui.dylib`) through `node:ffi`, which requires Node >= 26.4 with
`--experimental-ffi`; the shipped Node 22.9 runtime has neither (`opencode` prints the REPL
guidance instead). The Node 26 iPhoneOS runtime is built by
`.github/workflows/build-runtime-node26.yml` (runtime-engineer, Phase A/B). Upstream OpenTUI
v0.8.0 only ships native libraries for Linux/macOS/Windows, so an iPhoneOS build is the missing
piece on the CLI side.

Node 26's `src/ffi/jit_memory.cc` uses the device-proven W^X pattern (`mmap RW → write →
mprotect RX`, no `MAP_JIT`), which is what makes a Zig-built dylib viable on this device.

## Pins

| Input | Pin |
| --- | --- |
| OpenTUI source | `https://github.com/anomalyco/opentui` tag `v0.8.0`, commit `738067f47e940dcec3f5aab74868908574335c6c` |
| Zig | `0.16.0` (`zig-aarch64-macos-0.16.0.tar.xz`, sha256 `b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489`) |
| iOS target | `aarch64-ios.15.0`, deployment target minOS 15.0 (validation gate: minOS <= 16.1.1) |
| Xcode | `macos-15` runner image, iPhoneOS SDK from `xcrun --sdk iphoneos --show-sdk-path` |
| uucode tables | pre-generated `uucode-tables.zig` (vendored gzipped in `patches/opentui-ios/files/uucode-tables.zig.gz`; generated once with Zig 0.16.0 for the exact fields OpenTUI requests) |
| Signing | `ldid -S` with the device-verified 2-key node entitlements (`scripts/ios-runtime/entitlements.plist`) |

OpenTUI's Zig dependencies (yoga, uucode, ghostty) are vendored in
`packages/native/src/vendor/zig-deps.tar.gz` and unpacked by the upstream
`scripts/prepare-zig-deps.sh`; no network fetch is needed for them.

## Source patches (`patches/opentui-ios/`)

| # | Patch | Files | Purpose |
| --- | --- | --- | --- |
| 0001 | `ios-target-and-sdk` | `packages/native/build.zig`, `packages/native/src/clipboard/host.zig`, `packages/native/src/miniaudio_shim_ios.m` (new), `packages/native/src/opentui_ios_stubs.c` (new) | Adds the `aarch64-ios.15.0` library target; resolves an iPhoneOS SDK (`-Dios-sdk=` / `IOS_SDK_PATH`); `.ios` C flags (`-isysroot`) and an ObjC miniaudio shim (AVAudioSession/AVFoundation) for iOS; iPhoneOS framework linking (CoreFoundation/CoreAudio/AudioToolbox/Foundation/AVFoundation, no AppKit/UIKit) with SDK include/framework/library search paths; explicit SDK paths for the three `translate-c` steps. C++ is a hybrid: Zig 0.16 bundled libc++ headers + Zig`s libc++ configuration defines, linked against the SDK libc++/libc++abi `.tbd` stubs, with no bundled libc++ sub-build. Also adds `-Duucode-tables=<path>` (vendored pre-generated tables, no native `uucode_generate` host tool) and an iOS stub for the private macOS-only `_dyld_get_image_header_containing_address` symbol referenced by Zig`s debug self-info. iOS keeps the "clipboard unsupported" path. |

Apply with `git apply` from the OpenTUI checkout root (the script does this).

## Build

```bash
# on a macOS host with Xcode:
bash scripts/build-opentui-ios.sh all        # fetch + install Zig + build + sign/validate/package
# individual phases:
bash scripts/build-opentui-ios.sh zig
bash scripts/build-opentui-ios.sh fetch
bash scripts/build-opentui-ios.sh build      # FULL log: dist/opentui-build/zig-build.log
bash scripts/build-opentui-ios.sh package
bash scripts/build-opentui-ios.sh validate   # static audit of the packaged dylib
```

The script extracts the vendored uucode tables and the build is:

```bash
gzip -dc patches/opentui-ios/files/uucode-tables.zig.gz > packages/native/uucode-tables.zig
zig build -Dlibrary-target=aarch64-ios.15.0 -Doptimize=ReleaseFast \
  -Dios-sdk="$(xcrun --sdk iphoneos --show-sdk-path)" \
  -Duucode-tables=uucode-tables.zig
```

No global `zig build --sysroot` is used: it would apply to every compilation unit (including the
uucode host-tool build and Zig's bundled libc++ sub-build) and broke both. The iPhoneOS SDK is
wired explicitly in `build.zig` instead (`-isysroot` for the C/ObjC shims, SDK include/framework/
library search paths, translate-c SDK paths) and the uucode host tool is eliminated via the
vendored tables, so the iOS build graph contains no host executables. C++ is compiled with Zig's
bundled libc++ headers plus the configuration defines Zig normally supplies, and linked against
the iPhoneOS SDK's libc++/libc++abi stubs (see the patch table) because Zig 0.16.0 cannot build
its bundled libc++ for `aarch64-ios` and the SDK libc++ headers do not mix with Zig's libc headers.

from `dist/opentui-build/opentui/packages/native`; the dylib lands in
`packages/native/zig-out/lib/aarch64-ios/libopentui.dylib`. Environment overrides:
`OPENTUI_REPO`, `OPENTUI_REF`, `OPENTUI_COMMIT`, `OPENTUI_IOS_TARGET`, `OPENTUI_BUILD_DIR`,
`OPENTUI_DIST`, `OPENTUI_IOS_MAX_MINOS`, `IOS_SDK_PATH`.

## Artifact contract (`opentui-ios-renderer`)

```
opentui-ios-renderer/
  libopentui.dylib            # iPhoneOS arm64 dylib, ldid-signed (2-key node entitlements)
  opentui-ios-manifest.txt    # upstream/zig/SDK/patch pins, sha256/size, status caveat
  entitlements-signed.xml     # ldid -e output
  file.txt / otool-L.txt / vtool.txt
  SHA256SUMS
```

Static validation (hard gates in the script, so a green run means all of these passed):

1. Thin little-endian arm64 **Mach-O dylib** (`filetype = MH_DYLIB`), `LC_BUILD_VERSION` platform
   **iOS=2**, exactly one platform command, **minOS <= 16.1.1**.
2. `otool -L`: every dependency is `/usr/lib/*` or `/System/Library/Frameworks/*`.
3. `vtool -show-build` reports `platform IOS`.
4. `ldid -e` returns an embedded signature blob (signed).

## Result (green CI run)

| Field | Value |
| --- | --- |
| Run | [41313921358](https://github.com/Justintunsday/opencode-ios/actions/runs/41313921358) (success; commit `3392dcb`; earlier green run [41313516105](https://github.com/Justintunsday/opencode-ios/actions/runs/41313516105)) |
| Artifact | `opentui-ios-renderer` (zip 1,585,492 bytes) |
| Library | `libopentui.dylib`, **3,785,600 bytes**, sha256 **`954289152cc182780a81ca7199ceeec04ee8c55c334f85710e0ff192f4817638`** |
| Mach-O | thin arm64 `MH_DYLIB`, `LC_BUILD_VERSION` platform **iOS**, minOS **15.0.0** (gate <= 16.1.1), ldid-signed with the device-verified 2-key node entitlements |
| Dependencies (`otool -L`) | own `@rpath/libopentui.dylib` id + `/usr/lib/libc++.1.dylib`, `/usr/lib/libc++abi.dylib`, `/usr/lib/libSystem.B.dylib`, `/usr/lib/libobjc.A.dylib`, `CoreFoundation`, `CoreAudio`, `AudioToolbox`, `Foundation`, `AVFoundation`, `AVFAudio` (all iOS system libs) |
| Build time | ~2.5 min (Zig build step; full job ~3 min warm) |
| Patch | `0001-ios-target-and-sdk.patch` (sha256 `3e52a956…`; the patch header records the first green run) |

The `dylib` sha256 is **not reproducible across runs** because the `ldid` signature blob is not
deterministic; the compiled renderer payload itself is reproducible, and each artifact ZIPs own
`SHA256SUMS` is authoritative for that run. The CLI bundle artifacts have the same property.

## Phase D device precondition (dlopen, device-verified)

The Lead device-tested the loadability precondition on the target iPhone (iOS 16.1.1, Dopamine
rootless jailbreak) with a dedicated `dlopenprobe-2key` probe (opencode-ios run 41315221320,
51,424 B, sha256 `724e6fc69ea2f6f4973021c10a9d9922573a6fec225977dbe2e37ec30b464548`, same 2-key
entitlements as the CLI runtime) loading this artifact's dylib (sha256 `954289152c…`). Evidence file
in the lead workspace: `C:\opencode\device\PHASE_D_DLOPEN_EVIDENCE.md`.

| Test path | Result |
| --- | --- |
| `/usr/lib/libz.dylib` (system baseline) | `DLOPEN_OK` |
| `/var/mobile/libopentui.dylib` | `DLOPEN_FAIL: file system sandbox blocked mmap()` |
| `/private/var/tmp/octest/libopentui.dylib` | `DLOPEN_FAIL: file system sandbox blocked mmap()` |
| `/var/jb/tmp/octest/libopentui.dylib` | `DLOPEN_OK`, `DLCLOSE_OK` rc=0 |
| `/var/jb/var/mobile/octest/libopentui.dylib` | `DLOPEN_OK`, `DLCLOSE_OK` rc=0 |
| `/var/jb/usr/lib/opencode/libopentui.dylib` (root-owned 755, package path) | **`DLOPEN_OK`**, `DLCLOSE_OK` rc=0 |

Packaging requirement for Phase D: ship the renderer **under the rootless jailbreak prefix**
(`/var/jb/...`), e.g.
`/var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib` — the CLI assets
directory already lives under `/var/jb/usr/lib/opencode/cli/`, so the renderer belongs in the
normal asset tree. Do **not** load it from `/var/mobile` or `/tmp` (sandbox blocks executable
`mmap` there). The asset path must be derived from the installed CLI asset root, not from the
bundled module's original location. No JIT/extra entitlements are needed for `dlopen` itself:
2-key signatures on both the dylib and the loading binary are sufficient. `node:ffi`'s own
`dlopen` should follow the same sandbox rules; that is the remaining device unknown, blocked on
the Node 26 runtime (Phase A/B).

## Known limitations / remaining Phase D work

- **Not verified inside the Node runtime.** CI proves it is a correctly built/signed iPhoneOS dylib,
  and a 2-key-signed `dlopen` probe loaded it successfully on the device from `/var/jb` paths (see
  the Phase D device precondition above). Loading it from `node:ffi` inside the Node 26 runtime is
  still untested (blocked on the Node 26 Phase A/B runtime).
- **Hybrid C++ ABI (Zig 0.16.0 workaround).** The C++ translation units are compiled with Zig's
  bundled libc++/libc++abi headers (ABI version 1, hardening mode none, Zig's feature defines) but
  linked against the iPhoneOS SDK's libc++/libc++abi stubs. Both are LLVM libc++ (ABI 1) so this is
  expected to be compatible, but it is a workaround for Zig's missing Darwin/iOS libc++ support and
  must be confirmed by the Phase D device test (and revisited when Zig supports iOS libc++ natively).
- **Private dyld symbol stub.** `src/opentui_ios_stubs.c` defines
  `_dyld_get_image_header_containing_address` (a private macOS dyld API Zig's debug self-info
  references, absent on iPhoneOS). It is only used in panic/stack-trace self-info; rendering paths do
  not call it.
- **Clipboard is unsupported on iOS** in this library (v1): the macOS backend is the AppKit
  NSPasteboard shim; a future patch can add a UIPasteboard implementation. OpenTUI clipboard calls
  will report `unsupported` through the existing result codes.
- **Ghostty VT is disabled** for iOS (upstream availability check only enables it for
  linux/macos/windows); the embedded-terminal feature is therefore unavailable in v1.
- **Audio**: miniaudio is compiled with its CoreAudio backend (CoreAudio/AudioToolbox/Foundation/AVFoundation
  linked); iOS AVAudioSession behaviour is untested on device.
- Phase D (CLI side, to be tracked separately): accept `ios-arm64` in the OpenTUI asset resolver,
  ship `libopentui.dylib` in the CLI assets bundle under the `/var/jb` deb root prefix (see the
  Phase D device precondition above; never load from `/var/mobile`/`/tmp`), pass
  `--experimental-ffi` in the launcher, and replace the iOS REPL fallback with the real TUI once
  the Node 26 runtime + FFI + renderer all pass on device.
