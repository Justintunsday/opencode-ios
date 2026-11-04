# OpenCode iOS

## Builds

| | Stable | Experimental |
| --- | --- | --- |
| Version | `v2.2.5-ios.5` | `2.2.5-5` / `node26test.8` |
| Node.js | Embedded 22.9.0 | Separate `node26` `26.13.0-2` package |
| Interface | Line-based REPL | Real full-screen OpenTUI TUI |
| Best for | Minimal, proven path | Full OpenCode TUI on a phone |
| Status | Device-verified | Device-verified on iPhone SE 2 / iOS 16.1.1 |

## Requirements

- A **jailbroken, arm64 iPhone** with a **rootless** bootstrap (`/var/jb`), such as
  Dopamine. Rootful jailbreaks and other prefixes are not supported.
- Procursus `dpkg` and a shell from that bootstrap.
- iOS 15.0 or newer; the device used for all testing is iOS 16.1.1.
- A real terminal — NewTerm 3 or an SSH session. The TUI needs a TTY.
- Around 150 MB of free space under `/var/jb`.
- Your own model provider account or API key.
- Optional: `git`, if you want the agent to work with git repositories
  (`sudo apt-get install -y git`).

## Install the TUI build

Grab the package artifact on a computer with GitHub CLI logged in:

```sh
gh run download 41649519712 -R Justintunsday/opencode-ios \
  -n opencode-ios-rootless-node26 -D opencode-ios
```

Copy that directory to the phone, then install the runtime and the app:

```sh
cd opencode-ios
sha256sum -c SHA256SUMS
sudo dpkg -i node26_26.13.0-2_iphoneos-arm64.deb OpenCode-iOS-rootless-node26.deb
```

Confirm everything landed:

```sh
node --version                 # v26.13.0
node -p 'process.platform'     # ios
opencode --version             # opencode2-node v2.2.5
```

Then open a project and start:

```sh
cd /var/mobile/Documents
opencode
```

Two things worth knowing before you start:

- If an old prototype `nodejs26-ios` package is still installed, remove it first. The
  public command is now simply `node`.
- Config, credentials and sessions live in your home directory. Package upgrades leave
  them alone.

If you prefer the stable build, install it from the
[`v2.2.5-ios.5` release](https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5).
The detailed install, upgrade and uninstall procedures are in
[docs/INSTALL.md](docs/INSTALL.md).

## Your first five minutes

On first launch, run `/connect` to point OpenCode at your model provider, then `/models`
to choose a model. You can explore the interface and local CLI features before a provider
is configured; only actual model calls need one.

The essentials:

| What you want | What to press |
| --- | --- |
| Send a message | Enter |
| Add a line without sending | Ctrl+J (Shift+Enter on terminals that send it) |
| Open the command menu | `/` |
| Close a menu or cancel | Esc |
| Switch models | `/models` |
| Browse or create sessions | `/sessions`, `/new` |
| Leave | `/exit` |

The home screen hides the large startup logo on small screens, keeps status and common
commands visible, and anchors the composer to the bottom. Long conversations use a single
column so text stays readable at phone width. Rotating the device or opening the keyboard
reflows the layout without throwing away an unsent draft.

## What it looks like

These are native OpenTUI test frames rendered with desktop fonts, not phone screenshots.
They show the same 40×12 viewport before and after the mobile layout pass:

| Before: the logo pushes the composer off-screen | After: input and hints remain visible |
| --- | --- |
| ![Old 40×12 layout](docs/images/mobile-before-40x12.png) | ![Mobile 40×12 layout](docs/images/mobile-after-40x12.png) |

The terminal UI is deliberately quiet. Animations are off by default, the cursor is a
non-blinking bar, and on EverTerm the renderer no longer emits the synchronized-output
frames that used to make the whole screen flash. The frame stream now carries zero sync
frames, and idle time produces zero output.

## What works today

- **A genuine terminal UI.** Sessions, streaming responses, tool calls, model selection
  and history — all inside the real OpenTUI renderer.
- **A layout built for a phone.** It stays usable down to 24×8 columns; 40×12 or larger
  is comfortable. Drafts survive rotation and keyboard changes.
- **Flicker-free rendering on EverTerm.** The iOS build suppresses DECSET 2026
  synchronized-output frames, which EverTerm treated as a full-screen present. The fix
  was confirmed both by user A/B testing and by captured frame data.
- **POSIX calls that used to be missing.** The `node26` runtime ships a compatibility
  dylib that implements unnamed POSIX semaphores and System V shared memory; the device
  matrix is 21 PASS / 0 unsupported / 0 fail.
- **An optional root mode.** A separate, opt-in root-owned server can run tools with root
  privileges while the TUI keeps running as your normal user.

## What still hurts

The port is honest about its edges. The complete list is in
[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md); the short version:

- Node's user-facing `worker_threads` are not supported. iOS page-permission changes are
  process-wide, so background isolates cannot safely run JIT code.
