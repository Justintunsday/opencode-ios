# Codex mission — native OpenCode for jailbroken iOS, based on macOS ARM64

Act as a cross-platform systems engineer. Implement a genuine iPhoneOS ARM64 port of **OpenCode v2 CLI**, preserving the macOS ARM64 Darwin codebase as your primary source.

Target: iPhone SE 2, iOS 16.1.1, Dopamine rootless + ElleKit, NewTerm and SSH. Package: `iphoneos-arm64.deb`, installed beneath `/var/jb`, ultimately exposing `/var/jb/usr/bin/opencode`.

Use `UPSTREAM.lock` for pinned OpenCode and Bun sources. Review `PORTING_PLAN.md`, `packages/cli/script/build.ts`, `packages/cli/script/build-node.ts`, upstream platform-specific native dependencies and the official Bun source. Maintain a separate port repository and preserve upstream history/license.

**Do not** use Android binaries, Linux simulation, iSH, web wrappers, or a rename-and-resign of a macOS executable as the shipping solution. Build against the real iPhoneOS SDK and validate Mach-O platform and library linkage.

Implementation instructions:

1. Execute existing GitHub Actions toolchain probe. Test the probe on real iOS hardware if an available device connection exists; otherwise mark it `UNVERIFIED ON DEVICE`.
2. Attempt a source-level port of Bun from macOS Darwin ARM64 to iPhoneOS ARM64. Identify concrete iOS divergences and land minimal, reviewable patches. Test JS, TLS, filesystem, PTY and child processes on actual device.
3. Implement iPhoneOS target in OpenCode CLI's build scripts; do not invent support in upstream `Bun.Build.CompileTarget`. Assess native dependencies (`@opentui/core`, `@opencode/pty`, `@parcel/watcher`, fff, ffi-rs, image processing) and patch or provide feature-limited fallbacks.
4. If native Bun is blocked, investigate OpenCode v2's **macOS-derived Node build pathway** as a separately documented fallback. Do not quietly swap product/runtime without recording technical evidence and tradeoffs.
5. Implement secure and stable configuration/auth; API tokens are never hard-coded. Validate paths and default to unprivileged execution. Support OpenAI API / DeepSeek / compatible providers using official integrations.
6. Write deterministic iOS GitHub Actions build, sign and package pipelines with SHA256, architecture, load-command and dylib checks. Do not produce a fake OpenCode package containing only the smoke executable.
7. Demonstrate `opencode --version`, `opencode --help`, headless code analysis, local code editing and git operations, with real-device evidence before claiming full success.
8. Commit each stage to a new branch, create PR, attach compilation logs and tests. Do not merge automatically.

Deliverables: source diffs, reproducible workflows, risk register, real hardware test plan, actual rootless package if and only if functional, and explicit unresolved issues. Start now with stage 0, then progress through working gates. Do not claim a port is complete until it runs on the target device.
