export type SymbolKind = "function" | "method" | "class" | "module";

export interface Sym {
  id: string;
  name: string;
  qualname: string;
  file: string;
  kind: SymbolKind;
  line: number;
  endLine: number;
  signature: string;
}

export interface Edge {
  from: string;
  to: string;
  line: number;
  kind: "intra" | "cross" | "external";
}

export interface Claim {
  kind: string;
  subject: string;
  object: string;
  objectLabel: string;
  line: number;
  file: string;
}

export interface Stats {
  symbols: number;
  callables: number;
  edges: number;
  crossFile: number;
  unresolved: number;
  files: number;
}

export interface LanguageStatus {
  id: string;
  label: string;
  extensions: string[];
  files: number;
  available: boolean;
  command: string;
  source: string;
}

export interface BasePayload {
  root: string;
  name: string;
  revision: string;
  stats: Stats;
  languages: LanguageStatus[];
  symbols: Record<string, Sym>;
  edges: Edge[];
  claims: Record<string, Claim[]>;
  files: string[];
  byFile: Record<string, string[]>;
  unresolved: { caller: string; name: string; file: string; line: number }[];
  queries: string[];
}

export interface Staleness {
  fresh: boolean;
  usable: boolean;
  missing: string[];
  moved: string[];
  changed: string[];
  detail: Record<string, "ok" | "moved" | "changed" | "missing">;
  summary: string;
}

export interface Track {
  id: string;
  name: string;
  intent: string;
  depth: string;
  planId: string;
  planThreadId: string;
  pinnedSliceIds: string[];
  stage: string;
  createdAt: string;
  updatedAt: string;
}

export interface PlanItem {
  id: string;
  flowId: string;
  goal: string;
  after: string[];
  skippable: string;
  granularity: string;
}

export interface Plan {
  id: string;
  name: string;
  intent: string;
  items: PlanItem[];
  createdAt: string;
  updatedAt: string;
  health: { dangling: string[]; rotted: string[]; unreadable: boolean };
  order: string[];
  slices: Record<string, Slice>;
  flows?: Record<string, Slice>;
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations: Citation[];
  turn?: Record<string, unknown>;
  context?: SelectionContext | Record<string, never>;
  createdAt: string;
}

export interface Citation {
  kind: "symbol" | "range";
  symbolId?: string;
  file?: string;
  startLine?: number;
  endLine?: number;
  label?: string;
}

export interface Thread {
  id: string;
  scope: "plan" | "slice" | "symbol" | "range" | "file";
  trackId: string;
  sliceId: string;
  anchor: Record<string, unknown>;
  title: string;
  messages: ThreadMessage[];
  createdAt: string;
  updatedAt: string;
}

export interface TrackSummary extends Track {
  plan: {
    id: string;
    name: string;
    intent: string;
    steps: number;
    health: Plan["health"] | null;
  } | null;
  sliceCount: number;
  threadCount: number;
}

export interface Workspace {
  root: string;
  name: string;
  stats: Stats;
  tracks: TrackSummary[];
  slices: Slice[];
  recent: string[];
  queries: string[];
}

export interface ViewNode {
  symbolId: string;
  group: string;
  depth: number;
  note: string;
  role: string;
}

export interface ViewMessage {
  from: string;
  to: string;
  label: string;
  symbolId: string;
  status: "direct" | "reverse" | "inferred";
  site?: { file: string; line: number } | null;
}

export interface ViewLink {
  from: string;
  to: string;
  status: "direct" | "reverse" | "inferred";
  file?: string;
  line?: number | null;
}

export interface View {
  kind: "path" | "sequence" | "crosscut" | "zones" | "calltree" | "dataflow";
  title: string;
  rationale: string;
  nodes: ViewNode[];
  messages: ViewMessage[];
  links: ViewLink[];
}

export interface Segment {
  id: string;
  file: string;
  startLine: number;
  endLine: number;
  symbolId: string;
  role: string;
  note: string;
  flowTitle: string;
}

