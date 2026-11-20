# 在 macOS 上构建 Quick-TakeApart

这份包是为了**在 Mac 上重新构建安装包**而整理的：源码、图标、Tauri 配置都在，但 Windows 的
`runtime/`（`python.exe` / `node.exe`）和 `dist/` 产物没有带过来，它们必须在本机重新装配。

## 先决条件

| 需要 | 检查命令 | 备注 |
| --- | --- | --- |
| Xcode Command Line Tools | `xcode-select -p` | clang 与 `codesign`、`hdiutil` 都从这里来 |
| Rust | `rustc -V` / `cargo -V` | Tauri 的 Rust 侧编译 |
| Node 20+ | `node -v` / `npm -v` | 前端构建与 pyright 的运行 |
| python3 | `python3 -V` | 只用于构建脚本里的版本解析（不是最终运行时的 Python） |
| 网络 | — | 需要 npm（前端依赖、pyright）、crates.io（Rust 依赖）、GitHub（python-build-standalone） |

Rust 没装时：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

## 构建

```bash
cd Quick-TakeApart

# 1. 仓库根目录：安装 pyright（打包时会拷进 runtime）
npm install

# 2. desktop：安装 @tauri-apps/cli
cd desktop && npm install && cd ..

# 3. 装配 macOS runtime + 编译 + 打包（约 10–20 分钟，首次要下 Rust 依赖）
bash desktop/build-release.mac.sh
```

分步执行也支持：

```bash
bash desktop/prepare-runtime.mac.sh   # 只装配 runtime（会构建前端）
bash desktop/build-release.mac.sh --skip-runtime   # 只重编译外壳，复用已有 runtime
bash desktop/build-release.mac.sh --skip-frontend  # 前端没改时跳过 vite 构建
```

## 产物

都在 `desktop/dist/`：

| 产物 | 说明 |
| --- | --- |
| `Quick-TakeApart_2.1.0_arm64-macos.dmg` | 安装镜像，拖进 Applications 即可 |
| `Quick-TakeApart_2.1.0_arm64-macos.zip` | 内含 `.app`，解压即用 |
| `desktop/src-tauri/target/release/bundle/macos/Quick-TakeApart.app` | 原始 bundle |

## 已验证

这份包在 Apple Silicon 上完整跑通过一遍（macOS 15.5 / arm64，rustc 1.98.1，node 22.23.2）：

- `bash desktop/build-release.mac.sh` 一次到位，Rust 侧编译 4 分钟，产物 `.app` 286 MB、
  `dmg` 121 MB、`zip` 113 MB；
- `.app` 双击/命令行启动后会拉起内嵌 runtime，端口随机分配并写入
  `~/Library/Application Support/Quick-TakeApart/backend.log`；`/api/health` 返回
  `version=2.1`，`features` 含 `languages` / `langpacks`；
- 索引链路在 mac 上可用：对一个含 1 个 `.py` 的样例项目，`/api/index` 返回
  3 symbols / 2 edges，Python 语言项 `available=true`、`source=bundled`，命令解析为
  `.../runtime/node/node ... langserver.index.js --stdio`，说明内置 node + pyright 生效；
- 内嵌解释器为 `cpython-3.13.18+20261110-aarch64-apple-darwin-install_only`，`anthropic` 已装。

## macOS 上的语言检测与 PATH

`.app` 从 Finder / Launchpad 启动时，继承的是 launchd 的 PATH（只有
`/usr/bin:/bin:/usr/sbin:/sbin`），拿不到 `~/.zshrc` 里配的路径。所以即使终端里
`go version` 正常，应用也可能显示「Go 不可用」。外壳现在会自己重建登录 shell 的搜索路径：

- 读 `/etc/paths` 与 `/etc/paths.d/*`（等价于系统的 `path_helper`，Go 官方 pkg 把
  `/usr/local/go/bin` 写在这里）；
- 再补 `~/go/bin`、`~/.local/bin`、`~/.cargo/bin`、`~/Library/pnpm`、
  `~/.npm-global/bin`、`/opt/homebrew/bin`、`/usr/local/bin`、`/opt/local/bin`；
- 只保留真实存在的目录，最后仍追加进程原有的 PATH。

各语言要求的最小条件：

| 语言 | 需要 | 装法 |
| --- | --- | --- |
| Python | 内置完成，无需额外安装 | — |
| Go | `gopls` | `go install golang.org/x/tools/gopls@latest`（落到 `~/go/bin`） |
| C/C++ | `clangd` | Xcode CLT 已带 `/usr/bin/clangd` |
| Java | 语言包（当前资产是 Windows 版） | 见下方限制 |
| TypeScript / JS | `typescript-language-server` | `npm i -g typescript-language-server` |

`go install` 若卡在 `proxy.golang.org`，加 `GOPROXY=https://goproxy.cn,direct`；gopls 0.24
要求 go ≥ 1.27，Go 会自动切到新 toolchain（会额外下载一次）。

## 这套脚本做了什么

`prepare-runtime.mac.sh` 对应 Windows 的 `prepare-runtime.ps1`，装配出同样的目录结构：

```
desktop/src-tauri/runtime/
  server/     serve.py + engine/ + web/dist + node_modules/pyright
  node/node   从本机 node 复制（等价于 Windows 复制 node.exe）
  python/     python-build-standalone 的 CPython 3.13 + site-packages/anthropic
```

- Python 用 [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 的
  `install_only` 包，脚本按当前 `uname -m` 自动挑 arm64 / x86_64 的最新 3.13；
- Node 直接用本机二进制复制，不依赖用户机器上装 Node；
- pyright 从仓库根的 `node_modules` 拷进 `server/node_modules`，`PATH` 里加 `runtime/node`，
  与 Windows 一致。

`build-release.mac.sh` 只跑 `tauri build --bundles app`，然后自己 `codesign --sign -` 做 ad-hoc
签名，再用 `hdiutil` 出 dmg。**没有走 Tauri 的 dmg 打包环节**，因为未签名的 `.app` 在 Apple
Silicon 上会被 Gatekeeper 直接杀掉；先签再装进 dmg 才是能双击运行的顺序。

需要正式签名时（有 Developer ID 证书）：

```bash
QTA_SIGN_ID="Developer ID Application: Your Name (TEAMID)" bash desktop/build-release.mac.sh
```

## 已知限制

- **未做公证（notarization）**：首次打开仍需右键 →「打开」，或
  `xattr -dr com.apple.quarantine /Applications/Quick-TakeApart.app`。
- **语言包的下载源是 Windows 构建**：`engine/langpacks.py` 里的 jdtls 用 `config_win`、
  clangd 与 JRE 都是 windows/x64 资产。macOS 上 Java / C++ 的「下载语言包」按钮会失败，
  Python 支持不受影响。要在 mac 上支持，需要把 `PACKS` 改成按平台选（
  `platform.system()`）的 `config_mac` / `darwin-arm64` / `mac/x64` 资产。
- 运行期落点与 Windows 不同：引擎日志在
  `~/Library/Application Support/Quick-TakeApart/backend.log`，项目数据仍在项目目录下的
  `.qta/`，语言包在 `~/.qta/langpacks/`。
