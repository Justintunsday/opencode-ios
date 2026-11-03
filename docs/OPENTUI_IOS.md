# OpenTUI iPhoneOS renderer

> **node26test.7 / 2.2.5-4 — DEVICE-VERIFIED for mobile SSH PTY functionality; the full-screen flash was fixed.**
> Root cause: the TUI wrapped every changed frame in DECSET 2026 synchronized output and the device terminal
> (**EverTerm 1.5-2**, not NewTerm) presents each synchronized block as a full-screen present. iOS now emits
> no 2026 envelope (patch 0018); the user A/B confirmed the flash disappears and the new CLI frame stream has
> 0 sync frames. The user visually confirmed the official node26test.7 package no longer flashes (2026-11-03); see `MOBILE_TUI_DEVICE_RESULTS.md`.
> CLI [41641758047](https://github.com/Justintunsday/opencode-ios/actions/runs/41641758047),
> package [41642851035](https://github.com/Justintunsday/opencode-ios/actions/runs/41642851035):
> installation rc=0, narrow/resize TUI rc=0, 3-turn/121.600-second TUI rc=0, CLI 8/0 and JSON/tool E2E.

> [Exact identities, raw output and limits](MOBILE_TUI_DEVICE_RESULTS.md). Stable `v2.2.5-ios.5` is unchanged.

The renderer from [run 41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506)
is DEVICE-VERIFIED for native loading/execution. Its exact signed bytes are retained in
mobile node26test.7, package run 41642851035. Narrow/resize and 3-turn TUI acceptance
both exit 0 using the independent node26 runtime and the `/var/jb` asset root.
The mobile profile uses 20 FPS, **no DECSET 2026 synchronized-output envelope**, reduced motion and
a steady cursor. The old build had balanced 2026 envelopes (12/12 resize, 164/164 three-turn), but
the device terminal is EverTerm 1.5-2, which turns each synchronized block into a full-screen
present and flashed the whole screen on every update. The user A/B confirmed the trigger, and
test.7 emits 0/0 sync sequences, no repeated full-screen clear and zero output in measured idle
windows. The user visually confirmed the official package no longer flashes (2026-11-03).
See [mobile results](MOBILE_TUI_DEVICE_RESULTS.md) and the historical
[test.5 acceptance](NODE26_EXTERNAL_DEVICE_RESULTS.md).
Earlier embedded test.4 acceptance remains in [`VERIFICATION.md`](VERIFICATION.md).

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
| Renderer run | [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506), commit `59c2ed01ac06e1d00e48e171756b096a0fa96ecc` |
| `libopentui.dylib` | **4,181,472 bytes**, SHA-256 **`4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868`** |
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

The manual compiler-rt build requires `-fno-builtin -fno-stack-check -fno-stack-protector`
and a separate `-nobuiltin.a` cache key. Otherwise LLVM can
replace memory loops with recursive calls to the same builtin. The post-link
`scripts/check-macho-builtins.py` audit checks five memory routines and rejects
direct self branches/calls; it fails on the old renderer and passes on this artifact.

## Artifact contract (`opentui-ios-renderer`)

```text
libopentui.dylib                    # shipping clang/ld64 + codesign ad-hoc dylib
libopentui-ziglinked.dylib          # diagnostic control; known non-executable on device
opentui-ios-manifest.txt           # source/toolchain/linker/SHA/size provenance
clang-link.txt / exported-symbols.txt
compiler-rt-builtins-audit.txt      # no recursive memory builtins
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
| clang/ld64 + codesign, run `41531609826`, SHA `5a2f016b…` | Loading / basic drawing worked, but submission hung: `_memset` / `_memcpy` recursively called themselves. Superseded. |
| **No-builtin compiler-rt, run `41582979506`, SHA `4792df5d…`** | **Packaged normal and long TUI input, local-mock shell tool / reply and `/exit` rc=0; no new crash reports** |

The effective fix is the clang/ld64 final link plus ad-hoc signing under `/var/jb`.
The earlier `/var/mobile/Library/OpenCode/assets` mirror workaround was incorrect and has
been removed. Both `OPENCODE_NODE_ASSETS_DIR` and `OTUI_ASSET_ROOT` default to
`/var/jb/usr/lib/opencode/cli/assets`.

The Node executable keeps its device-proven **ldid two-key** signature
(`platform-application`, `com.apple.private.security.no-sandbox`); the renderer uses Apple
codesign ad-hoc. These are separate signing requirements.

An additional **612.4-second** packaged PTY test passed 12 shell/tool-result
turns and 12 fenced code blocks using the plain-text fallback. `/exit` returned 0;
the later crash baseline stayed 105/105. The private-server test used a 512 MiB heap
cap and preserved the user's existing root service. Exact scope and transcript hash:
[`VERIFICATION.md`](VERIFICATION.md).

## Runtime and remaining limits

The accepted runtime is `ios-node26-runtime-ffi` from
[41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128): Node 26.13.0, **134,710,336 bytes**,
SHA-256 `84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9`, source `7cd359f377d9d37dfe13d929927cf67274451ec2`.
It retains V8 14.6 W^X fixes 0007/0009, wasm allocator 0011, platform 0012 and wasm
trap-handler fix 0013. `node:ffi` is default-on; `--experimental-ffi` is redundant.
Always pass `--single-threaded`, including to server children (CLI patch 0010).

Actual input acceptance found a separate callback problem in the old runtime run
`41450472333`: libffi's generated config omitted iOS from the Apple ARM trampoline policy,
so it returned a callback in malloc `rw-` memory and native edit events SIGBUSed.
Patch 0014 enables the ARM trampoline table. Run `41541888412` then failed callback
allocation because iOS code-page remaps lost execute permission (device probe R/R).
Patch 0015 copies the fixed PC-relative trampoline instructions to anonymous RW memory,
flushes I-cache and seals code RX, retaining the adjacent metadata page as RW.
It does not request RWX or MAP_JIT. The accepted packaged runtime passed the qsort/reentrant
callback probe and renderer text insertion with a JS callback, plus actual TUI input.
CLI patch 0017 also checks TTY before FFI routing and prints guidance/1 for pipes.

Runtime patch 0016 is also required. The second package candidate reproduced a JIT
SIGBUS with inherited `--single-threaded`: a wasm background worker was publishing code
and toggling all JIT pages RW while the main thread executed one. iPhoneOS JobHandles now
receive zero background workers; `Join()` adds the foreground participant. This retains
synchronous wasm compilation and prevents that publication race. The accepted installed
runtime passed 192 HTTP/fetch requests and 24 varied wasm modules amid JIT loops, plus
normal and long real-TUI sessions without new crash reports.

Node user `worker_threads` are a separate constraint: `--single-threaded` does not
disable them. The first assistant reply reproduced a `WorkerThread` bootstrap
SIGBUS in tree-sitter. CLI dependency patch 0002 prevents the iOS tree-sitter
worker from starting and rejects its initialization. OpenTUI's existing plain-text
code fallback preserves fenced code content and Markdown layout; native TUI and
terminal program-status fields remain active. Final packaged acceptance includes
a local mock reply with a fenced shell code block. Tree-sitter syntax highlighting
is unavailable; arbitrary user worker isolates remain outside this runtime policy.

- Clipboard remains unsupported; no UIPasteboard backend is implemented.
- Ghostty VT / embedded interactive terminal panes are unavailable on iOS; shell tools use pipes.
- Audio / AVAudioSession behaviour has not been device-accepted.
- The hybrid libc++ header/SDK arrangement and private dyld debug-symbol stub remain porting
  workarounds; rendering success does not validate every optional native feature.
- Real external provider authentication/API calls require user credentials and separate
  acceptance. See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).
