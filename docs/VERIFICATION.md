# Verification matrix — OpenCode iOS (rootless)

This document distinguishes **what CI actually proves** from what is
**unverified** and must be executed on a real device. No CI run and no document in
this repository claims on-device success.

## Status summary

| Evidence class | Environment | Status |
| --- | --- | --- |
| Static package validation (Mach-O, dylibs, paths, permissions, metadata, manifests) | GitHub Actions `macos-15` runner | **CI-verified** when the workflows are green |
| Host-runtime JS smoke (`--version`, `--help`, launcher argv forwarding) | GitHub Actions `macos-15` runner, host Node.js 22.9.0 (nodejs.org, checksum-pinned) | **CI-verified** when the workflows are green |
| Compile of the native iPhoneOS runtime | GitHub Actions `macos-15` runner + iPhoneOS SDK | **CI-verified** (build-runtime workflow) |
| Actual CLI execution on iPhone SE 2 / iOS 16.1.1 / Dopamine rootless | Real device | **UNVERIFIED ON DEVICE** — requires the user runbook below |

> **UNVERIFIED ON DEVICE — requires real iPhone SE 2 (iOS 16.1.1, Dopamine rootless).**
> Hosted GitHub Actions macOS runners cannot execute iOS arm64 binaries. Any green
> check below is runner-only evidence.

## Where the evidence lives

| Artifact | Produced by | Contents |
| --- | --- | --- |
| `OpenCode-iOS-rootless` | `package-rootless.yml` | `.deb`, `SHA256SUMS`, `package-report.json` (contents manifest, Mach-O audit, sizes, SHA-256s, source run ids, device status) |
| `port-verification` | `test-port.yml` | `verification-report.json`, `verification-report.md`, `check-results.json`, `unittest.log`, `host-smoke.json`, extracted-file manifest, `dpkg-deb --info/--contents` dumps |

Latest successful runs (filled in from the artifacts; also recorded in
`package-report.json` → `workflow.run_url` and `sources.inputs.*.run_url`):