export interface Annotation {
  id: string;
  anchor: {
    kind: "segment" | "symbol" | "range";
    segmentId?: string;
    symbolId?: string;
    file?: string;
    startLine?: number;
    endLine?: number;
  };
  markdown: string;
}

export interface Diagram {
  id: string;
  kind: string;
  title: string;
  mermaid: string;
}

export interface Slice {
  id: string;
  trackId: string;
  title: string;
  query: string;
  summary: string;
  strategies: string[];
  views: View[];
  segments: Segment[];
  annotations: Annotation[];
  diagrams: Diagram[];
  source: {
    kind: string;
    label?: string;
    ref?: Record<string, unknown>;
    generator?: string;
  };
  rejected?: string[];
  createdAt: string;
  revision: string;
  staleness?: Staleness;
  symbolCount?: number;
  segmentCount?: number;
  quality?: {
    thinSegments: number;
    ungroupedViews: boolean;
    ok: boolean;
  };
}

export interface LlmProvider {
  provider_id: string;
  label: string;
  kind: "openai" | "ollama" | "anthropic";
  base_url: string;
  needs_key: boolean;
  supports_model_list: boolean;
  default_model: string;
  key_hint: string;
  known_models: string[];
  context_window?: number;
}

export interface LlmProfile {
  profile_id: string;
  label: string;
  provider_id: string;
  kind: LlmProvider["kind"];
  base_url: string;
  model: string;
  models: string[];
  think: "" | "true" | "false";
  num_ctx: number;
  effective_num_ctx: number;
  is_active: boolean;
  note: string;
  has_key: boolean;
  key_masked: string;
  created_at: string;
  updated_at: string;
}

export interface LlmConfigView {
  active: Omit<LlmProfile, "has_key" | "key_masked"> & {
    source?: string;
    api_key?: string;
    has_key?: boolean;
  };
  fallback: Record<string, unknown>;
  env_loaded: boolean;
  profiles_path: string;
  secrets_path: string;
}

export interface ApiSettings {
  baseUrl: string;
  model: string;
  hasKey: boolean;
  keyHint: string;
  envKey?: boolean;
  envKeyHint?: string;
  languageServers?: Record<string, string>;
  updatedAt: string;
  settingsPath: string;
}

export interface SkeletonNode {
  id: string;
  title: string;
  summary: string;
  phase: string;
  symbolIds: string[];
  files: string[];
  detail: string;
  detailCreatedAt: string;
  detailSource?: string;
}

export interface SkeletonLink {
  from: string;
  to: string;
  status: "direct" | "reverse" | "inferred";
  file?: string;
  line?: number | null;
}

export interface Skeleton {
  id: string;
  trackId: string;
  focus: string;
  title: string;
  overview: string;
  main: SkeletonNode[];
  support: SkeletonNode[];
  links: SkeletonLink[];
  createdAt: string;
  revision: string;
  staleness?: Staleness;
  detailCount?: number;
}

export interface TrackData {
  track: Track;
  plan: Plan | null;
  planThread: Thread | null;
  threads: Thread[];
  slices: Slice[];
  skeletons: Skeleton[];
}

export interface SelectionContext {
  file: string;
  startLine: number;
  endLine: number;
  startColumn?: number;
  endColumn?: number;
  text?: string;
  symbolId?: string;
  label?: string;
}

export interface TraceLocation {
  file: string;
  line: number;
  char: number;
  endLine: number;
  endChar: number;
  symbolId: string;
  name: string;
  external?: boolean;
  sites?: { file: string; line: number }[];
}

export interface TraceResult {
  kind: "definition" | "references" | "callers" | "callees";
  engine: "lsp" | "index";
  locations?: TraceLocation[];
  items?: TraceLocation[];
  externalCount?: number;
}

export type Stage = "architecture" | "plan" | "read" | "library";
