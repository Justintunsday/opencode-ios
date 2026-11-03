#!/var/jb/bin/sh
# Installs the optional root-owned OpenCode server (run with sudo).
# The service is enabled immediately; it is not auto-enabled by the OpenCode deb.
#
# Security model: the server runs as root, listens only on 127.0.0.1:4097 and
# requires HTTP Basic auth with a random password. The TUI client (`opencode-root`)
# runs as the calling user (mobile). Any process that can read the mobile-readable
# password copy can connect to the root server, so this is an explicit
# privilege-escalation trade-off for a jailbroken single-user device.
set -eu
PREFIX=/var/jb
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

ROOT_PW_DIR="$PREFIX/var/root/.config/opencode-root"
CLIENT_PW_DIR="$PREFIX/var/lib/opencode-root"
LOG_DIR="$PREFIX/var/log"
PLIST_DEST="$PREFIX/Library/LaunchDaemons/com.opencode.root-server.plist"

mkdir -p "$ROOT_PW_DIR" "$CLIENT_PW_DIR" "$LOG_DIR" "$PREFIX/usr/local/libexec"
chmod 700 "$ROOT_PW_DIR"
chmod 755 "$CLIENT_PW_DIR"
chown root:wheel "$ROOT_PW_DIR" "$CLIENT_PW_DIR" "$LOG_DIR"
chmod 640 "$LOG_DIR" 2>/dev/null || true

if [ ! -s "$ROOT_PW_DIR/server-password" ]; then
    "$PREFIX/usr/bin/node" --single-threaded -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("base64url"))' > "$ROOT_PW_DIR/server-password"
    chmod 600 "$ROOT_PW_DIR/server-password"
    chown root:wheel "$ROOT_PW_DIR/server-password"
fi
cp "$ROOT_PW_DIR/server-password" "$CLIENT_PW_DIR/server-password"
chown root:mobile "$CLIENT_PW_DIR/server-password"
chmod 640 "$CLIENT_PW_DIR/server-password"

install -m 755 -o root -g wheel "$SOURCE_DIR/opencode-root-server" "$PREFIX/usr/local/libexec/opencode-root-server"
install -m 755 -o root -g wheel "$SOURCE_DIR/opencode-root" "$PREFIX/usr/bin/opencode-root"
install -m 755 -o root -g wheel "$SOURCE_DIR/opencode-root-service" "$PREFIX/usr/bin/opencode-root-service"
install -m 644 -o root -g wheel "$SOURCE_DIR/com.opencode.root-server.plist" "$PLIST_DEST"

launchctl unload -w "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"
echo "opencode-root-service: installed and started (127.0.0.1:4097, HTTP Basic auth)"
echo "usage: opencode-root        # TUI client against the root server"
echo "       sudo opencode-root-service stop|start|status"
