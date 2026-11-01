# OpenCode iOS native iPhoneOS ARM64 port (rootless)

Native port of the **OpenCode v2 CLI** (`anomalyco/opencode`, macOS ARM64 baseline) to
jailbroken **iOS 16 / arm64** (iPhone SE 2, Dopamine rootless, ElleKit, NewTerm/SSH).
Everything is built and validated in GitHub Actions; the delivered package is an
`iphoneos-arm64` Debian package installing `/var/jb/usr/bin/opencode`.

> This is an independent port. Upstream OpenCode is MIT-licensed; this repository keeps the
> original attribution and applies upstream changes as patches 鈥?upstream repositories are never
> modified.

## What this repository contains

| Path | Purpose |
| --- | --- |
| `docs/ARCHITECTURE.md` | Port architecture and decision record (authoritative) |
| `docs/RUNTIME_DECISION.md` | Why the native iPhoneOS Node.js runtime (and not Bun) is the shipping runtime |
| `docs/BUN_FEASIBILITY.md` | Bun iPhoneOS audit with concrete blockers |
| `docs/INSTALL.md` | Device installation / upgrade / uninstall instructions |
| `docs/VERIFICATION.md` | Verification matrix + how to run the device smoke test |
| `docs/KNOWN_LIMITATIONS.md` | Honest feature gaps and unsupported optional features |
| `UPSTREAM.lock` | Pinned OpenCode / Bun / nodejs-mobile revisions |
| `.github/workflows/build-runtime.yml` | Builds the iPhoneOS arm64 Node.js runtime |
| `.github/workflows/build-opencode.yml` | Builds the OpenCode CLI JS bundle from pinned upstream |
| `.github/workflows/package-rootless.yml` | Assembles and checks the rootless `.deb` |
| `.github/workflows/test-port.yml` | Static validation suite and smoke tests runnable on CI |
| `patches/` | Reviewable upstream patches (OpenCode, nodejs-mobile) |
| `packaging/` | DEBIAN control scripts, launcher, docs packaged into the `.deb` |
| `scripts/`, `tests/`, `src/` | Build/validation tooling, Mach-O auditor, stage-0 probe |

The original bootstrap notes are preserved in [`docs/BOOTSTRAP_README.md`](docs/BOOTSTRAP_README.md),
[`CODEX_TASK.md`](CODEX_TASK.md) and [`PORTING_PLAN.md`](PORTING_PLAN.md).

## Runtime architecture

- **Runtime:** Node.js 22.9.0 compiled from nodejs-mobile's iPhoneOS patch set
  (`arm64-apple-ios`, iPhoneOS SDK) with **ICU enabled** (`--with-intl=full-icu`, required for
  ECMA-402 `Intl` and V8 Unicode property escapes), V8 `--jitless` and WebAssembly disabled, signed
  with `ldid` using the minimal device-verified entitlement pair
  (`platform-application` + `com.apple.private.security.no-sandbox`).
- **CLI:** the same OpenCode v2.2.5 source tree, built through upstream's
  `packages/cli/script/build-node.ts` Vite bundle path, with a small iOS adaptation patch set for
  the non-SEA asset layout and for optional native dependencies that have no iPhoneOS builds
  (PTY, file watcher, ffi/fff).
- **Package:** rootless layout under `/var/jb`, launcher `/var/jb/usr/bin/opencode`, runtime and
  bundle under `/var/jb/usr/lib/opencode/`.

## Install (summary)

See [`docs/INSTALL.md`](docs/INSTALL.md) for the verified procedure. Short version:

```sh
# copy OpenCode-iOS-rootless.deb to the device, then
sudo dpkg -i OpenCode-iOS-rootless.deb
opencode --version
opencode --help
```

## Verification status

**Current status: CI-complete, device-installable, CLI execution on device BLOCKED by a V8
JIT/W^X limitation of iOS 16.1.1.** Full evidence: [`docs/DEVICE_TEST_RESULTS.md`](docs/DEVICE_TEST_RESULTS.md).

