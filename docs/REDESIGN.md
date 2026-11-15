# Quick-TakeApart 重写设计契约

> 本文件是重写的硬约束。实现可以分阶段，但数据模型、边界和交互语义以这里为准。

## 0. 一句话

**一个目录是一份持久 session；session 内可以有多条学习轨道；每条轨道有自己的逻辑骨架、计划与对话；切片是全局可复用的阅读产物。阶段一只讲清主流程与平行支撑，阶段三把“左目录 / 中代码 / 右讲解”统一成一套阅读台，并复用骨架节点讲解。**

---

## 1. 领域模型

```text
Workspace（目录，持有多语言 LSP 索引）
└── Track（学习轨道 = 一个目的）
    ├── Skeleton（阶段一产物：主流程 + 平行支撑 + 按需节点讲解）
    ├── Plan（步骤 DAG）
    │   └── PlanThread（计划设计对话，独立记忆）
    ├── Slice[]（阶段三产物；全局库可见；可回指骨架节点）
    └── Thread[]（侧页问答；按切片一条线程，独立记忆）
```

### 1.1 Workspace

- 一个项目目录对应一个 workspace。
- 索引、符号、调用边、文件源文本是 workspace 级共享资源。
- 同一时间服务端只驻留一个 workspace 的索引；切换目录时重建索引，但磁盘产物不丢。
- 语言通过 `LanguageSpec` 适配：Python（pyright）、TypeScript/JavaScript（typescript-language-server）、Go（gopls）。一个 workspace 内多语言合并索引；缺少某个 LSP 时保留文件浏览并明确标注不可用，不伪造符号或调用边。
- 跨语言边通常无法由 LSP 证明；它们以 boundary 形式呈现，而不是硬连成一条调用链。

### 1.2 Track

- 用户可以为同一个目录开多条轨道：`整体了解` / `改这个 bug` / `只看认证`。
- 每条轨道有自己的 `intent`、`depth`（粒度契约）、`plan`、`planThread`。
- **目的与粒度只在轨道层设置一次**；计划、切片、骨架节点动作继承它们，不重复询问。
- 逻辑骨架属于轨道；切片默认是 workspace 级的，可被多条轨道引用。
- 删除轨道不删除全局切片；只删除轨道自己的骨架、计划、计划对话和侧页线程。

### 1.3 Skeleton

阶段一只产出一份**逻辑骨架**，不是模块陈列，也不是逐函数档案。

```ts
Skeleton {
  id, trackId, focus, title, overview,
  main: SkeletonNode[],            // 有顺序的运行时主流程
  support: SkeletonNode[],         // 并列的平行支撑
  links: [{from, to, status, site?}],
  createdAt, revision, fingerprints
}

SkeletonNode {
  id, title,                  // 清晰的组件/阶段名，如“请求分派”
  summary,                    // 一到两句通俗说明：做什么、交给谁
  phase?,                     // 启动/处理/数据等短标签
  symbolIds[], files[],       // 必须落到真实符号
  detail?, detailCreatedAt    // 点击时按需生成的通俗讲解
}
```

- `main` 讲**阶段**，不是按业务域把 users、orders 串成假顺序；多个域共享同一管线时只表达一次。
- 健康检查、CLI、后台任务等独立入口放 `support` 或 overview，不强行接在主流程末尾。
- 节点讲解按需生成：文件级、通俗语言、无代码块，保留可点击符号/位置；生成后冻结在骨架里。
- 骨架节点可以生成切片（`source.kind = "skeleton-node"`）或加入计划；整条主流程可以导入为计划草稿，平行支撑作为可跳过项。

### 1.4 Plan

- 计划是步骤 DAG，不是线性清单。
- 每个步骤引用一个 **Slice**（不是裸 Flow），或标记为 `needsGeneration`。
- 字段：`goal`、`sliceId`、`after[]`、`granularity`、`skippable`、`status`。
- 计划对话的产物是**计划变更**，不是解释文本；每轮必须产生操作或一个澄清问题。
- 计划对话持久化；重新打开轨道看到同一份计划与同一段设计过程。

### 1.5 Slice

切片是阶段三的持久化单位。它同时包含“逻辑流”和“代码材料”。

