# Optional iOS bridge integration

[Control API](https://github.com/Justintunsday/ios-control-bridge) supplies
fixed system-service operations. [iOSRemoteBridge](https://github.com/Justintunsday/iOSRemoteBridge)
supplies paired screenshots and UI input. OpenCode can use both from the same
session. Its provider and runtime configuration remain independent.

New packages include the optional `opencode-ios-bridge` command. Install Python
3.9+ and updated bridge sources/packages separately, and retain the private
pairing JSON from an existing iOSRemoteBridge installation. New upstream
iOSRemoteBridge packages include the Python backend under
`/var/jb/usr/lib/iosremotebridge`; an absolute checkout path is also supported.

Use `opencode debug paths` / `opencode debug config` to locate the actual server
configuration. A root-owned server can use a different home from its terminal
client. Preview setup first:

```sh
opencode-ios-bridge setup \
  --bridge-root /absolute/iOSRemoteBridge \
  --config /private/path/client-config.json \
  --opencode-config /actual/config/opencode.jsonc \
  --control
```

Append `--apply` to save. Omit `--control` for viewing only. Existing providers,
other MCP servers, instruction paths and unrelated JSONC comments are retained.
Changes have backups; repeated identical setup is a no-op. A conflicting server
name requires another `--server-name`.

The Control API package defaults to `/var/jb/usr/lib/ios-control-bridge`.
For a checkout, use `opencode-ios-bridge --icb-root /absolute/ios-control-bridge
setup ...`. `IOS_CONTROL_BRIDGE_ROOT` and `IOS_BRIDGE_PYTHON` override that root
and `/var/jb/usr/bin/python3` respectively. If this command is not yet installed,
run `python3 -B /absolute/ios-control-bridge/bin/iosctl opencode setup ...`.

Reload the OpenCode server and reopen its client after setup. For the optional
root server, restart the service after changing its configuration. Run
`opencode mcp list`, then check the integration with the same paths:

```sh
opencode-ios-bridge doctor \
  --bridge-root /absolute/iOSRemoteBridge \
  --config /private/path/client-config.json \
  --opencode-config /actual/config/opencode.jsonc
```

Doctor checks configuration, a real lazy MCP handshake, the 14-tool catalog and
local `iosctl` capabilities. It does not connect to or modify the phone.
Observe actual device info and an image through the model before claiming the
remote UI works. System-service readiness describes the machine running the
server; a desktop's `not_ios` is not the paired phone's state.

The generated instructions select fixed iosctl operations for supported services
and visual tools for visible UI tasks. Keep the screenshot → action → fresh
observation sequence, verify service writes by readback and release the single
remote session when finished. Setup does not enable root execution or Siri.

See the [full setup and validation contract](https://github.com/Justintunsday/ios-control-bridge/blob/main/docs/opencode-integration.md).

## Bundled skills

OpenCode packages contain the complete `opencode-ios` skill under
`/var/jb/usr/lib/opencode/skills/opencode-ios`. iOSRemoteBridge packages contain
`ios-computer-use` under `/var/jb/usr/lib/iosremotebridge/skills/ios-computer-use`.
The files are package-owned resources, including their references and metadata;
installing them does not overwrite user profiles or skill directories.

For OpenCode v2.2.5, add the desired package skill directory to the existing
configuration's `skills` array if it should participate in skill discovery.
Retain existing entries and avoid loading two copies of the same skill ID.
Other clients can reference the packaged skill directories directly.
