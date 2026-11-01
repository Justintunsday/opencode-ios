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
| Signing | `ldid -S` with the device-verified 2-key node entitlements (`scripts/ios-runtime/entitlements.plist`) |

OpenTUI's Zig dependencies (yoga, uucode, ghostty) are vendored in
`packages/native/src/vendor/zig-deps.tar.gz` and unpacked by the upstream
`scripts/prepare-zig-deps.sh`; no network fetch is needed for them.

## Source patches (`patches/opentui-ios/`)

| # | Patch | Files | Purpose |
| --- | --- | --- | --- |
| 0001 | `ios-target-and-sdk` | `packages/native/build.zig`, `packages/native/src/clipboard/host.zig` | Adds the `aarch64-ios.15.0` library target; resolves an iPhoneOS SDK (`-Dios-sdk=` / `IOS_SDK_PATH`); adds `.ios` arms for the miniaudio/image/libwebp C flags (`-isysroot <iPhoneOS.sdk>`), iPhoneOS framework linking (CoreFoundation/CoreAudio/AudioToolbox/AudioUnit/pthread, no AppKit/UIKit), SDK include/framework/lib search paths, and an `.ios` arm for the clipboard worker switch. iOS keeps the "clipboard unsupported" path (the macOS NSPasteboard shim is AppKit-only). |

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

The build is:

```bash
zig build -Dlibrary-target=aarch64-ios.15.0 -Doptimize=ReleaseFast \
  -Dios-sdk="$(xcrun --sdk iphoneos --show-sdk-path)"
```

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

## Known limitations / remaining Phase D work

- **Not device-verified.** The library has never been loaded on the iPhone; CI only proves it is a
  correctly built/signed iPhoneOS dylib. A device run needs the Node 26 iPhoneOS runtime first.
- **Clipboard is unsupported on iOS** in this library (v1): the macOS backend is the AppKit
  NSPasteboard shim; a future patch can add a UIPasteboard implementation. OpenTUI clipboard calls
  will report `unsupported` through the existing result codes.
- **Ghostty VT is disabled** for iOS (upstream availability check only enables it for
  linux/macos/windows); the embedded-terminal feature is therefore unavailable in v1.
- **Audio**: miniaudio is compiled with its CoreAudio backend (CoreAudio/AudioToolbox/AudioUnit
  linked); iOS AVAudioSession behaviour is untested on device.
- Phase D (CLI side, to be tracked separately): accept `ios-arm64` in the OpenTUI asset resolver,
  ship `libopentui.dylib` in the CLI assets bundle (so `stage`/manifest include it), pass
  `--experimental-ffi` in the launcher, and replace the iOS REPL fallback with the real TUI once
  the Node 26 runtime + FFI + renderer all pass on device.