```ts
Slice {
  id, trackId, title, query, summary,
  strategies: ("path" | "sequence" | "crosscut" | "zones" | "calltree" | "dataflow")[],
  views: View[],                 // 可多条平行流；每条流可独立阅读
  segments: Segment[],           // 从文件抽出的代码片段
  annotations: Annotation[],     // 锚定到片段/符号/行范围的富文本
  diagrams: Diagram[],           // 服务端从校验后的图重建，不信任模型 Mermaid
  source: SliceSource,           // plan-step / skeleton-node / query / selection / file / function / module
  createdAt, revision,
  fingerprints                   // 逐符号冻结，用于过期检测
}

Segment {
  id, file, startLine, endLine,
  symbolId?, role: "entry"|"trunk"|"branch"|"context"|"skip",
  note?, flowTitle?
}

View {
  kind, title, rationale,
  nodes: [{symbolId, group, depth, note, role}],
  messages?: [{from, to, label, symbolId?, status}],  // sequence 用
  edges?: [{from, to, status, site?}]                  // 服务端校验后的连接
}
```

**冻结策略**：结构、顺序、片段范围、批注冻结；代码文本实时读取。代码改动后逐符号报告 `ok/moved/changed/missing`，不静默渲染错误内容。

### 1.6 Thread

- `scope`: `plan` / `slice` / `symbol` / `range` / `file`。
- 计划对话与侧页问答是两条独立记忆，互不注入。
- 侧页默认按切片一条线程；函数/选区只是这条线程里的引用锚点。
- 每条消息可带 `citations` 与 `context`（选中的文件、行范围、代码文本）。
- AI 回答可被“提升”为一条新切片，或插入到计划。

---

## 2. 切片策略与组合规则

| 策略 | 回答的问题 | 形状 | 不适合 |
|---|---|---|---|
| `path`（链路） | 请求进来后发生了什么 | 一条有序主干 | 分散在各层的日志/指标 |
| `sequence`（时序） | 谁在什么时候调用谁 | 参与者 + 消息 | 没有明确参与者的散点 |
| `crosscut`（横切） | log/db/metrics/auth 都在哪 | 按用途分桶 | 硬凑成一条链 |
| `zones`（分区） | 整体怎么组织 | 区域卡片 | 单函数细节 |
| `calltree`（调用树） | 这个函数下面调了什么 | 嵌套树 | 跨模块的并列关系 |
| `dataflow`（数据流） | 数据从哪来到哪去 | 输入→转换→存储 | 控制流顺序 |

### 组合矩阵

- **可组合**：`path + sequence`（顺序 + 参与者）；`zones + crosscut`（区域 + 横切关注点）；`path + calltree`（主干 + 下钻）。
- **谨慎组合**：`path + crosscut`。只有横切点作为“可跳过旁路”时成立，不能把散点画进主链。
- **不建议**：`sequence + crosscut` 同时作为主视图；时序会暗示一条不存在的统一调用链。
- 一个切片最多 6 条 `path/sequence` 平行流；它们共享符号与片段，但各自有完整逻辑。
- 模型可以选择不生成某种视图；缺少视图是合法状态，不补假图。

---

## 3. 前端分层

```text
web/src/
  app/         路由、Shell、启动、命令面板、快捷键
  core/        API client、store、选择上下文、追踪服务、格式化
  domain/      project / track / skeleton / plan / slice / thread 类型与操作
  features/
    workspace/ 目录首页与项目切换
    skeleton/  逻辑骨架：主流程、平行支撑、按需节点讲解
    plan/      计划板、计划对话、手动编辑
    read/      统一阅读台：上下文目录、代码、切片目录、全量代码
    library/   全局切片库、当前轨道骨架库
  ui/          代码阅读器、富文本、Mermaid、证据徽章、面板、tabs
  styles/      设计令牌、排版、布局、组件样式
```

硬规则：

- feature 之间不直接操作对方 DOM；通过 domain store 和路由通信。
- 代码阅读器、富文本、符号 chip、证据徽章是共享 UI，不在三个阶段各写一套。
- 页面加载不一次性请求所有内容；先 workspace + track，切片正文按需加载。
- 任何 AI 产物在渲染前都过校验；不合法引用保留并标记，不静默删除。

---

## 4. 界面结构

