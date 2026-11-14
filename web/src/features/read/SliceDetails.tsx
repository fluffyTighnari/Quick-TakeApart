import { useNavigate } from "react-router-dom";
import { AlertTriangle, BookOpen, GitBranch, RefreshCw, Workflow } from "lucide-react";
import { useApp } from "../../core/store";
import type { Slice } from "../../types";
import { RichText } from "../../ui/RichText";

export function SliceDetails({ slice }: { slice: Slice | null }) {
  const navigate = useNavigate();
  const base = useApp((s) => s.base);
  const track = useApp((s) => s.track);
  const selectSkeleton = useApp((s) => s.selectSkeleton);
  const selectSkeletonNode = useApp((s) => s.selectSkeletonNode);
  const selectSymbol = useApp((s) => s.selectSymbol);
  const selectFile = useApp((s) => s.selectFile);
  const setStage = useApp((s) => s.setStage);
  const regenerateSlice = useApp((s) => s.regenerateSlice);
  const busy = useApp((s) => s.busy);

  if (!slice) {
    return <div className="empty"><strong>还没有打开切片</strong>从左侧切片、计划步骤或切片库打开一条。</div>;
  }

  function openSymbol(sid: string) {
    void selectSymbol(sid);
    setStage("read");
    if (track) navigate(`/track/${track.track.id}/read`);
  }

  function openLocation(file: string) {
    void selectFile(file);
    setStage("read");
    if (track) navigate(`/track/${track.track.id}/read`);
  }

  const ref = (slice.source?.ref || {}) as { skeletonId?: string; nodeId?: string };
  const skeleton = track?.skeletons?.find((s) => s.id === ref.skeletonId) || null;
  const skeletonNode = skeleton
    ? [...skeleton.main, ...skeleton.support].find((n) => n.id === ref.nodeId) || null
    : null;

  function openSkeletonNode() {
    if (!skeleton || !skeletonNode) return;
    selectSkeleton(skeleton.id);
    selectSkeletonNode(skeletonNode.id);
    setStage("architecture");
    if (track) navigate(`/track/${track.track.id}/architecture`);
  }

  const first = slice.segments[0] || null;
  const last = slice.segments[slice.segments.length - 1] || null;

  return (
    <div>
      <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 5 }}>阅读路线 · Slice</div>
        <div className="panel-title" style={{ fontSize: 19 }}>{slice.title}</div>
        <p className="small muted" style={{ marginTop: 6 }}>{slice.query}</p>
        <div className="row wrap" style={{ gap: 5, marginTop: 8 }}>
          {slice.strategies.map((strategy) => (
            <span className="chip teal" key={strategy}>{strategy}</span>
          ))}
          <span className="chip">{slice.segments.length} 片段</span>
          {slice.source?.generator === "heuristic" ? <span className="chip">本地推测</span> : null}
          {slice.staleness && !slice.staleness.fresh ? (
            <span className="chip amber">{slice.staleness.summary}</span>
          ) : null}
        </div>
        {slice.quality && !slice.quality.ok ? (
          <div className="notice warn" style={{ marginTop: 9 }}>
            <AlertTriangle size={12} />
            <span>
              {[
                slice.quality.thinSegments > 0 ? `有 ${slice.quality.thinSegments} 个片段小于 2 行` : "",
                slice.quality.ungroupedViews ? "有分区/横切视图没有分组" : "",
              ].filter(Boolean).join("，")}
              。建议原地重新生成；计划引用不会断。
            </span>
          </div>
        ) : null}
      </div>

      {skeletonNode ? (
        <div className="panel-flat panel-body explanation-contract" style={{ marginBottom: 12 }}>
          <div className="row" style={{ marginBottom: 7 }}>
            <div className="grow">
              <div className="eyebrow" style={{ marginBottom: 2 }}>全局讲解 · 复用阶段一</div>
              <div className="panel-title" style={{ fontSize: 16 }}>{skeletonNode.title}</div>
            </div>
            <button className="btn btn-xs btn-ghost" onClick={openSkeletonNode}>
              打开骨架节点
            </button>
          </div>
          {skeletonNode.detail ? (
            <RichText
              text={skeletonNode.detail}
              symbols={base?.symbols || {}}
              files={new Set(base?.files || [])}
              onSymbol={openSymbol}
              onLocation={openLocation}
            />
          ) : (
            <div className="small muted">
              这个骨架节点还没有全局讲解。回到阶段一点节点生成一次，这里会自动复用。
            </div>
          )}
          <div className="small muted" style={{ marginTop: 8 }}>
            全局理解以阶段一为准；本页只负责把这条切片怎么读讲清楚。
          </div>
        </div>
      ) : null}

      <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
        <div className="rail-label" style={{ paddingLeft: 0 }}>这条切片怎么读</div>
        {!skeletonNode ? (
          <p className="small muted" style={{ marginTop: 5 }}>
            这是自由问题生成的切片。全局背景请看阶段一骨架；这里只保留阅读路线和代码位置。
          </p>
        ) : null}
        <div className="col" style={{ gap: 5, marginTop: 8 }}>
          {slice.views.map((view, index) => (
            <div key={`${view.title}-${index}`} className="row" style={{ gap: 6 }}>
              {view.kind === "sequence" ? <Workflow size={12} /> : <GitBranch size={12} />}
              <span className="small">{view.title}</span>
              <span className="chip muted" style={{ marginLeft: "auto" }}>{view.kind}</span>
            </div>
          ))}
          {!slice.views.length ? <div className="small muted">没有视图。</div> : null}
        </div>
        {first && last ? (
          <div className="small muted" style={{ marginTop: 9 }}>
            从 <span className="mono">{first.file}:{first.startLine}</span> 开始，
            到 <span className="mono">{last.file}:{last.endLine}</span> 结束。
            左侧切片目录可以按流程、文件、函数切换。
          </div>
        ) : null}
      </div>

      <div className="panel-flat panel-body">
        <div className="row wrap" style={{ gap: 5 }}>
          <button className="btn btn-sm" onClick={() => {
            setStage("read");
            if (track) navigate(`/track/${track.track.id}/read/${slice.id}`);
          }}>
            <BookOpen size={12} /> 在阅读台打开
          </button>
          <button
            className="btn btn-sm"
            disabled={!!busy}
            onClick={() => void regenerateSlice(slice.id)}
          >
            <RefreshCw size={12} className={busy ? "spin" : ""} /> 重新生成
          </button>
        </div>
        <div className="small muted" style={{ marginTop: 8 }}>
          批注留在代码片段旁边，不再在右栏重复一遍。
        </div>
      </div>
    </div>
  );
}
