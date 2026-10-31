# Runtime decision record — why a native iPhoneOS Node.js runtime

Status: **accepted** (stage 1). Related: `docs/ARCHITECTURE.md`, `docs/BUN_FEASIBILITY.md`,
`UPSTREAM.lock`.

## Question

OpenCode v2 ships two official distribution paths from the same TypeScript source tree:

- **Bun path** (`packages/cli/script/build.ts`): `bun build --compile` produces a single native
  executable that embeds the Bun runtime. Targets are fixed to linux/darwin/win32.
- **Node path** (`packages/cli/script/build-node.ts`): Vite produces an ESM bundle plus a Node SEA
  asset set. Node 26.4 is used as the SEA builder, but the bundle is ordinary Node-targeted
  JavaScript and upstream explicitly supports running it on a stock Node runtime
  (`build-node --bundle-only` emits exactly that).

The target device is an iPhone SE 2 on iOS 16.1.1 (Dopamine rootless), arm64.

## Options considered

### A. Source-port Bun to iPhoneOS (primary path suggested by the bootstrap)

Rejected after a concrete audit (`docs/BUN_FEASIBILITY.md`):

- `bun build --compile --target=` has exactly nine supported targets; none is iOS
  (`bun-linux-x64/arm64/musl`, `bun-windows-x64/arm64`, `bun-darwin-x64/arm64`).
- Upstream position: `oven-sh/bun#339` is closed — "We will not be officially supporting
  Android/iOS for the foreseeable future." `oven-sh/bun#21237` remains open.
- Bun's runtime requires JavaScriptCore with JIT; on iOS, MAP_JIT/RWX executable memory requires
  the private `dynamic-codesigning` entitlement, and Bun links Apple platform/private frameworks
  that are not part of the iPhoneOS SDK's public surface.
- The only public Bun-on-iOS work is `dannote/bun` (a 3-star fork) + `dannote/pi-ios`: an
  *embedding* library with JSC `C_LOOP` interpreter-only, WebAssembly disabled, **iOS 17+**
  (target device is iOS 16.1.1), ~10x slower. Not a CLI, not our target OS.
- Effort: a compiler/runtime port (Zig build system + JSC + libuv-like IO layer + Mach-O target
  plumbing) with no upstream support. Unbounded.

### B. Ship a prebuilt Node.js 18.20.4 iOS binary (existing community artifact)

`imcynic/nodejs-ios` ships a real `nodejs_18.20.4-1_iphoneos-arm64.deb`
(Mach-O arm64 `MH_EXECUTE`, platform iOS, minOS 13.0, links only `libSystem`/`libc++`), and
`imcynic/claude-code-ios` ships the same runtime with a large Node CLI — proof that a Node CLI can
run natively on jailbroken iOS. However:

- Node 18 is EOL, and the OpenCode bundle needs Node ≥ 22 semantics:
  `node:sqlite` `DatabaseSync` (22.5+), `module.registerHooks` (22.15+), modern ESM/`import.meta`
  features and a Vite target of `node26`.
- The artifact is a third-party binary-only build with no reproducible pipeline of our own.

Rejected as the shipped runtime (kept as a fallback reference and as evidence that the target
class is real).

### C. Build Node.js 22.9.0 for iPhoneOS ourselves from the nodejs-mobile patch set

Accepted. `nodejs-mobile/nodejs-mobile` branch `update22-9-0` is Node.js 22.9.0 with maintained
iOS/Android build patches; `tools/ios_framework_prepare.sh` documents the exact iOS configure
flags; `make` still produces the `node` CLI executable (`out/Release/node`), which the framework
release packaging simply does not ship. Build fixes required to compile Node 22.9 with a modern
Xcode are captured from nodejs-mobile PR #150 as a reviewable patch in
`patches/nodejs-mobile/`.

This gives us:

- A **native iPhoneOS arm64** `node` executable built against the real iPhoneOS SDK in CI.
- A **pinned, reproducible** pipeline (workflow + patch series + checksums) instead of a
  binary-only artifact.
- The upstream OpenCode **Node distribution path** used unchanged where possible; the iOS
  adaptation is a small patch set for asset layout and unavailable native add-ons.

## Node major-version reconciliation

Our runtime is Node 22.9.0; upstream builds the node bundle with Node 26.4 tooling. The gap is
handled explicitly and verified on CI host Node 22.9.0 before packaging:

| Node 26 feature used upstream | iOS runtime handling |
| --- | --- |
| `module.registerHooks` (Node ≥ 22.15) | patched: plugin virtual modules resolved at bundle time; local module hooks degrade to a safe error path |
| `--experimental-ffi` + `node:ffi` | not available in 22.9; ffi/fff paths are optional and already have an unavailable-proxy fallback upstream; dropped from launcher argv |
| `--use-system-ca` | not available in 22.9; not passed; TLS uses Node's bundled CA store (documented in KNOWN_LIMITATIONS) |
| `node:sqlite` unflagged (Node ≥ 22.13) | 22.9 supports it behind `--experimental-sqlite`; launcher passes the flag; verified by smoke test |
| WebAssembly (SEA asset extraction not used) | runtime built `v8_enable_webassembly=0` (nodejs-mobile PR #150 configuration). Wasm-based optional features (image processing, TUI tree-sitter highlighting) degrade; documented |

If the Node 22.9 bundle smoke tests reveal an API that cannot be patched, the escalation path is to
rebase the nodejs-mobile iOS patch set onto a newer Node 22.x/24.x LTS in a branch, which is
tracked as a known risk rather than silently switching runtimes.

## JIT policy

nodejs-mobile's documented iOS configuration builds `--v8-options=--jitless` and
`v8_enable_webassembly=0`; this is the runtime we ship for v1. Rationale:

- The iOS JIT entitlement path (`dynamic-codesigning`) is not verifiable on hosted CI, and a
  wrong assumption would produce a runtime crash or an unusable CLI on the user's device.
- The shipping precedent packages run Node on jailbroken iOS with restricted/absent JIT, and the
  task prioritises functional correctness over terminal/cosmetic performance.
- We still sign with a minimal entitlement set (recorded in the deb) so a future
  JIT-enabled build can be attempted without re-architecting; the launcher exposes
  `OPENCODE_IOS_NODE_FLAGS` for experimentation.

## Fallback / escalation

If the Node iOS build cannot be made to work in CI, fallback order is: (1) newer Node 22.x/24.x
rebase of the same patch set; (2) ship the community Node 18.20.4 runtime only with an explicitly
reduced feature set and a documented warning — never silently. Both are documented in
`docs/KNOWN_LIMITATIONS.md` as part of the port risk register.
