# is-gpt-nerfed — Windows / Linux port

English · [简体中文](README.zh-CN.md)

A community desktop port of [kiyoakii/is-gpt-nerfed](https://github.com/kiyoakii/is-gpt-nerfed), with a Python/PySide6 window and system tray for Windows and Linux. It reads Codex session records and uses ModelTrace probes to compare the requested model with a statistical fingerprint of its answers.

This first port release implements basic functionality. Its core and calibration bank are based on upstream **0.5.2**, commit `f9132f3c8fb9116964e7b5a61052f1aefe73d7be`; it does **not** include upstream 0.5.3 changes. Release `v0.5.2-port.1` identifies the port distribution; the bundled core still reports `0.5.2`.

## Download and run

Download portable packages from [this fork's Releases](https://github.com/MizuIro-H/is-gpt-nerfed-port/releases/latest). The automatic GitHub “Source code” archives contain source, not compiled programs.

| Platform | Portable package | Start |
| --- | --- | --- |
| Windows 10/11, x64 | `IsGPTNerfed-0.5.2-port.1-windows-x64.zip` | Extract everything, then open `IsGPTNerfed.exe` |
| Linux, x86_64, glibc 2.35+ | `IsGPTNerfed-0.5.2-port.1-linux-x86_64.tar.gz` or `.zip` | Extract everything, then run `./IsGPTNerfed` |

Python and Qt are bundled. Keep `_internal/`, `nerfed-core`, `plugin/`, `.agents/`, `licenses/` and, on Windows, `wsl/` beside the application. Moving only the executable breaks the package. Linux needs a graphical desktop and the system libraries listed in the [platform guide](README-CROSSPLATFORM.md); TAR.GZ preserves executable permissions and symbolic links. ZIP extraction tools that discard permissions may require `chmod +x IsGPTNerfed nerfed-core`.

Before extracting, compare the download with `SHA256SUMS.txt`. On Linux use `sha256sum -c SHA256SUMS.txt --ignore-missing`; on Windows use `Get-FileHash .\IsGPTNerfed-0.5.2-port.1-windows-x64.zip -Algorithm SHA256`.

1. Install and sign in to Codex with plugin hooks and app-server support (upstream tested 0.154).
2. Open **Settings** and select the Codex home and binary. Windows offers Native or WSL; WSL paths and the Codex executable must belong to the chosen Linux distribution. The WSL runtime requires x86_64 Linux with glibc 2.35+.
3. In **Plugin**, select **Install plugin** and trust the hooks. Installation registers the plugin in the chosen Codex home; repeat it after moving/updating the application.
4. Select a session to probe, inspect its evidence, retry a failed probe or copy its report. **Fresh session** probes a new session. Settings include scheduling and login startup.

The Windows package includes the WSL core and deploys it into the selected distribution automatically. The UI supports English and Simplified Chinese. Use `IsGPTNerfed.exe --demo` or `./IsGPTNerfed --demo` for an isolated offline demonstration.

## What it checks

Passive checks read Codex's recorded model, reasoning effort and context-window information after turns. They do not make inference requests. Active checks fork a session ephemerally and collect three short random-number answers by default; these **use your Codex account's quota**.

ModelTrace scores those answers against a calibrated, closed-set bank. A match means the answers resemble the requested model; a confident mismatch can be marked downgrade, upgrade or rerouted. Suspicious, unlisted and invalid results need interpretation. The fingerprint is statistical evidence, not proof of the server's actual weights, and an unknown model can resemble a listed one. See the [original upstream guide](docs/README-upstream.md) for verdict definitions, thresholds, scheduling and methodology.

The desktop provides a session list, reports, notifications, manual/retry/fresh probes, plugin setup, hook trust and settings. Windows/Linux updates are **manual**; the original macOS automatic updater is not part of this port.

## Build from source

Clone this fork, then enter its root:

```sh
git clone https://github.com/MizuIro-H/is-gpt-nerfed-port.git
cd is-gpt-nerfed-port
```

Build tools are pinned to Python 3.12, PySide6 6.11.2 and PyInstaller 6.22.3. Network access is required for dependencies. PyInstaller builds for its host platform: build Windows on native Windows and Linux on Linux.

**Linux:** install Docker Engine (or enable Docker Desktop integration in your WSL distribution), ensure `docker info` succeeds, then run:

```sh
bash packaging/build_linux_docker.sh
```

This builds in Ubuntu 22.04, runs source tests and offline GUI/core smoke checks, and produces the desktop TAR.GZ plus a standalone WSL core TAR.GZ and SHA-256 files in `Linux/dist/`. Docker must be able to write to the mounted checkout. For the native Ubuntu 22.04 build and development commands, see the [platform guide](README-CROSSPLATFORM.md#building-from-source).

**Windows:** use Windows PowerShell 5.1 or PowerShell 7 with internet access. First create `Linux/dist/nerfed-core-linux-x86_64.tar.gz` with the Linux build above, or download the matching core asset from this fork's Release into that path. Then, from the checkout root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1
```

The script downloads project-local uv and Python, installs the pinned dependencies, builds and tests the Windows program, and produces `Windows/dist/IsGPTNerfed-0.5.2-windows-x64.zip` plus its checksum. To use another matching WSL archive, pass `-LinuxCoreArchive "C:\path\nerfed-core-linux-x86_64.tar.gz"`. Build filenames use the core version; Release filenames additionally identify the port revision.

Alternatively run **Actions → Build cross-platform desktop packages → Run workflow** in this fork. It builds Linux first and passes the WSL runtime to Windows. Download the two resulting Actions artifacts; this workflow does not publish a Release automatically.

## Repository and limitations

`desktop/`, `plugin/`, `packaging/` and `tests/` are shared source. `Windows/` and `Linux/` are local runnable snapshots and build outputs, ignored by Git. Release archives carry their compiled programs. The original `macos/` source and its [upstream guide](docs/README-upstream.md) are retained; macOS downloads remain in [upstream Releases](https://github.com/kiyoakii/is-gpt-nerfed/releases).

Validation uses isolated demo data and a fake Codex app-server: it checks GUI rendering, frozen-core startup, plugin registration, UTF-8 hooks and detached workers. It does not establish compatibility with every Linux desktop, Windows installation, or live Codex server. This release is unsigned and has no automatic updater. The 0.5.2 core's executable discovery can choose an old Codex on PATH; configure the desired binary explicitly.

Session records, model cache and account metadata are read from the selected Codex home. Config, probe records and logs are kept under its `is-gpt-nerfed/` directory; desktop profiles use the platform's per-user config directory. Account metadata is used for a hash and masked address. Active probes are normal remote Codex inference; detection records stay local. Windows/Linux update checks default to off. Updating/uninstalling instructions are in the [platform guide](README-CROSSPLATFORM.md).

## Credits and license

Original project and macOS app: [kiyoakii / Jin Li](https://github.com/kiyoakii/is-gpt-nerfed). Port maintained by [MizuIro-H](https://github.com/MizuIro-H), with AI assistance from **OpenAI Codex**; see [CONTRIBUTORS.md](CONTRIBUTORS.md).

[ModelTrace](https://github.com/xqy2006/ModelTrace) supplies the MIT-licensed bank, scorer and prompts; [hlwy-ai-checker](https://github.com/hanlinwenyuan/hlwy-ai-checker) inspired the random-number approach; [simple-term-menu](https://github.com/IngoMeyer441/simple-term-menu) supplies the MIT-licensed terminal picker. This repository is [MIT licensed](LICENSE). Bundled dependencies retain their own licenses in `licenses/` and `NOTICE`.
