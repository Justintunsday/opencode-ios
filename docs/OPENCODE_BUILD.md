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

A conditional fallback variant produces the same layout under a different artifact name:
`opencode-cli-node18-ios` (bundle for the device-proven Node 18.20.4 iPhoneOS runtime,
extra `assets/node18-sqlite/` payload; see §13). The default Node 22 artifact is unchanged.

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
# latest green build of this workflow:
gh run list --workflow build-opencode.yml -L 1 --json databaseId,conclusion
```

## 2. Pipeline

Workflow: `.github/workflows/build-opencode.yml` (`workflow_dispatch` + push paths
`patches/opencode/**`, `scripts/build-opencode-bundle.sh`, `src/opencode-ios/**`,
`UPSTREAM.lock`, the workflow itself). All steps delegate to
`scripts/build-opencode-bundle.sh` so the same commands run locally. Two jobs build two
artifacts from the same patch series:

- `bundle` → `opencode-cli-node-ios` (default Node 22.9 runtime bundle, primary deliverable);
- `bundle-node18` → `opencode-cli-node18-ios` (conditional Node 18.20.4 fallback hedge,
  `OPENCODE_IOS_NODE18=1`, extra sql.js payload; §13). It is independent and does not change
  the default artifact.

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
   manifest lie).
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

Patch series SHA-256 is recorded in `bundle-manifest.json` (`patches.series_sha256`), so a
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
- `env_contract` — exactly what the `.deb` launcher must provide (see §7).
- `smoke` — the full host smoke report embedded verbatim (required + informational
  commands, flags, exit codes, captured output, sqlite probes).
- `verification_status` — `host_smoke_required_passed`, required Node version,
  `device_verified: false` with the CI/device disclaimer.

## 7. Device runtime contract (for the .deb launcher)

`package-rootless.yml` builds `/var/jb/usr/bin/opencode`; the wrapper must launch the
bundle as:

```sh
exec /var/jb/usr/lib/opencode/runtime/node \
  --experimental-sqlite \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

- `--experimental-sqlite` is **required**: on Node 22.9 `node:sqlite` (used for
  `DatabaseSync`, session storage) is flag-gated. Do **not** pass `--experimental-ffi` or
  `--use-system-ca`; neither exists on Node 22.9.0.
- For the **Node 18 fallback variant** (§13) the launcher must instead pass `--no-warnings`
  and must not pass `--experimental-sqlite`/`--disable-warning` (Node 18 rejects them and has
  no `node:sqlite`; the bundle ships a sql.js shim). The variant's exact argv is recorded in
  its `bundle-manifest.json.env_contract`.
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
| TUI renderer (`@opentui/core` native library) | the native OpenTUI library is not shipped for iPhoneOS; headless CLI (`run`, `serve`, `models`, …) is the supported surface. | asset set excludes the dylib |
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

## 12. Device verification status (device-reported, no CLI claims yet)

Target device: iPhone SE (2nd gen), iOS 16.1.1, Dopamine rootless. The `.deb` produced from
a green CLI artifact is installable on the device and the native iPhoneOS Node.js runtime
starts (`node --version` works, `process.platform === "ios"`, fs/spawn/TLS/sqlite work on
device — reported by the device test). The **OpenCode CLI bundle has not yet passed a device
matrix**. Two runtime issues were found and addressed in the runtime build during device
testing:

1. **ICU** — the first iPhoneOS Node 22.9 runtime was built `--with-intl=none`; V8 then
   rejects the bundle's `\p{...}` regexes at parse time and `Intl` is missing. Fixed by
   rebuilding with `--with-intl=full-icu` (§11).
2. **JIT / WebAssembly** — the current Node 22.9 iPhoneOS runtime cannot execute JIT or
   WebAssembly code on this device (V8 12.4 W^X: only `mmap RW → write → mprotect RX → exec`
   works for generated code and V8 12.4 does not use that sequence; §13 explains why this
   matters for `fetch`/undici, which uses a wasm llhttp parser). This is a runtime-side V8
   limitation; the CLI bundle itself does not require wasm at startup.

Meanwhile the community **Node 18.20.4 iPhoneOS runtime** is device-proven on this exact
device: JIT, WebAssembly, ICU 74.2 and TLS all work. §13 describes the Node 18 fallback
variant of the CLI bundle built and host-tested as a hedge.

Status: CI builds, host smoke and packaging are complete; on-device CLI matrix remains
**UNVERIFIED ON DEVICE** and must not be claimed from CI.

## 13. Node 18 fallback (hedge) — conditional variant

Because the Node 22.9 runtime currently cannot run JIT/wasm on the device, a **separate
conditional variant** of the same CLI bundle can target the device-proven Node 18.20.4
iPhoneOS runtime. It does **not** change the default Node 22 artifact path; it is built by a
second `build-opencode.yml` job (`bundle-node18`) and uploaded as artifact
`opencode-cli-node18-ios` with its own manifest (`artifact`/`variant` = `node18-fallback`,
`build.runtime_node_version` = `18.20.4`, required host smoke Node 18.20.4).

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

CI evidence for this variant: the `bundle-node18` job in `build-opencode.yml` runs exactly the
same matrix on the macOS runner and passed it in
[run 41266035760](https://github.com/Justintunsday/opencode-ios/actions/runs/41266035760)
(both jobs green): artifact `opencode-cli-node18-ios`, `opencode.mjs` 21,393,413 bytes,
sha256 `f1ef6ea78f3fb80417f28040bbddb6f8bbf902376e69a35a26d37a459ce82018`, 24 assets /
33,614,156 bytes, 7 patches, manifest `variant=node18-fallback`,
`host_smoke_required_node_version=18.20.4`, `host_smoke_required_passed=true`, 24/24 smoke
checks passed across Node 18.20.4 (required) and 22.9.0 (informational). The manifest's
`verification_status.device_verified` stays `false`.

### Device risk / open questions for shipping the Node 18 variant

- **Runtime provenance/licensing.** The device-proven Node 18.20.4 iPhoneOS binary available
  today is a community build; it cannot be shipped in the `.deb` without a compatible
  license/attribution. Node's own sources (or nodejs-mobile's Node 18 release, framework-only)
  can be built to `out/Release/node`, but that is another ~1–2 h native build plus signing,
  and is runtime-team work, not CLI work.
- **Device execution still unverified for the CLI bundle.** Host smoke proves the JS bundle
  runs on stock Node 18.20.4; the iOS runtime is a patched cross-build, so its wasm/JIT/ICU
  behaviour must be confirmed by the device matrix (`--version`, `--help`, `debug paths`,
  `models`, `session list`, shell tool, a mock-provider agent turn).
- **sql.js persistence semantics** differ from native SQLite (see above); acceptable for a
  fallback but should be called out in user-facing limitations if this variant ships.
- Everything else (shell selection, rootless paths, PTY/watcher/ripgrep degradations) is
  identical to the Node 22 bundle because the same patch series is applied.

Implementation effort for this variant: ≈1.5 h from the device finding (analysis + patch
0007 + shim + build/smoke/manifest/workflow wiring), plus CI runtime. It is a hedge only;
the primary path remains fixing the Node 22.9 runtime's V8 W^X/JIT issue.
