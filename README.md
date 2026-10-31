# OpenCode iOS — native iPhoneOS ARM64 port (rootless)

Native port of the **OpenCode v2 CLI** (`anomalyco/opencode`, macOS ARM64 baseline) to
jailbroken **iOS 16 / arm64** (iPhone SE 2, Dopamine rootless, ElleKit, NewTerm/SSH).
Everything is built and validated in GitHub Actions; the delivered package is an
`iphoneos-arm64` Debian package installing `/var/jb/usr/bin/opencode`.

> This is an independent port. Upstream OpenCode is MIT-licensed; this repository keeps the
> original attribution and applies upstream changes as patches — upstream repositories are never
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
  (`arm64-apple-ios`, iPhoneOS SDK), signed with `ldid` and minimal JIT/exec-memory entitlements.
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

See [`docs/VERIFICATION.md`](docs/VERIFICATION.md). CI validates: Mach-O platform is iPhoneOS
(`PLATFORM_IOS=2`), CPU is arm64, minimum iOS ≤ 16.1.1, linked dylibs are iOS system libraries,
rootless paths are correct, package metadata is valid, and the CLI bundle runs (`--version`,
`--help`, catalog commands) on a host Node.js runtime on the macOS runner. **On-device execution
cannot be performed on hosted macOS runners and is marked `UNVERIFIED ON DEVICE` until the user
runs the provided smoke test on the iPhone.**

## CI workflows

All workflows are `workflow_dispatch`-enabled; the three build workflows also run on relevant
source changes. `build-runtime.yml` produces the iOS Node runtime, `build-opencode.yml` produces
the CLI bundle; `package-rootless.yml` and `test-port.yml` consume the latest successful artifacts
of both (or explicit `runtime_run_id` / `opencode_run_id` inputs).

## Licence and attribution

OpenCode is MIT-licensed and © its contributors. Node.js is MIT-licensed and © Node.js
contributors; the nodejs-mobile patch set is MIT-licensed. See the `LICENSE` and NOTICE section of
the package (`/var/jb/usr/share/doc/opencode/copyright`).
