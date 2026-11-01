# Device test results — iPhone SE 2 / iOS 16.1.1 / Dopamine rootless

This file records the **actual on-device evidence** for the released artifacts. Every line below
was produced by running the artifact on a real target device, not inferred from CI.

## Device under test

| Property | Value |
| --- | --- |
| Model | iPhone SE (2nd generation), `iPhone12,8`, `arm64` |
| OS | iPhone OS **16.1.1** (20B101), Darwin 22.1.0 |
| Jailbreak | Dopamine rootless, `/var/jb`, ElleKit |
| User | `mobile` (uid 501); root via `sudo` for `dpkg` |
| Terminals | SSH (PTY and non-PTY) + NewTerm; shells live under `/var/jb` (no `/bin/sh`, `/bin/bash`, `/bin/zsh`) |
| git | Procursus apt `git 2.39.1` (optional, for the agent shell tool) |

## STATUS: DEVICE-VERIFIED — current release `v2.2.5-ios.3`

**Released artifact:** `OpenCode-iOS-rootless.deb`
**SHA-256 `8a625f75a1f1fa3909d5128491c781a6559fff6d8d6894b9156e90e8d0d880dc`** (52,964,804 bytes),
package `opencode` 2.2.5-1, `Architecture: iphoneos-arm64`, rootless `/var/jb`,
installed `/var/jb/usr/bin/opencode`.

Previous release for traceability: `v2.2.5-ios.2`, deb SHA-256
`2f96fc183416ef336fc9855b9dedc51e6baaf89cda996b0147b31444dbef446b` — same runtime and behaviour; it
lacked patch 0011, so plain `opencode` (interactive TUI) crashed with an OpenTUI stack trace there.

Rolled-up identities verified **inside the installed package**:

| Component | Identity |
| --- | --- |
| Native runtime node | `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`, 106,842,800 B, iPhoneOS arm64, 2-key ldid entitlements, Node.js 22.9.0, ICU 75 full, JIT+WebAssembly |
| CLI bundle `opencode.mjs` | `484b2c1c6b8d932e5cde74d197b260e73abf8e25600f38d79239c6a8abf60f9d`, 21,392,407 B, 22 assets (11-patch series incl. TUI guidance) |
| Launcher `/var/jb/usr/bin/opencode` | `86f68f21f5e5ead2db347cc8bd7c623e40927afce18cdec7011f6de44d88c82b`; shebang `#!/var/jb/bin/sh`; node flags `--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings --max-old-space-size=1536` |

## Interactive TUI on iOS (release `v2.2.5-ios.3` behaviour)

Both TUI frontends (`opencode` with no arguments and `opencode mini`) use the **OpenTUI native
render library**, which has no iPhoneOS (`ios-arm64`) build. On `v2.2.5-ios.3` the CLI detects this
up front and prints clean guidance instead of a native-renderer stack trace (verified over a real
SSH PTY against the installed launcher):

```
$ opencode
Interactive TUI is not available on this iOS build.
The OpenTUI native renderer has no iPhoneOS (ios-arm64) build, so the full TUI
and `opencode mini` cannot start on this device. Use the headless CLI instead:
  opencode run "your prompt"        # one-shot agent turn
  opencode run -c "your prompt"     # continue the last session
  opencode run --standalone "..."   # private server (recommended)
  opencode models | auth login | auth list | session list | debug paths
Docs: /var/jb/usr/share/doc/opencode/KNOWN_LIMITATIONS.md
(exit 1; no stack trace; no background server is started or left running)

$ opencode mini
(identical guidance, exit 1)
```

The supported interface on iPhoneOS is the **headless CLI**: `opencode run`, `opencode run -c`,
`opencode models`, `opencode auth login/list`, `opencode session list`, `opencode debug ...`.

## Final packaged acceptance (release `v2.2.5-ios.3`, raw log, 2026-11-01)

```
deb file sha256: 8a625f75a1f1fa3909d5128491c781a6559fff6d8d6894b9156e90e8d0d880dc
PASS  dpkg install
Status: install ok installed / Version: 2.2.5-1 / Architecture: iphoneos-arm64
PASS  dpkg status installed
runtime node: cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce
cli bundle:  484b2c1c6b8d932e5cde74d197b260e73abf8e25600f38d79239c6a8abf60f9d
launcher:    86f68f21f5e5ead2db347cc8bd7c623e40927afce18cdec7011f6de44d88c82b
PASS  agent shell tool marker file
PASS  agent run exit
PASS  opencode --version            -> opencode2-node v2.2.5
PASS  opencode --help               -> full help (Intl.Segmenter works with full ICU)
PASS  debug paths                   -> ~/.config/opencode, ~/.local/share/opencode, ...
PASS  models                        -> catalog + configured mock provider models
PASS  auth list                     -> "No authenticated integrations"
PASS  session list                  -> ses_... Untitled session rows
PASS  debug config                  -> config document discovered
PASS  dpkg remove                   -> runtime removed, user data kept
PASS  dpkg reinstall
PASS  post-reinstall opencode --version
FINAL_PACKAGED_ACCEPTANCE PASS=14 FAIL=0
FINAL_PACKAGED_ACCEPTANCE_RESULT=PASS
```

