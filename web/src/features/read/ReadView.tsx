import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle, ArrowRight, BookOpen, FileCode2, Maximize2, MessageSquare,
  Minimize2, Plus, RefreshCw,
} from "lucide-react";
import { useApp } from "../../core/store";
import type { SelectionContext, Slice, View } from "../../types";
import { SegmentCard } from "./SegmentCard";
import { CodeReader } from "../../ui/CodeReader";

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

function viewOfSegment(slice: Slice, segmentId: string | null): number {
  if (!segmentId) return 0;
  const segment = slice.segments.find((s) => s.id === segmentId);
  if (!segment) return 0;
  const byTitle = slice.views.findIndex((v) => v.title && v.title === segment.flowTitle);
  if (byTitle >= 0) return byTitle;
  const bySymbol = slice.views.findIndex((v) =>
    v.nodes.some((n) => n.symbolId === segment.symbolId));
  return bySymbol >= 0 ? bySymbol : 0;
}

function FullFileView({
  file,
  slice,
  onAsk,
  onSliceSelection,
  onTrace,
  onSymbol,
}: {
  file: string;
  slice: Slice | null;
  onAsk?: (ctx: SelectionContext) => void;
  onSliceSelection?: (ctx: SelectionContext) => void;
  onTrace: (file: string, line: number, char: number) => void;
  onSymbol: (sid: string) => void;
}) {
  const base = useApp((s) => s.base);
  const sourceFor = useApp((s) => s.sourceFor);
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setError("");
    sourceFor(file)
      .then((text) => { if (alive) setSource(text); })
      .catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    return () => { alive = false; };
  }, [file, sourceFor]);

  const ranges = (slice?.segments || [])
    .filter((s) => s.file === file)
    .map((s) => ({ start: s.startLine, end: s.endLine }));
  const focus = ranges[0] || null;

  if (error) return <div className="notice bad">{error}</div>;
  if (!source) return <div className="loading" style={{ padding: 18 }}>读取源码…</div>;
  return (
    <CodeReader
      file={file}
      text={source}
      symbols={base?.symbols || {}}
      focus={focus}
      ranges={ranges}
      showAll
      onTrace={onTrace}
      onSymbol={onSymbol}
      onAsk={onAsk}
      onSliceSelection={onSliceSelection}
    />
  );
}

