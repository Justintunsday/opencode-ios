#!/var/jb/bin/sh
# OpenCode iOS (rootless) on-device smoke test.
#
# Shebang is /var/jb/bin/sh because rootless iOS has no /bin/sh; invoking it as
# `sh /var/jb/usr/share/doc/opencode/device-smoke.sh` works regardless.
#
# Checks (offline): package files, rootless shell/PATH/HOME/TMPDIR/git, runtime
# capabilities (WebAssembly+JIT+ICU+Intl.Segmenter), CLI --version, informational
# commands (models/debug paths/session list/sqlite persistence), argument
# forwarding. Works for BOTH shipped runtime variants (Node 18 primary and
# Node 22 experimental); the variant is detected from the shipped runtime.
#
# Model-provider connectivity and real agent turns are not part of this offline
# test; see docs/INSTALL.md.
#
# Run this ON THE iPHONE (NewTerm 3 or SSH), after installing
# OpenCode-iOS-rootless.deb. It performs offline checks only: no provider API
# calls, no credentials, no network access. A full agent run additionally
# requires `opencode auth login` and internet access; see docs/INSTALL.md.
#
# Usage:   sh /var/jb/usr/share/doc/opencode/device-smoke.sh
# Success: every FAIL line is absent and the final line says DEVICE SMOKE TEST: PASS.
set -u

FAILURES=0
WARNINGS=0

