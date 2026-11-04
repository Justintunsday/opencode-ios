# OpenCode iOS

## Builds

| | Stable | Experimental |
| --- | --- | --- |
| Version | `v2.2.5-ios.5` | `2.2.5-5` / `node26test.8` |
| Node.js | Embedded 22.9.0 | Separate `node26` `26.13.0-2` package |
| Interface | Line-based REPL | Full-screen OpenTUI terminal interface |
| Intended use | Stable, documented workflow | Full terminal interface on a phone |
| Status | Device-verified | Device-verified on iPhone SE 2 / iOS 16.1.1 |

## Requirements

- A **jailbroken, arm64 iPhone** with a **rootless** bootstrap (`/var/jb`), such as
  Dopamine. Rootful jailbreaks and other prefixes are not supported.
- Procursus `dpkg` and a shell from that bootstrap.
- iOS 15.0 or newer; the device used for testing runs iOS 16.1.1.
- A terminal application — NewTerm 3 or an SSH session. The terminal interface requires
  a TTY.
- Approximately 150 MB of free space under `/var/jb`.
- A model provider account or API key.
- Optional: `git`, if the agent is expected to work with git repositories
  (`sudo apt-get install -y git`).

## Install the terminal interface build

Download the package artifact from a computer with GitHub CLI authenticated:

```sh
gh run download 41649519712 -R Justintunsday/opencode-ios \
  -n opencode-ios-rootless-node26 -D opencode-ios
```

Transfer the directory to the device, then install the runtime and the application:

```sh
cd opencode-ios
sha256sum -c SHA256SUMS
sudo dpkg -i node26_26.13.0-2_iphoneos-arm64.deb OpenCode-iOS-rootless-node26.deb
```

Verify the installation:

```sh
node --version                 # v26.13.0
node -p 'process.platform'     # ios
opencode --version             # opencode2-node v2.2.5
```

Open a project and start the application:

```sh
cd /var/mobile/Documents
opencode
```

Notes:

- If an old prototype `nodejs26-ios` package is installed, remove it first. The public
  command is now `node`.
- Configuration, credentials and sessions are stored in the home directory and are
  preserved across package upgrades.

To use the stable build, install it from the
[`v2.2.5-ios.5` release](https://github.com/Justintunsday/opencode-ios/releases/tag/v2.2.5-ios.5).
Detailed installation, upgrade and uninstallation procedures are documented in
[docs/INSTALL.md](docs/INSTALL.md).

## First run

On first launch, run `/connect` to configure a model provider, then `/models` to select
a model. The interface and local CLI features are available before a provider is
configured; only model requests require one.

Common actions:

| Action | Key or command |
| --- | --- |
| Send a message | Enter |
| Insert a newline without sending | Ctrl+J (Shift+Enter on terminals that send it) |
| Open the command menu | `/` |
| Close a menu or cancel | Esc |
| Switch models | `/models` |
| Browse or create sessions | `/sessions`, `/new` |
| Quit | `/exit` |

The home screen omits the large startup logo on small displays, keeps status and common
commands visible, and anchors the composer at the bottom. Long conversations use a single
column so that text remains readable at phone width. Rotating the device or opening the
keyboard reflows the layout without discarding an unsent draft.

## Interface layout

The images below are native OpenTUI test frames rendered with desktop fonts; they are not
device screenshots. Both use a 40×12 viewport and show the layout before and after the
mobile pass:

| Before: the logo pushes the composer off-screen | After: input and hints remain visible |
| --- | --- |
| ![Old 40×12 layout](docs/images/mobile-before-40x12.png) | ![Mobile 40×12 layout](docs/images/mobile-after-40x12.png) |

The interface is intentionally minimal. Animations are disabled by default, the cursor is
a non-blinking bar, and on EverTerm the renderer no longer emits the synchronized-output
frames that previously caused full-screen flashing. The current frame stream contains no
synchronization frames, and idle periods produce no output.

## Feature status

- **Full terminal interface.** Sessions, streaming responses, tool calls, model selection
  and history are rendered by the OpenTUI renderer.
- **Phone-oriented layout.** The interface remains usable at 24×8 columns; 40×12 or
  larger is recommended. Drafts survive rotation and keyboard changes.
- **Flicker-free rendering on EverTerm.** The iOS build suppresses DECSET 2026
  synchronized-output frames, which EverTerm rendered as a full-screen present. The
  change was confirmed by user A/B testing and by captured frame data.
- **POSIX compatibility.** The `node26` runtime includes a compatibility dylib that
  implements unnamed POSIX semaphores and System V shared memory. The device matrix
  reports 21 PASS / 0 unsupported / 0 fail.
- **Optional root execution.** A separate, opt-in root-owned server can execute tools
  with root privileges while the terminal interface continues to run as the normal user.

## Limitations

A complete list is available in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md);
the principal items are:

- Node user-facing `worker_threads` are not supported. iOS page-permission changes apply
  process-wide, so background isolates cannot safely execute JIT code.
