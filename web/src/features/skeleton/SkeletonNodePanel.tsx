import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight, BookOpen, Plus, RefreshCw, Sparkles,
} from "lucide-react";
import { useApp } from "../../core/store";
import { trackPath } from "../../core/routes";
import { plainText } from "../../core/text";
import type { Skeleton, SkeletonNode } from "../../types";
import { RichText } from "../../ui/RichText";

export function SkeletonNodePanel() {
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const activeSkeletonId = useApp((s) => s.activeSkeletonId);
  const activeNodeId = useApp((s) => s.activeSkeletonNodeId);
  const busy = useApp((s) => s.busy);
  const explaining = busy?.startsWith("正在生成节点讲解") || false;
  const explain = useApp((s) => s.explainSkeletonNode);
  const importNode = useApp((s) => s.importSkeletonNode);
  const generateSlice = useApp((s) => s.generateSlice);
  const generateBind = useApp((s) => s.generateBind);
  const openCode = useApp((s) => s.openCode);
  const setStage = useApp((s) => s.setStage);

  const skeleton: Skeleton | null = useMemo(() => {
    const pool = track?.skeletons || [];
    return pool.find((s) => s.id === activeSkeletonId) || pool[0] || null;
  }, [track, activeSkeletonId]);

  const node: SkeletonNode | null = useMemo(() => {
    if (!skeleton) return null;
    return [...skeleton.main, ...skeleton.support]
      .find((n) => n.id === activeNodeId) || null;
  }, [skeleton, activeNodeId]);

  if (!skeleton) {
    return <div className="empty"><strong>还没有骨架</strong>先生成一份骨架，再点节点。</div>;
  }
  if (!node) {
    return (
      <div>
        <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
          <div className="panel-title" style={{ fontSize: 17 }}>{skeleton.title}</div>
          <p className="small muted" style={{ marginTop: 5 }}>{plainText(skeleton.overview)}</p>
          <div className="row wrap" style={{ gap: 5, marginTop: 8 }}>
            <span className="chip teal">{skeleton.main.length} 主流程</span>
            <span className="chip">{skeleton.support.length} 并行支撑</span>
          </div>
        </div>
        <div className="rail-label" style={{ paddingLeft: 0 }}>点击一个节点</div>
        <div className="col" style={{ gap: 4 }}>
          {[...skeleton.main, ...skeleton.support].map((item) => (
            <button key={item.id} className="rail-artifact" onClick={() => useApp.getState().selectSkeletonNode(item.id)}>
              <span className="mono small">{item.title}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  const mainIndex = skeleton.main.findIndex((n) => n.id === node.id);
  const isSupport = mainIndex < 0;

  function queryForNode(n: SkeletonNode) {
    return `${n.title}：${n.summary || "讲清这一节点的完整逻辑"}`;
  }

  async function makeSlice(andPlan: boolean) {
    if (!skeleton || !node) return;
    try {
      let sliceId: string | null = null;
      if (andPlan) {
        const created = await generateBind({
          query: queryForNode(node),
          stepId: `sk-${node.id}`,
          goal: node.title,
          after: [],
          granularity: track?.track.depth || "结构",
          skippable: isSupport ? "平行支撑，可按需跳过" : "",
          skeletonId: skeleton.id,
          nodeId: node.id,
        });
        sliceId = created.id;
      } else {
        const created = await generateSlice(queryForNode(node), {
          scope: {
            kind: "skeleton-node",
            skeletonId: skeleton.id,
            nodeId: node.id,
            label: node.title,
          },
        });
        sliceId = created.id;
      }
      setStage("read");
      if (track) navigate(trackPath(track.track.id, "read", sliceId));
    } catch {
      /* the status bar shows the failure */
    }
  }

  async function addPending() {
    if (!skeleton || !node) return;
    try {
      await importNode(skeleton.id, node.id);
      setStage("plan");
      if (track) navigate(trackPath(track.track.id, "plan"));
    } catch {
      /* the status bar shows the failure */
    }
  }

  function openSymbol(sid: string) {
    const file = base?.symbols[sid]?.file;
    if (!file) return;
    void openCode(file, sid);
    setStage("read");
    if (track) navigate(trackPath(track.track.id, "read"));
  }

  function openFile(file: string) {
    void openCode(file);
    setStage("read");
    if (track) navigate(trackPath(track.track.id, "read"));
  }

  return (
    <div>
      <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
        <div className="row">
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 4 }}>
              {isSupport ? "平行支撑节点" : `主流程 · 第 ${mainIndex + 1} 步`}
            </div>
            <div className="panel-title" style={{ fontSize: 20 }}>{node.title}</div>
            <p className="small" style={{ marginTop: 6 }}>{plainText(node.summary)}</p>
          </div>
          {node.phase ? <span className="chip amber">{node.phase}</span> : null}
        </div>
        <div className="row wrap" style={{ gap: 5, marginTop: 9 }}>
          <span className="chip">{node.symbolIds.length} 符号</span>
          {node.detail ? <span className="chip teal">讲解已生成</span> : null}
          {node.detailSource === "heuristic" ? <span className="chip amber">本地回退</span> : null}
        </div>
        <div className="row wrap" style={{ gap: 5, marginTop: 10 }}>
          <button className="btn btn-sm btn-primary" disabled={!!busy} onClick={() => void makeSlice(true)}>
            <Sparkles size={12} /> 生成切片并加入计划
          </button>
          <button className="btn btn-sm" disabled={!!busy} onClick={() => void makeSlice(false)}>
            <BookOpen size={12} /> 只生成切片
          </button>
          <button className="btn btn-sm" disabled={!!busy} onClick={() => void addPending()}>
            <Plus size={12} /> 加入计划（待生成）
          </button>
        </div>
      </div>

      {node.files.length ? (
        <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
          <div className="panel-label">相关文件</div>
          <div className="col" style={{ gap: 4 }}>
            {node.files.map((file) => (
              <button key={file} className="rail-artifact" onClick={() => openFile(file)}>
                <span className="mono small">{file}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel-flat panel-body">
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="panel-label">节点讲解</div>
          <span className="spacer" />
          {node.detail ? (
            <button className="btn btn-xs btn-ghost" disabled={!!busy}
              onClick={() => void explain(skeleton.id, node.id)}>
              <RefreshCw size={10} /> 重新生成
            </button>
          ) : null}
        </div>
        {node.detail ? (
          <RichText
            text={node.detail}
            symbols={base?.symbols || {}}
            files={new Set(base?.files || [])}
            onSymbol={openSymbol}
            onLocation={openFile}
          />
        ) : explaining ? (
          <div className="loading">正在生成节点讲解…</div>
        ) : (
          <div className="empty" style={{ padding: 18 }}>
            <strong>这一段还没有讲解</strong>
            点击“生成节点讲解”会按文件级、通俗语言讲清这个节点的作用、关系和边界。
            <div style={{ marginTop: 10 }}>
              <button className="btn btn-sm btn-primary" onClick={() => void explain(skeleton.id, node.id)}>
                <Sparkles size={12} /> 生成节点讲解
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <span className="small muted">节点讲解不等于逐函数阅读；函数名可点击跳转。</span>
        <span className="spacer" />
        <button className="btn btn-sm btn-ghost" onClick={() => {
          setStage("plan");
          if (track) navigate(trackPath(track.track.id, "plan"));
        }}>
          去计划 <ArrowRight size={12} />
        </button>
      </div>
    </div>
  );
}
