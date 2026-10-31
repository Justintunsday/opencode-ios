# Bun compile-target probe (host evidence)

Host: Windows x64, Bun 1.4.2 (pinned CI version is 1.4.4; the CI verification workflow repeats
this probe with 1.4.4).

```
$ bun build --compile --target=bun-ios-arm64 ./hello.ts --outfile hello-ios
error: Unsupported target "ios" in "bun-ios-arm64"
To see the supported targets:
  https://bun.com/docs/bundler/executables
```

Supported compile targets are exactly the nine listed in docs/BUN_FEASIBILITY.md.
