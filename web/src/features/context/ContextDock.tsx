import { useLocation, useNavigate } from "react-router-dom";
import { Pencil, Trash2 } from "lucide-react";
import { useApp } from "../../core/store";
import { stageFromPath } from "../../core/routes";
import { PlanChat } from "../plan/PlanChat";
import { SkeletonNodePanel } from "../skeleton/SkeletonNodePanel";
import { SliceDetails } from "../read/SliceDetails";
import { DiagramsPanel } from "../read/DiagramsPanel";
import { ThreadPanel } from "../ask/ThreadPanel";
import { TracePanel } from "../read/TracePanel";

export function ContextDock() {
  const location = useLocation();
  const navigate = useNavigate();
  const tab = useApp((s) => s.contextTab);
  const setTab = useApp((s) => s.setContextTab);
  const track = useApp((s) => s.track);
  const slice = useApp((s) => s.activeSlice);
  const activeFile = useApp((s) => s.activeFile);
  const traceOpen = useApp((s) => s.traceOpen);
  const setTraceOpen = useApp((s) => s.setTraceOpen);
  const updateActiveTrack = useApp((s) => s.updateActiveTrack);
  const deleteActiveTrack = useApp((s) => s.deleteActiveTrack);
  const stage = stageFromPath(location.pathname);

  if (stage === "plan") {
    return (
      <aside className="dock">
        <div className="dock-head">
          <button className={`dock-tab${tab !== "details" ? " active" : ""}`} onClick={() => setTab("thread")}>
            计划对话
          </button>
          <button className={`dock-tab${tab === "details" ? " active" : ""}`} onClick={() => setTab("details")}>
            轨道信息
          </button>
          <span className="spacer" />
          <span className="chip cyan">独立记忆</span>
        </div>
        {tab === "details" ? (
          <div className="dock-body">
            <div className="panel-flat panel-body">
              <div className="panel-title">{track?.track.name}</div>
              <p className="small muted" style={{ marginTop: 6 }}>{track?.track.intent || "未写用途"}</p>
              <div className="hairline" />
              <div className="col">
                <div className="row"><span className="chip">粒度</span><span className="small">{track?.track.depth || "未指定"}</span></div>
                <div className="row"><span className="chip">步骤</span><span className="small">{track?.plan?.items.length || 0}</span></div>
                <div className="row"><span className="chip">切片</span><span className="small">{track?.slices.length || 0}</span></div>
              </div>
              <div className="hairline" />
              <div className="row wrap" style={{ gap: 5 }}>
                <button
                  className="btn btn-xs"
                  onClick={() => {
                    const name = window.prompt("轨道名", track?.track.name || "");
                    if (name) void updateActiveTrack({ name });
                  }}
                >
                  <Pencil size={10} /> 改名
                </button>
                <button
                  className="btn btn-xs"
                  onClick={() => {
                    const intent = window.prompt("用途 / 粒度", track?.track.intent || "");
                    if (intent !== null) void updateActiveTrack({ intent });
                  }}
                >
                  改用途
                </button>
                <button
                  className="btn btn-xs btn-danger"
                  onClick={() => {
                    if (!confirm(`删除轨道「${track?.track.name}」？切片不会被删除。`)) return;
                    void deleteActiveTrack().then(() => navigate("/")).catch(() => undefined);
                  }}
                >
                  <Trash2 size={10} /> 删除轨道
                </button>
              </div>
            </div>
          </div>
        ) : (
          <PlanChat />
        )}
      </aside>
    );
  }

  if (stage === "read") {
    if (!slice) {
      return (
        <aside className="dock">
          <div className="dock-head">
            <button className="dock-tab active">全局阅读</button>
            <span className="spacer" />
            <span className="chip">文件模式</span>
          </div>
          <div className="dock-body">
            <div className="panel-flat panel-body">
              <div className="panel-title" style={{ fontSize: 16 }}>正在直接读代码</div>
              <p className="small muted" style={{ marginTop: 6 }}>
                当前没有切片，所以没有切片级讲解和问答。左侧文件树可以继续切换文件；
                选中代码后点“切开”会生成可复读的切片。
              </p>
              <div className="hairline" />
              <div className="small muted">文件：{activeFile || "未选择"}</div>
            </div>
          </div>
        </aside>
      );
    }
    return (
      <aside className="dock">
        <div className="dock-head">
          <button className={`dock-tab${tab === "details" && !traceOpen ? " active" : ""}`} onClick={() => { setTraceOpen(false); setTab("details"); }}>讲解</button>
          <button className={`dock-tab${tab === "thread" && !traceOpen ? " active" : ""}`} onClick={() => { setTraceOpen(false); setTab("thread"); }}>问答</button>
          <button className={`dock-tab${tab === "diagrams" && !traceOpen ? " active" : ""}`} onClick={() => { setTraceOpen(false); setTab("diagrams"); }}>图表</button>
          {traceOpen ? (
            <button
              className="dock-tab active"
              title="收起追踪结果"
              onClick={() => setTraceOpen(false)}
            >
              追踪
            </button>
          ) : null}
          <span className="spacer" />
          <span className="chip cyan">按切片记忆</span>
        </div>
        {traceOpen ? (
          <div className="dock-body"><TracePanel /></div>
        ) : tab === "thread" ? (
          <ThreadPanel />
        ) : tab === "diagrams" ? (
          <div className="dock-body"><DiagramsPanel slice={slice} /></div>
        ) : (
          <div className="dock-body"><SliceDetails slice={slice} /></div>
        )}
      </aside>
    );
  }

  if (stage === "library") {
    return (
      <aside className="dock">
        <div className="dock-head">
          {slice ? (
            <>
              <button
                className={`dock-tab${tab !== "thread" ? " active" : ""}`}
                onClick={() => setTab("details")}
              >
                讲解
              </button>
              <button
                className={`dock-tab${tab === "thread" ? " active" : ""}`}
                onClick={() => setTab("thread")}
              >
                问答
              </button>
            </>
          ) : (
            <button className="dock-tab active">库信息</button>
          )}
          <span className="spacer" />
          {slice ? <span className="chip cyan">按切片记忆</span> : null}
        </div>
        {slice && tab === "thread" ? (
          <ThreadPanel />
        ) : (
          <div className="dock-body">
            {slice ? <SliceDetails slice={slice} /> : (
              <div className="empty">
                <strong>全局切片库</strong>
                所有轨道生成的切片都在这里。选一张卡片查看讲解与问答。
              </div>
            )}
          </div>
        )}
      </aside>
    );
  }

  return (
    <aside className="dock">
      <div className="dock-head">
        <button className="dock-tab active">节点讲解</button>
        <span className="spacer" />
        <span className="chip">{track?.skeletons.length || 0} 份骨架</span>
      </div>
      <div className="dock-body"><SkeletonNodePanel /></div>
    </aside>
  );
}
