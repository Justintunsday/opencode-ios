# Engineering roadmap — macOS ARM64 → jailbroken iOS ARM64

## Architectural starting point

OpenCode v2 (pinned dev snapshot) ships:

- `packages/cli/script/build.ts`: `Bun.build` compiled binary `bun-darwin-arm64`, but no iOS target.
- `packages/cli/script/build-node.ts`: Vite-bundled Node single-executable application; Node 26.4.0 target list includes Darwin ARM64, but no iPhoneOS build.
- Native components include `@opentui/core`, `@opencode/pty`, `@parcel/watcher`, `ffi-rs`, and `fff` binaries, currently distributed for macOS/Linux/Windows, not iOS.

Platform identity, system APIs, and linked dylibs differ between iOS and macOS. Changing `LC_BUILD_VERSION` or signing the macOS executable is not a viable primary porting method: it does not fix missing APIs, invalid dynamic library dependencies, JIT behavior, or platform-specific native modules.

## Phase 0 — Device SDK and packaging (bootstrap included)

Build iOS ARM64 test binary using `xcrun --sdk iphoneos clang`, target `arm64-apple-ios16.0`, check `LC_BUILD_VERSION` platform iOS, compile & package rootless `/var/jb/usr/bin`, ad-hoc sign, test on iOS 16.1.1. The GitHub workflow only performs a compile + static Mach-O audit; physical-device execution must be separately verified.

### Exit gate

Probe runs on actual Dopamine iOS 16.1.1 and `opencode-ios-smoke` prints `IOS_ROOTLESS_PORT_SMOKE_OK`. Record loader errors and any signing/entitlements required.

## Phase 1 — Bun runtime from macOS Darwin code

Clone pinned `oven-sh/bun`. Audit CMake, Zig, JavaScriptCore, libuv/posix OS abstraction, and all macOS-only linked frameworks. Build minimal Bun for `arm64-apple-ios16.0` using iPhoneOS SDK rather than macOS SDK; patch Darwin calls only where iOS differs. Investigate JIT and executable-memory requirements; prefer an interpreter/no-JIT mode if supported and stable. Do not assume `MAP_JIT` or arbitrary JIT entitlements are available to a rootless CLI. Prove sequentially: `bun --version`, simple JS, filesystem read/write, subprocess execution, HTTPS/TLS, and package loading. Document unsupported APIs.

### Exit gate

A native **iPhoneOS** `bun` runs basic JavaScript and filesystem/exec tests on the target iPhone.

## Phase 2 — OpenCode macOS ARM64 CLI source adaptation

Using the pinned OpenCode source and the upstream macOS ARM64 build route:

- Add a properly implemented iPhoneOS target in the port's build scripts (do not claim vanilla `bun-darwin-arm64` is an iOS target).
- Use iOS-compatible runtime; build for ARM64 iPhoneOS with real platform identification.
- Audit terminal raw mode, TTY sizing, child processes, path handling, symlink resolution, CA certs, DNS, TLS, file watchers and signals.
- Patch assumptions about home, cache, config and executable locations for rootless iOS.
- Make interface resilient when optional native libraries are absent.

### Exit gate

`opencode --version`, `opencode --help`, a local read-only repository analysis, and one user-approved file patch succeed on real device.

## Phase 3 — Port native dependencies

Bring up OpenTUI, persistent PTY, `node-pty` fallback if needed, watcher bindings, FFF / ffi-rs, and image processing. Each must be natively iPhoneOS-built or safely replaced; never bundle macOS `.dylib` and mark it as iOS. Prioritize robust non-TUI/headless mode if TUI stalls. Test SSH and NewTerm separately.

### Exit gate

Interactive TUI sessions survive resizing, Ctrl-C, shell tool calls, git operations, subprocess exits, and logout/reconnect.

## Phase 4 — Node path fallback (same macOS-derived OpenCode source)

If Bun cannot reasonably be ported, evaluate the upstream `build-node.ts` / `vite.node.config.ts` pathway on the same Darwin codebase. `node-ios` (Node 22) demonstrates a jailbroken iOS runtime but upstream OpenCode's Node SEA build is currently pinned to Node 26.4.0; incompatible runtime features must be assessed, not guessed. An iOS Node runtime and all native deps must pass actual device tests before declaring success.

Do not use Linux emulation, Android Termux, or macOS-only Mach-O patching as a substitute for a real iOS port.

## Phase 5 — Package and CI

After real OpenCode is operational:

- `iphoneos-arm64.deb` with bin at `/var/jb/usr/bin/opencode` and runtime/assets under `/var/jb/usr/lib/opencode/` or another justified rootless path.
- `Depends` reflects **actual** runtime linkage, not assumptions.
- `ldid -S` or a properly justified, least-privilege signing workflow. Never embed user API keys in the package.
- Run static audits on each native binary: Mach-O platform=2 (iOS), arm64 CPU, min OS <=16.1.1; inspect `otool -L` for macOS-only paths.
- Use GitHub Actions macOS runners. Include build logs, checksums, test results, reproducible pinned dependencies.

## Security & authentication

Store tokens outside the repository in user home, chmod 0600 as appropriate. Preserve the CLI's normal provider authentication. Do not bypass ChatGPT authentication or misrepresent ChatGPT ordinary chat limits as Codex/OpenCode limits. Avoid root execution by default; use `mobile` where possible. Restrict shell access to explicitly approved workspaces.

## Completion criteria

No `PASS` without evidence. Distinguish: CI builds; static checks; simulator; physical-device execution; provider integration; agent autonomy. Final PR includes exact compiler commands, patches, failure analysis, test reports, version matrix and `.deb` artifact only after proven functionality.
