# OpenCode with the independent Node.js package

The experimental `v2.2.5-ios.5-node26test.5` packaging line uses two packages:

| Package | Version | Command / executable |
| --- | --- | --- |
| `node26` | `26.13.0-1` | `node`; `/var/jb/usr/lib/node26/node`; author `nodejs` |
| `opencode` | `2.2.5-2` | `opencode`; strict dependency on `node26 (= 26.13.0-1)` |

Install the runtime first, or pass both files to `dpkg`:

```sh
sudo dpkg -i node26_26.13.0-1_iphoneos-arm64.deb OpenCode-iOS-rootless-node26.deb
node --version
opencode --version
opencode --standalone
```

If the earlier `nodejs26-ios` prototype is installed, remove it before installing
the renamed `node26` package. That prototype supplied the old `node26` command.
The new package supplies `node` and includes a legacy internal binary-path link
for applications already running from the prototype location.

OpenCode's launcher directly executes the independent Node binary with required
`--single-threaded`, warning suppression and heap cap. Its CLI and signed native
renderer stay under `/var/jb/usr/lib/opencode/cli/assets`. The OpenCode package
contains no Node executable. Legacy `runtime/node` and metadata paths are relative
links to the independent package so already-running processes retain usable paths.
User configuration, provider credentials, service ports and sessions are preserved.

The runtime remains experimental: process-wide W^X requires single-threaded V8;
Node user worker isolates are unsupported, and OpenCode disables its tree-sitter
worker with a plain-text code fallback. Root/mobile managed services use separate
ports on the tested device (49374 / 49375); `--standalone` starts a private child.

CI validates both archives, exact runtime/CLI/renderer hashes, package dependencies,
ownership paths, file modes and links. It does not execute iPhoneOS code. Device
installation, CLI and real PTY results are recorded in `VERIFICATION.md` after
the new package pair passes acceptance. Stable `v2.2.5-ios.5` release assets are unchanged.
