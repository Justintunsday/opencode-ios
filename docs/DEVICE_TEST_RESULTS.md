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

## STATUS: DEVICE-VERIFIED — current release `v2.2.5-ios.5`

**Released artifact:** `OpenCode-iOS-rootless.deb`
**SHA-256 `b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073`** (52,926,812 bytes),
package `opencode` 2.2.5-1, `Architecture: iphoneos-arm64`, rootless `/var/jb`,
installed `/var/jb/usr/bin/opencode`.

Release history (kept for traceability):

| Release | deb SHA-256 | Notes |
| --- | --- | --- |
| v2.2.5-ios.2 | `2f96fc18…` | first device-verified package; plain `opencode` crashed on OpenTUI |
| v2.2.5-ios.3 | `8a625f75…` | clean TUI guidance (patch 0011) |
| v2.2.5-ios.4 | `299ee574…` | **superseded / NOT device-verified** (REPL turns failed: shared server lifecycle) |
| v2.2.5-ios.5 | `b23ed1fc…` | **current, DEVICE-VERIFIED**: pure-JS line REPL + fresh connection per turn + 3-attempt retry |

Rolled-up identities verified **inside the installed package**:

| Component | Identity |
| --- | --- |
| Native runtime node | `cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce`, 106,842,800 B, iPhoneOS arm64, 2-key ldid entitlements, Node.js 22.9.0, ICU 75 full, JIT+WebAssembly |
| CLI bundle `opencode.mjs` | `e99ac8d12f083539289fbeeb6ddc07a40348e8eec0db3a76c3d628409a826950`, 21,397,681 B, 22 assets (14-patch series incl. line REPL + retry budget) |
| Launcher `/var/jb/usr/bin/opencode` | `86f68f21f5e5ead2db347cc8bd7c623e40927afce18cdec7011f6de44d88c82b`; shebang `#!/var/jb/bin/sh`; node flags `--single-threaded --experimental-sqlite --disable-warning=ExperimentalWarning --no-warnings --max-old-space-size=1536` |

## Interactive interface on iOS — line REPL (device-verified)

The full-screen TUI cannot run on this port: `@opentui/core` 0.8.0's Node binding loads its native
Zig core through Node's `node:ffi`, which requires **Node.js >= 26.4 with `--experimental-ffi`**;
the device-verified iPhoneOS runtime is Node 22.9.0 and has neither (device: `bad option:
--experimental-ffi`). Since `v2.2.5-ios.5`, a terminal invocation of `opencode` (or `opencode mini`)
starts a **pure-JS line REPL** instead:

```
$ opencode
opencode iOS line REPL (full TUI/OpenTUI unavailable on iPhoneOS).
Type a prompt and press Enter. /help for commands, /exit or Ctrl-D to quit.
> Use the shell tool to write the acceptance marker file.

> build · mock-opencode-1
$ echo opencode-ios-e2e-ok > /var/mobile/ocdev-e2e.txt && id -un >> ... && git --version >> ... && pwd >> ...
(no output)
E2E_OK: shell tool executed on iPhone; file written, identity and git version captured.
> /new
Starting a new session on the next prompt.
> ...
> /exit
```

Device-verified REPL behaviour (real SSH PTY, packaged launcher, local OpenAI-compatible mock):

- REPL intro/prompt render; each line streams assistant text and tool activity like headless `run`;
  the shell tool really executes on the device; `/new`, `/help`, `/exit`, Ctrl-D work; `/exit` rc=0.
- Turn lifecycle is robust: in the acceptance run turn 1 succeeded on the first attempt (300 ms
  first-turn warm-up), turn 2 failed twice with `Transport: fetch failed` and succeeded on the third
  attempt (2 retries / 3 attempts with a fresh server connection each time); turn 3 after `/new`
  succeeded first attempt. Persistent failures return to the prompt instead of exiting.
- Marker file written by the shell tool: `/var/mobile/ocdev-e2e.txt` =
  `opencode-ios-e2e-ok / mobile / git version 2.39.1 / /var/mobile/repl9-work`.