export function ReadView() {
  const { sliceId } = useParams();
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const slice = useApp((s) => s.activeSlice);
  const activeSliceId = useApp((s) => s.activeSliceId);
  const activeSegmentId = useApp((s) => s.activeSegmentId);
  const activeFile = useApp((s) => s.activeFile);
  const selectSlice = useApp((s) => s.selectSlice);
  const selectSegment = useApp((s) => s.selectSegment);
  const selectSliceFile = useApp((s) => s.selectSliceFile);
  const openCode = useApp((s) => s.openCode);
  const setSelection = useApp((s) => s.setSelection);
  const setContextTab = useApp((s) => s.setContextTab);
  const trace = useApp((s) => s.trace);
  const setStage = useApp((s) => s.setStage);
  const generateSlice = useApp((s) => s.generateSlice);
  const focusMode = useApp((s) => s.focusMode);
  const toggleFocusMode = useApp((s) => s.toggleFocusMode);
  const [flowIndex, setFlowIndex] = useState(0);

  useEffect(() => {
    if (sliceId && sliceId !== activeSliceId) {
      void selectSlice(sliceId);
    }
  }, [sliceId, activeSliceId, selectSlice]);

  // The old reader preserved the main scroll position between slices, which made
  // every slice open at the bottom of the previous one. Always land at the top.
  useEffect(() => {
    document.querySelector(".main")?.scrollTo({ top: 0, behavior: "auto" });
  }, [activeSliceId, activeSegmentId, activeFile]);

  useEffect(() => {
    if (slice) setFlowIndex(viewOfSegment(slice, activeSegmentId));
  }, [slice?.id, activeSegmentId]);

  const segment = useMemo(
    () => slice?.segments.find((s) => s.id === activeSegmentId) || null,
    [slice, activeSegmentId],
  );

  const views = slice?.views || [];
  const view = views[flowIndex] || views[0] || null;
  const flowSegments = view && slice ? segmentsForView(view, slice, flowIndex) : [];

  function ask(ctx: SelectionContext) {
    if (!slice) return;
    setSelection(ctx);
    setContextTab("thread");
  }

  function onTrace(file: string, line: number, char: number) {
    void trace(file, line, char, "definition");
  }

  function onSymbol(sid: string) {
    const file = base?.symbols[sid]?.file;
    if (!file) return;
    void openCode(file, sid);
    setStage("read");
    if (track) navigate(`/track/${track.track.id}/read`);
  }

  async function sliceFromSelection(ctx: SelectionContext) {
    const label = ctx.label || `${ctx.file}:${ctx.startLine}-${ctx.endLine}`;
    const created = await generateSlice(`分析选中代码：${label}`, {
      scope: {
        kind: "selection",
        file: ctx.file,
        startLine: ctx.startLine,
        endLine: ctx.endLine,
        text: ctx.text,
        label,
      },
    });
    if (created && track) navigate(`/track/${track.track.id}/read/${created.id}`);
  }

  async function newQuestion() {
    if (!slice) return;
    const q = window.prompt("继续问一个问题，生成新的切片", "");
    if (!q) return;
    const created = await generateSlice(q);
    if (created && track) navigate(`/track/${track.track.id}/read/${created.id}`);
  }

  if (!slice) {
    if (activeFile) {
      return (
        <div className="stage read-stage">
          <div className="stage-head reveal">
            <div className="grow">
              <div className="eyebrow">Stage 03 · Global read</div>
              <h1 className="stage-title" style={{ fontSize: 24 }}>{activeFile}</h1>
              <p className="stage-sub">全量源码阅读。左侧文件树可切换文件；选中代码可以生成切片后再提问。</p>
            </div>
            <div className="stage-actions">
              <button className="btn btn-sm" onClick={toggleFocusMode}>
                {focusMode ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                {focusMode ? "退出全屏" : "全屏"}
              </button>
            </div>
          </div>
          <FullFileView
            file={activeFile}
            slice={null}
            onSliceSelection={(ctx) => void sliceFromSelection(ctx)}
            onTrace={onTrace}
            onSymbol={onSymbol}
          />
        </div>
      );
    }
    return (
      <div className="stage">
        <div className="stage-head reveal">
          <div className="grow">
            <div className="eyebrow">Stage 03 · Read</div>
            <h1 className="stage-title">阅读台</h1>
            <p className="stage-sub">从左侧文件树选一个文件开始全局阅读，或者在计划/骨架里生成切片。</p>
          </div>
        </div>
        <div className="empty">
          <strong>还没有打开内容</strong>
          左侧的文件树始终可用；选中切片后它会切换成切片目录。
        </div>
      </div>
    );
  }

  return (
    <div className="stage read-stage">
      <div className="stage-head reveal">
        <div className="grow">
          <div className="eyebrow">
            Stage 03 · Read · {slice.source?.kind === "skeleton-node" ? "骨架节点" : slice.source?.kind || "query"}
          </div>
          <h1 className="stage-title" style={{ fontSize: 26 }}>{slice.title}</h1>
          <p className="stage-sub">{slice.query}</p>
          <div className="row wrap" style={{ gap: 5, marginTop: 9 }}>
            {slice.strategies.map((s) => <span className="chip teal" key={s}>{s}</span>)}
            <span className="chip">{slice.segments.length} 片段</span>
            <span className="chip">{slice.views.length} 条流</span>
            {slice.staleness && !slice.staleness.fresh ? (
              <span className="chip amber"><AlertTriangle size={10} /> {slice.staleness.summary}</span>
            ) : null}
          </div>
        </div>
        <div className="stage-actions">
          <button className="btn btn-sm" onClick={() => setContextTab("thread")}>
            <MessageSquare size={13} /> 切片问答
          </button>
          <button className="btn btn-sm" onClick={newQuestion}>
            <Plus size={13} /> 新切片
          </button>
          <button className="btn btn-sm" onClick={toggleFocusMode}>
            {focusMode ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
            {focusMode ? "退出全屏" : "全屏"}
          </button>
        </div>
      </div>

      {slice.staleness && !slice.staleness.fresh ? (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          <AlertTriangle size={13} />
          这份切片是快照：{slice.staleness.summary}。仍可阅读，但个别位置可能已变化。
        </div>
      ) : null}

      <div className="read-toolbar">
        {views.length > 1 ? (
          <div className="flow-tabs" style={{ margin: 0 }}>
            {views.map((v, index) => (
              <button
                key={v.title}
                className={`flow-tab${flowIndex === index ? " active" : ""}`}
                onClick={() => {
                  setFlowIndex(index);
                  const first = segmentsForView(v, slice, index)[0];
                  if (first) selectSegment(first.id);
                }}
              >
                {v.title}
              </button>
            ))}
          </div>
        ) : (
          <span className="small muted">{view?.title || "切片段落"}</span>
        )}
        <span className="spacer" />
        <span className="small muted">左侧目录：流程 / 文件 / 函数</span>
      </div>

      {view && flowSegments.length ? (
        <div className="read-flow-strip">
          {flowSegments.map((item, index) => (
            <button
              key={item.id}
              className={`read-flow-step${item.id === activeSegmentId ? " on" : ""}`}
              onClick={() => selectSegment(item.id)}
              title={`${item.file}:${item.startLine}-${item.endLine}`}
            >
              <span className="rfs-n">{index + 1}</span>
              <span className="rfs-name">{item.symbolId ? item.symbolId.split("::").pop() : item.role}</span>
              <span className="rfs-file">{item.file.split("/").pop()}:{item.startLine}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="read-center">
        {segment ? (
          <SegmentCard
            segment={segment}
            annotations={slice.annotations.filter((a) =>
              a.anchor.segmentId === segment.id
              || (!!segment.symbolId && a.anchor.symbolId === segment.symbolId))}
            symbols={base?.symbols || {}}
            onAsk={ask}
            onTrace={onTrace}
            onOpenFile={(file) => void selectSliceFile(file)}
            onSymbol={onSymbol}
            onSliceSelection={(ctx) => void sliceFromSelection(ctx)}
          />
        ) : activeFile ? (
          <FullFileView
            file={activeFile}
            slice={slice}
            onAsk={ask}
            onSliceSelection={(ctx) => void sliceFromSelection(ctx)}
            onTrace={onTrace}
            onSymbol={onSymbol}
          />
        ) : (
          <div className="empty">
            <strong>从左侧选择一个片段或文件</strong>
            切片目录里有流程、文件和函数列表；点击任意一项就会在中间打开。
          </div>
        )}
      </div>

      <div className="row" style={{ marginTop: 18, gap: 8 }}>
        <button className="btn btn-sm" onClick={newQuestion}>
          <Plus size={13} /> 继续提问 / 新切片
        </button>
        <button className="btn btn-sm btn-ghost" onClick={() => {
          setStage("library");
          if (track) navigate(`/track/${track.track.id}/library`);
        }}>
          <BookOpen size={13} /> 切片库
        </button>
        <span className="spacer" />
        <span className="small muted">
          {segment ? `${segment.file}:${segment.startLine}–${segment.endLine}` : activeFile || ""}
        </span>
      </div>
    </div>
  );
}
