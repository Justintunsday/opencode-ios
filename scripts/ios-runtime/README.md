# iPhoneOS Node.js runtime — device verification checklist

The CI workflow (`.github/workflows/build-runtime.yml`) produces a **statically
validated** `ios-node-runtime` artifact. GitHub-hosted macOS runners cannot run
iPhoneOS binaries, so this checklist is how the runtime is tested on the actual
jailbroken device (iPhone SE 2, iOS 16.1.1, Dopamine rootless + ElleKit).

Status of every artifact produced by CI: **UNVERIFIED ON DEVICE** until the
device checks below are recorded with the artifact's run id + sha256.

## 1. Install on device (rootless)

Copy the artifact contents to the device, e.g. over SSH/NewTerm:

```sh
mkdir -p /var/jb/usr/lib/opencode/runtime
# scp the artifact contents, then on device:
cp node            /var/jb/usr/lib/opencode/runtime/node
cp entitlements.plist /var/jb/usr/lib/opencode/runtime/entitlements.plist
chmod 0755 /var/jb/usr/lib/opencode/runtime/node
ln -sf /var/jb/usr/lib/opencode/runtime/node /var/jb/usr/local/bin/node
```

If the binary fails to load with a signature/entitlement error, re-sign on device
with the bundled entitlements (requires `ldid` from the jailbreak's Procursus
repository):

```sh
ldid -S/var/jb/usr/lib/opencode/runtime/entitlements.plist \
     /var/jb/usr/lib/opencode/runtime/node
```

The runtime is JIT + WebAssembly enabled, and uses the **device-verified 2-key
set**: `platform-application` + `com.apple.private.security.no-sandbox`.

- The shipped iOS JIT memory model (patches 0005+0006) is **no MAP_JIT** plus
  V8's `RwxMemoryWriteScope` implemented over `mprotect`: registered executable
  ranges (JS code chunks, wasm code spaces) are toggled RW while code is being
  written and RX while executing. Device probing on this iPhone proved this is
  the only working executable-memory pattern on iOS 16.1.1.
- `platform-application` + `no-sandbox` are mandatory: `platform-application`
  alone and an old JIT set without `no-sandbox` were SIGKILLed (exit 137).
- Additional JIT keys (`dynamic-codesigning`, `allow-jit`,
  `allow-unsigned-executable-memory`, `disable-library-validation`) are NOT
  needed and are hard-rejected by the CI signing gate; on this device extra keys
  never fixed the MAP_JIT aborts (those were a V8 memory-model bug, see
  docs/RUNTIME_BUILD.md).

Do not improvise entitlements: on the target device the loader is strict (137 for
wrong sets).

## 2. Smoke tests (device — required before claiming runtime works)

**Always invoke the runtime with `--single-threaded`** (device-verified; add
`--experimental-sqlite` when the CLI needs `node:sqlite`). The iOS JIT memory
model toggles code-page permissions process-wide with `mprotect`, so V8's
background compiler/marking threads must be disabled; with the default
multithreaded mode, a JIT loop and built-in `fetch` can crash with SIGBUS (138)
even though `--version`, plain JS, wasm and `Intl` work. `--single-threaded`
made all of them pass on the target iPhone.

