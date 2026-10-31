# Team coordination (Agent Teams)

Repo: https://github.com/Justintunsday/opencode-ios (public) — dedicated port repository.
Local working tree: `C:\opencode\port` (git repo, branch `main`, remote `origin`).

## Hard rules

1. Never modify the upstream OpenCode/Bun/nodejs-mobile repositories. All upstream changes are
   patches applied at CI time (`patches/**`).
2. Never commit `upstream/` checkouts, `node_modules/`, build outputs, or secrets.
3. File ownership is exclusive. Only edit files inside your declared scope. Shared files
   (`README.md`, `UPSTREAM.lock`, `docs/ARCHITECTURE.md`) are Lead-owned.
4. Push discipline: `git add <your files> && git commit -m "..." && git pull --rebase && git push`.
   Never `git add -A` (avoids sweeping another member's in-progress work). Never force-push.
5. Every CI milestone gets a commit. Do not rewrite history.
6. Read the complete GitHub Actions failure log before changing anything (`gh run view <id>
   --log-failed`). Fix root causes; never disable validation or swallow errors to get green.
7. Report honestly: CI-green ≠ device-verified. Device-only results stay marked
   `UNVERIFIED ON DEVICE`.

## Artifact contract (workflows depend on these names)

| Artifact name | Producer | Contents |
| --- | --- | --- |
| `ios-node-runtime` | build-runtime.yml | `node` (iPhoneOS arm64), `entitlements.plist`, `runtime-manifest.json`, `SHA256SUMS` |
| `opencode-cli-node-ios` | build-opencode.yml | `opencode.mjs`, `assets/**`, `bundle-manifest.json`, `SHA256SUMS` |
| `OpenCode-iOS-rootless` | package-rootless.yml | `OpenCode-iOS-rootless.deb`, `SHA256SUMS`, `package-report.json` |
| `port-verification` | test-port.yml | `verification-report.json`, `verification-report.md`, tests log |

## Inter-workflow artifact reuse

`package-rootless.yml` and `test-port.yml` download the most recent **successful** run of
`build-runtime.yml` / `build-opencode.yml` on `main` via the GitHub API using `GITHUB_TOKEN`
(`actions: read`). They do not rebuild those components. Both workflows also accept
`workflow_dispatch` inputs (`runtime_run_id`, `opencode_run_id`) to pin a specific run.

## Scrumbag / progress

- Runtime: Node 22.9.0 iPhoneOS build via nodejs-mobile update22-9-0 + PR #150 fixes.
- CLI: upstream `build-node` Vite bundle (`--bundle-only`) + iOS prelude/optional-native patches.
- Package/test: rootless .deb assembly + static audits; device tests remain user-executed.

## Lead

Lead owns: repo bootstrap, `UPSTREAM.lock`, `README.md`, `docs/ARCHITECTURE.md`, integration,
final deliverable answer. Ask Lead for decisions that change the architecture.
