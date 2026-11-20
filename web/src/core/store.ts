import { create } from "zustand";
import { api, ApiError } from "./api";
import {
  applyCodeTheme, applyReadingScale, initialCodeTheme, initialReadingScale,
  type CodeTheme, type ReadingScale,
} from "./prefs";
import type {
  BasePayload, SelectionContext, Skeleton, SkeletonNode, Slice, Stage, Thread,
  TraceResult, TrackData, TrackSummary, Workspace,
} from "../types";

interface AppState {
  booted: boolean;
  booting: boolean;
  backendStale: string | null;
  base: BasePayload | null;
  workspace: Workspace | null;
  track: TrackData | null;
  activeTrackId: string | null;
  activeStage: Stage;
  activeSkeletonId: string | null;
  activeSkeletonNodeId: string | null;
  activeSliceId: string | null;
  activeSlice: Slice | null;
  activeSegmentId: string | null;
  activeThread: Thread | null;
  suggestedSlices: { query: string; title: string; reason: string }[];
  activeFile: string | null;
  activeLine: number | null;
  activeSymbol: string | null;
  readMode: "flow" | "files" | "functions";
  selection: SelectionContext | null;
  sourceCache: Record<string, string>;
  traceResult: TraceResult | null;
  traceRequest: { file: string; line: number; char: number } | null;
  traceOpen: boolean;
  traceLoading: boolean;
  commandOpen: boolean;
  railOpen: boolean;
  dockOpen: boolean;
  focusMode: boolean;
  contextTab: "details" | "thread" | "diagrams";
  readingScale: ReadingScale;
  codeTheme: CodeTheme;
  busy: string | null;
  error: string | null;
  notice: string | null;

  boot: () => Promise<void>;
  openProject: (root: string) => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  selectTrack: (id: string) => Promise<void>;
  createTrack: (name: string, intent?: string, depth?: string) => Promise<TrackData>;
  updateActiveTrack: (fields: { name?: string; intent?: string; depth?: string }) => Promise<void>;
  deleteActiveTrack: () => Promise<void>;
  setStage: (stage: Stage) => void;
  selectSkeleton: (id: string | null) => void;
  selectSkeletonNode: (id: string | null) => void;
  generateSkeleton: (focus?: string) => Promise<Skeleton>;
  explainSkeletonNode: (skeletonId: string, nodeId: string) => Promise<SkeletonNode>;
  importSkeletonMain: (skeletonId: string) => Promise<void>;
  importSkeletonNode: (skeletonId: string, nodeId: string) => Promise<void>;
  selectSlice: (id: string | null) => Promise<Slice | null>;
  openSlice: (slice: Slice) => Promise<string | null>;
  selectSegment: (id: string | null) => void;
  selectSliceFile: (file: string, line?: number | null) => Promise<void>;
  selectFile: (file: string | null, line?: number | null) => Promise<void>;
  selectSymbol: (id: string | null) => Promise<void>;
  openCode: (file: string, symbolId?: string | null) => Promise<void>;
  setReadMode: (mode: "flow" | "files" | "functions") => void;
  setSelection: (selection: SelectionContext | null) => void;
  sourceFor: (file: string) => Promise<string>;
  generateSlice: (query: string, opts?: {
    strategies?: string[];
    scope?: Record<string, unknown>;
  }) => Promise<Slice>;
  regenerateSlice: (id: string) => Promise<void>;
  planChat: (message: string) => Promise<void>;
  applyPlan: (items: unknown[], name?: string, intent?: string) => Promise<void>;
  generateBind: (request: Record<string, unknown>) => Promise<Slice>;
  sendThreadMessage: (message: string, context?: SelectionContext) => Promise<void>;
  trace: (file: string, line: number, char: number, kind: string) => Promise<void>;
  setTraceOpen: (open: boolean) => void;
  setCommandOpen: (open: boolean) => void;
  toggleRail: () => void;
  toggleDock: () => void;
  toggleFocusMode: () => void;
  setContextTab: (tab: "details" | "thread" | "diagrams") => void;
  revealDock: (tab: "details" | "thread" | "diagrams") => void;
  setReadingScale: (scale: ReadingScale) => void;
  cycleReadingScale: () => void;
  setCodeTheme: (theme: CodeTheme) => void;
  toggleCodeTheme: () => void;
  setError: (error: string | null) => void;
  setNotice: (notice: string | null) => void;
  clearActiveSlice: () => void;
}

