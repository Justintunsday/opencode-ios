# Bun on iPhoneOS — feasibility audit (why the Bun runtime path is not used)

Status: **rejected for the shipping runtime**, kept as an audited alternative. See
`docs/RUNTIME_DECISION.md`.

This audit covers what it would take to ship OpenCode's primary distribution path — the
`bun build --compile` executable from `packages/cli/script/build.ts` — as a native iPhoneOS arm64
binary. All claims below were checked against the pinned sources (`UPSTREAM.lock`) or public
upstream issues; the empirical probe was run with Bun 1.4.2 (host Windows) and is repeated with the
pinned Bun 1.4.4 in CI.

## 1. No iPhoneOS target exists in the compile pipeline

`bun build --compile --target=<target>` supports exactly these targets (Bun docs
`docs/compiler/executables.mdx`, verified against the pinned Bun source):

```
bun-linux-x64          bun-linux-arm64         bun-linux-x64-musl        bun-linux-arm64-musl
bun-linux-x64-baseline-musl
bun-windows-x64        bun-windows-arm64
bun-darwin-x64         bun-darwin-arm64
```

Empirical probe:

```
$ bun build --compile --target=bun-ios-arm64 ./hello.ts --outfile hello-ios
error: Unsupported target "ios" in "bun-ios-arm64"
```

OpenCode's own build script (`packages/cli/script/build.ts`) hard-codes the same nine
`{os, arch}` combinations and casts the target string into `Bun.Build.CompileTarget`; there is no
`ios` case, and the CLI's runtime builder (`Bun.build({ compile: { target } })`) has no
iPhoneOS/SDK concept. A source port would have to add a new platform to Bun itself, not just to
OpenCode.

## 2. Upstream position

- `oven-sh/bun#339` ("How to build for the mobile platform?", **closed**): maintainers state an
  official embedding path is far away and, later, **"We will not be officially supporting
  Android/iOS for the foreseeable future."**
- `oven-sh/bun#21237` ("feat: mobile compiling support", **open** since 2025-07): no shipped iOS
  target; the only public attempt is an unofficial fork.

## 3. The only public Bun-on-iOS work is the wrong shape for this task

- `dannote/bun` branch `ios-port` (fork of a fork, ~3 stars) + `dannote/pi-ios`: runs Bun's
  JavaScriptCore with **`C_LOOP` interpreter only** (`ENABLE_JIT=OFF`, `ENABLE_WEBASSEMBLY=OFF`),
  as an **embedding library** (`bun_start`/`bun_eval`), requires **iOS 17.0+** (our target is
  iOS 16.1.1), and is ~10x slower than JIT. It does not produce a `bun` CLI and is not maintained
  for our target OS.
- Bun's runtime is written in Zig/C++ and links Apple platform/private frameworks beyond the
  iPhoneOS SDK's public surface; its build system would need a new cross-compilation toolchain
  (iPhoneOS SDK + Zig target + JSC build) — a compiler/runtime port, not a build-flag change.

## 4. Executable-memory / JIT restriction

Bun embeds JavaScriptCore and relies on JIT for acceptable performance. On iOS, `mmap`/VM
allocations of executable memory require both the `MAP_JIT` flag and the private
`dynamic-codesigning` entitlement (Apple grants it to system processes, e.g. WebKit's
JavaScriptCore). Jailbreak tooling (ElleKit) is a hooking framework — it does **not** grant JIT to
arbitrary processes. A JIT-enabled Bun CLI would depend on entitlement behaviour we cannot verify
on hosted CI and cannot guarantee on the user's device; the interpreter-only fork removes that
dependency but is iOS 17+ and not a CLI.

## 5. Concrete blockers summary

| Requirement | Bun status | Consequence |
| --- | --- | --- |
| `bun build --compile` iPhoneOS target | absent (9 targets, no iOS) | must port Bun's compiler/runtime |
| iPhoneOS SDK toolchain in Bun's build | no iOS configuration | new Zig/CMake cross-build |
| JSC JIT on iOS <sup>1</sup> | needs private entitlement | unsafe/unknown on device |
| iOS 16.1.1 support | unofficial port requires iOS 17+ | out of target range |
| CLI shape (not embedding) | unofficial port is a library | none available |
| Upstream maintenance | explicitly unsupported | no fixes/chase-path |

<sup>1</sup> The jailbroken-device JIT question is discussed in `docs/RUNTIME_DECISION.md`.
ElleKit is documented by its authors as a function hooker ("a JIT inline assembly implementation
for Swift" = its own assembler), not a general JIT entitlement provider.

## 6. What we ship instead

OpenCode's **official Node distribution path** from the same source tree, on a **native iPhoneOS
Node.js 22.9.0 runtime** we compile ourselves from the nodejs-mobile patch set. This satisfies the
task's requirement to use the native Node.js build as a documented fallback when Bun cannot be
made operational, while keeping the OpenCode CLI source, attribution and licensing unchanged.

The Bun audit is re-verified in CI by `test-port.yml`, which runs the pinned Bun 1.4.4 compile
target probe and records the failing target evidence in the verification report.
