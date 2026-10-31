# OpenCode iOS rootless port — macOS ARM64 baseline

This repository is a **porting bootstrap**, **not** a working OpenCode iOS binary.

- Source baseline: `anomalyco/opencode` **macOS ARM64 / Darwin** OpenCode v2 CLI.
- Target: `arm64-apple-ios16.0`, jailbroken iOS 16.1.1 (Dopamine rootless, ElleKit).
- Output goal: `opencode-<version>-iphoneos-arm64.deb` with `/var/jb/usr/bin/opencode`.
- Primary path: source-port macOS ARM64 Bun runtime and CLI to the iPhoneOS SDK.
- Secondary path: use the same macOS OpenCode v2 source's Node build backend if iOS Bun is blocked; this is still a Darwin/macos-based port, **not** an Android port.

## Status (stage 0)

Included:

1. Reproducible upstream revision manifest.
2. A macOS GitHub Actions workflow that compiles a **minimal iPhoneOS ARM64 probe** against the iPhoneOS SDK, audits its Mach-O platform, signs it and produces a rootless `.deb` for testing.
3. Mach-O platform audit and tests (rejects macOS binaries masquerading as iOS).
4. Explicit multi-stage porting tasks for Codex.

**Not included:** iOS-compatible Bun, OpenCode executable, iOS builds of native dependencies, proof of real-device execution.

Do NOT rename the probe as `opencode`, market it as working OpenCode, or report a successful end-to-end OpenCode port based on a successful probe build.

## Start

1. Create a new GitHub repository for this project; do not put it in `airpods-compat`.
2. Upload these files.
3. Run **iOS Toolchain and Rootless Packaging Probe** via GitHub Actions.
4. Download `ios-rootless-probe`, install in a disposable/tested rootless environment, and test via SSH/NewTerm: `opencode-ios-smoke`.
5. Provide the result to Codex alongside [`CODEX_TASK.md`](CODEX_TASK.md).
6. Only build an actual `opencode` package after the upstream port executes and tests pass on iOS.

See [PORTING_PLAN.md](PORTING_PLAN.md) for blockers and gates.
