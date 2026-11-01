# Install OpenCode iOS (rootless) on iPhone SE 2 / iOS 16.1.1

This is the device installation procedure for `OpenCode-iOS-rootless.deb`, an
`iphoneos-arm64` Debian package that installs upstream **OpenCode v2 CLI** running
on a native iPhoneOS arm64 **Node.js 22.9.0** runtime, entirely beneath
`/var/jb` (Dopamine rootless layout).

> **Verification status:** the package is built and statically validated in GitHub
> Actions, and the CLI bundle is smoke-tested on a host Node.js 22.9.0 runtime.
> **On-device execution has not been performed by CI and remains
> `UNVERIFIED ON DEVICE`** until you run the smoke test in section 10 and report
> the result. See [`VERIFICATION.md`](VERIFICATION.md).

Target environment (only configuration validated by CI):

| Property | Value |
| --- | --- |
| Device | iPhone SE (2nd generation), identifier `iPhone12,8`, arm64 |
| iOS | 16.1.1 (20B101), Darwin 22.1.0 |
| Jailbreak | Dopamine (rootless), `/var/jb` -> `/private/preboot/.../dopamine-*/procursus`, ElleKit 1.2 |
| Package | `OpenCode-iOS-rootless.deb` (`Architecture: iphoneos-arm64`) |
| Installed binary | `/var/jb/usr/bin/opencode` |
| Runtime / CLI / assets | `/var/jb/usr/lib/opencode/{runtime,cli}` |
| Docs | `/var/jb/usr/share/doc/opencode/` |

Rootless environment facts (device-verified on the target iPhone):