Verified in CI (`build-runtime.yml`, `build-opencode.yml`, `package-rootless.yml`,
`test-port.yml`): Mach-O platform is iPhoneOS (`PLATFORM_IOS=2`), CPU is arm64, minimum iOS
鈮?16.1.1, linked dylibs are iOS system libraries only, static entitlements are the device-verified
minimal set, rootless paths/metadata/maintainer scripts are valid, the CLI bundle passes
`--version`/`--help`/catalog command smoke tests on stock Node 22.9.0, and the assembled `.deb`
passes the packaging audit and cross-contract verification.

Verified on the real device (iPhone SE 2, iOS 16.1.1, Dopamine rootless, ElleKit 1.2):

- the final `iphoneos-arm64` `.deb` installs, upgrades and removes cleanly with rootless `dpkg`;
- the native iPhoneOS arm64 Node.js 22.9.0 runtime executes with the 2-key entitlement set
  (`process.platform === "ios"`, fs/spawn/TLS/`node:sqlite`/ICU/Intl/Unicode property escapes);
- rootless shell/`dpkg` behaviours required by the package are device-verified.

**Not yet working on device:** the OpenCode CLI itself. The JavaScript bundle requires V8 JIT and
WebAssembly (Node's built-in `fetch`/undici needs a wasm llhttp parser), and V8 12.4's code-page
permission model is incompatible with iOS 16.1.1's W^X enforcement in all three configurations
attempted (MAP_JIT without APRR 鈫?SIGBUS; MAP_JIT + mprotect RWX 鈫?SIGTRAP/OOM; plain mprotect
RWX 鈫?code pages lose execute 鈫?SIGBUS). `opencode --version` therefore exits 138 (SIGBUS) on the
device today. The proposed next fix (a small V8 patch implementing mprotect-based RW鈫擱X code page
toggling, a primitive device-proven to work) is described in
[`docs/DEVICE_TEST_RESULTS.md`](docs/DEVICE_TEST_RESULTS.md#proposed-next-fix-not-yet-implemented).

## CI workflows

All workflows are `workflow_dispatch`-enabled; the three build workflows also run on relevant
source changes. `build-runtime.yml` produces the iOS Node runtime, `build-opencode.yml` produces
the CLI bundle; `package-rootless.yml` and `test-port.yml` consume the latest successful artifacts
of both (or explicit `runtime_run_id` / `opencode_run_id` inputs).

## Licence and attribution

OpenCode is MIT-licensed and 漏 its contributors. Node.js is MIT-licensed and 漏 Node.js
contributors; the nodejs-mobile patch set is MIT-licensed. See the `LICENSE` and NOTICE section of
the package (`/var/jb/usr/share/doc/opencode/copyright`).
## Latest validated artifacts (GitHub Actions)

| Workflow | Run | Result |
| --- | --- | --- |
| Build iOS Node.js runtime (v5: ICU + WebAssembly + JIT, no-MAP_JIT W^X model) | `41219489179` | success |
| Build OpenCode CLI iOS bundle (6-patch series, iOS prelude/asset set) | `41192939688` | success |
| Package rootless iOS .deb (pins the two runs above + optional iPhoneOS ripgrep) | `41264333018` | success |
| Port verification (static package + host-runtime smoke) | `41264491693` | success |

Final artifact: `OpenCode-iOS-rootless.deb`, 52,917,652 bytes, SHA-256
`0b87bb8783f20f2040ebe60bd408cb8bcecab5c58cd9d08ded623e7e74401bb8`
(Architecture `iphoneos-arm64`, rootless `/var/jb`, includes optional `/var/jb/usr/bin/rg`).
It is CI-validated and device-installable, but **device CLI execution is currently blocked** as
described above — do not treat it as a finished port.
