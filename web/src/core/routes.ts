import type { Stage } from "../types";

export function stageFromPath(pathname: string): Stage {
  const parts = pathname.split("/").filter(Boolean);
  const stage = parts[0] === "track" ? parts[2] : "";
  if (stage === "plan" || stage === "read" || stage === "library") return stage;
  return "architecture";
}

export function trackPath(trackId: string, stage: Stage, sliceId?: string | null) {
  const base = `/track/${trackId}/${stage}`;
  if (stage === "read" && sliceId) return `${base}/${sliceId}`;
  return base;
}
