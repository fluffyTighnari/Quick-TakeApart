import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Copy, Maximize2, MessageSquare, Minimize2 } from "lucide-react";
import { useApp } from "../../core/store";
import type { Annotation, Segment, SelectionContext, Sym } from "../../types";
import { CodeReader } from "../../ui/CodeReader";
import { RichText } from "../../ui/RichText";

function shortName(sid: string) {
  return sid.split("::").pop()?.split(".").pop() || sid;
}

export function SegmentCard({
  segment,
  annotations,
  symbols,
  onAsk,
  onTrace,
  onOpenFile,
  onSymbol,
  onSliceSelection,
}: {
  segment: Segment;
  annotations: Annotation[];
  symbols: Record<string, Sym>;
  onAsk: (ctx: SelectionContext) => void;
  onTrace: (file: string, line: number, char: number) => void;
  onOpenFile: (file: string, line: number) => void;
  onSymbol: (sid: string) => void;
  onSliceSelection?: (ctx: SelectionContext) => void;
}) {
  const sourceFor = useApp((s) => s.sourceFor);
  const [source, setSource] = useState("");
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setSource("");
    setError("");
    sourceFor(segment.file)
      .then((text) => { if (alive) setSource(text); })
      .catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    return () => { alive = false; };
  }, [segment.file, sourceFor]);

  const lines = source.split("\n");
  const excerpt = lines.slice(segment.startLine - 1, segment.endLine).join("\n");
  const text = expanded ? source : excerpt;
  const baseLine = expanded ? 1 : segment.startLine;
  const focus = { start: segment.startLine, end: segment.endLine };
  const roleClass = segment.role === "skip" ? "amber" : segment.role === "entry" ? "teal" : "muted";

  return (
    <div className="seg-card">
      <div className="seg-head" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <div className="grow">
          <div className="sh-file">{segment.file}:{segment.startLine}–{segment.endLine}</div>
          {segment.symbolId ? <div className="sh-sym">{shortName(segment.symbolId)}</div> : null}
        </div>
        <span className={`chip ${roleClass}`}>{segment.role || "context"}</span>
      </div>

      {open ? (
        <>
          {segment.note ? <div className="seg-note">{segment.note}</div> : null}
          {error ? <div className="notice bad" style={{ margin: 8 }}>{error}</div> : null}
          {!source && !error ? <div className="loading" style={{ padding: 12 }}>读取源码…</div> : null}
          {source ? (
            <CodeReader
              file={segment.file}
              text={text}
              baseLine={baseLine}
              symbols={symbols}
              focus={focus}
              maxHeight={expanded ? 620 : 360}
              showAll={false}
              onTrace={(file, line, char) => onTrace(file, line, char)}
              onSymbol={onSymbol}
              onAsk={onAsk}
              onSliceSelection={onSliceSelection}
            />
          ) : null}
          <div className="row" style={{ padding: "6px 9px", borderTop: "1px solid var(--line)", gap: 5 }}>
            <button className="btn btn-xs btn-ghost" onClick={() => setExpanded((v) => !v)}>
              {expanded ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
              {expanded ? "只看片段" : "展开整文件"}
            </button>
            <button className="btn btn-xs btn-ghost" onClick={() => onOpenFile(segment.file, segment.startLine)}>
              文件导航
            </button>
            <span className="spacer" />
            <button
              className="btn btn-xs"
              onClick={() => onAsk({
                file: segment.file,
                startLine: segment.startLine,
                endLine: segment.endLine,
                text: excerpt,
                symbolId: segment.symbolId,
                label: `${segment.file}:${segment.startLine}-${segment.endLine}`,
              })}
            >
              <MessageSquare size={11} /> 提问
            </button>
            <button
              className="btn btn-xs btn-ghost"
              title="复制引用"
              onClick={() => void navigator.clipboard?.writeText(`${segment.file}:${segment.startLine}-${segment.endLine}`)}
            >
              <Copy size={11} />
            </button>
          </div>
          {annotations.map((annotation) => (
            <div key={annotation.id} style={{ padding: "8px 11px", borderTop: "1px solid var(--line)", background: "rgba(255,255,255,.35)" }}>
              <RichText
                text={annotation.markdown}
                symbols={symbols}
                files={new Set(Object.values(symbols).map((s) => s.file))}
                onSymbol={onSymbol}
                onLocation={(file, line) => onOpenFile(file, line)}
              />
            </div>
          ))}
        </>
      ) : null}
    </div>
  );
}
