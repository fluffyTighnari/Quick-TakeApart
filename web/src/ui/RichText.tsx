import React, { useMemo } from "react";
import type { Sym } from "../types";
import { Mermaid } from "./Mermaid";

export interface RichContext {
  symbols: Record<string, Sym>;
  files: Set<string>;
  onSymbol?: (id: string) => void;
  onLocation?: (file: string, line: number) => void;
}

function shortName(sid: string): string {
  const [file, qual] = sid.split("::");
  return qual || file.split("/").pop() || sid;
}

function splitToken(inner: string): [string, string | undefined] {
  const at = inner.lastIndexOf("|");
  if (at < 0) return [inner, undefined];
  return [inner.slice(0, at), inner.slice(at + 1)];
}

function symbolNode(token: string, ctx: RichContext, key: string): React.ReactNode {
  const inner = token.slice("[[sym:".length, -"]]".length);
  const [sid, label] = splitToken(inner);
  const known = !!ctx.symbols[sid];
  return (
    <span
      key={key}
      className={`sym-chip${known ? "" : " invalid"}`}
      title={known ? sid : "索引中不存在这个符号"}
      role={known ? "button" : undefined}
      tabIndex={known ? 0 : undefined}
      onClick={() => known && ctx.onSymbol?.(sid)}
      onKeyDown={(e) => {
        if (known && (e.key === "Enter" || e.key === " ")) ctx.onSymbol?.(sid);
      }}
    >
      {known ? label || shortName(sid) : `${label || sid} · 未索引`}
    </span>
  );
}

function locationNode(token: string, ctx: RichContext, key: string): React.ReactNode {
  const inner = token.slice("[[loc:".length, -"]]".length);
  const [loc, label] = splitToken(inner);
  const m = loc.match(/^(.+):(\d+)(?:-(\d+))?$/);
  if (!m) {
    return <span key={key} className="sym-chip invalid">{label || loc}</span>;
  }
  const file = m[1];
  const start = Number(m[2]);
  const end = Number(m[3] || m[2]);
  const known = ctx.files.has(file);
  return (
    <span
      key={key}
      className={`sym-chip loc-chip${known ? "" : " invalid"}`}
      title={known ? `${file}:${start}` : "索引中不存在这个文件"}
      role={known ? "button" : undefined}
      tabIndex={known ? 0 : undefined}
      onClick={() => known && ctx.onLocation?.(file, start)}
      onKeyDown={(e) => {
        if (known && (e.key === "Enter" || e.key === " ")) ctx.onLocation?.(file, start);
      }}
    >
      {label || `${file.split("/").pop()}:${start}${end !== start ? `-${end}` : ""}`}
    </span>
  );
}

function inline(text: string, ctx: RichContext, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\[\[sym:[^\]]+\]\]|\[\[loc:[^\]]+\]\]|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    last = m.index + m[0].length;
    const token = m[0];
    const key = `${keyPrefix}-i${n++}`;
    if (token.startsWith("[[sym:")) {
      out.push(symbolNode(token, ctx, key));
    } else if (token.startsWith("[[loc:")) {
      out.push(locationNode(token, ctx, key));
    } else if (token.startsWith("**")) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("*")) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (link) {
        const href = link[2];
        const safe = /^(https?:|#|\/)/.test(href);
        out.push(
          <a
            key={key}
            href={safe ? href : "#"}
            target={href.startsWith("http") ? "_blank" : undefined}
            rel="noreferrer"
          >
            {link[1]}
          </a>,
        );
      } else {
        out.push(token);
      }
    }
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function EvidenceBlock({ code }: { code: string }) {
  const rows = useMemo(() => {
    return code
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return JSON.parse(line) as Record<string, unknown>;
        } catch {
          const parts = line.split(/\t|\s*\|\s*/);
          return {
            status: parts[0] || "",
            from: parts[1] || "",
            to: parts[2] || "",
            site: parts[3] || "",
          };
        }
      });
  }, [code]);
  return (
    <details className="evidence-block">
      <summary>证据 · {rows.length} 条</summary>
      {rows.map((row, i) => (
        <div className="evidence-row" key={i}>
          <span className={`chip ${row.status === "direct" ? "teal" : row.status === "reverse" ? "amber" : "muted"}`}>
            {String(row.status || "evidence")}
          </span>
          <span>{String(row.from || "")}</span>
          <span className="muted">→</span>
          <span>{String(row.to || "")}</span>
          {row.site ? <span className="muted" style={{ marginLeft: "auto" }}>{String(row.site)}</span> : null}
        </div>
      ))}
    </details>
  );
}

