# Desktop shell（Tauri）

把 Quick-TakeApart 打成 Windows 桌面应用：一个 Tauri 窗口 + 内嵌的 Python 引擎，不需要用户自己装 Python / Node。

## 结构

```
desktop/
  prepare-runtime.ps1        # 装配 src-tauri/runtime（本机 copy，不依赖外网下载器）
  make-icon.ps1              # 生成 icon-source.png（1024×1024）
  src-tauri/
    src/lib.rs               # 起 Python 引擎 → 轮询 /api/health → 开主窗口
    src/main.rs              # release 下隐藏控制台
    tauri.conf.json          # frontendDist = splash/，resources = runtime/
    splash/index.html        # 启动过渡页（Tauri 唯一的本地页面）
    capabilities/default.json
    icons/                   # npx tauri icon 生成
    runtime/                 # 生成物，未入库
      server/                # serve.py + engine/ + web/dist + node_modules/pyright
      node/node.exe          # 便携 Node（pyright 的 LSP 靠它启动）
      python/                # CPython 3.13（含 tkinter）+ site-packages(anthropic)
```

## 为什么这样包

`serve.py` 同时提供 API 和 `web/dist` 静态文件，是单进程单源的。于是外壳只需要：

1. 挑一个空闲端口；
2. 用 `runtime/python/python.exe serve.py --host 127.0.0.1 --port <port>` 起后端（`CREATE_NO_WINDOW`，没有黑框）；
3. 每 250ms 打一次 `/api/health`，通了自己再打开 `http://127.0.0.1:<port>/`。

因此**前端代码零改动**（`fetch` 全是相对路径），也不需要 Tauri IPC、不需要任何 shell 插件权限。

两个打包上的硬约束：

- `serve.py` 里 `PYRIGHT = <serve.py 目录>/node_modules/pyright/langserver.index.js`，启动时文件不存在直接 `return 2`，所以 pyright 必须跟着 `serve.py` 走到 `runtime/server/node_modules/pyright`；
- `engine/indexer.py` / `trace.py` 都用 `["node", …]` 拉起 pyright，所以 `runtime/node` 要前置到子进程的 `PATH`（`src/lib.rs` 的 `prepend_path`）。

## 构建

```powershell
cd desktop
npm install              # 只为拿 @tauri-apps/cli
npm run build            # prepare-runtime + tauri build --no-bundle + makensis + zip
```

三个产物都在 `desktop/dist/`：

| 产物 | 说明 |
| --- | --- |
| [`Quick-TakeApart_2.1.0_x64-setup.exe`](dist/Quick-TakeApart_2.1.0_x64-setup.exe) | NSIS 安装包，per-user 安装到 `%LOCALAPPDATA%\Quick-TakeApart`，带卸载项 |
| [`Quick-TakeApart_2.1.0_x64-portable.zip`](dist/Quick-TakeApart_2.1.0_x64-portable.zip) | 便携包，解压即用 |
| `Quick-TakeApart/` | 上面两者的共同内容：`Quick-TakeApart.exe` + `runtime/` |

只重打外壳（没改 Python / 前端）：

```powershell
npm run build:runtime     # = build-release.ps1 -SkipRuntime
```

只重装 runtime（改了 `serve.py`、`engine/` 或前端）：

```powershell
npm run runtime
```

### 为什么不用 `tauri build` 直接出安装包

`tauri build` 的 NSIS 打包环节会自己去 GitHub 下载 `nsis-3.13.zip` 和 `nsis_tauri_utils.dll`，在这台机器上稳定超时（`failed to bundle project: timeout: global`）。所以 `build-release.ps1` 改成：Rust 侧只跑 `tauri build --no-bundle` 出 exe，安装包由本地 `desktop/.tools/nsis/Bin/makensis.exe` 编译 `installer.nsi` 生成。首次运行脚本时如果 `.tools/nsis` 不存在，会自动 `curl --ssl-no-revoke` 下载（GitHub 通的时候几秒就好；不通就把 `nsis-3.13.zip` 丢进 `desktop/.tools/nsis/` 再跑）。

