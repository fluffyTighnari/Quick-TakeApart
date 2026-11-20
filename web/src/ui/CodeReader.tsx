import React, { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionContext, Sym } from "../types";

const PY_KEYWORDS = new Set([
  "def", "class", "return", "if", "elif", "else", "for", "while", "in",
  "not", "and", "or", "is", "None", "True", "False", "import", "from",
  "as", "with", "try", "except", "finally", "raise", "yield", "lambda",
  "pass", "break", "continue", "global", "nonlocal", "assert", "del",
  "async", "await", "match", "case",
]);

const TS_KEYWORDS = new Set([
  "const", "let", "var", "function", "return", "if", "else", "for",
  "while", "do", "switch", "case", "default", "class", "interface",
  "type", "enum", "namespace", "import", "from", "export", "extends",
  "implements", "new", "try", "catch", "finally", "throw", "async",
  "await", "yield", "public", "private", "protected", "static",
  "readonly", "as", "in", "of", "instanceof", "typeof", "void", "null",
  "undefined", "true", "false", "this", "super", "break", "continue",
  "abstract", "declare", "keyof", "unknown", "never",
]);

const GOLANG_KEYWORDS = new Set([
  "package", "import", "func", "type", "struct", "interface", "var",
  "const", "return", "if", "else", "for", "range", "go", "defer",
  "chan", "select", "case", "switch", "break", "continue", "fallthrough",
  "map", "make", "new", "nil", "true", "false", "iota", "default",
]);

const JAVA_KEYWORDS = new Set([
  "package", "import", "class", "interface", "enum", "record", "extends",
  "implements", "public", "private", "protected", "static", "final",
  "abstract", "native", "synchronized", "transient", "volatile", "strictfp",
  "default", "sealed", "permits", "void", "boolean", "byte", "char",
  "short", "int", "long", "float", "double", "return", "if", "else",
  "for", "while", "do", "switch", "case", "break", "continue", "new",
  "this", "super", "try", "catch", "finally", "throw", "throws",
  "instanceof", "null", "true", "false", "var", "yield", "assert",
]);

const CPP_KEYWORDS = new Set([
  "alignas", "auto", "bool", "break", "case", "catch", "char", "class",
  "const", "constexpr", "continue", "decltype", "default", "delete", "do",
  "double", "else", "enum", "explicit", "export", "extern", "false",
  "float", "for", "friend", "goto", "if", "inline", "int", "long",
  "mutable", "namespace", "new", "noexcept", "nullptr", "operator",
  "override", "private", "protected", "public", "return", "short",
  "signed", "sizeof", "static", "struct", "switch", "template", "this",
  "throw", "true", "try", "typedef", "typename", "union", "unsigned",
  "using", "virtual", "void", "volatile", "while",
]);

type CodeLanguage = "python" | "typescript" | "go" | "java" | "cpp" | "generic";

function languageForFile(file: string): CodeLanguage {
  const ext = file.slice(file.lastIndexOf(".")).toLowerCase();
  if ([".py", ".pyi"].includes(ext)) return "python";
  if ([".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"].includes(ext)) return "typescript";
  if (ext === ".go") return "go";
  if (ext === ".java") return "java";
  if ([".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".c++", ".h++", ".ino"].includes(ext)) return "cpp";
  return "generic";
}

function keywordsFor(language: string): Set<string> {
  if (language === "python") return PY_KEYWORDS;
  if (language === "typescript") return TS_KEYWORDS;
  if (language === "go") return GOLANG_KEYWORDS;
  if (language === "java") return JAVA_KEYWORDS;
  if (language === "cpp") return CPP_KEYWORDS;
  return new Set();
}

function commentStart(line: string, language: string): number {
  if (language === "generic") return -1;
  let quote = "";
  let escaped = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      if (escaped) { escaped = false; continue; }
      if (ch === "\\") { escaped = true; continue; }
      if (ch === quote) quote = "";
      continue;
    }
    if (ch === "'" || ch === '"' || ch === "`") { quote = ch; continue; }
    if (language === "python" && ch === "#") return i;
    if (language !== "python" && ch === "/" && line[i + 1] === "/") return i;
    if (language !== "python" && ch === "/" && line[i + 1] === "*") return i;
  }
  return -1;
}

