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
| Device | iPhone SE (2nd generation), arm64 |
| iOS | 16.1.1 (20B101) |
| Jailbreak | Dopamine (rootless), `/var/jb` prefix |
| Package | `OpenCode-iOS-rootless.deb` (`Architecture: iphoneos-arm64`) |
| Installed binary | `/var/jb/usr/bin/opencode` |
| Runtime / CLI / assets | `/var/jb/usr/lib/opencode/{runtime,cli}` |
| Docs | `/var/jb/usr/share/doc/opencode/` |

Node.js 22.9.0 is older than the Node version upstream OpenCode normally targets;
see [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 1. Requirements

- Dopamine **rootless** jailbreak (a rootless bootstrap that mounts `/var/jb`).
  Rootful jailbreaks and other prefixes are **not** supported by this package.
- A terminal: NewTerm 3 or SSH. `dpkg` from the rootless bootstrap
  (`/var/jb/usr/bin/dpkg`).
- ~150 MB free under `/var/jb` for the runtime, CLI bundle and assets
  (`Installed-Size` in the package metadata is authoritative).
- Internet access only for **agent usage** (provider API calls). Installation,
  `--version`, `--help` and `auth list` are offline.

## 2. Get the package

Download the **`OpenCode-iOS-rootless` artifact** from the latest successful
`package-rootless.yml` run:

<https://github.com/Justintunsday/opencode-ios/actions/workflows/package-rootless.yml>

The artifact contains:

| File | Purpose |
| --- | --- |
| `OpenCode-iOS-rootless.deb` | the installable package |
| `SHA256SUMS` | SHA-256 of the `.deb` |
| `package-report.json` | contents manifest, Mach-O audit, sizes, sha256s, source run ids |

Current pinned version: OpenCode **2.2.5** (package version `2.2.5-1`, see
`UPSTREAM.lock`). The exact SHA-256 of the published `.deb` is recorded in
`SHA256SUMS` and inside `package-report.json`.

## 3. Transfer the package to the device

Pick one:

- **AirDrop / Filza:** AirDrop the `.deb` to the iPhone, then use Filza to move it
  to `/var/mobile/Documents/`.
- **SSH/SFTP** (OpenSSH from the rootless bootstrap, on the same Wi-Fi):

  ```sh
  scp OpenCode-iOS-rootless.deb SHA256SUMS mobile@<iphone-ip>:/var/mobile/Documents/
  ```

- **NewTerm on-device download** (`curl` from the rootless bootstrap) into
  `/var/mobile/Documents/` if you have the artifact URL.

## 4. Verify integrity on the device

```sh
cd /var/mobile/Documents
sha256sum -c SHA256SUMS
# expected: OpenCode-iOS-rootless.deb: OK
dpkg-deb --info OpenCode-iOS-rootless.deb | head -n 20
# expected: Package: opencode, Version: 2.2.5-1, Architecture: iphoneos-arm64,
#           Depends: firmware (>= 15.0)
```

If `sha256sum` is unavailable, use `shasum -a 256 OpenCode-iOS-rootless.deb` and
compare with the value in `SHA256SUMS`.

## 5. Install

```sh
sudo dpkg -i /var/mobile/Documents/OpenCode-iOS-rootless.deb
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
opencode --help
```

The launcher (`/var/jb/usr/bin/opencode`, POSIX `sh`) exports
`OPENCODE_NODE_ASSETS_DIR` and `OPENCODE_IOS=1` and executes:

```sh
/var/jb/usr/lib/opencode/runtime/node \
  --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings \
  --max-old-space-size=1536 \
  /var/jb/usr/lib/opencode/cli/opencode.mjs "$@"
```

`--experimental-sqlite` is required by `node:sqlite` on Node 22.9 and is not a
bug. `/var/jb/usr/bin` is normally already on `PATH`; if `opencode` is not found,
add `export PATH="/var/jb/usr/bin:$PATH"` to `~/.profile`.

The v1 runtime is **built with V8 JIT disabled** (`--v8-options=--jitless`) and
WebAssembly disabled for reliability on a rootless jailbreak. It does not need a
JIT/executable-memory entitlement to start, so expect interpreter-level
performance rather than desktop speed. Escape hatches (documented in
`KNOWN_LIMITATIONS.md`):

```sh
OPENCODE_IOS_JITLESS=1 opencode --version     # explicit parity with future builds
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
`~/.local/share/opencode/` and `~/.cache/opencode/`. On a jailbroken device the
user home is `/var/mobile`.

> API keys are user data. Do not commit them, do not paste them into issues, and
> do not add them to the launcher or package.

## 8. Project usage

```sh
cd /var/mobile/Documents/my-project
opencode                 # interactive TUI (see PTY caveat below)
opencode --help          # commands and flags
opencode run "summarise this repository"   # headless, requires auth+network
```

TUI/terminal caveats: interactive PTY panes and native file watchers have no
iPhoneOS builds, so shell tool calls use pipe-based `child_process` fallback and
file-watch features degrade to polling/none. Headless `run` mode is the more
reliable path. See [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 9. Upgrade / uninstall

```sh
# upgrade in place (config and sessions are preserved)
sudo dpkg -i /var/mobile/Documents/OpenCode-iOS-rootless.deb

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
| CLI bundle present | `OK   CLI bundle present` |
| launcher executable | `OK   launcher present and executable` |
| `opencode --version` | exit 0 and the OpenCode version (2.2.5) printed |
| `opencode --help` | exit 0 with a usage block |
| argument forwarding | `OK   launcher forwards CLI arguments` |
| overall | `DEVICE SMOKE TEST: PASS (offline checks only; model connectivity not tested)` |

Manual equivalent (what proves success):

```sh
opencode --version; echo "exit=$?"      # exit=0 and a version string
opencode --help;    echo "exit=$?"      # exit=0 and usage text
opencode debug paths                    # config/data paths under /var/mobile (optional)
opencode auth list                      # works offline once installed (optional)
```

`WARN` lines for `opencode debug paths` / `opencode auth list` are informational
and may appear if the command name differs in this CLI build; the mandatory
`FAIL`-free result is the pass criterion. A full agent turn additionally needs
`opencode auth login` and network access, which are not part of the offline smoke
test.

## 11. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Process killed immediately (`Killed: 9`, exit 137) or bus error at startup | Code signature / executable-memory misbehaviour after transfer. Re-sign the runtime with the shipped entitlements: `sudo ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.xml /var/jb/usr/lib/opencode/runtime/node`, then retry. `ldid` is part of the rootless bootstrap; it is not a package dependency. |
| `bad option: --use-system-ca` / `--experimental-ffi` | A custom launcher/wrapper is passing Node flags that do not exist in Node 22.9. Use the installed launcher unmodified (it passes `--experimental-sqlite`, `--disable-warning=ExperimentalWarning`, `--no-warnings` only). |
| `cannot execute binary file` / `Exec format error` | Wrong binary (e.g. a macOS Node or desktop build). Reinstall this package; never mix in a macOS `node`. |
| `opencode: native runtime not found` | Incomplete extraction. Reinstall the `.deb`; the launcher prints the expected path. |
| `opencode: CLI bundle not found` | Incomplete extraction. Reinstall the `.deb`. |
| Out-of-memory / jetsam kill during a large session | Lower the heap: `OPENCODE_IOS_MAX_OLD_SPACE_MB=1024 opencode`, or set it in `~/.profile`. |
| Interactive TUI garbled or terminal panes unavailable | Expected PTY fallback; use `opencode run ...`/`--help`. |
| File changes are not picked up live | Expected watcher fallback (polling/none). Re-run the command or use a watch-free workflow. |
| `firmware` dependency error from `dpkg` | Rootless bootstrap package is missing/broken; repair the bootstrap via Sileo rather than `--force-depends`. |
| No provider requests / TLS errors | Check network and certificate trust; agent calls require internet and configured auth. |

Collect diagnostics for bug reports:

```sh
uname -a
dpkg -s opencode
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
2. The exact package version and `.deb` SHA-256 (from `SHA256SUMS`).
3. Full output of `sh /var/jb/usr/share/doc/opencode/device-smoke.sh`.
4. Which device tests in [`VERIFICATION.md`](VERIFICATION.md) passed/failed.
5. Whether `opencode auth login` + a minimal `opencode run` worked.

Do not include API keys, tokens, or personal project data in reports.