### 4.1 Shell

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：项目 / 阶段 / 命令面板 / 索引状态 / 左右栏与全屏        │
├──────────┬───────────────────────────────────┬───────────────┤
│ 左轨      │ 主画布                             │ 上下文/问答    │
│ 轨道切换  │ 骨架 / 计划 / 阅读 / 切片库          │ 节点讲解/线程  │
│ 切片快捷  │                                   │ 图表           │
│ 上下文目录│                                   │               │
├──────────┴───────────────────────────────────┴───────────────┤
│ 状态栏：文件/函数/边 · 保存状态 · 快捷键提示                    │
└──────────────────────────────────────────────────────────────┘
```

- **阶段导航只在顶栏**；左轨不再重复阶段。
- 左轨顶部是轨道切换 + 切片快捷选择；下面是上下文目录：
  - 没有选中切片时显示**真实文件树**，支持全局阅读；
  - 选中切片后切换为**切片目录**：流程 / 文件 / 函数三组，随切片变化。
- 左轨、右栏都可以独立折叠；全屏阅读会同时隐藏左右栏，把宽度让给代码。
- 右栏是上下文，不固定为聊天；阶段一显示骨架节点讲解，阶段二显示计划对话，阶段三显示切片讲解/问答/图表。
- 不再出现“四个功能挤在四栏”的布局。

### 4.2 阶段一：逻辑骨架

- 主页面只有一张骨架图，不再有“模块骨架 / 时序 / 分层富文本 / 入口与数据流”四个 tab。
- 图分两部分：
  - **主流程节点**：有顺序的运行时阶段，标题是清晰组件/职责（如“服务启动”“请求分派”“Service 业务处理”），每个节点给一到两句通俗说明；连接线标明 `direct / reverse / inferred`。
  - **平行支撑节点**：配置、日志、指标、错误处理、缓存、独立健康检查等并列能力，不画进主链。
- 粒度约束：主流程是阶段，不是按业务域串联；节点只给文件级概要，不在这里一次性讲完所有函数。
- 点节点 → 右栏按需生成/复读**节点讲解**：文件级、通俗语言、无代码块，带可点击函数与真实位置；生成后冻结在骨架里。
- 动作：
  - 节点 → 生成切片并加入计划、只生成独立切片、加入计划（待生成）；
  - 整条主流程 → 导入计划草稿，平行支撑作为可跳过项；
  - 相关文件 → 直接进入全局阅读。

### 4.3 阶段二：计划

- 主画布是计划板，不是聊天框。
- 轨道已经确定目的与粒度；计划页不再重复表单。首次排计划直接用当前轨道，手动加一步只填“这一步读什么”。
- 计划板：
  - 轨道标题、用途、深度契约、进度。
  - 步骤卡：目标、绑定切片、策略、粒度、可跳过、依赖、状态。
  - 连接线显示依赖；可切换“路线 / 依赖图”。
  - 点击步骤 → 复读切片；未生成 → 就地生成并绑定。
- 右栏是计划对话：
  - 持久化消息；每轮显示“计划变更”清单，而不是一段解释。
  - 缺口显示“生成并绑定”。
  - 对话不能绕过计划校验（悬空引用、成环）。
- 手动动作：加一步、删一步、改目标/粒度/依赖、重排。

### 4.4 阶段三：统一阅读台

取消“流程 / 文件 / 函数”三模式切换，统一成一套布局：

- **左目录**（左轨下半部分，随上下文变化）：
  - 没有切片：真实文件树，支持全局阅读；
  - 选中切片：切片目录，包含“流程 / 文件 / 函数·片段”三组；点流程或函数打开对应片段，点文件打开整文件并高亮目标范围。
- **中间代码**：
  - 当前片段显示代码、连接证据、批注、选区工具条；可展开整文件；
  - 顶部保留一条紧凑流程条，显示当前流的顺序和位置，不额外占一列。
- **右栏**：
  - **讲解**：如果切片来自骨架节点，直接、完整复用阶段一的全局讲解；否则只显示阅读路线（原问题、视图、起止位置）。不再重复模型生成的切片概要，也不在右栏重复批注。
  - **问答**：按切片一条线程；消息持久化；可引用选区/函数；
  - **图表**：Mermaid 图、证据表。
- 批注只留在代码片段旁，保持一句话；不把同样的话再抄到右栏。全局讲解归阶段一，局部批注归代码，右栏只负责“这条切片怎么读”。
- 右栏可折叠；左轨可折叠；全屏模式同时隐藏左右栏。
- 打开切片/片段/文件时主滚动区回到顶部，不继承上一个页面的滚动位置。

代码阅读器：

- 行号、语法高亮、选区。
- **查找收窄**：Ctrl+点击函数/类定义、函数调用和变量查定义、引用、来源、去向；语言关键字、`self` 和字面量不响应。
- 选中文本浮动工具条：提问 / 切开 / 复制引用。
- 面包屑：轨道 → 计划步骤 / 骨架节点 / 切片 → 文件 → 函数。

### 4.5 切片库

- 全局可查看所有切片；按轨道、策略、过期状态过滤；搜索标题/查询/符号。
- 可打开、重命名、删除、加入计划。
- 骨架属于当前轨道；库视图显示当前轨道骨架，可打开或删除。旧架构档案仅保留磁盘兼容，不再出现在新界面。

---

## 5. 后端 API

### Language settings

```text
GET  /api/settings                 -> languageServers / 旧版兼容字段
POST /api/settings                 {languageServers?}
```

语言服务器命令保存在本机 `~/.qta/settings.json`；留空走 PATH 自动检测。

### LLM providers / profiles

```text
GET  /api/llm/providers            -> items: 内置只读 Provider 目录
GET  /api/llm/config               -> active / fallback / env_loaded
GET  /api/llm/profiles             -> items: 不含密钥
POST /api/llm/profiles             -> 201 Profile；第一份自动激活
PATCH /api/llm/profiles/{id}       -> 局部更新，缺省字段不变
DELETE /api/llm/profiles/{id}      -> {profile_id, active_profile_id}
POST /api/llm/profiles/{id}/activate {model?}
POST /api/llm/profiles/{id}/models   -> {models, note}；POST 不是 GET
POST /api/llm/profiles/{id}/probe    -> {ok, detail}
```

- Provider 未知 → 422 并列出可用值；`base_url` 必须带 `http(s)`。
- 拉清单失败、网络失败、模型不在清单但可调用 → 都是 200 + `note/detail`，不是 422。
- 密钥只写 `~/.qta/secrets/<profile>.key`，响应永远只有 `has_key` / 掩码；`api_key` 三态：不传不改、`""` 清空、有值替换。
- `models` 永远包含 `model`；`activate` 一次切换档案与模型。
- 上下文预算 `num_ctx=0` 时用 Provider 保守窗口，响应给 `effective_num_ctx`；Ollama 显式发送，OpenAI 兼容请求不发送。
- 支持 Provider：DeepSeek、OpenAI、DashScope、Moonshot、智谱、SiliconFlow、OpenRouter、Groq、Ollama、LM Studio、vLLM、Anthropic、自定义 OpenAI 兼容。

### Workspace / Track

```text
GET  /api/workspace
POST /api/open                     {root}
GET  /api/track?id=...
POST /api/tracks                   {name,intent,depth}
POST /api/tracks/update            {id,name?,intent?,depth?}
POST /api/tracks/delete            {id}
```

### Skeleton

```text
GET  /api/skeletons                -> list + staleness
GET  /api/skeleton?id=...
POST /api/skeletons/generate       {trackId?,focus}
POST /api/skeletons/node/explain   {skeletonId,nodeId}
POST /api/skeletons/import-main    {trackId,skeletonId}
POST /api/skeletons/import-node    {trackId,skeletonId,nodeId}
POST /api/skeletons/delete         {id}
```

`import-main` / `import-node` 只把待生成步骤写入计划对话的 `needsGeneration`；用户生成切片后才进入计划 DAG。

### Slice

```text
GET  /api/slices                   -> list + staleness
GET  /api/slice?id=...
POST /api/slices/generate          {trackId,query,strategies?,source?}
POST /api/slices/delete            {id}
POST /api/slices/rename            {id,name}
```

### Plan / Thread

```text
POST /api/plan/chat                {trackId,message}
POST /api/plan/apply               {trackId,items}
POST /api/tracks/generate-bind     {trackId,request}
GET  /api/thread?id=...
POST /api/threads                  {scope,trackId?,sliceId?,anchor?,title?}
POST /api/threads/message          {threadId,message,context?}
```

### Code / Trace

```text
GET  /api/source?path=...
POST /api/trace                    {file,line,char,kind}
```

---

### 模型输入边界（token 预算）

模型永远不接收整个项目源码。输入按任务裁剪：

| 任务 | 输入 | 预算/边界 |
|---|---|---|
| 阶段一骨架 | 全项目压缩符号/调用表 | 最多 900 callable，无行号 |
| 切片生成 | 问题/选区/骨架节点种子 + 一跳邻居 + 入口/高扇入 + 未解析边界 | 最多 240 callable，带行号 |
| 节点讲解 | 节点符号 + 一跳邻居 + 节点附近真实代码 | 代码 ≤14k 字符 |
| 侧页问答 | 切片符号 + 一跳邻居 + 切片片段代码 | 代码 ≤14k 字符 |
| 计划对话 | 当前计划 + 切片库元数据 | 不含源码/全量符号表 |

硬规则：

- 切片使用 `build_scoped_inventory`，不得回退到全量 inventory；聚焦清单是显式边界，缺符号不等于项目里没有。
- 聚焦清单必须确定性排序，保持提示词缓存可命中；种子/邻居缺失时宁可少，不塞无关符号。
- 骨架可以看全项目符号，但只看压缩符号表，不读源码正文。
- 代码窗口只给节点/切片相关范围；不要用“为了完整”把整文件或全项目代码塞进 prompt。

## 6. 富文本协议

使用受控 Markdown + 可验证引用，不允许模型直接输出 HTML。

- `[[sym:path::qualname|显示名]]` → 符号 chip；校验失败则保留文本并标红。
- `[[loc:path:12-28|显示名]]` → 行范围 chip；校验失败标红。
- ` ```mermaid ` → 服务端/前端校验后渲染；不合法则显示错误块。
- ` ```evidence ` → 证据折叠块（JSON 行：status/from/to/site）。
- `> [!note]` / `> [!warn]` / `> [!evidence]` → callout。
- 支持标题、列表、引用、代码、表格（基础）、粗体/斜体/行内代码。
- 回答里的 citations 单独存储；渲染时与正文引用交叉校验。

---

## 7. 视觉系统

方向：**低饱和青色观测台**。

- 纸张底：`#f5f8f6`；次级面板：`#edf4f1`；墨色：`#17221f`。
- 主信号：`#2f7d73`（teal）；流动色：`#8ec9c4`（pale cyan）；琥珀：`#b8833f`；锈红：`#b45a45`。
- 代码舱：`#0f1716`；代码墨：`#d7e4df`；行号：`#5d7470`。
- 字体：`Fraunces`（展示/标题，衬线）+ `Sora`（UI/正文）+ `JetBrains Mono`（代码）。
- 动效：页面加载错峰 reveal；流程图连线轻微流动；hover 提升；不使用浮夸粒子。
- 背景：极淡青色径向渐变 + 细噪点；不干扰正文。
- 不使用的通用 AI 审美：紫色渐变、纯白卡片堆叠、Inter/Roboto、无意义的玻璃拟态。

