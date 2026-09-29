# Windows / Linux 平台指南

[项目简介（中文）](README.zh-CN.md) · [English README](README.md) · [Release 下载](https://github.com/MizuIro-H/is-gpt-nerfed-port/releases/latest)

此移植基于上游 [`kiyoakii/is-gpt-nerfed`](https://github.com/kiyoakii/is-gpt-nerfed) commit `f9132f3c8fb9116964e7b5a61052f1aefe73d7be`（0.5.2）。它在原有 `nerfed` 核心外提供 PySide6 桌面界面。目标平台是 Windows 10/11 x64、WSL 2 与 Linux x86_64（glibc 2.35 起）；Windows ZIP 中带有可自动部署到 WSL 的 Linux 核心包。构建使用 Python 3.12、PySide6 6.11.2 和 PyInstaller 6.22.3。

## 本地目录管理

两套已构建版本分别放在仓库根目录的 `Windows/` 和 `Linux/`：

| 内容 | Windows 移植 | Linux 移植 |
| --- | --- | --- |
| 可运行程序 | `Windows/IsGPTNerfed.exe` | `Linux/IsGPTNerfed` |
| 配套核心、插件与运行库 | `Windows/` 内 | `Linux/` 内 |
| 发布包及 SHA-256 | `Windows/dist/` | `Linux/dist/` |
| 构建入口 | `packaging/build_windows.ps1` | `packaging/build_linux_docker.sh` |

`Windows/wsl/` 是 Windows 版支持 WSL 所必需的核心包，请随 Windows 版一起保留。`Linux/dist/IsGPTNerfed/` 和 `Linux/dist/nerfed-core` 是原构建中间产物；日常运行使用上表中的完整版本。

`desktop/`、`plugin/`、`packaging/` 和测试继续由两平台共用，避免两套源码产生差异。构建缓存原本已分别位于 `.build/windows/` 与 `.build/linux/`，保持现有位置。以后构建生成的发布包会进入各平台的 `dist/`；根目录下的可运行版本是本次整理的快照，更新时需要从新发布包重新解压。

## 启动

**Windows：**解压 `IsGPTNerfed-0.5.2-windows-x64.zip` 到一个普通目录，运行 `IsGPTNerfed.exe`。在设置中选择本机 Windows 或目标 WSL 发行版。选择 WSL 后，桌面端会自动从 ZIP 内的 `wsl/nerfed-core-linux.tar.gz` 部署 Linux 核心与插件到该发行版的 `~/.local/share/is-gpt-nerfed/runtime/0.5.2-crossplatform/`；无需手工解压此文件。

**Linux：**将 `IsGPTNerfed-0.5.2-linux-x86_64.tar.gz` 解压到用户有写入权限的目录，然后运行 `./IsGPTNerfed`。此构建基于 Ubuntu 22.04 / glibc 2.35；尚未验证低于 glibc 2.35 的发行版。若 Qt 提示缺少系统共享库，请安装下方原生构建步骤列出的 Qt/XCB 依赖；其他发行版使用各自包管理器提供的对应库。可用 `ldd _internal/PySide6/Qt/lib/libQt6XcbQpa.so.6` 查找 `not found` 的库。Release 另外提供 Linux ZIP，若解压丢失执行权限，请运行 `chmod +x IsGPTNerfed nerfed-core`。TAR.GZ 能保留符号链接；请直接在 Linux 解压，不要用 Windows 文件复制去整理 Linux 共享库链接。

## 手动更新

下载同一平台的新 ZIP 或 TAR.GZ 以及旁边的 `.sha256` 文件。先核对 SHA-256，再退出桌面程序并解压新版本到新目录。更新后重新打开新目录中的程序，在“插件”页再次点击“安装插件”，刷新 Codex hooks、运行命令和核心运行路径；Windows 的 WSL 核心会按包内归档自动更新。若已启用登录自启动，在设置中关闭并保存，再重新开启并保存，让启动项改指向新目录。确认新版本工作后再删除旧目录。更新不会要求删除 Codex 配置或账本；保留旧目录即可回退。

Linux 校验示例：

```sh
sha256sum -c IsGPTNerfed-0.5.2-linux-x86_64.tar.gz.sha256
```

Windows PowerShell 校验示例：

```powershell
Get-FileHash .\IsGPTNerfed-0.5.2-windows-x64.zip -Algorithm SHA256
```

将输出与 `.sha256` 文件中的十六进制值比较。跨平台构建没有配置自动发布或自动下载更新；通过项目工作流或本地构建拿到新包后手动替换即可。

## Building from source

### Docker 构建 Linux

先克隆本 Fork：`git clone https://github.com/MizuIro-H/is-gpt-nerfed-port.git`，然后 `cd is-gpt-nerfed-port`。以下命令均在仓库根目录执行。Linux 需要能运行 `docker info` 的 Docker Engine；WSL 用户需要启用 Docker Desktop 对该发行版的集成。脚本在 Ubuntu 22.04 容器中建立独立 Python 环境，并写入 `Linux/dist/`：

```sh
bash packaging/build_linux_docker.sh
```

### 构建 Windows

Windows 必须在原生 Windows PowerShell 或 PowerShell 7 中构建。脚本把 uv、Python 3.12、虚拟环境、PyInstaller 缓存限制在 `.build/`，不改系统 Python 或用户 PATH。先完成 Linux 构建（WSL 核心位于 `Linux/dist/nerfed-core-linux-x86_64.tar.gz`），或者从本 Fork Release 下载相同版本的独立核心包：

```powershell
New-Item -ItemType Directory -Force .\Linux\dist | Out-Null
Invoke-WebRequest -Uri "https://github.com/MizuIro-H/is-gpt-nerfed-port/releases/download/v0.5.2-port.1/nerfed-core-linux-x86_64.tar.gz" -OutFile .\Linux\dist\nerfed-core-linux-x86_64.tar.gz
```

核对 Release 的校验文件后构建：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1
```

脚本会在 Linux 容器和 Windows 原生环境分别构建，并运行冻结核心、离线 fork、桌面 offscreen 启动及上游测试，然后生成 Linux 桌面 TAR.GZ、独立 WSL 核心 TAR.GZ 和 Windows ZIP，并为每个包写出 SHA-256。CI 的 `Build cross-platform desktop packages` 手动工作流同样在 Ubuntu 22.04 与 Windows 原生 runner 上构建和验收；工作流只上传构建产物，不创建 GitHub Release。

### Ubuntu 22.04 原生构建

这条路径要求 **glibc 恰好为 2.35**，以及 Python 3.12（含 venv 支持）、C 工具中的 `objdump` 和 Qt 运行依赖。Ubuntu 22.04 默认的 Python 3.10 不满足本项目要求；请先准备 Python 3.12，或者直接使用上面的 Docker 路径。安装所需系统库：

```sh
sudo apt-get update
sudo apt-get install -y binutils libegl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1 libglib2.0-0 libgl1 \
  libfontconfig1 libfreetype6 libwayland-cursor0 libx11-6 libx11-xcb1 libxcb1
PYTHON_BIN=python3.12 bash packaging/build_linux.sh
```

构建脚本会先确认 glibc 基线，再在 `.build/linux/venv` 内安装依赖。Ubuntu 24.04 等较新系统可以运行成品或开发源码；要生成同样兼容基线的发布包，请使用 Ubuntu 22.04 容器。

### 不打包，直接开发运行

系统需有 Python 3.12 和 Qt/XCB 所需共享库。从仓库根目录执行：

```sh
python3.12 -m venv .venv-dev
.venv-dev/bin/python -m pip install -r requirements.txt
.venv-dev/bin/python desktop/cli_entry.py --demo
.venv-dev/bin/python -m unittest discover -s tests -v
```

Windows 可使用 `py -3.12 -m venv .venv-dev`，并将上述 `.venv-dev/bin/python` 换成 `.\.venv-dev\Scripts\python.exe`。去掉 `--demo` 会读取实际 Codex 会话；主动探测需要登录并消耗额度。源码模式的 Windows → WSL 连接仍需准备 Linux 核心运行环境；测试 WSL 时优先使用包含核心归档的已打包 Windows 版。

PyInstaller 包含的许可证文本位于每个包的 `licenses/`，Qt/PySide6 相关共享库保持可替换；包内 `NOTICE` 说明组件许可与来源。插件资产随包分发，核心运行不需要安装 Python。

## 验收范围与限制

构建烟测运行冻结核心的版本输出、演示快照、内置 selftest，以及通过临时 fake appserver 发起的一次离线 fork probe；不会连接真实 Codex app-server，也不会修改 Codex 配置。桌面界面另以 Qt offscreen 模式做启动检查。构建包不代表已在所有 Windows/Linux 发行版、桌面环境或显卡驱动上完成兼容性认证。Linux 兼容基线是 Ubuntu 22.04 的 glibc 2.35；Windows 包由 Windows 原生 runner 构建。

卸载时先在设置中关闭“登录时启动”，再对相应 Codex home 执行 `teardown`，它会解除插件/hooks 注册并保留账本。例如 Windows 本机在解压目录运行 PowerShell 命令 `& (Join-Path $PWD 'nerfed-core.exe') teardown`，Linux 从解压目录运行 `./nerfed-core teardown`；WSL 则在选定发行版里对已部署的 `~/.local/share/is-gpt-nerfed/runtime/0.5.2-crossplatform/nerfed-core` 执行 `teardown`。确认 Codex 不再引用应用路径后，退出桌面程序并删除解压目录；WSL 用户也可删除该发行版下的 `~/.local/share/is-gpt-nerfed/runtime/`。如确实要清除历史账本，必须显式运行 `teardown --purge`；这会删除记录，不能作为普通卸载步骤。
