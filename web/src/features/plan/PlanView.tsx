import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowDown, ArrowRight, ArrowUp, CheckCircle2, Circle, Loader2, MessageSquare,
  Plus, RefreshCw, Route, Trash2, X,
} from "lucide-react";
import { useApp } from "../../core/store";
import { isImeEvent } from "../../core/keyboard";
import { trackPath } from "../../core/routes";
import { plainText } from "../../core/text";
import { useEscape } from "../../ui/useEscape";
import type { PlanItem } from "../../types";

type PendingNeed = {
  query: string;
  stepId: string;
  goal: string;
  after: string[];
  granularity: string;
  skippable: string;
  skeletonId?: string;
  nodeId?: string;
};

function pendingNeeds(thread: { messages: { role: string; turn?: Record<string, unknown> }[] } | null | undefined): PendingNeed[] {
  if (!thread) return [];
  const out: PendingNeed[] = [];
  const seen = new Set<string>();
  for (let i = thread.messages.length - 1; i >= 0; i--) {
    const message = thread.messages[i];
    if (message.role !== "assistant") continue;
    const needs = message.turn?.needsGeneration;
    if (!Array.isArray(needs)) continue;
    for (const need of needs as PendingNeed[]) {
      const key = need.stepId || need.query;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(need);
    }
  }
  return out;
}

