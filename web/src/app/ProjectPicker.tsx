import { useEffect, useState, type DragEvent } from "react";
import {
  ArrowRight, FolderOpen, FolderSearch, Home, HardDrive, MousePointer2, Upload,
} from "lucide-react";
import { api } from "../core/api";
import { useApp } from "../core/store";
import { extractDropPath } from "../core/localPath";
import { FolderBrowser } from "./FolderBrowser";

export function ProjectPicker({ error }: { error: string | null }) {
  const openProject = useApp((s) => s.openProject);
  const busy = useApp((s) => s.busy);
  const [root, setRoot] = useState("");
  const [recent, setRecent] = useState<string[]>([]);
  const [roots, setRoots] = useState<{ path: string; label: string; kind: string }[]>([]);
  const [defaultRoot, setDefaultRoot] = useState("");
  const [localError, setLocalError] = useState("");
  const [browserOpen, setBrowserOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [dropOver, setDropOver] = useState(false);
  const [dropNote, setDropNote] = useState("");

  useEffect(() => {
    api.projects()
      .then((data) => {
        setRecent(data.recent || []);
        setRoots(data.roots || []);
        setDefaultRoot(data.defaultRoot || "");
        setRoot(data.root || data.recent?.[0] || data.defaultRoot || "");
      })
      .catch(() => undefined);
  }, []);

  async function submit(path = root) {
    if (!path.trim()) return;
    setLocalError("");
    setDropNote("");
    try {
      await openProject(path.trim());
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    }
  }

  async function chooseFolder() {
    setPicking(true);
    setLocalError("");
    try {
      const res = await api.pickFolder(root || defaultRoot);
      if (res.path) {
        setRoot(res.path);
        await submit(res.path);
      } else if (!res.cancelled) {
        setLocalError("系统文件夹选择器不可用；请用“浏览目录”或直接输入路径。");
      }
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setPicking(false);
    }
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDropOver(false);
    setDropNote("");
    const candidate = extractDropPath(event.dataTransfer);
    if (candidate) {
      setRoot(candidate);
      await submit(candidate);
      return;
    }

    setDropNote(
      "浏览器出于安全限制，不会把拖入文件夹的绝对路径交给网页。请用“选择文件夹”或“浏览目录”。",
    );
  }

  return (
    <div className="picker-wrap">
      <div
        className={`picker reveal${dropOver ? " drop-active" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDropOver(true); }}
        onDragLeave={() => setDropOver(false)}
        onDrop={(e) => void handleDrop(e)}
      >
        <div className="eyebrow">Quick-TakeApart · 阅读台</div>
        <h1>先选一个想读懂的项目</h1>
        <p className="sub">
          一个目录就是一份持久 session。索引、逻辑骨架、学习轨道、切片和对话都会落在
          <code style={{ margin: "0 4px" }}>.qta/</code>
          下，下次打开仍在。
        </p>

        <div className="form-row">
          <div className="field">
            <label>项目根目录</label>
            <input
              className="input"
              value={root}
              spellCheck={false}
              placeholder="D:\\Workspace\\Code\\phy\\Quick-TakeApart"
              onChange={(e) => setRoot(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
              }}
            />
          </div>
          <button className="btn btn-primary" onClick={() => void submit()} disabled={!!busy}>
            <FolderOpen size={14} />
            {busy ? "索引中…" : "打开项目"}
            <ArrowRight size={13} />
          </button>
        </div>

        <div className="row wrap" style={{ marginTop: 9, gap: 6 }}>
          <button className="btn btn-sm" disabled={!!busy || picking} onClick={() => void chooseFolder()}>
            <FolderSearch size={13} /> {picking ? "等待选择…" : "选择文件夹"}
          </button>
          <button className="btn btn-sm" onClick={() => setBrowserOpen(true)}>
            <MousePointer2 size={13} /> 浏览目录
          </button>
          <span className="small muted" style={{ marginLeft: "auto" }}>
            支持绝对路径、~、file:///、带引号路径
          </span>
        </div>

        {recent.length ? (
          <div className="recent">
            <div className="rail-label" style={{ padding: "4px 0 4px" }}>最近打开</div>
            {recent.map((item) => (
              <button key={item} onClick={() => { setRoot(item); void submit(item); }} title={item}>
                {item}
              </button>
            ))}
          </div>
        ) : null}

        {roots.length ? (
          <div className="recent" style={{ marginTop: 10 }}>
            <div className="rail-label" style={{ padding: "4px 0 4px" }}>常用位置</div>
            <div className="row wrap" style={{ gap: 5 }}>
              {roots.map((item) => (
                <button
                  key={item.path}
                  className="chip"
                  title={item.path}
                  onClick={() => setRoot(item.path)}
                >
                  {item.kind === "home" ? <Home size={11} /> : <HardDrive size={11} />}
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className={`drop-zone${dropOver ? " over" : ""}`}>
          <Upload size={18} className="dz-icon" />
          <div className="grow">
            <div className="dz-title">也可以把项目文件夹拖到这里</div>
            <div className="dz-hint">桌面应用/部分浏览器会提供本地路径；否则用上面的“选择文件夹”。</div>
          </div>
        </div>

        {dropNote ? <div className="notice warn" style={{ marginTop: 10 }}>{dropNote}</div> : null}
        {localError || error ? (
          <div className="err">{localError || error}</div>
        ) : null}

        <div className="hint">
          提示：索引使用本地语言服务器（Python / TypeScript / Go，自动检测）。
          大项目第一次打开会慢一些；之后骨架、切片、对话都直接读磁盘，不会重新调用模型。
          {defaultRoot ? <span style={{ display: "block", marginTop: 4 }}>默认目录：{defaultRoot}</span> : null}
        </div>
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