| Workflow | Run | Artifact |
| --- | --- | --- |
| `build-runtime.yml` | see `package-report.json` → `sources.inputs.runtime.run_url` | `ios-node-runtime` |
| `build-opencode.yml` | see `package-report.json` → `sources.inputs.opencode_cli.run_url` | `opencode-cli-node-ios` |
| `package-rootless.yml` | see `package-report.json` → `workflow.run_url` | `OpenCode-iOS-rootless` |
| `test-port.yml` | see the Actions tab of <https://github.com/Justintunsday/opencode-ios/actions> | `port-verification` |

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
| Control metadata | `Package: opencode`, `Version: 2.2.5-1` (from `UPSTREAM.lock`), `Architecture: iphoneos-arm64`, `Depends: firmware (>= 15.0)` only (no node/zsh/ldid package deps), `Section: Development`, `Priority: optional`, multi-line `Description`, `Installed-Size` sane |
| Rootless layout | every installed path under `var/jb/`; required paths/modes; no unexpected files; `/var/jb/usr/bin/opencode` 0755, runtime node 0755, CLI/assets/docs 0644 |
| Permissions | no setuid/setgid/sticky, no world-writable, documented mode policy |
| Maintainer scripts | `postinst`/`prerm`/`postrm` are `#!/bin/sh`, `set -e`, `sh -n` clean, offline (no curl/wget/apt/npm/pip/ldid calls), `/var/jb`-relative, executed twice against a rewritten root to prove idempotency |
| Launcher contract | `#!/bin/sh`, execs runtime, forwards `"$@"`, passes `--experimental-sqlite`/`--no-warnings`, exports `OPENCODE_NODE_ASSETS_DIR`/`OPENCODE_IOS=1`, documents the JITless escape hatch, no invalid Node 22.9 flags (`--use-system-ca`, `--experimental-ffi`), no `uname` dependence, no embedded credentials |
| Native runtime | `scripts/check_macho.py`: thin arm64 little-endian Mach-O, `MH_EXECUTE`, `LC_BUILD_VERSION platform=iPhoneOS(2)`, minOS ≤ 16.1.1; `otool -L`: iOS system libraries only, no `/opt/homebrew`, `/usr/local`, `@rpath`/`@loader_path`, or macOS-only frameworks; `LC_CODE_SIGNATURE` presence (ldid); entitlements plist parses; `runtime-manifest.json` hashes match the shipped node |
| CLI bundle | `opencode.mjs` present and non-placeholder; `assets/**` copied verbatim; `bundle-manifest.json` hash entries verified when the format is recognised; deb files byte-identical to the source artifacts (`sha256` comparison against provenance) |
| Host-runtime smoke | pinned Node.js **22.9.0** downloaded from nodejs.org with `SHASUMS256.txt` SHA-256 verification; `node opencode.mjs --version` and `--help`; the **packaged launcher** run with `OPENCODE_IOS_PREFIX`/`OPENCODE_IOS_NODE` pointing at the host node (flag ordering, exec, argv forwarding incl. rejection of an unknown flag); version output must contain the pinned upstream version |
| Integrity & hygiene | `SHA256SUMS` matches the `.deb`; contents manifest re-verified against the archive (path/mode/size/SHA-256); no secret files/private keys; no `.git`/`node_modules`/`.DS_Store`/debug artifacts; size limits; packaged docs contain MIT/attribution and state the device status |
| Repository | LF line endings, shell syntax, no secrets in tracked files, packaging layout, workflow contract, factory unit tests (`python3 -m unittest discover -s tests -v`), optional workflow YAML parse |
| Optional components | iPhoneOS `rg` (stretch `ios-ripgrep` artifact): Mach-O + dylib audit when shipped; explicit SKIP when absent |

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
| 1 | Install | `sudo dpkg -i OpenCode-iOS-rootless.deb` | dpkg status `install ok installed`, no errors |
| 2 | CLI starts | `opencode --version` | exit 0, upstream version (2.2.5) printed |
| 3 | Help | `opencode --help` | exit 0, usage/commands printed |
| 4 | JITless startup | `opencode --version; echo exit=$?` | `exit=0`, no `Killed: 9`/bus error |
| 5 | Paths | `opencode debug paths` | config/data under `/var/mobile` (optional command; version-dependent) |
| 6 | Auth | `opencode auth list`, `opencode auth login` | login completes; credentials only in user home |
| 7 | Offline scripted smoke | `sh /var/jb/usr/share/doc/opencode/device-smoke.sh` | final line `DEVICE SMOKE TEST: PASS` |
| 8 | Liveness/signature | `sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml /var/jb/usr/lib/opencode/runtime/node` then `opencode --version` | re-signed runtime still starts (repair path works) |
| 9 | TUI (degraded PTY) | `cd /var/mobile/Documents && opencode` | TUI starts; shell tool panes use fallback (see limitations) |
| 10 | Agent turn (needs network+auth) | `opencode run "summarise this repository"` | request completes; results returned |
| 11 | Uninstall | `sudo dpkg -r opencode` (then `-P`) | package files gone; `~/.config/opencode` and sessions preserved |

Optional after test 10: confirm a local file edit and a `git` operation through
the agent in a throwaway repository.

## Device runbook (exact commands)

On the iPhone:

```sh
cd /var/mobile/Documents
sha256sum -c SHA256SUMS
sudo dpkg -i OpenCode-iOS-rootless.deb
opencode --version; echo "version_exit=$?"
opencode --help;    echo "help_exit=$?"
sh /var/jb/usr/share/doc/opencode/device-smoke.sh
opencode debug paths || true
opencode auth list || true
```

Record and report: device model, iOS version, jailbreak, `.deb` SHA-256, full
command outputs, and PASS/FAIL for each row of the table above. Open an issue at
<https://github.com/Justintunsday/opencode-ios/issues> — **never include API keys
or tokens**.

## How to re-run the CI verification locally

```sh
# after downloading the OpenCode-iOS-rootless artifact contents:
sha256sum -c SHA256SUMS
bash scripts/validate-port.sh --deb OpenCode-iOS-rootless.deb --mode verify \
  --artifact-dir . --package-report package-report.json --out-dir verification
```

The script needs `python3`; `otool`/`xcrun` for native checks (macOS) and network
access for the pinned Node.js download. Use `--skip-native-audit --skip-smoke`
only for local dry-runs; CI never skips these.

## Honesty guarantees

- Green CI ≠ device-verified. The report generator emits the literal strings
  `UNVERIFIED ON DEVICE` and `DEVICE TESTS: NOT PERFORMED (requires real iPhone)`
  in every report; there is no code path that marks a device test as passing.
- If an upstream artifact is missing, the packaging/validation workflows fail
  with an explicit message and never fabricate inputs.
- Skips are reported as `SKIP` with a reason (for example an optional
  `ios-ripgrep` artifact that was not published); they are never counted as passes.
