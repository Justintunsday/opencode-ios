# Known limitations — OpenCode iOS (rootless, v1)

This list is deliberately honest. Every item is either a **documented fallback**
implemented in the port or **unverified** on real hardware. "CI-green" does not
override any of it. Target device: iPhone SE 2, iOS 16.1.1, Dopamine rootless.

| # | Limitation | Impact | Status |
| --- | --- | --- | --- |
| 1 | **No native PTY for interactive terminal panes.** Upstream `@opencode/pty`/`node-pty` has no iPhoneOS build; shell tool calls use pipe-based `child_process` fallback and spawn the rootless dash (`/var/jb/bin/sh`) through the launcher's `PATH` prepend. | No interactive TTY allocation for tool-invoked shells; TUI terminal panes degrade or are unavailable. Headless `opencode run` is the reliable mode. | documented fallback |
| 2 | **TUI is not fully validated on device.** The interactive interface can start, but rendering, resizing, Ctrl-C handling and reconnect behaviour are unproven on the iPhone terminal. | Interactive experience may be degraded; use `--help`, `run`, and scripted commands. | unverified |
| 3 | **No native file watcher.** `@parcel/watcher` has no iPhoneOS build; watch-based features fall back to polling or are disabled. | Live reload/incremental watching may lag or not happen; re-run commands to observe changes. Large repositories are affected more. | documented fallback |
| 4 | **No `fff`/`ffi-rs` native modules.** Upstream ships an unavailable-proxy fallback for ffi; it is selected on iOS. Desktop native binaries are removed from the packaged assets (CI rejects stock bundles that still contain them). | Features requiring native FFI (and fff-backed search/UI helpers) are unavailable. Pure-JS and WASM paths can work because the final runtime enables WebAssembly, but wasm-backed optional components are not individually validated on device. | documented fallback |
| 5 | **Two runtime variants: Node 18.20.4 (primary) and Node 22.9.0 (experimental).** The `.deb` ships exactly one; the Node 18 variant is the device-proven fallback (V8 10.2 memory model), the Node 22 variant uses a newer V8 and is not yet device-runnable. Upstream OpenCode's Node build path normally targets an even newer Node version, so APIs added after the chosen line are missing (e.g. `module.registerHooks` on Node 18/22.9); the iOS prelude avoids them and the Vite bundle is patched. Node's built-in fetch/undici requires WebAssembly (wasm llhttp), so both runtimes are built with WASM+JIT enabled. Host smoke passes `--version`/`--help` on 22.9.0 (node22) and 18.20.4 (node18) after the iOS patch series; broader CLI commands are covered by the device runbook. | Variant-specific behaviour differences must be taken into account when triaging; `package-report.json` records `variant`/`runtime_kind`. | documented constraint |
| 6 | **JIT + WebAssembly are required; the iOS JIT memory model is the hard part.** Node's built-in fetch/undici needs WebAssembly (wasm llhttp). An intermediate JIT-less/WASM-disabled runtime made every CLI command fail with `ReferenceError: WebAssembly is not defined`. The **Node 18 variant uses the V8 10.2 memory model that is device-proven** on the target iPhone (the Node 18 CLI bundle ran JIT+WebAssembly there with the 2-key entitlements). The **Node 22 variant's JIT path is not device-runnable yet**: v3 trapped with SIGBUS on generated code, v4 crashed at V8 code-range reservation (`EXC_BREAKPOINT`/SIGTRAP → `FatalOOM` in `CodeRange::InitReservation`, iOS denies `mprotect` RWX), and v5/v6 mprotect-based W^X builds are still in CI/device investigation (patch `0005`/`0006`; optional `ios-jit-shim` interposer path exists but is unproven). `OPENCODE_IOS_JITLESS=1` remains a node22-only debug escape hatch but disables JIT/WASM and breaks fetch/network features. | The node18 variant is the shipping candidate; until its packaged acceptance run passes, JIT-dependent execution of the packaged CLI is **unverified**. Node 22 remains experimental and is not shippable. | node18: device-proven memory model (preliminary CLI evidence); node22: unverified / device-incompatible so far |
| 7 | **Entitlements are device-verified for the 2-key set.** The working minimal runtime entitlement set is exactly `platform-application` + `com.apple.private.security.no-sandbox` (device-verified; old 4-key allow-jit sets without those keys were SIGKILLed, exit 137). Both shipped variants use this 2-key set; the Node 22 v4 experiment used a tentative 4-key set but that build was device-incompatible for memory-model reasons, not signing. The loader can SIGKILL on an unresolved extra entitlement. | If the runtime is killed at startup, repair/re-sign with the shipped `runtime/entitlements.xml` only; do not add other keys randomly. | device-verified (2-key set) |
| 8 | **No GUI/desktop application.** CLI only. | No menu-bar app, no GUI editor, no native window; use NewTerm 3 or SSH. | documented constraint |
| 9 | **Jailbreak required; rootless only.** Only `iphoneos-arm64` + `/var/jb` prefix (Dopamine-style) is packaged and validated. | Rootful jailbreaks, other prefixes (`/var/jb` absent) and non-arm64 devices are unsupported. | documented constraint |
| 10 | **Only iPhone SE 2 / iOS 16.1.1 is targeted.** No testing on other models/iOS versions. | Behaviour on other devices is untested; minimum iOS stated by the runtime is ≤ 16.1.1 (build target iOS 15.0). | unverified |
| 11 | **Sessions/config/data live in the user home** (`HOME=/var/jb/var/mobile` on this device, e.g. `~/.config/opencode`, `~/.local/share/opencode`). | They are user data: preserved across `dpkg -r`/`dpkg -P`; cleared only if the user manually deletes them. Backup/restore is the user's responsibility. | documented behaviour |
| 12 | **Auto-update disabled.** The CLI is managed by dpkg, not a self-updater. | Upgrades go through new `.deb` artifacts/`dpkg -i`; no in-app network updater. | documented fallback |
| 13 | **Memory limits / jetsam.** iPhone SE 2 has 3 GB RAM; a large session can be killed by the OS before V8 GC settles. | Launcher caps V8 old space at 1536 MiB by default; override with `OPENCODE_IOS_MAX_OLD_SPACE_MB`. Very large repositories may still fail. | documented mitigation |
| 14 | **No background execution/daemon.** iOS does not allow a jailbreak CLI to stay resident like a server. | `opencode serve`-style long-running workflows are not validated for background/headless persistence; run in a foreground terminal/SSH session. | unverified |
| 15 | **TLS/CA and corporate proxy behaviour** relies on iOS system trust; custom proxies, client certificates and interception are untested. | Network/auth failures may occur in managed environments. Basic device HTTPS/TLS was verified (200 response, curl works) but proxies remain untested. | unverified |
| 16 | **Package is unsigned for Cydia/Sileo repo distribution** (no repo metadata, no package-signing key). | Install the `.deb` manually or via Filza/local Sileo; `dpkg` may warn about unauthenticated local installs. | documented limitation |
| 17 | **Device verification not performed by CI.** Hosted runners cannot execute iOS arm64 binaries. | The port is `UNVERIFIED ON DEVICE` until the user runs the device smoke test in `docs/VERIFICATION.md`; real device results are recorded in that document's **Device verification results** section when available. | unverified |
| 18 | **No `/bin/sh`, `/bin/bash` or `/bin/zsh` on rootless iOS.** Rootless shells live under `/var/jb`; the launcher and packaged helper scripts use `#!/var/jb/bin/sh`, while `DEBIAN/postinst`-style scripts keep `#!/bin/sh` (handled by patched rootless `dpkg`, device-verified). | Scripts must not hardcode `/bin/sh`; user-run helpers should be invoked as `sh /var/jb/...` or with the rootless shebang. | documented constraint |
| 19 | **`git` is not bundled or hard-required.** The package declares `Recommends: git`, not `Depends`. | Git tool features need `sudo apt-get install -y git` (Procursus apt, device-verified git 2.39.1). `dpkg -i` works without it. | documented behaviour |
| 20 | **ICU/Intl build requirement.** The Node runtime must be built with `--with-intl=full-icu` (small-icu trims Intl data and `Intl.Segmenter` misbehaves; the CLI uses it, and a community small-ICU Node 18 runtime crashed `opencode --help` in `JSSegmenter::Create` on the target device). An early build used `--with-intl=none`: `Intl` was undefined and V8 rejected the Unicode property escapes used by the CLI bundle (`SyntaxError: Invalid regular expression: /[\p{Mark}\p{Control}...]/gu`), so the CLI could not start on device. | Both shipped variants are built full-ICU; the packaging CI rejects runtime artifacts whose manifest declares `--with-intl=none` or that omit the full-ICU declaration. | documented constraint (device-verified requirement; satisfied by the shipped runtimes) |
| 21 | **Node 18 sqlite uses a bundled sql.js (WebAssembly) shim.** `node:sqlite` does not exist on Node 18, so the Node 18 CLI bundle maps it to `assets/node18-sqlite/sql-wasm.{js,wasm}`. | Persistence is whole-file (no WAL): the database is written out as a file, and a hard crash can lose recent writes (~≤250 ms of writes per the shim design). Large sessions may be slower and use more memory than native sqlite. Node 22 (experimental) uses native `node:sqlite`. Close/quit the CLI cleanly before copying or backing up the database. | documented fallback |
| 22 | **Inspector / CPU profiling is a stub on Node 18.** `node:inspector` is not available on the cross-built Node 18 runtime, so CLI patch `0008` replaces it with a stub that reports unavailability instead of crashing. | `--inspect`, CPU profiles and heap snapshots are unavailable/best-effort on the node18 variant; debugging must use logs. | documented fallback |
| 23 | **`run --standalone` child-server start needed a CLI patch.** The Node 18 device run found `opencode run --standalone` could not start its child server; CLI patch `0009` addresses the direct-spawn path. | Standalone mode must be re-tested on device with the final package; the plain `opencode run` path is unaffected. | fixed in CLI, device retest pending |
| 24 | **The node18 CLI device evidence was gathered with a community Node 18 runtime, not the packaged one.** `--version`, `debug paths`, `debug config`, `models`, `session list` returned rc=0 and sql.js sqlite worked; `--help` crashed only because that reference runtime is small-ICU. | The packaged acceptance run (own full-ICU Node 18 runtime) is still required; until then the package stays `UNVERIFIED ON DEVICE`. | preliminary device evidence |
| 25 | **`TMPDIR` may be unset in device sessions.** Some SSH/NewTerm sessions do not export it; the CLI/sql.js need a writable temp dir. | Both launchers provide a `TMPDIR` fallback (`/var/jb/tmp`, `/var/jb/var/tmp`, `/tmp`) when unset; `device-smoke.sh` checks and reports it. | documented mitigation |