- Interactive terminal panes fall back to pipes; there is no native PTY.
- File watching uses polling instead of a native watcher.
- Tree-sitter workers are disabled; code blocks render as plain text.
- npm and npx are not included.
- `git` is not installed by default.
- Large sessions can hit the iPhone SE 2's memory ceiling. The launcher caps V8 old-space
  at 1536 MiB; raise it with `OPENCODE_IOS_MAX_OLD_SPACE_MB` if you know what you are
  doing.
- Clipboard integration, Ghostty panes and audio are not fully validated.
- Arabic and other RTL text keep logical order; final shaping depends on the terminal.
- Real provider authentication, billing and network behaviour are outside this project's
  test coverage.

## Optional: run tools as root

Some work — installing packages, touching system paths, managing services — needs root.
Rather than making the whole app root, this repository offers a small opt-in service: a
root-owned OpenCode server on `127.0.0.1` with HTTP Basic auth, and a normal-user TUI
client (`opencode-root`) that talks to it.

```sh
# one-time setup, as root
sudo /var/jb/bin/sh /path/to/packaging/root-service/install-root-service.sh

opencode-root                        # TUI backed by the root server
sudo opencode-root-service status    # stop | start | restart
```

It is opt-in, it is not enabled by the package, and it deliberately creates a local
privilege-escalation path. The password has to be readable by the mobile user, which
means any local process running as `mobile` that can read it could also connect. Use it
only on a device you control. Full details and the security model are in
[docs/ROOT_SERVICE.md](docs/ROOT_SERVICE.md).

## Under the hood

Three pieces make this work.

**The CLI** is upstream OpenCode, pinned in [UPSTREAM.lock](UPSTREAM.lock) and maintained
with a patch series rather than a fork of every file. The iOS changes are small and
targeted: path/bootstrap assumptions, terminal detection, the mobile layout and the
renderer integration.

**The runtime** is a separate Node.js 26.13.0 port in
[nodejs26-ios](https://github.com/Justintunsday/nodejs26-ios). It uses an mprotect-based
RW→RX model with the `--single-threaded` flag, a minimal two-key entitlement set, libffi
callbacks for `node:ffi`, and the POSIX compatibility shim. That repository also holds the
JIT/wasm/POSIX device evidence.

**The renderer** is `@opentui/core`, cross-compiled and signed for iPhoneOS arm64. It
keeps the original signature, caps output at 20 FPS, removes the DECSET 2026 envelope and
implements the narrow-screen layout. Build instructions and constraints are in
[docs/OPENTUI_IOS.md](docs/OPENTUI_IOS.md).

Packaging is deliberately boring: plain rootless Debian packages, exact-version
dependencies, SHA-256 inventories and no self-updater. The OpenCode package depends on the
runtime package instead of shipping a second Node binary.

## Troubleshooting

**`opencode: command not found`** — make sure `/var/jb/usr/bin` is on your `PATH`, or run
`/var/jb/usr/bin/opencode` directly.

**`EADDRINUSE` when starting** — a stale background service is holding the port. Run
`opencode --standalone` for a private server, or exit the old session first.

**The screen flashes on every change** — update to the `node26test.8` build. Older
releases wrapped frames in DECSET 2026, which EverTerm presents as a full-screen flash.

**`dpkg` reports an unsatisfied node26 dependency** — install the matching runtime deb
from the same artifact directory. The OpenCode package requires the exact `26.13.0-2`
version.

**I upgraded but still see the old behavior** — exit the running TUI completely, then
start `opencode` again. The old process keeps the old code loaded.

**A script hangs or behaves oddly outside a terminal** — non-TTY runs are intentionally
unsupported; they print guidance and exit 1. Use `opencode run --standalone "..."` for
scripting.

**The app gets killed during a huge session** — that is the phone's memory pressure, not
a crash in the port. Try a smaller session or raise `OPENCODE_IOS_MAX_OLD_SPACE_MB`
carefully.

## Building it yourself

The upstream revision is pinned, patches live in the repository, and the runtime is built
in its own repository. Hosted CI runners cannot execute iPhoneOS binaries, so CI proves
assembly and static properties; device acceptance is a separate, documented step.

| Workflow | What it builds |
| --- | --- |
| `build-opencode.yml` | The JS CLI and mobile TUI, plus host tests |
| `build-opentui-ios.yml` | The signed iPhoneOS native renderer |
| `package-rootless-node26.yml` | The OpenCode deb that depends on the external Node runtime |
| `package-rootless.yml` | The stable Node 22 release line |

```sh
gh workflow run build-opencode.yml -R Justintunsday/opencode-ios -f variant=node26
```

Architecture notes are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); build details are
in [docs/OPENCODE_BUILD.md](docs/OPENCODE_BUILD.md). The UI follows the existing
Solid/OpenTUI structure, with visual direction from
[pageton/tui-design-skill](https://github.com/pageton/tui-design-skill).

## Credits

This is an independent port. OpenCode, Node.js and OpenTUI belong to their respective
authors and keep their original licenses. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for
the details.
