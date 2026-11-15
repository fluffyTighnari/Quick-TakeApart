import { ArrowDownLeft, ArrowUpRight, CircleDot, Crosshair, X } from "lucide-react";
import { useApp } from "../../core/store";

function shortName(sid: string) {
  return sid.split("::").pop()?.split(".").pop() || sid;
}

export function TracePanel() {
  const result = useApp((s) => s.traceResult);
  const request = useApp((s) => s.traceRequest);
  const loading = useApp((s) => s.traceLoading);
  const trace = useApp((s) => s.trace);
  const selectFile = useApp((s) => s.selectFile);
  const selectSymbol = useApp((s) => s.selectSymbol);
  const setStage = useApp((s) => s.setStage);
  const setTraceOpen = useApp((s) => s.setTraceOpen);

  if (!request) {
    return <div className="empty"><strong>还没有查找</strong>在代码里 Ctrl+点击函数或变量，查看定义、引用和调用关系。</div>;
  }

  const locations = (result?.locations || result?.items || [])
    .filter((location) => !location.external);
  const kinds: { id: string; label: string; icon: typeof Crosshair }[] = [
    { id: "definition", label: "定义", icon: Crosshair },
    { id: "references", label: "引用", icon: CircleDot },
    { id: "callers", label: "来源", icon: ArrowDownLeft },
    { id: "callees", label: "去向", icon: ArrowUpRight },
  ];

  return (
    <div>
      <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
        <div className="row">
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 4 }}>Trace</div>
            <div className="panel-title" style={{ fontSize: 16 }}>来源与去向</div>
            <div className="small muted" style={{ marginTop: 4 }}>{request.file}:{request.line}</div>
          </div>
          <button className="icon-btn" onClick={() => setTraceOpen(false)}><X size={14} /></button>
        </div>
        <div className="row wrap" style={{ gap: 4, marginTop: 10 }}>
          {kinds.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`btn btn-xs${result?.kind === id ? " btn-primary" : ""}`}
              disabled={loading}
              onClick={() => void trace(request.file, request.line, request.char, id)}
            >
              <Icon size={11} /> {label}
            </button>
          ))}
          <span className="spacer" />
          <span className="chip muted">{result?.engine === "lsp" ? "LSP" : "索引近似"}</span>
        </div>
      </div>

      {loading ? <div className="loading">正在询问语言服务器…</div> : null}

      {!loading && result ? (
        <div className="col" style={{ gap: 5 }}>
          {locations.length ? locations.map((loc, i) => (
            <button
              key={i}
              className="rail-artifact"
              style={{ padding: "7px 8px", whiteSpace: "normal" }}
              onClick={() => {
                if (loc.symbolId) void selectSymbol(loc.symbolId);
                else void selectFile(loc.file);
                setStage("read");
              }}
            >
              <div className="row">
                <span className="mono small">{loc.symbolId ? shortName(loc.symbolId) : loc.file}</span>
                <span className="spacer" />
                <span className="chip muted" style={{ fontSize: 9 }}>{loc.file}:{loc.line}</span>
              </div>
              {loc.sites?.length ? (
                <div className="small muted" style={{ marginTop: 3 }}>
                  调用点：{loc.sites.map((s) => `${s.file}:${s.line}`).join(" · ")}
                </div>
              ) : null}
            </button>
          )) : (
            <div className="empty">
              <strong>没有项目内结果</strong>
              {result.engine === "index" ? "索引里没有这条边；可能需要 LSP 才能解析。" : "语言服务器没有返回项目内位置。"}
            </div>
          )}
          {result.externalCount ? (
            <div className="notice info" style={{ marginTop: 8 }}>
              已隐藏 {result.externalCount} 个项目外位置（标准库 / 第三方库）。追踪只展示当前项目内的符号。
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
