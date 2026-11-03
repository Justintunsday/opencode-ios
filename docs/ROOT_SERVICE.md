# 可选：root 后台服务（OpenCode 以 root 执行工具）

这是可选的**高权限模式**：OpenCode 的服务端以 root 运行，TUI 仍以调用者（mobile）运行。
不是默认安装的一部分，也不会被 deb 自动启用；需要手动运行安装脚本。

## 模型

- 服务端：LaunchDaemon `com.opencode.root-server`，以 root 运行
  `opencode serve --hostname 127.0.0.1 --port 4097`；
- 认证：HTTP Basic，用户名固定 `opencode`，密码为安装时生成的 32 字节随机串；
  - 服务端密码文件：`/var/jb/var/root/.config/opencode-root/server-password`（root 600）
  - 客户端可读副本：`/var/jb/var/lib/opencode-root/server-password`（root:mobile 640）
- 客户端：`opencode-root` 启动 TUI 并连接 `http://127.0.0.1:4097`；
- 服务端只监听 loopback，不对局域网/公网暴露。

## 安装 / 启停

把本目录复制到设备（例如 `/var/mobile/ocdev/node26/root-service/`），然后：

```sh
sudo /var/jb/bin/sh /var/mobile/ocdev/node26/root-service/install-root-service.sh
opencode-root                 # 以 root 服务运行 TUI（工具以 root 执行）
sudo opencode-root-service status
sudo opencode-root-service stop
sudo opencode-root-service start
```

`install-root-service.sh` 会生成随机密码、安装脚本与 LaunchDaemon 并立即启动。

## 安全警告（重要）

- 该模式让 OpenCode 的 shell/工具以 **root** 执行；请只在自己信任的越狱设备上使用。
- 客户端密码副本对 `mobile` 用户可读：**任何能读取该文件的本地进程都可以连接 root 服务并执行命令**。
  这是本机提权面，不是网络暴露面。
- 服务端有独立的 root 配置/数据目录（`/var/jb/var/root/.config/opencode`、
  `/var/jb/var/root/.local/share/opencode`），与 mobile 的 OpenCode 配置隔离；需要单独配置 provider/API key。
- 不需要时可随时 `sudo opencode-root-service stop`，或删除 LaunchDaemon plist 后重启。
- 本功能仅验证于 iPhone SE 2 / iOS 16.1.1 / Dopamine rootless；不要在未理解后果的设备上启用。