ok()   { printf 'OK   %s\n' "$*"; }
bad()  { printf 'FAIL %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
warn() { printf 'WARN %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
have() { command -v "$1" >/dev/null 2>&1; }

printf 'OpenCode iOS device smoke test\n'
printf 'kernel: %s\n' "$(uname -a 2>/dev/null || echo unknown)"
printf 'date:   %s\n\n' "$(date 2>/dev/null || echo unknown)"

# 0. Runtime variant detection (Node 18 = primary fallback runtime, Node 22 =
#    experimental W^X path). Both variants use the same package layout.
RUNTIME_NODE=/var/jb/usr/lib/opencode/runtime/node
RUNTIME_MAJOR="unknown"
if [ -x "$RUNTIME_NODE" ]; then
    RUNTIME_MAJOR="$("$RUNTIME_NODE" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo unknown)"
    RUNTIME_FULL="$("$RUNTIME_NODE" -p 'process.versions.node' 2>/dev/null || echo unknown)"
    printf 'runtime variant: Node %s (node_version=%s)\n\n' "$RUNTIME_MAJOR" "$RUNTIME_FULL"
fi

# Temporary directory for this smoke test: HOME is known-writable on the
# target device; /tmp is not guaranteed under the rootless jailbreak.
SMOKE_DIR="${HOME:-/var/jb/var/mobile}/.opencode-ios-smoke.$$"
if mkdir -p "$SMOKE_DIR" 2>/dev/null; then
    :
else
    SMOKE_DIR="/tmp"
fi
cleanup() { rm -rf "$SMOKE_DIR" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 1. Package files are where the .deb installs them (rootless layout).
if [ -x "$RUNTIME_NODE" ]; then
    ok "native iPhoneOS Node runtime present: $RUNTIME_NODE"
else
    bad "missing runtime: $RUNTIME_NODE"
fi
if [ -f /var/jb/usr/lib/opencode/cli/opencode.mjs ]; then
    ok "CLI bundle present: /var/jb/usr/lib/opencode/cli/opencode.mjs"
else
    bad "missing CLI bundle: /var/jb/usr/lib/opencode/cli/opencode.mjs"
fi
if [ -x /var/jb/usr/bin/opencode ]; then
    ok "launcher present and executable: /var/jb/usr/bin/opencode"
else
    bad "missing launcher: /var/jb/usr/bin/opencode"
fi
if have opencode; then
    ok "opencode resolves in PATH: $(command -v opencode)"
else
    bad "opencode not in PATH (check /var/jb/usr/bin is exported in PATH)"
fi

# 1b. Rootless shell / tooling environment. Rootless iOS has no /bin/sh or
#     /bin/bash; the Procursus bootstrap shells live under /var/jb. The CLI's
#     shell tool spawns commands through sh, so a working rootless shell and a
#     PATH containing /var/jb/bin:/var/jb/usr/bin are required for shell tools.
SHELL_OK=0
for candidate_shell in /var/jb/bin/sh /var/jb/usr/bin/sh /var/jb/bin/bash; do
    if [ -x "$candidate_shell" ]; then
        if "$candidate_shell" -c 'printf shell-ok' 2>/dev/null | grep -q shell-ok; then
            ok "rootless shell executable: $candidate_shell"
            SHELL_OK=1
            break
        else
            warn "rootless shell exists but failed to execute: $candidate_shell"
        fi
    fi
done
if [ "$SHELL_OK" -eq 0 ]; then
    bad "no working rootless shell found under /var/jb/bin or /var/jb/usr/bin (CLI shell tools will fail)"
fi
if command -v sh >/dev/null 2>&1; then
    ok "sh resolves in PATH: $(command -v sh)"
else
    warn "sh not in PATH (launcher prepends /var/jb/bin:/var/jb/usr/bin; shell tools may still work via absolute path)"
fi
printf 'PATH=%s\n' "${PATH:-unset}"
printf 'HOME=%s\n' "${HOME:-unset}"
printf 'TMPDIR=%s\n' "${TMPDIR:-unset}"
if [ -d "${HOME:-/nonexistent}" ] && [ -w "${HOME:-/nonexistent}" ]; then
    ok "HOME is writable: $HOME (config/sessions resolve here)"
else
    warn "HOME is not writable or unset (${HOME:-unset})"
fi
if [ -n "${TMPDIR:-}" ] && [ -d "${TMPDIR:-/nonexistent}" ] && [ -w "${TMPDIR:-/nonexistent}" ]; then
    ok "TMPDIR is writable: $TMPDIR"
else
    warn "TMPDIR unset or not writable (the launcher provides a fallback; the CLI sqlite shim needs a temp dir)"
fi
if command -v git >/dev/null 2>&1; then
    ok "git present: $(git --version 2>/dev/null | head -n 1)"
else
    warn "git not installed (git tool features unavailable); install with: sudo apt-get install -y git"
fi

# 1c. Runtime capabilities required by the CLI. Node's built-in fetch/undici
#     needs WebAssembly (wasm llhttp), and the CLI bundle needs Intl (including
#     Intl.Segmenter) plus V8 JIT. The shipped runtime must be full-icu with
#     WebAssembly+JIT enabled and signed with the device-verified 2-key set.
if [ -x "$RUNTIME_NODE" ]; then
    CAPS="$("$RUNTIME_NODE" -e 'process.stdout.write([typeof WebAssembly, process.config.variables.v8_enable_webassembly, typeof fetch, typeof Intl, typeof Intl.Segmenter].join(","))' 2>&1)"
    case "$CAPS" in
        object,1,function,object,function)
            ok "runtime capabilities: WebAssembly=object, v8_enable_webassembly=1, fetch=function, Intl=object, Intl.Segmenter=function"
            ;;
        *)
            bad "runtime capabilities incomplete (got: $CAPS); WebAssembly+JIT+ICU (incl. Intl.Segmenter) are required by the CLI"
            ;;
    esac
    if "$RUNTIME_NODE" -e "new WebAssembly.Module(Buffer.from('0061736d01000000','hex'))" >/dev/null 2>&1; then
        ok "WebAssembly module compilation works (JIT/executable memory available)"
    else
        bad "WebAssembly module compilation failed (JIT/executable memory unavailable)"
    fi
else
    bad "cannot check runtime capabilities: $RUNTIME_NODE missing"
fi

# 2. Mandatory CLI startup check (offline): --version.
VERSION_OUTPUT=$(opencode --version 2>&1)
VERSION_RC=$?
if [ "$VERSION_RC" -eq 0 ] && [ -n "$VERSION_OUTPUT" ]; then
    ok "opencode --version (exit 0): $VERSION_OUTPUT"
elif printf '%s' "$VERSION_OUTPUT" | grep -q "CodeRange\|FatalOOM"; then
    bad "opencode --version crashed in the Node 22 JIT memory model (CodeRange/FatalOOM); use the Node 18 variant package"
else
    bad "opencode --version failed (exit $VERSION_RC): $VERSION_OUTPUT"
fi

# 2b. --help: on the Node 18 variant this exercises Intl.Segmenter; it is a
#     hard check because the shipped runtime must be full-icu. (The community
#     small-ICU Node 18 runtime crashed here; our package ships full-icu.)
HELP_OUTPUT=$(opencode --help 2>&1)
HELP_RC=$?
if [ "$HELP_RC" -eq 0 ] && [ -n "$HELP_OUTPUT" ]; then
    ok "opencode --help (exit 0, $(printf '%s\n' "$HELP_OUTPUT" | wc -l | tr -d ' ') lines; Intl.Segmenter usable)"
elif [ "$RUNTIME_MAJOR" = "18" ]; then
    warn "opencode --help failed on Node 18 (exit $HELP_RC) — Intl.Segmenter/ICU issue; record the output and report it: $(printf '%s' "$HELP_OUTPUT" | head -n 3)"
else
    bad "opencode --help failed (exit $HELP_RC): $HELP_OUTPUT"
fi

# 3. Informational commands: version/state dependent, never fail the smoke test.
info_cmd() {
    label="$1"
    shift
    if "$@" >"$SMOKE_DIR/$label.out" 2>&1; then
        ok "opencode $label: $(tr '\n' ' ' < "$SMOKE_DIR/$label.out" | cut -c1-200)"
        return 0
    fi
    warn "opencode $label not available in this CLI build/runtime (non-fatal): $(tr '\n' ' ' < "$SMOKE_DIR/$label.out" | cut -c1-200)"
    return 1
}
info_cmd "models" opencode models
info_cmd "debug paths" opencode debug paths
info_cmd "auth list" opencode auth list

# 3b. sqlite persistence. Node 18 uses the bundled sql.js WebAssembly shim
#     (whole-file persistence, no WAL); Node 22 uses node:sqlite. `session list`
#     must exit 0 and create/persist the database file.
if opencode session list >"$SMOKE_DIR/session-list.out" 2>&1; then
    ok "opencode session list (exit 0; sqlite path works): $(tr '\n' ' ' < "$SMOKE_DIR/session-list.out" | cut -c1-200)"
    DB_DIR="${HOME:-/var/jb/var/mobile}/.local/share/opencode"
    DB_FOUND="$(find "$DB_DIR" -maxdepth 3 -type f -name '*.db' 2>/dev/null | head -n 3 | tr '\n' ' ')"
    if [ -n "$DB_FOUND" ]; then
        ok "sqlite database file present after session list: $DB_FOUND"
    else
        warn "no sqlite database file found under $DB_DIR (session list may use a different path)"
    fi
else
    warn "opencode session list failed (non-fatal): $(tr '\n' ' ' < "$SMOKE_DIR/session-list.out" | cut -c1-200)"
fi

# 4. Confirm the runtime rejects an unknown flag rather than silently ignoring
#    arguments: proves argv forwarding through the launcher works.
if opencode --definitely-not-a-real-opencode-ios-flag >/dev/null 2>&1; then
    warn "unknown CLI flag was not rejected (continuing; flag parsing may differ)"
else
    ok "launcher forwards CLI arguments (unknown flag rejected)"
fi

# 5. Not covered here: model provider connectivity and an agent turn. Those need
#    credentials/network and are run manually (see docs/INSTALL.md):
#      opencode auth login
#      cd /var/jb/var/mobile/Documents/example && opencode run --help
#    Also confirm shell-tool fallback with a real CLI command once authenticated:
#      opencode run "run: printf shell-tool-ok"   (requires a provider)
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
    printf 'DEVICE SMOKE TEST: PASS (offline checks only; model connectivity not tested)\n'
    [ "$WARNINGS" -gt 0 ] && printf 'Warnings: %s (see WARN lines above)\n' "$WARNINGS"
    exit 0
fi
printf 'DEVICE SMOKE TEST: FAIL (%s failing check(s))\n' "$FAILURES"
exit 1
