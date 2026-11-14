import React, { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionContext, Sym } from "../types";

const PY_KEYWORDS = new Set([
  "def", "class", "return", "if", "elif", "else", "for", "while", "in",
  "not", "and", "or", "is", "None", "True", "False", "import", "from",
  "as", "with", "try", "except", "finally", "raise", "yield", "lambda",
  "pass", "break", "continue", "global", "nonlocal", "assert", "del",
  "async", "await", "match", "case",
]);

const PY_TYPES = new Set([
  "int", "str", "float", "bool", "bytes", "list", "dict", "set", "tuple",
  "frozenset", "object", "type", "Any", "Optional", "Union", "Callable",
  "Iterable", "Iterator", "Sequence", "Mapping", "Literal", "Self", "Never",
]);

const TOKEN_RE = new RegExp([
  "(#[^\\n]*)",
  '("""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\')',
  '([rbfuRBFU]{0,2}"(?:[^"\\\\\\n]|\\\\.)*")',
  "([rbfuRBFU]{0,2}'(?:[^'\\\\\\n]|\\\\.)*')",
  "(@[A-Za-z_][\\w.]*)",
  "\\b(\\d+\\.?\\d*(?:[eE][-+]?\\d+)?)\\b",
  "([A-Za-z_]\\w*)",
  "([^\\w\\s])",
].join("|"), "g");

type Tok = {
  text: string;
  cls: string;
  start: number;
  word: boolean;
};

function tokenize(line: string): Tok[] {
  const out: Tok[] = [];
  let last = 0;
  let prevReal = "";
  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(line)) !== null) {
    if (m.index > last) {
      out.push({ text: line.slice(last, m.index), cls: "tok-ghost", start: last, word: false });
    }
    const [tok, com, tri, dstr, sstr, deco, num, ident, punct] = m;
    let cls = "tok-ghost";
    let word = false;
    if (com) {
      cls = "tok-com";
      prevReal = "comment";
    } else if (tri || dstr || sstr) {
      cls = "tok-str";
      prevReal = "str";
    } else if (deco) {
      cls = "tok-deco";
      prevReal = "deco";
    } else if (num) {
      cls = "tok-num";
      prevReal = "num";
    } else if (ident) {
      word = true;
      if (PY_KEYWORDS.has(ident)) {
        cls = "tok-key";
        prevReal = ident === "def" || ident === "class" ? "def" : "kw";
      } else if (prevReal === "def") {
        cls = "tok-def";
        prevReal = "name";
      } else if (ident === "self" || ident === "cls") {
        cls = "tok-self";
        prevReal = "name";
      } else if (PY_TYPES.has(ident) || /^[A-Z][A-Za-z0-9_]*$/.test(ident)) {
        cls = "tok-type";
        prevReal = "name";
      } else if (line[m.index + tok.length] === "(") {
        cls = "tok-call";
        prevReal = "name";
      } else {
        cls = "tok-ghost";
        prevReal = "name";
      }
    } else if (punct) {
      cls = "tok-punct";
      prevReal = "punct";
    }
    out.push({ text: tok, cls, start: m.index, word });
    last = m.index + tok.length;
  }
  if (last < line.length) {
    out.push({ text: line.slice(last), cls: "tok-ghost", start: last, word: false });
  }
  return out;
}

function isTraceable(tok: Tok): boolean {
  // Reading lookup is deliberately narrow: functions/classes and language
  // keywords. Variables, self, literals and arbitrary words are not traceable.
  return tok.word && (
    tok.cls === "tok-call" || tok.cls === "tok-def" || tok.cls === "tok-key"
  );
}

function lineFromNode(node: Node | null): number | null {
  let el: Node | null = node;
  while (el) {
    if (el instanceof HTMLElement && el.dataset.line) {
      return Number(el.dataset.line);
    }
    el = el.parentNode;
  }
  return null;
}