### End-to-end agent turn on the device (mock OpenAI-compatible provider)

Command (through the installed launcher, no hacks):

```
opencode run --standalone --model lmstudio/mock-opencode-1 \
  "Use the shell tool to write the acceptance marker file." < /dev/null
```

Result on the `v2.2.5-ios.3` run: exit 0 on the 2nd attempt (attempt 1 hit the known intermittent
mock-transport flake `Transport: terminated`), stdout
`E2E_OK: shell tool executed on iPhone; file written, identity and git version captured.`, mock
server saw `GET /api/v1/models` + 3× `POST /chat/completions` (last with `toolResult=true`), and
the shell tool really ran on the device:

```
$ echo opencode-ios-e2e-ok > /var/mobile/ocdev-e2e.txt && id -un >> ... && git --version >> ... && pwd >> ...
marker file /var/mobile/ocdev-e2e.txt:
  opencode-ios-e2e-ok
  mobile
  git version 2.39.1
  /var/mobile/accept-work
```

## Runtime capability evidence (v6 runtime, device)

The Node 22.9 runtime carries patch 0005 (no MAP_JIT) + patch 0006 (V8 `RwxMemoryWriteScope`
implemented over mprotect over registered code ranges: RW while writing, RX while executing).

Device probe of the underlying primitives (native arm64-apple-ios diagnostic binary, both the
2-key and JIT-keys signature sets behave identically):

```
A plain mmap(RWX) + exec              -> exec SIGBUS (page has no X)
B/D/G/H MAP_JIT or mprotect RWX       -> EINVAL / exec SIGBUS
E plain RW -> write -> mprotect RX    -> exec OK          <-- the only working pattern
pthread_jit_write_protect_np          -> absent
```

Consequently V8 JIT is only safe when the process-wide mprotect toggle cannot race V8 background
threads, so the launcher passes `--single-threaded`. Device results with the shipped runtime:

- default (multithreaded): `--version`/plain JS/wasm compile/Intl OK, but JIT loop and `fetch`
  die with SIGBUS 138 (background compiler/marking threads race the toggle);
- with `--single-threaded`: JIT loop rc=0, `fetch('https://nodejs.org/...')` rc=0 HTTP 200,
  WebAssembly compile+instantiate OK, Intl/ICU 75/`\p{L}` OK, `process.platform === "ios"`;
- `node:sqlite` works natively (WAL files created by the CLI).

Earlier runtime iterations and their failure modes (kept for the record): v2 interpreted-only
started but wasm was missing; v3 MAP_JIT + no APRR -> SIGBUS; v4 MAP_JIT + mprotect RWX -> SIGTRAP
(FatalOOM in `CodeRange::InitReservation`); v5 plain RWX mprotect -> SIGBUS (the kernel silently
drops execute). The probe above is what drove the final v6 mprotect model.

## Known limitations observed on device

- **Interactive TUI and `opencode mini` cannot start on iOS** (OpenTUI has no iPhoneOS renderer);
  release `v2.2.5-ios.3` prints clean guidance and exits 1 instead of crashing. Headless CLI is the
  supported interface.
- **V8 must run single-threaded** (`--single-threaded`, baked into the launcher): background V8
  threads race the process-wide mprotect W^X toggle and crash (SIGBUS 138). Consequence: no
  background optimizing compiler/marking threads; functionally fine, potentially slower.
- **Intermittent provider transport flake with the local mock**: roughly 1 in 3 first E2E attempts
  logged `Transport: terminated` and the turn failed; a retry succeeded (the release acceptance
  passed on attempt 2). Real external providers were not tested for this port. Documented.
- **2 GB device memory pressure**: running several Node processes (CLI + server child + mock) plus
  the rest of iOS can trigger jetsam; the packaged launcher defaults `--max-old-space-size=1536`,
  and closing other apps is recommended. A stale `serve --service` child can hold port 49374;
  `pkill -f 'serve --service'` clears it. (After the TUI guidance patch, plain `opencode` no longer
  starts a server, so it no longer leaves one behind.)
- Native file watchers use the node/fallback backend (a non-fatal "watcher backend not supported"
  log for the config directory); agent file-change events still work.
- `--help` on a **small-ICU** Node 18 reference binary crashed in `JSSegmenter::Create`; the shipped
  full-ICU Node 22 runtime renders help correctly (the repo-built Node 18 runtime is full-ICU too).
- No real AI provider was exercised on-device; the agent loop was verified with a local
  OpenAI-compatible mock (no credentials involved).

## CI evidence for the released artifact

- CLI build for patch 0011: run **41278475579** (success; `opencode.mjs` sha
  `484b2c1c…`, required Node 22.9.0 host smoke passed).
- Package build `v2.2.5-ios.3`: run **41279438605** (success): variant `node22`, runtime run
  41273024931 (node `cf707ebe…`), CLI run 41278475579, 47 PASS / 0 FAIL / 1 SKIP (optional
  jit-shim not shipped), `ci_status=PASS`.
- Port verification: 41278163394 and 41279694687 (success).
- Runtime build: run **41273024931** (same node sha as device-verified `cf707ebe…`; runtime-manifest
  carries `device_verification.verified=true` and
  `runtime_policy.launcher.required_flags: ["--single-threaded","--experimental-sqlite"]`).
