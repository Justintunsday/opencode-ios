#!/usr/bin/env node
// Host-Node unit check for the Node 26 (Phase D real-TUI) CLI bundle's OpenTUI iOS renderer asset.
//
// Verifies (no device, no TUI launch):
//   1. the dependency-patched @opentui/core 0.8.0 build-time resolver maps the iOS native asset
//      target to @opentui/core-ios-arm64/libopentui.dylib, with process.platform stubbed to "ios";
//   2. getNodeAssets({platform:"ios"}) resolves the renderer source from OPENCODE_OPENTUI_IOS_DYLIB
//      (the asset-collector path the CLI build uses);
//   3. the staged CLI artifact contains that asset at the exact OTUI_ASSET_ROOT-relative key with
//      the expected sha256;
//   4. the installed runtime FFI chunk carries the ios entry + darwin->ios platform fallback, and
//      the built bundle references libopentui.dylib (i.e. the patch made it through Vite).
//
// Usage:
//   node src/opencode-ios/opentui_ios_asset_check.mjs \
//     --core <upstream>/node_modules/@opentui/core/node-assets.js \
//     --artifact-dir dist/opencode-cli-node26-ios \
//     --asset-key @opentui/core-ios-arm64/libopentui.dylib \
//     --dylib <opentui-ios-renderer>/libopentui.dylib \
//     --expected-sha256 <sha256> [--bundle dist/opencode-cli-node26-ios/opencode.mjs]
import { createHash } from "node:crypto"
import { existsSync, readFileSync, statSync } from "node:fs"
import { dirname, join } from "node:path"
import { pathToFileURL } from "node:url"

function fail(message) {
  console.error(`FAIL: ${message}`)
  process.exit(1)
}

function pass(message) {
  console.log(`PASS: ${message}`)
}

function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (!arg.startsWith("--")) fail(`unexpected argument: ${arg}`)
    const key = arg.slice(2)
    const value = argv[i + 1]
    if (value === undefined || value.startsWith("--")) fail(`missing value for ${arg}`)
    args[key] = value
    i += 1
  }
  return args
}

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

const args = parseArgs(process.argv.slice(2))
for (const required of ["core", "artifact-dir", "asset-key", "dylib", "expected-sha256"]) {
  if (!args[required]) fail(`missing --${required}`)
}
const corePath = args.core
const artifactDir = args["artifact-dir"]
const assetKey = args["asset-key"]
const dylibPath = args.dylib
const expectedSha = args["expected-sha256"].toLowerCase()

if (!existsSync(corePath)) fail(`patched @opentui/core resolver not found: ${corePath}`)
if (!existsSync(dylibPath)) fail(`OpenTUI iOS dylib not found: ${dylibPath}`)
if (!existsSync(artifactDir)) fail(`artifact dir not found: ${artifactDir}`)

const dylibSha = sha256File(dylibPath)
if (dylibSha !== expectedSha) fail(`dylib sha256 mismatch: expected ${expectedSha}, got ${dylibSha}`)
pass(`dylib sha256 ${dylibSha} (${statSync(dylibPath).size} bytes)`)

// --- 1/2: build-time resolver with process.platform stubbed to "ios" -------------------------
const coreUrl = pathToFileURL(corePath).href
const originalPlatform = process.platform
Object.defineProperty(process, "platform", { value: "ios", configurable: true })
process.env.OPENCODE_IOS = "1"
process.env.OPENCODE_OPENTUI_IOS_DYLIB = dylibPath
try {
  const core = await import(`${coreUrl}?case=ios-descriptor`)
  if (typeof core.getNativeAssetDescriptor !== "function")
    fail("patched node-assets.js does not export getNativeAssetDescriptor")
  if (typeof core.getNodeAssets !== "function") fail("node-assets.js does not export getNodeAssets")

  const descriptor = core.getNativeAssetDescriptor({ platform: "ios", arch: "arm64" })
  if (descriptor.key !== "@opentui/core-ios-arm64/libopentui.dylib")
    fail(`unexpected iOS native asset key: ${JSON.stringify(descriptor.key)}`)
  if (descriptor.packageName !== "@opentui/core-ios-arm64")
    fail(`unexpected iOS native asset package: ${JSON.stringify(descriptor.packageName)}`)
  if (descriptor.fileName !== "libopentui.dylib")
    fail(`unexpected iOS native asset file name: ${JSON.stringify(descriptor.fileName)}`)
  pass(`resolver maps process.platform="ios" to ${descriptor.key}`)

  const assets = core.getNodeAssets({ platform: "ios", arch: "arm64" })
  const native = assets.find((asset) => asset.key === descriptor.key)
  if (!native) fail(`getNodeAssets({platform:"ios"}) did not include ${descriptor.key}`)
  if (native.source !== dylibPath)
    fail(`getNodeAssets iOS native source is ${JSON.stringify(native.source)}, expected ${JSON.stringify(dylibPath)}`)
  pass(`getNodeAssets({platform:"ios"}) resolves the renderer from OPENCODE_OPENTUI_IOS_DYLIB`)

  // Unsupported desktop-only platforms must still be rejected.
  for (const platform of ["freebsd", "android"]) {
    let rejected = false
    try {
      core.getNativeAssetDescriptor({ platform, arch: "arm64" })
    } catch {
      rejected = true
    }
    if (!rejected) fail(`resolver unexpectedly accepted unsupported platform ${platform}`)
  }
} finally {
  Object.defineProperty(process, "platform", { value: originalPlatform, configurable: true })
}

// --- 3: staged artifact asset ----------------------------------------------------------------
const stagedPath = join(artifactDir, "assets", assetKey)
if (!existsSync(stagedPath)) fail(`staged asset missing: ${stagedPath}`)
const stagedSha = sha256File(stagedPath)
if (stagedSha !== expectedSha) fail(`staged asset sha256 mismatch: expected ${expectedSha}, got ${stagedSha}`)
pass(`staged asset ${assetKey} sha256 ${stagedSha}`)

// --- 4: runtime chunk patch + built bundle ---------------------------------------------------
const coreDir = dirname(corePath)
const runtimeChunk = join(coreDir, "chunk-node-y0w0hq5m.js")
if (!existsSync(runtimeChunk)) fail(`runtime FFI chunk not found: ${runtimeChunk}`)
const runtimeSource = readFileSync(runtimeChunk, "utf8")
if (!runtimeSource.includes('ios: "libopentui.dylib"'))
  fail("runtime FFI chunk is missing the ios native-asset entry (dependency patch not applied)")
if (!runtimeSource.includes('process.env.OPENCODE_IOS === "1" ? "ios" : process.platform'))
  fail("runtime FFI chunk is missing the darwin->ios platform fallback (dependency patch not applied)")
pass("runtime FFI chunk has the ios entry + darwin->ios fallback")

const bundlePath = args.bundle ?? join(artifactDir, "opencode.mjs")
if (!existsSync(bundlePath)) fail(`bundle not found: ${bundlePath}`)
const bundle = readFileSync(bundlePath, "utf8")
if (!bundle.includes("libopentui.dylib"))
  fail("built bundle does not reference libopentui.dylib (OpenTUI iOS patch did not reach the bundle)")
pass("built bundle references libopentui.dylib")

console.log("PASS: OpenTUI iOS renderer asset/resolver check")
