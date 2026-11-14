import { useEffect, useId, useMemo, useRef, useState } from "react";

interface MermaidApi {
  initialize: (config: Record<string, unknown>) => void;
  render: (id: string, code: string) => Promise<{ svg: string }>;
}

let ready = false;
let loading: Promise<MermaidApi> | null = null;

async function getMermaid(): Promise<MermaidApi> {
  if (!loading) {
    loading = import("mermaid").then((mod) => mod.default as unknown as MermaidApi);
  }
  return loading;
}

function init(mermaid: MermaidApi) {
  if (ready) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    fontFamily: '"JetBrains Mono", Consolas, monospace',
    themeVariables: {
      background: "#f7faf8",
      primaryColor: "#e2f0ec",
      primaryTextColor: "#17221f",
      primaryBorderColor: "#b9cdc8",
      lineColor: "#7b8f89",
      secondaryColor: "#edf4f1",
      tertiaryColor: "#f5f8f6",
      fontSize: "12px",
      actorBkg: "#e2f0ec",
      actorBorder: "#9dbfb8",
      actorTextColor: "#17221f",
      signalColor: "#2f7d73",
      signalTextColor: "#344641",
      labelBoxBkgColor: "#f5f8f6",
      labelBoxBorderColor: "#d5e2de",
    },
  });
  ready = true;
}

export function Mermaid({
  code,
  className = "",
  scroll = false,
}: {
  code: string;
  className?: string;
  scroll?: boolean;
}) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const wrapRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    if (!code.trim()) {
      setSvg("");
      return;
    }
    getMermaid()
      .then((mermaid) => {
        init(mermaid);
        return mermaid.render(`qta-${id}-${Date.now()}`, code);
      })
      .then(({ svg: rendered }) => {
        if (alive) {
          setSvg(rendered);
          setError("");
        }
      })
      .catch((err: unknown) => {
        if (alive) {
          setError(err instanceof Error ? err.message : String(err));
          setSvg("");
        }
      });
    return () => {
      alive = false;
    };
  }, [code, id]);

  useEffect(() => {
    if (!scroll || !svg) return;
    const svgEl = wrapRef.current?.querySelector("svg");
    if (!svgEl) return;
    const viewBox = svgEl.viewBox?.baseVal;
    if (viewBox?.width) {
      svgEl.setAttribute("width", String(Math.ceil(viewBox.width)));
      svgEl.setAttribute("height", String(Math.ceil(viewBox.height)));
      svgEl.style.maxWidth = "none";
    }
  }, [svg, scroll]);

  const content = useMemo(() => {
    if (error) return <div className="mermaid-error">图渲染失败：{error}</div>;
    if (!svg) return <div className="muted small" style={{ padding: 8 }}>正在绘制…</div>;
    return <div dangerouslySetInnerHTML={{ __html: svg }} />;
  }, [svg, error]);

  return (
    <div ref={wrapRef} className={`mermaid-wrap${scroll ? " scroll-x" : ""} ${className}`}>
      {content}
    </div>
  );
}
