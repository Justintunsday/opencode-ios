# Independent Node and dependent OpenCode — device results

**DEVICE-VERIFIED for the recorded functional scope**, experimental, on iPhone SE 2 /
iOS 16.1.1 / Dopamine rootless. Acceptance window: 2026-11-03 **10:44:46–10:56:35 UTC**.
The stable `v2.2.5-ios.5` release is unchanged. CI reports retain their assembly-only
`UNVERIFIED ON DEVICE` status; these results come from actual SSH exits and allocated PTYs.

| Item | Accepted value |
| --- | --- |
| OpenCode label / package | `v2.2.5-ios.5-node26test.5`; `opencode` `2.2.5-2`, `iphoneos-arm64` |
| OpenCode package run | [41621747546](https://github.com/Justintunsday/opencode-ios/actions/runs/41621747546); artifact `opencode-ios-rootless-node26` contains both debs |
| OpenCode deb | `OpenCode-iOS-rootless-node26.deb`, **30,782,884 bytes**, SHA-256 `7f01f19162e63ab4c9d18e444ac7028ebb601db3bf7ed648e0cfaaada9fb0895` |
| Independent Node package | `node26` `26.13.0-1`; author `nodejs`; command `node` |
| Node package run | [41620234785](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41620234785); artifact `node26-rootless` |
| Node deb | `node26_26.13.0-1_iphoneos-arm64.deb`, **25,893,168 bytes**, SHA-256 `c6cda114912707b5c229178449e0cc0a641fa7165c270a8dd81456196fed9e51` |
| Dependency / ownership | `opencode` depends on `node26 (= 26.13.0-1)`; no embedded Node executable; legacy runtime paths are relative links |
| Compiled inputs | Runtime [41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128), node SHA `84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9`; CLI [41584007287](https://github.com/Justintunsday/opencode-ios/actions/runs/41584007287), mjs SHA `1aab71859d5992e49b54f91fbe574578679dee3970693dc0176f9257869a3283`; renderer [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506), dylib SHA `4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868` |
| Static validation | Node deb **23 PASS**; app builder **68 PASS**, native `dpkg-deb` metadata/combined extraction checks and 5 renderer builtin checks; CI does not execute iPhoneOS binaries |

## Actual execution

| Check | Captured result |
| --- | --- |
| Installation | `node26` installation rc=0; `opencode` upgrade `2.2.5-1` → `2.2.5-2` rc=0; exact dependency configured |
| Runtime identity | `node --version` → `v26.13.0`; platform `ios`; execPath ends `/usr/lib/node26/node`; wrapper includes `--single-threaded`; installed raw Node SHA matches |
| Standalone runtime | 11/11 checks: identity/signature bytes, JIT checksum 5999999, wasm function 42 + 65,536-byte memory, ICU/Unicode, native FFI + reentrant qsort callback, SQLite persistence, ESM/stdin, fork flag inheritance, HTTP and HTTPS 200; rc=0 |
| Runtime stress / arguments | `WASM_HTTP_STRESS_OK requests=192 modules=24`; arguments containing spaces and stdin passed; old internal Node path link passed |
| Node REPL | Actual PTY, `2+3` → `5`, `.exit` rc=0, 6.571 seconds |
| CLI matrix | 8 PASS / 0 FAIL: version, help, debug paths/config, models, auth list, session list rc=0; non-TTY guidance rc=1, no stack trace; XDG paths point to the private evidence directory |
| Ordinary OpenCode TUI | Actual 80×24 PTY, **32.314 seconds**, OpenTUI notifications, `app=opencode`, alternate screen and OpenCode title; separately sent `/exit` and Enter; rc=0 |
| Headless agent/tool | `run --standalone --format json`, rc=0; 6 valid NDJSON events (`step_start,tool_use,step_finish,step_start,text,step_finish`); shell tool executes the public `node` command and asserts version, platform, independent execPath and flags |
| Three-turn TUI | Actual 80×24 private-server PTY, **122.328 seconds**, 3 shell/reply turns with fenced code, `/exit` rc=0; 3 tool-marker records plus the headless marker; no forced channel close |
| Child argv | Actual standalone server resolves to `/usr/lib/node26/node --single-threaded --no-warnings --max-old-space-size=512 .../opencode.mjs serve --stdio --port 0`; normal launcher default remains 1536 MiB |
| Packaged smoke helper | SHA `77084380d529fa1757d708704b634dd337605991d832cf1284066be2eb718651`; serial installed-helper run rc=0 / `DEVICE SMOKE TEST: PASS`, no warnings |
| File verification | `dpkg --verify node26 opencode` rc=0 after installation and final cleanup |
| Cleanup | Owned mock PID 36053 terminated; recorded normal/headless/private TUI parent and server PIDs exited; existing root/mobile services, user TUI and old Node REPL preserved |

The first smoke run overlapped the TUI and emitted one nonfatal `Location plugins did
not finish activating` warning for `models`. The strict command matrix returned 0;
the serial installed-helper rerun returned 0 with no warnings. A first private-TUI
harness invocation incorrectly supplied unsupported top-level `--model` and returned
1 with CLI usage; the accepted run uses the configured model and `--standalone`.

## PTY output and evidence

Captured terminal-control substrings, with control bytes escaped:

```text
\x1b]99;i=opentui-notifications:p=?;\x1b\\
\x1b[?1049h
\x1b]0;OpenCode\x07
```

The raw three-turn PTY contains **163,378 bytes**, SHA-256
`0efc9cd666b5b710a202f65f21062f5930305cce0e46d39c25c2a0d881e54b2b`. The harness recorded
`code=0`, `forcedClose=false`, `elapsedMs=122328`, all four native TUI flags true,
and both fallback flags false. It contains `EXTERNAL_RUNTIME_E2E_OK` from the mock reply.

Raw evidence remains in the maintainer workspace
`C:\opencode\device\artifacts\node26test4-evidence\`, labels
`node26-external-*`: `summary.json`, install/receipt/smoke/matrix/E2E JSON and stdout,
`pty.raw.bin`, `pty-three-turn.raw.bin`, mock request log, tool marker JSONL,
headless NDJSON, process snapshots, cleanup JSON and the three original Jetsam reports.
No real provider key was used.

## Crash comparison and limits

The fresh CrashReporter baseline was **0** `.ips`; final count was **3**:

| New report | Parsed termination evidence |
| --- | --- |
| `JetsamEvent-2026-11-03-185126.ips` | `accessoryupdaterd`, `per-process-limit`; Node entries have no termination reason |
| `JetsamEvent-2026-11-03-185354.ips` | System daemon entries include `vm-compressor-space-shortage` / `vm-pageshortage`; Node entries have no termination reason or kill delta |
| `JetsamEvent-2026-11-03-185554.ips` | `accessoryupdaterd`, `per-process-limit`; Node entries have no termination reason |

**No new Node crash report or Node Jetsam victim was observed.** System memory
pressure was observed and remains a limitation on this 3 GB device; running several
TUI/server processes concurrently increases pressure. This acceptance does not cover
indefinite uptime. The earlier 612.4-second / 12-turn run belongs to the embedded
test.4 package and is retained separately in `VERIFICATION.md`.

Mandatory `--single-threaded`, foreground V8 JobHandles 0016 and callback fixes
0014/0015 remain required. User `worker_threads` are unsupported; iOS tree-sitter
workers are disabled with plain-text code fallback. Real external AI provider keys,
clipboard, interactive tool PTYs, Ghostty panes and audio remain unverified or
unavailable. The Node deb is runtime-only and does not ship npm/npx.
