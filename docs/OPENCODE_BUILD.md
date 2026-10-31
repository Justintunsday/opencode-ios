# OpenCode CLI bundle for the iPhoneOS Node.js runtime

Status: **CI build + host-Node smoke verified; device execution pending user verification**
(`UNVERIFIED ON DEVICE` until the packaged `.deb` is tested on the target iPhone).

This document describes how `.github/workflows/build-opencode.yml` produces the
`opencode-cli-node-ios` artifact: the OpenCode v2 CLI as a Vite ESM bundle that runs on
the native iPhoneOS Node.js **22.9.0** runtime shipped in the `.deb`.

## 1. What the workload produces

Upstream OpenCode v2 ships two build paths (`docs/ARCHITECTURE.md`): a Bun-compiled
executable and `packages/cli/script/build-node.ts`, the official Node distribution path
(Vite ESM bundle, no Node runtime bundled). The port uses the Node path with
`--bundle-only`, so no SEA (single executable application) is built on the runner.

Artifact contract (consumed by `package-rootless.yml` / `test-port.yml`):

```
opencode-cli-node-ios/
  opencode.mjs            # ESM bundle, entry point (launcher: node <flags> <path>)
  assets/**               # app-archive.bin, attention sounds, tree-sitter wasm/scm, photon wasm
  bundle-manifest.json    # upstream/patch/bundle hashes, env contract, host smoke matrix
  SHA256SUMS              # sha256 of every payload file incl. bundle-manifest.json
```

Pinned inputs (single source of truth: `UPSTREAM.lock`):

| Input | Pin |
| --- | --- |
| OpenCode source | `anomalyco/opencode` `e8238bae9b807b72ecfc75afd3a9fe2e6b07b944` (v2.2.5) |
| Host build tool | Bun `1.4.4` (`oven-sh/setup-bun`, not shipped to the device) |
| Device runtime | Node.js `22.9.0` built for `arm64-apple-ios` (`build-runtime.yml`) |
| Build runner | `macos-15` (arm64) |
| Bundle target | `ios-arm64` (port patch; Darwin code path, iOS prelude/asset set) |

Download the artifact of a green run:

```bash
gh run download <run-id> -n opencode-cli-node-ios -D dist/opencode-cli-node-ios
# latest green build of this workflow:
gh run list --workflow build-opencode.yml -L 1 --json databaseId,conclusion
```

## 2. Pipeline

