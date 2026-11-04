# OpenCode iOS

**Run OpenCode v2 on a jailbroken iPhone — native arm64, real terminal UI.**

This is an independent iPhoneOS port of [OpenCode](https://github.com/sst/opencode) for
rootless jailbroken devices (`/var/jb`, Dopamine-style). It runs the upstream CLI on a
native arm64 Node.js runtime. The experimental line renders the actual OpenTUI
full-screen interface inside a real terminal, not a line-based fallback.

The project currently ships two lines:

| Line | Package | Runtime | What you get |
| --- | --- | --- | --- |
| **Stable** | `v2.2.5-ios.5` | Embedded Node.js 22.9.0 | Line-based REPL, headless `opencode run`, CLI |
| **Experimental** | `2.2.5-5` / `node26test.8` | Separate `node26` `26.13.0-2` package | Real full-screen OpenTUI TUI, mobile layout, flicker fix |

Both are built and packaged as Debian packages for `iphoneos-arm64`. The experimental
package depends on the standalone [node26 runtime](https://github.com/Justintunsday/nodejs26-ios)
instead of embedding a second Node build.

## Verified on real hardware

The packages below were installed and exercised on an actual device, not just CI:

| | |
| --- | --- |
| Device | iPhone SE 2 (`iPhone12,8`), iOS 16.1.1, Dopamine rootless |
| Terminal | NewTerm 3 and SSH PTY; rendering QA used **EverTerm 1.5-2** |
| Stable package | `v2.2.5-ios.5` — device-verified install, REPL, CLI and headless runs |
| Experimental package | `2.2.5-5` / `node26test.8` — [run 41649519712](https://github.com/Justintunsday/opencode-ios/actions/runs/41649519712), full TUI, resize/orientation, three-turn real PTY session, terminal restore and `/exit` |
| POSIX runtime matrix | **21 PASS / 0 UNSUPPORTED / 0 FAIL** on device with `node26` `26.13.0-2` |

Other iPhone models and iOS versions have not been validated. CI cannot execute
iPhoneOS binaries, so "CI green" only means the packages assembled and passed static
checks; the device results above are the real acceptance evidence.

## What works

- **A real TUI.** The full-screen OpenTUI interface opens in a real TTY, with sessions,
  model selection, tool activity and streaming responses.
- **Mobile-first layout.** The interface reflows for narrow screens and on-screen
  keyboards. The minimum usable size is 24×8; 40×12 or larger is recommended. Rotation
  and keyboard changes keep unsent drafts.
- **No full-screen flashing on EverTerm.** iOS builds no longer emit DECSET 2026
  synchronized-output frames, which EverTerm rendered as a full-screen present. The
  user A/B-confirmed the fix, and the shipped frame stream contains zero sync frames.
- **Flicker-free rendering defaults.** UI animations are off by default and the
  cursor is a non-blinking bar; explicit user preferences are preserved.
- **POSIX compatibility built in.** The `node26` launcher injects a compatibility dylib,
  so unnamed POSIX semaphores and System V shared memory work for CLI tools, scripts and
  native extensions.
- **Optional root mode.** A root-owned server can run OpenCode tools with root
  privileges while the TUI stays as your normal user. This is opt-in and documented
  separately — see [Root service](docs/ROOT_SERVICE.md).

## Requirements

- A jailbroken, **arm64** iPhone with a **rootless** bootstrap (`/var/jb`), e.g.
  Dopamine. Rootful jailbreaks and other prefixes are not packaged.
- Procursus `dpkg` from the bootstrap.
- iOS 15.0+ deployment target; the tested device is iOS 16.1.1.
- A real terminal: NewTerm 3 or SSH (the TUI needs a TTY).
- ~150 MB free under `/var/jb`.
- Optional: `git` (`sudo apt-get install -y git`) for git tool support.
- Your own model provider account or API key.

## Install the experimental TUI (node26test.8)

Download the package artifact to a computer where GitHub CLI is logged in:

```sh
gh run download 41649519712 -R Justintunsday/opencode-ios \
  -n opencode-ios-rootless-node26 -D opencode-ios
```

Copy the whole directory to the phone, then install both debs:

```sh
cd opencode-ios
sha256sum -c SHA256SUMS
sudo dpkg -i node26_26.13.0-2_iphoneos-arm64.deb OpenCode-iOS-rootless-node26.deb
```

Check the install and start the TUI:

```sh
node --version        # v26.13.0
node -p 'process.platform'   # ios
opencode --version
cd /var/mobile/Documents
opencode
```

Notes:

- If you still have the old prototype `nodejs26-ios` packages installed, remove them
  first. The public command is now `node`.
- Configuration, credentials and sessions live in your home directory and survive
  package upgrades.
- For the stable Node 22 line, use the artifacts from the
  [stable release](https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5).
- Detailed upgrade, rollback and uninstall steps are in [docs/INSTALL.md](docs/INSTALL.md).

## Using the TUI

On first launch, run `/connect` to set up a model provider, then `/models` to pick a
model. You can open the interface and browse local CLI features even before a real
provider is configured.

| Action | Key / command |
| --- | --- |
| Send message | Enter |
| Insert newline | Ctrl+J (Shift+Enter in terminals with an extended keyboard) |
| Search / command menu | `/` then arrows + Enter |
| Close menu / cancel | Esc |
| Change model | `/models` |
| Session history / new session | `/sessions` / `/new` |
| Quit | `/exit` then Enter |

The mobile layout drops the large startup logo, keeps status and common commands on the
home screen, and pins the composer to the bottom. Narrow conversations use a single
column with tighter margins.

These are native OpenTUI test frames rendered with desktop fonts (not phone screenshots).
They show the 40×12 layout before and after the mobile pass:

| Before: the large logo pushed the composer off-screen | After: input and hints stay visible |
| --- | --- |
| ![Old 40×12 layout](docs/images/mobile-before-40x12.png) | ![Mobile 40×12 layout](docs/images/mobile-after-40x12.png) |

## Rendering on iOS

iOS limits the renderer to 20 FPS and coalesces updates. The port also suppresses DECSET
2026 synchronized-output frames, because the tested terminal (EverTerm 1.5-2) treats each
synchronized block as a full-screen present. That was the cause of the old full-screen
flash; the fix is confirmed by user A/B testing and by frame capture (0/0 sync begin/end,
zero output while idle).

A few practical notes:

- After upgrading, `/exit` the old TUI first, then start `opencode` again so the new code
  is loaded.
- If you see `EADDRINUSE`, start with a private server: `opencode --standalone`. Use a
  different service port per account.
- Never remove `--single-threaded` from the launcher: iOS JIT page-permission changes are
  process-wide, so background V8 execution can race them.
- Keep the renderer at `/var/jb/usr/lib/opencode/cli/assets` with its original signature.
- Running outside a TTY prints guidance and exits with status 1. For scripts, use
  `opencode run --standalone "your task"`.

Useful commands:

```sh
opencode --version
opencode models --standalone
opencode debug paths
opencode run --standalone "summarize this project"
```

## Optional: run tools as root

If you want OpenCode's shell/tools to run as root, install the optional root-owned
server (see [docs/ROOT_SERVICE.md](docs/ROOT_SERVICE.md)). It listens only on
`127.0.0.1` with HTTP Basic authentication, while the TUI stays as your normal user.

```sh
# one-time install, as root
sudo /var/jb/bin/sh /path/to/packaging/root-service/install-root-service.sh

opencode-root                         # TUI connected to the root server
sudo opencode-root-service status     # stop | start | restart
```

This mode deliberately creates a local privilege-escalation path and is **not**
recommended on devices you don't fully trust. The mobile process needs to read the
service password, so any local process running as `mobile` that can read that file could
also connect to the root server.

## Known limitations

The port targets a specific device and is honest about what is missing:

- Node user `worker_threads` are unsupported. iOS JIT/executable-memory changes are
  process-wide.
- Tree-sitter background workers are disabled on iOS; code blocks fall back to plain
  text.
- The runtime package does not include npm/npx.
- Interactive terminal panes (native PTY), clipboard integration, Ghostty panes and
  audio are not fully validated.
- `git` is not installed by default; install it separately if you need git tools.
- Large sessions can hit the iPhone SE 2's memory limit. The launcher caps V8 old space
  at 1536 MiB; override with `OPENCODE_IOS_MAX_OLD_SPACE_MB`.
- Arabic/RTL text keeps logical order; final shaping depends on the terminal.
- Real provider auth, billing and network behaviour are the provider's domain and are
  not covered by our mock-provider tests.

The full, itemized list is in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).
The Node runtime's JIT/wasm/POSIX results are in the
[nodejs26-ios device report](https://github.com/Justintunsday/nodejs26-ios/blob/main/docs/POSIX_JIT_WASM_DEVICE_RESULTS.md)
(21 PASS, 0 unsupported).

## Development

The upstream revision is pinned in [UPSTREAM.lock](UPSTREAM.lock); iOS-specific changes
are maintained as patches. The Node.js runtime lives in a separate repository,
[nodejs26-ios](https://github.com/Justintunsday/nodejs26-ios). UI work builds on the
existing Solid/OpenTUI architecture; the design reference is
[pageton/tui-design-skill](https://github.com/pageton/tui-design-skill).

| Workflow | Purpose |
| --- | --- |
| `build-opencode.yml` | Build the JS CLI and mobile TUI, run host tests |
| `build-opentui-ios.yml` | Build and sign the iPhoneOS native renderer |
| `package-rootless-node26.yml` | Assemble the OpenCode deb that depends on the external Node runtime |
| `package-rootless.yml` | Build the stable Node 22 release line |

```sh
gh workflow run build-opencode.yml -R Justintunsday/opencode-ios -f variant=node26
```

Acceptance covers layout snapshots, basic input, paste, Unicode, resize/draft retention,
idle output, frame synchronization and terminal restore, followed by a real iPhone PTY
run. Build details are in [docs/OPENCODE_BUILD.md](docs/OPENCODE_BUILD.md); renderer
requirements are in [docs/OPENTUI_IOS.md](docs/OPENTUI_IOS.md).

## Credits and license

This is an independent port. OpenCode, Node.js and OpenTUI remain the property of their
respective authors and are distributed under their original licenses. See [LICENSE](LICENSE)
and [NOTICE](NOTICE) for details.
