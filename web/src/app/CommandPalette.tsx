import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen, Boxes, FileCode2, Library, Network, Route, Search, Sparkles,
} from "lucide-react";
import { useApp } from "../core/store";
import type { Stage } from "../types";

interface Item {
  id: string;
  label: string;
  kind: string;
  icon: typeof Search;
  run: () => void;
}

export function CommandPalette() {
  const open = useApp((s) => s.commandOpen);
  const setOpen = useApp((s) => s.setCommandOpen);
  const track = useApp((s) => s.track);
  const base = useApp((s) => s.base);
  const activeTrackId = useApp((s) => s.activeTrackId);
  const setStage = useApp((s) => s.setStage);
  const generateSkeleton = useApp((s) => s.generateSkeleton);
  const generateSlice = useApp((s) => s.generateSlice);
  const openCode = useApp((s) => s.openCode);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useApp.getState().commandOpen);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setOpen]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const go = (stage: Stage) => {
    if (!activeTrackId) return;
    setStage(stage);
    navigate(`/track/${activeTrackId}/${stage}`);
  };

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [
      { id: "arch", label: "前往逻辑骨架", kind: "阶段", icon: Network, run: () => go("architecture") },
      { id: "plan", label: "前往学习计划", kind: "阶段", icon: Route, run: () => go("plan") },
      { id: "read", label: "前往切片阅读", kind: "阶段", icon: BookOpen, run: () => go("read") },
      { id: "library", label: "打开全局切片库", kind: "阶段", icon: Library, run: () => go("library") },
      {
        id: "gen-arch", label: "生成一份逻辑骨架", kind: "动作", icon: Sparkles,
        run: () => {
          const focus = window.prompt("可选：关注点（留空则看整体）", "") || "";
          void generateSkeleton(focus).then(() => go("architecture")).catch(() => undefined);
        },
      },
      {
        id: "gen-slice", label: "按问题生成一条切片", kind: "动作", icon: Sparkles,
        run: () => {
          const q = window.prompt("想追踪什么？例如：WebSocket Server 的代码", "");
          if (!q) return;
          void generateSlice(q).then((slice) => {
            if (slice && activeTrackId) navigate(`/track/${activeTrackId}/read/${slice.id}`);
          });
        },
      },
    ];

    for (const skeleton of track?.skeletons || []) {
      out.push({
        id: `skeleton-${skeleton.id}`, label: skeleton.title, kind: "骨架", icon: Boxes,
        run: () => {
          useApp.getState().selectSkeleton(skeleton.id);
          go("architecture");
        },
      });
    }
    for (const slice of track?.slices || []) {
      out.push({
        id: `slice-${slice.id}`, label: slice.title, kind: "切片", icon: FileCode2,
        run: () => {
          void useApp.getState().selectSlice(slice.id);
          if (activeTrackId) navigate(`/track/${activeTrackId}/read/${slice.id}`);
        },
      });
    }
    if (base) {
      for (const file of base.files) {
        out.push({
          id: `file-${file}`, label: file, kind: "文件", icon: FileCode2,
          run: () => {
            void openCode(file);
            go("read");
          },
        });
      }
      const symbols = Object.values(base.symbols);
      for (const sym of symbols.slice(0, 400)) {
        out.push({
          id: `sym-${sym.id}`, label: sym.qualname, kind: `${sym.file}:${sym.line}`, icon: Boxes,
          run: () => {
            void openCode(sym.file, sym.id);
            go("read");
          },
        });
      }
    }
    return out;
  }, [track, base, activeTrackId, generateSkeleton, generateSlice, navigate, openCode]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items.slice(0, 40);
    return items.filter((item) =>
      item.label.toLowerCase().includes(q) || item.kind.toLowerCase().includes(q),
    ).slice(0, 60);
  }, [items, query]);

  if (!open) return null;

  return (
    <div className="palette-backdrop" onMouseDown={(e) => {
      if (e.target === e.currentTarget) setOpen(false);
    }}>
      <div className="palette">
        <input
          ref={inputRef}
          value={query}
          placeholder="搜索阶段、骨架、切片、文件、函数…"
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((n) => Math.min(filtered.length - 1, n + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((n) => Math.max(0, n - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              filtered[active]?.run();
              setOpen(false);
            }
          }}
        />
        <div className="palette-list">
          {filtered.map((item, index) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`palette-item${index === active ? " active" : ""}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => { item.run(); setOpen(false); }}
              >
                <Icon size={14} />
                <span className="truncate">{item.label}</span>
                <span className="pi-kind">{item.kind}</span>
              </button>
            );
          })}
          {!filtered.length ? <div className="empty" style={{ margin: 8 }}>没有匹配项。</div> : null}
        </div>
        <div className="palette-foot">
          <span>↑↓ 选择</span><span>↵ 打开</span><span>esc 关闭</span>
        </div>
      </div>
    </div>
  );
}
