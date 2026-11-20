import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileCode2, Search } from "lucide-react";
import { useApp } from "../../core/store";
import { trackPath } from "../../core/routes";

export function FileTree() {
  const navigate = useNavigate();
  const base = useApp((s) => s.base);
  const track = useApp((s) => s.track);
  const activeFile = useApp((s) => s.activeFile);
  const openCode = useApp((s) => s.openCode);
  const setStage = useApp((s) => s.setStage);
  const [query, setQuery] = useState("");

  const files = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (base?.files || []).filter((f) => !q || f.toLowerCase().includes(q));
  }, [base, query]);

  async function open(file: string) {
    await openCode(file);
    setStage("read");
    if (track) navigate(trackPath(track.track.id, "read"));
  }

  let currentDir: string | null = null;
  return (
    <div className="dir-tree">
      <div style={{ padding: "0 0 8px" }}>
        <div style={{ position: "relative" }}>
          <Search size={11} style={{ position: "absolute", left: 8, top: 9, color: "var(--muted)" }} />
          <input
            className="input"
            style={{ paddingLeft: 25, fontSize: 11, paddingTop: 6, paddingBottom: 6 }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="过滤文件…"
          />
        </div>
      </div>
      {files.map((file) => {
        const slash = file.lastIndexOf("/");
        const dir = slash >= 0 ? file.slice(0, slash) : ".";
        const header = dir !== currentDir ? dir : null;
        currentDir = dir;
        return (
          <div key={file}>
            {header ? <div className="tf-dir">{header}</div> : null}
            <button
              className={`tf-file${file === activeFile ? " on" : ""}`}
              title={file}
              onClick={() => void open(file)}
            >
              <FileCode2 size={11} />
              <span className="tf-name">{file.slice(slash + 1)}</span>
              <span className="tf-n">{(base?.byFile?.[file] || []).length}</span>
            </button>
          </div>
        );
      })}
      {!files.length ? <div className="rail-empty">没有匹配文件。</div> : null}
    </div>
  );
}