function AddStepModal({ onClose }: { onClose: () => void }) {
  const generateSlice = useApp((s) => s.generateSlice);
  const applyPlan = useApp((s) => s.applyPlan);
  const track = useApp((s) => s.track);
  const busy = useApp((s) => s.busy);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  useEscape(onClose);

  async function submit() {
    if (!query.trim()) return;
    try {
      const slice = await generateSlice(query.trim(), {
        scope: { kind: "plan-step", label: query.trim() },
      });
      const plan = track?.plan;
      const items = (plan?.items || []).map((i) => ({ ...i }));
      const last = items[items.length - 1];
      items.push({
        id: `s${items.length + 1}-${Math.random().toString(36).slice(2, 5)}`,
        flowId: slice.id,
        goal: query.trim(),
        after: last ? [last.id] : [],
        // The track owns the granularity contract; a step does not re-ask.
        granularity: track?.track.depth || "结构",
        skippable: "",
      });
      await applyPlan(items, plan?.name, plan?.intent);
      if (track) navigate(trackPath(track.track.id, "read", slice.id));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}>
      <div className="palette dialog" style={{ padding: 18 }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="grow">
            <div className="eyebrow" style={{ marginBottom: 2 }}>手动加一步</div>
            <div className="panel-title">提一个问题，切出来直接入计划</div>
          </div>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="col">
          <div className="field">
            <label>这一步要读什么</label>
            <input className="input" autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="例如：追踪 WebSocket Server 的消息分发"
              onKeyDown={(e) => { if (e.key === "Enter" && !isImeEvent(e)) void submit(); }} />
          </div>
          <div className="small muted">
            目的和粒度沿用当前轨道「{track?.track.depth || "结构"}」，这里不再重复选择。
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn btn-primary" disabled={!!busy || !query.trim()} onClick={() => void submit()}>
              <SparklesIcon /> {busy ? "生成中…" : "生成并加入"}
            </button>
          </div>
          {error ? <div className="notice bad">{error}</div> : null}
        </div>
      </div>
    </div>
  );
}

function SparklesIcon() {
  return <span style={{ fontSize: 12 }}>✦</span>;
}

export function PlanView() {
  const navigate = useNavigate();
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const selectSlice = useApp((s) => s.selectSlice);
  const setStage = useApp((s) => s.setStage);
  const setContextTab = useApp((s) => s.setContextTab);
  const revealDock = useApp((s) => s.revealDock);
  const generateBind = useApp((s) => s.generateBind);
  const applyPlan = useApp((s) => s.applyPlan);
  const planChat = useApp((s) => s.planChat);
  const busy = useApp((s) => s.busy);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    setContextTab("thread");
  }, [setContextTab]);

  if (!track) return null;
  const plan = track.plan;
  const items = plan?.items || [];
  const order = plan?.order?.length ? plan.order : items.map((i) => i.id);
  const byId = new Map(items.map((i) => [i.id, i]));
  const ordered = order.map((id) => byId.get(id)).filter(Boolean) as PlanItem[];
  const slices = plan?.slices || {};
  const ready = ordered.filter((item) => slices[item.flowId]).length;
  const pending = pendingNeeds(track.planThread).filter((need) => !byId.has(need.stepId));
  const totalSteps = ordered.length + pending.length;
  const pct = totalSteps ? Math.round((ready / totalSteps) * 100) : 0;

  async function openStep(item: PlanItem) {
    const slice = slices[item.flowId] || track?.slices.find((s) => s.id === item.flowId);
    if (slice) {
      await selectSlice(slice.id);
      setStage("read");
      if (track) navigate(trackPath(track.track.id, "read", slice.id));
    } else {
      await generateForStep(item);
    }
  }

  async function generateForStep(item: PlanItem) {
    try {
      const created = await generateBind({
        query: item.goal || plan?.name || "这一步要读的代码",
        stepId: item.id,
        goal: item.goal,
        after: item.after,
        granularity: item.granularity,
        skippable: item.skippable,
      });
      if (track) navigate(trackPath(track.track.id, "read", created.id));
    } catch {
      /* the status bar shows the failure */
    }
  }

  async function removeStep(item: PlanItem) {
    if (!confirm(`删除步骤「${item.goal || item.id}」？切片本身不会被删除。`)) return;
    const next = ordered.filter((i) => i.id !== item.id).map((i) => ({
      id: i.id, flowId: i.flowId, goal: i.goal, after: i.after.filter((a) => a !== item.id),
      skippable: i.skippable, granularity: i.granularity,
    }));
    try {
      await applyPlan(next, plan?.name, plan?.intent);
    } catch {
      /* the status bar shows the failure */
    }
  }

  async function moveStep(item: PlanItem, direction: -1 | 1) {
    const index = ordered.findIndex((i) => i.id === item.id);
    const target = index + direction;
    if (target < 0 || target >= ordered.length) return;
    const next = [...ordered];
    [next[index], next[target]] = [next[target], next[index]];
    try {
      await applyPlan(next.map((i) => ({
        id: i.id, flowId: i.flowId, goal: i.goal, after: i.after,
        skippable: i.skippable, granularity: i.granularity,
      })), plan?.name, plan?.intent);
    } catch {
      /* the status bar shows the failure */
    }
  }

  async function startPlan() {
    const message = [
      "为这个项目制定学习计划。",
      `目标：${track?.track.intent || "整体了解"}`,
      `粒度：${track?.track.depth || "结构"}`,
      "先给出一条可执行的步骤路线，每一步都要绑定或请求一条切片。",
    ].join("\n");
    try {
      await planChat(message);
      revealDock("thread");
    } catch {
      /* the store surfaces the error in the status bar */
    }
  }

  return (
    <div className="stage">
      <div className="stage-head reveal">
        <div className="grow">
          <div className="eyebrow">Stage 02 · Route</div>
          <h1 className="stage-title">{plan?.name || track.track.name}</h1>
          <p className="stage-sub">
            {plan?.intent || track.track.intent || "还没有写用途。计划对话在右侧，计划本身是主画布。"}
          </p>
          <div className="plan-meta">
            <span className="chip teal">{totalSteps} 步</span>
            {pending.length ? <span className="chip amber">{pending.length} 待生成</span> : null}
            <span className="chip">{ready} 已绑定切片</span>
            <span className="chip amber">粒度 · {track.track.depth || "未指定"}</span>
            {plan?.health?.dangling?.length ? <span className="chip rust">{plan.health.dangling.length} 悬空</span> : null}
            {plan?.health?.rotted?.length ? <span className="chip amber">{plan.health.rotted.length} 失效</span> : null}
          </div>
        </div>
        <div className="stage-actions">
          <button className="btn btn-sm" onClick={() => revealDock("thread")}>
            <MessageSquare size={13} /> 计划对话
          </button>
          <button className="btn btn-sm" onClick={() => setAddOpen(true)}>
            <Plus size={13} /> 加一步
          </button>
          {plan ? (
            <button className="btn btn-sm btn-ghost" onClick={() => void applyPlan(items, plan.name, plan.intent).catch(() => undefined)}>
              <RefreshCw size={13} /> 保存
            </button>
          ) : null}
        </div>
      </div>

      {!plan && !pending.length ? (
        <div className="reveal reveal-1">
          <div className="panel" style={{ maxWidth: 760 }}>
            <div className="panel-body">
              <div className="panel-title" style={{ marginBottom: 6 }}>还没有计划</div>
              <p className="small muted" style={{ marginBottom: 12 }}>
                目的和粒度沿用轨道设置，不在这里再问一遍。AI 会给出步骤路线；
                没有合适切片时它会明确请求生成，而不是编一个引用。
              </p>
              <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
                <div className="row wrap" style={{ gap: 6 }}>
                  <span className="chip teal">目的 · {track?.track.intent || "整体了解"}</span>
                  <span className="chip amber">粒度 · {track?.track.depth || "结构"}</span>
                </div>
                <div className="small muted" style={{ marginTop: 8 }}>
                  需要改目的或粒度时，在轨道层修改一次，计划和后续切片都会继承。
                </div>
              </div>
              <button className="btn btn-primary" disabled={!!busy} onClick={() => void startPlan()}>
                <Route size={14} /> 用当前轨道排计划
              </button>
            </div>
          </div>
          <div className="empty" style={{ marginTop: 14, maxWidth: 760 }}>
            <strong>也可以手动开始</strong>
            点右上角“加一步”，先提一个问题，生成切片后直接绑定进计划。
          </div>
        </div>
      ) : (
        <div className="plan-layout reveal reveal-1">
          <div className="plan-head-card panel-flat">
            <div className="row">
              <div className="grow">
                <div className="plan-title">{plan?.name || "计划草稿"}</div>
                <div className="plan-intent">{plan?.intent || track.track.intent || "未写用途"}</div>
              </div>
              <div className="chip teal">{pct}% 就绪</div>
            </div>
            <div className="plan-progress">
              <div className="progress-track"><div className="progress-fill" style={{ width: `${pct}%` }} /></div>
              <span>{ready}/{totalSteps}</span>
            </div>
            {pending.length ? (
              <div className="small muted" style={{ marginTop: 7 }}>
                这 {pending.length} 步是 AI 提议的路线，还没有绑定切片；生成后才会写入计划。
              </div>
            ) : null}
          </div>

          <div className="plan-route">
            {ordered.map((item, index) => {
              const slice = slices[item.flowId] || track.slices.find((s) => s.id === item.flowId);
              const dangling = plan?.health?.dangling?.includes(item.id);
              const rotted = plan?.health?.rotted?.includes(item.id);
              const current = !slice && index === ordered.findIndex((i) => !slices[i.flowId]);
              const deps = item.after
                .map((dep) => byId.get(dep))
                .filter(Boolean)
                .map((dep) => {
                  const pos = ordered.findIndex((i) => i.id === dep!.id);
                  return pos >= 0 ? `第 ${pos + 1} 步` : dep!.id;
                });
              return (
                <div
                  key={item.id}
                  className={`plan-step${current ? " current" : ""}${dangling ? " broken" : ""}`}
                  onClick={() => { if (slice) void openStep(item); }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      void openStep(item);
                    }
                  }}
                >
                  <div className="step-num">{String(index + 1).padStart(2, "0")}</div>
                  <div className="step-top">
                    <div className="step-goal">{item.goal || slice?.title || "（未写目标）"}</div>
                    <div className="step-actions">
                      <button className="btn btn-xs btn-ghost" title="上移" onClick={(e) => { e.stopPropagation(); void moveStep(item, -1); }}>
                        <ArrowUp size={11} />
                      </button>
                      <button className="btn btn-xs btn-ghost" title="下移" onClick={(e) => { e.stopPropagation(); void moveStep(item, 1); }}>
                        <ArrowDown size={11} />
                      </button>
                      <button className="btn btn-xs btn-ghost" title="删除" onClick={(e) => { e.stopPropagation(); void removeStep(item); }}>
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </div>

                  <div className="step-slice">
                    {slice ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                    <span>{slice ? slice.title : "还没有绑定切片"}</span>
                    {slice ? (
                      <span className="chip muted">{slice.strategies.join(" · ") || "slice"}</span>
                    ) : (
                      <span className="chip amber">待生成</span>
                    )}
                    {rotted ? <span className="chip rust">已过期</span> : null}
                    {dangling ? <span className="chip rust">引用丢失</span> : null}
                    {slice?.quality && !slice.quality.ok ? (
                      <span className="chip rust" title="片段过短或视图缺少分组，建议在切片详情里重新生成">
                        片段异常
                      </span>
                    ) : null}
                  </div>

                  {slice?.summary ? <div className="step-sub">{plainText(slice.summary, 180)}</div> : null}

                  <div className="step-foot">
                    {deps.length ? (
                      <div className="step-deps">
                        {deps.map((dep, i) => <span className="chip muted" key={i}>依赖 {dep}</span>)}
                      </div>
                    ) : <span className="chip muted">起点</span>}
                    {item.granularity ? <span className="chip">{item.granularity}</span> : null}
                    {item.skippable ? <span className="chip amber">可跳过 · {item.skippable}</span> : null}
                    <span className="spacer" />
                    {slice ? (
                      <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); void openStep(item); }}>
                        开始阅读 <ArrowRight size={12} />
                      </button>
                    ) : (
                      <button className="btn btn-sm btn-primary" disabled={!!busy} onClick={(e) => { e.stopPropagation(); void generateForStep(item); }}>
                        <Loader2 size={12} className={busy ? "spin" : ""} /> 生成切片
                      </button>
                    )}
                  </div>
                </div>
              );
            })}

            {pending.map((need, index) => (
              <div
                key={`pending-${need.stepId || index}`}
                className="plan-step pending"
              >
                <div className="step-num">{String(ordered.length + index + 1).padStart(2, "0")}</div>
                <div className="step-top">
                  <div className="step-goal">{need.goal || need.query}</div>
                  <span className="chip amber">待生成</span>
                </div>
                <div className="step-sub">{need.query}</div>
                <div className="step-foot">
                  <span className="chip muted">{need.after?.length ? "依赖前序步骤" : "起点"}</span>
                  {need.granularity ? <span className="chip">{need.granularity}</span> : null}
                  {need.skippable ? <span className="chip amber">可跳过 · {need.skippable}</span> : null}
                  <span className="spacer" />
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={!!busy}
                    onClick={() => void generateBind({
                      query: need.query,
                      stepId: need.stepId,
                      goal: need.goal,
                      after: need.after || [],
                      granularity: need.granularity,
                      skippable: need.skippable,
                      skeletonId: need.skeletonId,
                      nodeId: need.nodeId,
                    }).catch(() => undefined)}
                  >
                    <Loader2 size={12} className={busy ? "spin" : ""} /> 生成并绑定
                  </button>
                </div>
              </div>
            ))}

            {!totalSteps ? (
              <div className="empty">
                <strong>计划里还没有步骤</strong>
                用右侧对话加一步，或者点右上角“加一步”。
              </div>
            ) : null}
          </div>

          <div className="row wrap" style={{ marginTop: 16, gap: 8 }}>
            <button className="btn btn-sm" onClick={() => setAddOpen(true)}><Plus size={13} /> 加一步</button>
            <button className="btn btn-sm btn-ghost" onClick={() => revealDock("thread")}>
              <MessageSquare size={13} /> 在对话里调整
            </button>
            <span className="spacer" />
            <span className="small muted">切片可被多条计划复用；删除计划不会删除切片。</span>
          </div>
        </div>
      )}

      {addOpen ? <AddStepModal onClose={() => setAddOpen(false)} /> : null}
    </div>
  );
}
