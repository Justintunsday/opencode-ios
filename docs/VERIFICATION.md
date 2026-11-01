# Verification matrix — OpenCode iOS (rootless)

This document distinguishes **what CI actually proves** from what is
**unverified** and must be executed on a real device. No CI run and no document in
this repository claims on-device success.

## Status summary

| Evidence class | Environment | Status |
| --- | --- | --- |
| Static package validation (Mach-O, dylibs, paths, permissions, metadata, manifests, entitlements policy, variant consistency) | GitHub Actions `macos-15` runner | **CI-verified** when the workflows are green |
| Runtime capability gating (full-ICU + WebAssembly + JIT required for both variants; `Intl.Segmenter` data; Node 22 additionally requires an iOS V8 W^X patch; Node 18 uses the device-proven V8 10.2 memory model and must not require the Node-22-only W^X patches) | GitHub Actions `macos-15` runner | **CI-verified** |
| Host-runtime JS smoke | GitHub Actions `macos-15` runner: host Node.js **22.9.0** for node22 and host Node.js **18.20.4** for node18 (nodejs.org, checksum-pinned) | **CI-verified** when the workflows are green |
| Native iPhoneOS runtime compile | GitHub Actions `macos-15` runner + iPhoneOS SDK: `build-runtime.yml` (node22) / `build-runtime-node18.yml` (node18) | **CI-verified** |
| Rootless runtime bootstrap facts (entitlement pair, launcher shebang, dpkg `#!/bin/sh` handling, JIT/WASM/ICU requirements) | Real target iPhone, maintainer-executed probes | **Partially device-verified (preliminary)** — see *Interim device evidence* below |
| Native Node 18 runtime execution with the packaged CLI bundle | Real target iPhone, maintainer-executed probe on a **device-proven community Node 18.20.4 runtime** (not yet the CI-built full-ICU runtime) | **CLI commands device-verified (preliminary)**; the shipped runtime still needs its acceptance run |
| Node 22 native runtime execution (JIT code paths) | Real target iPhone | **device-incompatible so far** (`v4`: SIGTRAP/FatalOOM at V8 code-range reservation; `v5`/`v6` mprotect approaches still in CI/device investigation) |
| Actual packaged CLI execution on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless | Real device | **UNVERIFIED ON DEVICE** — requires the user runbook below |

> **UNVERIFIED ON DEVICE — requires real iPhone SE 2 (iOS 16.1.1, Dopamine rootless).**
> Hosted GitHub Actions macOS runners cannot execute iOS arm64 binaries. Any green
> check below is runner-only evidence. Preliminary probes on the real device
> (entitlement pair, rootless shells, dpkg script handling, runtime capability
> requirements, and the Node 18 CLI bundle on a community runtime) are recorded
> separately and do **not** verify the packaged CLI with its own runtime.

### Runtime variants and current candidates

Two runtime variants are packaged from the same launcher/layout; the `.deb` ships
exactly one and `package-report.json` records which (`variant` / `runtime_kind`).

| Variant | Runtime | Status |
| --- | --- | --- |
| **`node18`** (primary) | Node.js **18.20.4** iPhoneOS arm64, V8 10.2 memory model, full-ICU, bundled sql.js sqlite shim | **Under final CI packaging + device acceptance.** The Node 18 CLI bundle already runs on the target iPhone with a community Node 18.20.4 runtime (`--version`, `debug paths`, `debug config`, `models`, `session list` rc=0; sql.js sqlite database created). Our own full-ICU Node 18 runtime is built by `build-runtime-node18.yml` and replaces that reference runtime (the community one is small-ICU: `--help` crashes in `Intl.Segmenter`). |
| **`node22`** (experimental) | Node.js **22.9.0** iPhoneOS arm64, full-ICU, built-in sqlite | **Not device-runnable yet.** v4 (MAP_JIT + patch 0004) crashed at V8 code-range reservation; v5/v6 mprotect-based W^X variants are in CI + device investigation. Not shippable. |

