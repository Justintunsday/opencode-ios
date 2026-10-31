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

That plist carries exactly the two device-verified keys
`platform-application` + `com.apple.private.security.no-sandbox`. Do **not** add
JIT/executable-memory entitlements (`dynamic-codesigning`, `allow-jit`,
`allow-unsigned-executable-memory`, `disable-library-validation`): on the target
device those sets are SIGKILLed (exit 137) by the iOS loader, even together with
`platform-application`. This runtime is jitless and has no WebAssembly, so it
does not need them.

## 2. Smoke tests (device — required before claiming runtime works)

Run in NewTerm or over SSH. The runtime is built with V8 `--jitless` and without
WebAssembly, so avoid flags that require JIT/WASM. **ICU is compiled in** (the
CLI bundle needs ECMA-402 `Intl` and `\p{...}` regexp escapes).

```sh
node --version                          # expect v22.9.0
node -p process.platform                # expect 'ios' (NOT 'darwin')
node -p process.arch                    # expect 'arm64'
node -p 'process.versions.v8'           # V8 version from Node 22.9.0
node -p 'process.versions.icu'          # expect an ICU version (e.g. 75.1) - NOT undefined
node -p 'typeof Intl'                   # expect 'object'
node -e 'console.log(/\p{L}/u.test("é"), new Intl.Segmenter("en",{granularity:"word"}).segment("hi there").next().value)'  # expect 'true hi'
node -e 'console.log(new Intl.DateTimeFormat("en",{dateStyle:"short"}).format(new Date(0)))'
node -e 'console.log(1 + 2)'            # basic JS execution
node -e 'console.log(require("fs").readdirSync("."))'   # filesystem
node -e 'require("fs").writeFileSync("/tmp/node-ios-test.txt","ok")' \
  && cat /tmp/node-ios-test.txt         # write
node -e 'new (require("worker_threads").Worker)("console.log(1)",{eval:true})'  # threads
node -e 'require("https").get("https://example.com",r=>{console.log(r.statusCode);process.exit(0)})'  # TLS
node -e 'console.log(typeof WebAssembly)'  # expected 'undefined' (wasm disabled in this build)
```

Record for each: command, exit code, stdout/stderr. Attach to the device test
report; the CI artifact alone is not proof of runtime viability.

If `Intl` is still undefined or the `\p{L}` regexp throws, the ICU-enabled build
did not make it to the device — do not use that artifact for the CLI.

## 3. Known limitations of this runtime build

- **No JIT** — built with `--v8-options=--jitless`, matching the precedent
  packages. Expect slower CPU-bound JavaScript.
- **No WebAssembly** — PR #150 sets `v8_enable_webassembly=0`; `WebAssembly`
  is unavailable (tree-sitter/photon WASM features in the CLI must degrade).
- **ICU is required and compiled in** — the first no-ICU build was device-run but
  the CLI failed with `SyntaxError: Invalid regular expression: /[\p{Mark}...]/gu:
  Invalid property name in character class`; this build uses
  `--with-intl=full-icu` (statically linked, all locales).
- **Not executed by CI** — all CI checks are static (Mach-O platform/minos,
  arch, dylib linkage, ldid signature, ICU symbol presence).
- **Native addons** — only addons that are the same architecture (`arm64`) and
  statically compatible can load; prebuilt macOS/Linux addons will not.
- `process.platform === "ios"` — CLI code must treat iOS as its own platform,
  not `darwin`.

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