- Interactive terminal panes fall back to pipes; a native PTY is not available.
- File watching uses polling instead of a native watcher.
- Tree-sitter workers are disabled; code blocks are rendered as plain text.
- npm and npx are not included.
- `git` is not installed by default.
- Large sessions can exceed the memory limit of the iPhone SE 2. The launcher caps V8
  old-space at 1536 MiB; this value can be adjusted with
  `OPENCODE_IOS_MAX_OLD_SPACE_MB` with caution.
- Clipboard integration, Ghostty panes and audio have not been fully validated.
- Arabic and other RTL text retain logical order; final shaping depends on the terminal.
- Provider authentication, billing and network behaviour are outside the scope of this
  project's test coverage.

## Optional root execution

Certain operations — installing packages, modifying system paths, managing services —
require root privileges. As an alternative to running the entire application as root,
this repository provides an optional root-owned server on `127.0.0.1` with HTTP Basic
authentication, and a normal-user terminal client (`opencode-root`) that connects to it.

```sh
# one-time setup, as root
sudo /var/jb/bin/sh /path/to/packaging/root-service/install-root-service.sh

opencode-root                        # terminal client backed by the root server
sudo opencode-root-service status    # stop | start | restart
```

The feature is optional, is not enabled by the package, and introduces a local
privilege-escalation path. The password must be readable by the mobile user, which means
that any local process running as `mobile` that can read the password file could also
connect to the root server. Use this feature only on a device under your control. Full
details and the security model are documented in
[docs/ROOT_SERVICE.md](docs/ROOT_SERVICE.md).

## Architecture

The implementation consists of three components.

**The CLI** is upstream OpenCode, pinned in [UPSTREAM.lock](UPSTREAM.lock) and maintained
with a patch series rather than a complete fork. The iOS-specific changes are limited to
path and bootstrap assumptions, terminal detection, the mobile layout and renderer
integration.

**The runtime** is a separate Node.js 26.13.0 port in
[nodejs26-ios](https://github.com/Justintunsday/nodejs26-ios). It uses an mprotect-based
RW→RX model with the `--single-threaded` flag, a minimal two-key entitlement set, libffi
callbacks for `node:ffi`, and the POSIX compatibility shim. That repository also contains
the JIT, WebAssembly and POSIX device evidence.

**The renderer** is `@opentui/core`, cross-compiled and signed for iPhoneOS arm64. It
retains the original signature, limits output to 20 FPS, removes the DECSET 2026 envelope
and implements the narrow-screen layout. Build instructions and constraints are documented
in [docs/OPENTUI_IOS.md](docs/OPENTUI_IOS.md).

Packaging is intentionally straightforward: standard rootless Debian packages,
exact-version dependencies, SHA-256 inventories and no self-updater. The OpenCode package
depends on the runtime package rather than embedding a second Node binary.

## Troubleshooting

**`opencode: command not found`** — ensure that `/var/jb/usr/bin` is present in `PATH`, or
invoke `/var/jb/usr/bin/opencode` directly.

**`EADDRINUSE` when starting** — a background service is holding the port. Run
`opencode --standalone` to start a private server, or terminate the previous session
first.

**The screen flashes on every change** — update to the `node26test.8` build. Older
releases wrapped frames in DECSET 2026, which EverTerm presents as a full-screen flash.

**`dpkg` reports an unsatisfied node26 dependency** — install the matching runtime deb
from the same artifact directory. The OpenCode package requires the exact `26.13.0-2`
version.

**The upgrade does not appear to take effect** — terminate the running interface
completely, then start `opencode` again. The previous process continues to use the
previous code.

**A script does not behave as expected outside a terminal** — non-TTY execution is
intentionally unsupported; such runs print guidance and exit with status 1. Use
`opencode run --standalone "..."` for scripting.

**The process is terminated during a large session** — this is caused by system memory
pressure rather than a crash in the port. Use a smaller session or adjust
`OPENCODE_IOS_MAX_OLD_SPACE_MB` with caution.

## Building from source

The upstream revision is pinned, the patches are maintained in the repository, and the
runtime is built in its own repository. Hosted CI runners cannot execute iPhoneOS
binaries; CI therefore verifies assembly and static properties, while device acceptance
remains a separate, documented step.

| Workflow | Build output |
| --- | --- |
| `build-opencode.yml` | The JS CLI and mobile terminal interface, plus host tests |
| `build-opentui-ios.yml` | The signed iPhoneOS native renderer |
| `package-rootless-node26.yml` | The OpenCode package that depends on the external Node runtime |
| `package-rootless.yml` | The stable Node 22 release line |

```sh
gh workflow run build-opencode.yml -R Justintunsday/opencode-ios -f variant=node26
```

Architecture notes are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); build
details are documented in [docs/OPENCODE_BUILD.md](docs/OPENCODE_BUILD.md). The interface
follows the existing Solid/OpenTUI structure, with visual direction from
[pageton/tui-design-skill](https://github.com/pageton/tui-design-skill).

## Credits

This is an independent port. OpenCode, Node.js and OpenTUI remain the property of their
respective authors and retain their original licenses. See [LICENSE](LICENSE) and
[NOTICE](NOTICE) for details.
