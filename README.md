# OpenCode iOS (rootless)

Native port of the **OpenCode v2 CLI** (`anomalyco/opencode`, macOS ARM64 baseline) to
jailbroken **iOS 16 / arm64** (iPhone SE 2, Dopamine rootless, ElleKit, NewTerm/SSH).
Everything is built and validated in GitHub Actions; the delivered package is an
`iphoneos-arm64` Debian package installing `/var/jb/usr/bin/opencode`.

> This is an independent port. Upstream OpenCode is MIT-licensed; this repository keeps the
> original attribution and applies upstream changes as patches ?upstream repositories are never
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

**Current status: DEVICE-VERIFIED WORKING PORT.** The released rootless `.deb` (SHA-256
`2f96fc183416ef336fc9855b9dedc51e6baaf89cda996b0147b31444dbef446b`) was installed on the target
iPhone SE 2 (iOS 16.1.1, Dopamine rootless) and passed the full packaged acceptance:
**PASS=14 FAIL=0** - dpkg install/status, `opencode --version`, `--help`, `debug paths`,
`debug config`, `models`, `auth list`, `session list`, a complete mock-provider agent turn
(the shell tool executed on the device and wrote/verified a marker file), plus dpkg remove and
reinstall. Full raw evidence: [`docs/DEVICE_TEST_RESULTS.md`](docs/DEVICE_TEST_RESULTS.md).

Also verified in CI (`build-runtime.yml`, `build-opencode.yml`, `package-rootless.yml`,
`test-port.yml`): Mach-O platform is iPhoneOS (`PLATFORM_IOS=2`), CPU is arm64, minimum iOS
<= 16.1.1, linked dylibs are iOS system libraries only, static entitlements are the
device-verified minimal 2-key set, rootless paths/metadata/maintainer scripts are valid, the CLI
bundle passes the host Node 22.9.0 smoke matrix, and the assembled `.deb` passes the packaging
audit and cross-contract verification.

Device-verified components: the native iPhoneOS arm64 Node.js 22.9.0 runtime executes with the
2-key entitlement set (`process.platform === "ios"`, JIT + WebAssembly + full ICU/Intl/`\p{...}`,
native `node:sqlite`, fetch/TLS, fs, shell spawn); the launcher runs it with
`--single-threaded` (required: the V8 mprotect W^X toggling is process-wide, and V8 background
threads would race it - see KNOWN_LIMITATIONS); `git` from Procursus apt is used by the agent shell
tool. Known limits (documented in `docs/KNOWN_LIMITATIONS.md`): interactive TUI/PTY is not fully
validated on device, native file watchers degrade to the node/fallback backend, the local
mock-provider transport is intermittently flaky (retry succeeds), and 2 GB iPhones need the
packaged `--max-old-space-size=1536` default / other apps closed.

## CI workflows

All workflows are `workflow_dispatch`-enabled; the three build workflows also run on relevant
source changes. `build-runtime.yml` produces the iOS Node runtime, `build-opencode.yml` produces
the CLI bundle; `package-rootless.yml` and `test-port.yml` consume the latest successful artifacts
of both (or explicit `runtime_run_id` / `opencode_run_id` inputs).

## Licence and attribution

OpenCode is MIT-licensed and (c) its contributors. Node.js is MIT-licensed and (c) Node.js
contributors; the nodejs-mobile patch set is MIT-licensed. See the `LICENSE` and NOTICE section of
the package (`/var/jb/usr/share/doc/opencode/copyright`).
## Latest validated artifacts (GitHub Actions)

| Workflow | Run | Result |
| --- | --- | --- |
| Build iOS Node.js runtime (v6: ICU + WebAssembly + JIT, V8 mprotect RW<->RX W^X model) | `41273024931` | success |
| Build OpenCode CLI iOS bundle (10-patch series incl. patch 0010 child flag forwarding) | `41273112229` | success |
| Package rootless iOS .deb (node22 variant, pins the two runs above + optional iPhoneOS ripgrep) | `41274221353` | success |
| Port verification on the final package | `41274690207` / `41274713331` | success |

Final released artifact: `OpenCode-iOS-rootless.deb`, 52,968,920 bytes, SHA-256
`2f96fc183416ef336fc9855b9dedc51e6baaf89cda996b0147b31444dbef446b`
(Architecture `iphoneos-arm64`, rootless `/var/jb`, installs `/var/jb/usr/bin/opencode`; ships the
device-verified `v6` Node 22.9.0 runtime, the patch-0010 CLI bundle and the optional
`/var/jb/usr/bin/rg`). The Node 18 fallback runtime/bundle remains available as a documented
alternative, but node22+v6 is the device-verified primary deliverable.
