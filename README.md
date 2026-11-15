# Quick-TakeApart

一个按“逻辑骨架 → 学习计划 → 切片阅读”组织的本地代码理解工具。阶段一只讲清主流程与平行支撑，不陈列模块；阶段二可以把骨架节点直接导入计划；阶段三统一成“左目录 / 中代码 / 右讲解”。设计契约见 [`docs/REDESIGN.md`](docs/REDESIGN.md)。

## 运行

### 快速启动

Windows PowerShell：

```powershell
.\start.ps1 -Project <项目目录> -Port 7741
# 如果被执行策略拦截：
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Project <项目目录> -Port 7741
```

macOS / Linux：

```bash
./start.sh <项目目录> 7741
```

脚本会检查 Node/Python，安装 pyright（Python LSP）与前端依赖，构建 `web/dist`，然后启动服务。TypeScript / Go 的语言服务器会自动检测 PATH；缺失时仍可浏览文件，但不能建完整调用图。打开：

```text
http://127.0.0.1:7741/
```

### 桌面版（Tauri）

桌面壳已经独立在 [`desktop/`](desktop/)：Rust/Tauri 启动随包的 CPython + Node + pyright，等待 `/api/health`，再用 WebView 打开本地服务。不要把 Tauri 脚手架再放到仓库根目录。

```powershell
cd desktop
npm install
npm run dev          # 开发
npm run build        # 准备 runtime + Tauri release + NSIS + portable zip
```

`desktop/README.md` 里有 runtime 结构、NSIS 和日志/数据目录说明。桌面版是否在安装时勾选语言，取决于是否把对应 LSP 作为可选 runtime 组件打进安装器：

- **Python**：现在随 runtime 打包 pyright，必需。
- **TypeScript / JavaScript**：可检测用户已有 `typescript-language-server`；若要随安装包提供，需要在 `desktop/prepare-runtime.ps1` 增加可选 runtime 目录，并在 `installer.nsi` 增加 NSIS Components 页。
- **Go**：可检测用户已有 `gopls`；若要随包提供，同样作为可选 runtime 组件。

标准 Tauri NSIS 只有安装语言选择，没有“可选语言服务器组件”页；真正的安装器勾选需要自定义 `installer.nsi` 的 `MUI_PAGE_COMPONENTS` + 可选 `Section`。在完成这套可选组件前，应用内 API/语言设置会复用系统 PATH 中已有的服务器。

### 手动运行

```bash
# 1. Python 依赖
python -m pip install -r requirements.txt

# 2. 前端首次构建
cd web
npm ci
npm run build

# 3. 启动本地服务（按语言自动选择本地 LSP）
cd ..
python serve.py <项目目录> --port 7717
```

不传项目目录也可以，入口支持：

- 直接输入绝对路径、`~`、`file:///` 或带引号的路径；
- “选择文件夹”调用系统文件夹选择器；
- “浏览目录”在应用内逐级浏览；
- 从文件管理器拖入文件夹（浏览器能提供本地路径时自动打开，否则会提示改用选择器）。

首次索引按语言使用本地 LSP（Python 使用 pyright，TypeScript/JavaScript 使用 typescript-language-server，Go 使用 gopls）；大项目会慢一些。之后骨架、切片、对话都直接读磁盘，不会重新调用模型。阶段一的节点讲解是点击时按需生成的，生成一次后冻结在骨架里。

语言服务器自动检测 PATH；也可以在本机设置里指定命令：

```json
{
  "languageServers": {
    "python": "node /path/to/pyright/langserver.index.js --stdio",
    "typescript": "typescript-language-server --stdio",
    "go": "gopls serve"
  }
}
```

对应环境变量：`QTA_PYRIGHT`、`QTA_TYPESCRIPT_SERVER`、`QTA_GOPLS`。缺少某个语言的服务器时，文件仍可浏览，但该语言不会生成符号和调用图。

### 端口被旧进程占用

如果页面空白，或 `/api/browse` 返回 404、选择文件夹无反应，先检查端口：

```powershell
Get-NetTCPConnection -LocalPort 7717 -State Listen
```

结束旧进程（管理员终端）：

```powershell
taskkill /PID <PID> /F
```

不想处理旧进程就直接换端口：

```bash
python serve.py <项目目录> --port 7741
```

新版前端启动时会请求 `/api/health`。如果连到旧后端，会直接显示“后端进程是旧版本”，不会再表现为零散的 501/404。

### 前端开发模式

```bash
cd web
npm run dev
```

Vite 默认运行在 `5173`，并把 `/api` 代理到 `127.0.0.1:7717`。先启动 Python 服务。

## 模型配置

逻辑骨架、节点讲解、计划和侧页问答需要模型。右上角 **API 设置** 现在是多 Provider / 多 Profile 模型页：