## Notes

- Items marked **documented fallback** are implemented choices in the port (the
  CLI behaves as described above); items marked **unverified** require real
  hardware evidence and are not claimed to work.
- **Preliminary device probes** (entitlement pair, rootless shells, dpkg
  `#!/bin/sh` handling, device network/TLS) were executed by the maintainer
  directly on the target iPhone and are recorded in
  [`VERIFICATION.md`](VERIFICATION.md) → *Interim device evidence*. They are not
  package verification; the packaged CLI remains `UNVERIFIED ON DEVICE` until a
  full device run is recorded.
- CI **rejects** packages whose runtime entitlements lack the device-verified
  minimal pair (`platform-application` + `com.apple.private.security.no-sandbox`),
  packages built from stock (non-iOS) CLI artifacts, runtime artifacts that are
  not full-ICU or that lack WebAssembly/JIT (or contain `--v8-options=--jitless`),
  variant/artifact mismatches (a node18 CLI bundle with a node22 runtime or vice
  versa), and — for the **node22 variant only** — JIT-enabled runtime manifests
  without an iOS V8 W^X patch
  (`0004-ios-jit-write-protect.patch` or `0005-no-map-jit-on-ios.patch`); those
  are hard failures, not warnings. The node18 variant intentionally does not
  require the Node-22-only W^X patches (V8 10.2 uses its own device-proven memory
  model).
