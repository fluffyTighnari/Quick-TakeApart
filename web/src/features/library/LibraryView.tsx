import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Boxes, FileCode2, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { api } from "../../core/api";
import { useApp } from "../../core/store";
import type { Skeleton, Slice } from "../../types";

function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function LibraryView() {
  const navigate = useNavigate();
  const workspace = useApp((s) => s.workspace);
  const track = useApp((s) => s.track);
  const activeTrackId = useApp((s) => s.activeTrackId);
  const selectSlice = useApp((s) => s.selectSlice);
  const selectSkeleton = useApp((s) => s.selectSkeleton);
  const setStage = useApp((s) => s.setStage);
  const generateSlice = useApp((s) => s.generateSlice);
  const refreshWorkspace = useApp((s) => s.refreshWorkspace);
  const selectTrack = useApp((s) => s.selectTrack);
  const [query, setQuery] = useState("");
  const [strategy, setStrategy] = useState("");
  const [trackFilter, setTrackFilter] = useState("");
  const [kind, setKind] = useState<"all" | "slice" | "skeleton">("all");

  const slices = workspace?.slices || [];
  const skeletons = track?.skeletons || [];

  const filteredSlices = useMemo(() => {
    const q = query.trim().toLowerCase();
    return slices.filter((slice) => {
      if (strategy && !slice.strategies.includes(strategy)) return false;
      if (trackFilter && slice.trackId !== trackFilter) return false;
      if (!q) return true;
      return `${slice.title} ${slice.query} ${slice.summary}`.toLowerCase().includes(q);
    });
  }, [slices, query, strategy, trackFilter]);

  const filteredSkeletons = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (kind === "slice") return [];
    return skeletons.filter((skeleton) => {
      if (!q) return true;
      return `${skeleton.title} ${skeleton.overview} ${skeleton.focus}`.toLowerCase().includes(q);
    });
  }, [skeletons, query, kind]);

  const showSlices = kind !== "skeleton";
  const showSkeletons = kind !== "slice";

  async function openSlice(slice: Slice) {
    await selectSlice(slice.id);
    setStage("read");
    if (activeTrackId) navigate(`/track/${activeTrackId}/read/${slice.id}`);
  }

  function openSkeleton(skeleton: Skeleton) {
    selectSkeleton(skeleton.id);
    setStage("architecture");
    if (activeTrackId) navigate(`/track/${activeTrackId}/architecture`);
  }

  async function removeSlice(slice: Slice) {
    if (!confirm(`删除切片「${slice.title}」？计划里的引用会变成悬空。`)) return;
    await api.deleteSlice(slice.id);
    await refreshWorkspace();
    if (track) await selectTrack(track.track.id);
  }

  async function removeSkeleton(skeleton: Skeleton) {
    if (!confirm(`删除骨架「${skeleton.title}」？`)) return;
    await api.deleteSkeleton(skeleton.id);
    if (track) await selectTrack(track.track.id);
  }

  async function newSlice() {
    const q = window.prompt("想切出什么问题？", "");
    if (!q) return;
    const slice = await generateSlice(q);
    if (slice && activeTrackId) navigate(`/track/${activeTrackId}/read/${slice.id}`);
  }

  return (
    <div className="stage">
      <div className="stage-head reveal">
        <div className="grow">
          <div className="eyebrow">Stage 04 · Library</div>
          <h1 className="stage-title">库</h1>
          <p className="stage-sub">
            所有轨道生成的切片都在这里；骨架属于当前轨道。切片是全局产物，计划可以引用它，
            删除计划不会删除切片。
          </p>
          <div className="row wrap" style={{ gap: 6, marginTop: 9 }}>
            <span className="chip teal">{slices.length} 切片</span>
            <span className="chip">{skeletons.length} 骨架</span>
            <span className="chip">{workspace?.tracks.length || 0} 轨道</span>
          </div>
        </div>
        <div className="stage-actions">
          <button className="btn btn-sm btn-primary" onClick={() => void newSlice()}>
            <Plus size={13} /> 新切片
          </button>
        </div>
      </div>

      <div className="lib-filters reveal reveal-1">
        <div style={{ position: "relative", flex: 1, minWidth: 220 }}>
          <Search size={13} style={{ position: "absolute", left: 10, top: 9, color: "var(--muted)" }} />
          <input
            className="input"
            style={{ paddingLeft: 30 }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜切片标题、问题、概要…"
          />
        </div>
        <select className="select" style={{ width: 150 }} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="">全部策略</option>
          <option value="path">链路 path</option>
          <option value="sequence">时序 sequence</option>
          <option value="crosscut">横切 crosscut</option>
          <option value="zones">分区 zones</option>
          <option value="calltree">调用树 calltree</option>
          <option value="dataflow">数据流 dataflow</option>
        </select>
        <select className="select" style={{ width: 150 }} value={trackFilter} onChange={(e) => setTrackFilter(e.target.value)}>
          <option value="">全部轨道</option>
          {(workspace?.tracks || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <div className="segmented">
          <button className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>全部</button>
          <button className={kind === "slice" ? "active" : ""} onClick={() => setKind("slice")}>切片</button>
          <button className={kind === "skeleton" ? "active" : ""} onClick={() => setKind("skeleton")}>骨架</button>
        </div>
      </div>

      {showSkeletons && filteredSkeletons.length ? (
        <section style={{ marginBottom: 24 }}>
          <div className="row" style={{ marginBottom: 9 }}>
            <h2 style={{ fontSize: 19 }}>逻辑骨架</h2>
            <span className="spacer" />
            <span className="small muted">{filteredSkeletons.length}</span>
          </div>
          <div className="lib-grid">
            {filteredSkeletons.map((skeleton) => (
              <button className="lib-card reveal" key={skeleton.id} onClick={() => openSkeleton(skeleton)}>
                <div className="row">
                  <span className="chip teal"><Boxes size={10} /> 骨架</span>
                  <span className="spacer" />
                  <span className="small muted">{fmtDate(skeleton.createdAt)}</span>
                </div>
                <div className="lc-title" style={{ marginTop: 8 }}>{skeleton.title}</div>
                <div className="lc-sum">{skeleton.overview}</div>
                <div className="lc-meta">
                  <span className="chip">{skeleton.main.length} 主流程</span>
                  <span className="chip">{skeleton.support.length} 支撑</span>
                  <span className="chip">{skeleton.detailCount || 0} 讲解</span>
                  <span className="spacer" />
                  <span
                    className="chip muted"
                    role="button"
                    onClick={(e) => { e.stopPropagation(); void removeSkeleton(skeleton); }}
                  ><Trash2 size={10} /></span>
                </div>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {showSlices ? (
        <section>
          <div className="row" style={{ marginBottom: 9 }}>
            <h2 style={{ fontSize: 19 }}>切片</h2>
            <span className="spacer" />
            <span className="small muted">{filteredSlices.length}</span>
          </div>
          {filteredSlices.length ? (
            <div className="lib-grid">
              {filteredSlices.map((slice) => (
                <button className="lib-card reveal" key={slice.id} onClick={() => void openSlice(slice)}>
                  <div className="row">
                    <span className="chip teal"><FileCode2 size={10} /> 切片</span>
                    <span className="spacer" />
                    <span className="small muted">{fmtDate(slice.createdAt)}</span>
                  </div>
                  <div className="lc-title" style={{ marginTop: 8 }}>{slice.title}</div>
                  <div className="lc-sum">{slice.query || slice.summary}</div>
                  <div className="lc-meta">
                    {slice.strategies.map((s) => <span className="chip" key={s}>{s}</span>)}
                    <span className="chip">{slice.segments.length} 片段</span>
                    {slice.quality && !slice.quality.ok ? <span className="chip rust">片段异常</span> : null}
                    {slice.staleness && !slice.staleness.fresh ? <span className="chip amber">{slice.staleness.summary}</span> : null}
                    <span className="spacer" />
                    <span
                      className="chip muted"
                      role="button"
                      onClick={(e) => { e.stopPropagation(); void removeSlice(slice); }}
                    ><Trash2 size={10} /></span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty">
              <strong>没有匹配的切片</strong>
              换一个搜索词，或者从阅读台提一个问题生成切片。
            </div>
          )}
        </section>
      ) : null}

      <div className="row wrap" style={{ marginTop: 22, gap: 8 }}>
        <button className="btn btn-sm" onClick={() => void newSlice()}>
          <Sparkles size={13} /> 按问题生成切片
        </button>
        {track ? (
          <button className="btn btn-sm btn-ghost" onClick={() => {
            setStage("plan");
            if (activeTrackId) navigate(`/track/${activeTrackId}/plan`);
          }}>
            回到计划
          </button>
        ) : null}
      </div>
    </div>
  );
}