---

## 8. 实施顺序

1. **后端领域层**：workspace/track/thread/slice/skeleton 存储 + 校验 + API。
2. **前端壳层**：Vite/React、路由、store、设计令牌、Shell、命令面板。
3. **阶段一**：逻辑骨架（主流程 + 平行支撑）+ 按需节点讲解 + 导入计划/切片。
4. **阶段二**：计划板 + 持久化计划对话 + 生成绑定 + 骨架导入草稿。
5. **阶段三**：统一阅读台（上下文目录 + 代码 + 右栏）+ 全屏 + 回顶 + 骨架讲解复用。
6. **切片库/骨架库** + 过期状态 + 迁移/兼容。
7. **验证**：构建、后端测试、真实模型与浏览器关键路径。

---

## 9. 明确不做

- 不再用一套四栏视图覆盖三个阶段。
- 不把骨架做成力导向节点云或平铺模块陈列。
- 不把横切关注点、健康检查、后台任务硬接进主流程。
- 不把多个业务域串成一条假的时间顺序；共享管线只表达一次。
- 不让模型直接决定符号是否存在、行号是否存在、图是否能渲染。
- 不让节点讲解编造路由、中间件、端点或框架行为；代码/索引没展开就明确说无法确认。
- 不把计划聊天记录当成交付物；交付物是计划。
- 不在阶段一逐函数讲解，避免和阶段二重叠；阶段一只讲透节点逻辑。