const PY_TYPES = new Set([
  "int", "str", "float", "bool", "bytes", "list", "dict", "set", "tuple",
  "frozenset", "object", "type", "Any", "Optional", "Union", "Callable",
  "Iterable", "Iterator", "Sequence", "Mapping", "Literal", "Self", "Never",
]);

const TOKEN_RE = new RegExp([
  '("""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\')',
  '([rbfuRBFU]{0,2}"(?:[^"\\\\\\n]|\\\\.)*")',
  "([rbfuRBFU]{0,2}'(?:[^'\\\\\\n]|\\\\.)*')",
  "(`(?:[^`\\\\]|\\\\.)*`)",
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

function tokenize(line: string, language: string): Tok[] {
  const out: Tok[] = [];
  const cut = commentStart(line, language);
  const code = cut >= 0 ? line.slice(0, cut) : line;
  let last = 0;
  let prevReal = "";
  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(code)) !== null) {
    if (m.index > last) {
      out.push({ text: code.slice(last, m.index), cls: "tok-ghost", start: last, word: false });
    }
    const [tok, tri, dstr, sstr, bstr, deco, num, ident, punct] = m;
    let cls = "tok-ghost";
    let word = false;
    if (tri || dstr || sstr || bstr) {
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
      if (keywordsFor(language).has(ident)) {
        cls = "tok-key";
        prevReal = ["def", "class", "function", "func", "interface", "type"].includes(ident)
          ? "def" : "kw";
      } else if (prevReal === "def") {
        cls = "tok-def";
        prevReal = "name";
      } else if (ident === "self" || ident === "cls" || ident === "this") {
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
  if (last < code.length) {
    out.push({ text: code.slice(last), cls: "tok-ghost", start: last, word: false });
  }
  if (cut >= 0) {
    out.push({ text: line.slice(cut), cls: "tok-com", start: cut, word: false });
  }
  return out;
}

function isTraceable(tok: Tok): boolean {
  // Functions/types and variables/identifiers are traceable. Language
  // keywords and self/cls are not useful lookup targets.
  return tok.word && tok.cls !== "tok-key" && tok.cls !== "tok-self";
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

  const language = useMemo(() => languageForFile(file), [file]);
  const lines = useMemo(() => text.replace(/\r\n/g, "\n").split("\n"), [text]);
  const tokenLines = useMemo(
    () => lines.map((line) => tokenize(line, language)),
    [lines, language],
  );
  const defsByLine = useMemo(() => {
    const map = new Map<number, string>();
    for (const sym of Object.values(symbols)) {
      if (sym.file === file) map.set(sym.line, sym.id);
    }
    return map;
  }, [symbols, file]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const target = callSite || focus?.start;
    if (!target) return;
    const el = root.querySelector<HTMLElement>(`[data-line="${target}"]`);
    if (!el) return;
    // Only scroll the code viewport when it actually scrolls. Using
    // scrollIntoView unconditionally also scrolled the whole page, hiding the
    // slice title every time a segment opened.
    if (root.scrollHeight > root.clientHeight + 1) {
      const line = el.getBoundingClientRect();
      const box = root.getBoundingClientRect();
      const top = root.scrollTop + (line.top - box.top)
        - root.clientHeight / 2 + line.height / 2;
      root.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    } else {
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [file, focus?.start, callSite]);

  useEffect(() => {
    setSel(null);
  }, [file]);

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
        <span className="muted code-hint">Ctrl+点击函数/变量 · 选中提问</span>
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
                  return (
                    <span
                      key={i}
                      className={`${tok.cls}${tok.word ? " tok-word" : ""}${traceable ? " traceable" : ""}`}
                      onClick={(e) => {
                        if (e.ctrlKey || e.metaKey) traceToken(lineNo, tok, e);
                        else clickToken(lineNo, tok, e);
                      }}
                      title={traceable ? "Ctrl+点击查找函数/变量定义与引用" : undefined}
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
