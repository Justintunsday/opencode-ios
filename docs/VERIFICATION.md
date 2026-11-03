# Verification matrix — OpenCode iOS (rootless)

> **node26test.7 / 2.2.5-4 — DEVICE-VERIFIED for mobile SSH PTY functionality; the full-screen flash was fixed.**
> Root cause: the TUI wrapped every changed frame in DECSET 2026 synchronized output and the device terminal
> (**EverTerm 1.5-2**, not NewTerm) presents each synchronized block as a full-screen present. iOS now emits
> no 2026 envelope (patch 0018); the user A/B confirmed the flash disappears and the new CLI frame stream has
> 0 sync frames. The user visually confirmed the official node26test.7 package no longer flashes (2026-11-03); see `MOBILE_TUI_DEVICE_RESULTS.md`.
> CLI [41641758047](https://github.com/Justintunsday/opencode-ios/actions/runs/41641758047),
> package [41642851035](https://github.com/Justintunsday/opencode-ios/actions/runs/41642851035):
> installation rc=0, narrow/resize TUI rc=0, 3-turn/121.600-second TUI rc=0, CLI 8/0 and JSON/tool E2E.

> [Exact identities, raw output and limits](MOBILE_TUI_DEVICE_RESULTS.md). Stable `v2.2.5-ios.5` is unchanged.

This document distinguishes **what CI actually proves** from what is **device
evidence**. The current released artifact — **`v2.2.5-ios.5`**, `.deb` SHA-256
`b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073` — is
**DEVICE-VERIFIED**: packaged acceptance PASS=14/FAIL=0 plus a packaged PTY
acceptance of the **line-based REPL** (turn 1 first attempt, a retried turn
recovered on attempt 3, `/new` + another turn, clean `/exit` rc=0, shell-tool
marker written) and packaged non-TTY guidance checks (rc=1, no stack trace)
(2026-11-01). Raw log:
[`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md). Previous releases
`v2.2.5-ios.3` (`8a625f75…`) and `v2.2.5-ios.2` (`2f96fc18…`) also passed
PASS=14/0 and are kept for traceability. The candidate `v2.2.5-ios.4`
(`299ee574…`, first REPL attempt) **FAILED** packaged REPL acceptance and is
**superseded / NOT device-verified** — do not publish it. No CI run claims device
execution: hosted runners cannot execute iOS binaries.

## Status summary

| Evidence class | Environment | Status |
| --- | --- | --- |
| Static package validation (Mach-O, dylibs, paths, permissions, metadata, manifests, entitlements policy, variant consistency) | GitHub Actions `macos-15` runner | **CI-verified** when the workflows are green |
| Runtime capability gating (full-ICU + WebAssembly + JIT required for all variants; `Intl.Segmenter` data; Node 22 requires the 0004/0005 family iOS V8 W^X patch, Node 26 requires the V8 14.6 mprotect patch 0007 family, Node 18 uses the device-proven V8 10.2 memory model and must not require the Node-22/26-only W^X patches) | GitHub Actions `macos-15` runner | **CI-verified** |
| Host-runtime JS smoke | GitHub Actions `macos-15` runner: host Node.js **22.9.0** for node22, **18.20.4** for node18 and (experimental) **26.13.0** for node26 (nodejs.org, checksum-pinned) | **CI-verified** when the workflows are green |
| Native iPhoneOS runtime compile | GitHub Actions `macos-15` runner + iPhoneOS SDK: `build-runtime.yml` (node22) / `build-runtime-node18.yml` (node18) / external `Justintunsday/nodejs26-ios` (node26 experimental) | **CI-verified** |
| Rootless runtime bootstrap facts (entitlement pair, launcher shebang, dpkg `#!/bin/sh` handling, JIT/WASM/ICU requirements) | Real target iPhone, maintainer-executed probes | **Device-verified** (bootstrap) and **DEVICE-VERIFIED for the released package** — see *Device verification results* |
| Native Node 22 v6 runtime execution (JIT, WebAssembly, fetch, full ICU) | Real target iPhone, maintainer-executed probes | **DEVICE-VERIFIED with `--single-threaded`** (JIT loop, WASM compile+instantiate, HTTPS fetch 200, ICU 75/`\p{L}`, `Intl.Segmenter`); without the flag JIT-heavy code SIGBUSes (process-wide mprotect W^X races V8 background threads) |
| Node 22 v6 CLI commands (incl. server-spawning commands after patch `0010`; interactive line-based REPL after patch `0012`) | Real target iPhone, maintainer-executed through the packaged launcher | **DEVICE-VERIFIED:** `--version`, `--help`, `debug paths`, `debug config`, `models`, `auth list`, `session list` all rc=0; mock-provider agent turn rc=0 with the shell tool executing on device. **Interactive REPL: DEVICE-VERIFIED in `v2.2.5-ios.5`** (patch `0013` turn lifecycle + patch `0014` retry budget; the superseded `v2.2.5-ios.4` failed agent turns, fixed in those patches). Full-screen TUI requires the experimental node26/OpenTUI line. |
| Native Node 18 runtime execution with the packaged CLI bundle | Real target iPhone, maintainer-executed probe on a **device-proven community Node 18.20.4 runtime** (not the repo-built runtime) | **CLI commands device-verified (preliminary)** for the Node 18 bundle; the repo-built runtime/package remains the documented **alternative** and is **UNVERIFIED ON DEVICE** (no full-TUI expectation: node18 also gets the line REPL when packaged with patch 0012+) |
| Interactive line-based REPL (patches `0012`–`0014`) | Real target iPhone, maintainer packaged PTY acceptance of `v2.2.5-ios.5` | **DEVICE-VERIFIED:** REPL intro/prompt; turn 1 succeeded on the first attempt (300 ms warm-up); a following turn recovered through the documented 3-attempt retry (`Retrying turn with a fresh server connection…`) and returned `E2E_OK`; `/new` + another turn succeeded first attempt; `/exit` rc=0. Shell tool executed on-device and wrote `/var/mobile/ocdev-e2e.txt`; non-TTY `opencode < /dev/null` and `opencode mini < /dev/null` give clean guidance + rc=1 (no stack trace). |
| Experimental node26 with independent runtime (real OpenTUI via node:ffi) | Real iPhone SE 2 / iOS 16.1.1, node26test.7 + `node26` `26.13.0-1` | **DEVICE-VERIFIED mobile functional scope:** narrow/resize TUI and 3-turn/121.600-second TUI exit 0; CLI 8/0, strict JSON/tool E2E, terminal restoration and zero-byte idle windows. Full-screen flash **FIXED and user-A/B-confirmed**: DECSET 2026 was removed from the iOS profile (patch 0018), test.7 frames have 0/0 sync sequences and zero-byte idle windows; user visually confirmed the official package no longer flashes; [exact identities and crash attribution](MOBILE_TUI_DEVICE_RESULTS.md). |
| Actual packaged CLI execution on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless | Real device, released `.deb` sha256 `b23ed1fc…` (v2.2.5-ios.5), `8a625f75…` (`.3`), `2f96fc18…` (`.2`) | **DEVICE-VERIFIED — packaged acceptance PASS=14 FAIL=0 on all three releases (2026-11-01)**; `.5` additionally passed the packaged REPL PTY acceptance and non-TTY guidance; see [`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md) for raw logs |

> **Device status:** the current release **`v2.2.5-ios.5`** (`.deb` SHA-256
> `b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073`) is
> **DEVICE-VERIFIED**: packaged acceptance PASS=14/FAIL=0 plus a packaged PTY
> acceptance of the line REPL (first-attempt turn, a retried turn recovering on
> attempt 3, `/new` + another turn, clean `/exit` rc=0, shell-tool marker written)
> and packaged non-TTY guidance checks (rc=1, no stack trace). Previous releases
> `v2.2.5-ios.3` (`8a625f75…`) and `v2.2.5-ios.2` (`2f96fc18…`) also passed
> PASS=14/0 and are kept for traceability. Raw evidence:
> [`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md). CI workflows on hosted macOS
> runners still cannot execute iOS arm64 binaries, so their generated reports keep
> the literal `UNVERIFIED ON DEVICE`/`DEVICE TESTS: NOT PERFORMED` wording: that
> is a statement about the runner, not about these released artifacts.

### Runtime variants and current candidates

Two runtime variants are packaged from the same launcher/layout; the `.deb` ships
exactly one and `package-report.json` records which (`variant` / `runtime_kind`).
The **experimental node26** workflow now builds `node26test.7` with an exact
dependency on independent `node26` `26.13.0-1`, instead of embedding Node. It is
DEVICE-VERIFIED for the real TUI; the stable node22 release is unchanged. The
embedded test.4 acceptance remains a historical record below.

| Variant | Runtime | Status |
| --- | --- | --- |
| **`node22`** (primary) | Node.js **22.9.0** iPhoneOS arm64, v6 **mprotect RW⇄RX W^X** model, full-ICU, built-in sqlite | **DEVICE-VERIFIED for the released `.deb`s** (`v2.2.5-ios.5` current, `.3`/`.2` previous; packaged acceptance PASS=14/0 on all + packaged REPL PTY acceptance and non-TTY guidance on `.5`) with the mandatory `--single-threaded` launcher flag. Runtime run `41273024931` (node sha256 `cf707ebe…`, 2-key signed): JIT loop, WebAssembly, HTTPS `fetch` 200, ICU 75/`\p{L}`, `Intl.Segmenter` PASS; CLI matrix and mock-provider agent turn PASS through the packaged launcher. |
| **`node18`** (fallback) | Node.js **18.20.4** iPhoneOS arm64 (V8 10.2 memory model, full-ICU, bundled sql.js sqlite shim) | **Documented alternative, CI-validated only (UNVERIFIED ON DEVICE).** Final corrected-manifest build: package run `41291038144`, `.deb` 49,498,348 B sha256 `0be49c37…`, node sha256 `74e1c5c3…` (runtime run `41285669688`, minOS 13.0 derived from vtool, clean dylib list), CLI `41288234583` node18 bundle; CI 47/0/1 PASS. The Node 18 CLI bundle earlier ran on the target iPhone with a community Node 18.20.4 runtime (`--version`, `debug paths`, `debug config`, `models`, `session list` rc=0; sql.js sqlite database created). |
| **`node26`** (experimental Phase D) | Node.js **26.13.0** iPhoneOS arm64, node:ffi + clang/ld64 OpenTUI renderer | **DEVICE-VERIFIED in `v2.2.5-ios.5-node26test.7`** with external `node26 (= 26.13.0-1)`; command `node`, author `nodejs`, mandatory `--single-threaded` and `/var/jb` renderer assets. Separate experimental Actions artifact; stable node22 release unchanged. |

Node 22 v6 device evidence (maintainer, real iPhone SE 2 / iOS 16.1.1 /
Dopamine rootless; raw outputs will be recorded below once the packaged
acceptance run is done):

- 2-key entitlement set exactly (`platform-application` +
  `com.apple.private.security.no-sandbox`); v6 runtime node sha256
  `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`
  (106,842,800 bytes), CI run `41265520491`.
- With `--single-threaded`: `node -e` JIT loop rc=0; JIT+WASM; `fetch https` 200;
  `Intl`/ICU 75/`\p{L}` OK; WebAssembly compile+instantiate OK.
- Without `--single-threaded`: JIT-heavy code SIGBUS (signal 10/`138`) — V8
  background threads race the process-wide `mprotect` toggle. The launcher must
  therefore always pass `--single-threaded`.
- CLI on device with v6 + `--single-threaded`: `--version`, `--help` (full help
  now works: full ICU fixes `Intl.Segmenter`) and `debug paths` rc=0.
- Commands that spawn a server child SIGBUS because the CLI child-spawn
  whitelist drops `--single-threaded`; CLI patch `0010` adds it to the whitelist
  and device retest follows.

Node 18 CLI device evidence (maintainer, community Node 18.20.4 iPhoneOS runtime,
before the CI-built full-ICU runtime existed; the released node22 v6 package does
not depend on this):

- `opencode2-node --version` → `opencode2-node v2.2.5` (rc=0)
- `debug paths`, `debug config`, `models`, `session list` → rc=0 (sql.js sqlite
  shim works; database file created)
- `--help` → crashes in `Intl.Segmenter` **only because that reference runtime is
  small-ICU**; the shipped runtime is full-ICU, so this is expected to pass on the
  packaged runtime and is part of the acceptance run.
- One CLI bug observed (standalone server child start) is addressed by CLI patches
  `0009`/`0010`; device retest pending with the final package.

### Latest CI-verified package

The node22-v6 package is the shipped artifact. Current release **`v2.2.5-ios.5`**
(runtime `41273024931`, patch-0014 CLI `41291337297`) is **DEVICE-VERIFIED** —
packaged acceptance PASS=14/0 + packaged REPL PTY acceptance + non-TTY guidance
checks — and is published at
<https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5>. Previous
releases `v2.2.5-ios.3` (patch-`0011` CLI) and `v2.2.5-ios.2` (patch-`0010` CLI)
also passed PASS=14/0 and are kept for traceability. The candidate
`v2.2.5-ios.4` (patch-`0012` CLI) **FAILED** packaged REPL acceptance and is
**superseded / NOT device-verified** — do not publish it. The pinned runs below
identify the exact device-tested artifacts.

**Current release — v2.2.5-ios.5 (DEVICE-VERIFIED)**

| Item | Value |
| --- | --- |
| Release | <https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5> |
| Package workflow run | <https://github.com/Justintunsday/opencode-ios/actions/runs/41292412240> (pinned runtime `41273024931`, CLI `41291337297`) |
| Package artifact | `OpenCode-iOS-rootless`, artifact id `13077629042` |
| `.deb` | `OpenCode-iOS-rootless.deb`, 52,926,812 bytes |
| `.deb` SHA-256 | `b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073` |
| Variant / runtime | `node22` / v6 mprotect W^X; runtime node sha256 `cf707ebe…` (unchanged device-verified binary) |
| CLI artifact | run <https://github.com/Justintunsday/opencode-ios/actions/runs/41291337297> (patch `0014`: REPL turn lifecycle + 3-attempt retry/warm-up); `opencode.mjs` 21,397,681 bytes, sha256 `e99ac8d12f083539289fbeeb6ddc07a40348e8eec0db3a76c3d628409a826950` |
| Package validation | `ci_status=PASS`, 47 PASS / 0 FAIL / 1 SKIP |
| Verification workflow | <https://github.com/Justintunsday/opencode-ios/actions/runs/41293124128> (artifact `port-verification`, id `13077908178`): 48 PASS / 0 FAIL / 1 SKIP, `ci_status=PASS` |
| Device status | **DEVICE-VERIFIED (2026-11-01)** — packaged acceptance **PASS=14 FAIL=0** plus packaged **REPL PTY acceptance** (turn 1 first attempt, a following turn recovered via the 3-attempt retry, `/new` + another turn, clean `/exit` rc=0, shell-tool marker `/var/mobile/ocdev-e2e.txt` written) and **non-TTY guidance** (`opencode`/`opencode mini` with stdin redirected: rc=1, clean guidance, no stack trace). Installed identity confirmed: runtime `cf707ebe…`, CLI `e99ac8d1…`, launcher `86f68f21…`. Raw log: [`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md). |

**Superseded candidate — v2.2.5-ios.4 (CI-green; device REPL acceptance FAILED; do not publish)**

| Item | Value |
| --- | --- |
| Package workflow run | <https://github.com/Justintunsday/opencode-ios/actions/runs/41284719984> (pinned runtime `41273024931`, CLI `41284206666`) |
| Package artifact | `OpenCode-iOS-rootless`, artifact id `13074840907` |
| `.deb` | `OpenCode-iOS-rootless.deb`, 52,947,004 bytes |
| `.deb` SHA-256 | `299ee574a8b983b435c41d65e2cfbd26914dcb4f2dad2887f7413e074f1fdc56` |
| Variant / runtime | `node22` / v6 mprotect W^X; runtime node sha256 `cf707ebe…` (unchanged) |
| CLI artifact | run `41284206666` (patch `0012`: line REPL); `opencode.mjs` sha256 `ee15a9b185656e3c52350aa286986266e4677b6d851fb8a15036f72bfdef7fac` |
| Package validation | `ci_status=PASS`, 47 PASS / 0 FAIL / 1 SKIP; test-port run `41285258247` (artifact `13073949712`) 48/0/1 |
| Device result | **FAIL (packaged REPL agent turns, patch `0012`):** REPL starts, `/help`/`/exit` work, but agent turns error `Transport: terminated` then `Transport: fetch failed` with no provider traffic; marker not written. Same headless `opencode run --standalone` control PASSED on the same device/HOME/mock. Root cause: REPL reuses one `ServerConnection` across turns; fixed by CLI patch `0013` (device-functional: 4 turns + marker, retries on first-attempt transport flake); patch `0014` hardens retries. Superseded — do not publish. |

**Previous release — v2.2.5-ios.3** (kept for traceability; DEVICE-VERIFIED PASS=14/0 + PTY guidance)

| Item | Value |
| --- | --- |
| Package workflow run (node22 v6) | <https://github.com/Justintunsday/opencode-ios/actions/runs/41279438605> (dispatch; pinned runtime `41273024931`, CLI `41278475579`) |
| Package artifact | `OpenCode-iOS-rootless`, artifact id `13072533478` |
| `.deb` | `OpenCode-iOS-rootless.deb`, 52,964,804 bytes |
| `.deb` SHA-256 | `8a625f75a1f1fa3909d5128491c781a6559fff6d8d6894b9156e90e8d0d880dc` |
| Version / arch | `2.2.5-1` / `iphoneos-arm64` |
| Variant / runtime kind | `node22` / `node22`; runtime node_version `22.9.0` |
| Runtime artifact run | <https://github.com/Justintunsday/opencode-ios/actions/runs/41273024931> (v6 mprotect W^X; node sha256 `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`, 106,842,800 bytes, 2-key signed) |
| Launcher contract | unchanged from v2.2.5-ios.2: `--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings --max-old-space-size=1536`; launcher sha256 `86f68f21…` confirmed on device |
| CLI artifact | run <https://github.com/Justintunsday/opencode-ios/actions/runs/41278475579> (patch `0011`: clean TUI-unavailable guidance + exit 1); `opencode.mjs` 21,392,407 bytes, sha256 `484b2c1c6b8d932e5cde74d197b260e73abf8e25600f38d79239c6a8abf60f9d`; 22 assets; 11 patches; Node 22.9.0 smoke passed |
| Optional bundled `rg` | `ios-ripgrep`: sha256 `6cc1cea8bc1dbe159f026419d50e404eda6ee1556808e8bbefb37cde9e121b7b` |
| Package validation | `ci_status=PASS`, 47 PASS / 0 FAIL / 1 SKIP (optional `ios-jit-shim` not shipped) |
| Verification workflow | <https://github.com/Justintunsday/opencode-ios/actions/runs/41280083940> (artifact `port-verification`, id `13072243583`): 48 PASS / 0 FAIL / 1 SKIP, `ci_status=PASS` |
| Device status | DEVICE-VERIFIED packaged acceptance PASS=14/0 + packaged PTY TUI-guidance tests; superseded by `.5` (REPL) |

**Previous release — v2.2.5-ios.2** (kept for traceability; also DEVICE-VERIFIED PASS=14/0)

| Item | Value |
| --- | --- |
| Package workflow run | <https://github.com/Justintunsday/opencode-ios/actions/runs/41274221353> (pinned runtime `41273024931`, CLI `41273112229`) |
| Package artifact | artifact id `13071295324` |
| `.deb` / SHA-256 | 52,968,920 bytes / `2f96fc183416ef336fc9855b9dedc51e6baaf89cda996b0147b31444dbef446b` |
| CLI artifact | run `41273112229`; `opencode.mjs` sha256 `2e916ffad16fb7ae2b71d4446a527d1fa11ec82e94d7cd12932373d734cbd410` (patch `0010`) |
| Verification workflow | run `41274690207` (artifact `13070776185`), 48/0/1 |
| Device status | DEVICE-VERIFIED packaged acceptance PASS=14/0; superseded by `.3` (TUI guidance) |

### Node 18 alternative build (CI-validated only — UNVERIFIED ON DEVICE)

The Node 18 variant is **not** the release artifact; it is documented as an
alternative fallback with sql.js sqlite persistence.

| Item | Value |
| --- | --- |
| Status | **CI-VALIDATED only; UNVERIFIED ON DEVICE.** Documented alternative — the node22 v6 package is the primary/device-verified line. The Node 18 CLI bundle itself earlier ran on a community Node 18 runtime (see *Interim device evidence*). |
| Package workflow run | <https://github.com/Justintunsday/opencode-ios/actions/runs/41291038144> (pinned runtime `41285669688`, CLI `41288234583`) |
| Package artifact | `OpenCode-iOS-rootless`, artifact id `13076788227` |
| `.deb` | `OpenCode-iOS-rootless.deb`, 49,498,348 bytes |
| `.deb` SHA-256 | `0be49c3740544fb69d946a842c69d0d1c1526fcff87bad970474e603dd7b9440` |
| Variant / runtime | `node18` / Node.js 18.20.4; runtime node sha256 `74e1c5c3ca1e8d5c1430552706cf21151941dfd6fa97a759345aea98aa247bea` (81,511,888 B; manifest minOS 13.0 derived from vtool, clean `linked_dylibs`, full-ICU/JIT/WASM, 2-key entitlements) |
| CLI artifact | run `41288234583`, `opencode-cli-node18-ios`; `opencode.mjs` sha256 `0bfdf8f5c8699d828e10c1fc23bbcc8ed0b29c0309f99624a014bfb1fa729df7`; sql.js assets present |
| Package validation | `ci_status=PASS`, 47 PASS / 0 FAIL / 1 SKIP (optional jit-shim) |
| Verification workflow | <https://github.com/Justintunsday/opencode-ios/actions/runs/41291595265> (test-port `variant=node18`; artifact `port-verification` id `13077258415`): 48 PASS / 0 FAIL / 1 SKIP, `ci_status=PASS` |
| Device status | not device-accepted; no primary acceptance requirement (documented alternative). Earlier interim node18 package run `41285467457` (`.deb` `ed745667…`) is superseded by this corrected-manifest build. |

### Mobile node26test.7 (DEVICE-VERIFIED functional scope)

OpenCode `2.2.5-4`, package run `41642851035`, CLI run `41641758047`, same independent
Node and renderer as test.5. Installation rc=0; 40×12/resize/Unicode draft and 40×18
3-turn/121.600-second TUI exit 0 with terminal restoration; CLI 8/0, headless tool JSON E2E.
The previous test.6 stream carried 12/12 (resize) and 164/164 (three-turn) DECSET 2026 pairs;
test.7 emits 0/0 and three zero-byte idle windows. The user A/B confirmed the 2026 envelope caused
the EverTerm 1.5-2 whole-screen flash (the user visually confirmed the official package (2026-11-03)).
See [current identities and evidence](MOBILE_TUI_DEVICE_RESULTS.md); later System V probes
produced SIGSYS records and are separately attributed there.

### Previous independent node26 + OpenCode test.5 (DEVICE-VERIFIED, experimental)

The default command is now `node`; package ID `node26`, version `26.13.0-1`,
author `nodejs`. OpenCode `2.2.5-2` depends on that exact runtime package and
contains no Node executable. Both archives were installed on the device with rc=0.

| Item | Accepted value |
| --- | --- |
| OpenCode label / package | `v2.2.5-ios.5-node26test.5`; `opencode` `2.2.5-2`, `iphoneos-arm64` |
| OpenCode package run | [41621747546](https://github.com/Justintunsday/opencode-ios/actions/runs/41621747546); artifact `opencode-ios-rootless-node26` contains both debs |
| OpenCode deb | `OpenCode-iOS-rootless-node26.deb`, **30,782,884 bytes**, SHA-256 `7f01f19162e63ab4c9d18e444ac7028ebb601db3bf7ed648e0cfaaada9fb0895` |
| Independent Node package | `node26` `26.13.0-1`; author `nodejs`; command `node` |
| Node package run | [41620234785](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41620234785); artifact `node26-rootless` |
| Node deb | `node26_26.13.0-1_iphoneos-arm64.deb`, **25,893,168 bytes**, SHA-256 `c6cda114912707b5c229178449e0cc0a641fa7165c270a8dd81456196fed9e51` |
| Dependency / ownership | `opencode` depends on `node26 (= 26.13.0-1)`; no embedded Node executable; legacy runtime paths are relative links |
| Compiled inputs | Runtime [41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128), node SHA `84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9`; CLI [41584007287](https://github.com/Justintunsday/opencode-ios/actions/runs/41584007287), mjs SHA `1aab71859d5992e49b54f91fbe574578679dee3970693dc0176f9257869a3283`; renderer [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506), dylib SHA `4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868` |
| Static validation | Node deb **23 PASS**; app builder **68 PASS**, native `dpkg-deb` metadata/combined extraction checks and 5 renderer builtin checks; CI does not execute iPhoneOS binaries |

Actual acceptance: Node 11 checks plus 192 HTTP / 24 wasm-module stress, Node REPL
rc=0, CLI **8 PASS / 0 FAIL**, headless tool E2E with 6 strict JSON events, normal
TUI **32.314 seconds / rc=0**, and **3 shell/reply TUI turns in 122.328 seconds / rc=0**.
Parent/child/tool execPath resolves to the independent runtime and retains
`--single-threaded`. The installed revised smoke helper passed serially with no
warnings; `dpkg --verify node26 opencode` returned 0. Owned test processes were
cleaned up while existing user services, TUI and Node REPL remained running.

CrashReporter changed **0 → 3 `.ips`**, all system Jetsam reports. Their Node
entries have no termination reason/kill delta; **no Node crash or Node Jetsam
victim was observed**. One report contains system memory-pressure terminations;
two contain `accessoryupdaterd` per-process-limit terminations. This is a functional
device acceptance with documented memory-pressure observations.

Exact exits, raw PTY substrings/checksum, the initial concurrent-smoke warning,
serial rerun and all report filenames are recorded in
[`NODE26_EXTERNAL_DEVICE_RESULTS.md`](NODE26_EXTERNAL_DEVICE_RESULTS.md).
Installation: [`NODE26_EXTERNAL_RUNTIME.md`](NODE26_EXTERNAL_RUNTIME.md).
The stable `v2.2.5-ios.5` release is unchanged.

### Previous embedded node26test.4 + OpenTUI (DEVICE-VERIFIED history)

**`v2.2.5-ios.5-node26test.4` is DEVICE-VERIFIED for the real full-screen OpenTUI TUI**
on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless (2026-11-03 Asia/Hong_Kong).
It remains a separate experimental Actions artifact. The stable `v2.2.5-ios.5` release
is unchanged. CI reports retain runner-scoped `UNVERIFIED ON DEVICE` wording; the device
results below come from SSH command results and actual allocated PTYs.

| Item | Verified value |
| --- | --- |
| Label / package | `v2.2.5-ios.5-node26test.4`; `opencode` `2.2.5-1`, `iphoneos-arm64` |
| Package run | [41584835462](https://github.com/Justintunsday/opencode-ios/actions/runs/41584835462); artifact `opencode-ios-rootless-node26` |
| `.deb` | `OpenCode-iOS-rootless-node26.deb`, **56,849,780 bytes**, SHA-256 **`c64d99246ab1d1e9245a991217cb60c05f4c0c161ab56a599b182e7a4fbf934f`** |
| CLI run | [41584007287](https://github.com/Justintunsday/opencode-ios/actions/runs/41584007287); artifact `opencode-cli-node26-ios` |
| `opencode.mjs` | **21,398,737 bytes**, SHA-256 **`1aab71859d5992e49b54f91fbe574578679dee3970693dc0176f9257869a3283`** |
| Renderer run | [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506); `libopentui.dylib` **4,181,472 bytes**, SHA-256 **`4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868`** |
| Runtime run | [41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128); `ios-node26-runtime-ffi`, Node 26.13.0, **134,710,336 bytes**, SHA-256 **`84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9`** |
| Runtime source | `wasm-trap-handler-fix` commit `7cd359f377d9d37dfe13d929927cf67274451ec2`; W^X 0007/0009, wasm allocator 0011, platform 0012, trap-handler 0013, **libffi callback table 0014 + anonymous RW→RX code 0015**, and **foreground-only V8 JobHandles 0016** |
| Static package validation | **50 PASS / 0 FAIL / 2 SKIP**; `experimental=true`, `bootstrap_prep=false`, `require_ffi_runtime=true` |

The CLI embeds the pinned renderer and packaging verifies the same bytes. The renderer is
linked by Xcode clang/ld64 from the Zig static archive, then Apple codesign ad-hoc signed.
Its manually built compiler-rt uses `-fno-builtin -fno-stack-check -fno-stack-protector`;
the final Mach-O audit rejects self-calling `memset` / `memcpy` implementations.
The Node executable retains its two-key ldid signature. Runtime assets resolve from
`/var/jb/usr/lib/opencode/cli/assets` through `OPENCODE_NODE_ASSETS_DIR` / `OTUI_ASSET_ROOT`.
The old `/var/mobile/Library/OpenCode/assets` mirror workaround was incorrect and is removed;
real `/var/mobile` dylib executable mmap is sandbox-denied.

| Device check | Actual result |
| --- | --- |
| Install downloaded `.deb` | `sudo dpkg -i` rc=0; `install ok installed`; installed node / CLI / renderer hashes match the pinned artifacts |
| Runtime identity | `v26.13.0 ios`, rc=0 |
| FFI / wasm memory | `node:ffi dlopen=function`; `wasm_memory_bytes=65536`, rc=0 with `--single-threaded` |
| FFI callbacks | `FFI_CALLBACK_OK` (qsort callback + reentrant getpid), rc=0; renderer editor insert with a registered JS callback rc=0 |
| WASM / HTTP regression | `WASM_HTTP_STRESS_OK requests=192 modules=24`, rc=0; varied modules plus concurrent localhost fetches and main-thread JIT loops |
| Normal PTY | `cd /var/mobile/Documents && timeout -s KILL 60 /var/jb/usr/bin/opencode`; xterm-256color 80×24, real full-screen drawing, notification channel, alternate screen and OpenCode title; typed `/exit` → **rc=0**, no forced stream close |
| Long PTY + mock provider | 132.3 seconds; accepted a prompt, local mock shell-tool turn PASS (marker + mock tool result + E2E_OK rendered); typed `/exit` → **rc=0** |
| Non-TTY | `opencode < /dev/null` → clean guidance, **rc=1** |
| Headless commands | `--version`, `models`, `debug paths` → **rc=0** |
| Headless E2E | `run --standalone --model lmstudio/mock-opencode-1 ...` → **rc=0**, shell-tool marker written; mock observed tool result and returned `E2E_OK` |
| Child process | Actual `serve --service` argv includes **`--single-threaded --max-old-space-size=1536`** (patch 0010 forwarding) |
| Crash comparison / cleanup | **No new `.ips` files** relative to the pre-install baseline; all leftover `opencode.mjs` / `runtime/node` processes killed after testing |

PTY text and Enter were sent as separate input events, matching keyboard input. Sending
`/exit` and CR in one bulk write was interpreted as pasted text by the UI and did not submit.

Selected raw PTY sequences (noncontiguous; ESC/control bytes escaped):

```text
\x1b]99;i=opentui-notifications:p=?;\x1b\\
\x1b[?1049h
\x1b]7501;state=idle:app=opencode\x1b\\
\x1b]0;OpenCode\x07
[pty exit=0]
```

Captured server argv:

```text
22739 22679 /private/preboot/CB30563943D06BAB7C7DC1B1D006DF52A0066158D29F822D2CD6596B5C2CB27D1DB5486619F43C8021E060A997E5660A/dopamine-ROEKTm/procursus/usr/lib/opencode/runtime/node --single-threaded --no-warnings --max-old-space-size=1536 /var/jb/usr/lib/opencode/cli/opencode.mjs serve --service
```

Raw evidence is retained in the maintainer workspace at
`C:\opencode\device\artifacts\node26test4-evidence\` (`install.json`, `preflight.json`,
`matrix.json`, `wasm-http-stress.json`, `headless-e2e.json`, `pty-basic.raw.bin`, `pty-long.raw.bin`, corresponding
JSON input/exit/process snapshots and `device-summary.json`). Basic PTY SHA-256
`b2af499e70d27c536a349044cbb45ad204fc04abbf9982cce51db47179e6f250`; long PTY SHA-256 `e606da05b394afcd2bf0b7e2631d0c26e4c6441c539f500c957a8e0bf76a058a`.

The pre-existing `node-2026-11-03-055430.ips` reports an instruction permission fault in a
JIT region and four `node-V8Worker` threads. It predates this install and has no recorded argv.
The later `074108` crash below reproduced a wasm publication race despite inherited flags;
the old crash is consistent with that mechanism. It did **not** recur in the final packaged
tests with runtime patch 0016. This is bounded session acceptance, not an indefinite soak test.

The **first test.4 candidate was rejected**, despite CI 50/0/2: package run `41537717568`,
deb SHA `fda720ef5f6dd394553ebb8ea16a60f3bf114f9db556060fc0180c04bb95513f`, used the old
runtime run `41450472333`. It rendered but hung on the first input; a minimal renderer edit
probe isolated the missing callback policy (plain insert rc=0, insert with JS callback
SIGBUS/rc=138; `node-2026-11-03-065307.ips`, callback PC in `MALLOC_TINY rw-`). Runtime patch
0014 enables libffi's Apple ARM executable trampoline table for iOS instead of executing
malloc memory. The intermediate runtime run `41541888412` then reported
`ffi_closure_alloc failed`: iOS stripped execute permission from shared code remaps.
Runtime patch 0015 copies the fixed, PC-relative instruction table into anonymous RW pages,
flushes I-cache and seals the code page RX; closure metadata stays in its separate RW page.
No MAP_JIT or RWX is requested. The first package also failed non-TTY acceptance;
CLI patch 0017 now checks TTY before the
FFI branch and returns guidance/1. These failures and their raw logs are archived under
`candidate1/`.

The **second candidate was also rejected**: package run `41546616774`, SHA
`2fb58f05db9596e8fba03a9302d5185911b72d628793fc98cdbea52b4e5a9776`, runtime
`41544904398` / `52085f12…`. Callback and headless probes passed, but actual `serve --service`
PID 93785, whose observed argv included `--single-threaded`, crashed in
`node-2026-11-03-074108.ips`. Main-thread PC was in a JIT page mapped `rw-`; another
`node-V8Worker` was inside wasm `NativeModule::PublishCode` / `SetJitWriteProtected`.
V8 clamps wasm job concurrency to at least one, and Node supplied four platform workers
despite `--single-threaded`. Runtime patch **0016** gives iPhoneOS V8 JobHandles zero
background workers; `Join()` adds the foreground participant. Synchronous wasm still
compiles, without racing main-thread execution during process-wide W^X toggles. Other
targets keep their original worker count. Evidence is archived under `candidate2/`.
Runtime run `41547842175` was rejected before packaging because its binary was still
`52085f12…`: an omitted `diff --git` header prevented incremental source tracking. Commit
`7cd359f` corrected the patch header; the accepted build uses a different checked binary.
The same second candidate's headless E2E also exited 138 (`node-2026-11-03-075024.ips`);
its wasm compilation worker was relocating code while the main thread faulted on a RW JIT page.
The crash-free statement above compares the **final installation** against its own saved
pre-install baseline, which includes these earlier diagnostic crashes.
The comparison window is `2026-11-03T05:38:51.140Z` through `2026-11-03T05:44:11.791Z` (UTC):
**103 baseline / 103 final `.ips` files, zero new names**.

A further candidate, package `41551508863` / `691c24e4…`, passed the installed runtime
probes, basic PTY exit and headless E2E, but failed full TUI submission. Device
`spindump` (`submit-spin.txt`) sampled 100% main-thread CPU in renderer `_memset`.
Disassembly of the old `41531609826` / `5a2f016b…` renderer showed an unconditional
branch from `0x242994` to its own `_memset` entry `0x242984`; `_memcpy` also called
itself. Manual compiler-rt compilation lacked Zig's required no-builtin policy.
Renderer commits `a83f4d4` / `59c2ed0` add the correct flags and a static regression
audit. This fixes both program-status text and styled-text hangs without filtering
terminal status fields or disabling JIT optimization.

Rendering the first reply then exposed a separate user-worker race
(`node-2026-11-03-131931.ips`, faulting `WorkerThread` in `node::worker::Worker::Run`).
`--single-threaded` does not disable Node `worker_threads`. Dependency patch 0002
keeps the tree-sitter client from creating an iOS worker and reports unsupported
initialization; OpenTUI's existing plain-text code fallback renders the content.
The real native renderer, Markdown layout, tool calls and terminal program-status
reports remain active. Tree-sitter syntax highlighting is unavailable on this variant.

The local fixture explicitly defines its OpenAI-compatible model. A discovery-only first
attempt returned `Model unavailable` / rc=1 before asynchronous LM Studio discovery completed;
it did not crash. That fixture failure is retained under `fixture-model-discovery/`.
The final headless and TUI turns use the explicit mock model and a dummy local-only key.

Limits: real external provider API keys/auth were not exercised; the provider turn used a
local mock. Tree-sitter syntax highlighting, clipboard, native interactive tool PTYs /
Ghostty panes and audio acceptance
remain unavailable or unverified; other devices/iOS versions are untested. See
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) and [`OPENTUI_IOS.md`](OPENTUI_IOS.md).

Previous `node26test.3` (run `41483801031`, SHA `7bbfbfbd…`) bundled the old ldid renderer and
the incorrect mobile asset mirror; reinstalling it overwrites the working renderer. It is
superseded. `node26test.2` additionally lacked the wasm trap-handler fix. Non-FFI
`node26prep.*` artifacts are pipeline preparation only and cannot run the real TUI.

#### Extended 10-minute installed-package session — 2026-11-03

The **same installed package** from run `41584835462` / SHA `c64d99246ab1d1e9245a991217cb60c05f4c0c161ab56a599b182e7a4fbf934f`
passed an additional **612.4-second** real SSH PTY session (80×24).
The CLI, runtime and renderer hashes were unchanged. This test used an isolated HOME,
the local dummy-key provider on port 8789, `opencode --standalone`, and a 512 MiB
heap cap. The private child was `serve --stdio --port 0`, with inherited
`--single-threaded --max-old-space-size=512`; the user's pre-existing root service
was preserved.

| Extended device check | Actual result |
| --- | --- |
| Prompt / shell / reply turns | **12/12**: separate keyboard input and Enter; 12 on-device shell markers, 12 provider tool results and 12 rendered `SOAK_OK_01`–`SOAK_OK_12` replies |
| Fenced code fallback | **12/12** distinct `const check01 = 1;`–`const check12 = 1;` code lines captured from the native TUI stream |
| Normal exit | Typed `/exit` at 610 seconds, Enter at 612; **rc=0**, no forced channel close |
| Crash comparison | **105 → 105 `.ips` files; zero new names**, `2026-11-03T08:10:14.164Z`–`2026-11-03T08:20:56.584Z` UTC |
| Cleanup | Only the three recorded test processes (UID 501, checked start time and argv) were targeted; none remained. The pre-existing root service was still present afterward. |

This later baseline includes two system reports produced after the original acceptance:
`icloudsubscriptionoptimizerd.cpu_resource-2026-11-03-143553.ips` and
`JetsamEvent-2026-11-03-143814.ips`. The Jetsam victim was
`icloudsubscriptionoptimizerd` (`per-process-limit`); it had no Node entries.
They predate this extended test. The earlier **103/103** result above retains its own
original time window.

Evidence: maintainer workspace `node26test4-evidence/soak-summary.json`,
`soak-pty.json`, `soak-pty.raw.bin`, `soak-check.json`, `soak-cleanup.json`,
`soak-baseline.json` and `soak-after.json`. Raw stream: **181,385 bytes**,
SHA-256 `ba685cd086ce8b75b3ee2289d64e72143338e7d5e0f1d94a47f4142c5ff7d67e`. This is a bounded multi-turn local-mock test;
real external providers, other devices and indefinite soak testing remain unaccepted.

#### Additional installed CLI acceptance — 2026-11-03

The unchanged installed node26test.4 CLI passed **15 command checks / 0 failures**
in an isolated HOME/project with a local dummy-key provider (port 8790), a 512 MiB
heap cap and private `--standalone` server children. Existing user service PID 71572
was preserved. Version output was `opencode2-node v2.2.5`.

| CLI case | Actual rc | Result |
| --- | --- | --- |
| `version` | `0` | Expected |
| `help` | `0` | Expected |
| `models` | `0` | Expected |
| `paths` | `0` | Expected |
| `config` | `0` | Expected |
| `auth` | `0` | Expected |
| `sessions-empty` | `0` | Expected |
| `stats` | `0` | Expected |
| `run-help` | `0` | Expected |
| `non-tty` | `1` | Expected |
| `mini-non-tty` | `1` | Expected |
| `unknown-option` | `1` | Expected |
| `missing-model` | `1` | Expected |
| `agent-json` | `0` | Expected |
| `sessions-persisted` | `0` | Expected |

`models`, `debug config`, `auth list`, `stats --json` and both `session list --format json`
checks used `--standalone`; `debug paths` resolved the isolated home. Non-TTY bare/mini,
unknown option and missing model correctly returned 1. The matrix's complete argv/output
is retained in `cli-matrix.json` and `cli-matrix-results.tsv` in the maintainer evidence.

The `run --standalone --format json --model lmstudio/mock-cli-1 ...` turn emitted
**6 valid NDJSON events**, including a completed shell tool and final text. The shell
actually wrote `sum.cjs`, then ran the iPhoneOS Node runtime with `--single-threaded`:
`CLI_SUM_TEST_OK passed=2 result=5`. A receipt recorded two passed assertions, zero
failures and result 5. The agent's session ID was present in a later private-server
session listing (empty before the checks; two sessions afterward, including the
missing-model attempt). Stats output also parsed as JSON. No real provider key/API
was exercised.

Crash comparison: **105 → 105 `.ips` files, zero new names**, from
`2026-11-03T08:31:26.703Z` through `2026-11-03T08:39:16.382Z` UTC. Installed runtime/CLI/renderer
hashes were unchanged; no test runtime processes remained.

This review also found two defects in the legacy packaged `device-smoke.sh`:
direct runtime probes omitted `--single-threaded`, and failed HOME directory creation
fell back to `/tmp`, which its exit cleanup would recursively remove. The revised
[repository helper](../packaging/rootless/usr/share/doc/opencode/device-smoke.sh)
now preserves the runtime flags, uses a unique `mktemp` directory, fails safely when
HOME is unavailable, and uses private server children. The revised script was staged
separately on the iPhone: normal smoke **PASS / rc=0**; missing-HOME path **rc=1 as
expected**, with an unrelated sentinel intact. Script SHA-256:
`77084380d529fa1757d708704b634dd337605991d832cf1284066be2eb718651`.

**The deb from run 41584835462 still contains the old helper.** This source fix has not
been repackaged into that immutable artifact; use the revised repository copy for
smoke testing. The tests above executed the installed CLI and the separately staged
helper, with their scopes recorded independently.

Evidence: `cli-summary.json`, `cli-agent-json.ndjson`, `cli-sessions-before.json`,
`cli-sessions-after.json`, `cli-test-receipt.json`, `cli-generated-sum.cjs`,
`cli-smoke-revised.json`, `cli-smoke-no-home.json`, `cli-tests-baseline.json` and
`cli-final.json`. Agent NDJSON SHA-256 `10ad8006cb772f35c6654349b21a72cb2125574195033726c84e626121327524`.

#### Normal TUI startup: root/mobile service-port collision — 2026-11-03

A later bare `opencode` launch was reproduced failing **rc=1 before renderer init**:
`listen EADDRINUSE: address already in use 127.0.0.1:49374`. The pre-existing root
service owned that port; mobile had a separate service registration under its HOME.
The same installed binaries worked with a private `--standalone` server.

After verifying port 49375 was free, the mobile service configuration was backed up
(mode 0600) and its port changed **49374 → 49375**, preserving all other settings and
the root service. Normal `opencode` then rendered the real 80×24 OpenTUI notification,
alternate screen and title; `/exit` returned **0 in 42.232 seconds**. The user also
confirmed the TUI was visible in the phone terminal. Crash files stayed **106/106**.
The test UI exited; a subsequent user TUI and its mobile service were left running.

This is a per-account configuration fix. Root uses 49374; mobile uses 49375 on the
tested device. Different HOME/UID services need distinct ports. `opencode --standalone`
uses a private server when shared managed-service startup is unsuitable. No binary
or package was replaced. Evidence: `tui-repro-mobile.json/.raw.bin`,
`tui-user-port-fix.json`, `tui-user-fixed.json/.raw.bin`, `tui-port-fix-summary.json`.

### Node 22 pipeline history (superseded, not shippable)

| Build | Outcome |
| --- | --- |
| v1 intermediate (run `41185611403`, `.deb` sha `13a0483d...`) | WASM-disabled runtime: every CLI command failed with `ReferenceError: WebAssembly is not defined`. |
| v3 (run `41202900005`, `.deb` sha `cf5db02a...`) | JIT+WASM, no iOS V8 W^X path: SIGBUS on V8-generated code. |
| v4 (package run `41218342323`, `.deb` sha `1d643c3b8b3e4238bb1e692fadce9fcb72f74ea1b7b61621229cf502571b6dc4`) | CI-green (45/0/0 package, 46/0/0 verification); on device SIGTRAP → `FatalOOM` in `CodeRange::InitReservation` because iOS denies `mprotect` RWX. |
| v5 | mprotect W^X first attempt (`0005`); superseded by v6. |
| **v6** (runs `41265520491`/`41273024931`) | Device-working with `--single-threaded`; base of the device-verified releases `v2.2.5-ios.2` and `v2.2.5-ios.3`. |

**Artifact identity — do not rebuild the released artifacts.** The packaged
documentation is part of the `.deb`, so any later docs/code commit produces a
different `.deb` SHA-256. The released artifacts
`v2.2.5-ios.3` (`8a625f75…`) and `v2.2.5-ios.2` (`2f96fc18…`) must **not** be
rebuilt or replaced without re-running device acceptance on the new SHA-256.
`v2.2.5-ios.4` (`299ee574…`) was **not released** (device REPL acceptance
failed) and must **not** be published or described as device-verified. The
released `v2.2.5-ios.5` (`b23ed1fc…`) is the current device-verified artifact.
Their packaged docs reflect the repository state at their build
commits; **this repository document** is the authoritative post-release record.
Later green package runs are pipeline evidence only. **Do not rebuild the
released `.2`/`.3`/`.5` artifacts without re-running device acceptance.**

**Honesty note.** Device evidence for the releases is recorded in
[`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md) and condensed in *Device
verification results* below. CI reports remain runner-scoped (`UNVERIFIED ON
DEVICE`) because hosted runners cannot execute iOS binaries.

## Where the evidence lives

| Artifact | Produced by | Contents |
| --- | --- | --- |
| `OpenCode-iOS-rootless` | `package-rootless.yml` | `.deb`, `SHA256SUMS`, `package-report.json` (contents manifest, Mach-O audit, sizes, SHA-256s, source run ids, device status) |
| `port-verification` | `test-port.yml` | `verification-report.json`, `verification-report.md`, `check-results.json`, `unittest.log`, `host-smoke.json`, extracted-file manifest, `dpkg-deb --info/--contents` dumps |

Latest successful runs (filled in from the artifacts; also recorded in
`package-report.json` → `workflow.run_url` and `sources.inputs.*.run_url`):

| Workflow | Run | Artifact |
| --- | --- | --- |
| `build-runtime.yml` | <https://github.com/Justintunsday/opencode-ios/actions/runs/41207449703> (v4: full-ICU + WebAssembly + JIT + W^X patch 0004) | `ios-node-runtime` |
| `build-opencode.yml` | <https://github.com/Justintunsday/opencode-ios/actions/runs/41192939688> | `opencode-cli-node-ios` |
| `package-rootless.yml` | <https://github.com/Justintunsday/opencode-ios/actions/runs/41218342323> | `OpenCode-iOS-rootless` |
| `test-port.yml` | <https://github.com/Justintunsday/opencode-ios/actions/runs/41218528704> | `port-verification` |

Authoritative, self-describing source of truth: the `package-report.json` inside
the package artifact. It lists every file with path/mode/size/SHA-256, the
Mach-O platform/arch/minOS and dylib linkage audit of the runtime, the upstream
pins, the source workflow run ids/URLs and the full CI validation results.

## CI-runnable checks (runner evidence only)

Produced by `scripts/validate-port.sh` on `macos-15`. Each assertion appears in
`verification-report.json` with id, status (PASS/FAIL/SKIP) and evidence.

| Area | Checks |
| --- | --- |
| Package archive | `.deb` ar structure, `debian-binary 2.0`, control/data members parse; safe extraction (no absolute paths, `..`, or escaping symlinks) |
| Control metadata | `Package: opencode`, `Version: 2.2.5-1` (from `UPSTREAM.lock`), `Architecture: iphoneos-arm64`, `Depends: firmware (>= 15.0)` only (no node/zsh/ldid package deps), `Recommends: git` optional, `Section: Development`, `Priority: optional`, multi-line `Description`, `Installed-Size` sane |
| Rootless layout | every installed path under `var/jb/`; required paths/modes; no unexpected files; `/var/jb/usr/bin/opencode` 0755, runtime node 0755, CLI/assets/docs 0644 |
| Permissions | no setuid/setgid/sticky, no world-writable, documented mode policy |
| Maintainer scripts | `postinst`/`prerm`/`postrm` are `#!/bin/sh`, `set -e`, `sh -n` clean, offline (no curl/wget/apt/npm/pip/ldid calls), `/var/jb`-relative, executed twice against a rewritten root to prove idempotency. (`#!/bin/sh` is intentional: rootless Procursus `dpkg` executes such scripts on the target device even though `/bin/sh` is absent — device-verified with a test deb.) |
| Launcher contract | shebang `#!/var/jb/bin/sh` (kernel-exec'd directly; rootless iOS has no `/bin/sh`), prepends `/var/jb/bin:/var/jb/usr/bin` to `PATH`, execs runtime, forwards `"$@"`, passes `--experimental-sqlite`/`--no-warnings`/`--max-old-space-size`, exports `OPENCODE_NODE_ASSETS_DIR`/`OPENCODE_IOS=1`, documents the JITless escape hatch, no invalid Node 22.9 flags (`--use-system-ca`, `--experimental-ffi`), no `uname` dependence, no embedded credentials |
| Native runtime | `scripts/check_macho.py`: thin arm64 little-endian Mach-O, `MH_EXECUTE`, `LC_BUILD_VERSION platform=iPhoneOS(2)`, minOS ≤ 16.1.1; `otool -L`: iOS system libraries only, no `/opt/homebrew`, `/usr/local`, `@rpath`/`@loader_path`, or macOS-only frameworks; `LC_CODE_SIGNATURE` presence (ldid); entitlements plist parses; `runtime-manifest.json` hashes match the shipped node |
| Runtime build profile | `runtime-manifest.json` → `build.configure_flags` must contain `--dest-os=ios`, `--dest-cpu=arm64` and `--with-intl=full-icu` (or `small-icu` only if it demonstrably supports `Intl.Segmenter`); `--with-intl=none` is rejected (device-verified CLI parse failure). `runtime_policy.webassembly` must declare WebAssembly **enabled** and `runtime_policy.v8_jit` must declare JIT **enabled**: Node 22.9's fetch/undici needs wasm llhttp, and a wasm-disabled/JIT-less runtime fails on device with `ReferenceError: WebAssembly is not defined`. `--v8-options=--jitless` is rejected. For JIT-enabled runtimes the manifest's `source.patches` must list the iOS V8 W^X patch (`0004-ios-jit-write-protect.patch`) — the v3 JIT build without it trapped with SIGBUS when executing generated code on device. The runtime must report ICU (`process.versions.icu`). |
| Runtime entitlements policy | `runtime/entitlements.xml` must contain `platform-application=true` **and** `com.apple.private.security.no-sandbox=true` — the device-verified minimal working set; old allow-jit/executable-memory sets are rejected because they were SIGKILLed on the target device (exit 137) |
| CLI bundle | `opencode.mjs` present and non-placeholder; `assets/**` copied verbatim; `bundle-manifest.json` hash entries verified when the format is recognised; deb files byte-identical to the source artifacts (`sha256` comparison against provenance) |
| CLI artifact policy | `bundle-manifest.json` must not be flagged as a stock upstream build and its required host-Node smoke version must be **22.9.0**, matching the shipped iPhoneOS runtime (a stock Node-26-only bundle is rejected) |
| Native assets | `cli/assets/**` must not ship macOS/desktop Mach-O binaries; every Mach-O asset must report Mach-O `platform=iOS` (the patch series must remove desktop addons) |
| Host-runtime smoke | pinned Node.js **22.9.0** downloaded from nodejs.org with `SHASUMS256.txt` SHA-256 verification; `node opencode.mjs --version` and `--help`; the **packaged launcher** run with `OPENCODE_IOS_PREFIX`/`OPENCODE_IOS_NODE` pointing at the host node (flag ordering, exec, argv forwarding incl. rejection of an unknown flag); version output must contain the pinned upstream version |
| Integrity & hygiene | `SHA256SUMS` matches the `.deb`; contents manifest re-verified against the archive (path/mode/size/SHA-256); no secret files/private keys; no `.git`/`node_modules`/`.DS_Store`/debug artifacts; size limits; packaged docs contain MIT/attribution and state the device status |
| Repository | LF line endings, shell syntax, no secrets in tracked files, packaging layout, workflow contract, factory unit tests (`python3 -m unittest discover -s tests -v`), optional workflow YAML parse |
| Optional components | iPhoneOS `rg` (stretch `ios-ripgrep` artifact): Mach-O + dylib audit when shipped; explicit SKIP when absent. Optional `libjitshim.dylib` (`ios-jit-shim` artifact): iPhoneOS MH_DYLIB audit, conditional `DYLD_INSERT_LIBRARIES` launcher injection, provenance in `package-report.json`; SKIP when absent. |

The **host-runtime smoke is not a device test**. It executes the CLI JavaScript
bundle with a desktop macOS Node.js build of the same version on the same OS
family; it proves the bundle and launcher logic, not the iPhoneOS runtime,
signing, entitlements or iOS process environment.

## Device tests — acceptance matrix (verified for the released artifact)

The following require a real iPhone SE 2 (iOS 16.1.1, Dopamine rootless). The
released `.debs` (`v2.2.5-ios.5` SHA-256 `b23ed1fc…`, `v2.2.5-ios.3`
`8a625f75…`, `v2.2.5-ios.2` `2f96fc18…`) have been executed through this matrix —
see **Device verification results** below and
[`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md); the table remains the
acceptance runbook for future builds/devices. Run the commands from a NewTerm 3
shell or SSH. Full install instructions: [`INSTALL.md`](INSTALL.md).

> **Released artifacts: DEVICE-VERIFIED (PASS=14/FAIL=0 on all three; `.5` also
> passed the packaged REPL PTY acceptance and non-TTY guidance checks, `.3` passed
> packaged PTY TUI-guidance tests, 2026-11-01).** This is maintainer/user-reported
> device evidence, not CI output. CI cannot execute iOS binaries and its reports
> stay runner-scoped.

| # | Test | Command | Pass criterion |
| --- | --- | --- | --- |
| 1 | Install | `sudo dpkg -i ~/Documents/OpenCode-iOS-rootless.deb` | dpkg status `install ok installed`, no errors |
| 2 | Runtime variant | `/var/jb/usr/lib/opencode/runtime/node -p process.versions.node`; `dpkg -s opencode` | released primary prints `22.9.0` (node18 fallback prints `18.20.4`); matches `package-report.json` → `variant`; control description states the runtime |
| 3 | CLI starts | `opencode --version` | exit 0, upstream version (2.2.5) printed |
| 4 | Help (full-ICU/Segmenter) | `opencode --help` | exit 0, usage/commands printed; full ICU means `Intl.Segmenter` works (small-ICU runtimes crash) |
| 5 | Runtime capabilities | `/var/jb/usr/lib/opencode/runtime/node -e "console.log(typeof WebAssembly, process.config.variables.v8_enable_webassembly, typeof fetch, typeof Intl, typeof Intl.Segmenter)"` | `object 1 function object function`; wasm module compiles; `opencode --version` works (no `ReferenceError: WebAssembly is not defined`) |
| 6 | Paths/models (offline) | `opencode debug paths`, `opencode models` | config/data under `/var/jb/var/mobile/...`; model list prints (version-dependent, optional) |
| 7 | sqlite persistence | `opencode session list`; check the database file under `~/.local/share/opencode` | exit 0 and a sqlite file exists (released node22: native `node:sqlite` with `-wal`/`-shm`; node18 fallback: sql.js whole-file shim) |
| 8 | Auth | `opencode auth list`, `opencode auth login` | login completes; credentials only in user home |
| 9 | Offline scripted smoke | `sh /var/jb/usr/share/doc/opencode/device-smoke.sh` | final line `DEVICE SMOKE TEST: PASS` |
| 10 | Liveness/signature | `sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml /var/jb/usr/lib/opencode/runtime/node` then `opencode --version` | re-signed runtime still starts (repair path works; shipped entitlements are the verified minimal pair) |
| 11 | Shell-tool fallback | `sh /var/jb/bin/sh -c 'echo shell-ok'` and (after auth) a CLI shell-tool call | rootless dash runs; CLI-spawned shells resolve through the launcher's `PATH` prepend |
| 12 | git tooling (optional) | `sudo apt-get install -y git`; `git --version`; a git tool call through the CLI | git installed/works; without it the CLI error is actionable |
| 13 | Interactive REPL / TUI-unsupported behaviour | under a real TTY: `opencode` (no args) then `/help`, a prompt, `/exit`; `opencode mini`; non-TTY: `opencode </dev/null` | **TTY: line-based REPL starts** (streamed assistant text + tool activity, `/new`, `/exit`, `/help`, Ctrl-C cancels turn, session continuity) — the stable Node 22 full-screen TUI is unavailable (OpenTUI needs Node >= 26.4 + `node:ffi`); experimental Node 26 test.4 runs the verified real TUI. `opencode mini` aliases the REPL. **Non-TTY: clean guidance, exit 1.** |
| 14 | Agent turn + standalone fix (needs network+auth) | `opencode run "summarise this repository"`; `opencode run --standalone ...` | request completes; the patch-0009 standalone child-server start works |
| 15 | Inspector/CPU profiling | `opencode --inspect ...` (documented stub) | fails gracefully with the documented stub message, not a crash (node18 inspector is stubbed by patch 0008) |
| 16 | Uninstall | `sudo dpkg -r opencode` (then `-P`) | package files gone; `~/.config/opencode` and sessions preserved |

Optional after test 12: confirm a local file edit and a `git` operation through
the agent in a throwaway repository.

## Device verification results

Status: **DEVICE-VERIFIED for the released packaged artifacts.** The maintainer
installed the released `.deb` files on the target iPhone and ran the packaged
acceptance matrix plus a mock-provider agent turn: **PASS=14 / FAIL=0** on both
`v2.2.5-ios.3` (current) and `v2.2.5-ios.2` (previous), and `v2.2.5-ios.3`
additionally passed packaged PTY tests for the TUI-unavailable guidance. Raw
evidence, including command logs, E2E marker content and device identity, is in
[`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md); condensed records are below.

Device results are **user/owner-reported**, not CI-produced. CI reports
(`port-verification`, `package-report.json`) stay runner-only evidence and must
never be presented as device proof — their `device_status` field stays
`UNVERIFIED ON DEVICE` by design because hosted runners cannot execute iOS
binaries.

Target device identity (provided by the project maintainer; no credentials,
account identifiers or keys are recorded anywhere in this repository):

| Property | Value |
| --- | --- |
| Device | iPhone SE (2nd generation), identifier `iPhone12,8`, arm64 |
| OS | iOS 16.1.1 (20B101), Darwin 22.1.0 |
| Jailbreak | Dopamine rootless; `/var/jb` symlink into `/private/preboot/.../dopamine-*/procursus`; ElleKit 1.2 |
| User / tools | `mobile` (uid 501), `sudo` works; dpkg, ldid, zsh installed; NewTerm 3 / SSH; `git` installed separately (Recommends, not a dependency) |
| `HOME` | `/var/jb/var/mobile` in SSH/NewTerm sessions |
| Shells | **no `/bin/sh`, `/bin/bash`, `/bin/zsh`**; rootless shells are `/var/jb/bin/sh` and `/var/jb/usr/bin/sh` (both -> `/var/jb/usr/bin/dash`), plus `/var/jb/bin/bash`, `/var/jb/bin/zsh` |
| `PATH` | `/usr/bin:/bin:/usr/sbin:/sbin:/var/jb/usr/bin`; the packaged launcher prepends `/var/jb/bin:/var/jb/usr/bin` |
| Free space | 96 GiB |

### Post-release QA round on the same released artifact (2026-11-01)

A second real-device QA round on the **same released `.deb` `b23ed1fc…`** (installed
runtime `cf707ebe…`, CLI `e99ac8d1…`, launcher `86f68f21…`) passed end-to-end:
runtime `node v22.9.0`, platform `ios`/`arm64`, ICU 75.1, `Intl` object, `\p{L}`
true, WebAssembly object, JIT loop OK, `fetch https` 200 (all with
`--single-threaded`); CLI matrix (`--version`, `--help`, `debug paths`,
`debug config`, `models`, `auth list`, `session list`) rc=0; packaged PTY REPL
turn 1 hit a transport error then recovered on retry → `E2E_OK` (shell tool wrote
the marker), `/new`, turn 2 `E2E_OK` first attempt, `/exit` rc=0; marker
`opencode-ios-e2e-ok` / `mobile` / `git version 2.39.1` / `qa-repl-work`; non-TTY
`opencode < /dev/null` rc=1 clean guidance; headless `opencode run --standalone`
E2E PASS.

Observed nuance (documented in `KNOWN_LIMITATIONS` items 28/29): transport
failures were aggravated by **stale leftover Node processes** — an earlier
headless E2E failed 3/3 while an old CLI instance and a long-running mock server
were alive; after killing leftover `serve --service`/mock/`runtime/node`
processes and restarting the mock, the same test passed first try. No artifact
change needed; the released `.deb` remains the device-verified artifact.

### Completed device run — 2026-11-01 (UTC) — iPhone SE 2 / iOS 16.1.1 — v2.2.5-ios.5 (current release)

| Field | Value |
| --- | --- |
| Package file | `OpenCode-iOS-rootless.deb` |
| Package SHA-256 | `b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073` (52,926,812 bytes) |
| Release | <https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5> |
| Package variant / runtime | `node22` / v6 mprotect W^X; runtime node sha256 `cf707ebe…`; CLI `opencode.mjs` sha256 `e99ac8d1…`; launcher sha256 `86f68f21…` |
| Package / verification runs | package `41292412240`; test-port `41293124128` (artifact `13077908178`); CLI `41291337297`; runtime `41273024931` |
| Device identity | iPhone SE 2 (iPhone12,8), iOS 16.1.1 (20B101), Dopamine rootless, user `mobile` |
| Result | **FINAL_PACKAGED_ACCEPTANCE PASS=14 FAIL=0** + packaged REPL PTY acceptance + non-TTY guidance checks |

| Test | Status | Evidence / output snippet |
| --- | --- | --- |
| device.install (dpkg) | PASS | `Status: install ok installed`, Version 2.2.5-1, Architecture iphoneos-arm64 |
| device.identity | PASS | installed runtime `cf707ebe…`, CLI `e99ac8d1…`, launcher `86f68f21…` |
| device.repl-turn-1 | PASS | REPL intro/prompt printed; first prompt succeeded **on the first attempt** (300 ms warm-up); tool line shown; `E2E_OK: shell tool executed on iPhone…` |
| device.repl-retry-turn | PASS | a following turn hit the intermittent transport flake, printed two `Retrying turn with a fresh server connection…` lines, then `E2E_OK (3rd attempt)` — the documented 3-attempt retry budget works and returns to the prompt |
| device.repl-new-session | PASS | `/new` → `Starting a new session on the next prompt.`; next prompt succeeded first attempt |
| device.repl-exit | PASS | `/exit` → pty exit 0 |
| device.shell-tool marker | PASS | `/var/mobile/ocdev-e2e.txt`: `opencode-ios-e2e-ok` / `mobile` / `git version 2.39.1` / `/var/mobile/repl9-work` |
| device.non-tty-guidance | PASS | `opencode < /dev/null` and `opencode mini < /dev/null` → rc=1, identical clean guidance (TTY required; OpenTUI needs Node >= 26.4 + `node:ffi`; use line REPL or headless commands; docs path), no stack trace |
| device.version/help/paths/config/models/auth/session | PASS | all rc=0 (headless matrix) |
| device.agent-turn headless (mock provider) | PASS | `opencode run --standalone` PASS on attempt 1: `E2E_OK`, marker written, mock saw models + 3 chat completions (last `toolResult=true`) |
| device.remove/reinstall | PASS | `dpkg remove` (user data kept) + reinstall + post-reinstall `--version` PASS |
| device.overall | PASS | `FINAL_PACKAGED_ACCEPTANCE_RESULT=PASS` |

### Completed device run — 2026-11-01 (UTC) — iPhone SE 2 / iOS 16.1.1 — v2.2.5-ios.3 (previous release)

| Field | Value |
| --- | --- |
| Package file | `OpenCode-iOS-rootless.deb` |
| Package SHA-256 | `8a625f75a1f1fa3909d5128491c781a6559fff6d8d6894b9156e90e8d0d880dc` (52,964,804 bytes) |
| Package variant / runtime | `node22` / v6 mprotect W^X; runtime node sha256 `cf707ebe…`; CLI `opencode.mjs` sha256 `484b2c1c…`; launcher sha256 `86f68f21…` with flags `--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings --max-old-space-size=1536` |
| Package / verification runs | package `41279438605`; test-port `41280083940`; CLI `41278475579`; runtime `41273024931` |
| Device identity | iPhone SE 2 (iPhone12,8), iOS 16.1.1 (20B101), Dopamine rootless, user `mobile` |
| Result | **FINAL_PACKAGED_ACCEPTANCE PASS=14 FAIL=0** + packaged PTY TUI-guidance PASS |

| Test | Status | Evidence / output snippet |
| --- | --- | --- |
| device.install (dpkg) | PASS | `Status: install ok installed`, Version 2.2.5-1, Architecture iphoneos-arm64 |
| device.identity | PASS | runtime node `cf707ebe…`, CLI `484b2c1c…`, launcher `86f68f21…` confirmed inside installed package |
| device.pty-tui (bare `opencode`) | PASS (expected-unsupported) | rc=1, prints only the TUI-unavailable guidance block (`Interactive TUI is not available on this iOS build…`, headless hints, docs path); **no stack trace, no “Starting background server…”, no leftover background service** (ps checked) |
| device.pty-mini (`opencode mini`) | PASS (expected-unsupported) | identical guidance, rc=1, same cleanliness |
| device.version | PASS | `opencode --version` → `opencode2-node v2.2.5` |
| device.help | PASS | full help; `Intl.Segmenter` works with full ICU |
| device.paths/config/models/auth/session | PASS | `debug paths`, `debug config`, `models`, `auth list`, `session list` all rc=0 |
| device.agent-turn (mock provider) | PASS | `opencode run --standalone` exit 0 on attempt 2 (attempt 1 hit documented mock transport flake); mock saw `GET /api/v1/models` + 3×`POST /chat/completions` (last `toolResult=true`) |
| device.shell-tool marker | PASS | `/var/mobile/ocdev-e2e.txt`: `opencode-ios-e2e-ok` / `mobile` / `git version 2.39.1` / `/var/mobile/accept-work` |
| device.remove / reinstall | PASS | `dpkg remove` keeps user data; reinstall then `--version` OK |
| device.overall | PASS | `FINAL_PACKAGED_ACCEPTANCE_RESULT=PASS` |

### Completed device run — 2026-11-01 (UTC) — iPhone SE 2 / iOS 16.1.1 — v2.2.5-ios.2 (previous release, kept for traceability)

| Field | Value |
| --- | --- |
| Package SHA-256 | `2f96fc183416ef336fc9855b9dedc51e6baaf89cda996b0147b31444dbef446b` (52,968,920 bytes) |
| Package variant / runtime | `node22` / v6 mprotect W^X; runtime node sha256 `cf707ebe…`; CLI `opencode.mjs` sha256 `2e916ffa…`; launcher sha256 `86f68f21…` with the same flags |
| Package / verification runs | package `41274221353`; verification `41274690207`, `41274713331` |
| Result | **FINAL_PACKAGED_ACCEPTANCE PASS=14 FAIL=0** (`/var/jb/usr/bin/opencode` via installed launcher); superseded by `.3` (TUI guidance) |

| Test | Status | Evidence / output snippet |
| --- | --- | --- |
| device.install (dpkg) | PASS | `Status: install ok installed`, Version 2.2.5-1, Architecture iphoneos-arm64 |
| device.identity | PASS | runtime node `cf707ebe…`, CLI `2e916ffa…`, launcher `86f68f21…` verified inside installed package |
| device.version | PASS | `opencode --version` → `opencode2-node v2.2.5` |
| device.help | PASS | full help; `Intl.Segmenter` works with full ICU |
| device.paths | PASS | `debug paths` → `~/.config/opencode`, `~/.local/share/opencode`, … |
| device.models | PASS | catalog + configured mock-provider models |
| device.auth | PASS | `auth list` → “No authenticated integrations” |
| device.session-list | PASS | `ses_… Untitled session 11/1/2026, 12:59:10 PM` (native `node:sqlite` with `-wal`/`-shm`) |
| device.config | PASS | `debug config` → config document discovered |
| device.agent-turn (mock provider) | PASS | `opencode run --standalone` rc=0, stdout `E2E_OK: shell tool executed on iPhone; file written…`; mock saw `GET /api/v1/models` + 3×`POST /chat/completions` (last `toolResult=true`) |
| device.shell-tool marker | PASS | `/var/mobile/ocdev-e2e.txt`: `opencode-ios-e2e-ok` / `mobile` / `git version 2.39.1` / `/var/mobile/accept-work` |
| device.remove | PASS | `dpkg remove` → runtime removed, user data kept |
| device.reinstall | PASS | `dpkg reinstall` then `--version` OK |
| device.launcher-flags | PASS | launcher contains `--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings --max-old-space-size=1536` |
| device.overall | PASS | `FINAL_PACKAGED_ACCEPTANCE_RESULT=PASS` |

Observed device limitations are recorded in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)
(single-threaded V8; full-screen TUI unavailable because OpenTUI needs Node >= 26.4
+ `node:ffi` — iOS `opencode` in a TTY uses a line-based REPL added in patch
`0012`, `opencode mini` aliases it, non-TTY gets guidance + exit 1; local-mock
transport flake ~1/3 first attempts with retry; 2 GB memory pressure / stale
`serve --service` child holding port 49374; no real external AI provider
exercised on-device).

### Interim device evidence (preliminary, superseded by the packaged run)

Recorded by the project maintainer on the target iPhone on 2026-10-31 while
preparing the port. These probes used a locally re-signed runtime/bootstrapping
commands, **not** the packaged `.deb`; they are kept for the record and are
superseded by the packaged acceptance above.

| Probe | Result |
| --- | --- |
| Entitlement pair `platform-application=true` + `com.apple.private.security.no-sandbox=true`, ldid re-sign, run node | **PASS** — node starts, prints version, exit 0 |
| Old 4-key set (allow-jit, allow-unsigned-executable-memory, disable-library-validation, dynamic-codesigning) | **FAIL** — SIGKILL, exit 137 |
| `platform-application` alone, and with `dynamic-codesigning` / allow-jit variants | **FAIL** — SIGKILL, exit 137 |
| Community 9-key set | Boots, but the two-key set above is the minimal working set |
| Rootless shells | `/var/jb/bin/sh` and `/var/jb/usr/bin/sh` -> `/var/jb/usr/bin/dash`; `/bin/sh` absent |
| Rootless `dpkg` + `#!/bin/sh` maintainer script | **PASS** — test deb installed (`POSTINST_SHELL_RAN`), `dpkg -r` clean (`#!/bin/sh` handled by patched rootless dpkg even without `/bin/sh`) |
| Kernel-exec shebang of a direct `/var/jb/usr/bin/*` helper | `/bin/sh` would ENOENT → launchers use `#!/var/jb/bin/sh` (also used by installed rootless packages) |
| Device network/TLS | HTTPS request returned 200, `curl` works; device time/date correct |
| `node --jitless` on device | accepted (jitless runtime; not needed for the final runtime) |
| `git` | not installed by default; Procursus apt provides git 2.39.1 (`sudo apt-get install -y git`) |
| Intermediate package (WASM-disabled runtime) on device | **FAIL:** every CLI command dies with `ReferenceError: WebAssembly is not defined` — Node 22.9's built-in fetch/undici needs WASM (wasm llhttp). This is why the intermediate package is marked **not shippable**. |
| JIT+WASM with the 2-key entitlements | **PASS (non-generated-code paths):** the maintainer re-signed a JIT-enabled Node binary with `platform-application` + `com.apple.private.security.no-sandbox`; on device `WebAssembly` is an object, a wasm module compiles, and a JIT loop runs. The v3 runtime (JIT+WASM+full-ICU) was then built and packaged (runtime run 41193603642, package run 41202900005). |
| v3 JIT runtime on device (V8 generated-code execution) | **FAIL:** every entitlement set tested (2-key, +dynamic-codesigning, +allow-jit, 6-key, 9-key) still trapped with **SIGBUS** when executing V8-generated code. The trap is a V8 iOS memory-permission bug (no-op `pthread_jit_write_protect`/`MAP_JIT` code path), not signing. runtime-engineer's patch `0004-ios-jit-write-protect.patch` adds the iOS V8 W^X path; v4 runtime rebuild with a tentative 4-key JIT entitlement set (`platform-application`, `no-sandbox`, `dynamic-codesigning`, `allow-unsigned-executable-memory`) is in progress. The v3-based package (run `41202900005`) is therefore **superseded, not shippable**. |

Native runtime binary probes on the real iPhone (same date, ldid re-signed with the
2-key entitlement set — **runtime only, not the packaged CLI**):

| Probe | Result |
| --- | --- |
| `node --version` | `v22.9.0` (runs, exit 0) |
| `process.platform` / `process.arch` | `ios` / `arm64` |
| Embedded versions | V8 12.4.254.21-node.19, uv 1.48.0, OpenSSL 3.0.13, SQLite 3.46.1 |
| `node:sqlite` (`--experimental-sqlite`) create/insert/select | PASS |
| Filesystem write/read | PASS |
| TLS/network (`api.github.com`) | PASS |
| `child_process` spawn of `/var/jb/bin/sh -c` (uid 501) | PASS |
| Spawning `node` as a child process | PASS |
| WebAssembly | `undefined` on the intermediate JIT-less runtime (WebAssembly was disabled) |
| Dylib linkage on device | only `/usr/lib/libSystem.B.dylib` + `/usr/lib/libc++.1.dylib` |
| Re-sign with shipped 2-key entitlements (`ldid -S`) | PASS; old 4-key signature SIGKILLed (137) |
| v4 runtime built (patch 0004 W^X, tentative 4-key JIT set) | CI-green (run `41207449703`): node sha256 `48eecd59…`, `source.patches` includes `0004-ios-jit-write-protect.patch`, manifest marks entitlements tentative / device-unverified; packaged as run `41218342323`. |
| **v4 runtime on device** | **FAIL:** the package installs but the JIT runtime crashes while reserving V8 code range — `EXC_BREAKPOINT`/SIGTRAP → `FatalOOM` in `CodeRange::InitReservation` because iOS denies `mprotect` to RWX (MAP_JIT memory model). Resolution in progress: v5 runtime (plain-mprotect W^X, patch `0005-no-map-jit-on-ios.patch`, 2-key entitlements) and/or optional `libjitshim.dylib` interposer injected via `DYLD_INSERT_LIBRARIES`. |
| iOS JIT memory-permission probe | Separate diagnostic workflow (`iOS JIT memory probe dylib`) builds `libjitprobe.dylib` (artifact `ios-jit-probe`, never shipped) to report which executable-memory primitives the jailbreak permits; used to choose the v5/shim approach. |
| **v5 runtime / jit-shim candidate** | **Superseded by v6** — v5 plain-RWX mprotect trapped with SIGBUS (kernel drops execute); the mprotect RW⇄RX model of v6 is device-verified. Optional `ios-jit-shim` is consumed by packaging when published but was not needed for the released package. |
| ICU-enabled iOS Node reference | the community reference Node 18.20.4 binary on the same iPhone reports `process.versions.icu = 74.2` and `typeof Intl === "object"`, confirming an ICU-enabled iOS Node build works on this exact device |
| **Node 22 v6 runtime on device (mprotect W^X)** | **PASS with `--single-threaded`:** JIT loop rc=0, WebAssembly compile+instantiate, HTTPS fetch 200, ICU 75/`\p{L}`, `Intl.Segmenter`; node sha256 `cf707ebe…` (run `41265520491`). Without `--single-threaded`: SIGBUS (signal 10) on JIT-heavy code — V8 background threads race the process-wide mprotect toggle. |
| **Node 22 v6 CLI on device** | **PASS (partial):** `--version`, `--help` (full ICU fixes `Intl.Segmenter`) and `debug paths` rc=0 with `--single-threaded`. Commands spawning a server child SIGBUS until CLI patch `0010` adds `--single-threaded` to the child-spawn whitelist. |
| **Node 18 CLI bundle on community Node 18.20.4 runtime** (maintainer probe) | **PASS (preliminary):** `--version` → `opencode2-node v2.2.5` (rc=0); `debug paths`, `debug config`, `models`, `session list` all rc=0; the sql.js sqlite shim created/persisted the database. This is **not** the packaged runtime: it validates the Node 18 CLI bundle and the V8 10.2 device memory model. |
| **Node 18 `--help` on the community runtime** | **FAIL — environment-specific:** the community runtime is small-ICU, so `--help` crashes in `JSSegmenter::Create`. The shipped runtime is our own full-ICU Node 18 build (`build-runtime-node18.yml`), which is why the packaging gate requires full-ICU and `Intl.Segmenter`. |
| **Node 18 `run --standalone` child server** | **FAIL (preliminary):** the standalone command could not start its child server; CLI patch `0009` addresses it; device retest with the final package pending. |
| **CLI bundle, no-ICU runtime** | **FAIL:** `Intl` was undefined and V8 rejected `/[\p{Mark}\p{Control}...]/gu` with `SyntaxError: Invalid regular expression`. The packaging CI gate rejects `--with-intl=none` artifacts. |
| **Interactive line REPL on device (patch `0013` CLI, v6 runtime + mock provider; and packaged `v2.2.5-ios.5` with patch `0014`)** | **DEVICE-VERIFIED (packaged `.5`):** REPL intro/prompt; turn 1 first attempt (300 ms warm-up); a following turn recovered via the 3-attempt retry (`Retrying turn with a fresh server connection…`) then `E2E_OK`; `/new` + another turn first attempt; `/exit` rc=0; shell tool wrote `/var/mobile/ocdev-e2e.txt`; non-TTY `opencode`/`opencode mini` give clean guidance + rc=1. An earlier patch-`0013` dev-CLI PTY run (4 prompts, 13 mock chat requests, 4 with `toolResult=true`, `repl5-work` marker) is kept in the record. |
| **Interactive TUI on device** | **Experimental Node 26 test.5 with external runtime: DEVICE-VERIFIED real OpenTUI TUI**, 3 tool/reply turns and `/exit` rc=0; earlier embedded test.4 results are retained above. **Stable Node 22:** DEVICE-VERIFIED line REPL in `v2.2.5-ios.5`; it lacks `node:ffi` and cannot load the native full-screen renderer. Both variants return non-TTY guidance/1. |
| **CLI bundle, full-ICU but WASM-disabled runtime** | **FAIL:** parse succeeds, but `ReferenceError: WebAssembly is not defined` from Node's fetch/undici setup. The packaging CI gate now requires WebAssembly and JIT enabled (and rejects `--v8-options=--jitless`). |
| **v3 JIT runtime (no W^X patch)** | **FAIL on device:** SIGBUS when executing V8-generated code with every entitlement set; packaging gate now requires patch `0004-ios-jit-write-protect.patch` for JIT-enabled runtimes. |

### Recording template (copy per device run)

Use this template for future device runs (other devices/iOS versions or new
artifacts). The completed run for the released artifact is recorded above.

```markdown
### Device run N — YYYY-MM-DD (UTC) — <device> — package <version>

| Field | Value |
| --- | --- |
| Package file | `OpenCode-iOS-rootless.deb` |
| Package SHA-256 | `<sha256>` |
| Package variant | `node18` (expected) / `node22` — from `package-report.json` |
| Runtime version | `<output of runtime/node -p process.versions.node>` |
| Package workflow run | <package-rootless run URL> |
| Runtime artifact run | <build-runtime / build-runtime-node18 run URL> |
| CLI artifact run | <build-opencode run URL> |
| Packaging commit | `<git sha>` |
| Operator | <role/name> (credentials kept local, never shared) |
| Device identity | iPhone SE 2 (iPhone12,8), iOS 16.1.1 (20B101), Dopamine rootless, user `mobile` |

| Test | Status | Evidence / output snippet |
| --- | --- | --- |
| device.install | PENDING | |
| device.variant | PENDING | |
| device.single-threaded | PENDING | |
| device.version | PENDING | |
| device.help | PENDING | |
| device.paths | PENDING | |
| device.models | PENDING | |
| device.sqlite | PENDING | |
| device.auth | PENDING | |
| device.no-network | PENDING | |
| device.jitless | PENDING | |
| device.shell | PENDING | |
| device.git | PENDING | |
| device.wasm | PENDING | |
| device.tui | PENDING | |
| device.agent-turn | PENDING | |
| device.standalone | PENDING | |
| device.inspector | PENDING | |
| device.uninstall | PENDING | |
| device.ldid | PENDING | |

Observed limitations / deviations:
- <e.g. TUI rendering degraded in NewTerm, PTY fallback confirmed>

Open issues:
- <link to issue, if any>
```

Only mark a row PASS/FAIL from the exact captured command output, and update the
**Status summary** table at the top of this document in the same commit as the
evidence. Do not include API keys, tokens, account names or personal project data.

## Device runbook (exact commands)

On the iPhone:

```sh
cd ~/Documents                       # HOME=/var/jb/var/mobile
sha256sum -c SHA256SUMS
sudo dpkg -i OpenCode-iOS-rootless.deb
# variant/runtime identity + mandatory launcher flag
dpkg -s opencode | head -n 12
/var/jb/usr/lib/opencode/runtime/node -p process.versions.node
grep -n -- '--single-threaded' /var/jb/usr/bin/opencode   # must appear (node22 variant)
# JIT-heavy + WASM + fetch sanity with the same flags the launcher uses
/var/jb/usr/lib/opencode/runtime/node --single-threaded -e 'let s=0; for (let i=0;i<3e6;i++) s+=i%7; console.log("jit",s)'
/var/jb/usr/lib/opencode/runtime/node --single-threaded -e 'new WebAssembly.Module(Buffer.from("0061736d01000000","hex")); console.log("wasm-ok")'
opencode --version; echo "version_exit=$?"
opencode --help;    echo "help_exit=$?"
sh /var/jb/usr/share/doc/opencode/device-smoke.sh
sh /var/jb/bin/sh -c 'echo shell-ok'
command -v git && git --version
/var/jb/usr/lib/opencode/runtime/node -e "console.log(typeof WebAssembly, process.config.variables.v8_enable_webassembly, typeof fetch, typeof Intl, typeof Intl.Segmenter)"
opencode models || true
opencode debug paths || true
opencode session list; echo "session_list_exit=$?"   # sqlite persistence
ls -l "$HOME/.local/share/opencode"/*.db 2>/dev/null || true
opencode auth list || true
```

Record and report: device model, iOS version, jailbreak, `.deb` SHA-256,
**variant and runtime version**, full command outputs, and PASS/FAIL for each row
of the table above. Open an issue at
<https://github.com/Justintunsday/opencode-ios/issues> — **never include API keys
or tokens**.

## How to re-run the CI verification locally

```sh
# after downloading the OpenCode-iOS-rootless artifact contents:
sha256sum -c SHA256SUMS
bash scripts/validate-port.sh --deb OpenCode-iOS-rootless.deb --mode verify \
  --artifact-dir . --package-report package-report.json --out-dir verification
```

The variant is auto-detected from `package-report.json`/`sources.inputs`/the
runtime manifest (`--variant auto`); pass `--variant node18` or `node22` to force
it. The script needs `python3`; `otool`/`xcrun` for native checks (macOS) and
network access for the pinned host Node.js download (22.9.0 for node22,
18.20.4 for node18). Use `--skip-native-audit --skip-smoke` only for local
dry-runs; CI never skips these.

## Honesty guarantees

- Green CI ≠ device-verified. The CI report generator emits the literal strings
  `UNVERIFIED ON DEVICE` and `DEVICE TESTS: NOT PERFORMED (requires real iPhone)`
  in every CI report, because hosted runners cannot execute iOS binaries; there is
  no code path that marks a CI run as a device test. Device verification exists
  only in [`DEVICE_TEST_RESULTS.md`](DEVICE_TEST_RESULTS.md), produced by the
  maintainer on the target device for a specifically identified `.deb` SHA-256.
- The released `.debs` `v2.2.5-ios.5`
  (`b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073`),
  `v2.2.5-ios.3` (`8a625f75…`) and `v2.2.5-ios.2` (`2f96fc18…`) are
  device-verified (packaged acceptance PASS=14/FAIL=0, 2026-11-01; `.5` also
  passed the packaged REPL PTY acceptance with a retried turn, `/new`, `/exit`,
  shell-tool marker, and non-TTY guidance rc=1). The candidate `v2.2.5-ios.4`
  (`299ee574…`) is superseded/NOT device-verified. Later documentation commits do
  **not** change those artifacts' identities; re-running the package workflow on a
  docs-only commit produces a different SHA-256 and is pipeline evidence only,
  not a device-tested release artifact.
- Preliminary device probes (entitlement pair, rootless shells, dpkg script
  handling, runtime capability requirements, Node 18 community-runtime probes)
  are recorded under *Interim device evidence* and are superseded by the packaged
  acceptance run.
- The first CI-green package run is explicitly labelled **INTERMEDIATE, DO NOT
  SHIP** above: it used a WebAssembly-disabled runtime and fails on device. Only
  a package whose `package-report.json` passes the variant-aware runtime gates
  (full-ICU + WebAssembly + JIT enabled, 2-key entitlements, variant consistency,
  launcher flags) is a shipping candidate.
- Variant evidence is kept separate: the node22 v6 package is released and
  device-verified; the Node 18 fallback's CLI ran on a community Node 18 runtime
  and remains preliminary until its own runtime/package acceptance run is
  recorded.
- If an upstream artifact is missing, the packaging/validation workflows fail
  with an explicit message and never fabricate inputs.
- Stock/non-iOS CLI artifacts (desktop Mach-O assets, Node-26-only smoke policy,
  stock-bundle notes) and packages with non-conforming entitlements are rejected
  as hard failures by the validation gates.
- Skips are reported as `SKIP` with a reason (for example an optional
  `ios-ripgrep` artifact that was not published); they are never counted as passes.