| Fact | Detail |
| --- | --- |
| Shells | **No `/bin/sh`, `/bin/bash` or `/bin/zsh`.** The bootstrap shells are `/var/jb/bin/sh` and `/var/jb/usr/bin/sh` (both symlinks to `/var/jb/usr/bin/dash`), plus `/var/jb/bin/bash`, `/var/jb/bin/zsh`. |
| `HOME` | SSH/NewTerm sessions run as `mobile` (uid 501) with `HOME=/var/jb/var/mobile`. Config/data therefore resolve to `/var/jb/var/mobile/.config/opencode` and `/var/jb/var/mobile/.local/share/opencode`. |
| `PATH` | SSH default: `/usr/bin:/bin:/usr/sbin:/sbin:/var/jb/usr/bin`. The packaged launcher prepends `/var/jb/bin:/var/jb/usr/bin` so shells/tools spawned by the CLI resolve. |
| `git` | **Not installed by default.** The package `Recommends: git`; install it with `sudo apt-get install -y git` (Procursus apt, git 2.39.1) for git tool support. |
| Entitlements | The device-verified minimal runtime entitlement set is `platform-application` + `com.apple.private.security.no-sandbox` (the `.deb` ships it as `runtime/entitlements.xml`). Older allow-jit/executable-memory sets are **not** sufficient. The current Node 18 and Node 22 runtime builds use this 2-key set. |
| Runtime variants | The package is built from **one** of two runtimes and ships exactly one: **Node 18.20.4** (primary; V8 10.2 memory model, device-proven) or **Node 22.9.0** (experimental; newer V8 W^X model, device verification pending). Detect the installed variant with `/var/jb/usr/lib/opencode/runtime/node -p process.versions.node`; the `.deb` metadata description and `package-report.json` (`variant`/`runtime_kind`) also state it. |
| Runtime capabilities | The shipped runtime must be **full-ICU** with **WebAssembly and JIT enabled** (Node's built-in fetch/undici requires wasm llhttp; a wasm-disabled runtime fails on device with `ReferenceError: WebAssembly is not defined`). Packaging CI rejects runtimes built `--with-intl=none` or with `--jitless`/WebAssembly disabled, and requires `Intl.Segmenter` data (full-ICU; small-ICU trims it). |
| sqlite implementation | **Node 18**: the CLI maps `node:sqlite` to a bundled **sql.js WebAssembly shim** (`cli/assets/node18-sqlite/`), which persists the database as a whole file (no WAL; a crash can lose recent writes — see `KNOWN_LIMITATIONS.md`). **Node 22**: uses built-in `node:sqlite`. |
| Optional JIT shim | Node 22 variant only: if the `ios-jit-shim` artifact is published, the package installs `/var/jb/usr/lib/opencode/runtime/libjitshim.dylib` (0755) and the launcher exports `DYLD_INSERT_LIBRARIES` for it **only when present**. It is a jailbreak-only JIT interposer (relaxes W^X/mprotect for V8) and is recorded in `package-report.json`; without it the launcher behaves normally. The Node 18 variant does not use the shim. |
| Launcher shebang | `/var/jb/usr/bin/opencode` starts with `#!/var/jb/bin/sh` because the kernel execs it directly and `/bin/sh` does not exist. Maintainer scripts keep `#!/bin/sh`, which rootless Procursus `dpkg` handles (device-verified). |
| `TMPDIR` | Some SSH/NewTerm sessions do not export `TMPDIR`; both launchers provide a writable fallback (`/var/jb/tmp`, `/var/jb/var/tmp`, `/tmp`) and export it. |

Node.js 22.9.0 is older than the Node version upstream OpenCode normally targets;
the Node 18 fallback intentionally uses Node 18.20.4 (the V8 memory model that is
device-proven on iOS 16.1.1). See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 1. Requirements

- Dopamine **rootless** jailbreak (a rootless bootstrap that mounts `/var/jb`).
  Rootful jailbreaks and other prefixes are **not** supported by this package.
- A terminal: NewTerm 3 or SSH. `dpkg` from the rootless bootstrap
  (`/var/jb/usr/bin/dpkg`). On the target device `sudo` works with the device
  password, and `dpkg`, `ldid`, `zsh` are installed.
- ~150 MB free under `/var/jb` for the runtime, CLI bundle and assets
  (`Installed-Size` in the package metadata is authoritative).
- Internet access only for **agent usage** (provider API calls) and for optional
  `git` installation. Installation, `--version`, `--help` and `auth list` are
  offline.
- Optional: `git` for git tool support (`sudo apt-get install -y git`; the
  package declares `Recommends: git`, not a hard dependency).

## 2. Get the package

Download the **`OpenCode-iOS-rootless` artifact** from the latest successful
`package-rootless.yml` run:

<https://github.com/Justintunsday/opencode-ios/actions/workflows/package-rootless.yml>

The artifact contains:

| File | Purpose |
| --- | --- |
| `OpenCode-iOS-rootless.deb` | the installable package |
| `SHA256SUMS` | SHA-256 of the `.deb` |
| `package-report.json` | contents manifest, Mach-O audit, sizes, sha256s, source run ids, **variant/runtime_kind** |

Current pinned version: OpenCode **2.2.5** (package version `2.2.5-1`, see
`UPSTREAM.lock`). The exact SHA-256 of the published `.deb` is recorded in
`SHA256SUMS` and inside `package-report.json`.

### Which runtime variant is in this package?

One package ships exactly one runtime; the artifact name is the same for both:

| Variant | Runtime | Status | How to tell |
| --- | --- | --- | --- |
| `node18` | Node.js **18.20.4** iPhoneOS arm64, bundled sql.js sqlite shim | **Primary**, CLI runs on device with a community Node 18 runtime; our full-ICU Node 18 runtime is CI-built and awaiting its device acceptance run | `package-report.json`: `"variant": "node18"` / `"runtime_kind": "node18"`; `runtime.node.node_version` starts `18.` |
| `node22` | Node.js **22.9.0** iPhoneOS arm64, built-in sqlite | **Experimental**; the JIT memory model is not yet device-runnable (CI builds v5/v6 W^X variants) | `package-report.json`: `"variant": "node22"`; `runtime.node.node_version` starts `22.` |

Inside the installed package: `/var/jb/usr/lib/opencode/runtime/node -p process.versions.node`
prints the runtime version, and `/var/jb/usr/lib/opencode/runtime/runtime-manifest.json`
declares the capability profile.

> **Shipping status (2026-11-01):** the **Node 18 variant is the primary
> deliverable**, pending the maintainer's acceptance run on the final package
> (device evidence so far: with a device-proven community Node 18.20.4 iPhoneOS
> runtime the Node 18 CLI bundle runs `--version`, `debug paths`, `debug config`,
> `models` and `session list` with rc=0 and sql.js sqlite persistence works; that
> reference runtime is small-ICU and `--help` crashes in `Intl.Segmenter`, which
> is why the shipped runtime is our own full-ICU Node 18 build). The **Node 22
> variant is experimental and not device-runnable yet**: the v4-runtime package
> (run `41218342323`, `.deb` SHA-256
> `1d643c3b8b3e4238bb1e692fadce9fcb72f74ea1b7b61621229cf502571b6dc4`) passes every
> CI check but crashes on the iPhone while reserving V8 code range
> (`EXC_BREAKPOINT`/SIGTRAP → `FatalOOM` in `CodeRange::InitReservation`: iOS
> denies `mprotect` to RWX); v5/v6 mprotect-based W^X and the optional
> `ios-jit-shim` interposer are still under device investigation. Do **not**
> install the superseded v3-runtime package (run `41202900005`; SIGBUS on
> generated code) or WASM-disabled packages (`.deb` sha `13a0483d...`;
> `ReferenceError: WebAssembly is not defined`). Install a package only after the
> maintainer records a matching device run in `docs/VERIFICATION.md`.

## 3. Transfer the package to the device

Your device home is `/var/jb/var/mobile`, so `~/Documents` below means
`/var/jb/var/mobile/Documents`.

Pick one:

- **AirDrop / Filza:** AirDrop the `.deb` to the iPhone, then use Filza to move it
  to `~/Documents/` (`/var/jb/var/mobile/Documents/`).
- **SSH/SFTP** (OpenSSH from the rootless bootstrap, on the same Wi-Fi):

  ```sh
  scp OpenCode-iOS-rootless.deb SHA256SUMS mobile@<iphone-ip>:Documents/
  ```

- **NewTerm on-device download** (`curl` from the rootless bootstrap) into
  `~/Documents/` if you have the artifact URL.

## 4. Verify integrity on the device

```sh
cd ~/Documents
sha256sum -c SHA256SUMS
# expected: OpenCode-iOS-rootless.deb: OK
dpkg-deb --info OpenCode-iOS-rootless.deb | head -n 20
# expected: Package: opencode, Version: 2.2.5-1, Architecture: iphoneos-arm64,
#           Depends: firmware (>= 15.0), Recommends: git
```

If `sha256sum` is unavailable, use `shasum -a 256 OpenCode-iOS-rootless.deb` and
compare with the value in `SHA256SUMS`.

## 5. Install

```sh
sudo dpkg -i ~/Documents/OpenCode-iOS-rootless.deb
```

Expected: dpkg unpacks under `/var/jb`, runs `postinst`, and prints
`OpenCode iOS installed (rootless, /var/jb).`

Alternatives:

- **Sileo:** add the `.deb` as a local package (Sileo may require the repo/hosted
  route or Filza's installer integration).
- **Filza:** tap the `.deb` → Install.

`Depends: firmware (>= 15.0)` is provided by the rootless bootstrap. If `dpkg`
reports a missing `firmware` package, install/repair the bootstrap via Sileo; do
not force-install with `--force-depends`. The package ships its own Node runtime
and does **not** depend on any node/nodejs package.

## 6. First run

```sh
opencode --version
/var/jb/usr/lib/opencode/runtime/node -p process.versions.node   # 18.x or 22.x
opencode --help
```

The launcher (`/var/jb/usr/bin/opencode`, POSIX `dash`/`sh`, shebang
`#!/var/jb/bin/sh`) prepends `/var/jb/bin:/var/jb/usr/bin` to `PATH`, provides a
`TMPDIR` fallback, exports `OPENCODE_NODE_ASSETS_DIR` and `OPENCODE_IOS=1`, and
executes the runtime. The exact Node flags depend on the shipped variant:

```sh
# node18 variant (primary): Node 18 rejects the newer Node 22-only flags
/var/jb/usr/lib/opencode/runtime/node --no-warnings \
  --max-old-space-size=1536 \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"

# node22 variant (experimental)
/var/jb/usr/lib/opencode/runtime/node \
  --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings \
  --max-old-space-size=1536 \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

On the **Node 18 variant** the CLI maps `node:sqlite` to the bundled sql.js
WebAssembly shim (`cli/assets/node18-sqlite/sql-wasm.js|wasm`): sessions are
persisted as a whole database file under `~/.local/share/opencode` (no WAL; a
crash can lose recent writes — see `KNOWN_LIMITATIONS.md`). The launcher shebang
is `/var/jb/bin/sh` because rootless iOS has no `/bin/sh` and the kernel executes
`/var/jb/usr/bin/opencode` directly. If `opencode` is not found, add
`export PATH="/var/jb/usr/bin:$PATH"` to `~/.profile`. Your session `HOME` is
`/var/jb/var/mobile` (SSH/NewTerm), so config and sessions live beneath it.

The shipped runtime (either variant) is built with **full ICU and with
WebAssembly + JIT enabled**, signed with the device-verified 2-key entitlement
set. WebAssembly and JIT are required: Node's built-in fetch/undici needs wasm
llhttp, and a jitless/no-wasm build fails with
`ReferenceError: WebAssembly is not defined` for every CLI command.
`Intl.Segmenter` requires full-ICU: Node 18's community small-ICU runtime crashes
on `--help`, so the shipped Node 18 runtime is our own full-ICU build. The
`OPENCODE_IOS_JITLESS=1` escape hatch (node22 variant only) adds `--jitless`
(debug/fallback only): it disables JIT and WebAssembly, so network/fetch-dependent
commands will not work. Escape hatches (documented in `KNOWN_LIMITATIONS.md`):

```sh
OPENCODE_IOS_JITLESS=1 opencode --version     # node22 debug only: disables JIT+WASM
OPENCODE_IOS_MAX_OLD_SPACE_MB=1024 opencode   # lower V8 heap (2 GB devices)
OPENCODE_IOS_NODE_FLAGS=--trace-warnings opencode   # extra Node/V8 flags
```

## 7. Provider authentication (never embedded in the package)

```sh
opencode auth login          # interactive provider/API-key setup
opencode auth list           # show configured credentials (offline)
```

Supported paths include OpenAI-compatible providers and DeepSeek through the
CLI's normal provider configuration. Credentials are stored in the user home
(typically `~/.local/share/opencode/auth.json`, mode 600) — never in the package,
never in the repository, never in the launcher. For non-interactive use you can
export provider environment variables (for example `OPENAI_API_KEY` or
`DEEPSEEK_API_KEY`) in your own shell profile.

Configuration lives in `~/.config/opencode/` (for example
`~/.config/opencode/opencode.json`); sessions/history and caches live under
`~/.local/share/opencode/` and `~/.cache/opencode/`. On this rootless device the
session `HOME` is `/var/jb/var/mobile`, so those paths expand to
`/var/jb/var/mobile/.config/opencode` etc.

> API keys are user data. Do not commit them, do not paste them into issues, and
> do not add them to the launcher or package.

## 8. Project usage

```sh
cd ~/Documents/my-project
opencode                 # interactive TUI (see PTY caveat below)
opencode --help          # commands and flags
opencode run "summarise this repository"   # headless, requires auth+network
```

Git support: `git` is not installed by the rootless bootstrap by default; the
package declares `Recommends: git`, not a hard dependency. Install it when you
need git tool features:

```sh
sudo apt-get update
sudo apt-get install -y git   # Procursus apt, device-verified: git 2.39.1
git --version
```

TUI/terminal caveats: interactive PTY panes and native file watchers have no
iPhoneOS builds, so shell tool calls use pipe-based `child_process` fallback and
file-watch features degrade to polling/none. The shell fallback needs a working
rootless shell (`/var/jb/bin/sh` -> dash); the launcher's `PATH` prepend makes
that available to the CLI. Headless `run` mode is the more reliable path. See
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 9. Upgrade / uninstall

```sh
# upgrade in place (config and sessions are preserved)
sudo dpkg -i ~/Documents/OpenCode-iOS-rootless.deb

# remove the package, keep user data
sudo dpkg -r opencode

# purge: also removes package-owned caches; user config/sessions are preserved
sudo dpkg -P opencode

# manual cleanup of user data (only if you really want it gone)
rm -rf ~/.config/opencode ~/.local/share/opencode ~/.cache/opencode
```

## 10. On-device smoke test (required for device verification)

The package installs a smoke-test script:

```sh
sh /var/jb/usr/share/doc/opencode/device-smoke.sh
```

Success criteria:

| Check | Expected output |
| --- | --- |
| runtime present | `OK   native iPhoneOS Node runtime present` |
| runtime variant | `runtime variant: Node 18 …` (or `Node 22 …`; both layouts identical) |
| CLI bundle present | `OK   CLI bundle present` |
| launcher executable | `OK   launcher present and executable` |
| rootless shell | `OK   rootless shell executable: /var/jb/bin/sh` (rootless iOS has no `/bin/sh`) |
| shell in PATH | `OK   sh resolves in PATH: /var/jb/usr/bin/sh` |
| HOME/TMPDIR writable | `OK   HOME is writable: /var/jb/var/mobile` and `OK   TMPDIR is writable` (a WARN is acceptable if the shell exports neither) |
| git (optional) | `OK   git present: git version 2.39.1` — or a `WARN ... install with: sudo apt-get install -y git` |
| runtime capabilities | `OK   runtime capabilities: WebAssembly=object, v8_enable_webassembly=1, fetch=function, Intl=object, Intl.Segmenter=function` |
| WebAssembly compilation | `OK   WebAssembly module compilation works (JIT/executable memory available)` |
| `opencode --version` | exit 0 and the OpenCode version (2.2.5) printed |
| `opencode --help` | exit 0 with a usage block (requires full-ICU; a WARN is shown on small-ICU Node 18 runtimes) |
| sqlite persistence | `OK   opencode session list …` and `OK   sqlite database file present …` (Node 18 uses the sql.js shim) |
| argument forwarding | `OK   launcher forwards CLI arguments` |
| overall | `DEVICE SMOKE TEST: PASS (offline checks only; model connectivity not tested)` |

Manual equivalent (what proves success):

```sh
opencode --version; echo "exit=$?"      # exit=0 and a version string
/var/jb/usr/lib/opencode/runtime/node -p process.versions.node   # 18.x or 22.x
opencode --help;    echo "exit=$?"      # exit=0 and usage text (full-ICU)
opencode debug paths                    # config/data under /var/jb/var/mobile (optional)
opencode models                         # offline model list (optional)
opencode session list; echo "exit=$?"   # exit=0 proves sqlite (sql.js on Node 18)
opencode auth list                      # works offline once installed (optional)
sh /var/jb/bin/sh -c 'echo shell-ok'    # shell-tool fallback shell works
command -v git && git --version          # git tool support (optional)
```

`WARN` lines for `opencode debug paths` / `opencode auth list` are informational
and may appear if the command name differs in this CLI build; the mandatory
`FAIL`-free result is the pass criterion. A full agent turn additionally needs
`opencode auth login` and network access, which are not part of the offline smoke
test.

## 11. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Process killed immediately (`Killed: 9`, exit 137) or bus error at startup | Entitlement/code-signature problem. The package ships the **device-verified minimal entitlement set**: `platform-application` + `com.apple.private.security.no-sandbox` (`runtime/entitlements.xml`). Re-sign the runtime with exactly those shipped entitlements, then retry: `sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml /var/jb/usr/lib/opencode/runtime/node`. Do **not** substitute the older allow-jit / allow-unsigned-executable-memory / disable-library-validation / dynamic-codesigning sets: those were empirically SIGKILLed on the target device (exit 137), while the 2-key set was device-proven to run the JIT+WebAssembly-enabled runtime. `ldid` is installed on the target device; it is not a package dependency. |
| Every command fails with `ReferenceError: WebAssembly is not defined` | The runtime was built with WebAssembly disabled (device-verified on the intermediate package: Node's fetch/undici needs wasm llhttp) or `OPENCODE_IOS_JITLESS=1` is set in the environment. Install the final package built from a WebAssembly+JIT-enabled runtime (check `package-report.json` → `runtime.build-profile`: "WebAssembly enabled; JIT enabled") and unset `OPENCODE_IOS_JITLESS`. |
| CLI crashes early with `EXC_BREAKPOINT`/SIGTRAP, `FatalOOM`, or `CodeRange::InitReservation` | The **node22 experimental** variant's JIT memory model is not yet compatible with iOS 16.1.1 (iOS denies `mprotect` RWX; device-verified on the v4 runtime; v6 mprotect W^X builds are still under device investigation). Install the **node18 variant** (check `package-report.json` → `variant`). Do not try to fix this with entitlement changes alone. |
| `bad option: --experimental-sqlite` / `--disable-warning` / `--use-system-ca` | A **node22** launcher/flags were used with the Node 18 runtime (or a hand-edited launcher). Node 18.20.4 rejects those flags. Reinstall the node18 package and use its installed launcher unmodified (it passes `--no-warnings` and `--max-old-space-size` only). |
| `opencode --help` crashes in `Intl.Segmenter` / `JSSegmenter::Create` (node18) | The runtime is a small-ICU Node 18 build (device-verified with a community small-ICU binary). The shipped Node 18 runtime is our own **full-ICU** build; reinstall the package from the latest green `package-rootless.yml` node18 run (check `package-report.json` → `runtime.capabilities.intl_mode: full-icu`). |
| sqlite writes appear to be lost after a crash (node18) | Expected sql.js shim behaviour: the database is persisted as a whole file with no WAL, so a hard crash can lose recent writes (see `KNOWN_LIMITATIONS.md`). Close/quit the CLI cleanly; Node 22 (experimental) uses native `node:sqlite` with WAL. |
| `opencode: native runtime not found` with a stale launcher | The package variant changed (e.g. node22 → node18). Reinstall the `.deb`; both variants install the same paths and launcher. |
| JIT shim present but no effect / `DYLD_INSERT_LIBRARIES` ignored | The shim is a jailbreak-only W^X interposer and several factors can disable injection (hardened runtime restrictions, missing `dynamic-codesigning`, other injected tweaks). Check `package-report.json` → `runtime.jitshim` for whether the shim was shipped and its audit; run with a clean environment (no `DYLD_*` overrides of your own) and report outputs. Without the shim the launcher launches normally. |
| `bad option: --use-system-ca` / `--experimental-ffi` | A custom launcher/wrapper is passing Node flags that do not exist in Node 22.9. Use the installed launcher unmodified (it passes `--experimental-sqlite`, `--disable-warning=ExperimentalWarning`, `--no-warnings`, `--max-old-space-size` only). The device jitless runtime accepts `--jitless` fine; `--use-system-ca`/`--experimental-ffi` must never be passed. |
| `/var/jb/bin/sh: not found` / `bad interpreter` when running `opencode` | Launcher was replaced or the package was edited by hand. Rootless iOS has no `/bin/sh`; the launcher must keep the `#!/var/jb/bin/sh` shebang. Reinstall the `.deb`. |
| CLI fails with `SyntaxError: Invalid regular expression: /[\p{Mark}...]/gu` or `Intl is undefined` | The runtime was built without ICU (`--with-intl=none`). Device-verified on the first no-ICU runtime build; the CLI bundle requires Intl/Unicode property escapes and `Intl.Segmenter`. Reinstall a package built from a full-ICU (`--with-intl=full-icu`) runtime — packaging CI rejects no-ICU runtime artifacts, and the bundle must not be patched. |
| Shell tool calls fail with `sh: not found` / `/bin/sh: No such file or directory` | The CLI spawned a shell without the rootless paths. Run the installed launcher (`/var/jb/usr/bin/opencode`), which prepends `/var/jb/bin:/var/jb/usr/bin` to `PATH`; do not invoke the node runtime directly. |
| `git: command not found` in git tool calls | `git` is not installed by default on the rootless bootstrap (only `Recommends: git`). `sudo apt-get install -y git` (or install it from Sileo) and retry. |
| `cannot execute binary file` / `Exec format error` | Wrong binary (e.g. a macOS Node or desktop build). Reinstall this package; never mix in a macOS `node`. |
| `opencode: native runtime not found` | Incomplete extraction. Reinstall the `.deb`; the launcher prints the expected path. |
| `opencode: CLI bundle not found` | Incomplete extraction. Reinstall the `.deb`. |
| Out-of-memory / jetsam kill during a large session | Lower the heap: `OPENCODE_IOS_MAX_OLD_SPACE_MB=1024 opencode`, or set it in `~/.profile`. |
| Interactive TUI garbled or terminal panes unavailable | Expected PTY fallback; use `opencode run ...`/`--help`. Shell tool calls use the rootless dash via `PATH`. |
| File changes are not picked up live | Expected watcher fallback (polling/none). Re-run the command or use a watch-free workflow. |
| `firmware` dependency error from `dpkg` | Rootless bootstrap package is missing/broken; repair the bootstrap via Sileo rather than `--force-depends`. |
| No provider requests / TLS errors | Check network and certificate trust; agent calls require internet and configured auth. Basic device HTTPS/TLS and `curl` were verified on the target device; proxied/managed networks remain untested. |

Collect diagnostics for bug reports:

```sh
uname -a
dpkg -s opencode
/var/jb/usr/lib/opencode/runtime/node -p process.versions.node   # runtime variant
opencode --version; echo "exit=$?"
sh /var/jb/usr/share/doc/opencode/device-smoke.sh
```

## 12. Reporting a device result

Device verification results are recorded in
[`VERIFICATION.md`](VERIFICATION.md) under **Device verification results**, which
contains the device identity table and a per-test evidence template. The CI
reports (`port-verification`, `package-report.json`) stay runner-only evidence and
must not be presented as device proof.

To move the port out of `UNVERIFIED ON DEVICE`, open an issue with:

1. Device model, iOS version, jailbreak (e.g. "iPhone SE2, iOS 16.1.1, Dopamine rootless").
2. The exact package version, `.deb` SHA-256 (from `SHA256SUMS`) **and variant**
   (`package-report.json` → `variant`, or
   `/var/jb/usr/lib/opencode/runtime/node -p process.versions.node`).
3. Full output of `sh /var/jb/usr/share/doc/opencode/device-smoke.sh`.
4. Which device tests in [`VERIFICATION.md`](VERIFICATION.md) passed/failed.
5. Whether `opencode auth login` + a minimal `opencode run` worked.

Do not include API keys, tokens, or personal project data in reports.
