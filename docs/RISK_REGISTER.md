# Risk register 鈥?OpenCode iOS port

Living document. Severity 脳 likelihood, with concrete mitigation and current status/evidence.
Status values: `open`, `mitigated` (control in place, residual risk), `closed` (verified).

| ID | Risk | Sev | Lik | Mitigation | Status / evidence |
| --- | --- | --- | --- | --- | --- |
| R1 | Node.js 22.9 iOS build fails under the current Xcode/iPhoneOS SDK (nodejs-mobile branch is experimental) | high | med | Pin base + apply nodejs-mobile PR #150 build fixes as a reviewed patch; build only the arm64 device slice; sccache + `out/Release` cache; fast configure gate before the full compile | open 鈥?`build-runtime.yml` |
| R2 | `make` does not produce the `node` CLI for `dest_os=ios` (framework-only build defaults) | high | med | Configure without `--enable-static` so gyp `node_target_type=executable` builds `out/Release/node` (precedent: Procursus, imcynic) | **closed** 鈥?run 41171982508 built `out/Release/node` via make and it executed on the device |
| R2b | Runtime built without ICU cannot run the CLI: no `Intl`, V8 rejects `\p{...}` regex escapes | high | high (found) | Build with `--with-intl=full-icu` (canned ICU source in pinned tree); device-verify `typeof Intl` and `\p{L}`; hard-gate ICU symbols in CI | **mitigated** 鈥?ICU rebuild dispatched; no-ICU artifact device-rejected with exact SyntaxError recorded |
| R3 | OpenCode bundle needs Node > 22.9 APIs (`module.registerHooks`, `--use-system-ca`, `--experimental-ffi`, unflagged `node:sqlite`) | high | high | Patch series: bundle-time plugin module aliasing instead of loader hooks; drop unavailable flags from launcher; pass `--experimental-sqlite`; smoke-test on stock Node 22.9.0 in CI before packaging | open 鈥?`build-opencode.yml` + `patches/opencode/` |
| R4 | Native addons have no iPhoneOS builds (`node-pty`, `@parcel/watcher`, `ffi-rs`, `fff-bin`, persistent-pty Rust helper) | high | high | Make them optional with documented fallbacks; pipe-based shell execution; no-op watcher; upstream already has fff/ffi unavailable-proxy | open 鈥?`patches/opencode/`, `docs/KNOWN_LIMITATIONS.md` |
| R5 | V8 JIT/executable memory blocked on device; runtime built `--jitless` | med | high | Build jitless by design (no entitlement dependence); sign with minimal entitlements anyway; launcher env escape hatch; document performance expectation | mitigated by design |
| R6 | WebAssembly disabled in the runtime build (nodejs-mobile PR #150 config) 鈥?image processing / tree-sitter TUI highlighting unavailable | med | high | Treat wasm-dependent optional features as degraded; ensure no eager wasm import crashes startup; document | open 鈥?`patches/opencode/` |
| R7 | `process.platform` is `"ios"` (not `"darwin"`), so macOS branches do not run and unknown-platform branches may throw | med | high | CLI patch introduces Darwin-like handling for `ios`; specific degraded paths (watcher backend, updater, browser opener) handled explicitly | open |
| R8 | Agent search tool needs `rg`; release map has no iOS asset | med | med | Ship an iPhoneOS-built `ripgrep` in `/var/jb/usr/bin` (stretch job) and/or document search degradation | open |
| R9 | Rootless packaging mistakes (wrong paths, missing exec bits, wrong architecture, macOS dylib linkage) | high | low | CI validation: Mach-O platform/arch/minos, `otool -L` allow-list, deb path audit under `/var/jb`, `sh -n` scripts, SHA256 | open 鈥?`package-rootless.yml`, `test-port.yml` |
| R10 | Code signing/entitlements not accepted on the jailbroken device (AMFI/ldid behaviour varies by jailbreak) | med | med | Sign with ldid in CI; keep entitlements minimal; ship entitlements.xml + INSTALL troubleshooting (`ldid -S` re-sign); no JIT dependency | open 鈥?device test required |
| R11 | No physical device available in CI; runtime failures cannot be observed in this environment | high | certain (known) | All reports mark device execution `UNVERIFIED ON DEVICE`; ship an on-device smoke script (`device-smoke.sh`) and verification runbook; do not claim device success | tracked 鈥?`docs/VERIFICATION.md` |
| R12 | CI cost/time: macOS runners, long V8 compile | med | med | Public repo (free standard runners); sccache + compile cache; build only device arm64 slice; fast-fail configure gate; workflow concurrency guard | open 鈥?`build-runtime.yml` |
| R13 | Upstream drift: OpenCode pinned dev snapshot moves; patches stop applying | low | med | Pin commit in `UPSTREAM.lock`; patches applied to a temp checkout; patch series hashed in manifest; upgrade is a separate reviewed change | mitigated by pin |
| R14 | User data/permissions on device: running as mobile, config under `$HOME`, rootless paths | med | low | Launcher defaults to unprivileged user; no hardcoded tokens; config/auth in user home; documented | open 鈥?`docs/INSTALL.md` |
| R15 | License/attribution violation (OpenCode MIT, Node MIT, nodejs-mobile MIT) | high | low | Preserve LICENSE/NOTICE and upstream attribution in repo and in the packaged `/usr/share/doc/opencode/copyright`; only patches are shipped, upstream repos untouched | mitigated |
| R16 | Artifact tampering/mismatch between workflows (package uses stale/different bundle) | med | low | `package-report.json` records source run ids + SHA256 of every input; `test-port.yml` re-verifies hashes | open 鈥?`package-report.json` |

## Known-unverifiable-on-CI items (explicit)

- Actual on-device execution of the `.deb` on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless.
- JIT/WASM behaviour under the device's code-signing configuration.
- Terminal-specific behaviour in NewTerm vs SSH (PTY allocation is degraded by design in v1).
- Provider API connectivity from the device network (user must run `opencode auth login`).
## Device verification evidence (2026-10-31, real hardware)

Target device used for verification: iPhone SE 2 (`iPhone12,8`), iPhone OS 16.1.1 (20B101),
Darwin 22.1.0 arm64, Dopamine rootless (`/var/jb` -> `/private/preboot/.../dopamine-*/procursus`),
ElleKit 1.2, user `mobile` (uid 501), NewTerm/SSH, ~96 GiB free.

| Evidence | Result |
| --- | --- |
| iPhoneOS arm64 Node.js 22.9.0 binary executes on device | PASS (`v22.9.0`, `process.platform="ios"`, arch arm64) |
| V8 reports `v8 12.4.254.21-node.19`, `uv 1.48.0`, `openssl 3.0.13+quic`, `sqlite 3.46.1` | PASS |
| `node:sqlite` `DatabaseSync` create/insert/select with `--experimental-sqlite` | PASS |
| fs write/read in user home | PASS |
| TLS/network (`api.github.com` reached, HTTP 403 without UA) | PASS |
| `child_process` explicit `/var/jb/bin/sh -c` execution (uid 501) and child `node` spawn | PASS |
| `WebAssembly` unavailable (jitless/no-wasm build) | as designed |
| Minimal working entitlements | `platform-application` + `com.apple.private.security.no-sandbox`; 4-key/naive sets SIGKILL (exit 137) |
| Rootless `dpkg` maintainer-script execution with `#!/bin/sh` (test deb) | PASS; direct-executables need `#!/var/jb/bin/sh` |
| Initial no-ICU runtime vs CLI bundle | FAIL (expected): `SyntaxError: Invalid regular expression: /[\p{Mark}...]/gu`; ICU rebuild required |

Remaining device runbook (installable .deb, CLI commands, headless agent turn, uninstall) is executed
once the ICU-enabled runtime artifact and the packaged `.deb` exist; results are recorded in
`docs/VERIFICATION.md`