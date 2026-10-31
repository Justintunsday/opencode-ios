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
| 5 | **Node.js 22.9.0, not Node 26.x.** Upstream OpenCode's Node build path normally targets a newer Node version. | APIs added after 22.9 are missing (e.g. `module.registerHooks`); the iOS prelude avoids them and the Vite bundle is patched, but some CLI features/paths could fail. Node 22.9's built-in fetch/undici requires WebAssembly (wasm llhttp), which is why the runtime must be built with WASM+JIT enabled. Host-runtime smoke passes for `--version`/`--help` on 22.9.0 after the iOS patch series; broader CLI commands are covered by the device runbook. | documented constraint |
| 6 | **JIT + WebAssembly are required and enabled in the shipped runtime, with an iOS V8 W^X patch.** Node 22.9's built-in fetch/undici needs WebAssembly (wasm llhttp). An intermediate JIT-less/WASM-disabled runtime made every CLI command fail with `ReferenceError: WebAssembly is not defined`; a later JIT+WASM build (v3) then trapped with **SIGBUS when executing V8-generated code** on device with every entitlement set, because V8's iOS W^X path (`MAP_JIT` + `pthread_jit_write_protect`) was a no-op. The v4 runtime adds patch `0004-ios-jit-write-protect.patch` and a tentative 4-key JIT entitlement set; its device run is pending. `OPENCODE_IOS_JITLESS=1` remains a debug escape hatch but disables JIT/WASM and breaks fetch/network features. | Until the v4 device run passes, JIT-dependent code execution on iOS is **unverified**; devices/jailbreaks that cannot provide executable memory would require JITless mode and lose fetch-based functionality. | unverified (v4 W^X fix pending device verification) |
| 7 | **Entitlements are device-verified only partially.** The JIT-less runtime works with exactly `platform-application` + `com.apple.private.security.no-sandbox` (device-verified; old 4-key allow-jit sets without those keys were SIGKILLed, exit 137). For V8 JIT on iOS, `dynamic-codesigning`/`allow-unsigned-executable-memory` are likely required (tentative v4 4-key set: the 2-key pair + those two) and are pending device verification; the loader can SIGKILL on an unresolved extra entitlement. | If the runtime is killed at startup, repair/re-sign with the shipped `runtime/entitlements.xml` only; do not add other keys randomly. Exact v4 entitlement set will be documented after the device run. | partially device-verified (preliminary); packaged CLI v4 pending |
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
| 20 | **ICU/Intl build requirement.** The Node runtime must be built with `--with-intl=full-icu` (small-icu only if it demonstrably supports `Intl.Segmenter`; it trims Intl data and `Intl.Segmenter` is known to misbehave on small-icu builds, and the CLI uses it at module top level). The first build used `--with-intl=none`: `Intl` was undefined and V8 rejected the Unicode property escapes used by the CLI bundle (`SyntaxError: Invalid regular expression: /[\p{Mark}\p{Control}...]/gu`), so the CLI could not start on device. | The final runtime (v3, run `41193603642`) is full-ICU (ICU 75) and the packaging CI rejects runtime artifacts whose manifest declares `--with-intl=none`; the final `.deb` is built from that runtime. | documented constraint (device-verified requirement; satisfied by the shipped runtime) |

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
  packages built from stock (non-iOS) CLI artifacts, and runtime artifacts that
  are not full-ICU or that lack WebAssembly/JIT (or contain `--v8-options=--jitless`);
  those are hard failures, not warnings.
- The first CI-green package (run `41185611403`, `.deb` SHA-256
  `13a0483d...`) was an **intermediate artifact, not shippable** (WASM-disabled
  runtime: `ReferenceError: WebAssembly is not defined`). The v3-runtime package
  (run `41202900005`, `.deb` SHA-256
  `cf5db02aedb680ac0f3f31013c7e824bc43a2ee79f41cf34e92659b93f022647`, includes the
  optional iPhoneOS `rg`) passed all CI checks but is also **superseded**: device
  testing trapped with SIGBUS in V8-generated code. The final `.deb` will be
  rebuilt from the v4 runtime (patch `0004-ios-jit-write-protect.patch`); its
  device run is still `UNVERIFIED ON DEVICE`.
- Optional bundled `rg` (stretch `ios-ripgrep` artifact) is only used if the
  artifact was published; its absence is reported as `SKIP`, not as a failure of
  the package.
- See [`VERIFICATION.md`](VERIFICATION.md) for the exact CI evidence classes and
  [`INSTALL.md`](INSTALL.md) for device troubleshooting.
