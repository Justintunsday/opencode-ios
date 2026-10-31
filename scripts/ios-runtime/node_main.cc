/*
 * Fallback CLI launcher for the nodejs-mobile iPhoneOS arm64 Node.js runtime.
 *
 * The preferred build path (see scripts/build-ios-runtime.sh) links Node's own
 * executable target: nodejs-mobile's configure is intentionally run WITHOUT
 * --enable-static, which sets gyp's node_target_type=executable and makes
 * `make` produce out/Release/node directly.
 *
 * This file is only used when that binary is missing or its link step fails:
 * the build script retries the exact node link command recorded in the build
 * log (with iOS framework flags appended) and needs a small -DOS target main()
 * that calls into libnode.a's node::Start.
 *
 * This is the same 3-line UNIX entry point Node's own src/node_main.cc uses
 * after its Windows-only prelude.
 */
#include <cstdio>

#include "node.h"

int main(int argc, char* argv[]) {
  return node::Start(argc, argv);
}
