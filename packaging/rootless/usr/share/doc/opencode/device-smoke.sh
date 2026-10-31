#!/bin/sh
# OpenCode iOS (rootless) on-device smoke test.
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
#      cd /var/mobile/Documents/example && opencode run --help
printf '\n'
if [ "$FAILURES" -eq 0 ]; then
    printf 'DEVICE SMOKE TEST: PASS (offline checks only; model connectivity not tested)\n'
    [ "$WARNINGS" -gt 0 ] && printf 'Warnings: %s (see WARN lines above)\n' "$WARNINGS"
    exit 0
fi
printf 'DEVICE SMOKE TEST: FAIL (%s failing check(s))\n' "$FAILURES"
exit 1
