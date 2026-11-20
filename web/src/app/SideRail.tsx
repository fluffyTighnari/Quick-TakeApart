import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown, FileCode2, Layers, Plus, Route, Search, X,
} from "lucide-react";
import { useApp } from "../core/store";
import { isImeEvent } from "../core/keyboard";
import { stageFromPath, trackPath } from "../core/routes";
import { useEscape } from "../ui/useEscape";
import type { Stage } from "../types";
import { FileTree } from "../features/read/FileTree";
import { SliceDirectory } from "../features/read/SliceDirectory";

function NewTrackModal({ onClose }: { onClose: () => void }) {
  const createTrack = useApp((s) => s.createTrack);
  const busy = useApp((s) => s.busy);
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [intent, setIntent] = useState("");
  const [depth, setDepth] = useState("结构");
  const [error, setError] = useState("");

  useEscape(onClose);

  async function submit() {
    if (!name.trim()) return;
    try {
      const data = await createTrack(name.trim(), intent.trim(), depth);
      navigate(trackPath(data.track.id, "architecture"));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="palette dialog" style={{ padding: 18 }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>新学习轨道</div>
            <div className="panel-title">这个轨道想解决什么？</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="col">
          <div className="field">
            <label>轨道名</label>
            <input
              className="input"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isImeEvent(e)) void submit();
              }}
              placeholder="例如：搞懂请求主链路"
            />
          </div>
          <div className="field">
            <label>用途 / 目标</label>
            <textarea className="textarea" value={intent} onChange={(e) => setIntent(e.target.value)}
              placeholder="例如：先看骨架，再追一条主链路" />
          </div>
          <div className="field">
            <label>粒度契约</label>
            <select className="select" value={depth} onChange={(e) => setDepth(e.target.value)}>
              <option value="粗看">粗看：只建立位置感</option>
              <option value="结构">结构：看组件与主链路</option>
              <option value="逐函数">逐函数：按计划细读</option>
              <option value="只追链路">只追链路：不展开旁路</option>
            </select>
            <div className="small muted" style={{ marginTop: 5 }}>
              目的和粒度只在这里设置；计划、切片和节点动作都会继承。
            </div>
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-ghost" onClick={onClose}>取消</button>
            <button className="btn btn-primary" disabled={!!busy || !name.trim()} onClick={() => void submit()}>
              创建轨道
            </button>
          </div>
          {error ? <div className="notice bad">{error}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function SideRail() {
  const navigate = useNavigate();
  const location = useLocation();
  const workspace = useApp((s) => s.workspace);
  const track = useApp((s) => s.track);
  const activeTrackId = useApp((s) => s.activeTrackId);
  const activeSlice = useApp((s) => s.activeSlice);
  const activeSliceId = useApp((s) => s.activeSliceId);
  const selectTrack = useApp((s) => s.selectTrack);
  const openSlice = useApp((s) => s.openSlice);
  const setStage = useApp((s) => s.setStage);
  const [newTrack, setNewTrack] = useState(false);
  const [sliceQuery, setSliceQuery] = useState("");

  const stage: Stage = stageFromPath(location.pathname);

  const slices = useMemo(() => {
    const map = new Map((workspace?.slices || []).map((s) => [s.id, s]));
    for (const slice of track?.slices || []) map.set(slice.id, slice);
    return [...map.values()];
  }, [workspace, track]);
  const filteredSlices = slices.filter((s) =>
    !sliceQuery.trim() || `${s.title} ${s.query}`.toLowerCase().includes(sliceQuery.toLowerCase()),
  );

  async function switchTrack(id: string) {
    try {
      await selectTrack(id);
      const sliceId = stage === "read" ? useApp.getState().activeSliceId : null;
      navigate(trackPath(id, stage, sliceId));
    } catch {
      /* the status bar shows the failure */
    }
  }

  async function switchSlice(id: string) {
    if (!id) return;
    const slice = slices.find((item) => item.id === id);
    if (!slice) return;
    const trackId = await openSlice(slice);
    if (!trackId) return;
    setStage("read");
    navigate(trackPath(trackId, "read", id));
  }

  const showSliceDirectory = stage === "read" && activeSlice;

  return (
    <aside className="rail">
      <div className="rail-top">
        <div className="rail-select-block">
          <div className="rail-label">
            <span>学习轨道</span>
            <button title="新建轨道" onClick={() => setNewTrack(true)}><Plus size={13} /></button>
          </div>
          <div className="rail-select-wrap">
            <select
              className="rail-select"
              value={activeTrackId || ""}
              onChange={(e) => void switchTrack(e.target.value)}
            >
              {(workspace?.tracks || []).map((t) => (
                <option key={t.id} value={t.id}>{t.name} · {t.sliceCount} 切片</option>
              ))}
            </select>
            <ChevronDown size={12} className="rail-select-caret" />
          </div>
        </div>

        <div className="rail-select-block">
          <div className="rail-label"><span>切片快捷选择</span><span className="badge">{slices.length}</span></div>
          <div className="rail-select-wrap">
            <select
              className="rail-select"
              value={activeSliceId || ""}
              onChange={(e) => void switchSlice(e.target.value)}
            >
              <option value="">选择切片…</option>
              {slices.map((s) => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
            <ChevronDown size={12} className="rail-select-caret" />
          </div>
          <div className="rail-slice-search">
            <Search size={10} />
            <input
              value={sliceQuery}
              onChange={(e) => setSliceQuery(e.target.value)}
              placeholder="过滤切片…"
            />
          </div>
          {sliceQuery ? (
            <div className="rail-slice-results">
              {filteredSlices.slice(0, 8).map((s) => (
                <button key={s.id} className="rail-artifact" onClick={() => void switchSlice(s.id)}>
                  <span className="ra-kind"><FileCode2 size={10} /></span>{s.title}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="rail-context">
        <div className="rail-context-head">
          {showSliceDirectory ? <Layers size={12} /> : <FileCode2 size={12} />}
          <span>{showSliceDirectory ? "切片目录" : "项目文件"}</span>
          <span className="spacer" />
          {showSliceDirectory ? (
            <button
              className="rail-context-toggle"
              title="回到项目文件树（不删除切片）"
              onClick={() => {
                useApp.getState().clearActiveSlice();
                if (activeTrackId) navigate(trackPath(activeTrackId, "read"));
              }}
            >
              项目文件
            </button>
          ) : null}
          {activeSlice ? <span className="chip muted">{activeSlice.segments.length} 片段</span> : null}
        </div>
        {showSliceDirectory && activeSlice ? (
          <SliceDirectory slice={activeSlice} />
        ) : (
          <FileTree />
        )}
      </div>

      <button
        className="rail-plan-shortcut"
        onClick={() => {
          if (!activeTrackId) return;
          setStage("plan");
          navigate(trackPath(activeTrackId, "plan"));
        }}
      >
        <Route size={12} /> 打开学习计划
      </button>

      {newTrack ? <NewTrackModal onClose={() => setNewTrack(false)} /> : null}
    </aside>
  );
}
