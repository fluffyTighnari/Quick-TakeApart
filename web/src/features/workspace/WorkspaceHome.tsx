import { useNavigate } from "react-router-dom";
import { ArrowRight, BookOpen, Boxes, FileCode2, Library, Network, Plus, Route } from "lucide-react";
import { useApp } from "../../core/store";

function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function WorkspaceHome() {
  const navigate = useNavigate();
  const workspace = useApp((s) => s.workspace);
  const track = useApp((s) => s.track);
  const activeTrackId = useApp((s) => s.activeTrackId);
  const selectSlice = useApp((s) => s.selectSlice);
  const setStage = useApp((s) => s.setStage);
  const createTrack = useApp((s) => s.createTrack);

  if (!workspace) return null;
  const current = track?.track;

  function go(stage: string) {
    if (!activeTrackId) return;
    setStage(stage as "architecture" | "plan" | "read" | "library");
    navigate(`/track/${activeTrackId}/${stage}`);
  }

  async function newTrack() {
    const name = window.prompt("新轨道名", "搞懂主链路");
    if (!name) return;
    const intent = window.prompt("这条轨道的用途 / 粒度", "先看结构，再追一条主链路") || "";
    const data = await createTrack(name, intent, "结构");
    navigate(`/track/${data.track.id}/architecture`);
  }

  const recent = [
    ...(track?.skeletons || []).map((s) => ({
      id: s.id, kind: "骨架", title: s.title, date: s.createdAt,
      open: () => {
        useApp.getState().selectSkeleton(s.id);
        go("architecture");
      },
    })),
    ...workspace.slices.map((s) => ({
      id: s.id, kind: "切片", title: s.title, date: s.createdAt,
      open: () => {
        void selectSlice(s.id);
        if (activeTrackId) navigate(`/track/${activeTrackId}/read/${s.id}`);
      },
    })),
  ].sort((a, b) => (b.date || "").localeCompare(a.date || "")).slice(0, 8);

  return (
    <div className="stage">
      <div className="stage-head reveal">
        <div className="grow">
          <div className="eyebrow">Workspace · {workspace.name}</div>
          <h1 className="stage-title">读懂一个项目，先从位置感开始</h1>
          <p className="stage-sub">
            阶段一画骨架，阶段二排路线，阶段三把相关代码切成可复读的阅读流。
            当前轨道：<strong>{current?.name || "尚未选择"}</strong>
            {current?.intent ? ` — ${current.intent}` : ""}
          </p>
        </div>
        <div className="stage-actions">
          <button className="btn" onClick={() => void newTrack()}>
            <Plus size={14} /> 新建轨道
          </button>
        </div>
      </div>

      {workspace.stats.files === 0 ? (
        <div className="notice bad" style={{ marginBottom: 12 }}>
          这个目录里没有找到 Python 文件。当前索引器只支持 Python；请换一个包含
          <code style={{ margin: "0 3px" }}>.py</code>
          文件的目录，或等待后续语言支持。
        </div>
      ) : null}

      <div className="row wrap reveal reveal-1" style={{ gap: 7, marginBottom: 8 }}>
        <span className="chip teal">{workspace.stats.files} 文件</span>
        <span className="chip">{workspace.stats.callables} 函数</span>
        <span className="chip">{workspace.stats.edges} 调用边</span>
        <span className="chip muted">{workspace.stats.crossFile} 跨文件</span>
        {current?.depth ? <span className="chip amber">粒度 · {current.depth}</span> : null}
      </div>

      <div className="home-grid">
        <button className="home-card reveal reveal-1" onClick={() => go("architecture")}>
          <div className="hc-num">01 · SKELETON</div>
          <div className="hc-title">逻辑骨架</div>
          <div className="hc-desc">
            主流程节点按顺序讲完整逻辑，平行支撑节点单独成列；点节点再按需生成通俗讲解。
          </div>
          <div className="hc-foot">
            <span className="chip">主流程</span>
            <span className="chip">平行支撑</span>
            <span className="chip">节点讲解</span>
          </div>
          <ArrowRight size={15} style={{ position: "absolute", right: 16, top: 16, color: "var(--teal)" }} />
        </button>

        <button className="home-card reveal reveal-2" onClick={() => go("plan")}>
          <div className="hc-num">02 · ROUTE</div>
          <div className="hc-title">学习计划</div>
          <div className="hc-desc">
            从骨架主流程导入草稿，或和 AI 对话排步骤：先读什么、依赖什么、哪里可以跳过。计划是引用清单，不是聊天记录。
          </div>
          <div className="hc-foot">
            <span className="chip">{track?.plan?.items.length || 0} 步</span>
            <span className="chip">独立对话</span>
          </div>
          <ArrowRight size={15} style={{ position: "absolute", right: 16, top: 16, color: "var(--teal)" }} />
        </button>

        <button className="home-card reveal reveal-3" onClick={() => go("read")}>
          <div className="hc-num">03 · READ</div>
          <div className="hc-title">阅读台</div>
          <div className="hc-desc">
            左侧目录切换流程/文件/函数，中间读代码，右侧看讲解与图表；支持全屏、选区提问，以及 Ctrl+点击函数/关键字查找。
          </div>
          <div className="hc-foot">
            <span className="chip">{workspace.slices.length} 切片</span>
            <span className="chip">全屏</span>
            <span className="chip">函数/关键字查找</span>
          </div>
          <ArrowRight size={15} style={{ position: "absolute", right: 16, top: 16, color: "var(--teal)" }} />
        </button>
      </div>

      <div className="home-recent reveal reveal-4">
        <div className="row" style={{ marginBottom: 9 }}>
          <h2>最近产物</h2>
          <span className="spacer" />
          <button className="btn btn-sm btn-ghost" onClick={() => go("library")}>
            <Library size={13} /> 全局切片库
          </button>
        </div>
        {recent.length ? (
          <div className="recent-list">
            {recent.map((item) => (
              <button key={`${item.kind}-${item.id}`} className="recent-item" onClick={item.open}>
                <span className="ri-kind">{item.kind === "骨架" ? <Network size={12} /> : <FileCode2 size={12} />} {item.kind}</span>
                <span className="ri-title truncate">{item.title}</span>
                <span className="ri-meta">{fmtDate(item.date)}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty">
            <strong>还没有产物</strong>
            先让 AI 画一份逻辑骨架，或者在阅读阶段提一个问题生成切片。
          </div>
        )}
      </div>

      <div className="row wrap" style={{ marginTop: 22, gap: 8 }}>
        <button className="btn btn-sm" onClick={() => go("library")}><Boxes size={13} /> 查看全部切片与骨架</button>
        <button className="btn btn-sm" onClick={() => go("plan")}><Route size={13} /> 继续当前计划</button>
        <button className="btn btn-sm" onClick={() => go("read")}><BookOpen size={13} /> 打开阅读台</button>
      </div>
    </div>
  );
}