- 服务商下拉来自后端目录，不硬编码；
- 选服务商 → 默认 Base URL / 默认模型自动填好（DeepSeek 默认 `deepseek-flash`，即当前 API 的 4.1 Flash 别名；以拉取清单为准）；
- API Key 只进不出，响应只有 `has_key` 和掩码；
- “保存并拉取清单”先保存再拉，清单拉不到也返回 200 + 人话说明，仍可手填模型名；
- 一份配置可勾多个模型；切换档案和模型是一次 `activate`；
- “探活”会真实发一句请求，清单里没有的模型不会被误判为写错。

配置文件：`~/.qta/llm_profiles.json`，密钥单独放在 `~/.qta/secrets/<profile>.key`（可用 `QTA_LLM_DIR` 覆盖）。旧 `~/.qta/settings.json` 与环境变量仍可作为兜底。

环境变量兜底：

```bash
# 任选一种 key
set DEEPSEEK_API_KEY=...        # Windows PowerShell: $env:DEEPSEEK_API_KEY="..."
set QTA_BASE_URL=https://api.deepseek.com/v1
set QTA_MODEL=deepseek-flash
```

没有 key 时：

- 逻辑骨架和切片会退化为本地启发式结果，并在界面上标明“本地推测”；
- 节点讲解会退化为符号清单式说明，不会伪造完整逻辑；
- 计划对话会明确失败，而不是伪造计划；
- 代码阅读、Ctrl+点击函数/变量、文件导航、引用、切片复读都不依赖模型。

## 模型读到什么

模型不会拿到整个项目源码。它看到的是按任务裁剪过的符号/调用清单，必要时再加一小段真实代码：

| 任务 | 模型输入 | 不发送 |
|---|---|---|
| 阶段一骨架 | 全项目压缩符号表（最多 900 个 callable，无行号） | 源码正文 |
| 切片生成 | 以问题/选区/骨架节点为种子的聚焦符号表（最多 240 个 callable，带行号） | 全项目符号表、源码正文 |
| 节点讲解 | 节点符号 + 一跳邻居 + 节点附近真实代码窗口（≤14k 字符） | 全项目源码 |
| 侧页问答 | 切片符号 + 一跳邻居 + 切片片段代码（≤14k 字符） | 全项目源码 |
| 计划对话 | 当前计划 + 切片库元数据 | 源码/全量符号表 |

切片不再把整张符号表塞给模型。聚焦清单会保留问题命中符号、一跳调用者/被调用者、入口/高扇入方向和未解析边界；清单保持确定性，因此同一个问题仍可命中提示词缓存。

对一个 600 个 callable 的合成项目实测（字符数，token 大致同比例）：

- 全量 inventory：54,971 字符；
- 聚焦 inventory：7,996–11,247 字符，约减少 79–86%；
- 阶段一压缩 inventory：45,979 字符，约减少 16%。

目的与粒度只在**轨道层**设置一次；计划、切片和节点动作继承，不再逐层重复选择。阅读台的查找收窄为：函数/类定义、函数调用和变量可查定义与引用；语言关键字、`self`、字面量不再响应 Ctrl+点击。

### 讲解契约

- **全局讲解（阶段一）**：节点定位、职责、关系、下一步读哪里；不在阶段一逐函数展开，也不写 LSP/库存取证式的免责声明。
- **切片讲解（阶段三右栏）**：来自骨架节点的切片直接复用阶段一的全局讲解；自由切片只显示阅读路线（原问题、视图、起止位置），不再生成第二套概要。
- **批注（代码旁边）**：一句话说明这段在阅读路线里的作用，或什么可以跳过；不在右栏重复。
- **问答**：直接回答当前切片的问题，带可点击引用；不把“inventory 里没有边”写成一段分析日志。

## 持久化结构

每个项目目录下：

```text
.qta/
  tracks/         学习轨道（目录=session，多轨道）
  threads/        计划对话与侧页问答（独立记忆）
  plans/          步骤 DAG，引用切片
  slices/         切片：逻辑流 + 代码片段 + 批注 + 图表
  skeletons/      逻辑骨架：主流程 + 平行支撑 + 按需节点讲解
  architectures/  旧版架构档案（兼容保留，新界面不再使用）
  flows/          旧版冻结流（兼容保留）
```

切片与骨架都带逐符号指纹；代码改动后界面会报告 `moved/changed/missing`，而不是静默渲染旧内容。骨架节点讲解也冻结在骨架里，重新生成前不会随页面刷新丢失。

## 开发验证

前端为 Vite + React；Python 引擎测试保留在仓库根目录：

```bash
python test_store.py
python test_plans.py
python test_arch.py
python test_skeleton.py
python test_inventory.py
python test_languages.py
python test_llm_config.py
python test_settings.py
python test_plans_chat.py
python test_claims.py
```
