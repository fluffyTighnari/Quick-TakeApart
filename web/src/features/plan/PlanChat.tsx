import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Send, Sparkles } from "lucide-react";
import { useApp } from "../../core/store";
import { RichText } from "../../ui/RichText";

export function PlanChat() {
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const planChat = useApp((s) => s.planChat);
  const generateBind = useApp((s) => s.generateBind);
  const busy = useApp((s) => s.busy);
  const setStage = useApp((s) => s.setStage);
  const openCode = useApp((s) => s.openCode);
  const [message, setMessage] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const thread = track?.planThread;
  const messages = thread?.messages || [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, busy]);

  async function send() {
    const text = message.trim();
    if (!text || busy) return;
    setMessage("");
    try {
      await planChat(text);
    } catch {
      setMessage(text);
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-scroll" ref={scrollRef}>
        {!messages.length ? (
          <div className="chat-empty">
            <p><strong>这里只做一件事：把话变成计划。</strong></p>
            <p>轨道的用途和粒度已经确定，这里直接说下一步想读什么：</p>
            <p className="mono" style={{ color: "var(--teal-2)" }}>“先看 HTTP 入口，跳过 logging。”</p>
            <p>每轮要么改动计划，要么问一个澄清问题。对话记录会保存，但交付物是计划。</p>
          </div>
        ) : null}

        {messages.map((msg) => {
          const turn = (msg.turn || {}) as Record<string, unknown>;
          const notes = (turn.notes || []) as string[];
          const needs = (turn.needsGeneration || []) as {
            query: string; stepId: string; goal: string; after: string[];
            granularity: string; skippable: string;
            skeletonId?: string; nodeId?: string;
          }[];
          const rejected = (turn.rejected || []) as string[];
          return (
            <div className={`chat-msg ${msg.role}`} key={msg.id}>
              <div className="role">{msg.role === "user" ? "你" : "计划设计师"}</div>
              <div className="bubble">
                {msg.role === "assistant" ? (
                  <RichText
                    text={msg.content || "（无回复）"}
                    symbols={base?.symbols || {}}
                    files={new Set(base?.files || [])}
                    onSymbol={(sid) => {
                      const file = base?.symbols[sid]?.file;
                      if (file) void openCode(file, sid);
                      setStage("read");
                      if (track) navigate(`/track/${track.track.id}/read`);
                    }}
                    onLocation={(file) => {
                      void openCode(file);
                      setStage("read");
                      if (track) navigate(`/track/${track.track.id}/read`);
                    }}
                  />
                ) : (
                  msg.content
                )}
              </div>

              {notes.length ? (
                <div className="chat-notes">
                  {notes.map((note, i) => <div className="chat-note" key={i}>{note}</div>)}
                </div>
              ) : null}

              {needs.length ? (
                <div className="chat-needs">
                  <div className="small muted" style={{ marginBottom: 4 }}>这一步需要的切片还不存在：</div>
                  {needs.map((need, i) => (
                    <div className="chat-need-row" key={i}>
                      <code className="truncate" style={{ maxWidth: 180 }}>{need.query}</code>
                      <span className="spacer" />
                      <button
                        className="btn btn-xs btn-primary"
                        disabled={!!busy}
                        onClick={() => void generateBind({
                          query: need.query,
                          stepId: need.stepId,
                          goal: need.goal,
                          after: need.after,
                          granularity: need.granularity,
                          skippable: need.skippable,
                          skeletonId: need.skeletonId,
                          nodeId: need.nodeId,
                        })}
                      >
                        <Sparkles size={10} /> 生成并绑定
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}

              {rejected.length ? (
                <div className="small" style={{ color: "var(--rust)", marginTop: 5 }}>
                  拒绝：{rejected.join("；")}
                </div>
              ) : null}
            </div>
          );
        })}

        {busy ? <div className="loading" style={{ padding: "4px 2px" }}>正在把这句话映射成计划变更…</div> : null}
      </div>

      <div className="chat-composer">
        <div className="row">
          <textarea
            className="textarea"
            value={message}
            placeholder="说需求，不说感想：先看认证 / 加一步看写库 / 这部分太细了…"
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
          Enter 发送 · Shift+Enter 换行 · 对话与侧页问答记忆独立
        </div>
      </div>
    </div>
  );
}
