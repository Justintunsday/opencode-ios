# 移动 TUI 真机复验：node26test.6

2026-11-03，iPhone SE 2 / iOS 16.1.1 / Dopamine rootless。
**DEVICE-VERIFIED：新包安装、移动尺寸下的真实 OpenTUI、输入、缩放、三轮工具会话和退出。**
**NewTerm 持续闪烁的肉眼复验：PENDING。** 已请求用户在旧 TUI `/exit` 后重新运行 `opencode`，
尚未收到新版观感反馈。SSH 可以验证终端字节，不能证明手机合成器没有闪烁。
稳定 `v2.2.5-ios.5` release 未修改。

## 工件身份

| 工件 | run / 大小 / SHA-256 |
| --- | --- |
| CLI | [41631591793](https://github.com/Justintunsday/opencode-ios/actions/runs/41631591793)，21,403,769 B；`e4ea6bb07f3890c282b63b6ffd556a8ababf3abaaafe9835b1382c947fce519f` |
| OpenCode deb | [41632847889](https://github.com/Justintunsday/opencode-ios/actions/runs/41632847889)，`opencode` `2.2.5-3` / `node26test.6`，30,787,620 B；`7c2ca0c2c40d278969887356928ff374c36ef101deabe4dd3e59fd710f5e68b7` |
| 签名 renderer | [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506)，4,181,472 B；`4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868` |
| 独立 Node deb | [41620234785](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41620234785)，25,893,168 B；`c6cda114912707b5c229178449e0cc0a641fa7165c270a8dd81456196fed9e51` |
| Node 可执行文件 | [41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128)，134,710,336 B；`84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9` |

CI 源提交 `25eb185`，打包源提交 `c44e6e3`；19 个 CLI 补丁、2 个依赖补丁。
CLI 工件 25 个校验文件全部一致；deb 静态门禁 **68 PASS**，组合解包 37 个 app 文件通过。
Node、dylib 字节与上一版相同；OpenCode 精确依赖 `node26 (= 26.13.0-1)`，不内嵌 Node。

Azure 工件下载初次遇到连接超时。先安装了本地可复现构建，其 SHA 与 CI 实际日志完全相同；
随后已完整下载 CI zip（56,693,330 B，SHA `ab7c192b5e2f56f08ac23275342fd8198551dfc5e782a847558a1f034cabe80c`），
校验两个 deb 与报告，并逐字节确认 CI deb 等于安装的 deb。
CI 生成的 manifest/package-report 仍写 CI 范围的 device-unverified；本文件记录独立真机执行。

## 界面与绘制调整

依据 [pageton/tui-design-skill](https://github.com/pageton/tui-design-skill) 复用现有 Solid/OpenTUI 架构：
小屏首页显示 OpenCode / Ready / 常用命令，取消占七行的大字 Logo，输入区保留在底部。
窄屏减少边距、输入最多三行、菜单靠近顶部；最低 24×8，过小时显示尺寸提示而保留原编辑器。
iOS 默认关闭动画、使用不闪烁线形光标、合并 resize、限制 20 FPS，并输出完整 2026 同步帧。
显式用户动画/光标偏好仍有效。宽屏保留原桌面布局；iOS 使用基础键盘协议。

现有旧包的 SSH 空闲窗口也曾为零输出，因此不能从本次结果倒推 NewTerm 闪烁的唯一根因。
同步协议是否被终端实现，以及手机上的实际观感，仍需分开确认。

## 真机执行

所有功能验收使用私有 XDG 目录和本地 mock provider，没有使用真实 API key。
终端是 SSH 分配的真实 PTY；另有模拟旧终端的能力答复（2026 unsupported、固定颜色、VT attributes），
该能力模拟不等同 NewTerm。文本与 Enter 分开发送。

| 检查 | 实际结果 |
| --- | --- |
| dpkg 安装 | 12:09:14–12:09:17 UTC，rc=0；版本/精确依赖/Node/CLI/dylib SHA 一致 |
| runtime 基础 | `v26.13.0 ios`；ffi dlopen 为 function；wasm Memory 65536 B |
| 移动 PTY | 40×12 → 80×24 → 28×8 → 16×5 → 40×18；36.290 秒，`/exit` rc=0，未强制关闭 |
| 输入与缩放 | bracketed paste `中文 café é 👩‍💻 مرحبا`；放大、缩小、最小尺寸提示后草稿仍完整可见 |
| 三轮 TUI | 40×18，121.533 秒；三轮 shell 工具/回复，代码块纯文本回退，`/exit` rc=0 |
| CLI | --version、--help、debug paths/config、models、auth、session、非 TTY：8 PASS / 0 FAIL |
| 非 TTY | `opencode < /dev/null` 指引 + rc=1，无堆栈 |
| TERM=dumb 真 PTY | 指引 + rc=1，无 alternate screen / TUI 初始化 |
| NO_COLOR | headless CLI 按纯文本运行；没有宣称已验证完整 TUI 的 NO_COLOR 行为 |
| headless E2E | rc=0；6 行合法 JSON 事件；真实设备 shell 执行独立 node，marker/flags 验证通过 |
| 进程参数 | 私有子服务 `serve --stdio --port 0` 含 `--single-threaded` 与 512 MiB heap 参数 |
| 终端恢复 | 两次正常 TUI 退出前后 `stty -g` 一致，`TTY_RESTORED=PASS` |

40×12 原始输出经本地终端解释器重放后的可见文本（不是手机截图）：

```text
 OpenCode                         Ready
 /models  /sessions  /exit







 ┃ Ask about this project…
 ┃ Mock OpenCode Model
 Enter send                  / commands
```

原始转义序列确实包含 `opentui-notifications`、`app=opencode`、`ESC[?1049h` 和 OpenCode 窗口标题；
没有 `Interactive TUI is not available` 或 line-based REPL。正常退出摘录：

```text
... ESC[?1049l ... ESC[?25h ...
APP_RC=0
TTY_RESTORED=PASS
```

| 字节检查 | 移动缩放 | 三轮会话 |
| --- | --- | --- |
| 原始输出 B | 14270 | 40402 |
| 2026 begin / end | 12 / 12 | 164 / 164 |
| alternate screen 进入 / 退出 | 1 / 1 | 1 / 1 |
| `ESC[2J` | 0 | 0 |
| 空闲输出 | 10–11.9 秒：0 B | 12–19.5、44–49.5、74–79.5、110–119.5 秒：均 0 B |
| 原始输出 SHA-256 | `c540f7e5b4280afc3836dbf17a0449e75f7a23e9a1c06a3298e8dd14ac625a92` | `5956fcb6b3fcbb46ada620e29c9bc3c02a9473f44ba42cd5db1bfb0846e5028a` |

第一次 SSH 包装脚本缺少 `timeout --foreground`，Node 被终端作业控制暂停，160 秒后返回 137；
没有渲染，不计通过。修正测试脚本后才得到上面的真实输出。测试中的 resize 没有清屏/反复进出 alternate screen。

## 主机回归与限制

macOS CI 的移动布局/输入/配置/原生输出门禁 **33 PASS / 0 FAIL**，官方 TUI `typecheck:tsc` 通过；host Node 26.13.0
和信息性 24.22.2 smoke 均通过。Windows 移动测试重复十轮 70/0，终端输出测试重复十轮 30/0；
app/home-footer 相关回归 47 PASS / 2 SKIP / 0 FAIL。
全 TUI 套件为 **1583 PASS / 16 SKIP / 6 FAIL**；6 个失败在原始 17 补丁基线上复现一致
（4 个 plugin-source 本地 ESM reload、2 个 mini model label fixture）。没有把全套写成通过。
根目录 check 的 lint 通过，随后被本机 Astro Roaming 配置目录 EPERM 阻断；TUI 范围的官方 tsc 通过。

## 崩溃差分与清理

本次安装前基线 7 份 `.ips`，所有追加的 UI 与 Node 系统能力测试后为 12 份。
其中两份为 accessoryupdaterd / per-process-limit Jetsam，没有 Node 终止条目。
两份 Node SIGSYS 的栈顶为 shmget，来自随后执行的 System V 能力探测（20:25:40、20:27:43 +0800），
另有一次外层 timeout raise(SIGSYS) 记录；不是 TUI 会话中的 JIT SIGBUS。
完整 Node 操作结果见 [POSIX/JIT/wasm 报告](https://github.com/Justintunsday/nodejs26-ios/blob/main/docs/POSIX_JIT_WASM_DEVICE_RESULTS.md)。
本轮没有新的 SIGBUS。不能把包含能力探测的整轮写成“无 Node 崩溃”。

私有 mock pid 58762 和测试子进程已清理，rootless 测试库已移除；原有用户服务、TUI 和 REPL 保留。
`dpkg --verify node26 opencode` rc=0。原始命令结果、时间、raw PTY SHA、重放文本与崩溃摘要在
[结构化证据](evidence/mobile-tui-20261103.json)；完整 raw/log 文件保存在本地 `device/artifacts/mobile-tui-evidence/`。

真实 provider 的认证、计费/网络行为未使用真实 key 验收；tree-sitter worker、用户 worker_threads、
剪贴板、交互式工具 PTY 和无限时长稳定性限制继续适用。NewTerm 肉眼闪烁结果仍待反馈。