function summaryFromTrack(data: TrackData): TrackSummary {
  return {
    ...data.track,
    plan: data.plan
      ? {
          id: data.plan.id,
          name: data.plan.name,
          intent: data.plan.intent,
          steps: data.plan.items.length,
          health: data.plan.health,
        }
      : null,
    sliceCount: data.slices.length,
    threadCount: data.threads.length,
  };
}

function mergeWorkspace(workspace: Workspace | null, data: TrackData): Workspace | null {
  if (!workspace) return workspace;
  const tracks = workspace.tracks.map((t) =>
    t.id === data.track.id ? summaryFromTrack(data) : t,
  );
  if (!tracks.some((t) => t.id === data.track.id)) tracks.unshift(summaryFromTrack(data));
  // The library and home page read workspace.slices, not track.slices. Keep the
  // two views in sync whenever a track mutation returns fresh slice records.
  const slices = new Map(workspace.slices.map((slice) => [slice.id, slice]));
  for (const slice of data.slices) slices.set(slice.id, slice);
  return { ...workspace, tracks, slices: [...slices.values()] };
}

export const useApp = create<AppState>((set, get) => ({
  booted: false,
  booting: false,
  backendStale: null,
  base: null,
  workspace: null,
  track: null,
  activeTrackId: null,
  activeStage: "architecture",
  activeSkeletonId: null,
  activeSkeletonNodeId: null,
  activeSliceId: null,
  activeSlice: null,
  activeSegmentId: null,
  activeThread: null,
  suggestedSlices: [],
  activeFile: null,
  activeLine: null,
  activeSymbol: null,
  readMode: "files",
  selection: null,
  sourceCache: {},
  traceResult: null,
  traceRequest: null,
  traceOpen: false,
  traceLoading: false,
  commandOpen: false,
  railOpen: true,
  dockOpen: true,
  focusMode: false,
  contextTab: "details",
  readingScale: initialReadingScale(),
  codeTheme: initialCodeTheme(),
  busy: null,
  error: null,
  notice: null,

  boot: async () => {
    if (get().booting) return;
    set({ booting: true, error: null, backendStale: null });
    try {
      // Fail loudly when the page is talking to an old server process. The new
      // frontend cannot work against an old API; without this check the user sees
      // a confusing mix of 404/501 responses.
      try {
        const health = await api.health();
        const required = ["workspace", "browse", "pick-folder", "slices", "trace"];
        const missing = required.filter((name) => !health.features.includes(name));
        if (missing.length) {
          throw new ApiError(`后端缺少功能：${missing.join("、")}`, 0);
        }
      } catch (err) {
        const isOld = err instanceof ApiError
          && (err.status === 404 || err.message.includes("后端缺少功能"));
        set({
          booted: true,
          booting: false,
          backendStale: isOld
            ? `当前页面连接的后端进程是旧版本：${window.location.origin} 没有新的 workspace/browse API。`
            : `无法连接当前后端：${err instanceof Error ? err.message : String(err)}`,
        });
        return;
      }

      let workspace: Workspace | null = null;
      try {
        workspace = await api.workspace();
      } catch (err) {
        if (!(err instanceof ApiError) || err.status !== 503) throw err;
      }
      if (!workspace) {
        set({ booted: true, booting: false, workspace: null, base: null, track: null });
        return;
      }
      const base = await api.base();
      const first = workspace.tracks[0];
      set({
        booted: true,
        booting: false,
        base,
        workspace,
        activeTrackId: first?.id || null,
        activeStage: "architecture",
      });
      if (first) {
        const data = await api.track(first.id);
        set({
          track: data,
          workspace: mergeWorkspace(get().workspace, data),
          activeTrackId: data.track.id,
          activeSkeletonId: data.skeletons[0]?.id || null,
          activeSkeletonNodeId: null,
        });
      }
    } catch (err) {
      set({
        booted: true,
        booting: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },

  openProject: async (root) => {
    set({ busy: "正在索引项目…", error: null, notice: null });
    try {
      await api.open(root);
      // A different project has different track/slice ids. Keeping the old hash
      // would send the new workspace to a route that no longer exists.
      window.location.hash = "#/";
      set({
        base: await api.base(),
        booted: false,
        workspace: null,
        track: null,
        activeTrackId: null,
        activeStage: "architecture",
        activeSkeletonId: null,
        activeSkeletonNodeId: null,
        activeSliceId: null,
        activeSlice: null,
        activeSegmentId: null,
        activeThread: null,
        suggestedSlices: [],
        activeFile: null,
        activeLine: null,
        activeSymbol: null,
        selection: null,
        sourceCache: {},
        traceResult: null,
        traceRequest: null,
        traceOpen: false,
        traceLoading: false,
        contextTab: "details",
        focusMode: false,
        backendStale: null,
      });
      await get().boot();
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  refreshWorkspace: async () => {
    try {
      const workspace = await api.workspace();
      set({ workspace });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  selectTrack: async (id) => {
    if (!id) return;
    set({
      busy: "正在打开轨道…",
      error: null,
      suggestedSlices: [],
      selection: null,
      traceResult: null,
      traceRequest: null,
      traceOpen: false,
      traceLoading: false,
    });
    try {
      const data = await api.track(id);
      const firstSlice = data.slices[0];
      set({
        track: data,
        workspace: mergeWorkspace(get().workspace, data),
        activeTrackId: data.track.id,
        activeSkeletonId: data.skeletons[0]?.id || null,
        activeSkeletonNodeId: null,
        activeSliceId: firstSlice?.id || null,
        activeSlice: null,
        activeSegmentId: null,
        activeThread: null,
        activeFile: firstSlice?.segments?.[0]?.file || null,
        activeLine: null,
        activeSymbol: null,
        readMode: firstSlice ? "flow" : "files",
        contextTab: "details",
      });
      if (firstSlice) {
        const loaded = await api.slice(firstSlice.id).catch((err) => {
          set({ error: err instanceof Error ? err.message : String(err) });
          return null;
        });
        if (loaded) {
          set({
            activeSlice: loaded.slice,
            activeSegmentId: loaded.slice.segments[0]?.id || null,
            activeFile: loaded.slice.segments[0]?.file || null,
            readMode: "flow",
          });
          let thread = loaded.thread ||
            data.threads.find((t) => t.sliceId === loaded.slice.id) || null;
          if (!thread) {
            try {
              const created = await api.createThread({
                scope: "slice",
                trackId: data.track.id,
                sliceId: loaded.slice.id,
                title: loaded.slice.title,
              });
              thread = created.thread;
            } catch (err) {
              set({ error: err instanceof Error ? err.message : String(err) });
            }
          }
          set({ activeThread: thread });
        }
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  createTrack: async (name, intent = "", depth = "") => {
    set({ busy: "正在创建轨道…", error: null });
    try {
      const res = await api.createTrack({ name, intent, depth });
      const workspace = get().workspace;
      if (workspace) set({ workspace: mergeWorkspace(workspace, res.trackRecord) });
      set({
        track: res.trackRecord,
        activeTrackId: res.track.id,
        activeStage: "architecture",
        activeSkeletonId: null,
        activeSkeletonNodeId: null,
        activeSliceId: null,
        activeSlice: null,
        activeSegmentId: null,
        activeThread: null,
        suggestedSlices: [],
        activeFile: null,
        activeLine: null,
        activeSymbol: null,
        selection: null,
        traceResult: null,
        traceRequest: null,
        traceOpen: false,
        traceLoading: false,
        contextTab: "details",
      });
      return res.trackRecord;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  updateActiveTrack: async (fields) => {
    const track = get().track;
    if (!track) return;
    try {
      const res = await api.updateTrack({ id: track.track.id, ...fields });
      const next: TrackData = { ...track, track: res.track };
      set({
        track: next,
        workspace: mergeWorkspace(get().workspace, next),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    }
  },

  deleteActiveTrack: async () => {
    const track = get().track;
    if (!track) return;
    set({ busy: "正在删除轨道…", error: null });
    try {
      await api.deleteTrack(track.track.id);
      const workspace = await api.workspace();
      const next = workspace.tracks.find((t) => t.id !== track.track.id);
      set({ workspace, track: null, activeTrackId: null });
      if (next) {
        await get().selectTrack(next.id);
      } else {
        set({
          workspace: { ...workspace, tracks: [] },
          activeSkeletonId: null,
          activeSkeletonNodeId: null,
          activeSliceId: null,
          activeSlice: null,
          activeSegmentId: null,
          activeThread: null,
          suggestedSlices: [],
          activeFile: null,
          activeLine: null,
          activeSymbol: null,
          selection: null,
          traceResult: null,
          traceRequest: null,
          traceOpen: false,
          traceLoading: false,
          readMode: "files",
          contextTab: "details",
        });
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  setStage: (stage) => {
    set({ activeStage: stage });
    const track = get().track;
    if (track) {
      api.updateTrack({ id: track.track.id, stage }).catch(() => undefined);
    }
  },


  selectSkeleton: (id) => {
    set({ activeSkeletonId: id, activeSkeletonNodeId: null, contextTab: "details" });
  },

  selectSkeletonNode: (id) => {
    set({ activeSkeletonNodeId: id, contextTab: "details" });
  },

  generateSkeleton: async (focus = "") => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在生成逻辑骨架…（模型可能需要 20–60 秒）", error: null });
    try {
      const res = await api.generateSkeleton({ trackId: track.track.id, focus });
      const next: TrackData = {
        ...track,
        skeletons: [res.skeleton, ...track.skeletons.filter((s) => s.id !== res.skeleton.id)],
      };
      set({
        track: next,
        workspace: mergeWorkspace(get().workspace, next),
        activeSkeletonId: res.skeleton.id,
        contextTab: "details",
        notice: res.source === "model" ? "骨架已生成" : "模型不可用，已生成本地推测骨架",
      });
      return res.skeleton;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  explainSkeletonNode: async (skeletonId, nodeId) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在生成节点讲解…", error: null });
    try {
      const res = await api.explainSkeletonNode({ skeletonId, nodeId });
      const next: TrackData = {
        ...track,
        skeletons: track.skeletons.map((s) => (s.id === res.skeleton.id ? res.skeleton : s)),
      };
      set({
        track: next,
        workspace: mergeWorkspace(get().workspace, next),
        activeSkeletonId: res.skeleton.id,
        contextTab: "details",
      });
      return res.node;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  importSkeletonMain: async (skeletonId) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在把骨架导入计划…", error: null });
    try {
      const res = await api.importSkeletonMain({ trackId: track.track.id, skeletonId });
      set({
        track: res.trackRecord,
        workspace: mergeWorkspace(get().workspace, res.trackRecord),
        notice: "骨架已导入计划；生成切片后才会写入计划",
        contextTab: "thread",
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  importSkeletonNode: async (skeletonId, nodeId) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在把节点加入计划…", error: null });
    try {
      const res = await api.importSkeletonNode({ trackId: track.track.id, skeletonId, nodeId });
      set({
        track: res.trackRecord,
        workspace: mergeWorkspace(get().workspace, res.trackRecord),
        notice: "节点已加入计划，等待生成切片",
        contextTab: "thread",
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  selectSlice: async (id) => {
    if (!id) {
      set({
        activeSliceId: null,
        activeSlice: null,
        activeSegmentId: null,
        activeThread: null,
      });
      return null;
    }
    const first = get().activeSlice;
    set({
      busy: "正在打开切片…",
      error: null,
      suggestedSlices: [],
      selection: null,
      traceResult: null,
      traceRequest: null,
      traceOpen: false,
      traceLoading: false,
      // Do not keep showing the previous slice while the requested one loads.
      activeSlice: first?.id === id ? first : null,
    });
    try {
      const res = await api.slice(id);
      const segment = res.slice.segments[0] || null;
      set({
        activeSliceId: res.slice.id,
        activeSlice: res.slice,
        suggestedSlices: [],
        activeThread: null,
        activeSegmentId: segment?.id || null,
        activeFile: segment?.file || null,
        activeLine: null,
        activeSymbol: null,
        readMode: "flow",
        selection: null,
        contextTab: "details",
      });
      const track = get().track;
      let thread = res.thread ||
        track?.threads.find((t) => t.sliceId === id) || null;
      if (!thread) {
        try {
          const created = await api.createThread({
            scope: "slice",
            trackId: track?.track.id,
            sliceId: id,
            title: res.slice.title,
          });
          thread = created.thread;
        } catch (err) {
          set({ error: err instanceof Error ? err.message : String(err) });
        }
      }
      set({ activeThread: thread, busy: null });
      return res.slice;
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : String(err),
        busy: null,
        activeSliceId: null,
        activeSlice: null,
        activeSegmentId: null,
        activeThread: null,
      });
      return null;
    }
  },

  openSlice: async (slice) => {
    const workspace = get().workspace;
    const knownTrack = slice.trackId
      && workspace?.tracks.some((item) => item.id === slice.trackId)
      ? slice.trackId
      : null;
    const target = knownTrack || get().activeTrackId;
    try {
      if (target && target !== get().activeTrackId) {
        await get().selectTrack(target);
      }
      const loaded = await get().selectSlice(slice.id);
      return loaded ? get().activeTrackId : null;
    } catch {
      return null;
    }
  },

  selectSegment: (id) => {
    const slice = get().activeSlice;
    const segment = slice?.segments.find((s) => s.id === id) || null;
    set({
      activeSegmentId: id,
      activeFile: segment?.file || get().activeFile,
      activeLine: segment?.startLine ?? null,
      activeSymbol: segment?.symbolId || null,
      contextTab: "details",
    });
    if (segment) {
      void get().sourceFor(segment.file);
      // Keep the code in view when the user picks a segment from the rail.
      // `nearest` leaves the page alone when the card is already visible.
      requestAnimationFrame(() => {
        document.querySelector(".seg-card")?.scrollIntoView({
          block: "nearest",
          behavior: "smooth",
        });
      });
    }
  },

  selectSliceFile: async (file, line = null) => {
    set({
      activeSegmentId: null,
      activeFile: file,
      activeLine: line,
      activeSymbol: null,
      readMode: "files",
    });
    try {
      await get().sourceFor(file);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  selectFile: async (file, line = null) => {
    if (!file) {
      set({
        activeFile: null,
        activeLine: null,
        activeSymbol: null,
        activeSegmentId: null,
      });
      return;
    }
    set({
      activeFile: file,
      activeLine: line,
      activeSymbol: null,
      activeSegmentId: null,
      readMode: "files",
    });
    try {
      await get().sourceFor(file);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  selectSymbol: async (id) => {
    if (!id) {
      set({ activeSymbol: null });
      return;
    }
    const base = get().base;
    const sym = base?.symbols[id];
    if (!sym) return;
    set({
      activeSymbol: id,
      activeFile: sym.file,
      activeLine: sym.line,
      // A symbol jump must leave segment mode, otherwise the old segment card
      // keeps rendering and the app looks like nothing happened.
      activeSegmentId: null,
      readMode: "files",
      selection: null,
    });
    try {
      await get().sourceFor(sym.file);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  openCode: async (file, symbolId) => {
    const sym = symbolId ? get().base?.symbols[symbolId] : null;
    set({
      activeSliceId: null,
      activeSlice: null,
      activeThread: null,
      suggestedSlices: [],
      activeFile: file,
      activeLine: sym?.line ?? null,
      activeSymbol: symbolId || null,
      activeSegmentId: null,
      readMode: "files",
      selection: null,
      contextTab: "details",
      traceResult: null,
      traceRequest: null,
      traceOpen: false,
      traceLoading: false,
    });
    try {
      await get().sourceFor(file);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  setReadMode: (mode) => set({ readMode: mode }),

  setSelection: (selection) => set({ selection }),

  sourceFor: async (file) => {
    const cache = get().sourceCache;
    if (cache[file] !== undefined) return cache[file];
    const res = await api.source(file);
    set({ sourceCache: { ...get().sourceCache, [file]: res.text } });
    return res.text;
  },

  generateSlice: async (query, opts = {}) => {
    const track = get().track;
    set({ busy: "正在生成切片…（模型可能需要 30–90 秒）", error: null });
    try {
      const res = await api.generateSlice({
        trackId: track?.track.id,
        query,
        strategies: opts.strategies,
        scope: opts.scope,
      });
      const current = get().track;
      if (current) {
        const next: TrackData = {
          ...current,
          slices: [res.slice, ...current.slices.filter((s) => s.id !== res.slice.id)],
          threads: [res.thread, ...current.threads.filter((t) => t.id !== res.thread.id)],
        };
        set({ track: next, workspace: mergeWorkspace(get().workspace, next) });
      }
      set({
        activeSliceId: res.slice.id,
        activeSlice: res.slice,
        activeThread: res.thread,
        activeSegmentId: res.slice.segments[0]?.id || null,
        activeFile: res.slice.segments[0]?.file || null,
        activeLine: null,
        activeSymbol: null,
        readMode: "flow",
        contextTab: "details",
      });
      return res.slice;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  regenerateSlice: async (id) => {
    const track = get().track;
    set({ busy: "正在重新生成切片…（超时会保留旧内容）", error: null });
    try {
      const res = await api.regenerateSlice(id);
      let next = track;
      if (track) {
        next = await api.track(track.track.id);
      }
      set({
        track: next,
        workspace: next ? mergeWorkspace(get().workspace, next) : get().workspace,
        activeSliceId: id,
        activeSlice: res.slice,
        activeThread: res.thread,
        activeSegmentId: res.slice.segments[0]?.id || null,
        activeFile: res.slice.segments[0]?.file || null,
        activeLine: null,
        activeSymbol: null,
        readMode: "flow",
        notice: `已重新生成「${res.slice.title}」`,
        contextTab: "details",
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  planChat: async (message) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在修改计划…", error: null });
    try {
      const res = await api.planChat({ trackId: track.track.id, message });
      const next = res.trackRecord;
      set({
        track: next,
        workspace: mergeWorkspace(get().workspace, next),
        contextTab: "thread",
        notice: res.notes?.length ? res.notes.join("；") : res.reply,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  applyPlan: async (items, name, intent) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在保存计划…", error: null });
    try {
      const res = await api.applyPlan({
        trackId: track.track.id, items, name, intent,
      });
      set({
        track: res.trackRecord,
        workspace: mergeWorkspace(get().workspace, res.trackRecord),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  generateBind: async (request) => {
    const track = get().track;
    if (!track) throw new Error("no track");
    set({ busy: "正在生成并绑定切片…（模型可能需要 30–90 秒）", error: null });
    try {
      const res = await api.generateBind({ trackId: track.track.id, request });
      set({
        track: res.trackRecord,
        workspace: mergeWorkspace(get().workspace, res.trackRecord),
        activeSlice: res.slice,
        activeSliceId: res.slice.id,
        activeThread: res.thread,
        activeSegmentId: res.slice.segments[0]?.id || null,
        activeFile: res.slice.segments[0]?.file || null,
        activeLine: null,
        activeSymbol: null,
        readMode: "flow",
        notice: `已生成并绑定「${res.slice.title}」`,
        contextTab: "details",
      });
      return res.slice;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  sendThreadMessage: async (message, context) => {
    const thread = get().activeThread;
    if (!thread) throw new Error("no thread");
    set({ busy: "正在回答…", error: null });
    try {
      const res = await api.threadMessage({
        threadId: thread.id, message, context,
      });
      const current = get().track;
      if (current) {
        const next: TrackData = {
          ...current,
          threads: current.threads.map((t) => (t.id === res.thread.id ? res.thread : t)),
        };
        set({ track: next, workspace: mergeWorkspace(get().workspace, next) });
      }
      set({
        activeThread: res.thread,
        suggestedSlices: res.suggestedSlices || [],
        selection: null,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
      throw err;
    } finally {
      set({ busy: null });
    }
  },

  trace: async (file, line, char, kind) => {
    set({
      traceLoading: true,
      traceOpen: true,
      traceRequest: { file, line, char },
      traceResult: null,
      dockOpen: true,
      focusMode: false,
    });
    try {
      const res = await api.trace({ file, line, char, kind });
      set({ traceResult: res });
    } catch (err) {
      set({
        traceResult: {
          kind: kind as TraceResult["kind"],
          engine: "index",
          locations: [],
          items: [],
        },
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      set({ traceLoading: false });
    }
  },

  setTraceOpen: (open) => set({ traceOpen: open }),
  setCommandOpen: (open) => set({ commandOpen: open }),
  toggleRail: () => set((state) => ({ railOpen: !state.railOpen, focusMode: false })),
  toggleDock: () => set((state) => ({ dockOpen: !state.dockOpen, focusMode: false })),
  toggleFocusMode: () => set((state) => ({ focusMode: !state.focusMode })),
  setContextTab: (tab) => set({ contextTab: tab }),
  revealDock: (tab) => set({ contextTab: tab, dockOpen: true, focusMode: false }),
  setReadingScale: (scale) => {
    applyReadingScale(scale);
    set({ readingScale: scale });
  },
  cycleReadingScale: () => {
    const order: ReadingScale[] = ["compact", "comfortable", "large"];
    const index = order.indexOf(get().readingScale);
    const next = order[(index + 1) % order.length];
    applyReadingScale(next);
    set({ readingScale: next });
  },
  setCodeTheme: (theme) => {
    applyCodeTheme(theme);
    set({ codeTheme: theme });
  },
  toggleCodeTheme: () => {
    const next: CodeTheme = get().codeTheme === "dark" ? "light" : "dark";
    applyCodeTheme(next);
    set({ codeTheme: next });
  },
  setError: (error) => set({ error }),
  setNotice: (notice) => set({ notice }),
  clearActiveSlice: () => set({
    activeSliceId: null, activeSlice: null, activeSegmentId: null,
    activeThread: null, suggestedSlices: [], activeLine: null,
    traceResult: null, traceRequest: null, traceOpen: false, traceLoading: false,
  }),
}));
