import { X } from "lucide-react";
import { useApp } from "../core/store";

export function StatusBar() {
  const workspace = useApp((s) => s.workspace);
  const track = useApp((s) => s.track);
  const busy = useApp((s) => s.busy);
  const notice = useApp((s) => s.notice);
  const error = useApp((s) => s.error);
  const setNotice = useApp((s) => s.setNotice);
  const setError = useApp((s) => s.setError);

  return (
    <footer className="statusbar">
      <span className="st-item">
        <span className={`dot${busy ? " busy" : ""}`} />
        {busy || "就绪"}
      </span>
      {workspace ? (
        <span className="st-item">
          {workspace.name} · {workspace.stats.files} 文件 / {workspace.stats.callables} 函数 / {workspace.stats.edges} 边
        </span>
      ) : null}
      <span className="st-item"><span className="dot" /> 持久化 · .qta/</span>
      {track ? <span className="st-item">轨道 · {track.track.name}</span> : null}
      <span className="st-spacer" />
      {notice ? (
        <span className="st-item" style={{ maxWidth: 420 }}>
          <span className="truncate" title={notice}>{notice}</span>
          <button className="btn-ghost btn-xs" onClick={() => setNotice(null)}><X size={10} /></button>
        </span>
      ) : null}
      {error ? (
        <span className="st-item" style={{ color: "var(--rust)", maxWidth: 420 }}>
          <span className="truncate" title={error}>{error}</span>
          <button className="btn-ghost btn-xs" onClick={() => setError(null)}><X size={10} /></button>
        </span>
      ) : null}
      <span className="st-item">Ctrl/Cmd+K 命令</span>
      <span className="st-item">Ctrl+点击函数/关键字</span>
    </footer>
  );
}
