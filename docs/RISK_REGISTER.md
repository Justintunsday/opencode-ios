# Risk register — OpenCode iOS port

Living document. Severity × likelihood, with concrete mitigation and current status/evidence.
Status values: `open`, `mitigated` (control in place, residual risk), `closed` (verified).

| ID | Risk | Sev | Lik | Mitigation | Status / evidence |
| --- | --- | --- | --- | --- | --- |
| R1 | Node.js 22.9 iOS build fails under the current Xcode/iPhoneOS SDK (nodejs-mobile branch is experimental) | high | med | Pin base + apply nodejs-mobile PR #150 build fixes as a reviewed patch; build only the arm64 device slice; sccache + `out/Release` cache; fast configure gate before the full compile | open — `build-runtime.yml` |
| R2 | `make` does not produce the `node` CLI for `dest_os=ios` (framework-only build defaults) | high | med | Configure without `--enable-static` so gyp `node_target_type=executable` builds `out/Release/node` (precedent: Procursus, imcynic) | open — `build-runtime.yml` |
| R3 | OpenCode bundle needs Node > 22.9 APIs (`module.registerHooks`, `--use-system-ca`, `--experimental-ffi`, unflagged `node:sqlite`) | high | high | Patch series: bundle-time plugin module aliasing instead of loader hooks; drop unavailable flags from launcher; pass `--experimental-sqlite`; smoke-test on stock Node 22.9.0 in CI before packaging | open — `build-opencode.yml` + `patches/opencode/` |
| R4 | Native addons have no iPhoneOS builds (`node-pty`, `@parcel/watcher`, `ffi-rs`, `fff-bin`, persistent-pty Rust helper) | high | high | Make them optional with documented fallbacks; pipe-based shell execution; no-op watcher; upstream already has fff/ffi unavailable-proxy | open — `patches/opencode/`, `docs/KNOWN_LIMITATIONS.md` |
| R5 | V8 JIT/executable memory blocked on device; runtime built `--jitless` | med | high | Build jitless by design (no entitlement dependence); sign with minimal entitlements anyway; launcher env escape hatch; document performance expectation | mitigated by design |
| R6 | WebAssembly disabled in the runtime build (nodejs-mobile PR #150 config) — image processing / tree-sitter TUI highlighting unavailable | med | high | Treat wasm-dependent optional features as degraded; ensure no eager wasm import crashes startup; document | open — `patches/opencode/` |
| R7 | `process.platform` is `"ios"` (not `"darwin"`), so macOS branches do not run and unknown-platform branches may throw | med | high | CLI patch introduces Darwin-like handling for `ios`; specific degraded paths (watcher backend, updater, browser opener) handled explicitly | open |
| R8 | Agent search tool needs `rg`; release map has no iOS asset | med | med | Ship an iPhoneOS-built `ripgrep` in `/var/jb/usr/bin` (stretch job) and/or document search degradation | open |
| R9 | Rootless packaging mistakes (wrong paths, missing exec bits, wrong architecture, macOS dylib linkage) | high | low | CI validation: Mach-O platform/arch/minos, `otool -L` allow-list, deb path audit under `/var/jb`, `sh -n` scripts, SHA256 | open — `package-rootless.yml`, `test-port.yml` |
| R10 | Code signing/entitlements not accepted on the jailbroken device (AMFI/ldid behaviour varies by jailbreak) | med | med | Sign with ldid in CI; keep entitlements minimal; ship entitlements.xml + INSTALL troubleshooting (`ldid -S` re-sign); no JIT dependency | open — device test required |
| R11 | No physical device available in CI; runtime failures cannot be observed in this environment | high | certain (known) | All reports mark device execution `UNVERIFIED ON DEVICE`; ship an on-device smoke script (`device-smoke.sh`) and verification runbook; do not claim device success | tracked — `docs/VERIFICATION.md` |
| R12 | CI cost/time: macOS runners, long V8 compile | med | med | Public repo (free standard runners); sccache + compile cache; build only device arm64 slice; fast-fail configure gate; workflow concurrency guard | open — `build-runtime.yml` |
| R13 | Upstream drift: OpenCode pinned dev snapshot moves; patches stop applying | low | med | Pin commit in `UPSTREAM.lock`; patches applied to a temp checkout; patch series hashed in manifest; upgrade is a separate reviewed change | mitigated by pin |
| R14 | User data/permissions on device: running as mobile, config under `$HOME`, rootless paths | med | low | Launcher defaults to unprivileged user; no hardcoded tokens; config/auth in user home; documented | open — `docs/INSTALL.md` |
| R15 | License/attribution violation (OpenCode MIT, Node MIT, nodejs-mobile MIT) | high | low | Preserve LICENSE/NOTICE and upstream attribution in repo and in the packaged `/usr/share/doc/opencode/copyright`; only patches are shipped, upstream repos untouched | mitigated |
| R16 | Artifact tampering/mismatch between workflows (package uses stale/different bundle) | med | low | `package-report.json` records source run ids + SHA256 of every input; `test-port.yml` re-verifies hashes | open — `package-report.json` |

## Known-unverifiable-on-CI items (explicit)

- Actual on-device execution of the `.deb` on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless.
- JIT/WASM behaviour under the device's code-signing configuration.
- Terminal-specific behaviour in NewTerm vs SSH (PTY allocation is degraded by design in v1).
- Provider API connectivity from the device network (user must run `opencode auth login`).
