# OpenCode CLI bundle for the iPhoneOS Node.js runtime

Status: **CI build + host-Node smoke + .deb package build verified; device execution pending**
(`UNVERIFIED ON DEVICE`). The first device attempt exposed a runtime capability gap (initial iPhoneOS runtime was built
`--with-intl=none` and without WebAssembly, which makes V8 reject the bundle's Unicode
property escapes at parse time and breaks Node's wasm-based `fetch` llhttp - see §11). The
runtime is now built with full-icu + WebAssembly + JIT; the CLI matrix on hardware is the
last step (§12).

This document describes how `.github/workflows/build-opencode.yml` produces the
`opencode-cli-node-ios` artifact: the OpenCode v2 CLI as a Vite ESM bundle that runs on
the native iPhoneOS Node.js **22.9.0** runtime shipped in the `.deb`.

Since Phase D the workflow also builds a **Node 26.13.0 real-TUI variant**
(`opencode-cli-node26-ios`) that ships the prebuilt OpenTUI iPhoneOS renderer
(`libopentui.dylib`) so `opencode` can start the real TUI through `node:ffi` instead of the
iOS line REPL. It is conditional and does not change the default Node 22 artifact; see §14.
Its end-to-end TUI is **UNVERIFIED ON DEVICE** (the dlopen precondition and the Node 26
JIT/WASM runtime are device-verified; the FFI-enabled runtime and the full TUI are not yet).

## 1. What the workload produces

Upstream OpenCode v2 ships two build paths (`docs/ARCHITECTURE.md`): a Bun-compiled
executable and `packages/cli/script/build-node.ts`, the official Node distribution path
(Vite ESM bundle, no Node runtime bundled). The port uses the Node path with
`--bundle-only`, so no SEA (single executable application) is built on the runner.

Artifact contract (default variant; consumed by `package-rootless.yml` / `test-port.yml`):

```
opencode-cli-node-ios/
  opencode.mjs            # ESM bundle, entry point (launcher: node <flags> <path>)
  assets/**               # app-archive.bin, attention sounds, tree-sitter wasm/scm, photon wasm
  bundle-manifest.json    # upstream/patch/bundle hashes, env contract, host smoke matrix
  SHA256SUMS              # sha256 of every payload file incl. bundle-manifest.json
```

Conditional variants produce the same layout under different artifact names:
`opencode-cli-node18-ios` (bundle for the device-proven Node 18.20.4 iPhoneOS runtime,
extra `assets/node18-sqlite/` payload; see §13) and `opencode-cli-node26-ios` (Node 26.13.0
+ `node:ffi` real-TUI bundle, extra `assets/@opentui/core-ios-arm64/libopentui.dylib`
renderer, see §14). The default Node 22 artifact is unchanged.

Pinned inputs (single source of truth: `UPSTREAM.lock`):

| Input | Pin |
| --- | --- |
| OpenCode source | `anomalyco/opencode` `e8238bae9b807b72ecfc75afd3a9fe2e6b07b944` (v2.2.5) |
| Host build tool | Bun `1.4.4` (`oven-sh/setup-bun`, not shipped to the device) |
| Device runtime (default) | Node.js `22.9.0` built for `arm64-apple-ios` (`build-runtime.yml`) |
| Device runtime (Node 18 hedge) | Node.js `18.20.4` iPhoneOS runtime (reference runtime, §13) |
| Build runner | `macos-15` (arm64) |
| Bundle target | `ios-arm64` (port patch; Darwin code path, iOS prelude/asset set) |

Download the artifact of a green run:

```bash
# default Node 22 bundle (primary deliverable)
gh run download <run-id> -n opencode-cli-node-ios -D dist/opencode-cli-node-ios
# Node 18 fallback hedge variant (§13)
gh run download <run-id> -n opencode-cli-node18-ios -D dist/opencode-cli-node18-ios
# Node 26 real-TUI variant (§14; needs the FFI-enabled Node 26 iPhoneOS runtime)
gh run download <run-id> -n opencode-cli-node26-ios -D dist/opencode-cli-node26-ios
# latest green build of this workflow:
gh run list --workflow build-opencode.yml -L 1 --json databaseId,conclusion
```

## 2. Pipeline

Workflow: `.github/workflows/build-opencode.yml` (`workflow_dispatch` + push paths
`patches/opencode/**`, `scripts/build-opencode-bundle.sh`, `src/opencode-ios/**`,
`UPSTREAM.lock`, the workflow itself). All steps delegate to
`scripts/build-opencode-bundle.sh` so the same commands run locally. Three jobs build three
artifacts from the same patch series:

- `bundle` → `opencode-cli-node-ios` (default Node 22.9 runtime bundle, primary deliverable);
- `bundle-node18` → `opencode-cli-node18-ios` (conditional Node 18.20.4 fallback hedge,
  `OPENCODE_IOS_NODE18=1`, extra sql.js payload; §13). It is independent and does not change
  the default artifact;
- `bundle-node26` → `opencode-cli-node26-ios` (conditional Node 26.13.0 real-TUI bundle,
  `OPENCODE_IOS_NODE26=1`, ships the prebuilt OpenTUI iPhoneOS renderer and needs the
  FFI-enabled Node 26 runtime; §14). It is independent and does not change the default
  artifact.

1. **fetch** — shallow-fetch the pinned upstream commit into `upstream-src/opencode`
   (gitignored; codeload tarball fallback if the shallow fetch fails). The checkout must
   stay at the pinned commit.
2. **patches** — apply `patches/opencode/*.patch` in filename order to the clean checkout.
3. **bun install --os=* --cpu=*`** — install the full platform asset set the upstream
   bundle build resolves (`@lydell/node-pty-*`, `@parcel/watcher-*`, …); `bun` is only the
   host build tool.
4. **build** — `OPENCODE_TARGET=ios-arm64 OPENCODE_IOS=1 bun run script/build-node.ts
   --bundle-only --skip-install`. Upstream runs `bun install` itself unless skipped; the
   workflow installs once explicitly. The run also builds the web app archive
   (`packages/app` Vite build) that is embedded as `assets/app-archive.bin`.
5. **stage** — copy `packages/cli/dist-node/{opencode.mjs,assets}` into the artifact dir
   exactly as the patched build produced them (no post-hoc filtering that could make the
   manifest lie). For the Node 26 variant `stage` also re-verifies the sha256 of the staged
   `assets/@opentui/core-ios-arm64/libopentui.dylib` renderer.
   Node 26-only extra steps: **deps-patches** (apply `patches/opencode/node-modules/*.patch`
   to the installed `@opentui/core` package after `bun install`) and **assetcheck** (host-Node
   unit check that the OpenTUI iOS asset key resolves to the staged renderer; §14).
6. **smoke** — download stock Node.js releases from nodejs.org (SHA-256 verified against
   `SHASUMS256.txt`) and run the bundle with a throw-away `HOME`:
   - required: `--version`, `--help` on **Node 22.9.0** (the shipped runtime version);
   - informational: Node `24.22.2` and `26.4.0`, plus the deeper no-network commands
     `debug paths`, `models`, `auth list`, `session list`;
   - a `node:sqlite` probe records whether `DatabaseSync` imports with/without
     `--experimental-sqlite` on every tested version.
7. **manifest + verify** — `bundle-manifest.json` (see §6) and `SHA256SUMS` are generated,
   then re-verified against the staged tree before upload.

Local reproduction (any POSIX host with bash + bun + python3, e.g. macOS):

```bash
bash scripts/build-opencode-bundle.sh fetch
bash scripts/build-opencode-bundle.sh patches
bash scripts/build-opencode-bundle.sh install
bash scripts/build-opencode-bundle.sh build
bash scripts/build-opencode-bundle.sh stage
bash scripts/build-opencode-bundle.sh smoke
bash scripts/build-opencode-bundle.sh manifest
bash scripts/build-opencode-bundle.sh verify
```

Useful environment overrides: `OPENCODE_TARGET`, `OPENCODE_UPSTREAM_DIR`,
`OPENCODE_ARTIFACT_DIR`, `OPENCODE_NODE_MATRIX`, `OPENCODE_SMOKE_REQUIRED`, `PYTHON`.
On hosts whose system temp directory is not writable by child processes, set
`OPENCODE_SMOKE_WORK_ROOT` to a workspace directory.

## 3. Patch series (`patches/opencode/`)

Patches are unified diffs (with a documented `#` header per file) against the pinned
upstream commit; each one is applied with `git apply` in CI. They are the only upstream
change surface — upstream itself is never modified.

| # | Patch | Files | Purpose |
| --- | --- | --- | --- |
| 0001 | `ios-node-target-and-prelude` | `packages/cli/src/node/target.ts`, `script/build-node.ts`, `script/node-assets.ts`, `vite.node.config.ts` | Adds the `ios-arm64` Node target; iOS asset collector (no macOS dylibs/addons/helpers); non-SEA iOS prelude (no `node:sea` import, no `module.registerHooks`, no `--experimental-ffi`, assets from `OPENCODE_NODE_ASSETS_DIR`, `/var/jb` PATH prefixes, `OPENCODE_IOS=1`); Node 22.9 HTTP content-length workaround; photon wasm module kept external/lazy so startup never instantiates wasm (works on wasm-less runtimes and avoids eager 1.9 MB wasm init). |
| 0002 | `node22-registerhooks-and-sqlite-fallback` | `packages/cli/src/util/process.ts`, `packages/plugin/src/source.node.ts`, `packages/util/src/runtime/import.node.ts` | `module.registerHooks` exists only in Node ≥22.15: namespace import + guarded call so startup never throws a link-time SyntaxError; plugin local-reload degrades but loads. Propagates `--experimental-sqlite` to self-spawned server children (required for `node:sqlite` on 22.9). |
| 0003 | `optional-native-modules-startup-safe` | `packages/core/src/pty/pty.node.ts`, `packages/core/src/image/photon-wasm.node.ts` | `node-pty` native addon does not exist on iPhoneOS; its top-level `require` is guarded (PTY unavailable, shell tool uses pipe-based `child_process`). Drops the `node:sea` import (bundle is non-SEA). Guards photon wasm artifact resolution so importing the image pipeline reports “unavailable” instead of throwing when the wasm artifact/JS glue or WebAssembly support is missing. |
| 0004 | `ios-shell-selection-and-git` | `packages/core/src/shell/select.ts`, `packages/core/src/util/git-executable.ts` | Rootless iOS has no `/bin/sh`,`/bin/bash`,`/bin/zsh`; shell resolution prefers `$SHELL` then `/var/jb/bin[/usr/bin]/{sh,bash,zsh}` etc. The agent shell tool spawns the resolved shell with `-c` (never Node's hardcoded `/bin/sh`). git is not part of the bootstrap → clear actionable error instead of ENOENT. |
| 0005 | `node22-sqlite-api-fallbacks` | `packages/core/src/database/sqlite.node.ts` | Node 22.9 `node:sqlite` lacks `StatementSync#setReturnArrays` and `DatabaseSync#loadExtension`: map object rows to column-ordered arrays when the API is missing, report extension loading as unavailable. Without this the embedded server answers 500 on `/api/info` and `/api/model`. |
| 0006 | `device-robustness` | `packages/cli/vite.node.config.ts`, `packages/core/src/persistent-pty/binary.node.ts`, `packages/core/src/ripgrep/binary.ts` | Rootless-iOS robustness: home-rooted `TMPDIR` fallback in the prelude (do not depend on `/tmp`), persistent-PTY capability reports `false` on ios (the daemon binary is not shipped), and a missing `rg` produces an actionable install hint instead of `unsupported platform for ripgrep: arm64-ios`. |
| 0007 | `node18-ios-compat` | `packages/cli/vite.node.config.ts`, `packages/cli/script/node-assets.ts`, `packages/core/src/provider.ts`, `packages/util/src/runtime/import.node.ts`, `packages/codemode/src/interpreter/objects.ts` | **Conditional Node 18 fallback variant** (`OPENCODE_IOS_NODE18=1`, separate artifact, §13). Node 18 prelude (`__filename`/`__dirname` from `import.meta.url`, global `crypto`, built-in polyfills for `toSorted`/`groupBy`/`withResolvers`/…, no `--experimental-sqlite`/`--disable-warning` flags, Vite target `node18`); maps `node:sqlite` to the sql.js-backed shim; `vm.constants` fallback for plugin imports; iterator-helper-free `mergeRecord`/codemode iterators (Node 18 predates `Iterator.prototype.map`). |
| 0008 | `node18-inspector-optional` | `packages/cli/vite.node.config.ts` | **Node 18 fallback only.** Inspector-less Node 18.20.4 iOS builds make the static `node:inspector` import in `cli/src/cpu-profile.ts` throw `ERR_INSPECTOR_NOT_AVAILABLE` at bundle link time (device-reported). Maps `node:inspector` to a build-time stub so startup succeeds and `SIGPROF` CPU profiling fails cleanly (handler logs and continues). Node 22 bundle untouched. |
| 0009 | `ios-standalone-direct-spawn` | `packages/cli/src/services/standalone.ts` | **iOS path.** On the device, `opencode run --standalone` never saw the child's readiness line through the Effect `ChildProcessSpawner`/`Stream` path (`Standalone server exited before reporting readiness`) although `serve --stdio --port 0` works when spawned with plain `node:child_process` (device-reported). When `process.platform === "ios"` or `OPENCODE_IOS=1`, spawn the server directly (stdin pipe kept open as lease, stdout pipe drained, stderr inherit when `OPENCODE_PRINT_LOGS=1`), resolve on the first JSON `{url}` stdout line, keep the child referenced, and enforce a 20s readiness timeout that kills the child and throws a clear error. Non-iOS behavior unchanged. |
| 0010 | `ios-child-node-flags` | `packages/cli/src/util/process.ts` | **iOS path (device-verified).** The v6 Node 22.9 iPhoneOS runtime only executes JIT/WebAssembly safely single-threaded (process-wide mprotect W^X toggle races background V8 threads → SIGBUS 138). The launcher passes `--single-threaded`, but `nodeFlags()` dropped it when building `selfCommand()`, so spawned `serve --service`/`serve --stdio` children crashed. Forwards `--single-threaded` and `--max-old-space-size=...` to children when present in the parent's `execArgv`; nothing is added unconditionally, so desktop behavior is unchanged (device proof: full CLI matrix + mock-provider agent turn pass; without the forwarding the children SIGBUS). |
| 0011 | `ios-tui-unavailable-guidance` | `packages/cli/src/util/ios.ts` (new), `packages/cli/src/commands/handlers/default.ts`, `packages/cli/src/commands/handlers/mini.ts` | **iOS path (device-reported).** Plain `opencode` and `opencode mini` crashed inside OpenTUI renderer init (`Unsupported OpenTUI Node asset target: ios-arm64` + native stack trace). The real TUI needs OpenTUI's Node binding, which loads its Zig core through `node:ffi` (Node >= 26.4 + `--experimental-ffi`); the Node 22.9 iOS runtime has neither. Both handlers now check `isIOS()` before starting the background server: the terminal path goes to the pure-JS REPL (patch 0012), the non-TTY path prints an actionable headless-CLI message to stderr and exits 1 with no stack trace. A defensive `Effect.catchCause` around the renderer entry points degrades future renderer-init failures to the same guidance. Non-iOS behavior unchanged. |
| 0012 | `ios-line-repl` | `packages/cli/src/ios-repl.ts` (new), `packages/cli/src/util/ios.ts`, `packages/cli/src/commands/handlers/default.ts`, `packages/cli/src/commands/handlers/mini.ts` | **iOS path.** Adds a pure-JS interactive line REPL for `opencode` (no args) and `opencode mini` when stdio is a TTY (node:readline, no OpenTUI/FFI imports): each line is sent through the same non-interactive run pipeline as `opencode run` (streamed assistant text, tool activity lines, auto-handled permission/questions, Ctrl-C interrupts the turn via the pipeline's SIGINT handling), session continuity across turns like `run -c`, `/help`/`/new`/`/exit`/Ctrl-D, errors return to the prompt instead of killing the loop. Non-TTY keeps guidance + exit 1. `TUI_UNAVAILABLE_MESSAGE` now explains the Node >= 26.4 + node:ffi requirement and the TTY/line-REPL alternative. Host-test hook `OPENCODE_IOS_REPL_ASSUME_TTY=1` exercises the REPL with piped stdio. Non-iOS behavior unchanged. |
| 0013 | `ios-repl-turn-lifecycle` | `packages/cli/src/ios-repl.ts`, `packages/cli/src/commands/handlers/default.ts`, `packages/cli/src/commands/handlers/mini.ts`, `packages/cli/src/run/run.ts`, `packages/cli/src/services/standalone.ts` | **iOS path (device-reported).** The patch-0012 REPL resolved its server once and reused that connection for every turn; after the first device turn the transport died (`Transport: terminated`) and later turns failed with `Transport: fetch failed` without reaching the provider. The REPL now takes a `resolveServer()` closure and resolves a **fresh connection per turn/attempt**, exactly like separate `opencode run` processes: with `--standalone` each turn gets its own private stdio server (disposed through a new `close()` on the owned endpoint); with the managed service it re-discovers/reconnects per turn. One automatic retry per turn on transport-class failures (caught through the new internal `onError` hook plus captured pipeline stderr: transport/fetch failed/terminated/socket/ECONNRESET/EPIPE/network), with a short `Retrying turn...` line. The first prompt waits for a healthy resolution because resolution happens inside the turn. Headless behavior is unchanged. |
| 0014 | `ios-repl-retry-budget` | `packages/cli/src/ios-repl.ts` | **iOS path (device-reported).** The patch-0013 REPL retried a failed turn only once (2 attempts), but device turn 1 (and occasionally turn 3) still failed both attempts (`Transport: fetch failed` then `Transport: terminated`), losing that prompt. The transport retry budget is now **2 retries per turn (3 attempts)** with a 1 s delay between attempts (each attempt resolves a fresh server connection); the first turn also waits a short 300 ms warm-up after the first private server resolves (device evidence: turn 1 is the flakiest). The `Transport error: …` / `Retrying turn...` lines are unchanged and the reason text prefers the real transport/error line. Failures that persist across all attempts still return to the prompt cleanly. |

| 0015 | `ios-opentui-native-asset` | `packages/cli/script/node-assets.ts` | **Phase D Node 26 variant.** The iOS asset collector stages the prebuilt OpenTUI iPhoneOS renderer dylib (path supplied via `OPENCODE_OPENTUI_IOS_DYLIB` from the `opentui-ios-renderer` artifact) under the asset key `@opentui/core-ios-arm64/libopentui.dylib`, and requires the variable when `OPENCODE_IOS_NODE26=1`. Node 22/18 builds do not set the variable, so their asset set is unchanged (no macOS/iPhoneOS dylib is shipped for them). |

| 0016 | `ios-tui-when-ffi-available` | `packages/cli/src/util/ios.ts`, `packages/cli/src/commands/handlers/default.ts`, `packages/cli/src/commands/handlers/mini.ts`, `packages/cli/vite.node.config.ts` | **Phase D.** 0011/0012 made every iOS build take the line-REPL/guidance fallback unconditionally. With the FFI-enabled Node 26 iPhoneOS runtime + staged renderer the real TUI must be attempted: the handlers probe `node:ffi` lazily (`hasNodeFFI()`: `createRequire` from `node:module`, guarded) and only fall back when FFI is unavailable, so the FFI-less Node 22 path is unchanged. `isTUIRendererUnavailable` also recognizes renderer-asset errors (`Missing OpenTUI asset`, `OpenTUI native library does not exist`). The iOS prelude carries an `IOS_TUI_FFI_GATE` marker that the node26 bundle build statically asserts (together with `hasNodeFFI`, `runIOSRepl`, `node:ffi`). |

A second, post-install patch group lives in `patches/opencode/node-modules/` (applied by
`scripts/build-opencode-bundle.sh deps-patches` after `bun install`, Node 26 variant only,
because it patches the *published* `@opentui/core` package rather than the upstream source):
`0001-opentui-core-ios-native-asset.patch` adds the `ios` native-asset platform to the
OpenTUI 0.8.0 compiled JS (`NATIVE_FILE_NAMES.ios = "libopentui.dylib"`), reads the renderer
source from `OPENCODE_OPENTUI_IOS_DYLIB` at build time, and adds a defensive
`darwin -> ios` platform fallback in the runtime FFI loader for a Node 26 iOS runtime that
still reports `process.platform === "darwin"` (known regression; an FFI rebuild will report
`ios` directly). Patch series/dependency-group SHA-256 values are recorded in
`bundle-manifest.json` (`patches.series_sha256`, `patches.dependency_series_sha256`), so a
consumer can tell exactly which series produced the artifact.

## 4. CI runs (honest log)

| Run | Commit | Result | Notes |
| --- | --- | --- | --- |
| [41171615578](https://github.com/Justintunsday/opencode-ios/actions/runs/41171615578) | `37fc62c` | failure | First stock build. Build/stage/upload steps succeeded; smoke failed on a bug in the new `host_smoke.py` stock-Node archive extraction (version dots in `node-v22.9.0-darwin-arm64`). Fixed in `9b74a90`. |
| [41172138603](https://github.com/Justintunsday/opencode-ios/actions/runs/41172138603) | `9b74a90` | **success** | Stock upstream bundle baseline (no patches, target `darwin-arm64`). Node 24/26 passed `--version`/`--help` and all deeper commands; Node 22.9 failed as expected (`SyntaxError: node:sea does not provide an export named 'getAssetKeys'`, exit 1) — this is why the iOS patch series exists. Artifact sha256 (opencode.mjs) `d706daffa028e779e5c876a4b9edc11fa3867b162c61d1ab38337a1aca31728a`. |
| 41174945683 | `bede0f8` | **success** | First patched iOS build (`ios-arm64`, 5 patches); required smoke version is the shipped Node 22.9.0. All 18 host-Node smoke commands passed (6 commands × Node 22.9.0 / 24.22.2 / 26.4.0), sqlite probe shows `--experimental-sqlite` required on 22.9.0 only. Artifact: `opencode.mjs` 21,388,775 bytes, sha256 `bb52eed4607adffbb7fbf4a052e0799b7616fd0511b80d3a395d6876ebc23907`; 22 assets (31.36 MB), 0 native binaries; patch series sha256 `76f1b66c4c0ff6906848186902bfd0566dc416a2b3897f1f9e2d241bf8fb42d9`. |
| [41176539017](https://github.com/Justintunsday/opencode-ios/actions/runs/41176539017) | `14a5d9f` | **success** | First 6-patch build: adds patch 0006 (TMPDIR fallback, persistent-PTY capability false, ripgrep install hint). 18/18 host-Node smoke commands passed; asset tree byte-identical to the previous run (`06ef5eb6…`, 22 files / 32,881,480 bytes — deterministic). Artifact: `opencode.mjs` 21,389,137 bytes, sha256 `69ce398b9d60bca0d93110417a91f910962e722b48271c3da58c8e5d8f7657ce`; patch series sha256 `5cb5ceb52c96c7631010de11e13dfc10774d2fd627adcb274b599e1756360c4a`. This payload is the one packaged into the green `.deb` (package run 41185611403). |
| [41192939688](https://github.com/Justintunsday/opencode-ios/actions/runs/41192939688) | `2179099` | **success** | Documentation-only correction of runtime-capability text in the patch comments and `bundle-manifest.json` (WebAssembly/JIT now provided by the runtime; wasm payloads remain lazy). **Bundle payload is byte-identical to run 41176539017**: `opencode.mjs` sha256 `69ce398b…`, same 22-file asset tree. 18/18 host-Node smoke commands passed; patch series sha256 `02b80588924db742…`. |
| [41266035760](https://github.com/Justintunsday/opencode-ios/actions/runs/41266035760) | `be216d3` | **success** | Adds patch 0007 + the conditional Node 18 fallback variant; **both jobs green**. Default Node 22 artifact: `opencode.mjs` 21,389,249 bytes, sha256 `2e506a36eca415a158600302319b7ab3c4830c6ee661f37675eb835904fad8d9` (bundle changed only because 0007 removes iterator helpers in shared code), 22 assets (32,881,480 bytes), required Node 22.9.0 smoke 18/18. Node 18 fallback artifact `opencode-cli-node18-ios`: `opencode.mjs` 21,393,413 bytes, sha256 `f1ef6ea78f3fb80417f28040bbddb6f8bbf902376e69a35a26d37a459ce82018`, 24 assets (33,614,156 bytes incl. sql.js), required Node 18.20.4 smoke 12/12 (plus Node 22.9.0 informational 6/6). Patch series sha256 `628a195774f7bd6a…`. |
| [41269585090](https://github.com/Justintunsday/opencode-ios/actions/runs/41269585090) | `38faf40` | **success** | Adds patch 0008 (`node:inspector` stub for the Node 18 variant) after the first device startup attempt hit `ERR_INSPECTOR_NOT_AVAILABLE` at bundle link. **Both jobs green**; default Node 22 artifact **byte-identical** to the previous run (`opencode.mjs` sha256 `2e506a36…`, 22 assets); Node 18 fallback artifact `opencode-cli-node18-ios`: `opencode.mjs` 21,393,629 bytes, sha256 `9256f2caf2e475f9f37bf4fe47881bca1cc4c5a9580efe329cdcb46b16d04cdf`, 24 assets, 8 patches (series sha256 `de9fa7eb52a34850…`), required Node 18.20.4 smoke passed (+ Node 22.9.0 informational). On device this artifact then ran `--version`/`debug paths`/`debug config`/`models`/`session list` successfully; `run --standalone` was still blocked (patch 0009). |
| [41271384704](https://github.com/Justintunsday/opencode-ios/actions/runs/41271384704) | `d66bac7` | **success** | Adds patch 0009 (iOS direct `node:child_process` standalone-server spawn for `opencode run --standalone`) after the device-reported readiness failure. Both jobs green. Node 18 fallback artifact `opencode-cli-node18-ios`: `opencode.mjs` 21,395,457 bytes, sha256 `25f5f4f39f8fead79a349d170ce1d644ca2890a3555055a6aa8f2e91434c9286`, 24 assets (33,614,156 bytes), 9 patches (series `f56cfd572e74d58f…`), required Node 18.20.4 smoke passed (+ Node 22.9.0 informational); local host `run --standalone` resolves the server and reaches model resolution. Default Node 22 artifact rebuilt with shared-code change: `opencode.mjs` sha256 `e3746a991f21741d23eebc68226419fd5fc46e88b8af8db904fd2cf29bbc4d84`, 22 assets, Node 22.9.0 smoke green (device path unchanged unless `process.platform === "ios"`). Device retest pending. |
| [41273112229](https://github.com/Justintunsday/opencode-ios/actions/runs/41273112229) | `266730a` | **success** | Adds patch 0010: forward `--single-threaded`/`--max-old-space-size=` to spawned server children (device-verified direction: without forwarding the `serve --service` child SIGBUSes on the v6 Node 22.9 runtime). Both jobs green, 10 patches (series `6fc8c51a9d5ffe73…`). Default Node 22 artifact: `opencode.mjs` 21,391,147 bytes, sha256 `2e916ffad16fb7ae2b71d4446a527d1fa11ec82e94d7cd12932373d734cbd410`, 22 assets, required Node 22.9.0 smoke 18/18; manifest launcher argv now `node --single-threaded --experimental-sqlite …`. Node 18 fallback: `opencode.mjs` 21,395,527 bytes, sha256 `5e0fa4f5fc4185e827da9f69a6c3d6d6147b33eeec8bc54d409057eb0ed4e8a4`, 24 assets, required Node 18.20.4 smoke passed. Local host check: child command line inherited `--single-threaded --max-old-space-size=1536 --no-warnings`. |
| [41278475579](https://github.com/Justintunsday/opencode-ios/actions/runs/41278475579) | `15f27fa` | **success** | Adds patch 0011 (iOS TUI/`mini` headless guidance instead of OpenTUI renderer crash). Both jobs green, 11 patches (series `ea1a11182447d4d6…`). Default Node 22 artifact: `opencode.mjs` 21,392,407 bytes, sha256 `484b2c1c6b8d932e5cde74d197b260e73abf8e25600f38d79239c6a8abf60f9d`, 22 assets, required Node 22.9.0 smoke passed. Node 18 fallback: `opencode.mjs` 21,396,787 bytes, sha256 `756b9b01599147f32bb331707ec8c4835d68ccd6905c8dc307dec1cf7a0a16a5`, 24 assets, required Node 18.20.4 smoke passed. Verified on the CI artifacts with matching host runtimes: `opencode` and `opencode mini` exit 1 with the guidance text, no stack frames, no `Starting background server` line. |
| [41284206666](https://github.com/Justintunsday/opencode-ios/actions/runs/41284206666) | `bb386ba` | **success** | Adds patch 0012 (pure-JS iOS line REPL for `opencode`/`opencode mini`; real TUI needs Node >= 26.4 + node:ffi and is impossible on Node 22.9) plus a sql.js shim flush-retry fix for Node 18. Both jobs green, 12 patches (series `ffa915acdcf7a658…`). Default Node 22 artifact: `opencode.mjs` 21,396,302 bytes, sha256 `ee15a9b185656e3c52350aa286986266e4677b6d851fb8a15036f72bfdef7fac`, 22 assets, required Node 22.9.0 smoke passed (+24.22.2/26.4.0). Node 18 fallback: `opencode.mjs` 21,400,899 bytes, sha256 `6208f99dd2256eafd7eaa4e16475d736aa7c3a8fda49057d3b9d03f3a1e0fc29`, 24 assets, required Node 18.20.4 smoke passed. Verified on the CI artifacts with matching host runtimes: non-TTY no-arg prints the guidance (TTY/node:ffi wording) and exits 1 with no stack; forced-TTY REPL handles `/help`, unknown `/cmd`, `/new`, `/exit` and exits 0 with no OpenTUI crash. Device PTY/mock-provider acceptance pending. |
| [41288234583](https://github.com/Justintunsday/opencode-ios/actions/runs/41288234583) | `1cbf01c` | **success** | Adds patch 0013: iOS REPL turn lifecycle (fresh server connection per turn/attempt, per-turn private `--standalone` server disposed via `close()`, managed-service re-discover, transport-class retry with `Retrying turn...` line, first prompt waits for readiness), fixing the device-reported `Transport: terminated` / `Transport: fetch failed` from turn 2. Both jobs green, 13 patches (series `f2411070ce57768b…`). Default Node 22 artifact: `opencode.mjs` 21,397,471 bytes, sha256 `b5ed68a445def947412e309d395c069dff41874eb7f2d734fa236cb7d6a2b3d6`, 22 assets, required Node 22.9.0 smoke passed. Node 18 fallback: `opencode.mjs` 21,402,068 bytes, sha256 `0bfdf8f5c8699d828e10c1fc23bbcc8ed0b29c0309f99624a014bfb1fa729df7`, 24 assets, required Node 18.20.4 smoke passed. Host mock-provider E2E on **both CI artifacts**: 4 consecutive REPL prompts all reached the provider on fresh servers, shell-tool marker written, E2E_OK ×4, `/exit` exit 0, no leftover children; managed-service mode also 4/4; retry path verified with an unreachable provider (one `Retrying turn...` line, clean error, loop survives). Device PTY run then showed turn 1 (and occasionally 3) still failing both attempts → patch 0014. |
| [41291337297](https://github.com/Justintunsday/opencode-ios/actions/runs/41291337297) | `4cfa9f4` | **success** | Adds patch 0014: iOS REPL turn retry budget 2 retries / **3 attempts** per turn with 1 s spacing, plus a 300 ms first-turn warm-up after the first private server resolves (device-reported turn-1 flakiness). Both jobs green, 14 patches (series `48b88cd92526be79…`). Default Node 22 artifact: `opencode.mjs` 21,397,681 bytes, sha256 `e99ac8d12f083539289fbeeb6ddc07a40348e8eec0db3a76c3d628409a826950`, 22 assets, required Node 22.9.0 smoke passed (+24.22.2/26.4.0). Node 18 fallback: `opencode.mjs` 21,402,278 bytes, sha256 `19a09a47c27446dd53eda82425efb61784ece535d147bc5b648f78c303d571e1`, 24 assets, required Node 18.20.4 smoke passed. Host verification: total provider outage → one prompt made exactly 3 attempts (2 `Retrying turn...` lines) then returned cleanly to the prompt, `/exit` 0; clean mock E2E on **both CI artifacts** again 4 prompts / E2E_OK ×4 / shell-tool marker / exit 0. Device PTY acceptance pending in v2.2.5-ios.5. |

The workflow never claims device success: `bundle-manifest.json` always records
`verification_status.device_verified = false` and the runner only executes stock host
Node binaries.

### Integration with the packaging workflow

`package-rootless.yml` resolves the latest successful run of this workflow, downloads
`opencode-cli-node-ios` and verifies it before assembling the `.deb`.

**Latest package build (green):**
[41185611403](https://github.com/Justintunsday/opencode-ios/actions/runs/41185611403) —
`OpenCode-iOS-rootless.deb` sha256 `13a0483d817a03d2f9a3b706526546289328cd62e60a0cac32243d2b03f0ae24`,
50,315,864 bytes; verification `passed=44 failed=0 skipped=1`, `ci_status=PASS`,
`device_status=UNVERIFIED ON DEVICE`. Provenance: CLI run
[41176539017](https://github.com/Justintunsday/opencode-ios/actions/runs/41176539017) (this
workflow, `opencode.mjs` sha256 `69ce398b…`, verified byte-identical in the package) +
full-icu runtime run 41184686029. CLI-side evidence from that run:

| Check | Result |
| --- | --- |
| `pkg.bundle-manifest` — manifest hashes consistent against packaged files | PASS |
| `cli.artifact-policy` — iOS candidate (patch series + required Node 22.9 smoke) | PASS |
| `cli.native-assets` — no desktop Mach-O binaries shipped as CLI assets | PASS |
| `cli.assets-contract` — non-SEA assets directory wired up | PASS |
| `cli.host-node-smoke` — bundle/launcher run on host Node.js 22.9.0 (7/7 checks) | PASS |
| `pkg.verbatim-copy` — packaged CLI files byte-identical to the artifact | PASS |
| `runtime.build-profile` — runtime built with `--with-intl=full-icu` (Intl/\p{} capable) | PASS |
| host Node provenance/version (nodejs.org checksum, pinned 22.9.0) | PASS |

An earlier package run
([41177665245](https://github.com/Justintunsday/opencode-ios/actions/runs/41177665245))
failed only on `runtime.entitlements*`/`runtime.build-profile` from the then-current runtime
artifact; those are runtime-owned and now pass.

The `.deb` is ready to install on the device; the CLI device matrix is still
**UNVERIFIED ON DEVICE** until the Lead's device run is recorded (§12).

## 5. Host-Node smoke matrix

Smoke tests execute the staged `opencode.mjs` on **stock Node.js** binaries on the build
host with a throw-away `HOME`. They prove the JavaScript bundle links, the CLI starts and
its embedded server boots; they are **not** device verification (the iPhoneOS runtime has
`process.platform === "ios"`, ships no PTY/watch/ffi native addons, and its JIT/WebAssembly/
ICU capabilities come from the runtime build rather than from this bundle).

Stock upstream bundle (CI run 41172138603, target `darwin-arm64`, no patches):

| Node | `--version` | `--help` | `debug paths` | `models` | `auth list` | `session list` | sqlite probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 22.9.0 | FAIL (node:sea link error) | FAIL | skipped | skipped | skipped | skipped | ok with `--experimental-sqlite` |
| 24.22.2 | PASS | PASS | PASS | PASS | PASS | PASS | ok without flag |
| 26.4.0 | PASS | PASS | PASS | PASS | PASS | PASS | ok without flag |

Patched iOS bundle (target `ios-arm64`, 6 patches, CI run 41176539017 on the macos-15
runner, embedded verbatim in the artifact's `bundle-manifest.json`):

| Node | `--version` | `--help` | `debug paths` | `models` | `auth list` | `session list` | sqlite probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 22.9.0 (required) | PASS | PASS | PASS | PASS | PASS | PASS | ok with `--experimental-sqlite` (flag required) |
| 24.22.2 | PASS | PASS | PASS | PASS | PASS | PASS | ok without flag |
| 26.4.0 | PASS | PASS | PASS | PASS | PASS | PASS | ok without flag |

18/18 smoke commands passed. The same matrix was reproduced on the development host
(Windows x64, stock Node 22.9.0 + `--experimental-sqlite`) with identical results before
the CI run.

Local dev-host failures that drove patches 0001/0005 (kept for future maintainers): before
patch 0005 the embedded server returned HTTP 500 (`TypeError: setReturnArrays is not a
function`); before patch 0001’s HTTP workaround the embedded server looped on
`ERR_HTTP_CONTENT_LENGTH_MISMATCH`. Both are Node-22.9-specific failure classes.

Additional host check (same development host, Node 22.9.0): `opencode serve --port 0
--hostname 127.0.0.1` boots the embedded server and serves the web app from
`assets/app-archive.bin` — `GET /` returns HTTP 200 HTML; `/api/*` requires authentication
(HTTP 401 without credentials, by design). This exercises the non-SEA app-assets path of
patch 0001 end-to-end.

## 6. bundle-manifest.json

Key fields (all values are computed from the real build/stage output):

- `upstream` — repository, pinned commit, OpenCode version.
- `patches` — ordered patch file names, per-file sha256 and `series_sha256`.
- `build` — target (`ios-arm64`), `ios_prelude` (detected from the iOS prelude marker in
  the bundle, not from an env var), bun version, host OS/arch/Node, CI run URL.
- `bundle.opencode_mjs` — path, bytes, sha256.
- `bundle.assets` — count, bytes, tree sha256, per-file sha256/category
  (`app-archive`, `audio`, `wasm`, `data`, `native-binary`). `native-binary` must be 0 for
  a shippable iOS artifact; the stock baseline manifest records the 7 native files it had.
- `runtime_bootstrap_signatures` — shebang, presence of an `ios_prelude` marker, whether
  the bundle has a *named* `registerHooks` import from `node:module` or a named
  `node:sea` asset-API import (both would make Node 22.9 throw at module link time), and
  whether the prelude shebang passes `--experimental-ffi`. These are the cheapest static
  guards against regressing the iOS prelude.
- `env_contract` — exactly what the `.deb` launcher must provide (see §7; the Node 26
  variant's contract is in §14: `--single-threaded`, no `--experimental-sqlite`, node:ffi
  default-on, `OTUI_ASSET_ROOT`).
- Node 26 variant only: `build.runtime_node_version = 26.13.0`, `build.ffi`
  (`node:ffi` default-on, renderer loaded via dlopen), `patches.dependency_*` (the
  post-install `@opentui/core` patch group), and a top-level `opentui_renderer` block with
  the `asset_key`, bytes, sha256, expected sha256 and `sha256_matches_expected` for
  `assets/@opentui/core-ios-arm64/libopentui.dylib`; the asset is categorized
  `ios-native-library` (not `native-binary`).
- `smoke` — the full host smoke report embedded verbatim (required + informational
  commands, flags, exit codes, captured output, sqlite probes).
- `verification_status` — `host_smoke_required_passed`, required Node version,
  `device_verified: false` with the CI/device disclaimer.

## 7. Device runtime contract (for the .deb launcher)

`package-rootless.yml` builds `/var/jb/usr/bin/opencode`; the wrapper must launch the
bundle as:

```sh
exec /var/jb/usr/lib/opencode/runtime/node \
  --single-threaded \
  --experimental-sqlite \
  --disable-warning=ExperimentalWarning \
  --no-warnings \
  --max-old-space-size=1536 \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

- `--experimental-sqlite` is **required**: on Node 22.9 `node:sqlite` (used for
  `DatabaseSync`, session storage) is flag-gated. Do **not** pass `--experimental-ffi` or
  `--use-system-ca`; neither exists on Node 22.9.0.
- `--single-threaded` is **required on the v6 iPhoneOS Node 22.9 runtime** (device-verified):
  V8's JIT/WebAssembly code-memory W^X toggle is process-wide (mprotect RW<->RX) and
  background V8 threads race it, so a multithreaded process dies with SIGBUS (138) on the
  first optimized loop or `fetch`. `--no-concurrent-recompilation` is an accepted alternative.
  The CLI forwards `--single-threaded` and `--max-old-space-size=` to every spawned server
  child (patch 0010), so passing them once on the launcher is sufficient — device proof:
  without forwarding the child `serve --service` died with SIGBUS and `models`/`debug config`
  failed; with it the full matrix and the mock-provider agent turn pass.
- For the **Node 18 fallback variant** (§13) the launcher must instead pass `--no-warnings`
  and must not pass `--experimental-sqlite`/`--disable-warning` (Node 18 rejects them and has
  no `node:sqlite`; the bundle ships a sql.js shim). The variant's exact argv is recorded in
  its `bundle-manifest.json.env_contract`; `--single-threaded` is forwarded if supplied but is
  not required by that runtime.
- For the **Node 26 real-TUI variant** (§14) the launcher must pass `--single-threaded`
  (same V8 W^X requirement) and must not pass `--experimental-sqlite`. `node:ffi` is
  default-on in Node 26.13.0, and the shipped runtime must be the **FFI-enabled** Node 26
  build (not the `--without-ffi` Phase A/B fallback). The renderer asset must be installed
  under the rootless `/var/jb` prefix; its exact argv and asset key are in §14 / the
  variant's `bundle-manifest.json.env_contract`.
- The runtime **must be built with ICU** (`--with-intl=full-icu`, used by `build-runtime.yml`;
  `small-icu` would also work). A runtime built `--with-intl=none` cannot run the bundle at
  all: V8 without ICU rejects `\p{...}` regex property escapes at parse time and `Intl` is
  undefined (device-reported; see §11). `build-runtime.yml` gates on
  `v8_enable_i18n_support=1` and statically linked ICU so a no-ICU runtime is rejected.
- The runtime needs **WebAssembly and JIT** support (`build-runtime.yml` enables both):
  Node 22.9's built-in `fetch`/undici HTTP client uses a WebAssembly llhttp parser, and a
  `--jitless` build cannot instantiate wasm, so provider HTTPS calls fail without them. The
  CLI bundle itself does not require WebAssembly at startup (photon/tree-sitter payloads are
  lazy), but the agent's model calls need `fetch` working. Runtime capabilities are reported
  in the runtime manifest, not in this bundle.
- The prelude sets `OPENCODE_NODE_ASSETS_DIR` to `<bundle dir>/assets` by default. If the
  wrapper sets it explicitly (recommended: `/var/jb/usr/lib/opencode/cli/assets`) the
  prelude respects the override. `OTUI_ASSET_ROOT` is set from the same root.
- The prelude sets `OPENCODE_IOS=1` if not already set, and (when
  `process.platform === "ios"`) prepends `/var/jb/bin`, `/var/jb/usr/bin`,
  `/var/jb/usr/sbin`, `/var/jb/sbin` to `PATH` if missing.
- `HOME` must be a writable directory (device: `/var/jb/var/mobile`); config/cache/data
  then default under `$HOME/.config/opencode`, `$HOME/.cache/opencode`,
  `$HOME/.local/share/opencode`. `TMPDIR` must be writable; if the launcher does not set
  it, the prelude derives `$HOME/.cache/opencode/tmp` on ios (patch 0006) instead of
  relying on `/tmp`.
- Self-spawned server children inherit the parent's `--experimental-sqlite` via
  `packages/cli/src/util/process.ts` (patch 0002); the launcher does not need to export
  `NODE_OPTIONS`.

## 8. Known degradations on iPhoneOS (documented, not silent)

These follow from the runtime capabilities and from what the artifact intentionally does
not contain; they are patched to degrade gracefully rather than crash:

| Feature | Behaviour on iPhoneOS | Evidence |
| --- | --- | --- |
| PTY-backed terminals (`@lydell/node-pty`) | unavailable; interactive terminal panes cannot spawn a PTY. PTY creation fails with a clear error; the rest of the CLI is unaffected. | startup guard patch 0003 |
| Persistent PTY (`@opencode/pty` Rust binary) | binary not shipped for iPhoneOS; the server reports `persistentPty: false` so clients do not attempt it (patch 0006). | asset set excludes it |
| File watcher (`@parcel/watcher`) | native binding absent → no native watcher; consumers already fall back (watcher-less). | upstream fallback + asset set |
| Image resize (photon WebAssembly) | unavailable in v1: the port deliberately keeps the `@silvia-odwyer/photon-node` wasm-bindgen JS module external/lazy and the single-file bundle does not ship that JS glue nor the photon worker entry, so `photon-normalize` reports “unavailable” and image files pass through unchanged. (WebAssembly itself is available on the shipped runtime; enabling image resize needs a follow-up patch that ships the photon JS payload.) | patch 0003 + prelude does not set `OPENCODE_PHOTON_WASM_PATH` |
| TUI syntax highlighting (web-tree-sitter wasm) | tree-sitter wasm payload is included and WebAssembly is available on the shipped runtime; the TUI renderer itself is unavailable (see next row), so syntax highlighting only matters if the TUI is ever brought up. | asset set + TUI renderer gap |
| TUI renderer (`@opentui/core` native library) | the real TUI cannot run on iPhoneOS: OpenTUI's Node binding loads its native core via `node:ffi` (Node >= 26.4 + `--experimental-ffi`), and the shipped runtime is Node 22.9 without `node:ffi`. In a terminal, `opencode` (no args) and `opencode mini` fall back to a pure-JS **line REPL** (readline, streaming text + tool lines, `/help`, `/new`, `/exit`, Ctrl-C cancels a turn, session continuity; patch 0012). Non-TTY invocations print the headless-CLI guidance and exit 1 (patch 0011/0012). Headless CLI (`run`, `serve`, `models`, …) is otherwise unchanged. | patch 0011/0012 + asset set excludes the dylib |
| grep/glob (ripgrep binary) | no `rg` in the artifact; the tool reports an actionable error (patch 0006). If a system `rg` is present in `PATH` (runtime team may ship one under `/var/jb`), it is used. | upstream `which("rg")` first |
| Plugin loading/registration | plugins load, but Node 22.9 has no `module.registerHooks`, so live reload of a local plugin’s relative module graph degrades and the special `@opencode/plugin` runtime specifier mapping is unavailable to external plugin code. | patch 0002 |
| git integration | git is not installed by default on the device; commands needing git fail with “install it with `apt install git`” instead of a generic ENOENT. | patch 0004 |
| Browser opening / updater | disabled/side-lined on this install type; the CLI remains usable headless. | upstream behaviour |

Anything not marked as device-verified remains **UNVERIFIED ON DEVICE**.

## 9. Device verification checklist (user-executed)

The CI artifact is only device-ready once these pass on the target iPhone SE (2nd gen),
iOS 16.1.1, Dopamine rootless, with the re-signed iPhoneOS Node 22.9.0 runtime:

1. `opencode --version` prints the OpenCode version and exits 0.
2. `opencode --help` renders the command tree and exits 0.
3. `opencode debug paths` shows paths under `$HOME` (e.g. `/var/jb/var/mobile/...`) and
   exits 0.
4. `opencode models` (embedded server boot + schema bootstrap + model list) exits 0.
5. `opencode session list` exits 0; the SQLite database file is created under
   `$HOME/.local/share/opencode`.
6. Shell tool: an agent command (e.g. `echo ok`, `pwd`) runs through `/var/jb/bin/sh` and
   returns output (checks patch 0004; no `/bin/sh` exists on rootless iOS).
7. `opencode run` against a configured provider completes one file read/edit round-trip.
8. Optional stretch: grep/glob with a system `rg` on `PATH`.

Record exact commands/output in the verification report; CI cannot assert these.

## 10. Honesty notes

- Host smoke ≠ device verification. The manifest states this explicitly.
- No run in this document is reported green unless the GitHub Actions run is green.
- Failure logs and the fix for each failure are kept in §4; the patch series exists because
  of concrete failures on Node 22.9.0, not speculation.

## 11. Runtime ICU capability gap (device-reported) and no-ICU hedge analysis

### Observed failure (reported by the device test, 2026-10-31)

The first device-verified iPhoneOS Node 22.9.0 runtime (`node --version` = v22.9.0,
`process.platform` = `ios`, fs/spawn/TLS/sqlite working) could not parse the CLI bundle:

```
SyntaxError: Invalid regular expression:
  /[\p{Mark}\p{Control}\p{Default_Ignorable_Code_Point}]/gu:
  Invalid property name in character class
```

Cause: that runtime was built with nodejs-mobile's default `--with-intl=none`. With V8's
i18n support disabled, (a) every `\p{...}`/`\P{...}` property escape is a **parse-time**
SyntaxError (the whole 21 MB bundle fails to compile before any code — no CLI-side patch can
catch it), and (b) the ECMA-402 `Intl` object is absent. This is a runtime capability gap;
the CLI patch series is not implicated (none of the six patches uses `Intl` or `\p{...}`).

Primary fix (owned by the runtime build): rebuild Node 22.9.0 with
`--with-intl=full-icu` (the option `build-runtime.yml` uses) or `small-icu`. Both link ICU
(so V8 regex property escapes work and
`Intl.Segmenter`/`DateTimeFormat`/`NumberFormat`/`ListFormat`/`Collator` exist); `\p{...}`
support depends on ICU's Unicode property data, which both configurations include. Node's
configure treats the pinned tree's `deps/icu-small` (which carries `README-FULL-ICU.txt`) as
the **canned full-ICU source** (`canned_is_full`); the full-icu CI build compiled ICU 75 for
iPhoneOS (`obj.target/icui18n`, `obj.target/icuucx`, host ICU tools, `libicui18n.a`/
`libicuuc.a` linked), so no external ICU source is needed in this tree. The runtime build
also validates `v8_enable_i18n_support=1` so a no-ICU runtime cannot be packaged.

An intermediate runtime run failed that validation's ICU symbol-grep heuristic: ICU symbols
carry hidden visibility in the iOS build, so a `nm -gU`-style grep misses them even though
the libraries are linked. That was a false negative in the runtime-build audit, since
corrected by the runtime owner; it has no CLI impact.

### Measured exposure in the run-4 artifact

Measured directly from `opencode-cli-node-ios` run 41176539017 (`opencode.mjs` sha256
`69ce398b…`):

| Item | Count / detail |
| --- | --- |
| Regex literals containing `\p{...}` (parse-time failures) | **75** occurrences |
| `\\p{...}` inside JS strings passed to `new RegExp(..., "u")` (construction-time failures) | **121** occurrences |
| Negated property escapes `\P{...}` | **0** (no complement ranges needed) |
| Distinct literal properties | `L, Nl, N, P, S, C, Cc, Cf, Co, Cn, Mark, Control, Default_Ignorable_Code_Point, Zl, Zp` |
| Distinct string-embedded properties | adds binary properties `Emoji, Emoji_Presentation, Emoji_Component, Extended_Pictographic, Regional_Indicator, DI` and `Script=Latin`, `Nd, Zs, Z, Ll, Lu, Pc, M, Cs` |
| `Intl.*` references | 30: `Segmenter` 14, `DateTimeFormat` 9, `NumberFormat` 5, `ListFormat` 1, `Collator` 1 |
| Top-level `new Intl.Segmenter(...)` module initialisers (crash even if regex parsing were fixed) | 6 source sites: `packages/merman/src/core/text.ts`, `packages/latex/src/layout.ts`, `packages/tui/src/util/string-width.node.ts`, `packages/tui/src/component/spinner-renderable.ts`, `packages/tui/src/util/locale.ts`, `packages/tui/src/prompt/display.ts` |
| Other ICU-dependent APIs at risk | `.normalize(` 45 refs (Unicode normalization needs ICU), `toLocaleString(` 23, `localeCompare(` 86 |

Origin of the property escapes: mostly bundled third-party code — the markdown/micromark
stack (`[\s\p{P}\p{S}]` patterns), width/emoji/ANSI helpers (`\p{Mark}\p{Control}…`,
`\p{Emoji_Presentation}`, `\p{Extended_Pictographic}`) — plus a small number in the port's
own sources (`packages/core/src/shell/scan.ts`, `packages/core/src/tool/plugin/edit.ts`,
`packages/tui/src/util/string-width.node.ts`, `packages/patchmark/src/inline.ts`,
`packages/session-ui/...`). The top-level `Intl.Segmenter` sites are in merman/latex/tui
modules that the single-file bundle evaluates at load.

### Hedge if the ICU rebuild fails (design only, not implemented)

This is deliberately **not implemented**; the ICU runtime is the correct fix. If it cannot
be produced, the minimal on-device workaround has two parts:

1. **Build-time escape rewriter** (runs in `scripts/build-opencode-bundle.sh` after Vite):
   walk the 21 MB bundle text once, tracking string literals, template literals, regex
   literals and character-class nesting; replace every property escape with explicit
   code-point ranges generated *at build time* by the build-host Node (which has full ICU).
   Inside `[...]` emit the ranges; standalone emit `[ranges]`; inside JS strings emit escaped
   `\\u{…}` sequences. No complements are needed (no `\P`). Worst-case growth measured on
   the run-4 bundle: ≈ **645 KiB** of range text (e.g. `L` = 684 ranges / 10.6 KB, `C` =
   741 ranges / 10.8 KB, `Mark` = 327 ranges / 4.9 KB; small properties like `Control` are
   two ranges). Risks: Unicode data version drift between build-host ICU and the emulated
   sets, astral-plane handling, context-scanning errors in minified code, and maintenance on
   every upstream bump. Effort: ~1 day plus regression testing.
2. **Prelude `Intl` shim** (defines `globalThis.Intl` before the bundle body evaluates, so
   the 6 top-level `new Intl.Segmenter` sites do not throw): `Segmenter` approximating
   grapheme clusters by code points, `DateTimeFormat`/`NumberFormat` basic formatting with
   `resolvedOptions()` (at least `timeZone`), `ListFormat` joining with `", "`, `Collator`
   code-unit comparison. Risks: cosmetic formatting differences (stats/date output) and
   approximate grapheme widths in TUI-only code. Effort: ~2 hours.
3. `String.prototype.normalize` / `localeCompare` fallbacks would still be missing without
   ICU; some bundled width/slug helpers call `normalize`, so the hedge is incomplete without
   additional polyfills (another ~half day, higher risk).

**Verdict:** the no-ICU hedge is 1–2 days of fragile build/transform work and approximates
Unicode behaviour; rebuilding the runtime with ICU (a supported Node configuration) fixes
both failure classes exactly and keeps the CLI patch series unchanged. Only pursue the
hedge if the ICU runtime cannot be produced.

No device success is claimed in this section; it records a device-reported failure and a
contingency analysis. The device verification matrix in §9 will be filled from the
rebuilt-runtime run.

## 12. Device verification status (device-reported)

Target device: iPhone SE (2nd gen), iOS 16.1.1, Dopamine rootless. **The Node 22 default
artifact is device-verified** with the v6 iPhoneOS Node 22.9 runtime (runtime sha256
`cf707ebe…`, 106,842,800 bytes, 2-key signed, device accepts it) and launcher flags:

```sh
--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning \
--no-warnings --max-old-space-size=1536
```

Device-verified (all rc=0): `--version` (`opencode2-node v2.2.5`), `--help` (full help;
`Intl.Segmenter` works with full ICU), `debug paths`, `debug config`, `models`, `auth list`,
`session list` (native `node:sqlite` DB with `-wal`/`-shm` on device), and a **mock-provider
agent turn**: `opencode run --standalone --model lmstudio/mock-opencode-1 "…"` where the model
called the shell tool, which wrote `/var/mobile/ocdev-e2e.txt` with the acceptance marker,
device identity (`id -un`), `git --version` (2.39.1) and `pwd`; the mock server saw
`GET /api/v1/models` and three `POST /chat/completions` (2nd/3rd carrying `toolResult`).
This evidence was obtained with a local one-line hack of patch 0010's forwarding on the
device; the official artifact (patch 0010) is being retested at the time of writing.

**The real TUI is impossible on the shipped runtime; iOS provides a line REPL instead.**
Root cause (verified): `@opentui/core` 0.8.0's Node binding loads its Zig native core
(`libopentui.dylib`) through `node:ffi`, which requires **Node.js >= 26.4 with
`--experimental-ffi`**. The device-verified iPhoneOS runtime is **Node 22.9.0**, which has no
`--experimental-ffi` (device: `bad option`) and no `node:ffi`, so an iPhoneOS OpenTUI build
could never be loaded — the real TUI needs a future Node 26+ iOS runtime (major runtime work,
out of scope). Patch 0011 made the failure clean (guidance + exit 1, no native stack trace);
**patch 0012 adds the actually-usable interactive path**: on iOS, `opencode` (no args) and
`opencode mini` with a terminal start a pure-JS **line REPL** (node:readline, no OpenTUI/FFI
imports): prompts are streamed through the same non-interactive run pipeline used by
`opencode run` (live assistant text, tool activity lines, auto-handled permission/questions,
Ctrl-C interrupts the running turn without quitting), with `/help`, `/new`, `/exit`/Ctrl-D,
session continuity across turns (like `run -c`) and errors that return to the prompt instead
of killing the loop. Non-TTY invocations (pipes/scripts) keep the guidance + exit 1, which
now states that interactive mode requires a TTY and that OpenTUI needs Node >= 26.4 +
node:ffi. The headless commands are unchanged. TUI/PTY remains a documented limitation (§8).

**Patch 0013 fixes REPL turn lifecycle (device-reported).** The first device PTY run of patch
0012 failed from turn 2 on: the REPL had resolved its server once and reused that connection,
so after the first turn the transport died (`Transport: terminated`, then `Transport: fetch
failed` with no provider traffic). The REPL now resolves a **fresh connection per turn**, like
separate `opencode run` processes: with `--standalone` each prompt gets its own private stdio
server (owned endpoints expose `close()` and are disposed after the turn), and the managed
service is re-discovered/reconnected per turn. One automatic retry per turn covers
transport-class failures (`Transport: ...`, `fetch failed`, terminated/socket/ECONNRESET/EPIPE)
with a `Retrying turn with a fresh server connection...` line; the first prompt waits for a
healthy resolution because resolution happens inside the turn. Host verification (mock
OpenAI-compatible provider, 4 consecutive REPL prompts): every turn reached the provider on a
fresh server, the shell tool wrote the marker file in all modes (`--standalone` and managed),
`/help`/`/new`/`/exit`/EOF work, and the retry path was exercised with an unreachable provider
(one retry line, then a clean error, loop still exits 0 on `/exit`).

**Patch 0014 raises the turn retry budget (device-reported).** On the device, turns 1 (and
occasionally 3) still failed both attempts of patch 0013 (`Transport: fetch failed` then
`Transport: terminated`) and lost the prompt even though other turns succeeded. The REPL now
makes **up to 3 attempts per turn** (2 retries) with a 1 s delay between attempts, each attempt
resolving a fresh server connection; the first turn additionally waits a 300 ms warm-up after
the first private server resolves (turn 1 is the flakiest on device). The
`Transport error: …` / `Retrying turn...` lines are unchanged, and failures that persist across
all attempts still return to the prompt cleanly. Host verification: with a mock whose provider
aborts every request, a single prompt performed 3 attempts (2 retry lines), returned to the
prompt and `/exit` exited 0; normal 4-prompt mock runs on both artifacts still reach the
provider, write the shell-tool marker and print E2E_OK ×4.

Runtime issues found and fixed during device bring-up (in order):

1. **ICU** — a runtime built `--with-intl=none` makes V8 reject the bundle's `\p{...}`
   regexes at parse time and leaves `Intl` missing. Fixed by rebuilding with
   `--with-intl=full-icu` (§11).
2. **JIT/WebAssembly W^X** — the v6 Node 22.9 runtime toggles code memory with mprotect
   RW<->RX; that toggle is process-wide, so background V8 threads race it and a multithreaded
   process dies with SIGBUS (138) on the first optimized loop or `fetch`. Device proof:
   `--single-threaded` (or `--no-concurrent-recompilation`) makes JIT/WebAssembly/fetch work.
   **The launcher must pass `--single-threaded`, and the CLI must forward it to every spawned
   server child (patch 0010)** — without forwarding, `serve --service` children crashed with
   SIGBUS and `models`/`debug config`/`session list` failed.
3. **Node 18 fallback** (hedge, §13) — the reference Node 18.20.4 runtime is device-proven for
   JIT/wasm/ICU/TLS; with patches 0007–0009 the CLI starts, `--version`/`debug paths`/
   `debug config`/`models`/`session list` pass. `--help` crashes with SIGSEGV only because the
   reference runtime is small-ICU (`Intl.Segmenter` lacks brkitr data); a full-ICU Node 18
   runtime is being built (`build-runtime-node18.yml`). Device retest of the official
   patch-0009/0010 artifact is pending.

CI itself never claims device success: `bundle-manifest.json` keeps
`verification_status.device_verified = false`; the device evidence above is reported by the
human-executed device matrix.

## 13. Node 18 fallback (hedge) — conditional variant

While the v6 Node 22.9 iOS runtime was still being fixed, the **device-proven Node 18.20.4
iPhoneOS runtime** was the fallback path, so a **separate conditional variant** of the same CLI
bundle can target it. It does **not** change the default Node 22 artifact path; it is built by
a second `build-opencode.yml` job (`bundle-node18`) and uploaded as artifact
`opencode-cli-node18-ios` with its own manifest (`artifact`/`variant` = `node18-fallback`,
`build.runtime_node_version` = `18.20.4`, required host smoke Node 18.20.4). After the v6
runtime reached JIT/wasm support with `--single-threaded` (§12), the Node 22 artifact is the
primary path; this variant remains a hedge and is kept green in the same workflow.

### Build/run

```bash
# everything the workflow does, locally (macOS or POSIX host):
OPENCODE_IOS_NODE18=1 bash scripts/build-opencode-bundle.sh build
OPENCODE_IOS_NODE18=1 bash scripts/build-opencode-bundle.sh stage
OPENCODE_IOS_NODE18=1 OPENCODE_NODE_MATRIX='18.20.4 22.9.0' OPENCODE_SMOKE_REQUIRED=18.20.4 \
  bash scripts/build-opencode-bundle.sh smoke
OPENCODE_IOS_NODE18=1 bash scripts/build-opencode-bundle.sh manifest verify
```

The build script downloads the pinned sql.js release
(`sql.js@1.15.2`, MIT; tarball sha256
`74fbdd373ad7eb2bbe74c7807581c1c39e424ee53ed95042a02208cbc96d72fd`), verifies it and the two
staged files, and stages `assets/node18-sqlite/{sql-wasm.js,sql-wasm.wasm}` (≈777 KB).
Patch `0007-node18-ios-compat` is applied on top of 0001–0006; it is a no-op unless
`OPENCODE_IOS_NODE18=1`.

Launcher contract for this variant (`bundle-manifest.json.env_contract`):

```sh
exec /var/jb/usr/lib/opencode/runtime/node \
  --no-warnings \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

`--experimental-sqlite`, `--disable-warning=…`, `--experimental-ffi` and `--use-system-ca`
must **not** be passed: Node 18.20.4 rejects all of them.

### Node 18 API gap analysis (what the bundle needed)

Measured on the run-5 Node 22 bundle against stock official Node 18.20.4; every gap below is
handled by patch 0007 (the first two were startup-fatal):

| # | Node 18 gap | Impact | Fix in variant |
| --- | --- | --- | --- |
| 1 | `node:sqlite` module absent | startup link error (static import in `database/sqlite.node.ts`) | Vite maps `node:sqlite` to the sql.js-backed synchronous shim; sql.js JS+wasm staged as assets |
| 2 | `import.meta.filename` / `import.meta.dirname` absent | bundle prelude sets `__filename`/`__dirname` to `undefined`; npm tooling bundled for plugin resolution then crashes at startup (`path.resolve(undefined)` in its `setPath`) | prelude derives both from `import.meta.url` |
| 3 | `node:vm` ESM named export `constants` absent | link error in `util/runtime/import.node.ts` | namespace import + fallback; plugin entrypoints use a plain dynamic import when `vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER` is unavailable |
| 4 | global `crypto` absent | `TypeError: crypto is not defined` in logger init | prelude sets `globalThis.crypto = require("node:crypto").webcrypto` |
| 5 | Iterator helpers absent (`Iterator.prototype.map`, `Iterator.from`, …) | server 500 on `/api/model` (`mergeRecord`) and codemode iterators | `mergeRecord`/codemode use spread + `.values()` (no iterator helpers) |
| 6 | `Array.prototype.toSorted/toReversed/toSpliced/with/findLast*`, `Object.groupBy`, `Map.groupBy`, `Promise.withResolvers`, `Array.fromAsync`, `String.isWellFormed/toWellFormed`, `AbortSignal.any` absent | would throw where used | prelude polyfills (guarded; newer runtimes keep native implementations) |
| 7 | `--experimental-sqlite`, `--disable-warning=…`, `--use-system-ca`, `--experimental-ffi` flags absent | `bad option` at launch | variant prelude/launcher use `--no-warnings` only |
| 8 | Vite output target | new syntax lowered by `build.target: node18` | — |
| 9 | `node:inspector` disabled in the device runtime (device-reported: `ERR_INSPECTOR_NOT_AVAILABLE` at startup; only static import is `cli/src/cpu-profile.ts`) | bundle failed to link before any CLI code ran | patch 0008 maps it to a build-time stub; `SIGPROF` CPU profiling is unavailable on this variant (handler logs and continues) |
| 10 | Effect `ChildProcessSpawner` + `Stream` readiness path did not surface the standalone server's promise line on device (device-reported: `opencode run --standalone` → `Standalone server exited before reporting readiness`; direct `node:child_process.spawn` of the same command works) | agent turns could not start: no standalone server, no model request | patch 0009: iOS/`OPENCODE_IOS=1` spawns the server with plain `node:child_process`, reads the first JSON `{url}` line, keeps the stdin lease pipe open and enforces a 20 s readiness timeout; non-iOS unaffected |
| 11 | `Intl.Segmenter` has no `brkitr` data on the reference Node 18 runtime (small-ICU) → `--help` SIGSEGV in `v8::internal::JSSegmenter::Create` (device-reported) | help rendering crashes on that runtime only | runtime-side: use a full-ICU Node 18 build (`build-runtime-node18.yml` builds `--with-intl=full-icu`); no CLI patch planned (a SIGSEGV cannot be caught in JS) |

`node:sea` (absent on Node 18) is already never imported by the iOS bundle (patch 0001).
The sql.js shim implements only the `DatabaseSync`/`StatementSync` subset this tree uses
(`exec`, `prepare`, `all`/`get`/`run`, `setReadBigInts`/`setReturnArrays` flags, `close`);
it is synchronous after a one-time WebAssembly init (top-level await; the bundle already has
one) and persists by exporting/atomically rewriting the database file at most every 250 ms
and on `close()`/process exit. Consequences to document for users: no WAL, whole-file
writes (slower than native SQLite, small crash-window of up to 250 ms of writes), and no
`loadExtension`.

### Host evidence (this artifact's smoke)

Executed locally on the development host with stock official Node 18.20.4 (downloaded from
nodejs.org, SHA-256 verified) and Node 22.9.0, throw-away `HOME`:

| Node | `--version` | `--help` | `debug paths` | `models` | `auth list` | `session list` | sqlite |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 18.20.4 (required) | PASS | PASS | PASS | PASS | PASS | PASS | runtime module absent; bundled sql.js shim used |
| 22.9.0 (informational) | PASS | PASS | PASS | PASS | PASS | PASS | runtime `node:sqlite` + `--experimental-sqlite` |

Additional local check (`OPENCODE_IOS=1`, stock Node 18.20.4): `opencode run --standalone
--model openai/gpt-4o-mini "say hi"` started the directly-spawned standalone server, created
a session and reached model resolution (fails only with `Model unavailable` because no
provider is configured locally) — the device-reported `Standalone server exited before
reporting readiness` failure is gone from the bundle (patch 0009). A device mock-provider
agent turn is still required to call this end-to-end verified.

CI evidence for this variant: the `bundle-node18` job in `build-opencode.yml` runs exactly the
same matrix on the macOS runner and passed it in
[run 41291337297](https://github.com/Justintunsday/opencode-ios/actions/runs/41291337297)
(both jobs green, 14 patches incl. the node:inspector stub, standalone direct-spawn,
child-flag forwarding, the TUI guidance, the line REPL, REPL turn lifecycle and the 3-attempt
turn budget): artifact `opencode-cli-node18-ios`, `opencode.mjs` 21,402,278 bytes, sha256
`19a09a47c27446dd53eda82425efb61784ece535d147bc5b648f78c303d571e1`, 24 assets /
33,614,156 bytes, manifest `variant=node18-fallback`,
`host_smoke_required_node_version=18.20.4`, `host_smoke_required_passed=true`; the required
Node 18.20.4 checks and all informational checks passed (Node 18.20.4 + 22.9.0). Device
history: the 7-patch artifact reached CLI startup and hit the inspector link error (fixed by
0008); the 8-patch artifact then passed `--version`/`debug paths`/`debug config`/`models`/
`session list` on the device and failed `run --standalone` at server readiness (fixed by
0009). The primary Node 22 artifact reached full device verification with patch 0010 (§12),
so this variant remains a hedge; its own device agent turn was pending at the time of
writing. The manifest's `verification_status.device_verified` stays `false`. The default
Node 22 artifact from the same run (`opencode.mjs` sha256 `e99ac8d1…`, 22 assets) is the
artifact offered for the final device matrix / `.deb`.

### Device risk / open questions for shipping the Node 18 variant

- **Runtime provenance.** The Node 18 fallback runtime is now built natively in this repo
  (`.github/workflows/build-runtime-node18.yml` + `scripts/build-ios-runtime-node18.sh` from
  nodejs-mobile `v18.20.4`, `--with-intl=full-icu`, JIT+WebAssembly, 2-key entitlements), so
  the licensing blocker of shipping a community binary no longer applies; the remaining work
  is a green runtime build + device confirmation before packaging it.
- **Device execution.** The CLI bundle reached actual startup on the device with an
  inspector-less community Node 18 runtime; the first runtime gap was `node:inspector`
  (`ERR_INSPECTOR_NOT_AVAILABLE` at bundle link), fixed by patch 0008/this artifact. The
  subsequent device matrix (`--version`, `--help`, `debug paths`, `models`, `session list`,
  shell tool, mock-provider agent turn) still has to pass and is **UNVERIFIED ON DEVICE**.
- **Diagnostic degradation on the Node 18 variant:** `SIGPROF`-triggered CPU profiling is
  unavailable (patch 0008 stubs the module; the handler logs `Failed to capture CPU profile`
  and keeps running). Heap snapshots via `v8`/`util` are unaffected. This applies to every
  Node 18 fallback build, including one compiled with the inspector enabled (the stub is
  build-time for this variant); if CPU profiling is needed later the stub can be made
  runtime-conditional.
- **sql.js persistence semantics** differ from native SQLite (see above); acceptable for a
  fallback but should be called out in user-facing limitations if this variant ships.
- Everything else (shell selection, rootless paths, PTY/watcher/ripgrep degradations) is
  identical to the Node 22 bundle because the same patch series is applied.

Implementation effort for this variant: ≈2 h from the device finding (analysis + patches
0007/0008 + shim + build/smoke/manifest/workflow wiring), plus CI runtime. It is a hedge
only; the primary path remains fixing the Node 22.9 runtime's V8 W^X/JIT issue.

## 14. Node 26 real-TUI variant (Phase D) — conditional variant

The default Node 22 bundle cannot start the real OpenTUI TUI: OpenTUI's Node binding needs
`node:ffi` (and loads its native Zig core `libopentui.dylib` through it), which exists only in
Node >= 26.4. This variant targets the native iPhoneOS **Node 26.13.0** runtime and ships the
prebuilt OpenTUI iPhoneOS renderer as a CLI asset, so `opencode` in a TTY can start the real
TUI instead of the line REPL (patches 0011–0014 remain the fallback for the Node 22 variant).

Status (honest):

| Check | Status |
| --- | --- |
| Node 26.13.0 iPhoneOS runtime builds and runs JIT-dependent JS (`--single-threaded`) | device-verified (Phase A/B runtime; WebAssembly runtime patch pending) |
| `node:ffi` availability + API compatibility on stock Node 26.13.0 | host-verified (`require('node:ffi')` default-on; `ffi.dlopen(path, defs)` → `{lib, functions}`; OpenTUI destructures exactly that) |
| OpenTUI renderer dylib `dlopen` on the device | device-verified from `/var/jb` paths (probe run 41315221320); `/var/mobile` and `/tmp` are sandbox-blocked (`file system sandbox blocked mmap()`) |
| OpenTUI renderer build (iPhoneOS arm64 dylib) | CI green (opencode-ios run 41313921358; dylib sha256 `954289152cc182780a81ca7199ceeec04ee8c55c334f85710e0ff192f4817638`) |
| CLI bundle + renderer asset staged and host-verified | this workflow (`bundle-node26` job); see artifact below |
| FFI-enabled Node 26 iPhoneOS runtime | pending (Phase A/B artifact is `--without-ffi`; follow-up FFI build required) |
| **End-to-end real TUI on the device** | **NOT verified** — needs the FFI-enabled runtime + this bundle |

### Build

```bash
# download the renderer artifact (Phase C green run) and the CLI bundle is built against it:
gh run download 41313921358 -R Justintunsday/opencode-ios -n opentui-ios-renderer -D dist/opentui-ios-renderer
export OPENCODE_OPENTUI_IOS_DYLIB="$PWD/dist/opentui-ios-renderer/libopentui.dylib"
export OPENCODE_OPENTUI_IOS_DYLIB_SHA256=954289152cc182780a81ca7199ceeec04ee8c55c334f85710e0ff192f4817638

# everything the workflow does, locally (macOS or POSIX host with bun + python3 + node):
export OPENCODE_IOS_NODE26=1 OPENCODE_IOS=1 OPENCODE_TARGET=ios-arm64
bash scripts/build-opencode-bundle.sh fetch
bash scripts/build-opencode-bundle.sh patches
bash scripts/build-opencode-bundle.sh install
bash scripts/build-opencode-bundle.sh deps-patches      # patch installed @opentui/core
bash scripts/build-opencode-bundle.sh build
bash scripts/build-opencode-bundle.sh stage             # verifies staged renderer sha256
bash scripts/build-opencode-bundle.sh assetcheck        # OpenTUI iOS asset/resolver check
OPENCODE_NODE_MATRIX='26.13.0 24.22.2' OPENCODE_SMOKE_REQUIRED=26.13.0 \
  bash scripts/build-opencode-bundle.sh smoke
bash scripts/build-opencode-bundle.sh manifest
bash scripts/build-opencode-bundle.sh verify
```

The build script verifies the dylib sha256 against the pin and runs
`scripts/check_macho.py <dylib> --kind dylib --max-minos 16.1.1` before staging. The
workflow (`bundle-node26` job) downloads the pinned `opentui-ios-renderer` artifact from
run 41313921358 directly (same repository, `actions: read` permission), re-verifies it, then
runs the same commands. The `assetcheck` step is a host-Node unit check:
`src/opencode-ios/opentui_ios_asset_check.mjs` imports the patched build-time resolver with
`process.platform` stubbed to `"ios"`, asserts the descriptor/key/source, and checks the staged
asset + runtime FFI chunk + bundle contain the expected strings.

Artifact contract: same layout as §1 plus
`assets/@opentui/core-ios-arm64/libopentui.dylib` (3,785,600 bytes renderer at the pinned
Phase C build), artifact name `opencode-cli-node26-ios`, manifest `variant=node26`,
`build.runtime_node_version=26.13.0`, `verification_status.host_smoke_required_node_version`
= `26.13.0`, `verification_status.device_verified = false`.

### Launcher contract (node26 variant)

```sh
exec /var/jb/usr/lib/opencode/runtime/node \
  --single-threaded \
  --no-warnings \
  --max-old-space-size=1536 \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

Environment (the CLI iOS prelude also sets most of these; the wrapper should provide the
absolute rootless paths):

- `OPENCODE_IOS=1`
- `OPENCODE_NODE_ASSETS_DIR=/var/jb/usr/lib/opencode/cli/assets`
- `OTUI_ASSET_ROOT=/var/jb/usr/lib/opencode/cli/assets` (the OpenTUI loader joins the native
  asset key `@opentui/core-ios-arm64/libopentui.dylib` onto it; the asset must exist at that
  absolute path)
- `HOME` writable (device: `/var/jb/var/mobile`); `TMPDIR` writable (prelude falls back to
  `$HOME/.cache/opencode/tmp` when unset)
- `PATH` should start with `/var/jb/bin:/var/jb/usr/bin:/var/jb/usr/sbin:/var/jb/sbin`
  (the prelude only prepends them when `process.platform === "ios"`; the Node 26 runtime may
  report `darwin` until the FFI rebuild, so the wrapper should set PATH itself)

Flags: `--single-threaded` is **required** (same process-wide V8 W^X constraint as Node 22);
do **not** pass `--experimental-sqlite` (not needed; Node 26 has `node:sqlite`) or
`--no-experimental-ffi` (would disable the renderer). `--experimental-ffi` is accepted but
redundant on 26.13; `--allow-ffi` is only for the permission model.

### CI evidence (this workflow's `bundle-node26` job)

Run [41431113315](https://github.com/Justintunsday/opencode-ios/actions/runs/41431113315) (all
three jobs green; `bundle-node26` all steps success) — this is the Phase D real-TUI bundle with
patch 0016 (the node:ffi-conditional TUI gate). Artifact `opencode-cli-node26-ios` (zip
32,693,073 bytes):

| Field | Value |
| --- | --- |
| `opencode.mjs` | 21,398,198 bytes, sha256 `d031509c318fe1f8cdbde17ee574373dddad43cebfd08aba54d9991f9f21b2ce` |
| Assets | 23 files / 36,667,080 bytes (app-archive 1, audio 5, data 8, wasm 8, **ios-native-library 1**) |
| Renderer asset | `assets/@opentui/core-ios-arm64/libopentui.dylib`, 3,785,600 bytes, sha256 `954289152cc182780a81ca7199ceeec04ee8c55c334f85710e0ff192f4817638` (= pinned Phase C artifact; manifest `sha256_matches_expected: true`) |
| Manifest | `variant=node26`, `build.runtime_node_version=26.13.0`, **16** upstream patches + 1 dependency patch (0016 sha256 `63ebc1464cd0c334d5406917ff81d11d7024b5890e06a6480f50caec802f0e0f`), `host_smoke_required_node_version=26.13.0`, `host_smoke_required_passed=true`, `device_verified=false` |
| Host smoke | 12/12 commands pass on stock Node 26.13.0 (required) and 24.22.2 (informational): `--version`, `--help`, `debug paths`, `models`, `auth list`, `session list`; native `node:sqlite` (no flag needed) |
| Resolver/asset check | `assetcheck` step passed (patched build-time resolver maps `process.platform="ios"` to the key; staged dylib hash matches; runtime FFI chunk + bundle contain the iOS entry/fallback) |
| Real-TUI gate (patch 0016) | bundle contains `IOS_TUI_FFI_GATE` (prelude marker), `hasNodeFFI`, `runIOSRepl` and `node:ffi`; both handlers bundle the conditional shape `const ffi = yield* Effect.promise(() => hasNodeFFI()); if (isIOS() && !ffi) { …line-REPL fallback… }` — so on the FFI-enabled Node 26 runtime the handlers fall through to the real TUI, while the Node 22/no-FFI path keeps the line REPL/guidance exactly as before |

Two CI-only fixes this run needed: bun 1.4 installs `@opentui/core` in the **isolated**
`node_modules/.bun/@opentui+core@0.8.0+<hash>/node_modules/@opentui/core` layout (the build
script now locates it via `find` and applies the dependency patch with
`git apply --directory`), and `OPENCODE_OPENTUI_IOS_DYLIB` must be absolute because the
upstream build runs with cwd `packages/cli` (the script normalizes it).

### Device verification checklist (human-executed; CI cannot do this)

1. Build/obtain the **FFI-enabled** Node 26.13.0 iPhoneOS runtime (not `--without-ffi`) and
   confirm on the device: `node -e "console.log(typeof require('node:ffi').dlopen)"`.
2. Install this bundle + the renderer dylib under `/var/jb/usr/lib/opencode/cli/assets/...`
   (root-owned, 0755 for the dylib), then run the launcher in a real PTY.
3. Expect: no `Unsupported OpenTUI Node asset target`, no stack trace; the full TUI renders
   and accepts a prompt.
4. Capture evidence (run id/build sha, runtime sha, exact argv/env, screenshot/transcript,
   exit codes); if it crashes, capture the crash type/symbol before reporting failure.

### Risks / open questions

- **FFI runtime provenance:** the Phase A/B Node 26 runtime is built `--without-ffi`. Loading
  the renderer requires the FFI-enabled build (`deps/libffi` iOS cross-build risk noted by the
  runtime workstream). Without it the TUI cannot start.
- **WebAssembly runtime patch pending:** Node 26's `fetch` (llhttp wasm) needs WebAssembly;
  the runtime patch is in flight. Without it provider network calls fail even though the TUI
  renders.
- **Hybrid C++ ABI in the renderer:** the dylib is compiled with Zig 0.16 bundled libc++
  headers but links the iPhoneOS SDK libc++ stubs (Zig 0.16 cannot build its bundled libc++ for
  `aarch64-ios`). Both are libc++ ABI v1; the device TUI load is the final confirmation.
- **Renderer asset versioning:** the dylib is ldid-signed (2-key entitlements); its hash is not
  reproducible across builds because the signature blob is nondeterministic. The CLI build pins
  the Phase C artifact hash and the manifest records the staged hash; when the renderer is
  rebuilt, update the pin in `build-opencode.yml`/build script together.
- **Device UX:** real TUI keyboard/PTY limitations on iPhone (no hardware keyboard assumptions,
  PTY only, no clipboard until an iOS clipboard port, performance) are tracked in
  `docs/KNOWN_LIMITATIONS.md` by the packaging workstream.

