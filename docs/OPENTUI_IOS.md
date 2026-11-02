# OpenTUI iPhoneOS renderer build (Phase C prep)

Status: **renderer built, codesign-signed and statically validated; loading into the Node
runtime on the device is pending.** This workflow cross-compiles the native Zig core of OpenTUI for
iPhoneOS arm64 so the real TUI has a renderer to load once the iPhoneOS Node.js runtime can execute
`node:ffi` (Node >= 26.4). It is now shipped as a CLI asset in the Node 26 bundle (Phase D) and the
fix for the device-reported exec-mapping failure is Apple `codesign` (ad-hoc) signing: **ldid-signed
dylibs are mapped non-executable by dyld on iOS 16.1.1** (calling into them SIGBUSes; crash `.ips`
shows `__TEXT` `r--/rw-`), while codesign-ad-hoc dylibs execute under `node:ffi` (device-verified
with a minimal probe: `CALL_OK add=5/13`). See "Signing: device-reported root cause" below.

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
| Signing | Apple `codesign` **ad-hoc** (`xcrun codesign --force --sign - --timestamp=none`), verified with `codesign --verify` / `codesign -dvv` (`Signature=adhoc`). **Not ldid**: ldid signatures make the dylib non-executable on the device (device-reported root cause). |

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
bash scripts/build-opentui-ios.sh all        # fetch + install Zig + build + codesign/validate/package
# individual phases:
bash scripts/build-opentui-ios.sh zig
bash scripts/build-opentui-ios.sh fetch
bash scripts/build-opentui-ios.sh build      # FULL log: dist/opentui-build/zig-build.log
bash scripts/build-opentui-ios.sh package    # stage + codesign(ad-hoc) + manifest/SHA256SUMS
bash scripts/build-opentui-ios.sh validate   # static audit of the packaged dylib (incl. codesign)
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
  libopentui.dylib             # iPhoneOS arm64 dylib; mach_header flags normalized to 0x100085
                               # (clang-dylib shape) + Apple codesign AD-HOC
  libopentui-unmodified.dylib  # A/B control variant: unmodified Zig Mach-O (flags 0x910085)
                               # + Apple codesign AD-HOC
  opentui-ios-manifest.txt     # pins, sha256/size, signing tool, original/normalized Mach-O flags
  codesign.txt / codesign-verify.txt                          # primary variant
  codesign-unmodified.txt / codesign-verify-unmodified.txt    # A/B control variant
  macho-flags-normalize.txt    # flags rewrite log (0x910085 -> 0x100085)
  file.txt / otool-L.txt / vtool.txt
  SHA256SUMS
