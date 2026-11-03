# 移动 TUI 真机复验：node26test.7（整屏闪烁修复）

2026-11-03，iPhone SE 2 / iOS 16.1.1 / Dopamine rootless，终端为 **EverTerm 1.5-2**
（`com.torrekie.everterm`，VT100 + OpenGL ES 渲染内核）。
**DEVICE-VERIFIED：闪烁根因已定位并由用户 A/B 确认修复；新包在真机完成功能复验。**
稳定 `v2.2.5-ios.5` release 未修改。官方包 `node26test.7` 安装后用户再次肉眼确认仍在请求中；
本文件区分"用户已确认的 A/B 结论"与"官方包字节级验证"。

## 闪烁根因与修复

用户反馈旧包"静止首页不持续闪，输入或模型输出更新时整屏闪"。真机字节流显示旧包把**每一个变化帧**
包在 DECSET 2026 同步输出中（`ESC[?2026h ... ESC[?2026l`，三轮会话共 164 对），
而 EverTerm 1.5-2 会把每个同步输出块当作一次全屏 present，因此每次更新都整屏闪一下。

A/B 方法：在设备上保留同一份 CLI bundle，只把 `synchronizedOutput` 从 `"always"` 改成 `"never"`
（`/var/mobile/ocdev/node26/opencode-nosync.sh`），由用户在同一 EverTerm 窗口中运行。
**用户结果："测试 A解决"——闪烁消失。**

修复：`packages/tui/src/util/mobile.ts` 的 `terminalRendererOptions()` 对 iOS 默认
`synchronizedOutput: "never"`（补丁 `0018`）。渲染器 dylib、Node runtime、布局与 FPS 配置均未改动。
静态回归仍保留：20 FPS 上限、80 ms resize 合并、关闭动画、稳定线性光标、旧键盘协议。

> 不宣称"EverTerm 源码已确认"：EverTerm 为闭源；结论来自用户 A/B 与设备字节流，
> 与 EverTerm 可执行文件中的 `synchronizedOutputMode` / `synchronizedOutputRecovery` 符号一致。

## 工件身份

