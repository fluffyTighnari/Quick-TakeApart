import { useEffect, useState, type DragEvent } from "react";
import { FolderOpen, FolderSearch, MousePointer2, Upload, X } from "lucide-react";
import { api } from "../core/api";
import { isImeEvent } from "../core/keyboard";
import { useApp } from "../core/store";
import { extractDropPath } from "../core/localPath";
import { useEscape } from "../ui/useEscape";
import { FolderBrowser } from "./FolderBrowser";

export function ProjectModal({ onClose }: { onClose: () => void }) {
  const openProject = useApp((s) => s.openProject);
  const busy = useApp((s) => s.busy);
  const [root, setRoot] = useState("");
  const [recent, setRecent] = useState<string[]>([]);
  const [defaultRoot, setDefaultRoot] = useState("");
  const [error, setError] = useState("");
  const [browserOpen, setBrowserOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [dropOver, setDropOver] = useState(false);
  const [dropNote, setDropNote] = useState("");

  useEscape(onClose);

  useEffect(() => {
    api.projects().then((data) => {
      setRecent(data.recent || []);
      setRoot(data.root || data.recent?.[0] || data.defaultRoot || "");
      setDefaultRoot(data.defaultRoot || "");
    }).catch(() => undefined);
  }, []);

  async function submit(path = root) {
    if (!path.trim()) return;
    setError("");
    setDropNote("");
    try {
      await openProject(path.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function chooseFolder() {
    setPicking(true);
    setError("");
    try {
      const res = await api.pickFolder(root || defaultRoot);
      if (res.path) {
        setRoot(res.path);
        await submit(res.path);
      } else if (!res.cancelled) {
        setError("系统文件夹选择器不可用；请用“浏览目录”或直接输入路径。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPicking(false);
    }
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDropOver(false);
    const candidate = extractDropPath(event.dataTransfer);
    if (candidate) {
      setRoot(candidate);
      await submit(candidate);
      return;
    }
    setDropNote("浏览器不会把拖入文件夹的绝对路径交给网页；请用“选择文件夹”或“浏览目录”。");
  }

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div
        className="palette dialog"
        style={{ padding: 18 }}
        onDragOver={(e) => { e.preventDefault(); setDropOver(true); }}
        onDragLeave={() => setDropOver(false)}
        onDrop={(e) => void handleDrop(e)}
      >
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>切换项目</div>
            <div className="panel-title">打开另一个目录</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="form-row">
          <div className="field">
            <label>项目根目录</label>
            <input
              className="input"
              autoFocus
              value={root}
              spellCheck={false}
              onChange={(e) => setRoot(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !isImeEvent(e)) void submit(); }}
            />
          </div>
          <button className="btn btn-primary" disabled={!!busy} onClick={() => void submit()}>
            <FolderOpen size={14} /> 打开
          </button>
        </div>

        <div className="row wrap" style={{ marginTop: 8, gap: 6 }}>
          <button className="btn btn-sm" disabled={!!busy || picking} onClick={() => void chooseFolder()}>
            <FolderSearch size={13} /> {picking ? "等待选择…" : "选择文件夹"}
          </button>
          <button className="btn btn-sm" onClick={() => setBrowserOpen(true)}>
            <MousePointer2 size={13} /> 浏览目录
          </button>
          <span className={`drop-zone${dropOver ? " over" : ""}`} style={{ margin: 0, padding: "5px 9px", flex: 1 }}>
            <Upload size={14} className="dz-icon" />
            <span className="small muted">拖入文件夹或路径</span>
          </span>
        </div>

        {recent.length ? (
          <div className="recent" style={{ marginTop: 12 }}>
            <div className="rail-label" style={{ padding: "2px 0 4px" }}>最近打开</div>
            {recent.map((item) => (
              <button key={item} onClick={() => { setRoot(item); void submit(item); }} title={item}>{item}</button>
            ))}
          </div>
        ) : null}

        {dropNote ? <div className="notice warn" style={{ marginTop: 10 }}>{dropNote}</div> : null}
        {error ? <div className="err">{error}</div> : null}
      </div>

      {browserOpen ? (
        <FolderBrowser
          initial={root || defaultRoot || undefined}
          onClose={() => setBrowserOpen(false)}
          onPick={(path) => {
            setBrowserOpen(false);
            setRoot(path);
            void submit(path);
          }}
        />
      ) : null}
    </div>
  );
}