Node 18 CLI device evidence (maintainer, community Node 18.20.4 iPhoneOS runtime,
before the CI-built full-ICU runtime existed):

- `opencode2-node --version` → `opencode2-node v2.2.5` (rc=0)
- `debug paths`, `debug config`, `models`, `session list` → rc=0 (sql.js sqlite
  shim works; database file created)
- `--help` → crashes in `Intl.Segmenter` **only because that reference runtime is
  small-ICU**; the shipped runtime is full-ICU, so this is expected to pass on the
  packaged runtime and is part of the acceptance run.
- One CLI bug observed (standalone server child start) is addressed by CLI patch
  `0009`; device retest pending with the final package.

### Latest CI-verified package

The node18-variant package is the delivery candidate. Fill/refresh this table from
the artifact of the most recent green `package-rootless.yml` run **with
`variant=node18`** (the pinned run identifies the device-test artifact):

| Item | Value |
| --- | --- |
| Package workflow run (node18) | **PENDING** — dispatch `package-rootless.yml` with `variant=node18` after the full-ICU Node 18 runtime build is green |
| Package artifact | `OpenCode-iOS-rootless` (artifact id recorded from the run) |
| `.deb` SHA-256 | recorded in the artifact's `SHA256SUMS`; copy the exact value here when the run is green |
| Version / arch | `2.2.5-1` / `iphoneos-arm64` |
| Runtime artifact run | latest successful `build-runtime-node18.yml` run with `ios-node18-runtime` |
| Runtime node | Node.js 18.20.4 iPhoneOS arm64, full-ICU + WebAssembly + JIT, 2-key entitlements, dylibs only `libSystem`/`libc++` |
| CLI artifact | latest successful `build-opencode.yml` run with `opencode-cli-node18-ios` (variant `node18-fallback`, patch series `patches/opencode`, sql.js shim declared) |
| Package validation | to be filled from the run (`ci_status`, PASS/FAIL/SKIP counts) |
| Verification workflow | to be filled: `test-port.yml` on the pinned package run |
| Device status | **UNVERIFIED ON DEVICE** — pending the maintainer's acceptance run with this exact `.deb` |

### Node 22 pipeline history (all superseded, not shippable)

| Build | Outcome |
| --- | --- |
| v1 intermediate (run `41185611403`, `.deb` sha `13a0483d...`) | WASM-disabled runtime: every CLI command failed with `ReferenceError: WebAssembly is not defined`. |
| v3 (run `41202900005`, `.deb` sha `cf5db02a...`) | JIT+WASM, no iOS V8 W^X path: SIGBUS on V8-generated code. |
| v4 (package run `41218342323`, `.deb` sha `1d643c3b8b3e4238bb1e692fadce9fcb72f74ea1b7b61621229cf502571b6dc4`) | CI-green (45/0/0 package, 46/0/0 verification); on device SIGTRAP → `FatalOOM` in `CodeRange::InitReservation` because iOS denies `mprotect` RWX. |
| v5/v6 | mprotect-based W^X repackaging in progress (`0005`/`0006` patch work); no device-runnable Node 22 artifact yet. |

**Artifact identity across docs commits.** The packaged documentation is part of
the `.deb`, so CI rebuilds triggered by documentation-only commits produce
byte-different `.debs` (different SHA-256) even though the runtime, CLI bundle and
launcher code are identical. Pinned runs above identify specific artifacts; later
green runs on docs commits are pipeline evidence only.

**Honesty note.** The node18 CLI device evidence above was produced with a
community Node 18 runtime, not the CI-built runtime that ships in the `.deb`.
Until the maintainer runs the packaged acceptance procedure, the package remains
`UNVERIFIED ON DEVICE`.

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

## Device tests — UNVERIFIED ON DEVICE

The following require a real iPhone SE 2 (iOS 16.1.1, Dopamine rootless). Run the
commands from a NewTerm 3 shell or SSH. Full install instructions:
[`INSTALL.md`](INSTALL.md).

> **UNVERIFIED ON DEVICE — requires real iPhone SE 2 (iOS 16.1.1, Dopamine rootless).**
> None of these has been executed by CI. They are the acceptance runbook.

