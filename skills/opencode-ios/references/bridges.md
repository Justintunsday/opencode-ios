# 两个设备桥接通道

Control API 包 ID 为 `ios-control-bridge`，入口为 `iosctl`，实现与技能位于
`/var/jb/usr/lib/ios-control-bridge`。iOSRemoteBridge 后端与 Computer Use 技能
位于 `/var/jb/usr/lib/iosremotebridge`。两者可按需安装，不依赖特定模型账号。

已有配对时，使用 OpenCode 包内的固定配置入口：

```sh
opencode-ios-bridge setup \
  --bridge-root /var/jb/usr/lib/iosremotebridge \
  --config /absolute/private/client-config.json \
  --opencode-config /actual/server/config/opencode.jsonc \
  --control
```

上述文件路径需换成当前环境的实际路径。先看预览，带 `--apply` 后才保存；
保存有备份，已有 provider、其他 MCP 项和 JSONC 注释会保留。再以相同路径
运行 `opencode-ios-bridge doctor`。它检查惰性握手和 14 工具清单，不打开手机会话。

直接运行 `iosctl capabilities` 描述的是该终端所在主机；电脑返回 `not_ios`
不能推断配对手机的系统状态。使用已授权的手机终端执行系统操作，以准确 ID
或值调用固定适配器。App 安装、删除、设置修改后均独立读回。

视觉 MCP 的参数、图像和会话规则以 Remote Bridge 包内
`skills/ios-computer-use/SKILL.md` 为准。账号认证由用户在手机的正常系统界面
完成；配对 JSON、provider 密钥和个人画面不进入公开包体或日志。