- Package history (node22, all superseded/not shippable): the first CI-green
  package (run `41185611403`, `.deb` SHA-256 `13a0483d...`) used a WASM-disabled
  runtime (`ReferenceError: WebAssembly is not defined`); the v3-runtime package
  (run `41202900005`, `.deb` SHA-256 `cf5db02a...`) trapped with SIGBUS in
  V8-generated code; the v4-runtime package (run `41218342323`, `.deb` SHA-256
  `1d643c3b8b3e4238bb1e692fadce9fcb72f74ea1b7b61621229cf502571b6dc4`) passed all
  CI checks but crashed on device at V8 code-range reservation (`FatalOOM`/
  SIGTRAP, iOS denies `mprotect` RWX). Node 18 is the shipping direction; the
  node18 package is `UNVERIFIED ON DEVICE` until the maintainer records the
  acceptance run.
- Optional bundled `rg` (stretch `ios-ripgrep` artifact) is only used if the
  artifact was published; its absence is reported as `SKIP`, not as a failure of
  the package. The optional `libjitshim.dylib` (`ios-jit-shim` artifact) is
  likewise included only when published (node22 variant only) and is injected
  via `DYLD_INSERT_LIBRARIES` only when present; it is a jailbreak JIT W^X
  interposer, documented and audited in `package-report.json`.
- See [`VERIFICATION.md`](VERIFICATION.md) for the exact CI evidence classes and
  [`INSTALL.md`](INSTALL.md) for device troubleshooting.