| # | Test | Command | Pass criterion |
| --- | --- | --- | --- |
| 1 | Install | `sudo dpkg -i ~/Documents/OpenCode-iOS-rootless.deb` | dpkg status `install ok installed`, no errors |
| 2 | Runtime variant | `/var/jb/usr/lib/opencode/runtime/node -p process.versions.node`; `dpkg -s opencode` | prints `18.20.4` (expected for the node18 candidate) or `22.9.0`; matches `package-report.json` → `variant`; control description states the runtime |
| 3 | CLI starts | `opencode --version` | exit 0, upstream version (2.2.5) printed |
| 4 | Help (full-ICU/Segmenter) | `opencode --help` | exit 0, usage/commands printed; on node18 this exercises `Intl.Segmenter` (fails only on small-ICU runtimes) |
| 5 | Runtime capabilities | `/var/jb/usr/lib/opencode/runtime/node -e "console.log(typeof WebAssembly, process.config.variables.v8_enable_webassembly, typeof fetch, typeof Intl, typeof Intl.Segmenter)"` | `object 1 function object function`; wasm module compiles; `opencode --version` works (no `ReferenceError: WebAssembly is not defined`) |
| 6 | Paths/models (offline) | `opencode debug paths`, `opencode models` | config/data under `/var/jb/var/mobile/...`; model list prints (version-dependent, optional) |
| 7 | sqlite persistence | `opencode session list`; check the database file under `~/.local/share/opencode` | exit 0 and a sqlite file exists; node18 uses the bundled sql.js shim (whole-file, no WAL) |
| 8 | Auth | `opencode auth list`, `opencode auth login` | login completes; credentials only in user home |
| 9 | Offline scripted smoke | `sh /var/jb/usr/share/doc/opencode/device-smoke.sh` | final line `DEVICE SMOKE TEST: PASS` |
| 10 | Liveness/signature | `sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml /var/jb/usr/lib/opencode/runtime/node` then `opencode --version` | re-signed runtime still starts (repair path works; shipped entitlements are the verified minimal pair) |
| 11 | Shell-tool fallback | `sh /var/jb/bin/sh -c 'echo shell-ok'` and (after auth) a CLI shell-tool call | rootless dash runs; CLI-spawned shells resolve through the launcher's `PATH` prepend |
| 12 | git tooling (optional) | `sudo apt-get install -y git`; `git --version`; a git tool call through the CLI | git installed/works; without it the CLI error is actionable |
| 13 | TUI (degraded PTY) | `cd ~/Documents && opencode` | TUI starts; shell tool panes use fallback (see limitations) |
| 14 | Agent turn + standalone fix (needs network+auth) | `opencode run "summarise this repository"`; `opencode run --standalone ...` | request completes; the patch-0009 standalone child-server start works |
| 15 | Inspector/CPU profiling | `opencode --inspect ...` (documented stub) | fails gracefully with the documented stub message, not a crash (node18 inspector is stubbed by patch 0008) |
| 16 | Uninstall | `sudo dpkg -r opencode` (then `-P`) | package files gone; `~/.config/opencode` and sessions preserved |

Optional after test 12: confirm a local file edit and a `git` operation through
the agent in a throwaway repository.

## Device verification results

Status: **PENDING for the packaged CLI — no full package device run has been
recorded yet.** The device tests above therefore remain `UNVERIFIED ON DEVICE`.
Preliminary bootstrap probes performed by the maintainer directly on the target
iPhone (not via this package) are recorded under *Interim device evidence* below;
they must not be read as package verification.

Device results are **user/owner-reported**, not CI-produced. CI reports
(`port-verification`, `package-report.json`) stay runner-only evidence and must
never be presented as device proof.

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

### Interim device evidence (preliminary, not package verification)

