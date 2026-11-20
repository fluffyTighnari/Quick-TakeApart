import { useEffect, useState } from "react";
import { ArrowUp, Check, ChevronRight, Folder, FolderGit2, HardDrive, Home, X } from "lucide-react";
import { api } from "../core/api";
import { isImeEvent } from "../core/keyboard";
import { useEscape } from "../ui/useEscape";

interface BrowseData {
  path: string;
  parent: string | null;
  entries: { name: string; path: string; hidden: boolean; project: boolean }[];
  roots: { path: string; label: string; kind: string }[];
  home: string;
  cwd: string;
}

function RootIcon({ kind }: { kind: string }) {
  if (kind === "home") return <Home size={11} />;
  if (kind === "drive" || kind === "root") return <HardDrive size={11} />;
  return <Folder size={11} />;
}

export function FolderBrowser({
  initial,
  onClose,
  onPick,
}: {
  initial?: string;
  onClose: () => void;
  onPick: (path: string) => void;
}) {
  const [data, setData] = useState<BrowseData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manual, setManual] = useState("");

  useEscape(onClose);

  async function load(path?: string) {
    setLoading(true);
    setError("");
    try {
      const next = await api.browse(path);
      setData(next);
      setManual(next.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(initial);
  }, [initial]);

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="palette folder-browser">
        <div className="folder-head">
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>选择项目目录</div>
            <div className="panel-title">浏览这台机器上的目录</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>

        <div className="folder-path">
          <input
            className="input"
            value={manual}
            spellCheck={false}
            onChange={(e) => setManual(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isImeEvent(e)) void load(manual);
            }}
            placeholder="D:\\path\\to\\project 或 ~/project"
          />
          <button className="btn btn-sm" onClick={() => void load(manual)}>前往</button>
        </div>

        <div className="folder-roots">
          {data?.roots.map((root) => (
            <button key={root.path} className="chip" title={root.path} onClick={() => void load(root.path)}>
              <RootIcon kind={root.kind} /> {root.label}
            </button>
          ))}
        </div>

        <div className="folder-current">
          <button
            className="btn btn-xs btn-ghost"
            disabled={!data?.parent || loading}
            onClick={() => data?.parent && void load(data.parent)}
          >
            <ArrowUp size={11} /> 上一级
          </button>
          <span className="small mono truncate" title={data?.path}>{data?.path || "…"}</span>
          <span className="spacer" />
          {data?.entries.some((e) => e.project) ? <span className="chip teal">含项目标记</span> : null}
        </div>

        <div className="folder-list">
          {loading ? <div className="loading" style={{ padding: 18 }}>读取目录…</div> : null}
          {error ? <div className="notice bad" style={{ margin: 10 }}>{error}</div> : null}
          {!loading && data?.entries.map((entry) => (
            <button
              key={entry.path}
              className={`folder-row${entry.project ? " project" : ""}`}
              onClick={() => void load(entry.path)}
              title={entry.path}
            >
              {entry.project ? <FolderGit2 size={14} /> : <Folder size={14} />}
              <span className="folder-name truncate">{entry.name}</span>
              {entry.project ? <span className="chip teal" style={{ fontSize: 9 }}>项目</span> : null}
              {entry.hidden ? <span className="chip muted" style={{ fontSize: 9 }}>隐藏</span> : null}
              <ChevronRight size={12} style={{ marginLeft: "auto", color: "var(--muted)" }} />
            </button>
          ))}
          {!loading && data && !data.entries.length ? (
            <div className="empty" style={{ margin: 12 }}>
              <strong>这里没有子目录</strong>
              可以直接选择当前目录，或返回上一级。
            </div>
          ) : null}
        </div>

        <div className="folder-foot">
          <span className="small muted truncate" title={data?.path}>{data?.path}</span>
          <span className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>取消</button>
          <button
            className="btn btn-primary"
            disabled={!data?.path || loading}
            onClick={() => data && onPick(data.path)}
          >
            <Check size={13} /> 选择此目录
          </button>
        </div>
      </div>
    </div>
  );
}