```

Static validation (hard gates in the script, so a green run means all of these passed):

1. Thin little-endian arm64 **Mach-O dylib** (`filetype = MH_DYLIB`), `LC_BUILD_VERSION` platform
   **iOS=2**, exactly one platform command, **minOS <= 16.1.1**.
2. `otool -L`: every dependency is `/usr/lib/*` or `/System/Library/Frameworks/*`.
3. `vtool -show-build` reports `platform IOS`.
4. `codesign --verify --verbose=2` passes and `codesign -dvv` reports `Signature=adhoc`
   (Apple codesign ad-hoc signature; `ldid` signatures are explicitly NOT accepted any more).

## Result (green CI run)

| Field | Value |
| --- | --- |
| Latest run (A/B experiment) | [41491573878](https://github.com/Justintunsday/opencode-ios/actions/runs/41491573878) (success): primary flags-normalized `libopentui.dylib` sha256 `5301c35f…` + unmodified control `libopentui-unmodified.dylib` sha256 `761dd065…`; see the A/B table under "Signing: device-reported root cause" |
| Previous codesign run | [41487998437](https://github.com/Justintunsday/opencode-ios/actions/runs/41487998437) (success; workflow_dispatch from `main` `bd3fbac`; codesign commit `54e0eab`; this codesign-only Zig dylib still mapped non-executable on device — superseded by the A/B run) |
| Earlier ldid run (history) | [41313921358](https://github.com/Justintunsday/opencode-ios/actions/runs/41313921358) (success; ldid signature maps non-executable on device) |
| Artifact | `opentui-ios-renderer`, artifact id `13163002781` (zip 1,567,284 bytes) |
| Library | `libopentui.dylib`, **3,784,448 bytes**, sha256 **`c2123919402a3ab418f6e431d3c21bec4c33e130bb439c657a8ac17479da62a9`** |
| Mach-O | thin arm64 `MH_DYLIB`, `LC_BUILD_VERSION` platform **iOS**, minOS **15.0.0** (gate <= 16.1.1), **Apple codesign ad-hoc signed** (`Signature=adhoc`, `flags=0x2(adhoc)`, `codesign --verify` valid; no entitlements) |
| Dependencies (`otool -L`) | own `@rpath/libopentui.dylib` id + `/usr/lib/libc++.1.dylib`, `/usr/lib/libc++abi.dylib`, `/usr/lib/libSystem.B.dylib`, `/usr/lib/libobjc.A.dylib`, `CoreFoundation`, `CoreAudio`, `AudioToolbox`, `Foundation`, `AVFoundation`, `AVFAudio` (all iOS system libs) |
| Build time | ~2.5 min (Zig build step; full job ~3 min warm) |
| Patch | `0001-ios-target-and-sdk.patch` (sha256 `3e52a956…`; the patch header records the first green run) |

The `dylib` sha256 can change between builds because the ad-hoc code signature/identifier is part
of the file; the compiled renderer payload itself is reproducible. Each artifact ZIP's own
`SHA256SUMS` is authoritative for that run. The CLI bundle artifacts have the same property.
Changing the signing tool (ldid -> codesign) **changes the dylib sha256** — the CLI bundle pins the
codesign-adhoc artifact (run 41487998437) and was rebuilt with it.

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
a 2-key signature on the loading binary is sufficient; the dylib needs an Apple codesign
signature (ad-hoc) for executable mappings. `node:ffi`'s own `dlopen` follows the same sandbox
rules (device-verified from `/var/jb`).

### Launch flags and node:ffi API (validated on stock Node 26.13.0 host)

- `node:ffi` is **enabled by default** in Node 26.13.0: `node -e "require('node:ffi')"` works with no
  flags. `--no-experimental-ffi` disables it; `--experimental-ffi` is still accepted but redundant;
  `--allow-ffi` belongs to the permission model (and errors without `--permission`). The Phase D
  launcher therefore must not *depend* on `--experimental-ffi` (keeping it for explicitness is fine
  on 26.13, but it is not the switch that enables FFI).
- `require('node:ffi')` exports `dlopen`/`dlclose`/`dlsym`/`DynamicLibrary`/`suffix`/…, and
  `ffi.dlopen(path, definitions)` returns `{ lib, functions }` — exactly what OpenTUI 0.8.0
  destructures (`const { lib, functions } = nodeFfi.dlopen(...)`); `dlsym` returns a bigint. So
  OpenTUI's Node FFI backend is API-compatible with Node 26.13.
- Caveat: the Phase A runtime is currently built with `--without-ffi` as a fallback artifact; Phase D
  targets the FFI-enabled follow-up build (`deps/libffi` iOS cross-build is the noted risk). Keep the
  `--single-threaded` requirement (the V8 W^X toggle is process-wide) and the `/var/jb` asset-path
  rule from the dlopen evidence above.

## Signing: device-reported root cause (renderer exec mapping)

The first end-to-end TUI attempt failed with a `SIGBUS` when executing renderer code. The Lead built
a minimal probe (`libocprobe.dylib`: `int add(int,int)` compiled with `xcrun clang` for
`arm64-apple-ios`) and ran it on the target iPhone SE 2 / iOS 16.1.1 under `node:ffi`:

- signed with **Apple `xcrun codesign --force --sign -`** (ad-hoc; with or without the 2-key
  entitlements) -> `dlopen` + call -> **`CALL_OK add=5/13`** (execution works from `/var/jb/tmp`);
- the same source signed with **`ldid -S` / `-S<entitlements>` / `-M`** -> `dlopen` succeeds but
  calling the function **SIGBUSes**; the crash `.ips` shows the dylib `__TEXT` mapped `r--/rw-`
  (non-executable).

Conclusion: the runtime, the `/var/jb` path and the OpenTUI build were fine; **ldid's code signature
is not sufficient for executable mappings on this device**. The renderer is therefore signed with
Apple `codesign` ad-hoc (`scripts/build-opentui-ios.sh package`), the artifact ships `codesign.txt` /
`codesign-verify.txt`, and the static gate requires `codesign --verify` + `Signature=adhoc`. The
`ldid`-signed dylib from run 41313921358 remains in the docs only as history.

**Second device finding: codesign alone is still not sufficient for the Zig-produced dylib.** The
codesign-adhoc Zig dylib (run 41487998437, sha256 `c2123919…`) still SIGBUSed on the device with the
same `__TEXT r--/rw-` mapping, while the clang-built minimal probe dylib with the identical
`codesign --force --sign -` signature executed (`add(2,3)=5`). Mach-O diff of the two:

| Field | clang minimal (executes) | Zig renderer (mapped non-exec) |
| --- | --- | --- |
| `mach_header_64.flags` | `0x100085` | `0x910085` (extra `0x800000` MH_HAS_TLV_DESCRIPTORS, `0x10000` MH_BINDS_TO_WEAK) |
| `__TEXT` maxprot/initprot | 5 / 5 | 5 / 5 |
| LC_CODE_SIGNATURE | valid | valid (codesign verifies) |

### A/B experiment (run 41491573878)

`scripts/build-opentui-ios.sh package` now rewrites `mach_header_64.flags` at file offset 24 to
`0x100085` on the primary artifact (after `zig build`, before codesign; log in
`macho-flags-normalize.txt`) and ships an unmodified control so both can be device-probed in one
cycle. Artifact `opentui-ios-renderer` run 41491573878 (artifact id 13164658134, zip 3,132,730 B):

| Variant | File | Size | sha256 | flags | codesign |
| --- | --- | --- | --- | --- | --- |
| A: normalized + codesign (primary) | `libopentui.dylib` | 3,784,448 B | `5301c35fe237969a9c13ef6d16f468d95bc05b2a1c638aa7d26d50fa13b40730` | `0x100085` | adhoc, verify PASS |
| B: unmodified + codesign (control) | `libopentui-unmodified.dylib` | 3,784,448 B | `761dd0653312d0ca5288e5db5ae5ff17682610df1424ecf1e0895ff7aab88a6d` | `0x910085` | adhoc, verify PASS |

Device outcome of the A/B probe is pending (Lead). If A executes, the Zig output is rebuilt/pinned
with flags normalization and the CLI bundle + package are rebuilt from it. If both fail, the fallback
is to link the final dylib with `xcrun clang -dynamiclib -target arm64-apple-ios15.0` from Zig objects
instead of using Zig's linker (same Mach-O shape as the working clang probe).

## Known limitations / remaining Phase D work


- **Loading into the Node runtime is the remaining device check.** CI proves the codesign-adhoc
  Mach-O/loader/linkage gates, a `dlopen` probe proved `/var/jb` paths work, and the ldid-vs-codesign
  exec-mapping root cause is device-verified; the full `node:ffi` load + renderer call inside the Node
  26 runtime is the Lead's pending device test.
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
- Phase D (CLI side): DONE in the Node 26 bundle — `ios-arm64` accepted by the OpenTUI asset
  resolver, `libopentui.dylib` staged at `@opentui/core-ios-arm64/` and installed under the
  `/var/jb/usr/lib/opencode/cli/assets` deb root (never `/var/mobile` or `/tmp`), node:ffi default-on
  (no `--experimental-ffi` needed on 26.13) and the handlers only use the line-REPL fallback when
  `node:ffi` is unavailable (patch 0016). Remaining item: device TUI acceptance with the
  FFI-enabled runtime + codesign-adhoc renderer.