Recorded by the project maintainer on the target iPhone on 2026-10-31 while
preparing the port. These probes used a locally re-signed runtime/bootstrapping
commands, **not** the packaged `.deb`, so the status summary above stays
`UNVERIFIED ON DEVICE` for the package.

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
| **v5 runtime / jit-shim candidate** | **PENDING** — v5 runtime run in progress; optional `ios-jit-shim` is consumed by packaging when published. Device PASS only after the maintainer's raw outputs. |
| ICU-enabled iOS Node reference | the community reference Node 18.20.4 binary on the same iPhone reports `process.versions.icu = 74.2` and `typeof Intl === "object"`, confirming an ICU-enabled iOS Node build works on this exact device |
| **Node 18 CLI bundle on community Node 18.20.4 runtime** (maintainer probe) | **PASS (preliminary):** `--version` → `opencode2-node v2.2.5` (rc=0); `debug paths`, `debug config`, `models`, `session list` all rc=0; the sql.js sqlite shim created/persisted the database. This is **not** the packaged runtime: it validates the Node 18 CLI bundle and the V8 10.2 device memory model. |
| **Node 18 `--help` on the community runtime** | **FAIL — environment-specific:** the community runtime is small-ICU, so `--help` crashes in `JSSegmenter::Create`. The shipped runtime is our own full-ICU Node 18 build (`build-runtime-node18.yml`), which is why the packaging gate requires full-ICU and `Intl.Segmenter`. |
| **Node 18 `run --standalone` child server** | **FAIL (preliminary):** the standalone command could not start its child server; CLI patch `0009` addresses it; device retest with the final package pending. |
| **CLI bundle, no-ICU runtime** | **FAIL:** `Intl` was undefined and V8 rejected `/[\p{Mark}\p{Control}...]/gu` with `SyntaxError: Invalid regular expression`. The packaging CI gate rejects `--with-intl=none` artifacts. |
| **CLI bundle, full-ICU but WASM-disabled runtime** | **FAIL:** parse succeeds, but `ReferenceError: WebAssembly is not defined` from Node's fetch/undici setup. The packaging CI gate now requires WebAssembly and JIT enabled (and rejects `--v8-options=--jitless`). |
| **v3 JIT runtime (no W^X patch)** | **FAIL on device:** SIGBUS when executing V8-generated code with every entitlement set; packaging gate now requires patch `0004-ios-jit-write-protect.patch` for JIT-enabled runtimes. |

### Recording template (copy per device run)

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
# variant/runtime identity (node18 candidate expects 18.20.4)
dpkg -s opencode | head -n 12
/var/jb/usr/lib/opencode/runtime/node -p process.versions.node
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

- Green CI ≠ device-verified. The report generator emits the literal strings
  `UNVERIFIED ON DEVICE` and `DEVICE TESTS: NOT PERFORMED (requires real iPhone)`
  in every report; there is no code path that marks a device test as passing.
- Preliminary device probes (entitlement pair, rootless shells, dpkg script
  handling, runtime capability requirements) are recorded above as *Interim
  device evidence*; they are explicitly **not** package verification and do not
  change the status summary.
- The first CI-green package run is explicitly labelled **INTERMEDIATE, DO NOT
  SHIP** above: it used a WebAssembly-disabled runtime and fails on device. Only
  a package whose `package-report.json` passes the variant-aware runtime gates
  (full-ICU + WebAssembly + JIT enabled, 2-key entitlements, variant consistency)
  is a shipping candidate.
- Variant evidence is kept separate: Node 18 CLI device probes were performed with
  a community Node 18 runtime and are labelled preliminary; the node22 runtime is
  recorded as device-incompatible until a device-runnable Node 22 build exists.
  Neither is presented as verification of the packaged CLI.
- If an upstream artifact is missing, the packaging/validation workflows fail
  with an explicit message and never fabricate inputs.
- Stock/non-iOS CLI artifacts (desktop Mach-O assets, Node-26-only smoke policy,
  stock-bundle notes) and packages with non-conforming entitlements are rejected
  as hard failures by the validation gates.
- Skips are reported as `SKIP` with a reason (for example an optional
  `ios-ripgrep` artifact that was not published); they are never counted as passes.