Run in NewTerm or over SSH. The runtime ships with **V8 JIT + WebAssembly
enabled** and **full ICU** (the CLI bundle needs ECMA-402 `Intl`, `\p{...}`
regexp escapes, and a wasm llhttp parser for Node's `fetch()`/undici).

```sh
node --single-threaded --version        # expect v22.9.0
node -p process.platform                # expect 'ios' (NOT 'darwin')
node -p process.arch                    # expect 'arm64'
node -p 'process.versions.v8'           # V8 version from Node 22.9.0
node -p 'process.versions.icu'          # expect an ICU version (e.g. 75.1) - NOT undefined
node -p 'typeof Intl'                   # expect 'object'
node -p 'typeof WebAssembly'            # expect 'object' (wasm enabled)
node -e 'console.log(/\p{L}/u.test("é"), new Intl.Segmenter("en",{granularity:"word"}).segment("hi there").next().value)'  # expect 'true hi'
node -e 'new WebAssembly.Module(new Uint8Array([0,97,115,109,1,0,0,0]))'  # minimal valid wasm module: no throw
node -e 'const t=Date.now();for(let i=0;i<1e7;i++){};console.log("jit loop ok",Date.now()-t)'  # JIT executes (no SIGBUS 138)
node -p 'process.versions.undici || "n/a"'  # informational: built-in fetch stack
node -e 'fetch("https://example.com").then(r=>{console.log(r.status);process.exit(0)},e=>{console.error(e);process.exit(1)})'  # built-in fetch (uses wasm llhttp)
node -e 'console.log(1 + 2)'            # basic JS execution
node -e 'console.log(require("fs").readdirSync("."))'   # filesystem
node -e 'require("fs").writeFileSync("/tmp/node-ios-test.txt","ok")' \
  && cat /tmp/node-ios-test.txt         # write
node -e 'new (require("worker_threads").Worker)("console.log(1)",{eval:true})'  # threads
node -e 'require("https").get("https://example.com",r=>{console.log(r.statusCode);process.exit(0)})'  # TLS
```

Record for each: command, exit code, stdout/stderr. Attach to the device test
report; the CI artifact alone is not proof of runtime viability.

If `Intl` is undefined, the `\p{L}` regexp throws, `WebAssembly` is undefined, or
built-in `fetch()` fails at startup, do not use that artifact for the CLI.

## 3. Known limitations of this runtime build

- **JIT + WebAssembly enabled** — with the device-verified 2-key entitlement set
  and the no-MAP_JIT / mprotect RW<->RX toggling iOS memory model (patches
  0005+0006). The launcher MUST pass `--single-threaded` (and
  `--experimental-sqlite` for `node:sqlite`); without it JIT code execution and
  `fetch` can SIGBUS due to the process-wide mprotect toggle. Re-sign only with
  the artifact's own `entitlements.plist`.
- **ICU is required and compiled in** — `--with-intl=full-icu`, statically
  linked (all locales). The first no-ICU build was device-run but the CLI failed
  with `SyntaxError: Invalid regular expression: /[\p{Mark}...]/gu: Invalid
  property name in character class`.
- **WebAssembly is required and compiled in** — Node 22.9's built-in
  `fetch()`/undici instantiates a wasm llhttp parser at startup; the earlier
  no-wasm runtime failed with `ReferenceError: WebAssembly is not defined`.
- **iOS JIT memory model** — no `MAP_JIT` on iOS; V8's write scopes toggle
  registered code ranges between RW and RX with `mprotect` (patches 0005+0006).
  MAP_JIT / RWX variants aborted on the target device (SIGBUS / SIGTRAP) even
  with JIT entitlements; MAP_JIT and `pthread_jit_write_protect_np` are simply
  unavailable on iOS 16.1.1.
- **Not executed by CI** — all CI checks are static (Mach-O platform/minos,
  arch, dylib linkage, ICU/WebAssembly audits, ldid signature).
- **Native addons** — only addons that are the same architecture (`arm64`) and
  statically compatible can load; prebuilt macOS/Linux addons will not.
- `process.platform === "ios"` — CLI code must treat iOS as its own platform,
  not `darwin` (device-confirmed).
- **No full OpenTUI TUI on this runtime** — `@opentui/core` 0.8.0's Node binding
  needs Node `>= 26.4.0` with `--experimental-ffi`/`node:ffi`, which Node 22.9.0
  does not have (device-confirmed: `bad option: --experimental-ffi`). On iOS the
  CLI provides a **pure-JS, line-based interactive REPL** instead (streaming
  text/tool activity, `/new` `/exit` `/help`, Ctrl-C cancels a turn, session
  continuity); non-TTY runs keep the guidance output. No runtime/launcher change
  is needed for that. A real TUI would require a future Node 26+ iPhoneOS
  runtime (nodejs-mobile Node 26 + V8 14 + redoing the W^X patch series).

## 4. Rebuild / reproduce locally

```sh
# from a clone of this repository on macOS with Xcode 16.4:
git clone --depth 1 https://github.com/nodejs-mobile/nodejs-mobile.git nodejs-mobile
cd nodejs-mobile
git fetch --depth 1 origin 106c51f95d55d1010de56a2ffd09bfb4ba819a47
git checkout FETCH_HEAD
for p in ../patches/nodejs-mobile/*.patch; do git apply "$p"; done
cd ..
python3.12 -m venv .venv && . .venv/bin/activate && pip install setuptools
bash scripts/build-ios-runtime.sh all
# artifact: dist/ios-node-runtime/{node,entitlements.plist,runtime-manifest.json,SHA256SUMS}
```
