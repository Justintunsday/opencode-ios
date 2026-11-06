---
name: opencode-ios
description: 配置、运行和排查越狱 iPhone 上的 OpenCode 终端或服务端，并连接 Control API 与 iOSRemoteBridge。用于 OpenCode iOS 包、运行身份、模型配置和设备桥接；普通 iOS 开发不适用。
---

# OpenCode iOS

本技能随 OpenCode 包保存在 `/var/jb/usr/lib/opencode/skills/opencode-ios`。
使用已安装的运行时与当前用户授权，不自行切换 provider 或启用 root 服务。

## 确认运行环境

先运行 `opencode --version`、`opencode debug paths` 和 `opencode debug config`。
区分手机上的进程与电脑上的客户端；后台服务的用户、目录和配置可能不同。
`debug paths` 是文本输出，`debug config` 在 v2.2.5 中是配置条目列表，不能
假定是单一 JSON 对象。输出中只保留排查所需信息，不显示完整 provider 密钥。

当前 rootless 包由独立 `node26` 包提供运行时，启动器位于 `/var/jb/usr/bin/opencode`。
保留包启动器的 Node/V8 参数及运行时资产路径；不要替换成电脑的 Bun、Node
或修改系统分区。运行时与 OpenTUI 的限制见包内 `/var/jb/usr/share/doc/opencode`。

配置调整沿用用户已有授权，先读取实际文件，仅修改所需字段并保留其余配置。
认证错误先区分 provider、运行身份和服务端缓存；密钥变更后按原部署方式
重载服务。不以一次请求失败判断整个账号不可用，不把密钥写进技能或仓库。

## iPhone 服务与视觉操作

连接方法见 [bridges.md](references/bridges.md)。Control API 提供 `iosctl`
固定系统操作，iOSRemoteBridge 提供已配对的屏幕与输入；两种通道分别验收。

系统操作先读 `iosctl capabilities`，只调用 implemented 且 runtime ready 的
操作，写后读回。保留 verified / partial / unavailable / error、来源、时间与
范围。App Store 等待手机认证或下载时只查询状态，不重复发起结果不明的请求。

视觉任务读取 Remote Bridge 包内的 `ios-computer-use` 技能。先查看实际图片，
一次动作后重新观察；普通 Unicode 输入使用 `insert_text`。只持有一个会话，
结束后断开。视觉配对不包含 SSH 权限，也不能代替系统服务的结果验证。

技能随包提供，是否自动发现取决于客户端配置。OpenCode v2.2.5 可在已有配置的
`skills` 数组中加入 `/var/jb/usr/lib/opencode/skills`；先检查当前格式并保留
已有项，不覆盖整份配置。包安装不会修改个人技能目录或 provider 配置。
