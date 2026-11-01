# Device test results — iPhone SE 2 / iOS 16.1.1 / Dopamine rootless

This file records the **actual on-device evidence** gathered during the port. Nothing here is
inferred from CI: every line was produced by running the artifacts on a real target device.

## Device under test

| Property | Value |
| --- | --- |
| Model | iPhone SE (2nd generation), `iPhone12,8`, `arm64` |
| OS | iPhone OS **16.1.1** (20B101), Darwin 22.1.0 |
| Jailbreak | Dopamine rootless, `/var/jb` -> `/private/preboot/.../dopamine-*/procursus`, ElleKit 1.2 |
| User | `mobile` (uid 501), root via `sudo` for `dpkg` |
| Terminals | SSH (OpenSSH 9.7p1), NewTerm-compatible zsh at `/var/jb/bin/zsh` |
| Shell reality | no `/bin/sh`, `/bin/bash`, `/bin/zsh`; shell tools live under `/var/jb/{bin,usr/bin}` |
| git | installed from Procursus apt (`git 2.39.1`) for testing |

## Status summary

| Area | Result |
| --- | --- |
| Debian package install/uninstall/upgrade (`iphoneos-arm64`, rootless `/var/jb`) | **PASS** |
| Native iPhoneOS arm64 Node.js runtime executes (`node --version` -> `v22.9.0`, `process.platform === "ios"`) | **PASS** |
| Runtime minimal entitlements (`platform-application` + `com.apple.private.security.no-sandbox`) | **PASS** (other sets SIGKILL, exit 137) |
| ICU / Intl / Unicode property escapes in the shipped runtime | **PASS** on device: `{"icu":"75.1","intl":"object","regex":true}` |
| `node:sqlite` (`--experimental-sqlite`), fs, explicit-shell `child_process`, TLS, child `node` spawn | **PASS** (jitless build) |
| V8 JIT / WebAssembly execution (required by the CLI bundle: `Intl.Segmenter` is fine, but Node's built-in `fetch`/undici needs wasm llhttp at startup) | **BLOCKED — V8 code-page permission failure on iOS (SIGBUS)** |
| `opencode --version` / `--help` through the installed launcher | **FAIL — SIGBUS (exit 138)** |
| Interactive TUI / provider auth / agent turns | **NOT REACHED** (blocked by the same V8 issue) |

## What was device-verified in detail

### 1. Package installation (final v5-based package)

- `.deb`: `OpenCode-iOS-rootless.deb`, 52,917,652 bytes, SHA-256
  `0b87bb8783f20f2040ebe60bd408cb8bcecab5c58cd9d08ded623e7e74401bb8`
- `sudo dpkg -i` -> `Setting up opencode (2.2.5-1)`, exit 0; status `install ok installed`,
  `Architecture: iphoneos-arm64`, `Installed-Size: 163996`, `Depends: firmware (>= 15.0)`.
- Installed layout verified: `/var/jb/usr/bin/opencode` (0755),
  `/var/jb/usr/lib/opencode/runtime/node` (native iPhoneOS arm64, 106,822,656 bytes),
  `/var/jb/usr/lib/opencode/cli/opencode.mjs`, `cli/assets/`, `/var/jb/usr/bin/rg`,
  `/var/jb/usr/share/doc/opencode/*`.
- Upgrade over an earlier package version and `dpkg -r`/`-P` were exercised; maintainer scripts
  are `#!/bin/sh` (rootless Procursus dpkg executes them; verified with a test deb) and the
  launcher shebang is `#!/var/jb/bin/sh` because the kernel execs it directly.

### 2. Native runtime (iPhoneOS arm64 Node.js 22.9.0)

- `node --version` -> `v22.9.0`; `process.platform === "ios"`, `arch === "arm64"`,
  `v8 12.4.254.21-node.19`, `uv 1.48.0`, `openssl 3.0.13+quic`, `icu 75.1`, `sqlite 3.46.1`.
- Mach-O: `Mach-O 64-bit executable arm64`, `LC_BUILD_VERSION platform=IOS minos=14.0 sdk=18.5`,
  links only `/usr/lib/libSystem.B.dylib` and `/usr/lib/libc++.1.dylib` (ICU + wasm static).
- Signing: `ldid -S` with the 2-key set works. Device matrix: 4-key/large sets that include JIT
  entitlements are SIGKILLed (137) when they lack `no-sandbox`; the minimal working set is
  `platform-application` + `com.apple.private.security.no-sandbox`.
- ICU under `--jitless` on device: `{"icu":"75.1","intl":"object","regex":true}` — full-icu
  works; without ICU the CLI bundle fails to parse with
  `SyntaxError: Invalid regular expression: /[\p{Mark}...]/gu` (device-captured).
- `node:sqlite` create/insert/select, fs read/write in `/var/jb/var/mobile`, explicit
  `/var/jb/bin/sh -c` child process, TLS to a public host, and spawning child `node` all pass.

### 3. The blocker: V8 JIT code pages are not executable on iOS

Any execution of JIT-generated/copied code traps; only `--jitless` works (and then
`WebAssembly` is undefined, which breaks Node's built-in `fetch`/undici at startup):

| Runtime variant | Device result |
| --- | --- |
| v2: ICU, `--v8-options=--jitless`, no wasm | starts, `--version` OK; CLI cannot parse/start fetch (wasm undefined) |
| v3: ICU + wasm, V8 JIT, MAP_JIT, 2-key | `EXC_BAD_ACCESS/SIGBUS` (exit 138) in `Builtins_InterpreterEntryTrampoline`; JIT page `max rwx / current rw-` |
| v4: MAP_JIT + pthread_jit_write_protect | `EXC_BREAKPOINT/SIGTRAP` (exit 133), `V8::FatalProcessOutOfMemory` at `CodeRange::InitReservation` (mprotect RWX of the code range denied) |
| v5: no MAP_JIT, plain mprotect W^X, 2-key | `--version` OK; any JS execution -> `SIGBUS` (exit 138) executing builtins from an `rw-` page |

Memory-permission probe run on the device (native iPhoneOS arm64 diagnostic binary, same 2-key
signing):

```
plain_then_mprotect_rwx: mmap=ok mprotect=0 errno=0
mmap_jit_rwx: FAIL errno=22
plain_write_rx_exec: mprotect_rx=0 exec=0 errno=0
mapjit_reserve_mprotect_rwx_exec: mprotect=-1 exec=-1 errno=22
pthread_jit_write_protect_np: absent
```

Interpretation: on this device an ordinary mapping can be written, `mprotect`ed to RX and
executed, but **`mprotect(RWX)` silently loses the execute permission** (the region stays
`rw-`), `MAP_JIT` mappings are rejected (`EINVAL`), and the APRR toggle API is absent. V8 12.4
assumes either `MAP_JIT` + APRR (macOS) or permanently-RWX pages (Linux); neither holds on
iOS 16.1.1, so JIT code pages end up non-executable and the first generated-code execution
traps. No entitlement set changes this (9-key included).

Crash evidence (device CrashReporter `.ips`):
- v5: `EXC_BAD_ACCESS`, `SIGBUS`, `KERN_PROTECTION_FAILURE`, region `rw-/rwx`, thread executing
  `Builtins_InterpreterEntryTrampoline` from the code range.
- v4: `EXC_BREAKPOINT`, `SIGTRAP`, backtrace `OS::Abort <- FatalOOM <- V8::FatalProcessOutOfMemory
  <- Heap::SetUp` (`Failed to reserve virtual memory for CodeRange`).

## What this means

The port is **CI-complete and device-installable**, the native iPhoneOS runtime is proven to run,
ICU/Intl/sqlite/fs/TLS/process-spawn are device-verified, and the packaging/signing/rootless
behaviour is device-verified. The **CLI itself does not yet run on the device**, because the
JavaScript bundle requires V8 JIT/WebAssembly and V8 12.4's code-page permission model is not
compatible with iOS 16.1.1's W^X enforcement in any of the three configurations tried
(MAP_JIT + no APRR; MAP_JIT + mprotect RWX; plain mprotect RWX).

## Proposed next fix (not yet implemented)

Implement a *third* V8 write-protect mode for iOS: keep `V8_HAS_PTHREAD_JIT_WRITE_PROTECT=0`
and no MAP_JIT, but replace V8's assumption "RWX pages stay executable" with explicit
`mprotect` toggling of the code range between RW (writes) and RX (execution), driven by
`RwxMemoryWriteScope`/`CodePageMemoryModificationScope` (a small V8 patch: track the code-range
base/size and make `SetWritable`/`SetExecutable` do `mprotect`). The device probe above shows
exactly this primitive works (`plain_write_rx_exec: exec=0`). This requires one more Node/V8
iPhoneOS rebuild (~2 h in the current GitHub Actions pipeline) plus on-device testing.

An alternative fallback, not chosen for v1, is to ship the interpreted-only runtime and replace
Node's WebAssembly-based `fetch` stack in the OpenCode bundle with a pure-JS HTTP client; that
trades performance (interpreter-only start-up is ~74 s for this bundle on the device) and needs
a significant CLI patch.
