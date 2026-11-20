import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight, Boxes, GitBranch, Layers, Plus, RefreshCw, Sparkles,
} from "lucide-react";
import { useApp } from "../../core/store";
import { trackPath } from "../../core/routes";
import { plainText } from "../../core/text";
import type { Skeleton, SkeletonNode } from "../../types";

function Connector({ status }: { status: "direct" | "reverse" | "inferred" }) {
  return (
    <div className={`connector skeleton-link ${status}`}>
      <span className="line" />
      <span>
        ↓ {status === "direct" ? "真实调用" : status === "reverse" ? "方向相反" : "无直接调用边 · 推断"}
      </span>
    </div>
  );
}

export function SkeletonView() {
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const activeSkeletonId = useApp((s) => s.activeSkeletonId);
  const activeNodeId = useApp((s) => s.activeSkeletonNodeId);
  const selectSkeleton = useApp((s) => s.selectSkeleton);
  const selectSkeletonNode = useApp((s) => s.selectSkeletonNode);
  const generateSkeleton = useApp((s) => s.generateSkeleton);
  const explainSkeletonNode = useApp((s) => s.explainSkeletonNode);
  const importSkeletonMain = useApp((s) => s.importSkeletonMain);
  const revealDock = useApp((s) => s.revealDock);
  const busy = useApp((s) => s.busy);
  const generating = busy?.startsWith("正在生成逻辑骨架") || false;
  const [focus, setFocus] = useState("");

  const skeleton: Skeleton | null = useMemo(() => {
    const pool = track?.skeletons || [];
    return pool.find((s) => s.id === activeSkeletonId) || pool[0] || null;
  }, [track, activeSkeletonId]);

  useEffect(() => {
    if (skeleton && skeleton.id !== activeSkeletonId) selectSkeleton(skeleton.id);
  }, [skeleton, activeSkeletonId, selectSkeleton]);

  async function generate() {
    try {
      const created = await generateSkeleton(focus);
      selectSkeleton(created.id);
      setFocus("");
    } catch {
      /* the status bar shows the failure */
    }
  }

  function openNode(node: SkeletonNode) {
    if (!skeleton) return;
    selectSkeletonNode(node.id);
    revealDock("details");
    if (!node.detail && !busy) {
      void explainSkeletonNode(skeleton.id, node.id).catch(() => undefined);
    }
  }

  async function importMain() {
    if (!skeleton) return;
    try {
      await importSkeletonMain(skeleton.id);
      if (track) navigate(trackPath(track.track.id, "plan"));
    } catch {
      /* the status bar shows the failure */
    }
  }

  if (!skeleton) {
    return (
      <div className="stage">
        <div className="stage-head reveal">
          <div className="grow">
            <div className="eyebrow">Stage 01 · Skeleton</div>
            <h1 className="stage-title">先看清逻辑骨架，而不是先看文件</h1>
            <p className="stage-sub">
              主流程告诉你系统从哪里开始、按什么顺序运行；平行支撑告诉你配置、日志、指标和错误处理如何挂在旁边。
              节点先给文件级通俗概要，点开后再按需生成完整讲解。
            </p>
          </div>
        </div>
        <div className="panel reveal reveal-1" style={{ maxWidth: 760 }}>
          <div className="panel-body">
            <div className="panel-title" style={{ marginBottom: 6 }}>生成第一份逻辑骨架</div>
            <p className="small muted" style={{ marginBottom: 12 }}>
              可选关注点：“整体请求链路”“启动与退出”“只看数据访问”。骨架不会逐函数展开。
            </p>
            <div className="form-row">
              <div className="field">
                <label>关注点（可选）</label>
                <input className="input" value={focus} onChange={(e) => setFocus(e.target.value)}
                  placeholder="例如：整体逻辑 / 请求链路 / 启动过程" />
              </div>
              <button className="btn btn-primary" disabled={!!busy} onClick={() => void generate()}>
                <Sparkles size={14} /> {generating ? "生成中…" : "生成骨架"}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="stage">
      <div className="stage-head skeleton-head reveal">
        <div className="grow">
          <div className="eyebrow">
            Stage 01 · Skeleton · {skeleton.focus || "整体逻辑"}
          </div>
          <h1 className="stage-title">{skeleton.title}</h1>
          <p className="stage-sub">{plainText(skeleton.overview)}</p>
          <div className="row wrap" style={{ marginTop: 9, gap: 6 }}>
            <span className="chip teal">{skeleton.main.length} 个主流程节点</span>
            <span className="chip">{skeleton.support.length} 个平行支撑</span>
            <span className="chip">{skeleton.detailCount || 0} 个已生成讲解</span>
            {skeleton.staleness && !skeleton.staleness.fresh ? (
              <span
                className="chip amber"
                title={`骨架与当前代码有漂移：${skeleton.staleness.summary}。节点仍可阅读，但个别位置可能已变化。`}
              >
                {skeleton.staleness.summary}
              </span>
            ) : null}
          </div>
        </div>
        <div className="stage-actions">
          {(track?.skeletons || []).length > 1 ? (
            <select
              className="select"
              style={{ width: 190, fontSize: 11, padding: "6px 9px" }}
              value={skeleton.id}
              onChange={(e) => {
                selectSkeleton(e.target.value);
                useApp.getState().selectSkeletonNode(null);
              }}
            >
              {(track?.skeletons || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title} · {item.createdAt?.slice(5, 16).replace("T", " ")}
                </option>
              ))}
            </select>
          ) : null}
          <div className="field" style={{ width: 170 }}>
            <input className="input" value={focus} onChange={(e) => setFocus(e.target.value)}
              placeholder="换个关注点…" style={{ padding: "6px 9px", fontSize: 11 }} />
          </div>
          <button className="btn btn-sm" disabled={!!busy} onClick={() => void generate()}>
            <RefreshCw size={13} className={generating ? "spin" : ""} /> 重新生成
          </button>
          <button className="btn btn-sm btn-primary" disabled={!!busy} onClick={() => void importMain()}>
            <Plus size={13} /> 主流程导入计划
          </button>
        </div>
      </div>

      <div className="skeleton-layout">
        <section className="skeleton-main">
          <div className="skeleton-column-head">
            <div>
              <div className="eyebrow" style={{ marginBottom: 2 }}>Main flow</div>
              <h2>主流程节点</h2>
              <p className="small muted">按运行时顺序阅读；点击节点生成通俗讲解。</p>
            </div>
            <span className="chip teal">{skeleton.main.length} 节点</span>
          </div>

          <div className="skeleton-spine">
            {skeleton.main.map((node, index) => {
              const link = skeleton.links.find((l) => l.from === node.id);
              return (
                <div key={node.id}>
                  <button
                    className={`sk-node${activeNodeId === node.id ? " selected" : ""}`}
                    onClick={() => openNode(node)}
                  >
                    <span className="sk-num">{String(index + 1).padStart(2, "0")}</span>
                    <span className="sk-body">
                      <span className="sk-title">{node.title}</span>
                      <span className="sk-summary">{plainText(node.summary)}</span>
                      <span className="sk-meta">
                        {node.phase ? <span className="chip muted">{node.phase}</span> : null}
                        <span className="chip">{node.symbolIds.length} 符号</span>
                        {node.files.slice(0, 2).map((file) => (
                          <span className="chip" key={file}>{file}</span>
                        ))}
                        {node.detail ? <span className="chip teal">已生成讲解</span> : null}
                      </span>
                    </span>
                    <ArrowRight size={14} className="sk-arrow" />
                  </button>
                  {link ? <Connector status={link.status} /> : null}
                </div>
              );
            })}
          </div>
        </section>

        <aside className="skeleton-support">
          <div className="skeleton-column-head">
            <div>
              <div className="eyebrow" style={{ marginBottom: 2 }}>Parallel support</div>
              <h2>平行支撑节点</h2>
              <p className="small muted">不组成主流程，但横切在多个节点上。</p>
            </div>
          </div>
          <div className="sk-support-grid">
            {skeleton.support.map((node) => (
              <button
                key={node.id}
                className={`sk-support-card${activeNodeId === node.id ? " selected" : ""}`}
                onClick={() => openNode(node)}
              >
                <div className="sk-support-icon"><Layers size={13} /></div>
                <div className="grow">
                  <div className="sk-title">{node.title}</div>
                  <div className="sk-summary">{plainText(node.summary)}</div>
                  <div className="sk-meta">
                    <span className="chip">{node.symbolIds.length} 符号</span>
                    {node.detail ? <span className="chip teal">已讲解</span> : null}
                  </div>
                </div>
              </button>
            ))}
            {!skeleton.support.length ? (
              <div className="empty" style={{ padding: 16 }}>
                <strong>没有平行支撑节点</strong>
                小项目或扁平脚本可能没有独立的配置/日志层。
              </div>
            ) : null}
          </div>
          <div className="skeleton-legend">
            <span><GitBranch size={11} /> 主流程是有顺序的</span>
            <span><Boxes size={11} /> 支撑节点是并列的</span>
          </div>
        </aside>
      </div>

      <div className="row" style={{ marginTop: 18, gap: 8 }}>
        <button className="btn btn-sm" onClick={() => {
          if (!track) return;
          useApp.getState().setStage("plan");
          navigate(trackPath(track.track.id, "plan"));
        }}>
          <ArrowRight size={13} /> 去计划
        </button>
        <button className="btn btn-sm btn-ghost" onClick={() => {
          useApp.getState().setStage("read");
          if (track) {
            navigate(trackPath(track.track.id, "read", useApp.getState().activeSliceId));
          }
        }}>
          直接去读代码
        </button>
        <span className="spacer" />
        <span className="small muted">节点详情是按需生成的；不会一次性把所有函数讲一遍。</span>
      </div>
    </div>
  );
}

export function SkeletonNodePreview({ skeleton, node }: { skeleton: Skeleton; node: SkeletonNode }) {
  const selectSkeletonNode = useApp((s) => s.selectSkeletonNode);
  return (
    <button className="rail-artifact" onClick={() => selectSkeletonNode(node.id)}>
      <span className="mono small">{node.title}</span>
      <span className="small muted" style={{ marginLeft: 5 }}>{node.summary.slice(0, 40)}</span>
    </button>
  );
}