function isBlockStart(line: string): boolean {
  return /^(#{1,4}\s|```|>\s?|[-*]\s|\d+\.\s|---+\s*$)/.test(line) ||
    (/^\|/.test(line));
}

function blocks(text: string, ctx: RichContext, keyPrefix: string): React.ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  let n = 0;
  const nextKey = () => `${keyPrefix}-b${n++}`;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    const fence = line.match(/^```([\w-]*)\s*$/);
    if (fence) {
      const lang = fence[1] || "";
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        body.push(lines[i]);
        i++;
      }
      i++;
      const code = body.join("\n");
      const key = nextKey();
      if (lang === "mermaid") {
        out.push(<Mermaid key={key} code={code} scroll />);
      } else if (lang === "evidence") {
        out.push(<EvidenceBlock key={key} code={code} />);
      } else {
        out.push(
          <pre key={key}>
            <code>{code}</code>
          </pre>,
        );
      }
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2], ctx, nextKey());
      const Tag = (`h${level}` as unknown) as keyof React.JSX.IntrinsicElements;
      out.push(React.createElement(Tag, { key: nextKey() }, content));
      i++;
      continue;
    }

    if (/^---+\s*$/.test(line)) {
      out.push(<hr key={nextKey()} />);
      i++;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      let tone = "";
      if (quote[0]?.startsWith("[!note]")) {
        tone = "note";
        quote[0] = quote[0].replace("[!note]", "").trim();
      } else if (quote[0]?.startsWith("[!warn]")) {
        tone = "warn";
        quote[0] = quote[0].replace("[!warn]", "").trim();
      } else if (quote[0]?.startsWith("[!evidence]")) {
        tone = "evidence";
        quote[0] = quote[0].replace("[!evidence]", "").trim();
      }
      out.push(
        <blockquote key={nextKey()} className={tone}>
          {blocks(quote.join("\n"), ctx, nextKey())}
        </blockquote>,
      );
      continue;
    }

    if (/^[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s/, ""));
        i++;
      }
      out.push(
        <ul key={nextKey()}>
          {items.map((item, idx) => <li key={idx}>{inline(item, ctx, `${nextKey()}-l${idx}`)}</li>)}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ""));
        i++;
      }
      out.push(
        <ol key={nextKey()}>
          {items.map((item, idx) => <li key={idx}>{inline(item, ctx, `${nextKey()}-o${idx}`)}</li>)}
        </ol>,
      );
      continue;
    }

    if (/^\|/.test(line) && i + 1 < lines.length && /^\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const headerCells = line.split("|").slice(1, -1).map((s) => s.trim());
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\|/.test(lines[i])) {
        rows.push(lines[i].split("|").slice(1, -1).map((s) => s.trim()));
        i++;
      }
      out.push(
        <table key={nextKey()}>
          <thead>
            <tr>{headerCells.map((cell, idx) => <th key={idx}>{inline(cell, ctx, `${nextKey()}-th${idx}`)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>{row.map((cell, c) => <td key={c}>{inline(cell, ctx, `${nextKey()}-td${r}-${c}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }

    const para: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    out.push(<p key={nextKey()}>{inline(para.join(" "), ctx, nextKey())}</p>);
  }
  return out;
}

export function RichText({
  text,
  symbols,
  files,
  onSymbol,
  onLocation,
  className = "",
}: {
  text: string;
  symbols: Record<string, Sym>;
  files: Set<string>;
  onSymbol?: (id: string) => void;
  onLocation?: (file: string, line: number) => void;
  className?: string;
}) {
  const ctx = useMemo<RichContext>(
    () => ({ symbols, files, onSymbol, onLocation }),
    [symbols, files, onSymbol, onLocation],
  );
  const nodes = useMemo(() => blocks(text || "", ctx, "r"), [text, ctx]);
  return <div className={`rich ${className}`}>{nodes}</div>;
}
