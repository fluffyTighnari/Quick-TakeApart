import { useMemo } from "react";
import { FileCode2, GitBranch, ListTree, Workflow } from "lucide-react";
import { useApp } from "../../core/store";
import type { Slice, View } from "../../types";

function shortName(sid: string) {
  return sid.split("::").pop()?.split(".").pop() || sid;
}

function segmentsForView(view: View, slice: Slice, index: number) {
  const exact = slice.segments.filter((seg) => seg.flowTitle && seg.flowTitle === view.title);
  const symbols = new Set(view.nodes.map((n) => n.symbolId));
  const bySymbol = slice.segments.filter((seg) => seg.symbolId && symbols.has(seg.symbolId));
  const chosen = exact.length ? exact : bySymbol.length ? bySymbol : index === 0 ? slice.segments : [];
  const seen = new Set<string>();
  return chosen.filter((seg) => {
    if (seen.has(seg.id)) return false;
    seen.add(seg.id);
    return true;
  });
}

export function SliceDirectory({ slice }: { slice: Slice }) {
  const activeSegmentId = useApp((s) => s.activeSegmentId);
  const activeFile = useApp((s) => s.activeFile);
  const selectSegment = useApp((s) => s.selectSegment);
  const selectSliceFile = useApp((s) => s.selectSliceFile);

  const files = useMemo(() => {
    const map = new Map<string, number>();
    for (const segment of slice.segments) {
      map.set(segment.file, (map.get(segment.file) || 0) + 1);
    }
    return [...map.entries()];
  }, [slice]);

  const functions = useMemo(
    () => slice.segments.filter((segment) => segment.symbolId),
    [slice],
  );

  return (
    <div className="slice-dir">
      {slice.views.map((view, index) => (
        <details key={view.title} open={index === 0} className="slice-dir-details">
          <summary>
            {view.kind === "sequence" ? <Workflow size={11} /> : <GitBranch size={11} />}
            <span className="truncate">{view.title}</span>
            <span className="chip muted">{view.kind}</span>
          </summary>
          <div className="slice-dir-list">
            {segmentsForView(view, slice, index).map((segment, i) => (
              <button
                key={segment.id}
                className={`slice-dir-row${segment.id === activeSegmentId ? " on" : ""}`}
                title={`${segment.file}:${segment.startLine}-${segment.endLine}`}
                onClick={() => selectSegment(segment.id)}
              >
                <span className="sdr-n">{i + 1}</span>
                <span className="sdr-main">
                  <span className="sdr-name">{segment.symbolId ? shortName(segment.symbolId) : segment.role}</span>
                  <span className="sdr-loc">{segment.file}:{segment.startLine}</span>
                </span>
                <span className={`status-dot ${segment.role === "skip" ? "warn" : "ok"}`} />
              </button>
            ))}
            {!segmentsForView(view, slice, index).length ? (
              <div className="rail-empty">这条流没有独立片段。</div>
            ) : null}
          </div>
        </details>
      ))}

      <details className="slice-dir-details" open>
        <summary><FileCode2 size={11} /><span>文件</span><span className="chip muted">{files.length}</span></summary>
        <div className="slice-dir-list">
          {files.map(([file, count]) => (
            <button
              key={file}
              className={`slice-dir-row${!activeSegmentId && file === activeFile ? " on" : ""}`}
              title={file}
              onClick={() => void selectSliceFile(
                file,
                slice.segments.find((segment) => segment.file === file)?.startLine ?? null,
              )}
            >
              <FileCode2 size={11} />
              <span className="sdr-main">
                <span className="sdr-name truncate">{file}</span>
                <span className="sdr-loc">{count} 片段</span>
              </span>
            </button>
          ))}
        </div>
      </details>

      <details className="slice-dir-details">
        <summary><ListTree size={11} /><span>函数 / 片段</span><span className="chip muted">{functions.length}</span></summary>
        <div className="slice-dir-list">
          {functions.map((segment) => (
            <button
              key={segment.id}
              className={`slice-dir-row${segment.id === activeSegmentId ? " on" : ""}`}
              title={`${segment.file}:${segment.startLine}`}
              onClick={() => selectSegment(segment.id)}
            >
              <span className="sdr-main">
                <span className="sdr-name">{shortName(segment.symbolId)}</span>
                <span className="sdr-loc">{segment.file}:{segment.startLine}</span>
              </span>
              <span className="chip muted">{segment.role}</span>
            </button>
          ))}
        </div>
      </details>
    </div>
  );
}
