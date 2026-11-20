import { useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";
import type { Slice } from "../../types";
import { Mermaid } from "../../ui/Mermaid";

export function DiagramsPanel({ slice }: { slice: Slice | null }) {
  const [raw, setRaw] = useState(false);

  if (!slice) {
    return <div className="empty"><strong>没有打开切片</strong>图表会跟随当前切片。</div>;
  }
  if (!slice.diagrams.length) {
    return (
      <div className="empty">
        <strong>这张切片没有图表</strong>
        不是每条切片都需要图；链路、时序、分区各有适用场景。模型可以选择不生成。
      </div>
    );
  }
  return (
    <div>
      <div className="panel-flat panel-body" style={{ marginBottom: 12 }}>
        <div className="row">
          <div className="grow">
            <div className="panel-title" style={{ fontSize: 16 }}>图与证据</div>
            <p className="small muted" style={{ marginTop: 4 }}>
              图由服务端从校验后的节点和边重建；虚线表示推断，不是真实调用。
            </p>
          </div>
          <button
            className="btn btn-xs"
            title={raw ? "缩放到面板宽度" : "按原始尺寸查看"}
            onClick={() => setRaw((value) => !value)}
          >
            {raw ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
            {raw ? "适应宽度" : "原始尺寸"}
          </button>
        </div>
      </div>
      {slice.diagrams.map((diagram) => (
        <div key={diagram.id} style={{ marginBottom: 14 }}>
          <div className="row" style={{ marginBottom: 6 }}>
            <span className="chip teal">{diagram.kind}</span>
            <span className="small truncate">{diagram.title}</span>
          </div>
          <Mermaid code={diagram.mermaid} scroll={raw} />
        </div>
      ))}
    </div>
  );
}