function columnInLine(node: Node | null, offset: number): number {
  let el: Node | null = node;
  while (el && !(el instanceof HTMLElement && el.dataset.line)) el = el.parentNode;
  if (!(el instanceof HTMLElement)) return offset;
  const src = el.querySelector(".src");
  if (!src) return offset;
  const walker = document.createTreeWalker(src, NodeFilter.SHOW_TEXT);
  let col = 0;
  let current = walker.nextNode();
  while (current) {
    if (current === node) return col + offset;
    col += current.textContent?.length || 0;
    current = walker.nextNode();
  }
  return col + offset;
}

export function CodeReader({
  file,
  text,
  baseLine = 1,
  symbols,
  focus,
  ranges,
  callSite,
  onTrace,
  onSymbol,
  onAsk,
  onSliceSelection,
  maxHeight = 460,
  showAll = false,
  className = "",
}: {
  file: string;
  text: string;
  baseLine?: number;
  symbols: Record<string, Sym>;
  focus?: { start: number; end: number } | null;
  ranges?: { start: number; end: number }[];
  callSite?: number | null;
  onTrace?: (file: string, line: number, char: number) => void;
  onSymbol?: (id: string) => void;
  onAsk?: (ctx: SelectionContext) => void;
  onSliceSelection?: (ctx: SelectionContext) => void;
  maxHeight?: number;
  showAll?: boolean;
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [sel, setSel] = useState<(SelectionContext & { x: number; y: number }) | null>(null);
  const [keywordHit, setKeywordHit] = useState<string | null>(null);

  const lines = useMemo(() => text.replace(/\r\n/g, "\n").split("\n"), [text]);
  const tokenLines = useMemo(() => lines.map((line) => tokenize(line)), [lines]);
  const keywordCount = useMemo(
    () => keywordHit
      ? tokenLines.flat().filter((tok) => tok.cls === "tok-key" && tok.text === keywordHit).length
      : 0,
    [tokenLines, keywordHit],
  );

  useEffect(() => {
    setKeywordHit(null);
  }, [file]);
  const defsByLine = useMemo(() => {
    const map = new Map<number, string>();
    for (const sym of Object.values(symbols)) {
      if (sym.file === file) map.set(sym.line, sym.id);
    }
    return map;
  }, [symbols, file]);

  useEffect(() => {
    if (!rootRef.current) return;
    const target = focus?.start || callSite;
    if (!target) return;
    const el = rootRef.current.querySelector(`[data-line="${target}"]`);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [file, focus?.start, callSite]);

  useEffect(() => {
    const hide = (event: MouseEvent) => {
      if (!(event.target as HTMLElement)?.closest?.(".selection-toolbar")) setSel(null);
    };
    document.addEventListener("mousedown", hide);
    return () => document.removeEventListener("mousedown", hide);
  }, []);

  function handleMouseUp() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !rootRef.current) {
      setSel(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!rootRef.current.contains(range.commonAncestorContainer)) {
      setSel(null);
      return;
    }
    const start = lineFromNode(range.startContainer);
    const end = lineFromNode(range.endContainer);
    const selected = selection.toString();
    if (!start || !end || !selected.trim()) {
      setSel(null);
      return;
    }
    const rect = range.getBoundingClientRect();
    setSel({
      file,
      startLine: start,
      endLine: Math.max(start, end),
      startColumn: columnInLine(range.startContainer, range.startOffset),
      endColumn: columnInLine(range.endContainer, range.endOffset),
      text: selected,
      x: Math.min(window.innerWidth - 220, Math.max(12, rect.left)),
      y: Math.max(48, rect.top - 42),
    });
  }

  function traceToken(lineNo: number, tok: Tok, event: React.MouseEvent) {
    if (!(event.ctrlKey || event.metaKey) || !isTraceable(tok)) return;
    event.preventDefault();
    if (tok.cls === "tok-key") {
      // Keywords are a local find, not a language-server definition request.
      setKeywordHit((current) => current === tok.text ? null : tok.text);
      return;
    }
    onTrace?.(file, lineNo, tok.start);
  }

  function clickToken(lineNo: number, tok: Tok, event: React.MouseEvent) {
    if (event.ctrlKey || event.metaKey) return;
    if (!(tok.cls === "tok-def" || tok.cls === "tok-call")) return;
    const def = defsByLine.get(lineNo);
    if (def) onSymbol?.(def);
  }

  return (
    <div className={`code-cabin ${className}`}>
      <div className="code-top">
        <span className="file">{file}</span>
        <span className="sep">/</span>
        <span>{lines.length} 行</span>
        <span className="grow" />
        {keywordHit ? (
          <span className="code-keyword-hit">
            关键字 {keywordHit} · {keywordCount} 处
            <button onClick={() => setKeywordHit(null)}>清除</button>
          </span>
        ) : null}
        <span className="muted">Ctrl+点击函数/关键字 · 选中提问</span>
      </div>
      <div
        className={`code-scroll${showAll ? " tall" : ""}`}
        style={showAll ? undefined : { maxHeight }}
        ref={rootRef}
        onMouseUp={handleMouseUp}
      >
        {tokenLines.map((tokens, index) => {
          const lineNo = baseLine + index;
          const inFocus = (focus && lineNo >= focus.start && lineNo <= focus.end) ||
            !!ranges?.some((r) => lineNo >= r.start && lineNo <= r.end);
          const isDef = defsByLine.has(lineNo);
          const isHead = focus?.start === lineNo;
          return (
            <div
              key={lineNo}
              data-line={lineNo}
              className={[
                "code-line",
                inFocus ? "target" : "",
                isHead ? "head" : "",
                isDef && !isHead ? "hit" : "",
                callSite === lineNo ? "hit" : "",
              ].filter(Boolean).join(" ")}
            >
              <span className="ln">{lineNo}</span>
              <span className="src">
                {tokens.map((tok, i) => {
                  const traceable = isTraceable(tok);
                  const keywordHitHere = !!keywordHit
                    && tok.cls === "tok-key" && tok.text === keywordHit;
                  const title = !traceable ? undefined
                    : tok.cls === "tok-key"
                      ? "Ctrl+点击查找关键字出现位置"
                      : "Ctrl+点击查找函数定义与引用";
                  return (
                    <span
                      key={i}
                      className={`${tok.cls}${tok.word ? " tok-word" : ""}${traceable ? " traceable" : ""}${keywordHitHere ? " keyword-hit" : ""}`}
                      onClick={(e) => {
                        if (e.ctrlKey || e.metaKey) traceToken(lineNo, tok, e);
                        else clickToken(lineNo, tok, e);
                      }}
                      title={title}
                    >
                      {tok.text || " "}
                    </span>
                  );
                })}
              </span>
            </div>
          );
        })}
      </div>
      {sel ? (
        <div className="selection-toolbar" style={{ left: sel.x, top: sel.y }}>
          {onAsk ? (
            <button
              onClick={() => {
                onAsk({
                  file: sel.file,
                  startLine: sel.startLine,
                  endLine: sel.endLine,
                  startColumn: sel.startColumn,
                  endColumn: sel.endColumn,
                  text: sel.text,
                  label: `${file}:${sel.startLine}-${sel.endLine}`,
                });
                setSel(null);
              }}
            >
              提问
            </button>
          ) : null}
          {onSliceSelection ? (
            <button
              onClick={() => {
                onSliceSelection({
                  file: sel.file,
                  startLine: sel.startLine,
                  endLine: sel.endLine,
                  startColumn: sel.startColumn,
                  endColumn: sel.endColumn,
                  text: sel.text,
                  label: `${sel.file}:${sel.startLine}-${sel.endLine}`,
                });
                setSel(null);
              }}
            >
              切开
            </button>
          ) : null}
          <button
            onClick={() => {
              void navigator.clipboard?.writeText(`${sel.file}:${sel.startLine}-${sel.endLine}`);
              setSel(null);
            }}
          >
            复制引用
          </button>
        </div>
      ) : null}
    </div>
  );
}
