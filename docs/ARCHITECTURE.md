# OpenCode iOS port — architecture

Status: **decision record for the port** (stage 1). This file is authoritative for the CI
workflows and patches in this repository.

## Target

| Property | Value |
| --- | --- |
| Device | iPhone SE (2nd gen), arm64 |
| OS | iOS 16.1.1 (20B101) |
| Jailbreak | Dopamine (rootless), ElleKit tweak injection |
| Terminals | NewTerm 3, SSH |
| Package arch | `iphoneos-arm64`, installed under `/var/jb` |
| Entry point | `opencode` in `PATH`, i.e. `/var/jb/usr/bin/opencode` |
| Final artifact | `OpenCode-iOS-rootless.deb` |

## Upstream pins (see `UPSTREAM.lock`)

- OpenCode: `anomalyco/opencode` `e8238bae9b807b72ecfc75afd3a9fe2e6b07b944` (v2.2.5, Bun 1.4.4 baseline, MIT).
- Bun: `oven-sh/bun` `d7d941c045fe75950910a93752603ca86c2731a4` (1.4.4) — used only for the
  OpenCode *host* build tooling; it is **not** the iOS runtime.
- Node.js mobile patches: `nodejs-mobile/nodejs-mobile` branch `update22-9-0`
  `106c51f95d55d1010de56a2ffd09bfb4ba819a47` (Node 22.9.0 source + iOS/Android patches, MIT),
  plus build fixes from `nodejs-mobile/nodejs-mobile` PR #150 (open at time of writing).
- iOS runtime: Node.js **22.9.0** compiled `arm64-apple-ios` (iPhoneOS SDK).

## Why Node.js and not Bun

OpenCode v2 ships two build paths:

1. `packages/cli/script/build.ts` — `bun build --compile` producing a native Bun executable per
   desktop platform. Targets are hard-coded to linux/darwin/win32; there is no iPhoneOS target and
   `Bun.Build.CompileTarget` has no iOS value.
2. `packages/cli/script/build-node.ts` — Vite ESM bundle (`opencode.mjs`) plus Node SEA assets,
   explicitly designed to run on stock Node.js. This is a supported, first-class distribution path
   for the same CLI source.

Bun's runtime is tightly coupled to JavaScriptCore's JIT, MAP_JIT executable memory, Apple
private/platform frameworks and a Zig/C++ build that has no iPhoneOS SDK configuration. Porting it
would be a multi-month compiler/runtime project (see `docs/BUN_FEASIBILITY.md` for the concrete
audit), while the task explicitly allows the native Node.js build path as the fallback when Bun
cannot be made operational. We therefore ship the **same OpenCode v2 CLI source** through its
official Node build path on a **native iPhoneOS Node.js runtime**, which is different from
emulation, translation, or remote execution.

## Component layout in the .deb

```
/var/jb/usr/bin/opencode                      # POSIX sh launcher (sets V8 flags, execs runtime)
/var/jb/usr/lib/opencode/runtime/node         # native iPhoneOS arm64 Node.js 22.9.0
/var/jb/usr/lib/opencode/runtime/entitlements.xml  # JIT/exec-mem entitlements used at build time
/var/jb/usr/lib/opencode/cli/opencode.mjs     # Vite ESM bundle of the upstream CLI
/var/jb/usr/lib/opencode/cli/assets/...       # SEA-equivalent assets (app-archive.bin, wasm, ...)
/var/jb/usr/share/doc/opencode/{README,LICENSE,copyright}
/var/jb/usr/share/opencode/VERIFICATION.md
```

Rootless convention: every path lives under `/var/jb`; `dpkg` on Dopamine maps `/var/jb` to the
rootless prefix. No files are written outside `/var/jb` on install.

## iOS adaptation surface

The port applies a small patch set to upstream OpenCode (kept in `patches/opencode/`, applied in
CI to a clean checkout of the pinned commit — upstream is never modified):

1. **Build target** — an `ios`/`ios-arm64` build target that selects the Darwin code paths, the
   iPhoneOS Node runtime and the installed asset directory layout.
2. **Node runtime bootstrap** — the generated `opencode.mjs` prelude is adapted for the
   non-SEA filesystem asset mode: no `node:sea` asset extraction, assets read from
   `OPENCODE_NODE_ASSETS_DIR` (the installed `cli/assets` dir), no `--experimental-ffi`, no SEA
   cache directory. Node 22.9 lacks `module.registerHooks`, so the plugin virtual modules are
   provided by build-time aliasing instead of the loader hook.
3. **Optional native dependencies** — none of the prebuilt Node native addons shipped by upstream
   (`@lydell/node-pty-*`, `@parcel/watcher-*`, `@ff-labs/fff-*`, `ffi-rs`) exist for iPhoneOS.
   They are made *optional* with safe fallbacks:
   - PTY: fall back to pipe-based `child_process` execution for shell tool calls (no
     interactive TTY allocation); `serve`/TUI terminal panes degrade gracefully.
   - File watcher: fall back to stat polling / watcher-less mode.
   - fff/ffi: upstream already ships an unavailable-proxy fallback; it is selected on iOS.
   - photon/wasm and web-tree-sitter: pure WebAssembly, kept (works with V8's Liftoff/WASM).
4. **iOS path/env defaults** — config/cache/data dirs under `$HOME` on the jailbroken device,
   `process.platform === "darwin"` quirks disabled where they assume macOS (open browser, system
   CA query via Security.framework is available on iOS, updater disabled for .deb installs).

## CI pipeline (GitHub Actions, macOS runners)

| Workflow | Responsibility | Artifact |
| --- | --- | --- |
| `build-runtime.yml` | Compile Node.js 22.9.0 for `arm64-apple-ios` from pinned nodejs-mobile source, sign with `ldid`, static Mach-O audit | `ios-node-runtime` |
| `build-opencode.yml` | Apply patches to pinned OpenCode, `bun install`, Vite node bundle, host-Node smoke tests (`--version`, `--help`), audit bundle | `opencode-cli-node-ios` |
| `package-rootless.yml` | Download latest successful runtime+bundle artifacts, assemble rootless tree, `dpkg-deb` build, checksums, static package audit | `OpenCode-iOS-rootless` (.deb + SHA256SUMS) |
| `test-port.yml` | Static validation suites (Mach-O platform/minos/arch, dylib linkage, rootless paths, package metadata, bundle smoke on host Node) | `port-verification` report |
| `ios-toolchain-smoke.yml` | Preserved stage-0 probe (bootstrap) | `ios-rootless-toolchain-probe` |

Device execution is **not** possible on the hosted macOS runners; every workflow states this
explicitly and writes the device test checklist to the verification report. No workflow claims
on-device success.