Workflow: `.github/workflows/build-opencode.yml` (`workflow_dispatch` + push paths
`patches/opencode/**`, `scripts/build-opencode-bundle.sh`, `src/opencode-ios/**`,
`UPSTREAM.lock`, the workflow itself). All steps delegate to
`scripts/build-opencode-bundle.sh` so the same commands run locally.

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
| 0001 | `ios-node-target-and-prelude` | `packages/cli/src/node/target.ts`, `script/build-node.ts`, `script/node-assets.ts`, `vite.node.config.ts` | Adds the `ios-arm64` Node target; iOS asset collector (no macOS dylibs/addons/helpers); non-SEA iOS prelude (no `node:sea` import, no `module.registerHooks`, no `--experimental-ffi`, assets from `OPENCODE_NODE_ASSETS_DIR`, `/var/jb` PATH prefixes, `OPENCODE_IOS=1`); Node 22.9 HTTP content-length workaround; photon wasm module kept external/lazy. |
| 0002 | `node22-registerhooks-and-sqlite-fallback` | `packages/cli/src/util/process.ts`, `packages/plugin/src/source.node.ts`, `packages/util/src/runtime/import.node.ts` | `module.registerHooks` exists only in Node ≥22.15: namespace import + guarded call so startup never throws a link-time SyntaxError; plugin local-reload degrades but loads. Propagates `--experimental-sqlite` to self-spawned server children (required for `node:sqlite` on 22.9). |
| 0003 | `optional-native-modules-startup-safe` | `packages/core/src/pty/pty.node.ts`, `packages/core/src/image/photon-wasm.node.ts` | `node-pty` native addon does not exist on iPhoneOS; its top-level `require` is guarded (PTY unavailable, shell tool uses pipe-based `child_process`). Drops the `node:sea` import (bundle is non-SEA). Guards photon wasm artifact resolution so importing the image pipeline reports “unavailable” instead of throwing (iPhoneOS runtime has WebAssembly disabled). |
| 0004 | `ios-shell-selection-and-git` | `packages/core/src/shell/select.ts`, `packages/core/src/util/git-executable.ts` | Rootless iOS has no `/bin/sh`,`/bin/bash`,`/bin/zsh`; shell resolution prefers `$SHELL` then `/var/jb/bin[/usr/bin]/{sh,bash,zsh}` etc. The agent shell tool spawns the resolved shell with `-c` (never Node's hardcoded `/bin/sh`). git is not part of the bootstrap → clear actionable error instead of ENOENT. |
| 0005 | `node22-sqlite-api-fallbacks` | `packages/core/src/database/sqlite.node.ts` | Node 22.9 `node:sqlite` lacks `StatementSync#setReturnArrays` and `DatabaseSync#loadExtension`: map object rows to column-ordered arrays when the API is missing, report extension loading as unavailable. Without this the embedded server answers 500 on `/api/info` and `/api/model`. |
| 0006 | `device-robustness` | `packages/cli/vite.node.config.ts`, `packages/core/src/persistent-pty/binary.node.ts`, `packages/core/src/ripgrep/binary.ts` | Rootless-iOS robustness: home-rooted `TMPDIR` fallback in the prelude (do not depend on `/tmp`), persistent-PTY capability reports `false` on ios (the daemon binary is not shipped), and a missing `rg` produces an actionable install hint instead of `unsupported platform for ripgrep: arm64-ios`. |

Patch series SHA-256 is recorded in `bundle-manifest.json` (`patches.series_sha256`), so a
consumer can tell exactly which series produced the artifact.

## 4. CI runs (honest log)

| Run | Commit | Result | Notes |
| --- | --- | --- | --- |
| [41171615578](https://github.com/Justintunsday/opencode-ios/actions/runs/41171615578) | `37fc62c` | failure | First stock build. Build/stage/upload steps succeeded; smoke failed on a bug in the new `host_smoke.py` stock-Node archive extraction (version dots in `node-v22.9.0-darwin-arm64`). Fixed in `9b74a90`. |
| [41172138603](https://github.com/Justintunsday/opencode-ios/actions/runs/41172138603) | `9b74a90` | **success** | Stock upstream bundle baseline (no patches, target `darwin-arm64`). Node 24/26 passed `--version`/`--help` and all deeper commands; Node 22.9 failed as expected (`SyntaxError: node:sea does not provide an export named 'getAssetKeys'`, exit 1) — this is why the iOS patch series exists. Artifact sha256 (opencode.mjs) `d706daffa028e779e5c876a4b9edc11fa3867b162c61d1ab38337a1aca31728a`. |
| 41174945683 | `bede0f8` | **success** | First patched iOS build (`ios-arm64`, 5 patches); required smoke version is the shipped Node 22.9.0. All 18 host-Node smoke commands passed (6 commands × Node 22.9.0 / 24.22.2 / 26.4.0), sqlite probe shows `--experimental-sqlite` required on 22.9.0 only. Artifact: `opencode.mjs` 21,388,775 bytes, sha256 `bb52eed4607adffbb7fbf4a052e0799b7616fd0511b80d3a395d6876ebc23907`; 22 assets (31.36 MB), 0 native binaries; patch series sha256 `76f1b66c4c0ff6906848186902bfd0566dc416a2b3897f1f9e2d241bf8fb42d9`. |
| [41176539017](https://github.com/Justintunsday/opencode-ios/actions/runs/41176539017) | `14a5d9f` | **success** | Current artifact: same iOS build plus patch 0006 (TMPDIR fallback, persistent-PTY capability false, ripgrep install hint). 18/18 host-Node smoke commands passed again; asset tree is byte-identical to the previous run (`06ef5eb6…`, 22 files / 32,881,480 bytes — deterministic). Artifact: `opencode.mjs` 21,389,137 bytes, sha256 `69ce398b9d60bca0d93110417a91f910962e722b48271c3da58c8e5d8f7657ce`; patch series sha256 `5cb5ceb52c96c7631010de11e13dfc10774d2fd627adcb274b599e1756360c4a`. |

The workflow never claims device success: `bundle-manifest.json` always records
`verification_status.device_verified = false` and the runner only executes stock host
Node binaries.

## 5. Host-Node smoke matrix

Smoke tests execute the staged `opencode.mjs` on **stock Node.js** binaries on the build
host with a throw-away `HOME`. They prove the JavaScript bundle links, the CLI starts and
its embedded server boots; they are **not** device verification (the iPhoneOS runtime is
`--jitless`, has no WebAssembly, no PTY/watch/ffi native addons, and `process.platform`
is `ios`).

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
| Image resize (photon WebAssembly) | WebAssembly disabled in the shipped runtime → image normalization/auto-resize unavailable; image files still pass through. | patch 0003 + prelude does not set `OPENCODE_PHOTON_WASM_PATH` |
| TUI syntax highlighting (web-tree-sitter wasm) | wasm payload is included but WebAssembly is disabled; TUI is secondary on device. | asset set + runtime |
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