- Non-TTY invocation (`opencode < /dev/null`, and `opencode mini < /dev/null`) prints clean
  guidance (TTY requirement, Node >= 26.4 + node:ffi reason, line-REPL and headless alternatives,
  docs path) and exits 1 — no stack trace.

## Final packaged acceptance (release `v2.2.5-ios.5`, raw log, 2026-11-01)

```
deb file sha256: b23ed1fc6f99ab67c0882cfed5c990d941e99984e4ccbaa622e23bbd75f0f073
PASS  dpkg install
Status: install ok installed / Version: 2.2.5-1 / Architecture: iphoneos-arm64
PASS  dpkg status installed
runtime node: cf707ebe5122531958e01e9737509476c419ff890b8165438a8ba8ad82ef4fce
cli bundle:  e99ac8d12f083539289fbeeb6ddc07a40348e8eec0db3a76c3d628409a826950
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

Headless E2E agent turn (through the installed launcher, mock OpenAI-compatible provider) passed on
the first attempt in this acceptance run: exit 0, stdout
`E2E_OK: shell tool executed on iPhone; file written, identity and git version captured.`, mock
server saw `GET /api/v1/models` + 3× `POST /chat/completions` (last with `toolResult=true`).

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

- **Full-screen TUI is unavailable on iOS**: OpenTUI's Node binding requires Node >= 26.4 with
  `node:ffi`; the iPhoneOS Node 22.9 runtime lacks it. A line-based REPL is provided for terminals
  (`opencode`, `opencode mini`); non-TTY scripts get guidance + exit 1. A real TUI would need a
  future Node 26+ iPhoneOS runtime.
- **V8 must run single-threaded** (`--single-threaded`, baked into the launcher): background V8
  threads race the process-wide mprotect W^X toggle and crash (SIGBUS 138). Consequence: no
  background optimizing compiler/marking threads; functionally fine, potentially slower.
- **Intermittent first-attempt transport errors with a provider** (`Transport: fetch failed` /
  `Transport: terminated`): observed with the local mock provider on some turns, both in the REPL
  and in headless `opencode run`. The REPL retries with a fresh server connection (up to 3 attempts,
  1 s apart) and succeeds; headless `run` retries at the process/CLI level. Real external providers
  were not exercised on-device.
- **2 GB device memory pressure**: running several Node processes (CLI + server child + mock) plus
  the rest of iOS can trigger jetsam; the packaged launcher defaults `--max-old-space-size=1536`,
  and closing other apps is recommended. A stale `serve --service` child can hold port 49374;
  `pkill -f 'serve --service'` clears it.
- Native file watchers use the node/fallback backend (a non-fatal "watcher backend not supported"
  log for the config directory); agent file-change events still work.
- No real AI provider was exercised on-device; the agent loop was verified with a local
  OpenAI-compatible mock (no credentials involved).

## CI evidence for the released artifact

- CLI build patch 0014 (REPL retry budget): run **41291337297** (success; `opencode.mjs` sha
  `e99ac8d1…`, required Node 22.9.0 host smoke passed).
- Package build `v2.2.5-ios.5`: run **41292412240** (success): variant `node22`, runtime run
  41273024931 (node `cf707ebe…`), CLI run 41291337297, 47 PASS / 0 FAIL / 1 SKIP (optional
  jit-shim not shipped), `ci_status=PASS`.
- Port verification on this package: run **41293124128** (workflow_dispatch) and
  **41293169688** (push), both success.
- Runtime build: run **41273024931** (device-verified node sha `cf707ebe…`; runtime-manifest carries
  `device_verification.verified=true` and
  `runtime_policy.launcher.required_flags: ["--single-threaded","--experimental-sqlite"]`).
- Node 18 fallback alternative: runtime run 41285669688 (node `74e1c5c3…`), package run
  41291038144 (deb `0be49c37…`) — documented alternative, CI-validated only.
