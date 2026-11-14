import type {
  ApiSettings, BasePayload, SelectionContext, Skeleton, SkeletonNode,
  Slice, Thread, TrackData, TraceResult, Workspace,
} from "../types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  const payload = (data || {}) as { error?: string; hint?: string };
  if (!res.ok || payload.error) {
    const message = payload.error
      ? `${payload.error}${payload.hint ? ` — ${payload.hint}` : ""}`
      : `HTTP ${res.status}`;
    throw new ApiError(message, res.status);
  }
  return data as T;
}

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

export const api = {
  health: () => request<{
    ok: boolean;
    version: string;
    build: string;
    features: string[];
    root: string | null;
    frontend: string;
  }>("/api/health"),
  base: () => request<BasePayload>("/api/index"),
  settings: () => request<{ settings: ApiSettings }>("/api/settings"),
  saveSettings: (body: {
    apiKey?: string;
    baseUrl?: string;
    model?: string;
    clearKey?: boolean;
  }) => post<{ settings: ApiSettings }>("/api/settings", body),
  listModels: (body: { baseUrl: string; apiKey?: string }) =>
    post<{ models: string[] }>("/api/settings/models", body),

  workspace: () => request<Workspace>("/api/workspace"),
  projects: () => request<{
    root: string | null;
    recent: string[];
    defaultRoot: string;
    home: string;
    roots: { path: string; label: string; kind: string }[];
  }>("/api/projects"),
  browse: (path?: string) => request<{
    path: string;
    parent: string | null;
    entries: { name: string; path: string; hidden: boolean; project: boolean }[];
    roots: { path: string; label: string; kind: string }[];
    home: string;
    cwd: string;
  }>(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  pickFolder: (initial?: string) =>
    post<{ path: string | null; cancelled: boolean }>("/api/pick-folder", { initial: initial || "" }),
  open: (root: string) => post<BasePayload>("/api/open", { root }),
  source: (path: string) =>
    request<{ path: string; text: string }>(`/api/source?path=${encodeURIComponent(path)}`),

  track: (id: string) => request<TrackData>(`/api/track?id=${encodeURIComponent(id)}`),
  createTrack: (body: { name: string; intent?: string; depth?: string }) =>
    post<{ track: TrackData["track"]; trackRecord: TrackData }>("/api/tracks", body),
  updateTrack: (body: { id: string; name?: string; intent?: string; depth?: string; stage?: string }) =>
    post<{ track: TrackData["track"]; trackRecord: TrackData }>("/api/tracks/update", body),
  deleteTrack: (id: string) => post<{ deleted: boolean }>("/api/tracks/delete", { id }),

  skeletons: () => request<{ skeletons: Skeleton[] }>("/api/skeletons"),
  skeleton: (id: string) => request<{ skeleton: Skeleton }>(`/api/skeleton?id=${encodeURIComponent(id)}`),
  generateSkeleton: (body: { trackId?: string; focus?: string }) =>
    post<{ skeleton: Skeleton; source: string }>("/api/skeletons/generate", body),
  explainSkeletonNode: (body: { skeletonId: string; nodeId: string }) =>
    post<{ skeleton: Skeleton; node: SkeletonNode }>("/api/skeletons/node/explain", body),
  importSkeletonMain: (body: { trackId: string; skeletonId: string }) =>
    post<{ trackRecord: TrackData; needs: unknown[]; thread: Thread }>("/api/skeletons/import-main", body),
  importSkeletonNode: (body: { trackId: string; skeletonId: string; nodeId: string }) =>
    post<{ trackRecord: TrackData; needs: unknown[]; thread: Thread }>("/api/skeletons/import-node", body),
  deleteSkeleton: (id: string) => post<{ deleted: boolean }>("/api/skeletons/delete", { id }),

  slices: () => request<{ slices: Slice[] }>("/api/slices"),
  slice: (id: string) => request<{ slice: Slice; thread: Thread | null }>(`/api/slice?id=${encodeURIComponent(id)}`),
  generateSlice: (body: {
    trackId?: string; query: string; strategies?: string[];
    scope?: Record<string, unknown>;
  }) => post<{ slice: Slice; thread: Thread; source: string }>("/api/slices/generate", body),
  regenerateSlice: (id: string) =>
    post<{ slice: Slice; thread: Thread; source: string }>("/api/slices/regenerate", { id }),
  deleteSlice: (id: string) => post<{ deleted: boolean }>("/api/slices/delete", { id }),
  renameSlice: (id: string, name: string) => post<{ slice: Slice }>("/api/slices/rename", { id, name }),

  planChat: (body: { trackId: string; message: string }) =>
    post<{
      reply: string;
      turn: Record<string, unknown>;
      notes: string[];
      plan: TrackData["plan"];
      trackRecord: TrackData;
      thread: Thread | null;
    }>("/api/plan/chat", body),
  applyPlan: (body: { trackId: string; name?: string; intent?: string; items: unknown[] }) =>
    post<{ plan: TrackData["plan"]; trackRecord: TrackData }>("/api/plan/apply", body),
  generateBind: (body: { trackId: string; request: Record<string, unknown> }) =>
    post<{
      bind: Record<string, unknown>;
      source: string;
      slice: Slice;
      thread: Thread;
      trackRecord: TrackData;
    }>("/api/tracks/generate-bind", body),

  thread: (id: string) => request<{ thread: Thread }>(`/api/thread?id=${encodeURIComponent(id)}`),
  createThread: (body: {
    scope: string; trackId?: string; sliceId?: string;
    anchor?: Record<string, unknown>; title?: string;
  }) => post<{ thread: Thread }>("/api/threads", body),
  threadMessage: (body: {
    threadId: string; message: string; context?: SelectionContext | Record<string, unknown>;
  }) => post<{ thread: Thread; rejected: string[]; suggestedSlices: { query: string; title: string; reason: string }[] }>(
    "/api/threads/message", body,
  ),

  trace: (body: { file: string; line: number; char: number; kind: string }) =>
    post<TraceResult>("/api/trace", body),
};
