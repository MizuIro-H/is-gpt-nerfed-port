# is-gpt-nerfed — Windows / Linux 移植版

[English](README.md) · 简体中文

基于 [kiyoakii/is-gpt-nerfed](https://github.com/kiyoakii/is-gpt-nerfed) 的社区移植，使用 Python / PySide6 提供 Windows 和 Linux 桌面窗口与托盘。程序读取 Codex 会话记录，并通过 ModelTrace 探测比较所选模型与回答的统计指纹。

目前实现了两平台的**基本功能**。核心和校准库基于上游 **0.5.2**，commit `f9132f3c8fb9116964e7b5a61052f1aefe73d7be`，**未合入上游 0.5.3 更新**。`v0.5.2-port.1` 是移植发行版本号，包内核心仍显示 `0.5.2`。

## 下载与运行

从 [本 Fork 的 Releases](https://github.com/MizuIro-H/is-gpt-nerfed-port/releases/latest) 下载。GitHub 自动提供的 “Source code” 只包含源码，请下载下面的成品附件。

| 平台 | 便携包 | 启动方式 |
| --- | --- | --- |
| Windows 10/11 x64 | `IsGPTNerfed-0.5.2-port.1-windows-x64.zip` | 完整解压后运行 `IsGPTNerfed.exe` |
| Linux x86_64，glibc 2.35+ | `IsGPTNerfed-0.5.2-port.1-linux-x86_64.tar.gz` 或 `.zip` | 完整解压后运行 `./IsGPTNerfed` |

无需另装 Python 或 Qt。请一起保留 `_internal/`、核心程序、`plugin/`、`.agents/`、`licenses/`，以及 Windows 包内的 `wsl/`；只移动主程序会导致运行失败。Linux 需要图形桌面和 [平台指南](README-CROSSPLATFORM.md) 中列出的系统运行库。推荐 Linux 使用 TAR.GZ，保留执行权限与符号链接；ZIP 解压工具若丢失执行权限，请执行 `chmod +x IsGPTNerfed nerfed-core`。

先用 `SHA256SUMS.txt` 核对下载文件。Linux 可执行 `sha256sum -c SHA256SUMS.txt --ignore-missing`；Windows 在 PowerShell 中执行 `Get-FileHash .\IsGPTNerfed-0.5.2-port.1-windows-x64.zip -Algorithm SHA256`，比较十六进制结果。

1. 安装并登录支持插件 hooks 与 app-server 的 Codex；上游曾测试版本 0.154。
2. 打开“设置”，选择 Codex home 与可执行文件。Windows 可选本机或 WSL；选择 WSL 时填写对应发行版内部的 Linux 路径。WSL 核心同样要求 x86_64、glibc 2.35+。
3. 在“插件”页点击“安装插件”，并信任 hooks。该操作会在选定的 Codex home 注册插件；移动或更新程序后需重新执行。
4. 选择会话进行探测，查看证据、重试失败探测、复制报告；也可探测全新会话，并在设置中调整周期与登录自启动。

Windows 包带有 WSL 核心，选择发行版后自动部署。界面支持英文和简体中文。通过 `IsGPTNerfed.exe --demo` 或 `./IsGPTNerfed --demo` 可打开使用临时目录的离线演示。

## 检测方式

被动检查读取每轮记录中的模型、推理强度和上下文窗口变化，不发出模型请求。主动检查通过临时分叉默认收集三段随机数字回答，**会消耗你的 Codex 账户额度**。

ModelTrace 将回答与已校准模型库比较，给出匹配、可疑、降级、升级、重路由、未收录或无效等结果。它提供统计证据，不能直接证明服务端实际使用的权重；库外模型也可能被映射到相近模型。阈值、调度和方法说明见 [上游原版中文指南](docs/README-upstream.zh-CN.md)。

桌面版包含会话列表、报告、通知、手动/重试/新会话探测、插件安装、hooks 信任和设置。Windows/Linux 通过手动替换便携包更新，上游 macOS 自动更新器不适用于本移植。

## 从源码编译

先克隆本 Fork 并进入根目录：

```sh
git clone https://github.com/MizuIro-H/is-gpt-nerfed-port.git
cd is-gpt-nerfed-port
```

构建使用 Python 3.12、PySide6 6.11.2、PyInstaller 6.22.3，需要联网下载依赖。PyInstaller 按所在平台打包，因此 Windows 必须在原生 Windows 构建，Linux 在 Linux 环境构建。

**Linux：**安装 Docker Engine，或在 Docker Desktop 中为所用 WSL 发行版开启集成。确认 `docker info` 正常后执行：

```sh
bash packaging/build_linux_docker.sh
```

脚本在 Ubuntu 22.04 容器中构建，运行源码测试与离线界面/核心验收，输出桌面 TAR.GZ、独立 WSL 核心 TAR.GZ 及校验文件到 `Linux/dist/`。Docker 需能写入挂载的项目目录。Ubuntu 22.04 原生构建及开发调试命令见 [平台指南](README-CROSSPLATFORM.md#building-from-source)。

**Windows：**在 Windows PowerShell 5.1 或 PowerShell 7 中执行。先通过上面的 Linux 构建生成 `Linux/dist/nerfed-core-linux-x86_64.tar.gz`，也可从本仓库 Release 下载匹配版本的该附件并放入这个路径。然后在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1
```

脚本将 uv、Python、虚拟环境和缓存放在项目 `.build/` 内，安装固定版本依赖、编译、验收，再输出 `Windows/dist/IsGPTNerfed-0.5.2-windows-x64.zip` 及校验文件。如核心包位于其他目录，追加 `-LinuxCoreArchive "C:\path\nerfed-core-linux-x86_64.tar.gz"`。构建文件名使用核心版本号，Release 附件名另包含移植版本号。

也可打开本 Fork 的 **Actions → Build cross-platform desktop packages → Run workflow**。工作流先构建 Linux，再把 WSL 核心交给 Windows 构建；完成后下载两个 Actions 产物即可。工作流不自动创建 Release。

## 源码结构与限制

两平台共用 `desktop/`、`plugin/`、`packaging/` 和 `tests/`。本地 `Windows/`、`Linux/` 是已解压程序快照及构建产物，通过 `.gitignore` 排除，不上传到 Git 源码历史；编译成品通过 Release 附件分发。原始 `macos/` 源码和 [macOS 指南](docs/README-upstream.zh-CN.md) 仍保留，macOS 成品请到 [上游 Releases](https://github.com/kiyoakii/is-gpt-nerfed/releases) 获取。

验收使用隔离的演示数据和模拟 Codex app-server，覆盖界面渲染、冻结核心、插件注册、UTF-8 hooks 与后台工作进程；尚未覆盖所有 Linux 桌面、Windows 环境及真实 Codex 服务端。当前发行版未签名，无自动更新器。0.5.2 核心可能优先选中 PATH 中的旧 Codex，建议在设置中显式指定所需版本的可执行文件。

程序读取选定 Codex home 中的会话、模型缓存和账户信息；检测配置、记录和日志保存在其 `is-gpt-nerfed/` 子目录，桌面连接配置位于系统的用户配置目录。账户信息用于哈希和掩码地址。主动探测是账户下的普通远程推理，检测记录保留在本地；Windows/Linux 的更新检查默认关闭。更新和卸载步骤见 [平台指南](README-CROSSPLATFORM.md)。

## 贡献与许可

原项目及 macOS 程序由 [kiyoakii / Jin Li](https://github.com/kiyoakii/is-gpt-nerfed) 开发。移植由 [MizuIro-H](https://github.com/MizuIro-H) 维护，**OpenAI Codex** 提供 AI 辅助开发、检查与发布整理，详见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

感谢 [ModelTrace](https://github.com/xqy2006/ModelTrace) 的 MIT 许可指纹库、评分器与提示词，[hlwy-ai-checker](https://github.com/hanlinwenyuan/hlwy-ai-checker) 的随机数字思路，以及 [simple-term-menu](https://github.com/IngoMeyer441/simple-term-menu) 的 MIT 许可终端选择器。仓库使用 [MIT License](LICENSE)，包内第三方依赖遵循 `licenses/` 和 `NOTICE` 中的各自许可。
