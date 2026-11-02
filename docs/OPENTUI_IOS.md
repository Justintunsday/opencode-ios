# OpenTUI iPhoneOS renderer

The renderer from [run 41531609826](https://github.com/Justintunsday/opencode-ios/actions/runs/41531609826)
is **DEVICE-VERIFIED for node:ffi loading and execution** on iPhone SE 2 / iOS 16.1.1 /
Dopamine rootless: `dlopen` plus `imageRetainIccCache()` returned `RENDERER_CALL_OK`, and
real OpenTUI rendering was observed. Packaged acceptance is recorded in
[`VERIFICATION.md`](VERIFICATION.md).

The final dylib must be linked with **Xcode clang/ld64 from the Zig static archive**, then
signed with **Apple codesign ad-hoc**. The stable `v2.2.5-ios.5` release uses Node 22 and its
line REPL; the separate experimental Node 26 package loads this renderer through `node:ffi`.

## Pins

| Input / output | Pin |
| --- | --- |
| OpenTUI | `anomalyco/opentui` tag `v0.8.0`, commit `738067f47e940dcec3f5aab74868908574335c6c` |
| Zig | `0.16.0`; archive SHA-256 `b23d70deaa879b5c2d486ed3316f7eaa53e84acf6fc9cc747de152450d401489` |
| Target | `aarch64-ios.15.0`, thin arm64 `MH_DYLIB`, platform IOS, minOS 15.0, SDK 18.5 |
| Final linker | Apple clang 17.0.0 / ld64, Xcode 16.4 |
| Renderer run | [41531609826](https://github.com/Justintunsday/opencode-ios/actions/runs/41531609826), commit `cbba01240a3306ef475213dedbaad9e410056358` |
| `libopentui.dylib` | **4,181,456 bytes**, SHA-256 **`5a2f016bd8a3a2a7b86560204f0c48106666892a419353276493a462c6707242`** |
| Signing | `xcrun codesign --force --sign - --timestamp=none`; `Signature=adhoc`, no Team ID or dylib entitlements; `codesign --verify` passes |
| Dynamic ABI | 1,847 exported symbols, including `imageRetainIccCache` |
| Asset key | `@opentui/core-ios-arm64/libopentui.dylib` |
| Installed path | `/var/jb/usr/lib/opencode/cli/assets/@opentui/core-ios-arm64/libopentui.dylib`, mode 0755 |

The CLI build pins this run and SHA in `.github/workflows/build-opencode.yml`, audits the
Mach-O/signature, then embeds the renderer in `opencode-cli-node26-ios`. Packaging checks the
same pin. Rebuilding/signing can change the hash; use the exact artifact's `SHA256SUMS`.

## Build

On macOS with Xcode:

```sh
bash scripts/build-opentui-ios.sh all
# Individual phases:
bash scripts/build-opentui-ios.sh zig
bash scripts/build-opentui-ios.sh fetch
bash scripts/build-opentui-ios.sh build
bash scripts/build-opentui-ios.sh package
bash scripts/build-opentui-ios.sh validate
```

`patches/opentui-ios/0001-ios-target-and-sdk.patch` adds the iOS target, SDK paths,
Objective-C miniaudio shim, clipboard unsupported branch, private dyld debug-symbol stub and
static-library output. The build uses vendored Zig dependencies and pre-generated
`uucode-tables.zig` from `patches/opentui-ios/files/uucode-tables.zig.gz`; no iOS host tool runs.
C++ uses Zig's libc++ headers with ABI version 1 and the iPhoneOS SDK's libc++/libc++abi stubs.

The `build` phase produces the Zig static archive and a Zig-linked diagnostic dylib. The
`package` phase builds matching Zig compiler-rt, then runs Xcode
`clang++ -dynamiclib -target arm64-apple-ios15.0` with `-force_load` of `libopentui.a` and an
explicit exported-symbol list. Linker-generated `__dso_handle` / `__mh_dylib_header` are
excluded from the required ABI. Every required dynamic symbol is audited before signing.

Dependencies are only iOS libc++ / libc++abi / libSystem / libobjc and CoreFoundation,
CoreAudio, AudioToolbox, Foundation, AVFoundation, AVFAudio, ImageIO and CoreGraphics.
Commands/logs: `clang-link.txt`, `dist/opentui-build/zig-build.log`.
Environment overrides: `OPENTUI_REPO`, `OPENTUI_REF`, `OPENTUI_COMMIT`, `OPENTUI_IOS_TARGET`,
`OPENTUI_BUILD_DIR`, `OPENTUI_DIST`, `OPENTUI_IOS_MAX_MINOS`, `IOS_SDK_PATH`.

## Artifact contract (`opentui-ios-renderer`)

```text
libopentui.dylib                    # shipping clang/ld64 + codesign ad-hoc dylib
libopentui-ziglinked.dylib          # diagnostic control; known non-executable on device
opentui-ios-manifest.txt           # source/toolchain/linker/SHA/size provenance
clang-link.txt / exported-symbols.txt
nm-exported.txt / nm-exported-ziglinked.txt
codesign.txt / codesign-verify.txt
codesign-ziglinked.txt / codesign-verify-ziglinked.txt
file.txt / otool-L.txt / vtool.txt
SHA256SUMS
```

Static gates check thin little-endian arm64 `MH_DYLIB`, platform iOS, minOS <= 16.1.1,
system-only dependencies, exported ABI and `codesign --verify`. The CLI workflow also
requires `Signature=adhoc`. Host build success alone does not prove device execution.

## Device findings and superseded experiments

| Experiment | Actual device result |
| --- | --- |
| Dylib under real `/var/mobile` or `/private/var/tmp` | `dlopen` fails: sandbox blocked executable `mmap` |
| Dylib under `/var/jb` | `dlopen` succeeds; execution also depends on final link/signature |
| ldid-signed renderer, run `41313921358`, SHA `954289152c…` | Renderer call SIGBUSes; `__TEXT` mapped non-executable |
| Zig-linked + codesign, run `41487998437`, SHA `c2123919…` | Still SIGBUSes; codesign alone does not fix the Zig-linked image |
| Header flags A/B, run `41491573878` (`5301c35f…` normalized / `761dd065…` original) | Both failed; rewriting flags to `0x100085` did not fix execution |
| **clang/ld64 + codesign, run `41531609826`, SHA `5a2f016b…`** | **node:ffi load + `imageRetainIccCache()` → `RENDERER_CALL_OK`; real TUI rendered** |

The effective fix is the clang/ld64 final link plus ad-hoc signing under `/var/jb`.
The earlier `/var/mobile/Library/OpenCode/assets` mirror workaround was incorrect and has
been removed. Both `OPENCODE_NODE_ASSETS_DIR` and `OTUI_ASSET_ROOT` default to
`/var/jb/usr/lib/opencode/cli/assets`.

The Node executable keeps its device-proven **ldid two-key** signature
(`platform-application`, `com.apple.private.security.no-sandbox`); the renderer uses Apple
codesign ad-hoc. These are separate signing requirements.

## Runtime and remaining limits

The acceptance runtime is `ios-node26-runtime-ffi` from
[nodejs26-ios run 41450472333](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41450472333):
Node 26.13.0, 134,677,104 bytes, SHA-256
`73144efa5002e17b09340e0681274f38a7ed2a2fb5f7dc91572fc637570c74af`.
It includes the V8 14.6 iOS W^X fixes (0007/0009), wasm allocator fix (0011) and wasm trap-handler
fix (0013). `node:ffi` is default-on; `--experimental-ffi` is redundant. Always pass
`--single-threaded`, including to spawned server children (CLI patch 0010).
The older `--without-ffi` runtime cannot run the real TUI.

- Clipboard remains unsupported; no UIPasteboard backend is implemented.
- Ghostty VT / embedded interactive terminal panes are unavailable on iOS; shell tools use pipes.
- Audio / AVAudioSession behaviour has not been device-accepted.
- The hybrid libc++ header/SDK arrangement and private dyld debug-symbol stub remain porting
  workarounds; rendering success does not validate every optional native feature.
- Real external provider authentication/API calls require user credentials and separate
  acceptance. See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).