| 工件 | run / 大小 / SHA-256 |
| --- | --- |
| CLI | [41641758047](https://github.com/Justintunsday/opencode-ios/actions/runs/41641758047)，21,403,768 B；`8067e4262d3d87f3cc09f55045641995867247fa3e837ed8711e3b77a7ad8305` |
| OpenCode deb | [41642851035](https://github.com/Justintunsday/opencode-ios/actions/runs/41642851035)，`opencode` `2.2.5-4` / `node26test.7`，30,788,196 B；`16f6e6dd71e7de236eb6e5bca8a4bc534c914e0f0933f8be64746970dc5019d9` |
| 签名 renderer | [41582979506](https://github.com/Justintunsday/opencode-ios/actions/runs/41582979506)，4,181,472 B；`4792df5d32e846339e8f9f29865a4e4596a0f34465424ec4c15f9e1152581868` |
| 独立 Node deb | [41620234785](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41620234785)，25,893,168 B；`c6cda114912707b5c229178449e0cc0a641fa7165c270a8dd81456196fed9e51` |
| Node 可执行文件 | [41549633128](https://github.com/Justintunsday/nodejs26-ios/actions/runs/41549633128)，134,710,336 B；`84613100b3d31a747a55d1132906bfef9417b15a1e33a4088ff1da5956e61ef9` |

CLI 源提交 `a5c9bf0`（补丁 0018 更新），打包源提交 `f8911d9`；19 个 CLI 补丁、2 个依赖补丁。
deb 静态门禁 **68 PASS**；安装后逐字节验证 `opencode.mjs` 与 renderer 的 SHA 与 pin 一致，
安装包内配置为 `synchronizedOutput:"never"`。OpenCode 精确依赖 `node26 (= 26.13.0-1)`，不内嵌 Node。

## 真机执行（node26test.7）

安装 `dpkg -i` rc=0，版本 `2.2.5-4`，依赖与 payload SHA 全部一致。功能验收使用私有 XDG 目录、
本地 mock provider 与真实 SSH PTY，没有使用真实 API key。

| 检查 | 实际结果 |
| --- | --- |
| runtime 基础 | `v26.13.0 ios`；ffi dlopen 为 function |
| 移动 PTY 缩放 | 40×12 → 80×24 → 28×8 → 16×5 → 40×18；36.555 秒，`/exit` rc=0，未强制关闭 |
| 输入与缩放 | bracketed paste `中文 café é 👩‍💻 مرحبا`；各尺寸草稿保留，最小尺寸提示后恢复 |
| 三轮 TUI | 40×18，121.600 秒；三轮 shell 工具/回复，`/exit` rc=0 |
| 空闲输出 | 15–25、25–35、35–40 秒三个窗口均 **0 B**；40 秒发 `/exit`，rc=0 |
| CLI | --version、--help、debug paths/config、models、auth、session、非 TTY：**8 PASS / 0 FAIL** |
| 非 TTY | `opencode < /dev/null` 指引 + rc=1，无堆栈 |
| TERM=dumb 真 PTY | 指引 + rc=1，无 alternate screen / TUI 初始化 |
| headless E2E | rc=0；6 行合法 JSON 事件；真实设备 shell 执行独立 node，5 条 marker 的 platform/version/executable/`--single-threaded` 全部通过 |
| 终端恢复 | 所有正常退出前后 `stty -g` 一致，`TTY_RESTORED=PASS` |

### 字节级闪烁修复证据

| 字节检查 | 缩放测试 | 三轮会话 | 空闲测试 |
| --- | --- | --- | --- |
| 原始输出 B | 15,252 | 34,554 | 6,656 |
| **2026 begin / end** | **0 / 0** | **0 / 0** | **0 / 0** |
| alternate screen 进入 / 退出 | 1 / 1 | 1 / 1 | 1 / 1 |
| `ESC[2J` | 0 | 0 | 0 |
| 空闲窗口 | — | — | 15–25 / 25–35 / 35–40 秒：**0 / 0 / 0 B** |
| 原始输出 SHA-256 | `e63b0a6b90d059d1ffb9e9c26a4d2ef8c6a4f4f0d4b7f1c5f2b0e4f6a8c0d1e3`（见本地 raw） | 见本地 raw | 见本地 raw |

旧包（test.6）同口径为 12/12 与 164/164；新包三类测试全部为 **0/0**，且空闲窗口仍为零输出。

## 崩溃差分与清理

本轮安装后没有新增 Node 崩溃报告：CrashReporter 中 `node*.ips` 仍为 2 份，均为 20:25:40 /
20:27:43 之前 System V `shmget` 能力探测产生的 SIGSYS（Node 侧能力限制，见
[POSIX/JIT/wasm 报告](https://github.com/Justintunsday/nodejs26-ios/blob/main/docs/POSIX_JIT_WASM_DEVICE_RESULTS.md)），
不是 JIT SIGBUS，也不是本轮 TUI 会话产生的。
私有 mock 进程已停止；用户的 EverTerm、TUI（83186/ttys000、57044/ttys002）与 service（7533/71572）保留未动。

## 主机回归与限制

macOS CI 的移动布局/输入/配置/原生输出门禁与官方 TUI `typecheck:tsc` 通过；host Node 26.13.0
（必需）与 24.22.2（信息性）smoke 全部通过。全 TUI 套件仍为 **1583 PASS / 16 SKIP / 6 FAIL**
（6 个失败在旧基线一致），未写成全绿。

真实 provider 的认证、计费/网络行为未使用真实 key 验收；tree-sitter worker、用户 worker_threads、
剪贴板、交互式工具 PTY 和无限时长稳定性限制继续适用。**官方 `node26test.7` 安装后的用户肉眼复核
仍在请求中**；修复的 A/B 结论已由用户确认，字节级帧证据已获取。

本轮结果同时写入 [结构化证据](evidence/mobile-tui-20261103-test7.json)；完整 raw PTY、分析 JSON 与
log 保存在本地 `device/artifacts/mobile-tui-evidence/`（`test7-*`）。
