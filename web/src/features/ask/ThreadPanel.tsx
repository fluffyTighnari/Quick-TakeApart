import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, MessageSquare, Send, Sparkles, X } from "lucide-react";
import { useApp } from "../../core/store";
import { RichText } from "../../ui/RichText";

function shortName(sid: string) {
  return sid.split("::").pop() || sid;
}

export function ThreadPanel() {
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const slice = useApp((s) => s.activeSlice);
  const thread = useApp((s) => s.activeThread);
  const selection = useApp((s) => s.selection);
  const suggested = useApp((s) => s.suggestedSlices);
  const sendThreadMessage = useApp((s) => s.sendThreadMessage);
  const generateSlice = useApp((s) => s.generateSlice);
  const setSelection = useApp((s) => s.setSelection);
  const setStage = useApp((s) => s.setStage);
  const selectSymbol = useApp((s) => s.selectSymbol);
  const selectFile = useApp((s) => s.selectFile);
  const busy = useApp((s) => s.busy);
  const setReadMode = useApp((s) => s.setReadMode);
  const [message, setMessage] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const messages = thread?.messages || [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, busy]);

  if (!slice) {
    return <div className="dock-body"><div className="empty"><strong>没有打开切片</strong>侧页问答按切片隔离；先打开一条切片。</div></div>;
  }
  if (!thread) {
    return <div className="dock-body"><div className="loading">正在准备这条切片的问答线程…</div></div>;
  }

  async function send() {
    const text = message.trim();
    if (!text || busy) return;
    setMessage("");
    try {
      await sendThreadMessage(text, selection || undefined);
    } catch {
      setMessage(text);
    }
  }

  function openSymbol(sid: string) {
    void selectSymbol(sid);
    setReadMode("files");
    setStage("read");
  }
  function openLocation(file: string) {
    void selectFile(file);
    setReadMode("files");
    setStage("read");
  }

  return (
    <div className="chat-panel">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="row small muted" style={{ marginBottom: 10, gap: 6 }}>
          <MessageSquare size={12} />
          <span className="truncate">{slice.title}</span>
          <span className="spacer" />
          <span className="chip muted">按切片记忆</span>
        </div>

        {!messages.length ? (
          <div className="chat-empty">
            <p><strong>问这条切片的任何问题。</strong></p>
            <p>选中代码后点“提问”，会把文件与行范围一起带进来。回答里的符号和行号可以点击跳到现场。</p>
            <p>这条线程与计划对话完全独立，不会串味。</p>
          </div>
        ) : null}

        {messages.map((msg) => {
          const context = msg.context as { file?: string; startLine?: number; endLine?: number } | undefined;
          return (
            <div className={`thread-msg ${msg.role}`} key={msg.id}>
              <div className="thread-role">
                {msg.role === "user" ? "你" : "讲解"}
                {msg.role === "assistant" ? <span className="chip muted" style={{ fontSize: 9 }}>独立线程</span> : null}
              </div>
              {msg.role === "assistant" ? (
                <RichText
                  text={msg.content}
                  symbols={base?.symbols || {}}
                  files={new Set(base?.files || [])}
                  onSymbol={openSymbol}
                  onLocation={openLocation}
                />
              ) : (
                <div>{msg.content}</div>
              )}
              {context?.file ? (
                <div className="thread-context">
                  引用 · {context.file}:{context.startLine}–{context.endLine}
                </div>
              ) : null}
              {msg.citations?.length ? (
                <div className="citations">
                  {msg.citations.map((citation, i) => (
                    <button
                      className="chip"
                      key={i}
                      onClick={() => {
                        if (citation.kind === "symbol" && citation.symbolId) openSymbol(citation.symbolId);
                        else if (citation.file) openLocation(citation.file);
                      }}
                    >
                      {citation.kind === "symbol" ? shortName(citation.symbolId || "") : citation.label || citation.file}
                      <ArrowUpRight size={10} />
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}

        {busy ? <div className="loading" style={{ padding: "4px 2px" }}>正在读你选中的代码…</div> : null}

        {suggested.length ? (
          <div className="chat-needs">
            <div className="small muted" style={{ marginBottom: 4 }}>可以继续切开的问题：</div>
            {suggested.map((item, i) => (
              <div className="chat-need-row" key={i}>
                <span className="truncate" style={{ maxWidth: 190 }}>{item.title || item.query}</span>
                <span className="spacer" />
                <button
                  className="btn btn-xs btn-primary"
                  disabled={!!busy}
                  onClick={() => void generateSlice(item.query).then((created) => {
                    if (created && track) navigate(`/track/${track.track.id}/read/${created.id}`);
                  })}
                >
                  <Sparkles size={10} /> 生成切片
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div className="thread-composer">
        {selection ? (
          <div className="context-chip">
            <span className="grow">{selection.file}:{selection.startLine}–{selection.endLine}</span>
            <button title="移除引用" onClick={() => setSelection(null)}><X size={11} /></button>
          </div>
        ) : null}
        <div className="row">
          <textarea
            className="textarea"
            value={message}
            placeholder="问这条切片：这个函数为什么这样写？/ 这里失败会怎样？"
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button className="btn btn-primary" disabled={!message.trim() || !!busy} onClick={() => void send()}>
            <Send size={13} />
          </button>
        </div>
        <div className="small muted" style={{ marginTop: 5, fontSize: 10 }}>
          Enter 发送 · 选中代码会自动带上文件与行范围
        </div>
      </div>
    </div>
  );
}