`src-tauri/tauri.conf.json` 里的 `bundle.resources` 和 `targets: ["nsis"]` 保持着，网络正常时 `npx tauri build` 依然能直接出同一个安装包。

## 运行期落点

| 东西 | 位置 |
| --- | --- |
| 引擎日志（stderr） | `%LOCALAPPDATA%\Quick-TakeApart\backend.log` |
| 应用数据（设置、最近项目、track） | `~/.qta`（沿用原有逻辑，未改动） |
| 可选语言包（Java / C/C++） | `~/.qta/langpacks/<id>`（`QTA_LANGPACK_DIR` 可覆盖） |
| runtime | 安装目录下的 `runtime\`（NSIS 装到 `%LOCALAPPDATA%\Quick-TakeApart`） |

## 注意

- runtime 约 160 MB（CPython ~70 MB + node 83 MB + pyright 19 MB），安装包本身还有压缩。
- 安装包**没有代码签名**，首次运行 SmartScreen 会提示「未知发布者」。
- WebView2 用系统已装的那份（Win10/11 默认自带）；没装时 NSIS 会走微软 bootstrapper 下载。
- 版本号在两处：`package.json` 与 `src-tauri/tauri.conf.json`（`Cargo.toml` 的是 crate 版本，不参与打包命名）。
- 唯一一处为打包做的源码改动：`engine/picker.py` 的文件夹选择器优先用 `pythonw.exe`，避免点「选择目录」时闪一个控制台窗口。

## 语言支持

runtime 自带 Python 的 pyright；TypeScript/JavaScript 和 Go 走自动检测；Java 与 C/C++ 用「应用内按需下载」的语言包，不打进安装包。

| 语言 | 来源 | 说明 |
| --- | --- | --- |
| Python | `runtime/server/node_modules/pyright` + runtime 的 `node.exe` | 必需，随包 |
| TypeScript/JavaScript | PATH 里的 `typescript-language-server`（tsserver.js 会自动找） | 不随包，检测复用 |
| Go | PATH 里的 `gopls` | 不随包，检测复用 |
| Java | `engine/langpacks.py` 下载 jdtls + JRE 25 | 约 102 MB，装完不依赖本机 Java |
| C / C++ | 同上，下载 clangd 23.1.0 | 约 30 MB，单文件二进制 |

首个来源都可在应用设置里用命令覆盖（`QTA_JDTLS` / `QTA_CLANGD` 等环境变量同理）。

### 语言包为什么走下载

jdtls 约 50 MB、它要求的运行时又是 50 MB 量级，clangd 约 30 MB；直接进安装块会让安装包从 39 MB 涨到 150 MB 以上，而多数人只读一两种语言。所以 `engine/langpacks.py` 定义了包目录（id、体积、下载/解压步骤、入口文件查找），`/api/langpacks*` 暴露给前端，下载放到后台线程，进度由设置页轮询。

几个必须保留的细节：

- 下载走系统 `curl.exe`（`--ssl-no-revoke` + 失败重试），因为本机 Python 的 urllib 直连 GitHub/open-vsx 会被重置；curl 不可用时才回落 urllib。
- jdtls 取自 open-vsx 的 `redhat.java` 扩展（`extension/server` 目录，与 Eclipse 快照同一份构建），因为 `download.eclipse.org` 在这类网络上只有 0.02 MB/s；版本号在 `engine/langpacks.py` 里写死，升级时改 URL 并重测。
- jdtls 1.59 的 bundle 要求 `osgi.ee version=25`，所以内置运行时必须是 JRE 25（用 17/21 会在 OSGi 解析阶段直接退出，日志只报 `UnsupportedClassVersionError` 或 bundle 未解析）。
- 装完包不会自动重建索引，需要重新打开项目（`index_project` 在 open 时跑）。
- 若要在安装器里做组件勾选，仍有两条路：把包塞进 `installer.nsi` 的可选 `Section`（安装包变大），或在安装阶段联网下载（失败要重装）；当前选择的是应用内下载。
