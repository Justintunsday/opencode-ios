#!/var/jb/bin/sh
# OpenCode iOS (rootless) on-device smoke test.
#
# Shebang is /var/jb/bin/sh because rootless iOS has no /bin/sh; invoking it as
# `sh /var/jb/usr/share/doc/opencode/device-smoke.sh` works regardless.
#
# Run this ON THE iPHONE (NewTerm 3 or SSH), after installing
# OpenCode-iOS-rootless.deb. It performs offline checks only: no provider API
# calls, no credentials, no network access. A full agent run additionally
# requires `opencode auth login` and internet access; see docs/INSTALL.md.
#
# Usage:   sh /var/jb/usr/share/doc/opencode/device-smoke.sh
# Success: every line is OK and the final line says DEVICE SMOKE TEST: PASS.
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

# 1. Package files are where the .deb installs them (rootless layout).
if [ -x /var/jb/usr/lib/opencode/runtime/node ]; then
    ok "native iPhoneOS Node runtime present: /var/jb/usr/lib/opencode/runtime/node"
else
    bad "missing runtime: /var/jb/usr/lib/opencode/runtime/node"
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
if [ -d "${HOME:-/nonexistent}" ] && [ -w "${HOME:-/nonexistent}" ]; then
    ok "HOME is writable: $HOME (config/sessions resolve here)"
else
    warn "HOME is not writable or unset (${HOME:-unset})"
fi
if command -v git >/dev/null 2>&1; then
    ok "git present: $(git --version 2>/dev/null | head -n 1)"
else
    warn "git not installed (git tool features unavailable); install with: sudo apt-get install -y git"
fi

# 2. Mandatory CLI startup checks (offline).
VERSION_OUTPUT=$(opencode --version 2>&1)
VERSION_RC=$?
if [ "$VERSION_RC" -eq 0 ] && [ -n "$VERSION_OUTPUT" ]; then
    ok "opencode --version (exit 0): $VERSION_OUTPUT"
else
    bad "opencode --version failed (exit $VERSION_RC): $VERSION_OUTPUT"
fi

HELP_OUTPUT=$(opencode --help 2>&1)
HELP_RC=$?
if [ "$HELP_RC" -eq 0 ] && [ -n "$HELP_OUTPUT" ]; then
    ok "opencode --help (exit 0, $(printf '%s\n' "$HELP_OUTPUT" | wc -l | tr -d ' ') lines)"
else
    bad "opencode --help failed (exit $HELP_RC): $HELP_OUTPUT"
fi

# 3. Informational commands: version-dependent, never fail the smoke test.
if opencode debug paths >/tmp/opencode-ios-smoke-paths.txt 2>&1; then
    ok "opencode debug paths: $(tr '\n' ' ' < /tmp/opencode-ios-smoke-paths.txt | cut -c1-200)"
else
    warn "opencode debug paths not available in this CLI build (non-fatal)"
fi
if opencode auth list >/tmp/opencode-ios-smoke-auth.txt 2>&1; then
    ok "opencode auth list (offline): $(tr '\n' ' ' < /tmp/opencode-ios-smoke-auth.txt | cut -c1-200)"
else
    warn "opencode auth list failed (no credentials configured yet is normal; non-fatal)"
fi
rm -f /tmp/opencode-ios-smoke-paths.txt /tmp/opencode-ios-smoke-auth.txt

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
